#!/usr/bin/env bash
# Full extraction on this host: raw dump (needs x86_64), then icons.
source "$(dirname "$0")/lib.sh"
"$ROOT/scripts/dump.sh"
"$ROOT/scripts/icons.sh"
