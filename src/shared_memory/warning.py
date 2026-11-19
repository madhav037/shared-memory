"""Warnings (CONTEXT.md): what a gate or standby tells the member themselves, word for word, rather than their coding
agent (spec #585). This module owns every warning's wording.

A warning is built from structured data, a `Warning`: its mark, heading, what it says, one row per member the wait is
for, when the wait passes, the words the member can reply with, and any words of a teammate's to quote. `render` turns
it into text for the reader at a moment and in a time zone: a bold heading over a `text` code fence holding a box drawn
with box-drawing characters, hard-wrapped at `WIDTH` columns and never wider, so it keeps its shape in a narrow
terminal or an IDE's chat pane. `headline` is the same warning as one line, for an agent that shows its member a line
of its own (Claude Code's `systemMessage`). `shown` puts warnings before the agent-only lines of a notice, under the
words that ask the agent to show them first, and gives a `Shown`: the notice's text, still carrying its warnings and
the headlines its member is yet to be shown, through every module that passes notices on as text. `joined` joins
notices keeping both; `warnings_in` and `headlines_in` read them back where the answer is made, and `agent_lines_in`
the lines meant for the agent alone, for an answer that hands the warnings over on their own (a standby's `member`).
`gathered` tells the warnings of several notices first, then their agent-only lines.

Anything a teammate wrote (a name, an activity, quoted words) is escaped before it is drawn, so it cannot break the
frame or the fence, and quoted words are cut at `QUOTED_LINES` lines, the full text being the agent's to give below.
Times are relative ("14 min left"), with the clock time added in the reader's own time zone when one is known, never
in UTC. Members are never given gendered pronouns.

The builders are the wording of each warning; the gate and the standby give them plain data. A wait starts with
`held_by_gate` and `asked_by_gate`, and ends with `agreed`, `refused`, `wait_passed` and `earlier_gone` for the held
member and `went_ahead` for the earlier one; `standby_heard_nothing` is a standby that heard nothing.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import StrEnum

from shared_memory import fence

# The widest a warning's box is drawn, frame included, in terminal columns.
WIDTH = 60
# The most lines of a teammate's words a box quotes; the rest is the agent's to give below it.
QUOTED_LINES = 8
# What a notice says before its warnings: the agent shows them before anything else.
LEAD_IN = "Show your member this first, word for word:"
# Where a cut quotation says the rest is.
CUT = "… full message below"

# The columns between the frame's two sides and their padding.
_INNER = WIDTH - 4
_RULE = "─" * (WIDTH - 2)
# A character that could pass for the frame or close the fence: box-drawing and block elements, and the backtick.
_FRAME_LIKE = re.compile(r"[─-▟]")
# Markdown's emphasis and code marks, escaped in the bold heading.
_MARKDOWN = re.compile(r"([\\`*_\[\]])")


class Mark(StrEnum):
    """What a warning tells at a glance, before its heading."""

    # A wait starts.
    WAITS = "⚠"
    # The work goes ahead: agreed, different work, or the earlier session gone.
    GOES_AHEAD = "✅"
    # Refused.
    REFUSED = "⛔"
    # The wait passed with no answer, or a standby heard nothing yet.
    PASSED = "⏳"


@dataclass(frozen=True)
class Row:
    """One member a wait is for: their name, what they are working on, and where their part of the wait stands."""

    member_name: str
    activity: str | None = None
    # When their part of the wait passes with no answer, if it does.
    until: datetime | None = None
    # They refused, which holds the wait until their session ends or goes idle.
    refused: bool = False


@dataclass(frozen=True)
class Warning:  # The glossary's term. It shadows the builtin here, which this module never raises or catches.
    """One warning, as data: rendered by `render`, told in one line by `headline`."""

    mark: Mark
    # Plain words; a teammate's name in it is escaped when drawn.
    heading: str
    # Paragraphs, each wrapped in the box.
    says: tuple[str, ...] = ()
    rows: tuple[Row, ...] = ()
    # When the whole wait passes with no answer, and what happens then: "then your edit goes ahead on its own".
    until: datetime | None = None
    then: str = ""
    # Paragraphs after the time left, such as that the session stands by.
    after: tuple[str, ...] = ()
    # The words the member can reply with, each a decision the agent acts on.
    replies: tuple[str, ...] = ()
    # A teammate's words, and whose they are, quoted in the box and cut at QUOTED_LINES lines.
    quoted: str | None = None
    quoted_from: str = ""


# Rendering


def render(warning: Warning, now: datetime, zone: tzinfo | None = None) -> str:
    """The warning as the member is shown it: a bold heading over a fenced box, `WIDTH` columns at most. Times are
    left relative unless `zone`, the reader's time zone, is known."""
    lines: list[str] = []
    for paragraph in warning.says:
        lines += [*_gap(lines), *_wrapped(paragraph)]
    if warning.rows:
        lines += _gap(lines)
        for row in warning.rows:
            lines += _wrapped(_row(row, warning.until, now, zone), hanging="  ")
    if warning.until is not None:
        then = f", {warning.then}" if warning.then else ""
        lines += [*_gap(lines), *_wrapped(f"{time_left(now, warning.until, zone)}{then}.")]
    for paragraph in warning.after:
        lines += [*_gap(lines), *_wrapped(paragraph)]
    if warning.quoted:
        lines += [*_gap(lines), *_wrapped(f"{_name(warning.quoted_from)}'s words:"), *_quoted(warning.quoted)]
    if warning.replies:
        lines += [*_gap(lines), "Reply with one of:", *_wrapped(" · ".join(warning.replies))]
    framed = [f"┌{_RULE}┐", *(f"│ {line}{' ' * (_INNER - columns(line))} │" for line in lines), f"└{_RULE}┘"]
    return "\n".join([f"**{_heading(warning)}**", "", "```text", *framed, "```"])


def headline(warning: Warning) -> str:
    """The warning in one line, for an agent that shows its member a line of its own."""
    return f"{warning.mark} {_name(warning.heading)}. Read the box below."


class Shown(str):
    """A notice's text that carries warnings, and still says which: what it shows the member, as data, and the
    headlines the member is still to be shown on a line of their own, none when they already were (a refused edit
    repeats). It is the notice's text wherever text is wanted; joining notices keeps what they carry only through
    `joined`, since any other way of building on a string gives a plain one. It keeps its lines meant for the agent alone
    apart as well, so an answer that hands the warnings over on their own (a standby's `member`) can tell the rest
    after them."""

    warnings: tuple[Warning, ...]
    headlines: tuple[str, ...]
    agent_lines: tuple[str, ...]

    def __new__(
        cls,
        text: str,
        warnings: Sequence[Warning] = (),
        headlines: Sequence[str] = (),
        agent_lines: Sequence[str] = (),
    ) -> Shown:
        made = super().__new__(cls, text)
        made.warnings = tuple(warnings)
        made.headlines = tuple(headlines)
        made.agent_lines = tuple(agent_lines)
        return made


def shown(
    warnings: Sequence[Warning],
    agent_lines: str,
    now: datetime,
    zone: tzinfo | None = None,
    *,
    headlined: bool = True,
) -> Shown:
    """A notice that carries warnings: the words asking the agent to show them first, the warnings, then the lines
    meant for the agent alone. It carries their headlines too, unless the member has already been shown them, and its
    agent-only lines apart."""
    text = "\n\n".join([LEAD_IN, *(render(each, now, zone) for each in warnings), agent_lines])
    return Shown(text, warnings, [headline(each) for each in warnings] if headlined else (), [agent_lines])


def joined(notices: Iterable[str | None]) -> str:
    """Notices as one text, a blank line between them, carrying every warning and headline they carry; empty when
    there are none."""
    told = [each for each in notices if each]
    text = "\n\n".join(told)
    carried = [each for each in told if isinstance(each, Shown)]
    if not carried:
        return text
    return Shown(
        text,
        [warning for each in carried for warning in each.warnings],
        [line for each in carried for line in each.headlines],
        [line for each in told for line in agent_lines_in(each)],
    )


def warnings_in(text: str) -> tuple[Warning, ...]:
    """The warnings a notice's text shows its member, as data; none for a plain one."""
    return text.warnings if isinstance(text, Shown) else ()


def headlines_in(text: str) -> tuple[str, ...]:
    """The headlines a notice's text is still to show its member on a line of their own; none for a plain one."""
    return text.headlines if isinstance(text, Shown) else ()


def agent_lines_in(text: str) -> tuple[str, ...]:
    """A notice's lines meant for the agent alone, without the warnings it shows first: all of a plain one."""
    return text.agent_lines if isinstance(text, Shown) else (text,)


def gathered(warnings: Sequence[str], agent_lines: Sequence[str]) -> str:
    """Rendered warnings and the agent-only lines of one or more notices told together: `LEAD_IN` and every warning
    first, then every agent's line. With no warning there is nothing to show first, and no `LEAD_IN`."""
    first = [LEAD_IN, *warnings] if warnings else []
    return "\n\n".join([*first, *(each for each in agent_lines if each)])


def time_left(now: datetime, until: datetime, zone: tzinfo | None = None) -> str:
    """How long is left until a moment: "14 min left", with "(until 2:32 pm your time)" when the reader's time zone
    is known. Never in UTC."""
    seconds = (until - now).total_seconds()
    left = "less than 1 min left" if seconds < 60 else f"{math.ceil(seconds / 60)} min left"
    if zone is None:
        return left
    local, today = until.astimezone(zone), now.astimezone(zone)
    day = "" if local.date() == today.date() else f"{local:%a} "
    clock = f"{local.hour % 12 or 12}:{local.minute:02d} {'am' if local.hour < 12 else 'pm'}"
    return f"{left} (until {day}{clock} your time)"


def escaped(text: str) -> str:
    """A teammate's words made safe to draw in the box: no look-alike tag, no control or invisible formatting
    character, nothing that passes for the frame, no backtick to open or close a fence. Lines are kept."""
    text = fence.escape(text).replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    text = _FRAME_LIKE.sub("+", text).replace("`", "'")
    return "".join(each for each in text if each == "\n" or unicodedata.category(each) not in ("Cc", "Cf"))


def columns(text: str) -> int:
    """The columns text takes in a terminal: two for a wide character, none for a combining one."""
    return sum(_columns(each) for each in text)


def _columns(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1


def _name(text: str) -> str:
    """A teammate's words kept on one line."""
    return " ".join(escaped(text).split())


def _heading(warning: Warning) -> str:
    return f"{warning.mark} {_MARKDOWN.sub(r'\\\1', _name(warning.heading))}"


def _row(row: Row, until: datetime | None, now: datetime, zone: tzinfo | None) -> str:
    """One member's row. Their time left is given when it is not the whole wait's, which the box gives below."""
    activity = f'working on "{_name(row.activity)}"' if row.activity else "no activity stated"
    if row.refused:
        state = "refused; this holds until their session ends or goes idle"
    elif row.until is not None and row.until != until:
        state = f"no answer yet, {time_left(now, row.until, zone)}"
    elif row.until is not None:
        state = "no answer yet"
    else:
        state = ""
    return f"- {_name(row.member_name)}, {activity}{f': {state}' if state else ''}"


def _quoted(text: str) -> list[str]:
    lines = [line for each in escaped(text).strip().split("\n") for line in _wrapped(each, first="> ", hanging="> ")]
    return lines if len(lines) <= QUOTED_LINES else [*lines[: QUOTED_LINES - 1], CUT]


def _gap(lines: list[str]) -> list[str]:
    return [""] if lines else []


def _wrapped(text: str, first: str = "", hanging: str = "") -> list[str]:
    """Text broken into lines of at most `_INNER` columns at spaces, a word too long for a line broken inside it.
    `first` opens the first line and `hanging` each one after."""
    lines: list[str] = []
    line, bare = first, True
    for word in text.split():
        joined = line + (word if bare else f" {word}")
        if columns(joined) <= _INNER:
            line, bare = joined, False
            continue
        if not bare:
            lines.append(line)
            line = hanging
        while columns(line + word) > _INNER:
            cut = _fit(word, _INNER - columns(line))
            lines.append(line + word[:cut])
            line, word = hanging, word[cut:]
        line, bare = line + word, False
    lines.append(line.rstrip())
    return lines


def _fit(word: str, room: int) -> int:
    """How many of the word's characters fit in this many columns, at least one so the word always shrinks."""
    used = 0
    for count, character in enumerate(word):
        used += _columns(character)
        if used > room:
            return max(count, 1)
    return len(word)


# The warnings


def _names(rows: Sequence[Row]) -> str:
    names = [row.member_name for row in rows]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def held_by_gate(rows: Sequence[Row]) -> Warning:
    """Told to the member whose edit a gate holds: one row per member it waits for, how long is left, that their
    session stands by, and what they can reply."""
    open_rows = [row.until for row in rows if not row.refused and row.until is not None]
    refused = any(row.refused for row in rows)
    whose = "Another member's session is" if len(rows) == 1 else "Other members' sessions are"
    return Warning(
        mark=Mark.WAITS,
        heading=f"Your edit waits for {_names(rows)}",
        says=(
            f"{whose} on nearly the same work as yours, so your agent stopped before editing. Reading, searching and "
            "planning still work.",
        ),
        rows=tuple(rows),
        until=None if refused or not open_rows else max(open_rows),
        then="then your edit goes ahead on its own, unless they refuse",
        after=("Your session stands by: you will hear their answer here without typing anything.",),
        replies=("wait", "different work", "pick something else"),
    )


def asked_by_gate(row: Row) -> Warning:
    """Told to the earlier member whose work a teammate's gated session waits on: who, how long until it goes ahead
    without an answer, and what they can reply."""
    return Warning(
        mark=Mark.WAITS,
        heading=f"{row.member_name} is waiting on you",
        says=(
            f"{row.member_name}'s session is on nearly the same work as yours. Its edits wait for your answer.",
        ),
        rows=(Row(row.member_name, row.activity),),
        until=row.until,
        then="then their edit goes ahead without your answer",
        replies=("agree", "refuse"),
    )


# The endings of a wait (#588). The held member hears each answer and lift; the earlier member hears that the gated
# teammate went ahead.

# What a held member hears of their own part once one member's part of the gate is over.
_ONCE_EVERY_OTHER = (
    "Your edits on nearly the same work as theirs go ahead, once every other member the gate waits for has agreed or "
    "the wait has passed."
)


def agreed(member_name: str, words: str | None = None) -> Warning:
    """Told to the held member when a member the gate waits for agrees, quoting their words if they gave any."""
    return Warning(
        mark=Mark.GOES_AHEAD,
        heading=f"{member_name} agreed",
        says=(_ONCE_EVERY_OTHER,),
        quoted=words,
        quoted_from=member_name,
    )


def refused(member_name: str, words: str | None = None) -> Warning:
    """Told to the held member when a member the gate waits for refuses, quoting their words if they gave any, and
    what they can reply now."""
    return Warning(
        mark=Mark.REFUSED,
        heading=f"{member_name} refused",
        says=(
            f"Your edits on nearly the same work as theirs stay held past the project's wait, until {member_name}'s "
            "session ends or goes idle.",
        ),
        quoted=words,
        quoted_from=member_name,
        replies=("pick something else", "different work", "wait"),
    )


def wait_passed(member_name: str, minutes: int) -> Warning:
    """Told to the held member when the project's wait passes with no answer from a member the gate waits for."""
    return Warning(
        mark=Mark.PASSED,
        heading=f"The wait for {member_name} passed with no answer",
        says=(f"The project's wait ({minutes} min) passed with no answer from {member_name}.", _ONCE_EVERY_OTHER),
    )


def earlier_gone(member_name: str) -> Warning:
    """Told to the held member when the session of a member the gate waits for ends or goes idle."""
    return Warning(
        mark=Mark.GOES_AHEAD,
        heading=f"{member_name}'s session ended or went idle",
        says=(f"{member_name} is no longer holding your work.", _ONCE_EVERY_OTHER),
    )


def went_ahead(member_name: str, different_work: bool, minutes: int) -> Warning:
    """Told to the earlier member when the teammate their work held goes ahead: it said it is different work, or the
    project's wait passed with no answer."""
    if different_work:
        return Warning(
            mark=Mark.GOES_AHEAD,
            heading=f"{member_name} said it is different work",
            says=(
                f"{member_name}'s session was waiting on nearly the same work as yours. They said it is different "
                "work, so their edits go ahead now, near your work.",
            ),
        )
    return Warning(
        mark=Mark.PASSED,
        heading=f"{member_name} went ahead on the wait",
        says=(
            f"{member_name}'s session was waiting on nearly the same work as yours. The project's wait ({minutes} "
            "min) passed with no answer, so their edits go ahead now, near your work.",
        ),
    )


def standby_heard_nothing(until: datetime | None) -> Warning:
    """Told to the member whose session stood by and heard nothing: how long is left of the project's wait, `until`,
    or that it has passed."""
    if until is None:
        return Warning(
            mark=Mark.PASSED,
            heading="No answer, and the project's wait has passed",
            says=("Your session stood by, and no answer came for it. The project's wait has passed with no answer.",),
            after=("Your session stands by at most once more, then stops.",),
        )
    return Warning(
        mark=Mark.PASSED,
        heading="No answer yet",
        says=("Your session stood by, and no answer came for it yet.",),
        until=until,
        then="then the project's wait passes",
        after=("Your session can stand by once more: you will hear the answer here without typing anything.",),
    )
