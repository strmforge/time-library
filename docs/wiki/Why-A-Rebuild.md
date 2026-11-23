# Why A Rebuild

2026.11.23 does not add to the earlier version: Time Library was rebuilt from
the ground up. The aim is unchanged — one memory for all your agents, every
memory resting on the original words. Almost everything else is new.

## What changed

| | 2026.9.11 and earlier | 2026.11.23 on |
|---|---|---|
| Where it runs | A full set of services on every computer | One server on your NAS (Docker), a small client on each computer |
| Who shares memory | The agents on one computer | Every agent on every computer |
| What is kept | Whole session files, runtime (tool output and the like) included | Dialogue only; runtime dropped on the computer, credentials masked before they leave it |
| A new agent | Needed an adapter written for it | Describes its own session format, checks it, reports it |
| Memories | Raw records with two layers of notes on top | Decisions, preferences, corrections, facts and lessons, each quoting the words it rests on (checked character for character); the user's own words told apart from an assistant's and from pasted text; experience cards per project |
| Models | chat/completions | A model per task with backups; OpenAI Responses and Anthropic Messages natively; a built-in local model |
| Install | Install scripts and installers | `docker compose up` for the server; the server hands out the client, with its own Python |
| Admin | A local page on each computer | One web admin on the server, in English and Chinese |

## Why

- **A full stack on every computer meant every computer had its own
  problems.** Most of what it kept was runtime rather than dialogue, so local
  disks kept filling. Now a computer keeps only its read position; the dialogue
  goes to the NAS, and the original session files stay where each agent keeps
  them.
- **Memory should cross computers.** One memory per computer meant starting
  over on the next one.
- **Adapters per product cannot keep up.** New agents appear faster than
  adapters get written. Now an agent says what it is and how its sessions
  look; Time Library only has to read that description. There is no code for
  any particular product.
- **A memory should hold up as evidence.** It points back to the original
  words, and says whose words they were: a preference resting only on a pasted
  report from another AI is not the user's preference.
- **Models are a choice, not a given.** Each task (history import, nightly
  distillation, deep summary) gets its own model and backup, and a model that
  runs out of balance or goes offline is retried without losing the place.

## What did not come along

- The per-computer console, installers and services. Their history comes along
  (see [Moving From An Earlier Version](Moving-From-An-Earlier-Version.md)).
- Per-product adapters and the tool discovery that went with them.
- The Hermes skill-and-experience loop. Hermes's conversations are collected
  like any other agent's.

The earlier versions stay on the [releases page](https://github.com/strmforge/time-library/releases)
and in the `v2026.9.11` tag.
