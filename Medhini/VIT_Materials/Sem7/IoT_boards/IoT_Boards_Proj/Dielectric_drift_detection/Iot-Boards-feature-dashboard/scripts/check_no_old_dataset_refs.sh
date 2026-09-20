#!/usr/bin/env bash
#
# Step 11: search the repository for anything tying it to the old,
# pre-Phase-0 dataset or simulation assumptions.
#
# Excludes vendored/virtualenv directories (iotboard/) and __pycache__,
# since matches there are third-party library internals, not application
# code, and would just be noise.
#
# Run from the repo root: bash scripts/check_no_old_dataset_refs.sh
# Exit code 0 = clean, 1 = found something to review.

set -uo pipefail

EXCLUDE_DIRS=(--exclude-dir=iotboard --exclude-dir=__pycache__ --exclude-dir=.git)
SEARCH_PATHS=(app.py config.py database routes simulator dataset static templates)

# Patterns that would indicate a leftover from the old 2,200-row dataset /
# old fixed-value simulator, based on what demo_generator.py used to hard-code
# before the Phase 0 rewrite (ANTENNAS, FREQUENCIES_MHZ, DEFAULT_CONTAINER_ID).
PATTERNS=(
    "2200"
    "2,200 row"
    "2,200-row"
    "old dataset"
    "\bC001\b"
    "FREQUENCIES_MHZ"
    "\bANTENNAS\s*="
    "DEFAULT_CONTAINER_ID"
    "433\.0"
    "868\.0"
    "915\.0"
    "2400\.0"
)

found=0
for pattern in "${PATTERNS[@]}"; do
    matches=$(grep -rnE "${EXCLUDE_DIRS[@]}" "$pattern" "${SEARCH_PATHS[@]}" 2>/dev/null)
    if [ -n "$matches" ]; then
        echo "FOUND pattern '$pattern':"
        echo "$matches"
        echo
        found=1
    fi
done

if [ "$found" -eq 0 ]; then
    echo "Clean: no references to the old dataset or old simulation constants found."
    exit 0
else
    echo "Review the matches above - one or more may be a leftover old-dataset dependency."
    exit 1
fi
