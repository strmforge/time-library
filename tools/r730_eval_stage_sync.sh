#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="${REMOTE:-root@192.168.50.121}"
IDENTITY="${IDENTITY:-$HOME/.ssh/github_codex_ed25519}"
DEST="${DEST:-/root/memcore-eval-stage/memcore-cloud-rebuilt-20260527/}"
REMOTE_DEST_QUOTED="$(printf '%q' "${DEST}")"

rsync -az --delete \
  --exclude '.git/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'memory/' \
  --exclude 'output/' \
  --exclude 'release/' \
  --exclude 'benchmarks/eval-runs/' \
  -e "ssh -i ${IDENTITY} -o IdentitiesOnly=yes" \
  "${ROOT}/" "${REMOTE}:${DEST}"

ssh -i "${IDENTITY}" -o IdentitiesOnly=yes "${REMOTE}" \
  "du -sh ${REMOTE_DEST_QUOTED} && cd ${REMOTE_DEST_QUOTED} && python3 -m py_compile src/official_memory_benchmarks.py src/eval_resource_ledger.py src/eval_entrypoints.py src/free_memory_benchmark.py src/eval_miss_report.py tools/memcore_eval_entry.py tools/eval_miss_report.py"
