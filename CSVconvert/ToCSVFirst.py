import sarracen
import glob
import os
import pandas as pd

# ── Configuration ────────────────────────────────────────────────────────────
INPUT_DIR    = r"\\wsl.localhost\Ubuntu\home\mboyle\solarsystem"  # input folder for your dump files
DUMP_PATTERN = "solarsystem1_*"   # glob pattern for your dump files
OUTPUT_DIR   = "csv_output"       # folder where CSVs will be saved
# ─────────────────────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

if INPUT_DIR:
    dump_pattern = os.path.join(INPUT_DIR, DUMP_PATTERN)
else:
    dump_pattern = DUMP_PATTERN

dump_files = sorted(glob.glob(dump_pattern))

if not dump_files:
    print(f"No dump files found matching pattern: {DUMP_PATTERN}")
else:
    print(f"Found {len(dump_files)} dump file(s)\n")

for dump in dump_files:
    try:
        # For a pure sink-particle simulation, read_phantom returns a list.
        # The first element is SPH particles (empty here), the last is sinks.
        result = sarracen.read_phantom(dump, separate_types='all')

        # Grab the sink particle dataframe — last item in the returned list
        sdf_sinks = result[-1]

        if sdf_sinks is None or len(sdf_sinks) == 0:
            print(f"  [{dump}] No sink particles found, skipping.")
            continue

        # Get code unit conversion parameters from metadata
        udist = float(sdf_sinks.params.get('udist', 1.0))
        AU_IN_CM = 1.495978707e13
        
        # Start with all columns from the sink dataframe
        df = sdf_sinks.copy()
        
        # Convert position coordinates to AU
        if 'x' in df.columns:
            df['x'] = df['x'] * udist / AU_IN_CM
        if 'y' in df.columns:
            df['y'] = df['y'] * udist / AU_IN_CM
        if 'z' in df.columns:
            df['z'] = df['z'] * udist / AU_IN_CM
        
        # Rename position columns for clarity
        if 'x' in df.columns:
            df.rename(columns={'x': 'x_au'}, inplace=True)
        if 'y' in df.columns:
            df.rename(columns={'y': 'y_au'}, inplace=True)
        if 'z' in df.columns:
            df.rename(columns={'z': 'z_au'}, inplace=True)

        # Save to CSV
        out_name = os.path.join(OUTPUT_DIR, os.path.basename(dump) + ".csv")
        df.to_csv(out_name, index=False)

        # Print a quick summary
        print(f"  [{dump}] {len(df)} sink particles → {out_name}")
        print(f"    Simulation time: {sdf_sinks.params.get('time', 'N/A')}")
        print(f"    Columns: {list(df.columns)}\n")

    except Exception as e:
        print(f"  [{dump}] ERROR: {e}\n")

print("Done.")