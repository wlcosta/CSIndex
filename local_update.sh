#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Working tree is not clean. Commit, stash, or discard changes before a DBLP update." >&2
  exit 1
fi

if [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then
  PYTHON_BIN="$ROOT/.venv/Scripts/python.exe"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT/.venv/bin/python"
else
  echo "Could not find .venv Python. Create it and install requirements first." >&2
  exit 1
fi

timestamp="$(date +%Y%m%d-%H%M%S)"
backup_dir="$ROOT/local-backups/$timestamp"
log_dir="$ROOT/update-logs"
log_file="$log_dir/dblp-update-$timestamp.log"
mkdir -p "$backup_dir/data" "$log_dir" "$ROOT/cache/dblp" "$ROOT/cache/arxiv" "$ROOT/cache/profs"

cp data/*-out-*.csv "$backup_dir/data/" 2>/dev/null || true
cp statistics.html profs.html "$backup_dir/" 2>/dev/null || true
if [[ -d cache/dblp ]]; then
  cp -R cache/dblp "$backup_dir/dblp-cache"
fi

exec > >(tee "$log_file") 2>&1

echo "Started: $(date -Iseconds)"
echo "Python: $PYTHON_BIN"
"$PYTHON_BIN" --version
export PYTHONUTF8=1

cd "$ROOT/data"
PYTHON="$PYTHON_BIN" ./rundblp
PYTHON="$PYTHON_BIN" ./runall
"$PYTHON_BIN" ../dblp.py -test

if find "$ROOT/data" -name '*-out-*.csv' -size 0 | grep -q .; then
  echo "One or more generated CSV files are empty." >&2
  exit 1
fi

echo "Completed: $(date -Iseconds)"
echo "Log: $log_file"
echo "Backup: $backup_dir"
