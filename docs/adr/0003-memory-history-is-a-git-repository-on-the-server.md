# Memory history is a git repository on the server

Every save to the memory folder is committed automatically on the server and credited to the member, which gives history, undo, diffs and authorship for superseded and retired memories; a nightly push to a private remote doubles as the file backup. This is not the "memory in git" rejected in ADR-0001: members never see these commits, nothing goes through review, and nothing lands in project repositories.
