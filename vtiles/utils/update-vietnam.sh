#!/usr/bin/env bash

set -euo pipefail

# ============================================================
# Configuration
# ============================================================

PBF="vietnam-latest.osm.pbf"
OUTPUT_PBF="vietnam-update.osm.pbf"

BASE_URL="https://download.geofabrik.de/asia/vietnam-updates"

WORK_DIR=".vietnam-update"
DIFF_DIR="$WORK_DIR/diffs"
MERGED_CHANGES="$WORK_DIR/changes.osc.gz"
STATE_FILE="$WORK_DIR/state.txt"

# ============================================================
# Check dependencies
# ============================================================

command -v osmium >/dev/null 2>&1 || {
    echo "ERROR: osmium not found."
    exit 1
}

command -v curl >/dev/null 2>&1 || {
    echo "ERROR: curl not found."
    exit 1
}

if [[ ! -f "$PBF" ]]; then
    echo "ERROR: Input PBF not found: $PBF"
    exit 1
fi

# ============================================================
# Read local replication sequence
# ============================================================

echo "Reading local PBF replication sequence..."

LOCAL_SEQ=$(
    osmium fileinfo "$PBF" 2>/dev/null |
    sed -n \
        's/.*osmosis_replication_sequence_number=\([0-9]*\).*/\1/p' |
    head -n 1
)

if [[ -z "$LOCAL_SEQ" ]]; then
    echo "ERROR: Could not find replication sequence in $PBF"
    exit 1
fi

echo "Local sequence: $LOCAL_SEQ"

# ============================================================
# Get remote replication state
# ============================================================

mkdir -p "$DIFF_DIR"

echo
echo "Downloading replication state..."

curl -fL \
    --retry 5 \
    --retry-delay 2 \
    "$BASE_URL/state.txt" \
    -o "$STATE_FILE"

REMOTE_SEQ=$(
    grep '^sequenceNumber=' "$STATE_FILE" |
    cut -d= -f2 |
    tr -d '[:space:]'
)

# Geofabrik state.txt uses escaped colons:
#
#   timestamp=2026-10-06T20\:21\:06Z
#
# Remove only the backslashes, NOT the colons.
REMOTE_TIMESTAMP=$(
    grep '^timestamp=' "$STATE_FILE" |
    cut -d= -f2- |
    sed 's/\\//g' |
    tr -d '[:space:]'
)

if [[ -z "$REMOTE_SEQ" ]]; then
    echo "ERROR: Could not determine remote replication sequence."
    cat "$STATE_FILE"
    exit 1
fi

if [[ -z "$REMOTE_TIMESTAMP" ]]; then
    echo "ERROR: Could not determine remote replication timestamp."
    cat "$STATE_FILE"
    exit 1
fi

echo "Remote sequence: $REMOTE_SEQ"
echo "Remote timestamp: $REMOTE_TIMESTAMP"

# ============================================================
# Check whether update is needed
# ============================================================

if (( REMOTE_SEQ <= LOCAL_SEQ )); then
    echo
    echo "PBF is already up to date."
    echo "Local sequence : $LOCAL_SEQ"
    echo "Remote sequence: $REMOTE_SEQ"
    exit 0
fi

echo
echo "Updates required: $LOCAL_SEQ -> $REMOTE_SEQ"

# ============================================================
# Download replication changes
# ============================================================

for (( seq=LOCAL_SEQ + 1; seq<=REMOTE_SEQ; seq++ )); do

    # Convert sequence to Geofabrik replication path.
    #
    # 4924      -> 000/004/924.osc.gz
    # 123456    -> 000/123/456.osc.gz
    # 123456789  -> 123/456/789.osc.gz

    printf -v SEQ "%09d" "$seq"

    DIR1="${SEQ:0:3}"
    DIR2="${SEQ:3:3}"
    DIR3="${SEQ:6:3}"

    URL="$BASE_URL/$DIR1/$DIR2/$DIR3.osc.gz"
    OUTPUT="$DIFF_DIR/$seq.osc.gz"

    if [[ -s "$OUTPUT" ]]; then
        echo "Already downloaded: $seq"
        continue
    fi

    echo
    echo "Downloading: $seq"
    echo "  $URL"

    curl -fL \
        --retry 5 \
        --retry-delay 2 \
        "$URL" \
        -o "$OUTPUT"

done

# ============================================================
# Verify downloaded change files
# ============================================================

echo
echo "Checking change files..."

CHANGE_FILES=()

for (( seq=LOCAL_SEQ + 1; seq<=REMOTE_SEQ; seq++ )); do

    FILE="$DIFF_DIR/$seq.osc.gz"

    if [[ ! -s "$FILE" ]]; then
        echo "ERROR: Missing change file: $FILE"
        exit 1
    fi

    CHANGE_FILES+=("$FILE")

done

echo "Change files: ${#CHANGE_FILES[@]}"

# ============================================================
# Merge changes
# ============================================================

echo
echo "Merging change files..."

rm -f "$MERGED_CHANGES"

osmium merge-changes \
    --simplify \
    "${CHANGE_FILES[@]}" \
    -o "$MERGED_CHANGES"

if [[ ! -s "$MERGED_CHANGES" ]]; then
    echo "ERROR: Merged change file was not created."
    exit 1
fi

echo "Merged changes:"
ls -lh "$MERGED_CHANGES"

# ============================================================
# Apply changes
# ============================================================

echo
echo "Applying changes to PBF..."

rm -f "$OUTPUT_PBF"

osmium apply-changes \
    "$PBF" \
    "$MERGED_CHANGES" \
    -o "$OUTPUT_PBF" \
    --output-header="osmosis_replication_base_url=$BASE_URL" \
    --output-header="osmosis_replication_sequence_number=$REMOTE_SEQ" \
    --output-header="osmosis_replication_timestamp=$REMOTE_TIMESTAMP"

if [[ ! -s "$OUTPUT_PBF" ]]; then
    echo "ERROR: Output PBF was not created."
    exit 1
fi

# ============================================================
# Verify output
# ============================================================

echo
echo "Verifying output PBF..."

osmium fileinfo "$OUTPUT_PBF"

OUTPUT_SEQ=$(
    osmium fileinfo "$OUTPUT_PBF" 2>/dev/null |
    sed -n \
        's/.*osmosis_replication_sequence_number=\([0-9]*\).*/\1/p' |
    head -n 1
)

OUTPUT_TIMESTAMP=$(
    osmium fileinfo "$OUTPUT_PBF" 2>/dev/null |
    sed -n \
        's/.*osmosis_replication_timestamp=\([^ ]*\).*/\1/p' |
    head -n 1
)

if [[ -z "$OUTPUT_SEQ" ]]; then
    echo
    echo "ERROR: Output PBF has no replication sequence."
    exit 1
fi

if [[ "$OUTPUT_SEQ" != "$REMOTE_SEQ" ]]; then
    echo
    echo "ERROR: Replication sequence mismatch."
    echo "Expected: $REMOTE_SEQ"
    echo "Got     : $OUTPUT_SEQ"
    exit 1
fi

# ============================================================
# Success
# ============================================================

echo
echo "============================================================"
echo "UPDATE SUCCESSFUL"
echo "============================================================"
echo
echo "Input PBF:"
echo "  $PBF"
echo "  sequence: $LOCAL_SEQ"
echo
echo "Output PBF:"
echo "  $OUTPUT_PBF"
echo "  sequence: $OUTPUT_SEQ"
echo
echo "Replication:"
echo "  $LOCAL_SEQ -> $REMOTE_SEQ"
echo
echo "Timestamp:"
echo "  $REMOTE_TIMESTAMP"
echo
echo "The original PBF has NOT been modified."
echo

# ============================================================
# Cleanup temporary files
# ============================================================

echo "Cleaning temporary files..."

rm -rf "$WORK_DIR"

echo "Done."