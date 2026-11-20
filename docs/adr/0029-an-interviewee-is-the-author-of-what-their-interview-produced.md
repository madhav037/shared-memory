# An interviewee is the author of what their interview produced

ADR-0016 names a memory's author from git blame: whoever wrote the words. An interview has no blame to run; the words are the interviewee's answers, typed by whichever member's coding agent ran the interview. Promote names the interviewee as author, and records the member who ran the interview as importer and the interview as the source. Authorship decides who may retire a memory and who decides a challenge against it, and that say belongs to the person whose knowledge it is, which is the point of interviewing someone who will not use a coding agent themselves.

## Considered options

- **The member who ran the interview is the author.** Rejected: a project lead interviewing a departing engineer would then decide every later challenge against rules they only transcribed.
- **The interviewee approves each proposal before anything is saved.** Rejected: it needs the interviewee in a session, the thing an interview exists to avoid. They govern afterwards instead.

## Consequences

- An interviewee must be a member who can reach the project, as ADR-0016 requires of any named author. Someone who is not keeps the member who ran the interview as author, with their name noted in the body.
- The interviewee is told in the console and in their next briefing, by whom and from which interview, and may retire any memory promoted from it from the console, which is governance (ADR-0009). They do not edit it there; a correction is a new memory in a session.
