import os
import sys

import numpy as np

# Code/ on sys.path for viz.dump_frames. __file__ is set when run directly and
# when sobol/Analysis/run_demtocsv_batch.py execs this file.
_CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CODE_DIR not in sys.path:
    sys.path.insert(0, _CODE_DIR)
from viz.dump_frames import GRAIN_VIS_SCALE, dump_paths, iter_dump_frames, read_setup_flags  # noqa: E402
import honours_paths  # noqa: E402  (data folder for the default BASE_OUTPUT_DIR)

# ── Configuration ─────────────────────────────────────────────────────────────
INPUT_DIR    = "/home/mboyle/Honours/sobol_mass_runs/sobol_20260629_132547_blender_vis_earth_aligned_np500/run_0001"
DUMP_PREFIX  = "sobol"   # dumps are <DUMP_PREFIX>_[0-9]*

# Root folder for all DEM output (bodies as CSV, grains as .npz).
# Subfolders are created automatically:
#   DEMCSVs\<sim_name>\<run_name>_bodies_output\   one <dump>.csv per dump
#   DEMCSVs\<sim_name>\<run_name>_grains_output\   one <dump>.npz per dump
# where <sim_name> is the simulation folder (parent of INPUT_DIR) and
# <run_name> is the last component of INPUT_DIR (e.g. run_0001).
BASE_OUTPUT_DIR = honours_paths.data_dir() + "/DEMCSVs"  # default: Max's OneDrive data folder

_run_name         = os.path.basename(INPUT_DIR.rstrip('/'))
_sim_name         = os.path.basename(os.path.dirname(INPUT_DIR.rstrip('/')))
BODIES_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, _sim_name, f"{_run_name}_bodies_output")
GRAINS_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, _sim_name, f"{_run_name}_grains_output")

# Number of solar-system body sinks before the DEM grain block.
N_BODIES = None  # None = auto-detect per dump; int = force (legacy/debug)

# PHANTOM writes full dumps (every nfulldump steps, all grains) and mini dumps
# (incomplete grain block, unusable). Dumps with fewer DEM grains than this are
# treated as mini dumps and skipped.
MIN_DEM_GRAINS = None   # None = derive from np_apophis in sobol.setup; int = override
# ─────────────────────────────────────────────────────────────────────────────

# Per-dump logic (body/grain split, CoM, units, x_vis): viz/dump_frames.py,
# shared with the viz preprocess scripts' --input-mode dump.
_FLAGS = read_setup_flags(INPUT_DIR)
if MIN_DEM_GRAINS is None:
    MIN_DEM_GRAINS = _FLAGS.min_dem_grains_auto

_n_bodies_mode = "auto" if N_BODIES is None else str(N_BODIES)
print(
    f"DEMDumpConvert: {_sim_name}/{_run_name}\n"
    f"  setup: apophis_only={_FLAGS.apophis_only}, np_apophis={_FLAGS.np_apophis}, "
    f"use_dem={_FLAGS.use_dem}, dem_model={_FLAGS.dem_model}\n"
    f"  MIN_DEM_GRAINS={MIN_DEM_GRAINS}, N_BODIES={_n_bodies_mode}\n"
    f"  bodies → {BODIES_OUTPUT_DIR}\n"
    f"  grains → {GRAINS_OUTPUT_DIR}\n"
)

os.makedirs(BODIES_OUTPUT_DIR, exist_ok=True)
os.makedirs(GRAINS_OUTPUT_DIR, exist_ok=True)

dump_files = dump_paths(INPUT_DIR, DUMP_PREFIX)
if not dump_files:
    print(f"No dump files found matching: {os.path.join(INPUT_DIR, DUMP_PREFIX + '_[0-9]*')}")
else:
    print(f"Found {len(dump_files)} dump file(s)\n")

for frame in iter_dump_frames(INPUT_DIR, prefix=DUMP_PREFIX, min_dem_grains=MIN_DEM_GRAINS,
                              n_bodies=N_BODIES, flags=_FLAGS):
    bodies_out = os.path.join(BODIES_OUTPUT_DIR, frame.name + ".csv")
    grains_out = os.path.join(GRAINS_OUTPUT_DIR, frame.name + ".npz")
    try:
        # Grains npz first: bodies are paired to grains by sorted position, so a
        # failed npz write must not leave an orphan bodies CSV.
        np.savez_compressed(grains_out, **frame.grains)
        frame.bodies.to_csv(bodies_out, index=False)
    except Exception as e:
        print(f"  [{frame.name}] ERROR: {e}\n")
        continue

    g = frame.grains
    mean_reff = float(g["Reff_km"].mean())
    vis_extent = float(np.sqrt(
        (g["x_rel_km"]**2 + g["y_rel_km"]**2 + g["z_rel_km"]**2).max()
    )) * GRAIN_VIS_SCALE
    cx, cy, cz = frame.com_au
    print(
        f"  [{frame.name}]  {frame.n_sinks} sinks "
        f"({frame.n_bodies} bodies + {frame.n_dem} DEM grains)  t={frame.time_param}\n"
        f"    Apophis CoM: ({cx:.6f}, {cy:.6f}, {cz:.6f}) AU\n"
        f"    Mean grain Reff: {mean_reff:.4f} km "
        f"Reff_vis: {mean_reff*GRAIN_VIS_SCALE:.2f} BU\n"
        f"    Body max radius (vis): {vis_extent:.2f} BU "
        f"(GRAIN_VIS_SCALE={GRAIN_VIS_SCALE})\n"
        f"    Written: {bodies_out}\n"
        f"            {grains_out}\n"
    )

print("Done.")
