"""A project's board: its cards, laid out in To do, Doing, Blocked and Done.

Cards are not memory (ADR-0014). They live in Postgres rather than the memory folder, a card's past is its audit log
entries, and moving one is a row update, not a commit. A board is reached as its project's memory is, so a restricted
project's board stays inside its access list.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from shared_memory.audit import (
    CARD_ADDED,
    CARD_CLAIMED,
    CARD_COMMENTED,
    CARD_DELETED,
    CARD_EDITED,
    CARD_MOVED,
    CARD_RETURNED,
    Audit,
)
from shared_memory.clock import Clock
from shared_memory.config import Settings
from shared_memory.db import Conn, Database
from shared_memory.errors import Refused
from shared_memory.identity import NAME_PATTERN, Caller, Identity, restricted_project
from shared_memory.memory import locate
from shared_memory.validation import CHARACTER_LIMIT

# Each column and priority as the tools take and give it, and as the board shows it to a member.
COLUMNS = {"to_do": "To do", "doing": "Doing", "blocked": "Blocked", "done": "Done"}
PRIORITIES = {"high": "High", "normal": "Normal", "low": "Low"}

TITLE_LIMIT = 200
LABEL_LIMIT = 40
# A comment is a remark on a card, smaller than its description, which is held to the memory word limit.
COMMENT_WORD_LIMIT = 150
COMMENT_CHARACTER_LIMIT = 1_500

# One card with everything it says, its creator and assignee by member ID, and its links in the order they were given.
_CARD = (
    "SELECT c.id, c.number, c.title, c.description, c.board_column, c.position, c.priority, c.labels, c.due_date,"
    " creator.member_id AS creator, assignee.member_id AS assignee, c.created_at, c.updated_at,"
    " ARRAY(SELECT l.target FROM card_links l WHERE l.card_id = c.id AND l.kind = 'memory' ORDER BY l.place)"
    " AS memories,"
    " ARRAY(SELECT l.target FROM card_links l WHERE l.card_id = c.id AND l.kind = 'file' ORDER BY l.place) AS files,"
    " ARRAY(SELECT l.target FROM card_links l WHERE l.card_id = c.id AND l.kind = 'known_issue' ORDER BY l.place)"
    " AS known_issues,"
    " COALESCE((SELECT json_agg(json_build_object('author', a.member_id, 'text', k.body, 'created_at', k.created_at)"
    " ORDER BY k.id) FROM card_comments k JOIN members a ON a.id = k.author_id WHERE k.card_id = c.id), '[]')"
    " AS comments"
    " FROM cards c JOIN members creator ON creator.id = c.creator_id"
    " LEFT JOIN members assignee ON assignee.id = c.assignee_id"
)


def _named(value: str, names: dict[str, str], what: str) -> str:
    """A column or priority as the tools take it, however a member or agent wrote it ("To do", "to-do", "to_do")."""
    key = re.sub(r"[\s-]+", "_", value.strip().lower())
    if key not in names:
        listed = list(names.values())
        raise Refused(f"{what} {value!r} is not on the board: use {', '.join(listed[:-1])} or {listed[-1]}.")
    return key


def column_named(value: str) -> str:
    return _named(value, COLUMNS, "Column")


def priority_named(value: str) -> str:
    return _named(value, PRIORITIES, "Priority")


def _title(value: str) -> str:
    title = value.strip()
    if not title:
        raise Refused("A card needs a title.")
    if "\n" in title:
        raise Refused("A card's title must be one line.")
    if len(title) > TITLE_LIMIT:
        raise Refused(f"A card's title must be at most {TITLE_LIMIT} characters.")
    return title


def _description(value: str, word_limit: int) -> str:
    """A card's description is held to the memory word limit, so a card stays something a session can read whole."""
    words = len(value.split())
    if words > word_limit:
        raise Refused(
            f"This description is {words} words; the limit is {word_limit} words. "
            "Keep the card short, and put what it needs to know in a memory linked from it."
        )
    if len(value) > CHARACTER_LIMIT:
        raise Refused(f"This description is {len(value)} characters; the limit is {CHARACTER_LIMIT} characters.")
    return value.strip()


def _labels(values: list[str]) -> list[str]:
    """Labels in lower case and each once, so the same label isn't written two ways on one board."""
    labels: list[str] = []
    for value in values:
        label = value.strip().lower()
        if not label or "\n" in label or len(label) > LABEL_LIMIT:
            raise Refused(f"Label {value!r} must be one line of 1-{LABEL_LIMIT} characters.")
        if label not in labels:
            labels.append(label)
    return labels


def _due_date(value: str) -> date | None:
    """A due date, or None for an empty one, which clears it."""
    if not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise Refused(f"Due date {value!r} must be a date written YYYY-MM-DD, such as 2026-10-15.") from None


def _memories(caller: Caller, paths: list[str]) -> list[str]:
    """Memory links, each a memory path the caller can reach."""
    linked: list[str] = []
    for path in paths:
        location = locate(path.strip())
        caller.require_reach(str(location.path))
        if str(location.path) not in linked:
            linked.append(str(location.path))
    return linked


def _files(entries: list[str]) -> list[str]:
    """File links, each written as repository:path, the way a memory's related files are."""
    linked: list[str] = []
    for entry in entries:
        repository, _, path = entry.strip().partition(":")
        if not NAME_PATTERN.match(repository) or not path.strip() or "\n" in entry:
            raise Refused(f"File {entry!r} must be written as repository:path, for example billing-api:package.json.")
        if entry.strip() not in linked:
            linked.append(entry.strip())
    return linked


def _comment(value: str) -> str:
    text = value.strip()
    if not text:
        raise Refused("A comment can't be empty.")
    words = len(text.split())
    if words > COMMENT_WORD_LIMIT:
        raise Refused(
            f"This comment is {words} words; the limit is {COMMENT_WORD_LIMIT} words. "
            "Say what matters in a few sentences, and put anything longer in a memory linked from the card."
        )
    if len(text) > COMMENT_CHARACTER_LIMIT:
        raise Refused(f"This comment is {len(text)} characters; the limit is {COMMENT_CHARACTER_LIMIT} characters.")
    return text


def _held_by(row: dict[str, Any]) -> str:
    """A card's assignee as a refusal names them."""
    return f"{row['assignee_name']} ({row['assignee']})"


def _like(text: str) -> str:
    """A pattern matching the text anywhere, with the text's own wildcards taken literally."""
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _shown(row: dict[str, Any]) -> dict[str, Any]:
    """A card as the tools give it."""
    return {
        "number": row["number"],
        "title": row["title"],
        "description": row["description"],
        "column": row["board_column"],
        "position": row["position"],
        "priority": row["priority"],
        "labels": list(row["labels"]),
        "due_date": row["due_date"].isoformat() if row["due_date"] else None,
        "creator": row["creator"],
        "assignee": row["assignee"],
        "memories": list(row["memories"]),
        "files": list(row["files"]),
        "known_issues": list(row["known_issues"]),
        "comments": list(row["comments"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


class Board:
    def __init__(self, settings: Settings, db: Database, identity: Identity, audit: Audit, clock: Clock) -> None:
        self._settings = settings
        self._db = db
        self._identity = identity
        self._audit = audit
        self._clock = clock

    @staticmethod
    def _project(caller: Caller) -> str:
        """The board a session works on: its project's, refused as the project's memory would be."""
        project_id = caller.require_project().project_id
        if project_id in caller.unreachable:
            raise restricted_project(project_id)
        return project_id

    def read(
        self,
        caller: Caller,
        column: str | None = None,
        assignee: str | None = None,
        label: str | None = None,
        priority: str | None = None,
        text: str | None = None,
    ) -> dict[str, Any]:
        """The board's cards column by column, top first, narrowed by whichever filters are given, and every label
        already on the board, to reuse rather than reword."""
        project_id = self._project(caller)
        wheres = ["c.project_id = %s"]
        values: list[Any] = [project_id]
        if column:
            wheres.append("c.board_column = %s")
            values.append(column_named(column))
        if assignee:
            wheres.append("assignee.member_id = %s")
            values.append(assignee.strip())
        if label:
            wheres.append("%s = ANY(c.labels)")
            values.append(label.strip().lower())
        if priority:
            wheres.append("c.priority = %s")
            values.append(priority_named(priority))
        if text and text.strip():
            wheres.append("(c.title ILIKE %s OR c.description ILIKE %s)")
            values += [_like(text), _like(text)]
        with self._db.transaction() as conn:
            rows = conn.execute(f"{_CARD} WHERE {' AND '.join(wheres)} ORDER BY c.position", values).fetchall()
            labels = conn.execute(
                "SELECT DISTINCT unnest(labels) AS label FROM cards WHERE project_id = %s ORDER BY label", (project_id,)
            ).fetchall()
        columns: dict[str, list[dict[str, Any]]] = {name: [] for name in COLUMNS}
        for row in rows:
            columns[row["board_column"]].append(_shown(row))
        return {"project_id": project_id, "columns": columns, "labels": [row["label"] for row in labels]}

    def add(
        self,
        caller: Caller,
        title: str,
        description: str = "",
        priority: str | None = None,
        labels: list[str] | None = None,
        due_date: str | None = None,
        memories: list[str] | None = None,
        files: list[str] | None = None,
        known_issues: list[str] | None = None,
    ) -> dict[str, Any]:
        """Add a card at the bottom of To do, numbered next in its project. known_issues are the known issues it
        fixes, linked by path as a known issue is saved."""
        project_id = self._project(caller)
        fields = {
            "title": _title(title),
            "description": _description(description, self._settings.memory_word_limit),
            "priority": priority_named(priority) if priority else "normal",
            "labels": _labels(labels or []),
            "due_date": _due_date(due_date or ""),
        }
        links = {"memory": _memories(caller, memories or []), "file": _files(files or [])}
        if known_issues:
            links["known_issue"] = _memories(caller, known_issues)
        now = self._clock()
        with self._db.transaction() as conn:
            numbered = conn.execute(
                "INSERT INTO boards (project_id, last_number) VALUES (%s, 1)"
                " ON CONFLICT (project_id) DO UPDATE SET last_number = boards.last_number + 1 RETURNING last_number",
                (project_id,),
            ).fetchone()
            assert numbered is not None
            row = conn.execute(
                "INSERT INTO cards (project_id, number, title, description, board_column, position, priority, labels,"
                " due_date, creator_id, created_at, updated_at, moved_at)"
                " VALUES (%s, %s, %s, %s, 'to_do',"
                " (SELECT COALESCE(MAX(position), 0) + 1 FROM cards WHERE project_id = %s AND board_column = 'to_do'),"
                " %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    project_id, numbered["last_number"], fields["title"], fields["description"], project_id,
                    fields["priority"], fields["labels"], fields["due_date"], caller.member.pk, now, now, now,
                ),
            ).fetchone()  # fmt: skip
            assert row is not None
            self._link(conn, row["id"], links)
            card = self._card(conn, row["id"])
        self._audit.card(caller, CARD_ADDED, project_id, card["number"], title=card["title"])
        return card

    def update(
        self,
        caller: Caller,
        number: int,
        *,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        labels: list[str] | None = None,
        due_date: str | None = None,
        memories: list[str] | None = None,
        files: list[str] | None = None,
        assignee: str | None = None,
        column: str | None = None,
        position: int | None = None,
    ) -> dict[str, Any]:
        """Change a card: only what is given changes. column moves it (to the bottom, unless a position is given);
        position alone moves it within its column, 1 being the top. An empty assignee takes the assignee off.

        A card with an assignee is changed only by them, the project's leads and the team's admins; any member may
        change an unassigned one, but only those three set its assignee: a member takes a card by claiming it."""
        project_id = self._project(caller)
        edits: dict[str, Any] = {}
        if title is not None:
            edits["title"] = _title(title)
        if description is not None:
            edits["description"] = _description(description, self._settings.memory_word_limit)
        if priority is not None:
            edits["priority"] = priority_named(priority)
        if labels is not None:
            edits["labels"] = _labels(labels)
        if due_date is not None:
            edits["due_date"] = _due_date(due_date)
        links: dict[str, list[str]] = {}
        if memories is not None:
            links["memory"] = _memories(caller, memories)
        if files is not None:
            links["file"] = _files(files)
        if assignee is not None:
            edits["assignee_id"] = (
                self._identity.member_reaching(caller, project_id, assignee.strip()) if assignee.strip() else None
            )
        to_column = column_named(column) if column is not None else None
        now = self._clock()
        with self._db.transaction() as conn:
            found = self._may_edit(conn, caller, project_id, number)
            if assignee is not None and assignee.strip() and not self._runs(conn, caller, project_id, found):
                raise Refused(
                    "Only a card's assignee, the project's leads and the team's admins give a card an assignee. To "
                    f"work on card {number} yourself, claim it with claim_card."
                )
            card_id, from_column = found["id"], found["board_column"]
            if edits:
                assignments = ", ".join(f"{name} = %s" for name in edits)
                conn.execute(
                    f"UPDATE cards SET {assignments}, updated_at = %s WHERE id = %s", (*edits.values(), now, card_id)
                )
            self._link(conn, card_id, links)
            if to_column is not None or position is not None:
                self._place(conn, project_id, card_id, from_column, to_column or from_column, position, now)
            card = self._card(conn, card_id)
        changed = [name.removesuffix("_id") for name in edits] + [
            "memories" if kind == "memory" else "files" for kind in links
        ]
        if changed:
            self._audit.card(caller, CARD_EDITED, project_id, number, changed=changed)
        if to_column is not None or position is not None:
            moved = {"from": from_column, "to": card["column"], "position": card["position"]}
            self._audit.card(caller, CARD_MOVED, project_id, number, **moved)
        return card

    def require_card(self, caller: Caller, number: int) -> None:
        """Refuse a card number this project's board doesn't have, or a card the caller may not change: a known issue
        names its card before it lands, so a link that would be refused is refused before anything is saved."""
        project_id = self._project(caller)
        with self._db.transaction() as conn:
            self._may_edit(conn, caller, project_id, number)

    def link_known_issue(self, caller: Caller, number: int, path: str) -> dict[str, Any]:
        """Link a known issue to the card that will fix it, after the card's other known issues. Linking edits the
        card, so it takes what editing takes."""
        project_id = self._project(caller)
        (target,) = _memories(caller, [path])
        with self._db.transaction() as conn:
            found = self._may_edit(conn, caller, project_id, number)
            conn.execute(
                "INSERT INTO card_links (card_id, kind, target, place) VALUES (%(card)s, 'known_issue', %(target)s,"
                " (SELECT COUNT(*) FROM card_links WHERE card_id = %(card)s AND kind = 'known_issue'))"
                " ON CONFLICT DO NOTHING",
                {"card": found["id"], "target": target},
            )
            card = self._card(conn, found["id"])
        self._audit.card(caller, CARD_EDITED, project_id, number, changed=["known_issues"])
        return card

    def claim(self, caller: Caller, number: int) -> dict[str, Any]:
        """Make the caller a card's assignee and move it to the bottom of Doing. Only a card in To do with no
        assignee can be claimed, and the first claim wins: the card is taken by one conditional update."""
        project_id = self._project(caller)
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute("SELECT 1 FROM boards WHERE project_id = %s FOR UPDATE", (project_id,))
            claimed = conn.execute(
                "UPDATE cards SET assignee_id = %s, updated_at = %s WHERE project_id = %s AND number = %s"
                " AND assignee_id IS NULL AND board_column = 'to_do' RETURNING id",
                (caller.member.pk, now, project_id, number),
            ).fetchone()
            if claimed is None:
                found = self._found(conn, project_id, number)
                if found["assignee_id"] == caller.member.pk:
                    raise Refused(f"Card {number} is already yours.")
                if found["assignee_id"] is not None:
                    raise Refused(f"Card {number} is already claimed by {_held_by(found)}. Pick another card.")
                raise Refused(
                    f"Card {number} is in {COLUMNS[found['board_column']]}, and only cards in To do can be claimed. "
                    "A project lead can assign it to you, or move it back to To do first."
                )
            self._place(conn, project_id, claimed["id"], "to_do", "doing", None, now)
            card = self._card(conn, claimed["id"])
        self._audit.card(caller, CARD_CLAIMED, project_id, number)
        return card

    def comment(self, caller: Caller, number: int, text: str) -> dict[str, Any]:
        """Add a comment to a card. Anyone who reaches the project may, whoever the card's assignee is."""
        project_id = self._project(caller)
        body = _comment(text)
        with self._db.transaction() as conn:
            found = self._found(conn, project_id, number)
            conn.execute(
                "INSERT INTO card_comments (card_id, author_id, body, created_at) VALUES (%s, %s, %s, %s)",
                (found["id"], caller.member.pk, body, self._clock()),
            )
            card = self._card(conn, found["id"])
        self._audit.card(caller, CARD_COMMENTED, project_id, number)
        return card

    def delete(self, caller: Caller, number: int) -> dict[str, Any]:
        """Delete a card, its links and its comments. Its assignee, the project's leads and the team's admins may;
        so may its creator while it has no assignee. Its number is not used again."""
        project_id = self._project(caller)
        with self._db.transaction() as conn:
            found = self._found(conn, project_id, number)
            if not self._runs(conn, caller, project_id, found):
                if found["assignee_id"] is not None:
                    raise Refused(
                        f"Card {number} is assigned to {_held_by(found)}: only they, the project's leads and the "
                        "team's admins can delete it. Say what you want with comment_card instead."
                    )
                if found["creator_id"] != caller.member.pk:
                    raise Refused(
                        f"Card {number} has no assignee, so only its creator, the project's leads and the team's "
                        "admins can delete it. Say why it should go with comment_card instead."
                    )
            conn.execute("DELETE FROM cards WHERE id = %s", (found["id"],))
            self._arrange(conn, project_id, found["board_column"])
        self._audit.card(caller, CARD_DELETED, project_id, number, title=found["title"])
        return {"deleted": number}

    def return_cards(self, caller: Caller) -> None:
        """Put back in To do, with no assignee, every open card whose assignee can no longer reach its project:
        removed from the team, or shut out of a restricted project. Done cards keep their assignee, as a record of
        who did them. Identity calls this after any change that may have cost a member a project."""
        now = self._clock()
        with self._db.transaction() as conn:
            conn.execute(
                "SELECT b.project_id FROM boards b JOIN projects p ON p.project_id = b.project_id"
                " WHERE p.team_id = %s ORDER BY b.project_id FOR UPDATE OF b",
                (caller.member.team_pk,),
            )
            stranded = conn.execute(
                "SELECT c.id, c.project_id, c.number, c.board_column, m.member_id FROM cards c"
                " JOIN projects p ON p.project_id = c.project_id JOIN members m ON m.id = c.assignee_id"
                " WHERE p.team_id = %s AND c.board_column <> 'done' AND (m.removed_at IS NOT NULL OR (p.restricted"
                " AND NOT m.is_owner AND NOT m.is_admin"
                " AND NOT EXISTS (SELECT 1 FROM project_leads l WHERE l.project_id = p.project_id AND l.member_id = m.id)"
                " AND NOT EXISTS (SELECT 1 FROM project_access a WHERE a.project_id = p.project_id AND a.member_id = m.id)"
                ")) ORDER BY c.project_id, c.number",
                (caller.member.team_pk,),
            ).fetchall()
            for row in stranded:
                conn.execute("UPDATE cards SET assignee_id = NULL, updated_at = %s WHERE id = %s", (now, row["id"]))
                if row["board_column"] != "to_do":
                    self._place(conn, row["project_id"], row["id"], row["board_column"], "to_do", None, now)
        for row in stranded:
            returned = {"from": row["board_column"], "assignee": row["member_id"]}
            self._audit.card(caller, CARD_RETURNED, row["project_id"], row["number"], **returned)

    @staticmethod
    def _found(conn: Conn, project_id: str, number: int) -> dict[str, Any]:
        """A card by its number, with its board locked so no other change to the board interleaves; refused if the
        board has no such card."""
        conn.execute("SELECT 1 FROM boards WHERE project_id = %s FOR UPDATE", (project_id,))
        found = conn.execute(
            "SELECT c.id, c.title, c.board_column, c.creator_id, c.assignee_id, a.member_id AS assignee,"
            " a.name AS assignee_name FROM cards c LEFT JOIN members a ON a.id = c.assignee_id"
            " WHERE c.project_id = %s AND c.number = %s",
            (project_id, number),
        ).fetchone()
        if found is None:
            raise Refused(f"This project's board has no card {number}. Read the board to find its cards' numbers.")
        return dict(found)

    def _may_edit(self, conn: Conn, caller: Caller, project_id: str, number: int) -> dict[str, Any]:
        """A card the caller may edit or move: any card with no assignee, or one they run; refused otherwise."""
        found = self._found(conn, project_id, number)
        if found["assignee_id"] is not None and not self._runs(conn, caller, project_id, found):
            raise Refused(
                f"Card {number} is assigned to {_held_by(found)}: only they, the project's leads and the team's "
                "admins can change it. Say what you want with comment_card instead."
            )
        return found

    @staticmethod
    def _runs(conn: Conn, caller: Caller, project_id: str, card: dict[str, Any]) -> bool:
        """Whether the caller may do anything to this card: its assignee, the project's leads and the team's admins."""
        member = caller.member
        if member.is_owner or member.is_admin or card["assignee_id"] == member.pk:
            return True
        leads = conn.execute(
            "SELECT 1 FROM project_leads WHERE project_id = %s AND member_id = %s", (project_id, member.pk)
        ).fetchone()
        return leads is not None

    @staticmethod
    def _link(conn: Conn, card_id: int, links: dict[str, list[str]]) -> None:
        """Replace a card's links of each kind given."""
        for kind, targets in links.items():
            conn.execute("DELETE FROM card_links WHERE card_id = %s AND kind = %s", (card_id, kind))
            for place, target in enumerate(targets):
                conn.execute(
                    "INSERT INTO card_links (card_id, kind, target, place) VALUES (%s, %s, %s, %s)",
                    (card_id, kind, target, place),
                )

    @staticmethod
    def _place(
        conn: Conn, project_id: str, card_id: int, from_column: str, to_column: str, position: int | None, now: datetime
    ) -> None:
        """Put a card at a position in a column (the bottom when none is given), and close the gap it left."""
        others = [
            row["id"]
            for row in conn.execute(
                "SELECT id FROM cards WHERE project_id = %s AND board_column = %s AND id <> %s ORDER BY position",
                (project_id, to_column, card_id),
            ).fetchall()
        ]
        at = len(others) if position is None else max(0, min(position - 1, len(others)))
        if to_column != from_column:
            conn.execute(
                "UPDATE cards SET board_column = %s, moved_at = %s, updated_at = %s WHERE id = %s",
                (to_column, now, now, card_id),
            )
            Board._arrange(conn, project_id, from_column)
        conn.execute(
            "UPDATE cards c SET position = o.place FROM unnest(%s::bigint[]) WITH ORDINALITY AS o(id, place)"
            " WHERE c.id = o.id",
            ([*others[:at], card_id, *others[at:]],),
        )

    @staticmethod
    def _arrange(conn: Conn, project_id: str, column: str) -> None:
        """Number a column's cards 1, 2, 3 from the top, keeping their order."""
        conn.execute(
            "UPDATE cards c SET position = o.place FROM ("
            " SELECT id, row_number() OVER (ORDER BY position) AS place FROM cards"
            " WHERE project_id = %s AND board_column = %s) o WHERE c.id = o.id",
            (project_id, column),
        )

    @staticmethod
    def _card(conn: Conn, card_id: int) -> dict[str, Any]:
        row = conn.execute(f"{_CARD} WHERE c.id = %s", (card_id,)).fetchone()
        assert row is not None
        return _shown(row)

