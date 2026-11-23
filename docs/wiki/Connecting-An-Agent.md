# Connecting An Agent

Time Library has no code for any particular agent and never will. An agent
connects itself: it describes its own session files, checks the description on
its own files, and reports it. The full field reference is in the install guide
each server hands out at `http://<nas-address>:9850/client/install.md`
(step 4); this page is the overview.

## Describe

The description is a small JSON object. It starts from the shape closest to the
agent's own records (`base`) and overrides what differs:

- **which records** are dialogue (`match`, `skip_if_true`, `skip_if_equals`);
- **who speaks** (`role`, with `role_map` when the agent's words for the
  speakers are not user/assistant);
- **what was said** (`content`, `text_block_types`, `block_text`);
- **when** (`timestamp`) and **which session** (`session_id`, or
  `session_id_from_path` when the folder names it);
- **where it worked** (`cwd`) and **where it was started** (`surface`, for an
  agent with a desktop app and a command line);
- **only what the user typed**: `user_match`, `unwrap_elements` (tags around
  the user's words), `runtime_elements` (context the harness adds),
  `runtime_messages`, and `session_skip_if_equals` for whole files that are a
  subagent's own transcript;
- **how sessions are stored**: JSON lines (zstd-compressed files are read as
  they are), one JSON document per session (`"store": "json"`), or a SQLite
  database (`"store": "sqlite"`, read only).

## Check

```bash
PY ~/.time-library-client/tl.py check --sessions "<folder>" --glob "<files>" --format-json @description.json
```

Nothing is sent. It says how many sessions and turns would be collected, shows
a few, lists what it left out and why, and warns about what looks wrong: every
file giving one session id, no user turns, speaker words it did not
understand, context written as user turns. The agent corrects its description
until the check says it looks right.

## Report

```bash
PY ~/.time-library-client/tl.py report-agent --name "<product name>" --sessions "<folder>" --glob "<files>" --format-json @description.json --capability mcp=true --capability skill=true --capability preflight=true
```

Reporting again later takes only what changed. `--since now` collects only what
is said from then on (for an agent whose past sessions are mostly tests).

## Prompt hooks

A hook that is "the prompt in, text out" points at
`tl.py preflight --agent "<name>"` directly. A hook of another shape is
described once with `report-agent --hook-json`: where the user's words are
(`prompt`), the output template with `{text}` where the memories go
(`output`), what to print when there are none (`empty`), and what identifies
one turn when the hook runs on every model call (`once_per`). Try it with
`tl.py check --agent "<name>" --hook-sample @sample.json`. No script in between.

## When something cannot be described

The agent does not work around it. It tells the user exactly what is missing
(the field, and a line of its file that shows it) and reports only what does
read right. That is how the description language grows: by what agents say
they need, not by code for one product.
