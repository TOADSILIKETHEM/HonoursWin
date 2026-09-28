#!/usr/bin/env bash
# run_sobol_phantom.sh (WSL-ready)

set -euo pipefail

# Resolve script directory so it works no matter where you launch it from.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INPUT_CSV="${SCRIPT_DIR}/sobol_input_matrix.csv"
OUTPUT_CSV="${SCRIPT_DIR}/sobol_outputs.csv"
BASE_SETUP="${SCRIPT_DIR}/apophis_base.setup"
BASE_INPUT="${SCRIPT_DIR}/apophis.in"
EXTRACT_SCRIPT="${SCRIPT_DIR}/extract_metric.py"

# CHANGE THIS to your actual PHANTOM install path in WSL:
PHANTOM_DIR="${PHANTOM_DIR:-/home/<your_wsl_user>/phantom}"

PHANTOMSETUP_BIN="${PHANTOM_DIR}/bin/phantomsetup"
PHANTOM_BIN="${PHANTOM_DIR}/bin/phantom"

# ---------- Preflight checks ----------
for f in "$INPUT_CSV" "$BASE_SETUP" "$BASE_INPUT" "$EXTRACT_SCRIPT"; do
  [[ -f "$f" ]] || { echo "Missing required file: $f" >&2; exit 1; }
done

[[ -x "$PHANTOMSETUP_BIN" ]] || { echo "Not executable or missing: $PHANTOMSETUP_BIN" >&2; exit 1; }
[[ -x "$PHANTOM_BIN" ]] || { echo "Not executable or missing: $PHANTOM_BIN" >&2; exit 1; }

command -v python3 >/dev/null 2>&1 || { echo "python3 not found in PATH" >&2; exit 1; }

# Use SPLASH if available; otherwise fail with a clear message.
if command -v splash >/dev/null 2>&1; then
  USE_SPLASH=1
else
  USE_SPLASH=0
  echo "WARNING: 'splash' not found. Install SPLASH or switch to your Python converter." >&2
  exit 1
fi

echo "run_id,density,closest_approach_au" > "$OUTPUT_CSV"

# Read all rows except header.
while IFS=',' read -r run_id density _; do
  # Skip blank/malformed rows.
  [[ -n "${run_id// }" && -n "${density// }" ]] || continue

  echo "Run ${run_id}: density = ${density} kg/m^3"

  RUN_DIR="${SCRIPT_DIR}/run_${run_id}"
  mkdir -p "$RUN_DIR"

  cp "$BASE_SETUP" "$RUN_DIR/apophis.setup"
  cp "$BASE_INPUT" "$RUN_DIR/apophis.in"

  # Update rho_apophis in setup file.
  sed -i "s/^rho_apophis.*/rho_apophis = ${density}/" "$RUN_DIR/apophis.setup"

  pushd "$RUN_DIR" >/dev/null

  # Step 1: Run PHANTOM
  "$PHANTOMSETUP_BIN" apophis > setup.log 2>&1
  "$PHANTOM_BIN" apophis.in > phantom.log 2>&1

  # Step 2: Convert dumps to CSV (SPLASH)
  if [[ "$USE_SPLASH" -eq 1 ]]; then
    splash to csv apophis_* >> splash.log 2>&1
  fi

  # Step 3: Extract metric
  python3 "$EXTRACT_SCRIPT" . > metric.txt
  CLOSEST="$(<metric.txt)"

  printf "%s,%s,%s\n" "$run_id" "$density" "$CLOSEST" >> "$OUTPUT_CSV"
  popd >/dev/null

  echo "  -> closest approach: ${CLOSEST} au"
done < <(tail -n +2 "$INPUT_CSV")

echo "All runs complete."
echo "Results written to: $OUTPUT_CSV"