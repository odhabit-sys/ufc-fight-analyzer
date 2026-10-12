#!/usr/bin/env bash
# Start the Fight Analyzer on macOS / Linux. The first run sets everything up
# (Python environment, dependencies, model weights); see launch.py.
cd "$(dirname "$0")" || exit 1

# Prefer the project's own environment, then any Python 3.12+ on the PATH.
for py in .venv/bin/python python3.13 python3.12 python3.14 python3 python; do
  if command -v "$py" >/dev/null 2>&1 &&
     "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    exec "$py" launch.py "$@"
  fi
done

cat >&2 <<'EOF'

==========================================================================
  ERROR: Python 3.12 or newer was not found.

  Install Python 3.12 or 3.13:
      macOS: https://www.python.org/downloads/macos/   or   brew install python@3.13
      Linux: your package manager, e.g.  sudo apt install python3.12 python3.12-venv
  Then run ./run.sh again.
==========================================================================
EOF
exit 1
