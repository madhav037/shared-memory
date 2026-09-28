"""The search index: memory sections as embeddings and unordered keyword tokens, with no readable content (ADR-0002).

A section longer than the search model reads is indexed as several overlapping chunks, found as the one section.

Headings and text are always read back from the memory files; Postgres holds only what ranking needs.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from pgvector import Vector

from shared_memory.db import Conn, Database
from shared_memory.embeddings import DIMENSIONS, MAX_TOKENS, Embedder
from shared_memory.memory import Memory, locate
from shared_memory.store import MemoryStore

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_RRF_K = 60
_CANDIDATES = 30
_SIMILAR_LIMIT = 10
# A section longer than the model reads is split into chunks of about this many tokens, each overlapping the one
# before it, so a sentence cut at a chunk's edge is still read whole in its neighbour.
_CHUNK_TOKENS = 256
_CHUNK_OVERLAP = 48

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
CREATE INDEX IF NOT EXISTS sections_tokens ON sections USING GIN (tokens);
"""


@dataclass(frozen=True)
class Hit:
    path: str
    section_no: int
    level: str
    member_id: str | None
    type: str
    author: str
    similarity: float


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
    def __init__(self, db: Database, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder
        with db.transaction() as conn:
            conn.execute(SCHEMA)
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

    def update(self, team: str, path: PurePosixPath, memory: Memory) -> None:
        with self._db.transaction() as conn:
            self._update(conn, team, path, memory)

    def _update(self, conn: Conn, team: str, path: PurePosixPath, memory: Memory) -> None:
        location = locate(str(path))
        texts = {
            (section_no, chunk_no): chunk
            for section_no, (heading, text) in enumerate(split_sections(memory))
            for chunk_no, chunk in enumerate(self._chunks(memory.title, heading, text))
        }
        hashes = {key: hashlib.sha256(text.encode()).hexdigest() for key, text in texts.items()}
        details = (location.level, location.project_id, location.member_id, memory.type, memory.author, memory.status)
        existing = {
            (row["section_no"], row["chunk_no"]): row["content_hash"]
            for row in conn.execute(
                "SELECT section_no, chunk_no, content_hash FROM sections WHERE team = %s AND path = %s",
                (team, str(path)),
            )
        }
        changed = [key for key, digest in hashes.items() if existing.get(key) != digest]
        vectors = dict(zip(changed, self._embedder.passages([texts[key] for key in changed]), strict=True))
        for section_no, chunk_no in existing.keys() - texts.keys():
            conn.execute(
                "DELETE FROM sections WHERE team = %s AND path = %s AND section_no = %s AND chunk_no = %s",
                (team, str(path), section_no, chunk_no),
            )
        for (section_no, chunk_no), text in texts.items():
            if (section_no, chunk_no) in vectors:
                conn.execute(
                    "INSERT INTO sections (team, path, section_no, chunk_no, level, project_id, member_id, type,"
                    " author, status, content_hash, embedding, tokens)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " strip(to_tsvector('simple', %s) || to_tsvector('english', %s)))"
                    " ON CONFLICT (team, path, section_no, chunk_no) DO UPDATE SET level = EXCLUDED.level,"
                    " project_id = EXCLUDED.project_id, member_id = EXCLUDED.member_id, type = EXCLUDED.type,"
                    " author = EXCLUDED.author, status = EXCLUDED.status, content_hash = EXCLUDED.content_hash,"
                    " embedding = EXCLUDED.embedding, tokens = EXCLUDED.tokens",
                    (
                        team,
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
                    "UPDATE sections SET level = %s, project_id = %s, member_id = %s, type = %s, author = %s,"
                    " status = %s WHERE team = %s AND path = %s AND section_no = %s AND chunk_no = %s",
                    (*details, team, str(path), section_no, chunk_no),
                )

    @contextmanager
    def on_change(
        self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]
    ) -> Iterator[None]:
        """Index a save in one transaction, which commits only once the save has landed everywhere else."""
        with self._db.transaction() as conn:
            for path in deletes:
                conn.execute("DELETE FROM sections WHERE team = %s AND path = %s", (team, str(path)))
            for path, memory in writes.items():
                self._update(conn, team, path, memory)
            yield

    def rebuild(self, store: MemoryStore) -> int:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM sections")
        return self._update_all(store)

    def _update_all(self, store: MemoryStore) -> int:
        count = 0
        for team in store.teams():
            for _, memories in store.walk(team, PurePosixPath()):
                for path, memory in memories:
                    self.update(team, path, memory)
                    count += 1
        return count

    def search(
        self,
        team: str,
        query: str,
        *,
        project_id: str | list[str],
        member_id: str | None = None,
        levels: Iterable[str] | None = None,
        type: str | None = None,
        limit: int = 10,
    ) -> list[Hit]:
        """Active sections visible from a project, or from several, ranked by meaning and exact words together.

        member_id, when given, limits personal memory to that member's own.
        """
        projects = [project_id] if isinstance(project_id, str) else list(project_id)
        conditions = ["team = %(team)s", "status = 'active'", "(level = 'team' OR project_id = ANY(%(projects)s))"]
        params: dict[str, object] = {"team": team, "projects": projects, "text": query}
        if member_id is not None:
            conditions.append("(level <> 'personal' OR member_id = %(member)s)")
            params["member"] = member_id
        if levels is not None:
            conditions.append("level = ANY(%(levels)s)")
            params["levels"] = list(levels)
        if type is not None:
            conditions.append("type = %(type)s")
            params["type"] = type
        params["query"] = Vector(self._embedder.query(query))
        where = " AND ".join(conditions)
        columns = "path, section_no, level, member_id, type, author, 1 - (embedding <=> %(query)s) AS similarity"
        with self._db.transaction() as conn:
            by_meaning = conn.execute(
                f"SELECT {columns} FROM sections WHERE {where} ORDER BY embedding <=> %(query)s LIMIT {_CANDIDATES}",
                params,
            ).fetchall()
            by_words = self._keyword(conn, columns, where, params)
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
            )
            for key in ordered[:limit]
        ]

    def similar(self, team: str, path: PurePosixPath, *, project_id: str, threshold: float) -> list[tuple[str, float]]:
        """Active project and team memories whose sections come close in meaning to any section of this memory."""
        with self._db.transaction() as conn:
            rows = conn.execute(
                "SELECT c.path, MAX(1 - (c.embedding <=> s.embedding)) AS similarity"
                " FROM sections s JOIN sections c ON c.team = s.team AND c.path <> s.path"
                " WHERE s.team = %(team)s AND s.path = %(path)s AND c.status = 'active'"
                " AND (c.level = 'team' OR (c.level = 'project' AND c.project_id = %(project)s))"
                " GROUP BY c.path HAVING MAX(1 - (c.embedding <=> s.embedding)) >= %(threshold)s"
                f" ORDER BY similarity DESC LIMIT {_SIMILAR_LIMIT}",
                {"team": team, "path": str(path), "project": project_id, "threshold": threshold},
            ).fetchall()
        return [(str(row["path"]), float(row["similarity"])) for row in rows]

    @staticmethod
    def _keyword(conn: Conn, columns: str, where: str, params: dict[str, object]) -> list[dict[str, Any]]:
        return conn.execute(
            f"SELECT {columns}, ts_rank(tokens, q.tq) AS rank FROM sections,"
            " (SELECT websearch_to_tsquery('simple', %(text)s) || websearch_to_tsquery('english', %(text)s) AS tq) q"
            f" WHERE {where} AND tokens @@ q.tq ORDER BY rank DESC LIMIT {_CANDIDATES}",
            params,
        ).fetchall()
