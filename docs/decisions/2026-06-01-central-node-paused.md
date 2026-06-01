# Central Node Work Paused

Date: 2026-06-01

Status: paused, not started

Decision:

Central node implementation is intentionally not started yet. The work should wait until the Nantianmen direction is complete enough to define the real coordination boundary.

Current allowed work:

- Keep the 2026.6.1 computer-first raw archive contract.
- Keep local platform discovery and local raw layout audit working.
- Keep legacy raw paths read-compatible only.
- Record central-node requirements and blockers as source-backed notes.

Current blocked work:

- Do not implement central-node sync.
- Do not create central-node manifests, receipts, or transport flows as production behavior.
- Do not move raw bodies into a central aggregation process.

Resume condition:

Start central-node construction only after the user confirms that Nantianmen is complete or ready enough to anchor the design.

Rationale:

The raw archive layout already prepares for central-node mode by grouping memory first by computer, then by source system, then by native artifact format. That is enough groundwork for now. Beginning central-node implementation before Nantianmen is ready would likely create the wrong abstraction boundary.
