import sarracen
import glob
import os
import pandas as pd
import numpy as np

# ── Configuration ─────────────────────────────────────────────────────────────
INPUT_DIR    = "//wsl.localhost/Ubuntu/home/mboyle/Honours/DEMTrial"
DUMP_PATTERN = "demtrial_*"

# Two output folders: bodies are compatible with existing Blender scripts
BODIES_OUTPUT_DIR = "dem_bodies_output"   # 10 solar system bodies + Apophis CoM
GRAINS_OUTPUT_DIR = "dem_grains_output"   # individual Apophis DEM grains

# The first N_BODIES sinks are solar system bodies in this order.
# Matches PHANTOM's solarsystem setup sink order.
N_BODIES = 10
BODY_NAMES = [
    "Sun", "Mercury", "Venus", "Earth", "Moon",
    "Mars", "Jupiter", "Saturn", "Uranus", "Neptune",
]

# Sinks with Reff (in km, after unit conversion) below this threshold are
# treated as DEM grains rather than solar system bodies.  Grain Reff ~0.05 km;
# smallest real body (Moon) is ~1737 km — so 1 km cleanly divides them.
# Used only as a sanity-check; N_BODIES is the primary classifier.
GRAIN_REFF_THRESHOLD_KM = 1.0

# Visual scale for the DEM grain body-frame positions written to the CSV.
# WHY THIS IS NECESSARY
# ─────────────────────
# Apophis is ~0.35 AU from Earth during the flyby.  At the solar-system
# SCALE=5000 used by the Blender scripts, that places it at ~1750 Blender
# units (BU) from the origin.  Float32 epsilon at 1750 BU is ~2e-4 BU, but
# the grain-to-grain separation is only ~5e-6 BU — so every grain collapses
# to exactly the same Blender coordinate.  The x_au columns in the CSV also
# cannot distinguish grains: all 64 print as the same value to 6 d.p.
#
# The fix: output body-frame positions (x_rel_km etc.) multiplied by
# GRAIN_VIS_SCALE into x_vis/y_vis/z_vis/Reff_vis columns.  These stay near
# the Blender origin, so float32 has full precision, and the Blender DEM
# script uses them directly — no solar-system SCALE conversion needed.
#
# HOW TO CHOOSE THE VALUE
# ───────────────────────
# Apophis physical radius ≈ 0.17 km; grain Reff ≈ 0.048 km.
# GRAIN_VIS_SCALE=50 → body spans ~15 BU, grain radius ~2.4 BU (visible,
# tightly packed as expected for a rubble pile).  Adjust freely — this
# visualisation is not to scale by design.
GRAIN_VIS_SCALE = 50.0

# PHANTOM writes two dump types:
#   Full dumps  (every nfulldump timesteps) — all 74 sinks present.
#   Mini dumps  (all others)               — only ~17 sinks in the file;
#               the DEM grain block is incomplete and unusable.
# Dumps with fewer than MIN_DEM_GRAINS DEM particles are treated as mini
# dumps and skipped.  Set to just below np_apophis (64).
MIN_DEM_GRAINS = 60
# ─────────────────────────────────────────────────────────────────────────────

AU_IN_CM = 1.495978707e13
KM_IN_CM = 1.0e5

os.makedirs(BODIES_OUTPUT_DIR, exist_ok=True)
os.makedirs(GRAINS_OUTPUT_DIR, exist_ok=True)

dump_pattern = os.path.join(INPUT_DIR, DUMP_PATTERN)
dump_files = sorted(glob.glob(dump_pattern))

if not dump_files:
    print(f"No dump files found matching: {dump_pattern}")
else:
    print(f"Found {len(dump_files)} dump file(s)\n")

for dump in dump_files:
    try:
        result = sarracen.read_phantom(dump, separate_types="all")
        sdf_sinks = result[-1]

        if sdf_sinks is None or len(sdf_sinks) == 0:
            print(f"  [{dump}] No sink particles found, skipping.")
            continue

        # Unit conversions
        udist    = float(sdf_sinks.params.get("udist", 1.0))  # code unit in cm
        to_km    = udist / KM_IN_CM   # code unit → km
        to_au    = udist / AU_IN_CM   # code unit → AU

        n_sinks  = len(sdf_sinks)
        n_dem    = n_sinks - N_BODIES   # number of DEM grains (should be 64)

        if n_dem < MIN_DEM_GRAINS:
            print(f"  [{os.path.basename(dump)}] mini dump ({n_sinks} sinks, {n_dem} DEM grains) — skipped")
            continue

        # Sanity check: confirm the split looks right via Reff threshold
        reff_bodies = sdf_sinks["Reff"].iloc[:N_BODIES].values * to_km
        reff_grains = sdf_sinks["Reff"].iloc[N_BODIES:].values * to_km
        if reff_bodies.min() < GRAIN_REFF_THRESHOLD_KM:
            print(
                f"  WARNING [{dump}]: some 'body' sink has Reff "
                f"{reff_bodies.min():.4f} km < threshold {GRAIN_REFF_THRESHOLD_KM} km. "
                f"Check N_BODIES."
            )
        if reff_grains.max() > GRAIN_REFF_THRESHOLD_KM:
            print(
                f"  WARNING [{dump}]: some 'grain' sink has Reff "
                f"{reff_grains.max():.4f} km > threshold {GRAIN_REFF_THRESHOLD_KM} km. "
                f"Check N_BODIES."
            )

        # ── Solar system bodies (rows 0 … N_BODIES-1) ────────────────────────
        b = sdf_sinks.iloc[:N_BODIES]

        bodies_df = pd.DataFrame({
            "name":   BODY_NAMES[: len(b)],
            "x_au":   b["x"].values * to_au,
            "y_au":   b["y"].values * to_au,
            "z_au":   b["z"].values * to_au,
            "x_km":   b["x"].values * to_km,
            "y_km":   b["y"].values * to_km,
            "z_km":   b["z"].values * to_km,
            # For solar system bodies PHANTOM stores the physical radius in h;
            # Reff is 0 for macro bodies and only populated for DEM grains.
            "h":      b["h"].values * to_km,    # physical radius (km) for bodies
            "Reff":   b["h"].values * to_km,    # alias so Blender scripts can use Reff column
            "m":      b["m"].values,
        })

        # ── DEM grains (rows N_BODIES … end) ─────────────────────────────────
        g = sdf_sinks.iloc[N_BODIES:]

        total_mass = g["m"].sum()
        com_x = (g["x"] * g["m"]).sum() / total_mass
        com_y = (g["y"] * g["m"]).sum() / total_mass
        com_z = (g["z"] * g["m"]).sum() / total_mass

        # Append a synthetic Apophis CoM row to the bodies CSV so existing
        # Blender scripts (which expect row 10 = Apophis) continue to work.
        apophis_row = {
            "name":  "Apophis",
            "x_au":  com_x * to_au,
            "y_au":  com_y * to_au,
            "z_au":  com_z * to_au,
            "x_km":  com_x * to_km,
            "y_km":  com_y * to_km,
            "z_km":  com_z * to_km,
            "h":     float(g["h"].mean()    * to_km),
            "Reff":  float(g["Reff"].mean() * to_km),
            "m":     float(total_mass),
        }
        bodies_df = pd.concat(
            [bodies_df, pd.DataFrame([apophis_row])], ignore_index=True
        )

        # Body-frame positions in km (relative to Apophis CoM)
        x_rel_km = (g["x"].values - com_x) * to_km
        y_rel_km = (g["y"].values - com_y) * to_km
        z_rel_km = (g["z"].values - com_z) * to_km
        reff_km  = g["Reff"].values * to_km

        # Per-grain DataFrame with both absolute (AU) and CoM-relative (km) positions
        grains_df = pd.DataFrame({
            "grain_id":   range(n_dem),
            # Absolute AU positions — only useful for locating Apophis in the
            # solar system; DO NOT use to position individual grains in Blender
            # (all 64 values are identical to 6 d.p. and float32 collapses them).
            "x_au":       g["x"].values * to_au,
            "y_au":       g["y"].values * to_au,
            "z_au":       g["z"].values * to_au,
            "x_km":       g["x"].values * to_km,
            "y_km":       g["y"].values * to_km,
            "z_km":       g["z"].values * to_km,
            # Body-frame positions (km) relative to Apophis CoM.
            # Use these — not x_au — whenever computing grain separation.
            "x_rel_km":   x_rel_km,
            "y_rel_km":   y_rel_km,
            "z_rel_km":   z_rel_km,
            "Reff_km":    reff_km,
            "h_km":       g["h"].values * to_km,
            # Pre-scaled body-frame coordinates for direct use in Blender.
            # x_vis = x_rel_km * GRAIN_VIS_SCALE, kept near the origin so
            # float32 has full precision (~1e-7 BU at these magnitudes vs
            # ~2e-4 BU at 1750 BU where Apophis sits in solar-system scale).
            # Use x_vis/y_vis/z_vis as the Blender object location;
            # use Reff_vis as the sphere radius.
            "x_vis":      x_rel_km * GRAIN_VIS_SCALE,
            "y_vis":      y_rel_km * GRAIN_VIS_SCALE,
            "z_vis":      z_rel_km * GRAIN_VIS_SCALE,
            "Reff_vis":   reff_km  * GRAIN_VIS_SCALE,
            "m":          g["m"].values,
            # Velocity and spin are only present in full dumps (every nfulldump
            # timesteps).  Mini dumps omit them; fill with NaN so the CSV
            # schema stays consistent across all frames.
            "vx":    g["vx"].values    if "vx"    in g.columns else np.nan,
            "vy":    g["vy"].values    if "vy"    in g.columns else np.nan,
            "vz":    g["vz"].values    if "vz"    in g.columns else np.nan,
            "spinx": g["spinx"].values if "spinx" in g.columns else np.nan,
            "spiny": g["spiny"].values if "spiny" in g.columns else np.nan,
            "spinz": g["spinz"].values if "spinz" in g.columns else np.nan,
        })

        # ── Write CSVs ────────────────────────────────────────────────────────
        basename   = os.path.basename(dump)
        bodies_out = os.path.join(BODIES_OUTPUT_DIR, basename + ".csv")
        grains_out = os.path.join(GRAINS_OUTPUT_DIR, basename + ".csv")

        bodies_df.to_csv(bodies_out, index=False)
        grains_df.to_csv(grains_out, index=False)

        time_val   = sdf_sinks.params.get("time", "N/A")
        mean_reff  = float(reff_km.mean())
        vis_extent = float(np.sqrt(
            (x_rel_km**2 + y_rel_km**2 + z_rel_km**2).max()
        )) * GRAIN_VIS_SCALE
        print(
            f"  [{basename}]  {n_sinks} sinks "
            f"({N_BODIES} bodies + {n_dem} DEM grains)  t={time_val}\n"
            f"    Apophis CoM: "
            f"({com_x*to_au:.6f}, {com_y*to_au:.6f}, {com_z*to_au:.6f}) AU\n"
            f"    Mean grain Reff: {mean_reff:.4f} km "
            f"Reff_vis: {mean_reff*GRAIN_VIS_SCALE:.2f} BU\n"
            f"    Body max radius (vis): {vis_extent:.2f} BU "
            f"(GRAIN_VIS_SCALE={GRAIN_VIS_SCALE})\n"
            f"    Written: {bodies_out}\n"
            f"            {grains_out}\n"
        )

    except Exception as e:
        print(f"  [{dump}] ERROR: {e}\n")

print("Done.")
