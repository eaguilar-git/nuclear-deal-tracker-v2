#!/usr/bin/env bash
# start_data_entry.sh
# ──────────────────────────────────────────────────────────────────────
# Convenience wrapper to start the data entry server with env vars set.
# Works from any directory — finds its own script location.
#
# Run with: ./start_data_entry.sh

set -e

# ── Find where this script lives, so we can find data_entry_server.py next to it ──
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# ── Find the credentials directory ──
CRED_DIR="$HOME/Documents/credentials_deal_tracker"
SVC_ACCT_FILE="$CRED_DIR/rugged-abacus-405804-effe0cb0fe9b.json"
API_KEY_FILE="$CRED_DIR/anthropic_key_v2.txt"

if [ ! -f "$SVC_ACCT_FILE" ]; then
    echo "ERROR: cannot find service account file at $SVC_ACCT_FILE"
    echo "       Update this script to point at your credentials."
    exit 1
fi

# Anthropic key not strictly needed for data entry, but set for consistency
if [ -f "$API_KEY_FILE" ]; then
    export ANTHROPIC_API_KEY="$(cat "$API_KEY_FILE")"
fi

export GOOGLE_SERVICE_ACCOUNT_JSON="$(cat "$SVC_ACCT_FILE")"
export GOOGLE_SHEET_ID="1UHKrpeS56Bgt5ZQ2si6i9LunogM88V4VDKZ93PoqTeg"

echo "Env vars set."
echo "Starting data entry server from $SCRIPT_DIR..."
echo
cd "$SCRIPT_DIR"
exec python3 data_entry_server.py
