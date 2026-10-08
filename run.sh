#!/bin/bash
# Start the Fight Analyzer web app and open it in the browser.
cd "$(dirname "$0")" && exec .venv/bin/python -m webapp "$@"
