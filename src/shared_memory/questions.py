"""Questions (#568): what a member asks a memory's author about that memory, and the thread its answers form.

A member's session asks about a memory it can read, written by someone else; the question reaches the author's next
briefing as a notice. Anyone who can read the memory may answer, its author first of all, and the answers form a thread
read with the memory by anyone who can read it, and by nobody else. The asker is told of each answer, and the author of
each answer they didn't write. A question is open until someone other than its asker answers it. A question and its
answers are not memory (ADR-0014, ADR-0028): the memory folder holds neither, and the audit log records each, never
its text.

Kept in Postgres, so every worker agrees (ADR-0013):

- `questions`: one row per question, with the memory's path, its asker, its text, who it is routed to (the memory's
  author; the project's leads or the team's admins once it is passed on), and whether it is open or answered.
- `answers`: one row per answer, with its question, its author and its text.

What other modules stand on, all of it on `Questions`:

- `ask(caller, path, text)`: ask the author of a memory the caller can read; its question ID and the author.
- `answer(caller, question_id, text)`: answer a question about a memory the caller can read.
- `on(caller, path)`: the memory's threads, oldest first, and how many are open: what a read of it carries.
- `pass_on(caller)`: pass on the team's questions now due (#569), before a briefing is composed.

A question its author has left unanswered for `PASS_ON_DAYS`, or whose author has been removed, is passed on to the
memory's project leads (the team's owner and admins where it has none), or for team memory to the team's admins. There
is no scheduler: it is worked out from the clock whenever questions are read, as a session's activity is (ADR-0018),
and each question is passed on once. The author may still answer it, and so may anyone else who can read the memory.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Literal

from shared_memory.audit import QUESTION_ANSWERED, QUESTION_ASKED, Audit
from shared_memory.clock import Clock
from shared_memory.db import Database
from shared_memory.errors import Refused
from shared_memory.fence import escape
from shared_memory.identity import Caller, Identity
from shared_memory.memory import Location, locate
from shared_memory.messages import TEXT_LIMIT
from shared_memory.store import MemoryStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id BIGSERIAL PRIMARY KEY,
    team TEXT NOT NULL,
    memory_path TEXT NOT NULL,
    asker_id BIGINT NOT NULL REFERENCES members(id),
    text TEXT NOT NULL,
    asked_at TIMESTAMPTZ NOT NULL,
    -- Who the question is for: the memory's author, or once passed on its project's leads or the team's admins.
    routed_to TEXT NOT NULL DEFAULT 'author',
    routed_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL DEFAULT 'open'
);
CREATE INDEX IF NOT EXISTS questions_by_memory ON questions (team, memory_path, id);
CREATE TABLE IF NOT EXISTS answers (
    id BIGSERIAL PRIMARY KEY,
    question_id BIGINT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    author_id BIGINT NOT NULL REFERENCES members(id),
    text TEXT NOT NULL,
    answered_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS answers_by_question ON answers (question_id, id);
-- The memory's author when the question was asked, by member ID, so that a removed author's questions are passed on.
ALTER TABLE questions ADD COLUMN IF NOT EXISTS author TEXT;
"""

# How long a question waits for its author before it is passed on to the memory's project leads or the team's admins.
PASS_ON_DAYS = 7

# Passes on the team's open questions now due, each once: still with their author, and asked `PASS_ON_DAYS` ago or by
# now about a removed author's memory.
PASSED_ON = """
UPDATE questions q SET routed_to = CASE WHEN q.memory_path LIKE 'projects/%%' THEN 'leads' ELSE 'admins' END,
    routed_at = %(now)s
WHERE q.team = %(team)s AND q.state = 'open' AND q.routed_to = 'author' AND (q.asked_at <= %(due)s OR EXISTS (
    SELECT 1 FROM members m WHERE m.team_id = %(team_pk)s AND m.member_id = q.author AND m.removed_at IS NOT NULL
))
RETURNING q.id, q.memory_path, q.asker_id, q.author, q.text, EXISTS (
    SELECT 1 FROM members m WHERE m.team_id = %(team_pk)s AND m.member_id = q.author AND m.removed_at IS NOT NULL
) AS removed
"""

State = Literal["open", "answered"]


class Questions:
    def __init__(
        self,
        db: Database,
        store: MemoryStore,
        identity: Identity,
        audit: Audit,
        clock: Clock,
        tell: Callable[[str, str, str], None],
    ) -> None:
        self._db = db
        self._store = store
        self._identity = identity
        self._audit = audit
        self._clock = clock
        self._tell = tell
        if db.sets_up:
            with db.transaction() as conn:
                conn.execute(SCHEMA)

    def ask(self, caller: Caller, path: str, text: str) -> dict[str, Any]:
        """Ask the author of a memory the caller can read about it; the author's next briefing carries it."""
        location, author = self._readable(caller, path)
        if author == caller.member_id:
            raise Refused(
                f"{location.path} is your own memory: there is no one to ask. If it is unclear, edit it in a session."
            )
        said = _text(text, "A question")
        now = self._clock()
        with self._db.transaction() as conn:
            row = conn.execute(
                "INSERT INTO questions (team, memory_path, asker_id, author, text, asked_at, routed_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (caller.team, str(location.path), caller.member.pk, author, said, now, now),
            ).fetchone()
        assert row is not None
        question_id = int(row["id"])
        self._audit.memory(
            caller, QUESTION_ASKED, str(location.path), project_id=location.project_id, question_id=question_id
        )
        if self._reaches(caller, location.project_id, author):
            self._tell(
                caller.team,
                author,
                f"{_who(caller)} asked about your memory {location.path} (question {question_id}): "
                f'"{escape(said)}" Show it to the member, and send their answer with answer_question.',
            )
        return {"question_id": question_id, "path": str(location.path), "author": author}

    def answer(self, caller: Caller, question_id: int, text: str) -> dict[str, Any]:
        """Answer a question about a memory the caller can read. The asker is told, and so is the memory's author when
        someone else answered."""
        with self._db.transaction() as conn:
            found = conn.execute(
                "SELECT memory_path, state, asker_id FROM questions WHERE id = %s AND team = %s",
                (question_id, caller.team),
            ).fetchone()
        if found is None:
            raise Refused(f"There is no question {question_id} in your team.")
        location, author = self._readable(caller, found["memory_path"])
        said = _text(text, "An answer")
        asker = self._identity.named([found["asker_id"]])[found["asker_id"]][0]
        with self._db.transaction() as conn:
            conn.execute(
                "INSERT INTO answers (question_id, author_id, text, answered_at) VALUES (%s, %s, %s, %s)",
                (question_id, caller.member.pk, said, self._clock()),
            )
            if caller.member_id != asker:
                conn.execute("UPDATE questions SET state = 'answered' WHERE id = %s", (question_id,))
        self._audit.memory(
            caller, QUESTION_ANSWERED, str(location.path), project_id=location.project_id, question_id=question_id
        )
        quoted = f'"{escape(said)}"'
        if caller.member_id != asker and self._reaches(caller, location.project_id, asker):
            self._tell(
                caller.team,
                asker,
                f"{_who(caller)} answered your question {question_id} about {location.path}: {quoted}",
            )
        if caller.member_id != author and author != asker and self._reaches(caller, location.project_id, author):
            self._tell(
                caller.team,
                author,
                f"{_who(caller)} answered question {question_id} about your memory {location.path}: {quoted}",
            )
        state: State = "answered" if caller.member_id != asker else found["state"]
        return {"question_id": question_id, "path": str(location.path), "state": state}

    def pass_on(self, caller: Caller) -> None:
        """Pass on every open question in the caller's team that its author has left unanswered for `PASS_ON_DAYS`, or
        whose author has been removed: the memory's project leads are told, or for team memory the team's admins. Each
        question is passed on once, by whichever read finds it due first."""
        now = self._clock()
        with self._db.transaction() as conn:
            due = conn.execute(
                PASSED_ON,
                {
                    "now": now,
                    "team": caller.team,
                    "team_pk": caller.member.team_pk,
                    "due": now - timedelta(days=PASS_ON_DAYS),
                },
            ).fetchall()
            if not due:
                return
            askers = self._identity.named_in(conn, [row["asker_id"] for row in due])
            authors = {
                row["member_id"]: row["name"]
                for row in conn.execute(
                    "SELECT member_id, name FROM members WHERE team_id = %s AND member_id = ANY(%s)",
                    (caller.member.team_pk, [row["author"] for row in due if row["author"] is not None]),
                )
            }
            told: list[tuple[str, str]] = []
            for row in sorted(due, key=lambda each: int(each["id"])):
                location = locate(row["memory_path"])
                if location.project_id is None:
                    standing, hearing = (
                        "one of the team's admins",
                        self._identity.admins_in(conn, caller.member.team_pk),
                    )
                else:
                    standing = "a lead of its project"
                    hearing = self._identity.told_about(conn, caller.member.team_pk, location.project_id)
                asker_id, asker_name = askers[row["asker_id"]]
                author = row["author"] or "its author"
                if row["author"] is not None:
                    author = f"its author {_named(row['author'], authors.get(row['author'], row['author']))}"
                why = (
                    f"{author} has been removed"
                    if row["removed"]
                    else f"unanswered by {author} for {PASS_ON_DAYS} days"
                )
                text = (
                    f"{_named(asker_id, asker_name)} asked about {location.path} (question {row['id']}), {why}: "
                    f'"{escape(row["text"])}" It comes to you as {standing}. Show it to the member, and send an '
                    "answer with answer_question."
                )
                others = [member_id for member_id in hearing if member_id not in (asker_id, row["author"])]
                if not others:
                    # The project's only leads are the asker or the silent author: its team's admins hear instead.
                    admins = self._identity.admins_in(conn, caller.member.team_pk)
                    others = [member_id for member_id in admins if member_id not in (asker_id, row["author"])]
                told.extend((member_id, text) for member_id in others)
        for member_id, text in told:
            self._tell(caller.team, member_id, text)

    def on(self, caller: Caller, path: str) -> dict[str, Any]:
        """The threads on one memory the caller has already been let read, oldest first, and how many are open."""
        self.pass_on(caller)
        with self._db.transaction() as conn:
            asked = conn.execute(
                "SELECT id, text, asked_at, state, asker_id FROM questions WHERE team = %s AND memory_path = %s"
                " ORDER BY id",
                (caller.team, path),
            ).fetchall()
            answered = conn.execute(
                "SELECT question_id, text, answered_at, author_id FROM answers WHERE question_id = ANY(%s) ORDER BY id",
                ([row["id"] for row in asked],),
            ).fetchall()
        names = self._identity.named([*(row["asker_id"] for row in asked), *(row["author_id"] for row in answered)])
        answers: dict[int, list[dict[str, Any]]] = {}
        for row in answered:
            answers.setdefault(row["question_id"], []).append(
                {"by": _named(*names[row["author_id"]]), "at": _when(row["answered_at"]), "text": row["text"]}
            )
        threads = [
            {
                "question_id": row["id"],
                "asked_by": _named(*names[row["asker_id"]]),
                "asked_at": _when(row["asked_at"]),
                "text": row["text"],
                "state": row["state"],
                "answers": answers.get(row["id"], []),
            }
            for row in asked
        ]
        return {"open": sum(1 for each in threads if each["state"] == "open"), "threads": threads}

    def _readable(self, caller: Caller, path: str) -> tuple[Location, str]:
        """The memory's location and its author's member ID, refused unless the caller can read it."""
        caller.require_project()
        caller.require_reach(path)
        location = locate(path)
        return location, self._store.read(caller.team, location.path).author

    def _reaches(self, caller: Caller, project_id: str | None, member_id: str) -> bool:
        """Whether a member could read a memory of this project, so that they may be told what is said about it."""
        if project_id is None:
            return True
        try:
            self._identity.member_reaching(caller, project_id, member_id)
        except Refused:
            return False
        return True


def _text(value: str, what: str) -> str:
    """A question's or an answer's text as it is kept, refused when empty or too long."""
    text = value.strip()
    if not text:
        raise Refused(f"{what} can't be empty.")
    if len(text) > TEXT_LIMIT:
        raise Refused(f"{what} is {len(text)} characters; the limit is {TEXT_LIMIT}. Say what matters in fewer words.")
    return text


def _who(caller: Caller) -> str:
    return _named(caller.member_id, caller.member.name)


def _named(member_id: str, name: str) -> str:
    return f"{name} ({member_id})"


def _when(at: datetime) -> str:
    return at.isoformat()
