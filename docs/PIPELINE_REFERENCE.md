# Pipeline + format reference (Code)

On-demand detail moved verbatim from `CLAUDE.md` on 2026-09-25. Hub: `../CLAUDE.md`. Shared layout/names: `../../docs/SHARED_FACTS.md`.

## Data pipelines

### Pipeline A — Point-mass simulation (original)

```
WSL PHANTOM run  (solarsystem/)
  └─ solarsystem1_XXXXX  (binary, 11 sinks: Sun + 9 planets + Apophis point-mass)
        │  (legacy: solarsystem/ dumps no longer on disk; read with WSL python3)
        ▼
  CSVconvert/ToCSVFirst.py   (sarracen.read_phantom, udist → AU)
        │
        ▼
  csv_output/solarsystem1_XXXXX.csv   (11 rows)
        ▼
  BlenderConvert/OnlyEarth_ApophisTrueSize.py   (SCALE=5000, camera-centric handler)
        ▼
  Blender: 11 body spheres/meshes, solar-system scale
```

### Pipeline B — DEM rubble-pile (Sobol sweeps, current)

```
WSL PHANTOM Sobol run  (sobol_mass_runs/<batch>/run_XXXX/)
  └─ sobol_XXXXX  (binary; 10 solar sinks, or 1 Earth sink for hyperbola runs, + np_apophis DEM grains:
                  idem particles with R = h (particle DEM, default) or sinks (sink DEM, legacy))
        │  DEM sweeps force nfulldump=1 (every dump is full)
        │  Typical np_apophis: 500 (OBJ crop ~501 grains) up to 2000 (S1 lattice)
        ▼
  WSL: sobol/Analysis/run_demtocsv_batch.py
        │  execs this repo's CSVconvert/DEMDumpConvert.py with patched paths
        │  --min-dem-grains 450  (skip non-DEM dumps; match np_apophis)
        ▼
  DEMCSVs/<sim_name>/<run_name>_bodies_output/*.csv   (11 rows, solar bodies + synthetic Apophis CoM)
  DEMCSVs/<sim_name>/<run_name>_grains_output/*.npz   (n_grains entries; one per DEM grain)
        ▼
  BlenderConvert/DEMGrainsBlenderEarthCam.py
        │  set GRAINS_DIR / BODIES_CSV_DIR to the run_*_output folders
        ▼
  Blender: n_grains UV spheres in Apophis body-frame + Earth mesh
```

**Pipeline B — bulk composite branch (additive, high-*N* or breakup):**

```
  (same grains/bodies folders as above)
        ▼
  viz/viz_preprocess.py  →  DEMCSVs/<sim>/<run>_viz/
        │  FOF clustering, envelope meshes (.npz), ejecta subset, manifest.json
        ▼
  BlenderConvert/DEMBulkVizBlender.py  (set VIZ_MANIFEST; Cycles)
        ▼
  Blender: deforming envelope mesh(es) + GN-instanced ejecta + Earth/camera
```

Does **not** replace per-sphere import — use per-sphere for ≤~2000 grains and hero shots; use composite for high-*N* or when individual interior grains are not needed.

**Canonical datasets:** `docs/BATCHES_VIZ.md`

**Legacy path:** early tests used `DEMTrial/demtrial_*` with `nfulldump=10` and flat `dem_bodies_output/` / `dem_grains_output/` — do not document as the default workflow.

### Pipeline C — concurrent SPH+DEM (exclusion)

Not a planned pipeline. Distill **excludes** concurrent SPH+DEM (SPH matrix + DEM boulders). Do not implement without a documented scope change agreed with supervisors. WSL `ThesisStuff/SCI4502_SCOPE_CONTEXT.md`.

## Output file conventions

Layout / formats / converter name: WSL `docs/SHARED_FACTS.md`. Schema below is Windows-owned how-to.

### Bodies CSVs (`csv_output/` and `DEMCSVs/*_bodies_output/`)

Both pipelines produce the same 11-row body schema — existing Blender scripts work with either folder:

| Column | Units | Notes |
|--------|-------|-------|
| `name` | — | Body name string |
| `x_au`, `y_au`, `z_au` | AU | Absolute position |
| `x_km`, `y_km`, `z_km` | km | Absolute position |
| `h` | km | Physical radius (from PHANTOM `h` field) |
| `Reff` | km | Effective radius; alias of `h` for macro bodies |
| `m` | code units | Mass |

**Row order** — same in both pipelines:

| Index | Body     |
|-------|----------|
| 0     | Sun      |
| 1     | Mercury  |
| 2     | Venus    |
| 3     | Earth    |
| 4     | Moon     |
| 5     | Mars     |
| 6     | Jupiter  |
| 7     | Saturn   |
| 8     | Uranus   |
| 9     | Neptune  |
| 10    | Apophis  |

- In the DEM pipeline, row 10 (Apophis) is a **synthetic row** — mass-weighted centroid of all DEM grains. Not a raw PHANTOM sink.

### Grains npz (`DEMCSVs/*_grains_output/`) — DEM pipeline only

One compressed `.npz` per dump (same basename as the bodies CSV, e.g. `sobol_00003.npz`), written by `DEMDumpConvert.py` with `np.savez_compressed`. Each key is one array of length `n_grains` (typical ~500 for OBJ crop), except `time_s`. Read it with `d = np.load(path)`; no pandas is needed. CSV-era grain folders are not read by the current scripts. Reconvert them from the WSL dumps if the dumps still exist, or run `CSVconvert/grains_csv_to_npz.py` to write `.npz` next to the existing CSVs when they don't — see **Upgrade CSV-era grain folders** in Key commands.

| Key | dtype | Units | Notes |
|-----|-------|-------|-------|
| `grain_id` | int64 | index | 0…n−1 |
| `time_s` | float64, 0-d | s | Dump time — scalar, read with `float(d['time_s'])` |
| `x_au`, `y_au`, `z_au` | float64 | AU | Absolute solar-system position — **do not use for grain-level Blender placement** |
| `x_km`, `y_km`, `z_km` | float64 | km | Absolute position |
| `x_rel_km`, `y_rel_km`, `z_rel_km` | float64 | km | Position relative to Apophis CoM |
| `Reff_km` | float64 | km | Grain effective radius |
| `h_km` | float64 | km | Smoothing length |
| `x_vis`, `y_vis`, `z_vis` | float64 | BU | `x_rel_km × GRAIN_VIS_SCALE` — **use as Blender object location** |
| `Reff_vis` | float64 | BU | `Reff_km × GRAIN_VIS_SCALE` — use as Blender sphere radius |
| `m` | float64 | code units | Mass |
| `vx`, `vy`, `vz` | float64 | (code units) | Velocity; NaN if absent from the dump |
| `spinx`, `spiny`, `spinz` | float64 | (code units) | Spin; NaN if absent from the dump |

Measured 2026-09-13 on a 501-grain frame: CSV 200 KB → npz 43 KB, loading 2× faster, values bit-identical.

**Code units — `udist` is 1 km, so km *are* code length.** Verified 2026-09-07 from
the data itself (finite-differenced `x_km` against `time_s` and `vx`, with
`G·M☉` fixing the velocity unit): `udist = 0.999992 km`, `umass = M☉` (Sun's `m`
is exactly 1.0, Earth's 3.0035e-6), `G = 1`. Two consequences:

- `x_rel_km` / `Reff_km` are already code units — an energy test such as
  `eps = ½v² − m/r` mixing them with code-unit `m` and `vx` is **correct as
  written**, not a unit bug. (Sanity anchor: the DEM Apophis is
  `m = 2.79e-20` M☉ = 5.6e10 kg, and `sqrt(2m/r)` in code units maps to a
  surface escape speed of **0.21 m/s**.)
- The velocity unit is `sqrt(G·M☉/udist) ≈ 3.64e5 km/s` — superluminal, which
  is normal for this unit choice and not a sign of corrupt data.

`x_au` is *absolute* heliocentric position; it is not a code-unit column and is
not a drop-in substitute for `x_rel_km` in body-frame calculations.


### Pipeline comparison

| Aspect | Point-mass (A) | DEM Sobol (B) |
|--------|----------------|---------------|
| Dump source | `solarsystem/solarsystem1_*` | `sobol_mass_runs/.../sobol_*` |
| Grains per dump | — | `np_apophis` (variable, typical ~500) |
| Full dumps | All | `nfulldump=1` on DEM sweeps |
| Converter | `ToCSVFirst.py` | `run_demtocsv_batch.py` → `DEMDumpConvert.py` |
| Bodies output | `csv_output/` | `DEMCSVs/<sim>/<run>_bodies_output/*.csv` |
| Grains output | — | `DEMCSVs/<sim>/<run>_grains_output/*.npz` |
| Apophis in bodies CSV | Raw PHANTOM sink | Synthetic CoM row |
| Position for Blender | `x_au` × SCALE | `x_vis` (= `x_rel_km` × 50); no SCALE |
| Blender importer | `OnlyEarth_ApophisTrueSize.py` | `DEMGrainsBlenderEarthCam.py` |
| Blender objects | 11 spheres/meshes | n_grains spheres |

### DEM-specific notes

**PHANTOM DEM module:** Custom in-tree DEM developed by supervisor Daniel — grain contact forces within PHANTOM's N-body framework. Grains are `idem` particles (particle DEM, default since 2026-09-26; radius = h) or sink particles (sink DEM, legacy) in dumps (not pkdgrav/SSDEM).

**Why `x_vis` instead of `x_au` for grain placement:**
At solar-system SCALE=5000, Apophis sits at ~1750 BU from origin. Float32 epsilon there collapses grain separations. Fix: body-frame `x_rel_km` × `GRAIN_VIS_SCALE=50` → `x_vis` near Blender origin.

**Apophis CoM compatibility:**
`DEMDumpConvert.py` appends synthetic row 10 to bodies CSV — mass-weighted centroid of all grains. Drop-in compatible with point-mass Blender scripts.

**Mini-dump guard:**
Production DEM sweeps use `nfulldump=1`. `DEMDumpConvert.py` still checks `n_dem < MIN_DEM_GRAINS` and skips corrupt dumps.

**Grain ↔ bodies file matching:** per-sphere importers pair each frame's grain file with the bodies CSV of the same stem (`sobol_00003.npz` ↔ `sobol_00003.csv`), swapping the extension. A lookup by full filename finds nothing and silently drops Earth/Moon/Sun (the script falls back to `apophis_only` mode without an error) — keep the stem-based lookup.


## Body model files

- `BlenderConvert/TheEarth.blend` — objects: `Surface`, `Atmosphere`, `Clouds`.
- `BlenderConvert/TheEarth1.blend` — full 3-D Earth for DEM scripts. `Surface` radius ≈ 1274 BU; `EARTH_VIS_SCALE = 0.2`. Volume atmosphere is scale-dependent. **Rendered in Cycles.**
- `BlenderConvert/Apophis.blend` — object `Apophis` (fallback: append-all).
- Both appended (not linked) after import.
