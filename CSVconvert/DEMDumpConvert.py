import sarracen
import glob
import os
import pandas as pd
import numpy as np

# ── Configuration ─────────────────────────────────────────────────────────────
INPUT_DIR    = "/home/mboyle/Honours/sobol_mass_runs/sobol_20260629_132547_blender_vis_earth_aligned_np500/run_0001"
DUMP_PATTERN = "sobol_[0-9]*"

# Root folder for all DEM output (bodies as CSV, grains as .npz).
# Subfolders are created automatically:
#   DEMCSVs\<sim_name>\<run_name>_bodies_output\   one <dump>.csv per dump
#   DEMCSVs\<sim_name>\<run_name>_grains_output\   one <dump>.npz per dump
# where <sim_name> is the simulation folder (parent of INPUT_DIR) and
# <run_name> is the last component of INPUT_DIR (e.g. run_0001).
BASE_OUTPUT_DIR = "/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs"

_run_name         = os.path.basename(INPUT_DIR.rstrip('/'))
_sim_name         = os.path.basename(os.path.dirname(INPUT_DIR.rstrip('/')))
BODIES_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, _sim_name, f"{_run_name}_bodies_output")
GRAINS_OUTPUT_DIR = os.path.join(BASE_OUTPUT_DIR, _sim_name, f"{_run_name}_grains_output")

# The first N_BODIES sinks are solar system bodies in this order when
# apophis_only=F (full solarsystem setup).  When apophis_only=T, N_BODIES=0.
# Auto-detected per dump from sink Reff layout; override here only if needed.
N_BODIES = None  # None = auto-detect; int = force (legacy/debug)
BODY_NAMES = [
    "Sun", "Mercury", "Venus", "Earth", "Moon",
    "Mars", "Jupiter", "Saturn", "Uranus", "Neptune",
]

# Sinks with h or Reff (in km, after unit conversion) below this threshold are
# treated as DEM grains rather than solar system bodies.  Grain Reff ~0.05 km;
# smallest real body (Moon) is ~1737 km — so 1 km cleanly divides them.
# Macro bodies store radius in h; Reff is 0 for planets and >0 for DEM grains.
GRAIN_REFF_THRESHOLD_KM = 1.0

# Visual scale for the DEM grain body-frame positions written to the grains npz.
# WHY THIS IS NECESSARY
# ─────────────────────
# Apophis is ~0.35 AU from Earth during the flyby.  At the solar-system
# SCALE=5000 used by the Blender scripts, that places it at ~1750 Blender
# units (BU) from the origin.  Float32 epsilon at 1750 BU is ~2e-4 BU, but
# the grain-to-grain separation is only ~5e-6 BU — so every grain collapses
# to exactly the same Blender coordinate.  The x_au values in the grains npz
# also cannot distinguish grains: all 64 print as the same value to 6 d.p.
#
# The fix: output body-frame positions (x_rel_km etc.) multiplied by
# GRAIN_VIS_SCALE into x_vis/y_vis/z_vis/Reff_vis keys of the grains npz.
# These stay near the Blender origin, so float32 has full precision, and
# the Blender DEM script uses them directly — no solar-system SCALE
# conversion needed.
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
MIN_DEM_GRAINS = None   # None = derive from np_apophis in sobol.setup; int = override
# ─────────────────────────────────────────────────────────────────────────────

AU_IN_CM = 1.495978707e13
KM_IN_CM = 1.0e5


def _parse_setup_flags(input_dir):
    """Read apophis_only, np_apophis, use_dem, use_dem_as_sinks from sobol.setup if present."""
    setup_path = os.path.join(input_dir, "sobol.setup")
    apophis_only = None
    np_apophis = None
    use_dem = None
    use_dem_as_sinks = None
    if not os.path.isfile(setup_path):
        return apophis_only, np_apophis, use_dem, use_dem_as_sinks
    with open(setup_path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            stripped = line.split("!", 1)[0].strip()
            if not stripped or "=" not in stripped:
                continue
            key, _, val = stripped.partition("=")
            key = key.strip().lower()
            val = val.strip()
            if not val:
                continue
            if key == "apophis_only":
                apophis_only = val.upper().startswith("T")
            elif key == "np_apophis":
                np_apophis = int(float(val))
            elif key == "use_dem":
                use_dem = val.upper().startswith("T")
            elif key == "use_dem_as_sinks":
                use_dem_as_sinks = val.upper().startswith("T")
    return apophis_only, np_apophis, use_dem, use_dem_as_sinks


def _dem_model(use_dem, use_dem_as_sinks):
    """'particle', 'sink' or None. No use_dem_as_sinks key = pre-merge setup, where use_dem meant sinks."""
    if use_dem_as_sinks:
        return "sink"
    if use_dem and use_dem_as_sinks is None:
        return "sink"
    if use_dem:
        return "particle"
    return None


def _particle_grains(sdf_parts):
    """DEM grain frame from idem particles: grain radius R = h (Mia fbc0e4e63)."""
    keep = sdf_parts["h"].values > 0
    if "itype" in sdf_parts.columns:
        keep &= sdf_parts["itype"].values == 2
    p = sdf_parts[keep]
    if "m" in p.columns:
        m = p["m"].values
    else:
        m = np.full(len(p), float(sdf_parts.params["massoftype_2"]))
    cols = {"x": p["x"].values, "y": p["y"].values, "z": p["z"].values,
            "h": p["h"].values, "Reff": p["h"].values, "m": m}
    for c in ("vx", "vy", "vz"):
        if c in p.columns:
            cols[c] = p[c].values
    return pd.DataFrame(cols)


def _detect_n_bodies(sdf_sinks, to_km, setup_apophis_only=None):
    """Return number of solar-system body sinks before the DEM grain block."""
    if setup_apophis_only is True:
        return 0

    reff_km = sdf_sinks["Reff"].values * to_km
    h_km = sdf_sinks["h"].values * to_km

    # DEM grains always have Reff populated; macro bodies use h and Reff=0.
    is_grain = reff_km > 0.0
    if is_grain.any():
        return int(np.argmax(is_grain))

    # No DEM grains: count macro bodies by h (planets), or none for grain-only setups.
    return int(np.sum(h_km >= GRAIN_REFF_THRESHOLD_KM))


_SETUP_APOPHIS_ONLY, _SETUP_NP_APOPHIS, _SETUP_USE_DEM, _SETUP_USE_DEM_AS_SINKS = _parse_setup_flags(INPUT_DIR)
_SETUP_DEM_MODEL = _dem_model(_SETUP_USE_DEM, _SETUP_USE_DEM_AS_SINKS)
if _SETUP_NP_APOPHIS is not None:
    _MIN_DEM_AUTO = max(10, _SETUP_NP_APOPHIS - max(50, _SETUP_NP_APOPHIS // 10))
else:
    _MIN_DEM_AUTO = 450
if MIN_DEM_GRAINS is None:
    MIN_DEM_GRAINS = _MIN_DEM_AUTO

_n_bodies_mode = "auto" if N_BODIES is None else str(N_BODIES)
print(
    f"DEMDumpConvert: {_sim_name}/{_run_name}\n"
    f"  setup: apophis_only={_SETUP_APOPHIS_ONLY}, np_apophis={_SETUP_NP_APOPHIS}, "
    f"use_dem={_SETUP_USE_DEM}, dem_model={_SETUP_DEM_MODEL}\n"
    f"  MIN_DEM_GRAINS={MIN_DEM_GRAINS}, N_BODIES={_n_bodies_mode}\n"
    f"  bodies → {BODIES_OUTPUT_DIR}\n"
    f"  grains → {GRAINS_OUTPUT_DIR}\n"
)

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
        udist     = float(sdf_sinks.params.get("udist", 1.0))  # code unit in cm
        utime_raw = sdf_sinks.params.get("utime")
        if utime_raw is None:
            print(f'  WARNING [{os.path.basename(dump)}]: "utime" not in params; time_s equals raw code-unit time.')
            utime_s = 1.0
        else:
            utime_s = float(utime_raw)
        time_code = float(sdf_sinks.params.get("time", 0.0))
        time_s    = time_code * utime_s
        to_km    = udist / KM_IN_CM   # code unit → km
        to_au    = udist / AU_IN_CM   # code unit → AU

        n_sinks  = len(sdf_sinks)
        if _SETUP_DEM_MODEL == "particle":
            # grains are idem particles; every sink is a solar-system body
            n_bodies = int(N_BODIES) if N_BODIES is not None else n_sinks
            g_particles = _particle_grains(result[0]) if len(result) > 1 else pd.DataFrame()
            n_dem = len(g_particles)
        else:
            n_bodies = (
                int(N_BODIES)
                if N_BODIES is not None
                else _detect_n_bodies(sdf_sinks, to_km, _SETUP_APOPHIS_ONLY)
            )
            n_dem = n_sinks - n_bodies

        if _SETUP_DEM_MODEL is None:
            print(f"  [{os.path.basename(dump)}] no DEM model in setup — no DEM grains, skipped")
            continue
        if _SETUP_NP_APOPHIS is not None and _SETUP_NP_APOPHIS <= 1:
            print(
                f"  [{os.path.basename(dump)}] np_apophis={_SETUP_NP_APOPHIS} "
                f"(single sink, not DEM lattice) — skipped"
            )
            continue

        if n_dem < MIN_DEM_GRAINS:
            print(f"  [{os.path.basename(dump)}] mini dump ({n_sinks} sinks, {n_dem} DEM grains) — skipped")
            continue

        # Sanity check: macro bodies use h; DEM grains use Reff.
        if n_bodies > 0:
            h_bodies = sdf_sinks["h"].iloc[:n_bodies].values * to_km
            if h_bodies.min() < GRAIN_REFF_THRESHOLD_KM:
                print(
                    f"  WARNING [{dump}]: some 'body' sink has h "
                    f"{h_bodies.min():.4f} km < threshold {GRAIN_REFF_THRESHOLD_KM} km. "
                    f"Check N_BODIES (detected {n_bodies})."
                )
        if n_dem > 0 and _SETUP_DEM_MODEL != "particle":
            reff_grains = sdf_sinks["Reff"].iloc[n_bodies:].values * to_km
            if reff_grains.max() > GRAIN_REFF_THRESHOLD_KM:
                print(
                    f"  WARNING [{dump}]: some 'grain' sink has Reff "
                    f"{reff_grains.max():.4f} km > threshold {GRAIN_REFF_THRESHOLD_KM} km. "
                    f"Check N_BODIES (detected {n_bodies})."
                )

        # ── Solar system bodies (rows 0 … n_bodies-1) ────────────────────────
        if n_bodies > 0:
            b = sdf_sinks.iloc[:n_bodies]
            bodies_df = pd.DataFrame({
                "name":   BODY_NAMES[: len(b)],
                "time_s": time_s,
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
        else:
            bodies_df = pd.DataFrame(
                columns=["name", "time_s", "x_au", "y_au", "z_au",
                         "x_km", "y_km", "z_km", "h", "Reff", "m"]
            )
            if _SETUP_APOPHIS_ONLY:
                print(
                    f"  [{os.path.basename(dump)}] apophis_only=T: "
                    f"bodies CSV = synthetic Apophis only (no Earth/Sun for Blender)"
                )

        # ── DEM grains (rows n_bodies … end) ─────────────────────────────────
        g = g_particles if _SETUP_DEM_MODEL == "particle" else sdf_sinks.iloc[n_bodies:]
        if len(g) == 0:
            print(f"  [{os.path.basename(dump)}] no DEM grains after body split — skipped")
            continue

        total_mass = g["m"].sum()
        com_x = (g["x"] * g["m"]).sum() / total_mass
        com_y = (g["y"] * g["m"]).sum() / total_mass
        com_z = (g["z"] * g["m"]).sum() / total_mass

        # Append a synthetic Apophis CoM row to the bodies CSV so existing
        # Blender scripts (which expect row 10 = Apophis) continue to work.
        apophis_row = {
            "name":  "Apophis",
            "time_s": time_s,
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

        def _optional(col):
            # Velocity and spin can be absent (mini dumps); NaN-fill keeps the key set fixed.
            if col in g.columns:
                return g[col].values.astype(np.float64)
            return np.full(n_dem, np.nan)

        # One array per field; schema documented in CLAUDE.md "Grains npz".
        # x_au is absolute: all grains agree to many d.p., so never place grains
        # with it. x_vis = x_rel_km * GRAIN_VIS_SCALE stays near the Blender
        # origin, where float32 object coordinates keep full precision.
        grains = {
            "grain_id": np.arange(n_dem, dtype=np.int64),
            "time_s":   np.float64(time_s),
            "x_au":     (g["x"].values * to_au).astype(np.float64),
            "y_au":     (g["y"].values * to_au).astype(np.float64),
            "z_au":     (g["z"].values * to_au).astype(np.float64),
            "x_km":     (g["x"].values * to_km).astype(np.float64),
            "y_km":     (g["y"].values * to_km).astype(np.float64),
            "z_km":     (g["z"].values * to_km).astype(np.float64),
            "x_rel_km": x_rel_km.astype(np.float64),
            "y_rel_km": y_rel_km.astype(np.float64),
            "z_rel_km": z_rel_km.astype(np.float64),
            "Reff_km":  reff_km.astype(np.float64),
            "h_km":     (g["h"].values * to_km).astype(np.float64),
            "x_vis":    (x_rel_km * GRAIN_VIS_SCALE).astype(np.float64),
            "y_vis":    (y_rel_km * GRAIN_VIS_SCALE).astype(np.float64),
            "z_vis":    (z_rel_km * GRAIN_VIS_SCALE).astype(np.float64),
            "Reff_vis": (reff_km * GRAIN_VIS_SCALE).astype(np.float64),
            "m":        g["m"].values.astype(np.float64),
            "vx":       _optional("vx"),
            "vy":       _optional("vy"),
            "vz":       _optional("vz"),
            "spinx":    _optional("spinx"),
            "spiny":    _optional("spiny"),
            "spinz":    _optional("spinz"),
        }

        # ── Write outputs: bodies CSV, grains npz ─────────────────────────────
        basename   = os.path.basename(dump)
        bodies_out = os.path.join(BODIES_OUTPUT_DIR, basename + ".csv")
        grains_out = os.path.join(GRAINS_OUTPUT_DIR, basename + ".npz")

        # Grains npz first: bodies are paired to grains by sorted position, so a
        # failed npz write must not leave an orphan bodies CSV.
        np.savez_compressed(grains_out, **grains)
        bodies_df.to_csv(bodies_out, index=False)

        time_val   = sdf_sinks.params.get("time", "N/A")
        mean_reff  = float(reff_km.mean())
        vis_extent = float(np.sqrt(
            (x_rel_km**2 + y_rel_km**2 + z_rel_km**2).max()
        )) * GRAIN_VIS_SCALE
        print(
            f"  [{basename}]  {n_sinks} sinks "
            f"({n_bodies} bodies + {n_dem} DEM grains)  t={time_val}\n"
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
