#!/usr/bin/env zsh
# Usage: spikes/library-scale/run.sh <script.py> [args...]
# Runs a spike script with the backend's own virtualenv (+ numpy from .pydeps, installed once with:
#   uv pip install --python backend/.venv/bin/python --target spikes/library-scale/.pydeps numpy ).
HERE="${0:A:h}"
export PYTHONPATH="${SPIKE_PYDEPS:-$HERE/.pydeps}:$HERE:${PYTHONPATH:-}"
exec "$HERE/../../backend/.venv/bin/python" "$HERE/$@"
