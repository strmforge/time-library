# Memcore Cloud Agent Rules

## Remote Writes

Do not push without an explicit push instruction from the user in the current
turn.

This rule covers:

- `git push`
- pushing tags or moving release tags
- creating, editing, publishing, or deleting GitHub Releases
- pushing the wiki repository
- any other command that mutates a remote repository or public release surface

Ambiguous phrases such as "fix it", "release prep", "finish it", "next step",
"repair this", or "update it" are not push authorization. Treat them as local
work only unless the user explicitly says to push, publish, release, or update
the remote.

If a remote write is needed to repair a previous mistake, explain the exact
remote change first and wait for the user's explicit approval before running
the command.

## Local Work

Local edits, tests, status checks, and local commits may be prepared when they
fit the user's request. Keep the final answer clear about what is local versus
what has reached GitHub.

## Release Boundary

Never retag, force-push, rewrite a release tag, or edit a published GitHub
Release unless the user explicitly asks for that exact remote action.
