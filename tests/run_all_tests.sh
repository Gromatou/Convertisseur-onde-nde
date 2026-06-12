#!/usr/bin/env bash
# =========================================================================
# run_all_tests.sh  —  Full ONDE↔NDE converter test workflow
# =========================================================================
#
# This script orchestrates the complete end-to-end test suite:
#
#   1. Generate reference files (tests/generate_reference_ut.py)
#   2. Print browser-based conversion instructions
#   3. Run the comparison script to validate converter output
#
# Usage:
#   bash tests/run_all_tests.sh
#
# The converter itself runs in the browser (JavaScript + h5wasm). This test
# workflow validates the converter's output against a known-correct reference.
#
# Steps:
#   a) Generate reference NDE and ONDE files using Python/h5py
#   b) Instruct the user to convert the NDE → ONDE in the browser
#   c) Compare the browser-generated ONDE output against the expected reference
#
# Prerequisites:
#   - Python 3 with h5py (pip install h5py numpy)
#   - A browser that can open index.html (the converter)
# =========================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FIXTURES_DIR="$SCRIPT_DIR/fixtures"

# Colours for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Colour

echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║       ONDE ↔ NDE Converter — Test Suite                     ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Generate reference files ─────────────────────────────────────
echo -e "${YELLOW}[Step 1/3] Generating reference files...${NC}"
if python3 "$SCRIPT_DIR/generate_reference_ut.py"; then
    echo -e "  ${GREEN}✓ Reference files generated${NC}"
else
    echo -e "  ${RED}✗ Failed to generate reference files${NC}"
    exit 1
fi
echo ""

# ── Step 2: Browser conversion instructions ──────────────────────────────
echo -e "${YELLOW}[Step 2/3] Browser conversion step${NC}"
echo ""
echo -e "${CYAN}  ┌──────────────────────────────────────────────────────────┐${NC}"
echo -e "${CYAN}  │  MANUAL STEP REQUIRED                                    │${NC}"
echo -e "${CYAN}  │                                                          │${NC}"
echo -e "${CYAN}  │  1. Open ${PROJECT_DIR}/index.html in a browser.         │${NC}"
echo -e "${CYAN}  │                                                          │${NC}"
echo -e "${CYAN}  │  2. Load the NDE reference file:                         │${NC}"
echo -e "${CYAN}  │     ${FIXTURES_DIR}/reference_ut.nde             │${NC}"
echo -e "${CYAN}  │                                                          │${NC}"
echo -e "${CYAN}  │  3. Click the NDE → ONDE Convert button.                  │${NC}"
echo -e "${CYAN}  │                                                          │${NC}"
echo -e "${CYAN}  │  4. Save the converted file as:                          │${NC}"
echo -e "${CYAN}  │     ${FIXTURES_DIR}/converter_output.onde        │${NC}"
echo -e "${CYAN}  │                                                          │${NC}"
echo -e "${CYAN}  │  5. Return to this terminal and press ENTER to continue. │${NC}"
echo -e "${CYAN}  └──────────────────────────────────────────────────────────┘${NC}"
echo ""

# Wait for user
read -r -p "Press ENTER after saving converter_output.onde..."

# Verify the converter output exists
if [ ! -f "$FIXTURES_DIR/converter_output.onde" ]; then
    echo -e "${RED}  ✗ converter_output.onde not found at ${FIXTURES_DIR}/${NC}"
    echo -e "${YELLOW}    Please run the browser conversion and save the file.${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓ converter_output.onde found${NC}"
echo ""

# ── Step 3: Run comparison ───────────────────────────────────────────────
echo -e "${YELLOW}[Step 3/3] Running comparison script...${NC}"
echo ""

if python3 "$SCRIPT_DIR/compare_reference.py" \
    "$FIXTURES_DIR/converter_output.onde" \
    "$FIXTURES_DIR/reference_ut_expected.onde"; then
    echo -e "${GREEN}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║          ALL CHECKS PASSED ✓                           ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════╝${NC}"
    exit 0
else
    echo -e "${RED}╔════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║          SOME CHECKS FAILED ✗                           ║${NC}"
    echo -e "${RED}╚════════════════════════════════════════════════════════╝${NC}"
    exit 1
fi
