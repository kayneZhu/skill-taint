#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
workdir="runs/mock-campaign"
if [ -e "$workdir" ]; then
  printf '%s\n' "refusing to reuse ${workdir}; remove it before running the mock campaign again" >&2
  exit 1
fi
uv run skill-taint --backend mock --defense compare --workdir "$workdir"
