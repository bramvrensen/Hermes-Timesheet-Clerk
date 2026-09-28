#!/usr/bin/env bash
# Download a complete, immutable Timesheet Clerk version directly from GitHub.
set -euo pipefail
timesheet_ref="${TIMESHEET_CLERK_REF:-feature/v2}"
timesheet_args=("$@")
while (($#)); do
  case "$1" in
    --ref) [[ $# -ge 2 ]] || { echo "--ref requires a branch, tag or commit" >&2; exit 1; }; timesheet_ref="$2"; shift 2 ;;
    --help|-h)
      echo "Timesheet Clerk installer"
      echo "Usage: bash install.sh [--dir PATH] [--ref REF] [--env-file FILE] [--migrate-from PATH] [--yes]"
      echo "Existing settings and Docker data volumes are preserved on updates."
      exit 0 ;;
    *) shift ;;
  esac
done
for timesheet_command in curl python3 docker; do
  command -v "$timesheet_command" >/dev/null || { echo "Please install $timesheet_command first." >&2; exit 1; }
done
docker compose version >/dev/null
docker info >/dev/null
timesheet_tmp=$(mktemp -d)
trap 'rm -rf "$timesheet_tmp"' EXIT
timesheet_encoded_ref=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""))' "$timesheet_ref")
echo "Downloading Timesheet Clerk from GitHub…"
curl --retry 3 -fsSL "https://api.github.com/repos/bramvrensen/Hermes-Timesheet-Clerk/commits/$timesheet_encoded_ref" -o "$timesheet_tmp/commit.json"
timesheet_revision=$(python3 -c 'import json,sys,re; s=json.load(open(sys.argv[1]))["sha"]; assert re.fullmatch("[0-9a-f]{40}",s); print(s)' "$timesheet_tmp/commit.json")
curl --retry 3 -fsSL "https://codeload.github.com/bramvrensen/Hermes-Timesheet-Clerk/tar.gz/$timesheet_revision" -o "$timesheet_tmp/source.tar.gz"
mkdir "$timesheet_tmp/source"
tar -xzf "$timesheet_tmp/source.tar.gz" --strip-components=1 -C "$timesheet_tmp/source"
python3 "$timesheet_tmp/source/deploy/install.py" --source "$timesheet_tmp/source" --revision "$timesheet_revision" "${timesheet_args[@]}"
