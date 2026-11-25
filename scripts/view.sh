#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
. "$root/scripts/require-node.sh"
cd "$root/viewer"
if [ ! -f package-lock.json ]; then
  printf '%s\n' "viewer/package-lock.json is missing" >&2
  exit 1
fi
if [ ! -x node_modules/.bin/tsc ]; then
  npm ci
fi
./node_modules/.bin/tsc -p tsconfig.json
exec node server.mjs
