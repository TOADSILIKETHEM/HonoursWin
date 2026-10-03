#!/usr/bin/env python3
"""One PHANTOM DEM dump -> one grain frame + bodies table.

Shared by CSVconvert/DEMDumpConvert.py (writes each frame to a grains npz +
bodies CSV) and the viz preprocess scripts' ``--input-mode dump`` (read the
dumps directly and never write the grains npz; Objective 2 scale). A frame's
``grains`` dict has exactly the keys and dtypes of the grains npz (schema:
Code/CLAUDE.md "Grains npz"); ``bodies`` is the bodies CSV table.

sarracen and pandas are imported inside the functions that read dumps, so
npz-mode callers (numpy only) can import this module without them.
"""

from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Tuple, Union

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# x_vis = body-frame km * GRAIN_VIS_SCALE. Apophis sits ~1750 Blender units
# from the origin at the solar-system SCALE, where float32 epsilon (~2e-4 BU)
# swamps the ~5e-6 BU grain spacing; body-frame coordinates stay near the
# origin at full precision. 50 -> body ~15 BU, grain radius ~2.4 BU.
from viz.constants import GRAIN_VIS_SCALE  # noqa: E402

AU_IN_CM = 1.495978707e13
KM_IN_CM = 1.0e5

# Sinks with h or Reff below this (km) are DEM grains, not solar-system bodies.
# Grain Reff ~0.05 km; smallest real body (Moon) ~1737 km.
GRAIN_REFF_THRESHOLD_KM = 1.0

# The first N sinks are these bodies, in this order, when apophis_only=F.
BODY_NAMES = [
    "Sun", "Mercury", "Venus", "Earth", "Moon",
    "Mars", "Jupiter", "Saturn", "Uranus", "Neptune",
]


def parse_setup_flags(run_dir) -> Tuple[Optional[bool], Optional[int], Optional[bool], Optional[bool]]:
    """Read apophis_only, np_apophis, use_dem, use_dem_as_sinks from sobol.setup if present."""
    setup_path = os.path.join(str(run_dir), "sobol.setup")
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


def dem_model(use_dem, use_dem_as_sinks) -> Optional[str]:
    """'particle', 'sink' or None. No use_dem_as_sinks key = pre-merge setup, where use_dem meant sinks.

    No setup flags at all (sobol.setup missing) = 'sink': keep the old sink auto-detect.
    """
    if use_dem is None and use_dem_as_sinks is None:
        return "sink"
    if use_dem_as_sinks:
        return "sink"
    if use_dem and use_dem_as_sinks is None:
        return "sink"
    if use_dem:
        return "particle"
    return None


def encounter_mode(run_dir) -> str:
    """'hyperbola' when the sobol runner wrote encounter.json (phantomflyby: Earth is the only sink)."""
    p = os.path.join(str(run_dir), "encounter.json")
    if not os.path.isfile(p):
        return "ephemeris"
    with open(p, encoding="utf-8") as fh:
        return json.load(fh).get("mode", "ephemeris")


@dataclass(frozen=True)
class SetupFlags:
    apophis_only: Optional[bool] = None
    np_apophis: Optional[int] = None
    use_dem: Optional[bool] = None
    use_dem_as_sinks: Optional[bool] = None
    encounter: str = "ephemeris"

    @property
    def dem_model(self) -> Optional[str]:
        return dem_model(self.use_dem, self.use_dem_as_sinks)

    @property
    def min_dem_grains_auto(self) -> int:
        # Dumps with fewer DEM grains are mini dumps (incomplete grain block).
        if self.np_apophis is None:
            return 450
        return max(10, self.np_apophis - max(50, self.np_apophis // 10))

    @property
    def body_names(self) -> list:
        # phantomflyby adds exactly one sink, the Earth perturber.
        return ["Earth"] if self.encounter == "hyperbola" else BODY_NAMES


def read_setup_flags(run_dir) -> SetupFlags:
    apophis_only, np_apophis, use_dem, use_dem_as_sinks = parse_setup_flags(run_dir)
    return SetupFlags(apophis_only, np_apophis, use_dem, use_dem_as_sinks, encounter_mode(run_dir))


def particle_grains(sdf_parts):
    """DEM grain frame from idem particles: grain radius R = h (Mia fbc0e4e63)."""
    import pandas as pd

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
    for c in ("iorig", "vx", "vy", "vz"):
        if c in p.columns:
            cols[c] = p[c].values
    return pd.DataFrame(cols)


def detect_n_bodies(sdf_sinks, to_km, setup_apophis_only=None) -> int:
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


@dataclass
class DumpFrame:
    name: str  # dump basename, e.g. "sobol_00012"
    grains: dict  # grains-npz keys -> arrays
    bodies: Any  # pandas.DataFrame, bodies-CSV columns (+ synthetic Apophis row)
    n_sinks: int
    n_bodies: int
    n_dem: int
    time_param: Any  # dump params["time"] (code units), or "N/A"
    com_au: Tuple[float, float, float]


def dump_paths(run_dir, prefix: str = "sobol") -> list:
    return sorted(glob.glob(os.path.join(str(run_dir), f"{prefix}_[0-9]*")))


def frame_from_dump(dump, flags: SetupFlags, *, min_dem_grains: int,
                    n_bodies: Optional[int] = None) -> Union[DumpFrame, str]:
    """One dump -> DumpFrame, or the skip message (str) for a dump that has no usable grains.

    Warnings print. Read errors raise (iter_dump_frames logs them).
    """
    import pandas as pd
    import sarracen

    dump = str(dump)
    base = os.path.basename(dump)
    model = flags.dem_model
    body_names = flags.body_names

    result = sarracen.read_phantom(dump, separate_types="all")
    # sarracen returns a bare DataFrame when the dump has no sinks (apophis_only particle DEM)
    if isinstance(result, (list, tuple)):
        sdf_sinks = result[-1]
        sdf_parts = result[0] if len(result) > 1 else None
    else:
        sdf_sinks, sdf_parts = None, result

    if model != "particle" and (sdf_sinks is None or len(sdf_sinks) == 0):
        return f"  [{dump}] No sink particles found, skipping."
    sdf_meta = sdf_sinks if sdf_sinks is not None and len(sdf_sinks) > 0 else sdf_parts

    # Unit conversions
    udist = float(sdf_meta.params.get("udist", 1.0))  # code unit in cm
    utime_raw = sdf_meta.params.get("utime")
    if utime_raw is None:
        print(f'  WARNING [{base}]: "utime" not in params; time_s equals raw code-unit time.')
        utime_s = 1.0
    else:
        utime_s = float(utime_raw)
    time_code = float(sdf_meta.params.get("time", 0.0))
    time_s = time_code * utime_s
    to_km = udist / KM_IN_CM  # code unit -> km
    to_au = udist / AU_IN_CM  # code unit -> AU

    n_sinks = 0 if sdf_sinks is None else len(sdf_sinks)
    if model == "particle":
        # grains are idem particles; every sink is a solar-system body
        nb = int(n_bodies) if n_bodies is not None else n_sinks
        g_particles = particle_grains(sdf_parts) if sdf_parts is not None else pd.DataFrame()
        n_dem = len(g_particles)
    else:
        nb = (
            int(n_bodies)
            if n_bodies is not None
            else detect_n_bodies(sdf_sinks, to_km, flags.apophis_only)
        )
        n_dem = n_sinks - nb

    if model is None:
        return f"  [{base}] no DEM model in setup — no DEM grains, skipped"
    if flags.np_apophis is not None and flags.np_apophis <= 1:
        return (
            f"  [{base}] np_apophis={flags.np_apophis} "
            f"(single sink, not DEM lattice) — skipped"
        )
    if n_dem < min_dem_grains:
        return f"  [{base}] mini dump ({n_sinks} sinks, {n_dem} DEM grains) — skipped"

    # Sanity check: macro bodies use h; DEM grains use Reff.
    if nb > 0:
        h_bodies = sdf_sinks["h"].iloc[:nb].values * to_km
        if h_bodies.min() < GRAIN_REFF_THRESHOLD_KM:
            print(
                f"  WARNING [{dump}]: some 'body' sink has h "
                f"{h_bodies.min():.4f} km < threshold {GRAIN_REFF_THRESHOLD_KM} km. "
                f"Check N_BODIES (detected {nb})."
            )
    if n_dem > 0 and model != "particle":
        reff_grains = sdf_sinks["Reff"].iloc[nb:].values * to_km
        if reff_grains.max() > GRAIN_REFF_THRESHOLD_KM:
            print(
                f"  WARNING [{dump}]: some 'grain' sink has Reff "
                f"{reff_grains.max():.4f} km > threshold {GRAIN_REFF_THRESHOLD_KM} km. "
                f"Check N_BODIES (detected {nb})."
            )

    # ── Solar system bodies (rows 0 … nb-1) ──────────────────────────────────
    if flags.encounter == "hyperbola" and nb != 1:
        print(f"  WARNING [{base}]: hyperbola run with {nb} body sinks "
              f"(expected 1, the Earth perturber)")
    if nb > 0:
        b = sdf_sinks.iloc[:nb]
        bodies_df = pd.DataFrame({
            "name":   (list(body_names) + [f"sink{i + 1}" for i in range(len(body_names), len(b))])[: len(b)],
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
        if flags.apophis_only:
            print(
                f"  [{base}] apophis_only=T: "
                f"bodies CSV = synthetic Apophis only (no Earth/Sun for Blender)"
            )

    # ── DEM grains (rows nb … end) ───────────────────────────────────────────
    g = g_particles if model == "particle" else sdf_sinks.iloc[nb:]
    if len(g) == 0:
        return f"  [{base}] no DEM grains after body split — skipped"

    total_mass = g["m"].sum()
    com_x = (g["x"] * g["m"]).sum() / total_mass
    com_y = (g["y"] * g["m"]).sum() / total_mass
    com_z = (g["z"] * g["m"]).sum() / total_mass

    # Synthetic Apophis CoM row so Blender scripts (row 10 = Apophis) keep working.
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
    reff_km = g["Reff"].values * to_km

    def _optional(col):
        # Velocity and spin can be absent (mini dumps); NaN-fill keeps the key set fixed.
        if col in g.columns:
            return g[col].values.astype(np.float64)
        return np.full(n_dem, np.nan)

    # x_au is absolute: all grains agree to many d.p., so never place grains
    # with it. x_vis stays near the Blender origin (see GRAIN_VIS_SCALE).
    grains = {
        # Particle DEM: PHANTOM's iorig follows a grain through reorders.
        "grain_id": (g["iorig"].values if "iorig" in g.columns
                     else np.arange(n_dem)).astype(np.int64),
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
    return DumpFrame(
        name=base, grains=grains, bodies=bodies_df,
        n_sinks=n_sinks, n_bodies=nb, n_dem=n_dem,
        time_param=sdf_meta.params.get("time", "N/A"),
        com_au=(com_x * to_au, com_y * to_au, com_z * to_au),
    )


def iter_dump_frames(run_dir, *, prefix: str = "sobol", min_dem_grains: Optional[int] = None,
                     n_bodies: Optional[int] = None,
                     flags: Optional[SetupFlags] = None) -> Iterator[DumpFrame]:
    """Usable frames in dump order, one dump in memory at a time.

    Skips and read errors print (DEMDumpConvert.py's log lines) and never raise.
    """
    flags = flags if flags is not None else read_setup_flags(run_dir)
    mdg = flags.min_dem_grains_auto if min_dem_grains is None else min_dem_grains
    for dump in dump_paths(run_dir, prefix):
        try:
            frame = frame_from_dump(dump, flags, min_dem_grains=mdg, n_bodies=n_bodies)
        except Exception as e:
            print(f"  [{dump}] ERROR: {e}\n")
            continue
        if isinstance(frame, str):
            print(frame)
            continue
        yield frame


def iter_grain_frames(*, grains_dir=None, run_dir=None, bodies_dir=None, prefix: str = "sobol",
                      max_frames: Optional[int] = None) -> Iterator[Tuple[str, Mapping]]:
    """(frame name, grains mapping) per frame, for the viz preprocess scripts.

    npz mode (``grains_dir``): each ``*.npz`` via np.load, as before.
    dump mode (``run_dir``): iter_dump_frames, one dump at a time, never
    writing a grains npz. Blender still reads bodies CSVs (manifest
    ``bodies_csv_dir``), so each frame's bodies table is written to
    ``bodies_dir`` -- cleared of old ``*.csv`` first, since Blender pairs
    bodies with frames by sorted position.
    Raises FileNotFoundError when there is no frame at all.
    """
    if (grains_dir is None) == (run_dir is None):
        raise ValueError("pass exactly one of grains_dir (npz mode) / run_dir (dump mode)")
    if grains_dir is not None:
        files = sorted(glob.glob(os.path.join(str(grains_dir), "*.npz")))
        if not files:
            raise FileNotFoundError(
                f"No grain npz files in {grains_dir} (CSV-era folder? re-run DEMDumpConvert.py)"
            )
        for path in files[:max_frames]:
            with np.load(path) as d:
                yield Path(path).stem, d
        return
    if bodies_dir is None:
        raise ValueError("dump mode needs bodies_dir (Blender reads the bodies CSVs)")
    bodies_dir = Path(bodies_dir)
    bodies_dir.mkdir(parents=True, exist_ok=True)
    for old in bodies_dir.glob("*.csv"):
        old.unlink()
    n = 0
    for frame in iter_dump_frames(run_dir, prefix=prefix):
        # LF like DEMDumpConvert.py (WSL); pandas would write CRLF under the Windows .venv
        frame.bodies.to_csv(bodies_dir / f"{frame.name}.csv", index=False, lineterminator="\n")
        yield frame.name, frame.grains
        n += 1
        if max_frames is not None and n >= max_frames:
            return
    if n == 0:
        raise FileNotFoundError(f"No usable DEM dumps ({prefix}_[0-9]*) in {run_dir}")
