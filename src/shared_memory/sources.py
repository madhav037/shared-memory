"""Where an imported memory came from: the forms a source takes when a promotion records it.

The server never sees a source (ADR-0016), so it checks only the shape: a repository file is repository:path, a
commit is commit:repository@revision, and an outside source is its kind and a reference. Whatever the shape allows
is stored as given."""

from __future__ import annotations

from shared_memory.identity import NAME_PATTERN

SOURCE_LIMIT = 300
COMMIT = "commit"
INTERVIEW = "interview"
OUTSIDE_KINDS = ("wiki", "ticket", "pr-comment", INTERVIEW)
FORMS = (
    "repository:path for a file in a repository (billing-api:CLAUDE.md), commit:repository@revision for a commit "
    "(commit:billing-api@3f9c2ab), wiki:page for a wiki or doc export page, ticket:reference for a ticket, "
    "pr-comment:reference for a pull request review comment (pr-comment:billing-api#88), or interview:reference "
    "for an interview"
)


def well_formed(source: str) -> bool:
    """Whether a source, already stripped, has one of the accepted forms."""
    if not source or "\n" in source or len(source) > SOURCE_LIMIT:
        return False
    kind, _, reference = source.partition(":")
    reference = reference.strip()
    if kind == COMMIT:
        repository, at, revision = reference.partition("@")
        return bool(NAME_PATTERN.match(repository)) and bool(at) and bool(revision) and not revision.isspace()
    if kind in OUTSIDE_KINDS:
        return bool(reference)
    return bool(NAME_PATTERN.match(kind)) and bool(reference)


def of_repository(source: str, repository: str) -> bool:
    """Whether a source is a file or a commit of this repository."""
    return source.startswith(f"{repository}:") or source.startswith(f"{COMMIT}:{repository}@")


def of_kind(source: str, kind: str) -> bool:
    """Whether a source is an outside source of this kind."""
    return source.startswith(f"{kind}:")
