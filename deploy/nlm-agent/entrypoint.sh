#!/bin/sh
# Headful browser needs a display; xvfb-run deadlocks as a docker entrypoint
# (measured 2026-09-01), so start Xvfb explicitly and exec the agent.
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
export DISPLAY=:99
sleep 1
exec python3 /agent/nlm_agent.py "$@"
