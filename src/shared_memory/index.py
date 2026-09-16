"""The search index: sections of memories with embeddings and keyword tokens, and no readable content (ADR-0002)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from pgvector import Vector

from shared_memory.db import Conn, Database
from shared_memory.embeddings import Embedder
from shared_memory.memory import Memory, locate
from shared_memory.store import MemoryStore

_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
_RRF_K = 60
_CANDIDATES = 30

SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    team TEXT NOT NULL,
    path TEXT NOT NULL,
    section_no INT NOT NULL,
    heading TEXT NOT NULL,
    level TEXT NOT NULL,
    project_id TEXT,
    member_id TEXT,
    type TEXT NOT NULL,
    author TEXT NOT NULL,
    status TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    embedding vector(384) NOT NULL,
    tokens tsvector NOT NULL,
    PRIMARY KEY (team, path, section_no)
);
CREATE INDEX IF NOT EXISTS sections_tokens ON sections USING GIN (tokens);
"""


@dataclass(frozen=True)
class Hit:
    path: str
    heading: str
    level: str
    project_id: str | None
    member_id: str | None
    type: str
    author: str
    similarity: float
    keyword: bool


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

    def update(self, team: str, path: PurePosixPath, memory: Memory) -> None:
        location = locate(str(path))
        texts = [f"{memory.title}\n{heading}\n{text}" for heading, text in split_sections(memory)]
        headings = [heading for heading, _ in split_sections(memory)]
        hashes = [hashlib.sha256(text.encode()).hexdigest() for text in texts]
        with self._db.transaction() as conn:
            existing = {
                row["section_no"]: row["content_hash"]
                for row in conn.execute(
                    "SELECT section_no, content_hash FROM sections WHERE team = %s AND path = %s", (team, str(path))
                )
            }
            changed = [n for n, digest in enumerate(hashes) if existing.get(n) != digest]
            vectors = dict(zip(changed, self._embedder.passages([texts[n] for n in changed]), strict=True))
            conn.execute(
                "DELETE FROM sections WHERE team = %s AND path = %s AND section_no >= %s", (team, str(path), len(texts))
            )
            for n, text in enumerate(texts):
                details = (headings[n], location.level, location.project_id, location.member_id, memory.type, memory.author, memory.status)
                if n in vectors:
                    conn.execute(
                        "INSERT INTO sections (team, path, section_no, heading, level, project_id, member_id, type,"
                        " author, status, content_hash, embedding, tokens)"
                        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                        " setweight(to_tsvector('simple', %s), 'A') || to_tsvector('english', %s))"
                        " ON CONFLICT (team, path, section_no) DO UPDATE SET heading = EXCLUDED.heading,"
                        " level = EXCLUDED.level, project_id = EXCLUDED.project_id, member_id = EXCLUDED.member_id,"
                        " type = EXCLUDED.type, author = EXCLUDED.author, status = EXCLUDED.status,"
                        " content_hash = EXCLUDED.content_hash, embedding = EXCLUDED.embedding, tokens = EXCLUDED.tokens",
                        (team, str(path), n, *details, hashes[n], Vector(vectors[n]), text, text),
                    )
                else:
                    conn.execute(
                        "UPDATE sections SET heading = %s, level = %s, project_id = %s, member_id = %s, type = %s,"
                        " author = %s, status = %s WHERE team = %s AND path = %s AND section_no = %s",
                        (*details, team, str(path), n),
                    )

    def remove(self, team: str, path: PurePosixPath) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM sections WHERE team = %s AND path = %s", (team, str(path)))

    def on_change(self, team: str, writes: dict[PurePosixPath, Memory], deletes: Iterable[PurePosixPath]) -> None:
        for path in deletes:
            self.remove(team, path)
        for path, memory in writes.items():
            self.update(team, path, memory)

    def rebuild(self, store: MemoryStore) -> int:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM sections")
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
        project_id: str,
        member_id: str | None = None,
        levels: Iterable[str] | None = None,
        type: str | None = None,
        limit: int = 10,
    ) -> list[Hit]:
        """Active sections visible from a project, ranked by meaning and exact words together.

        member_id, when given, limits personal memory to that member's own.
        """
        conditions = ["team = %(team)s", "status = 'active'", "(level = 'team' OR project_id = %(project)s)"]
        params: dict[str, object] = {"team": team, "project": project_id, "text": query}
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
        columns = "path, section_no, heading, level, project_id, member_id, type, author, 1 - (embedding <=> %(query)s) AS similarity"
        with self._db.transaction() as conn:
            by_meaning = conn.execute(
                f"SELECT {columns} FROM sections WHERE {where} ORDER BY embedding <=> %(query)s LIMIT {_CANDIDATES}",
                params,
            ).fetchall()
            by_words = self._keyword(conn, columns, where, params)
        scores: dict[tuple[str, int], float] = {}
        rows: dict[tuple[str, int], dict[str, object]] = {}
        keyword_keys = set()
        for ranking, is_keyword in ((by_meaning, False), (by_words, True)):
            for rank, row in enumerate(ranking):
                key = (row["path"], row["section_no"])
                scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
                rows[key] = row
                if is_keyword:
                    keyword_keys.add(key)
        ordered = sorted(scores, key=lambda key: (-scores[key], -float(str(rows[key]["similarity"]))))
        return [
            Hit(
                path=str(rows[key]["path"]),
                heading=str(rows[key]["heading"]),
                level=str(rows[key]["level"]),
                project_id=None if rows[key]["project_id"] is None else str(rows[key]["project_id"]),
                member_id=None if rows[key]["member_id"] is None else str(rows[key]["member_id"]),
                type=str(rows[key]["type"]),
                author=str(rows[key]["author"]),
                similarity=float(str(rows[key]["similarity"])),
                keyword=key in keyword_keys,
            )
            for key in ordered[:limit]
        ]

    @staticmethod
    def _keyword(conn: Conn, columns: str, where: str, params: dict[str, object]) -> list[dict[str, object]]:
        return conn.execute(
            f"SELECT {columns}, ts_rank_cd(tokens, q.tq) AS rank FROM sections,"
            " (SELECT websearch_to_tsquery('simple', %(text)s) || websearch_to_tsquery('english', %(text)s) AS tq) q"
            f" WHERE {where} AND tokens @@ q.tq ORDER BY rank DESC LIMIT {_CANDIDATES}",
            params,
        ).fetchall()
