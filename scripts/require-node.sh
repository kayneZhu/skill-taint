# Source this file. It exits when Node.js is missing or older than 20.
if ! command -v node >/dev/null 2>&1; then
  printf '%s\n' "Node.js 20 or newer is required to build the campaign viewer" >&2
  exit 1
fi
node -e 'const major = Number(process.versions.node.split(".")[0]); if (!Number.isInteger(major) || major < 20) { process.stderr.write("Node.js 20 or newer is required, found " + process.versions.node + "\n"); process.exit(1); }'
