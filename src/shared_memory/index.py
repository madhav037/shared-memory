"""The search index: memory sections as embeddings and unordered keyword tokens, with no readable content (ADR-0002).

A section longer than the search model reads is indexed as several overlapping chunks, found as the one section.

Headings and text are always read back from the memory files; Postgres holds only what ranking needs.
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from pgvector import Vector

from shared_memory.db import Conn, Database, moved_prefix
from shared_memory.embeddings import DIMENSIONS, MAX_TOKENS, CachedQueries, QuerySource
from shared_memory.memory import Memory, locate
from shared_memory.store import MemoryStore

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_RRF_K = 60
_CANDIDATES = 30
_SIMILAR_LIMIT = 10
# Promote's check takes this many nearest sections for each of the memory's own, then keeps the memories they belong to.
_SIMILAR_CANDIDATES = 40
# A section longer than the model reads is split into chunks of about this many tokens, each overlapping the one
# before it, so a sentence cut at a chunk's edge is still read whole in its neighbour.
_CHUNK_TOKENS = 256
_CHUNK_OVERLAP = 48
# Vectors computed before a save's turn wait here for the turn to take them; the oldest go first past this many.
_PREPARED_LIMIT = 512

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS sections (
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    section_no INT NOT NULL,
    chunk_no INT NOT NULL,
    level TEXT NOT NULL,
    project_id TEXT,
    member_id TEXT,
    type TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding vector({DIMENSIONS}) NOT NULL,
    tokens tsvector NOT NULL,
    PRIMARY KEY (team, path, section_no, chunk_no)
);
ALTER TABLE sections DROP COLUMN IF EXISTS heading;
-- Set on department memory alone (ADR-0032), so a search keeps it to the departments of the projects it reaches.
ALTER TABLE sections ADD COLUMN IF NOT EXISTS department_id TEXT;
CREATE INDEX IF NOT EXISTS sections_tokens ON sections USING GIN (tokens);
CREATE INDEX IF NOT EXISTS sections_content_hash ON sections (team, content_hash);
"""
# Nearest sections by meaning come from an approximate-nearest-neighbour index rather than a comparison with every one.
_EMBEDDING_INDEX = "CREATE INDEX IF NOT EXISTS sections_embedding ON sections USING hnsw (embedding vector_cosine_ops)"
# The index hands out the nearest sections and a query's filters (company, status, level, project) drop the ones it can't
# see. Scanning on until enough have passed keeps a company's memories findable among every other company's. The scan may
# hand them out a little out of order (a stricter order skips sections it reaches late), so a query sorts them again.
_NEAREST = "SET LOCAL hnsw.iterative_scan = relaxed_order; SET LOCAL hnsw.ef_search = {ef}"


@dataclass(frozen=True)
class Hit:
    path: str
    section_no: int
    level: str
    member_id: str | None
    type: str
    author: str
    similarity: float
    # Whether the section has the words searched for, not only something close to them in meaning.
    words_match: bool = False
    # How it ranked, by meaning and exact words together: the higher, the better the match.
    score: float = 0.0


@dataclass(frozen=True)
class Reach:
    """The memory a search for similar memories may name: company memory if `company_memory`; the department memory of
    `departments`, or of every department when `departments` is None; the project memory of `projects`, or of every
    project but `unreachable` when `projects` is None; and the personal memory of `member_id` in `personal_in`, never
    any other member's."""

    company_memory: bool = False
    projects: tuple[str, ...] | None = ()
    unreachable: frozenset[str] = frozenset()
    member_id: str | None = None
    personal_in: str | None = None
    departments: tuple[str, ...] | None = ()

    @classmethod
    def project_memory_of(cls, project_id: str) -> Reach:
        """One project's project memory alone."""
        return cls(projects=(project_id,))

    @classmethod
    def of_member(cls, member_id: str, project_id: str, unreachable: frozenset[str]) -> Reach:
        """What a member's save is compared with: their own personal memory in the project they work in, plus the
        company memory, every department's memory and the project memory of every project they can reach."""
        return cls(
            company_memory=True,
            projects=None,
            unreachable=unreachable,
            member_id=member_id,
            personal_in=project_id,
            departments=None,
        )

    @classmethod
    def of_recall(cls, member_id: str, project_id: str, department_id: str | None = None) -> Reach:
        """What recall searches for a member's session: company memory, the department memory of the project's
        department if it has one, the project memory of the project the session works in, and the member's own
        personal memory there."""
        departments = () if department_id is None else (department_id,)
        return cls(
            company_memory=True,
            projects=(project_id,),
            member_id=member_id,
            personal_in=project_id,
            departments=departments,
        )

    def where(self) -> tuple[str, dict[str, object]]:
        """This reach as a condition on `sections`, with the parameters it binds."""
        if self.projects is None:
            projects = "NOT (project_id = ANY(%(reach_unreachable)s))"
        else:
            projects = "project_id = ANY(%(reach_projects)s)"
        if self.departments is None:
            departments = "level = 'department'"
        else:
            departments = "(level = 'department' AND department_id = ANY(%(reach_departments)s))"
        condition = (
            f"((level = 'company' AND %(reach_company)s) OR {departments} OR (level = 'project' AND {projects})"
            " OR (level = 'personal' AND member_id = %(reach_member)s AND project_id = %(reach_personal_in)s))"
        )
        return condition, {
            "reach_company": self.company_memory,
            "reach_departments": list(self.departments or ()),
            "reach_projects": list(self.projects or ()),
            "reach_unreachable": sorted(self.unreachable),
            "reach_member": self.member_id,
            "reach_personal_in": self.personal_in,
        }


def split_sections(memory: Memory) -> list[tuple[str, str]]:
    """A memory's sections: the part before the first heading, then one section per Markdown heading."""
    sections: list[tuple[str, str]] = []
    heading, lines = memory.title, [memory.summary]
    for line in memory.body.splitlines():
        match = _HEADING.match(line)
        if match:
            sections.append((heading, "\n".join(lines).strip()))
            heading, lines = match.group(1), []
        else:
            lines.append(line)
    sections.append((heading, "\n".join(lines).strip()))
    return [sections[0], *(section for section in sections[1:] if section[1])]


class SearchIndex:
    def __init__(self, db: Database, embedder: CachedQueries) -> None:
        self._db = db
        self._embedder = embedder
        self._prepared: OrderedDict[str, list[float]] = OrderedDict()
        self._prepared_lock = threading.Lock()
        self._unchunked = False
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)
                # Indexing a database that already holds many sections takes longer than any request is allowed.
                conn.execute("SET LOCAL statement_timeout = 0")
                conn.execute(_EMBEDDING_INDEX)
                conn.execute("RESET statement_timeout")
                conn.execute("LOCK TABLE sections IN ACCESS EXCLUSIVE MODE")
                self._unchunked = (
                    conn.execute(
                        "SELECT 1 FROM information_schema.columns WHERE table_schema = current_schema()"
                        " AND table_name = 'sections' AND column_name = 'chunk_no'"
                    ).fetchone()
                    is None
                )
                if self._unchunked:
                    # Built before long sections were split: every section so far is its own first chunk.
                    conn.execute(
                        "ALTER TABLE sections ADD COLUMN chunk_no INT NOT NULL DEFAULT 0, DROP CONSTRAINT sections_pkey,"
                        " ADD PRIMARY KEY (team, path, section_no, chunk_no)"
                    )
                    conn.execute("ALTER TABLE sections ALTER COLUMN chunk_no DROP DEFAULT")

    def catch_up(self, store: MemoryStore) -> None:
        """Index every memory again if the index was built before long sections were split into chunks.

        Sections short enough to have been read whole keep their embeddings; only long ones are embedded again.
        """
        if self._unchunked:
            self._update_all(store)
            self._unchunked = False

    def _chunks(self, title: str, heading: str, text: str) -> list[str]:
        """The texts embedded for one section: the whole of it, or overlapping chunks the model reads whole."""
        prefix = f"{title}\n{heading}\n"
        words = list(re.finditer(r"\S+", text))
        counts = self._embedder.tokens([word.group() for word in words])
        room = MAX_TOKENS - 2 - sum(self._embedder.tokens(prefix.split()))
        if sum(counts) <= room:
            return [prefix + text]
        budget = max(_CHUNK_OVERLAP * 2, min(_CHUNK_TOKENS, room))
        chunks: list[str] = []
        start = 0
        while True:
            end, used = start + 1, counts[start]
            while end < len(words) and used + counts[end] <= budget:
                used += counts[end]
                end += 1
            chunks.append(prefix + text[words[start].start() : words[end - 1].end()])
            if end == len(words):
                return chunks
            first, start, overlap = start, end, 0
            while start - 1 > first and overlap + counts[start - 1] <= _CHUNK_OVERLAP:
                start -= 1
                overlap += counts[start]

    def update(self, company: str, path: PurePosixPath, memory: Memory) -> None:
        with self._db.transaction() as conn:
            self._update(conn, company, path, memory)

    def _plan(self, memory: Memory) -> tuple[dict[tuple[int, int], str], dict[tuple[int, int], str]]:
        """The texts embedded for a memory and the content hash of each, by (section, chunk)."""
        texts = {
            (section_no, chunk_no): chunk
            for section_no, (heading, text) in enumerate(split_sections(memory))
            for chunk_no, chunk in enumerate(self._chunks(memory.title, heading, text))
        }
        return texts, {key: hashlib.sha256(text.encode()).hexdigest() for key, text in texts.items()}

    @staticmethod
    def _stored_vectors(conn: Conn, company: str, hashes: Iterable[str]) -> dict[str, list[float]]:
        """The vectors sections in this company already hold for text with these content hashes."""
        wanted = list(set(hashes))
        if not wanted:
            return {}
        rows = conn.execute(
            "SELECT DISTINCT ON (content_hash) content_hash, embedding FROM sections"
            " WHERE team = %s AND content_hash = ANY(%s)",
            (company, wanted),
        )
        return {row["content_hash"]: row["embedding"].to_list() for row in rows}

    def prepare(self, company: str, memory: Memory) -> None:
        """Embed a memory's text ahead of the save that will index it, so the save's turn runs no model.

        Text the company's index already holds vectors for is left alone. What is computed waits, bounded, for the save.
        """
        texts, hashes = self._plan(memory)
        with self._prepared_lock:
            wanted = {digest: texts[key] for key, digest in hashes.items() if digest not in self._prepared}
        if not wanted:
            return
        with self._db.transaction() as conn:
            wanted = {d: t for d, t in wanted.items() if d not in self._stored_vectors(conn, company, wanted)}
        if not wanted:
            return
        vectors = self._embedder.passages(list(wanted.values()))
        with self._prepared_lock:
            for digest, vector in zip(wanted, vectors, strict=True):
                self._prepared[digest] = vector
                self._prepared.move_to_end(digest)
            while len(self._prepared) > _PREPARED_LIMIT:
                self._prepared.popitem(last=False)

    def _update(
        self,
        conn: Conn,
        company: str,
        path: PurePosixPath,
        memory: Memory,
        known: dict[str, list[float]] | None = None,
    ) -> None:
        location = locate(str(path))
        texts, hashes = self._plan(memory)
        details = (
            location.level,
            location.project_id,
            location.member_id,
            location.department_id,
            memory.type,
            memory.author,
            memory.status,
        )
        existing = {
            (row["section_no"], row["chunk_no"]): row["content_hash"]
            for row in conn.execute(
                "SELECT section_no, chunk_no, content_hash FROM sections WHERE team = %s AND path = %s",
                (company, str(path)),
            )
        }
        changed = [key for key, digest in hashes.items() if existing.get(key) != digest]
        by_hash = {hashes[key]: texts[key] for key in changed}
        found: dict[str, list[float]] = {}
        with self._prepared_lock:
            for digest in by_hash:
                if digest in self._prepared:
                    # Left for another save of the same text in another area, running at the same time.
                    found[digest] = self._prepared[digest]
                    self._prepared.move_to_end(digest)
        if known is None:
            known = self._stored_vectors(conn, company, [d for d in by_hash if d not in found])
        found.update({d: v for d, v in known.items() if d in by_hash and d not in found})
        missing = [d for d in by_hash if d not in found]
        if missing:
            # Only reached when nothing prepared the vectors and no section holds them: embed inside the turn.
            found.update(zip(missing, self._embedder.passages([by_hash[d] for d in missing]), strict=True))
        vectors = {key: found[hashes[key]] for key in changed}
        for section_no, chunk_no in existing.keys() - texts.keys():
            conn.execute(
                "DELETE FROM sections WHERE team = %s AND path = %s AND section_no = %s AND chunk_no = %s",
                (company, str(path), section_no, chunk_no),
            )
        for (section_no, chunk_no), text in texts.items():
            if (section_no, chunk_no) in vectors:
                conn.execute(
                    "INSERT INTO sections (team, path, section_no, chunk_no, level, project_id, member_id,"
                    " department_id, type, author, status, content_hash, embedding, tokens)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " strip(to_tsvector('simple', %s) || to_tsvector('english', %s)))"
                    " ON CONFLICT (team, path, section_no, chunk_no) DO UPDATE SET level = EXCLUDED.level,"
                    " project_id = EXCLUDED.project_id, member_id = EXCLUDED.member_id,"
                    " department_id = EXCLUDED.department_id, type = EXCLUDED.type,"
                    " author = EXCLUDED.author, status = EXCLUDED.status, content_hash = EXCLUDED.content_hash,"
                    " embedding = EXCLUDED.embedding, tokens = EXCLUDED.tokens",
                    (
                        company,
                        str(path),
                        section_no,
                        chunk_no,
                        *details,
                        hashes[(section_no, chunk_no)],
                        Vector(vectors[(section_no, chunk_no)]),
                        text,
                        text,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE sections SET level = %s, project_id = %s, member_id = %s, department_id = %s, type = %s,"
                    " author = %s, status = %s WHERE team = %s AND path = %s AND section_no = %s AND chunk_no = %s",
                    (*details, company, str(path), section_no, chunk_no),
                )

    @contextmanager
    def on_change(
        self, company: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> Iterator[None]:
        """Index a save in one transaction, which commits only once the save has landed everywhere else."""
        with self._db.transaction() as conn:
            # Read before the deletes: a memory that moved keeps its text, so its old rows hold the vectors it needs.
            known = self._stored_vectors(
                conn, company, (digest for memory in writes.values() for digest in self._plan(memory)[1].values())
            )
            for path in deletes:
                conn.execute("DELETE FROM sections WHERE team = %s AND path = %s", (company, str(path)))
            for path, memory in writes.items():
                self._update(conn, company, path, memory, known)
            yield

    def rebuild(self, store: MemoryStore) -> int:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM sections")
        return self._update_all(store)

    def _update_all(self, store: MemoryStore) -> int:
        count = 0
        for company in store.companies():
            for _, memories in store.walk(company, PurePosixPath()):
                for path, memory in memories:
                    self.update(company, path, memory)
                    count += 1
        return count

    def search(
        self,
        company: str,
        query: str,
        *,
        project_id: str | list[str],
        departments: Iterable[str] = (),
        member_id: str | None = None,
        levels: Iterable[str] | None = None,
        type: str | None = None,
        limit: int | None = 10,
        source: QuerySource,
    ) -> list[Hit]:
        """Active sections visible from a project, or from several, ranked by meaning and exact words together.

        limit None returns every candidate, for a caller that ranks them again before it cuts them: at most
        `_CANDIDATES` found by meaning and `_CANDIDATES` by exact words, so never more than twice that. member_id, when
        given, limits personal memory to that member's own. Department memory is searched only for `departments`, the
        departments of those projects. `source` is where the query came from, for the query cache's counts.
        """
        projects = [project_id] if isinstance(project_id, str) else list(project_id)
        conditions = [
            "team = %(company)s",
            "status = 'active'",
            "(level = 'company' OR (level = 'department' AND department_id = ANY(%(departments)s))"
            " OR project_id = ANY(%(projects)s))",
        ]
        params: dict[str, object] = {
            "company": company,
            "projects": projects,
            "departments": list(departments),
            "text": query,
        }
        if member_id is not None:
            conditions.append("(level <> 'personal' OR member_id = %(member)s)")
            params["member"] = member_id
        if levels is not None:
            conditions.append("level = ANY(%(levels)s)")
            params["levels"] = list(levels)
        if type is not None:
            conditions.append("type = %(type)s")
            params["type"] = type
        params["query"] = Vector(self._embedder.query(query, source))
        where = " AND ".join(conditions)
        columns = "path, section_no, level, member_id, type, author, 1 - (embedding <=> %(query)s) AS similarity"
        with self._db.transaction() as conn:
            conn.execute(_NEAREST.format(ef=_CANDIDATES))
            by_meaning = conn.execute(
                f"WITH nearest AS MATERIALIZED (SELECT {columns} FROM sections WHERE {where}"  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
                f" ORDER BY embedding <=> %(query)s LIMIT {_CANDIDATES})"
                " SELECT * FROM nearest ORDER BY similarity DESC",
                params,
            ).fetchall()
            by_words = self._keyword(conn, columns, where, params)
        worded = {(row["path"], row["section_no"]) for row in by_words}
        scores: dict[tuple[str, int], float] = {}
        rows: dict[tuple[str, int], dict[str, Any]] = {}
        for ranking in (by_meaning, by_words):
            # A long section's chunks each rank on their own; the section takes its best-ranked chunk's place.
            sections = list(dict.fromkeys((row["path"], row["section_no"]) for row in ranking))
            for rank, key in enumerate(sections):
                scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            for row in ranking:
                key = (row["path"], row["section_no"])
                if key not in rows or row["similarity"] > rows[key]["similarity"]:
                    rows[key] = row
        ordered = sorted(scores, key=lambda key: (-scores[key], -float(rows[key]["similarity"])))
        return [
            Hit(
                path=rows[key]["path"],
                section_no=rows[key]["section_no"],
                level=rows[key]["level"],
                member_id=rows[key]["member_id"],
                type=rows[key]["type"],
                author=rows[key]["author"],
                similarity=float(rows[key]["similarity"]),
                words_match=key in worded,
                score=scores[key],
            )
            for key in ordered[:limit]
        ]

    def similar(
        self, company: str, path: PurePosixPath, *, project_id: str, threshold: float, department_id: str | None = None
    ) -> list[tuple[str, float]]:
        """Active project, department and company memories whose sections come close in meaning to any section of this
        memory: company memory, the department memory of `department_id` and the project memory of `project_id`."""
        with self._db.transaction() as conn:
            conn.execute(_NEAREST.format(ef=_SIMILAR_CANDIDATES))
            rows = conn.execute(
                "SELECT c.path, MAX(c.similarity) AS similarity FROM sections s CROSS JOIN LATERAL ("  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
                " SELECT n.path, 1 - (n.embedding <=> s.embedding) AS similarity FROM sections n"
                " WHERE n.team = s.team AND n.path <> s.path AND n.status = 'active'"
                " AND (n.level = 'company' OR (n.level = 'project' AND n.project_id = %(project)s)"
                " OR (n.level = 'department' AND n.department_id = %(department)s))"
                f" ORDER BY n.embedding <=> s.embedding LIMIT {_SIMILAR_CANDIDATES}) c"
                " WHERE s.team = %(company)s AND s.path = %(path)s"
                " GROUP BY c.path HAVING MAX(c.similarity) >= %(threshold)s"
                f" ORDER BY similarity DESC LIMIT {_SIMILAR_LIMIT}",
                {
                    "company": company,
                    "path": str(path),
                    "project": project_id,
                    "department": department_id,
                    "threshold": threshold,
                },
            ).fetchall()
        return [(str(row["path"]), float(row["similarity"])) for row in rows]

    def similar_to(
        self, company: str, memory: Memory, *, reach: Reach, threshold: float, excluding: PurePosixPath | None = None
    ) -> list[tuple[str, float]]:
        """Active memories within a reach whose sections come close in meaning to any section of a memory, most
        similar first: one not yet saved, such as a known issue about to land, or one just saved, left out by
        `excluding`. Vectors come from what was prepared or stored, so the model runs only for text never seen."""
        texts, hashes = self._plan(memory)
        found: dict[str, list[float]] = {}
        with self._prepared_lock:
            for digest in hashes.values():
                if digest in self._prepared:
                    found[digest] = self._prepared[digest]
        with self._db.transaction() as conn:
            found.update(self._stored_vectors(conn, company, [d for d in hashes.values() if d not in found]))
        missing = {digest: texts[key] for key, digest in hashes.items() if digest not in found}
        if missing:
            found.update(zip(missing, self._embedder.passages(list(missing.values())), strict=True))
        within, params = reach.where()
        params = {**params, "company": company, "excluding": None if excluding is None else str(excluding)}
        best: dict[str, float] = {}
        with self._db.transaction() as conn:
            conn.execute(_NEAREST.format(ef=_SIMILAR_CANDIDATES))
            for vector in {digest: found[digest] for digest in hashes.values()}.values():
                rows = conn.execute(
                    "SELECT path, 1 - (embedding <=> %(vector)s) AS similarity FROM sections"  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
                    f" WHERE team = %(company)s AND status = 'active' AND {within}"
                    " AND path IS DISTINCT FROM %(excluding)s"
                    f" ORDER BY embedding <=> %(vector)s LIMIT {_SIMILAR_CANDIDATES}",
                    {**params, "vector": Vector(vector)},
                ).fetchall()
                for row in rows:
                    best[str(row["path"])] = max(best.get(str(row["path"]), -1.0), float(row["similarity"]))
        close = sorted(((path, s) for path, s in best.items() if s >= threshold), key=lambda item: -item[1])
        return close[:_SIMILAR_LIMIT]

    @staticmethod
    def _keyword(conn: Conn, columns: str, where: str, params: dict[str, object]) -> list[dict[str, Any]]:
        return conn.execute(
            f"SELECT {columns}, ts_rank(tokens, q.tq) AS rank FROM sections,"  # noqa: S608  # values are bound as parameters; only clauses the code builds are spliced in
            " (SELECT websearch_to_tsquery('simple', %(text)s) || websearch_to_tsquery('english', %(text)s) AS tq) q"
            f" WHERE {where} AND tokens @@ q.tq ORDER BY rank DESC LIMIT {_CANDIDATES}",
            params,
        ).fetchall()


def move_paths(conn: Conn, old: str, new: str) -> None:
    """Index the memories under the folder `old` at the folder `new`, where they moved (`company_move.py`): their
    sections are the same, so nothing is embedded again."""
    conn.execute(
        "UPDATE sections SET path = %(new)s || substr(path, %(after)s) WHERE path LIKE %(old)s", moved_prefix(old, new)
    )


def rename_level(conn: Conn, old: str, new: str) -> None:
    """Say the level `old` as `new` in the indexed sections: company memory's level was `team` before the
    rename (`company_move.py`)."""
    conn.execute("UPDATE sections SET level = %s WHERE level = %s", (new, old))
