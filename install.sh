#!/usr/bin/env bash
# PG3/PG3x install hook. PG3 installs requirements.txt automatically, but do it
# explicitly so a manual clone-and-run also works.
set -e
python3 -m pip install --user -r requirements.txt
