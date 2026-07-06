# Local Runtime Preview

This page tracks local runtime features that have been proven on the maintainer
machine but are not yet a published release claim.

Use this page as a bridge between construction receipts and public release
notes. A feature listed here still needs the normal release gate, package
build, and cross-machine proof before it can be described as generally
available.

## Reading Area

Reading Area is a read-only project view for multiple local agent windows. It
keeps write ownership separate from read sharing:

- each window writes only to its own raw/source lane;
- the Reading Area projects a scoped, read-only view across declared project
  members;
- startup injection sends a compact project-page view, not raw bodies;
- full evidence is opened later by `library_id` or source refs.

The local runtime preview currently uses lanes for Codex, Opus, MiMo, and
Claude-family local records. The proof is local-loopback runtime only.

## Five Shelves In Startup Catalog

The startup catalog can project all five shelves:

- `raw`
- `zhiyi`
- `xingce`
- `toolbook`
- `errata`

The current startup view is intentionally small. It favors Reading Area lanes
and compact handles over a flat body dump. Source excerpts stay behind
`library_id` borrowing.

## Whiteboard

Whiteboard records are project handoff records, not a new shelf. They are a
read-only registry projection that lets one agent leave a handoff and another
agent claim it.

The local runtime has a Codex-to-Opus style handoff/claim chain. A true
external naked-window north-star test remains a posthoc validation item.

## Project History And Nominations

Project history records summarize project-level progress into project pages
instead of the five shelves. Nomination and claim records are registry workflow
objects:

- nomination suggests a possible project/member relation;
- claim records an explicit declaration;
- project history keeps source refs and durable evidence slices.

Project history evidence now rejects or materializes temporary source refs so a
borrowed history record does not depend on `/tmp` or `/var/folders` paths.

## Automatic Distillation

Local distillation now has a coverage ledger and windowed runner. The runner
can process scoped local records and write evidence-bound candidates for:

- `zhiyi`: preferences, naming boundaries, user intent, corrections;
- `xingce`: work experience, validation paths, repair order;
- `toolbook`: objective tool/platform facts such as ports, config, paths, and
  runbooks.

Every accepted card should keep byte offsets, a verbatim excerpt, and
`verbatim_sha256`. Low-quality status reports and one-off construction reports
should not become toolbook facts.

## Auto-Connect Dry Run

Auto-connect planning can produce platform-specific plans and rollback
previews without writing external platform config. The local runtime preview is
dry-run only.

Real apply remains behind explicit user authorization for each target platform.
It needs backup, rollback, capability check, and a real recall proof after
connect.

## FTS5 Recall Leg

The FTS5 leg is available as an explicit local runtime recall path for selected
substring/BM25-style queries. It is not the default vector freshness path and
does not prove full-chain natural freshness.

The current boundary is:

- explicit FTS5 local runtime: proven on the maintainer machine;
- default vector freshness: not claimed;
- natural full-chain freshness from raw/session write to MCP visibility: not
  signed.

## Not Yet Claimed

The local preview does not claim:

- a published release;
- cross-machine proof;
- packaged build proof;
- true external Opus/naked-window master audit;
- real auto-connect apply;
- natural full-chain freshness.

For proof anchors, use the maintainer-only receipt archive and private
continuation ledger. Those construction files are not part of the public
release package.
