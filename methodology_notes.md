# Post-processing and Visualisation Methodology

Maxwell Boyle & Mia Eng — SCI4502 Honours, Monash University
Supervisors: Daniel Price, Andy Tomkins, Rachel Kirby
Last updated: 2026-09-07

> **Agent ops:** pipeline commands and paths are maintained in `CLAUDE.md`. This file is thesis methodology prose.

---

## Purpose of this document

This file describes the methodology and design decisions behind the post-processing
and visualisation codebase that accompanies the PHANTOM SPH + DEM simulations of
the 2029 Apophis Earth flyby. It is intended as a reference for writing the thesis
methodology section and for explaining the code to examiners or reviewers.

---

## 1. Simulation context

PHANTOM (Price et al. 2018) is the smoothed particle hydrodynamics (SPH) code used
to simulate the Apophis flyby trajectory. Two simulation modes are used:

**Pipeline A — Point-mass mode.** Apophis is treated as a single sink particle
(zero physical extent, governed only by gravity). The solar system is represented by
11 sink particles: Sun + 8 planets + Moon + Apophis. All gravitational interactions
are computed directly. Output: `solarsystem1_XXXXX` binary dump files in WSL.

**Pipeline B — DEM rubble-pile mode.** Apophis is resolved into 64 discrete grains
via a custom Discrete Element Method (DEM) module developed by the supervisor and
added to PHANTOM. Each grain is a sink particle with an effective radius (`Reff`) and
experiences contact forces in addition to gravitational forces. Total sink count per
full dump: 74 (10 solar system bodies + 64 DEM grains).

Both pipelines produce binary PHANTOM dump files on the WSL Linux filesystem. The
post-processing pipeline described here converts those binary files to CSV (bodies)
and compressed NumPy `.npz` (DEM grains), then imports them into Blender for animation.

---

## 2. PHANTOM dump conversion (CSV bodies, npz grains)

### 2.1 Reading PHANTOM binary dumps

All converters use the `sarracen` Python library (Laura & Tricco) to read PHANTOM
dump files. The call

```python
result = sarracen.read_phantom(dump, separate_types='all')
sdf_sinks = result[-1]
```

returns a list where the last element is a `SarracenDataFrame` containing the sink
particle table, along with a `.params` dictionary of simulation metadata (code units,
simulation time, etc.).

### 2.2 Point-mass converter — `CSVconvert/ToCSVFirst.py`

**Purpose.** Converts each `solarsystem1_XXXXX` binary dump to a CSV of 11 rows
(one per body: Sun, 8 planets, Moon, Apophis).

**Unit conversion.** PHANTOM stores all positions in internal code units. The
conversion factor `udist` (code units → centimetres) is read from `sdf_sinks.params`.
Positions are then converted to AU by dividing by `AU_IN_CM = 1.495978707e13`:

```
x_au = x_code × udist / AU_IN_CM
```

**Output columns.** The CSV retains all native PHANTOM sink columns and adds
`x_au`, `y_au`, `z_au` as renamed position columns. The `h` column (smoothing length
for sink particles) encodes the physical radius of each body as set by the PHANTOM
setup and is used downstream as `Reff`.

**Key design choice.** The converter passes all native columns through rather than
selecting a fixed subset. This keeps downstream scripts flexible: they can read any
column available in the dump without requiring converter changes.

### 2.3 DEM converter — `CSVconvert/DEMDumpConvert.py`

**Purpose.** Converts each `demtrial_XXXXX` (or `sobol_XXXXX`) binary dump into two
files per timestep, sharing the dump's name as stem:

1. `*_bodies_output/<dump>.csv` — an 11-row CSV with solar system bodies plus a synthetic
   Apophis centre-of-mass row. Schema is identical to Pipeline A, so existing Blender
   scripts are drop-in compatible.
2. `*_grains_output/<dump>.npz` — a compressed NumPy archive with one float64 array
   entry per grain field (one element per grain, typically ~500), holding per-grain
   positions in both absolute AU coordinates and Apophis body-frame coordinates
   pre-scaled for Blender placement. Grains moved from CSV to `.npz` on 2026-09-13:
   the files are ~5× smaller, load ~2× faster, and store values bit-exactly.

**Mini-dump detection.** PHANTOM's `nfulldump` parameter controls how often a
complete dump is written. Between full dumps, PHANTOM writes "mini-dumps" that
contain only a subset of the sink table (~17 sinks) and lack usable grain data. The
converter detects these by checking:

```python
n_dem = n_sinks - N_BODIES
if n_dem < MIN_DEM_GRAINS:
    # skip — mini dump
```

`MIN_DEM_GRAINS` is set just below the actual grain count (e.g. 450 for a 500-grain
run). This ensures only complete dumps are processed.

**Sink classification.** The first `N_BODIES = 10` sinks are solar system bodies
(Sun through Neptune, in fixed PHANTOM sink order). All remaining sinks are DEM
grains. A sanity check compares the effective radius of each group against
`GRAIN_REFF_THRESHOLD_KM = 1.0 km`: solar system bodies have radii of hundreds to
tens-of-thousands of km, while DEM grains have radii of ~0.05 km, so the threshold
cleanly divides them.

**Synthetic Apophis CoM row.** The bodies CSV requires a row 10 for Apophis so that
the existing Blender point-mass scripts (which expect that row index) continue to
work. Since in Pipeline B Apophis is distributed across many DEM grains (typical ~500 for OBJ crop) rather than being
a single sink, a synthetic CoM row is computed as the mass-weighted centroid of all
grain positions:

```
com_x = Σ(x_i × m_i) / Σ(m_i)
```

This row is appended to the bodies CSV, making the output format identical to
Pipeline A for all downstream code that only needs the whole-body position.

**Body-frame and visualisation-scaled grain positions.** Three position
representations are written for each grain:

| Column set | Description | When to use |
|---|---|---|
| `x_au, y_au, z_au` | Absolute solar-system AU | Locating Apophis in the solar system; NOT for per-grain Blender placement |
| `x_rel_km, y_rel_km, z_rel_km` | km relative to Apophis CoM | Computing grain-to-grain separations, physical analysis |
| `x_vis, y_vis, z_vis` | `x_rel_km × GRAIN_VIS_SCALE` | Direct Blender object location |

The need for `x_vis` arises from floating-point precision. At the solar-system Blender
scale of `SCALE = 5000` (Blender units per AU), Apophis sits approximately 1750
Blender units from the origin during the flyby. IEEE 754 single-precision (float32)
epsilon at magnitude 1750 is approximately `2 × 10⁻⁴` BU. However, the typical
grain-to-grain separation within Apophis is only ~`5 × 10⁻⁶` BU at that scale, which
is below the float32 resolution: grains at solar-system scale collapse to an identical Blender
coordinate. By outputting positions relative to the Apophis CoM (`x_rel_km`) and then
multiplying by `GRAIN_VIS_SCALE = 50`, the grain cloud is centred near the Blender
world origin, where float32 epsilon is ~`9 × 10⁻⁷` BU — well below any physical
grain separation.

**Time output.** Each frame file carries `time_s` (a scalar in the grain `.npz`), the simulation time converted to
seconds using the `utime` code unit. This allows per-frame time labelling in Blender
overlays or figure captions without re-reading binary dumps.

**Output directory structure.** The converter automatically derives output paths from
the input directory structure:

```
DEMCSVs/<sim_name>/<run_name>_bodies_output/
DEMCSVs/<sim_name>/<run_name>_grains_output/
```

This makes it straightforward to convert multiple runs from a Sobol sweep without
path conflicts.

---

## 3. Blender visualisation pipeline

All Blender scripts are pasted into Blender's Scripting workspace and executed with
Run Script. They use Blender's Python API (`bpy`) and cannot be run as standalone
Python scripts. The render target is Cycles (ray-traced), not EEVEE (rasterised).

### 3.1 Common architectural pattern

All import scripts follow the same three-pass structure:

1. **Creation pass.** Read the first frame file (CSV for bodies, `.npz` for DEM
   grains). Create one Blender object (UV sphere or imported mesh) per body. Set
   initial location.
2. **Keyframe pass.** Iterate over all frame files in order. For each file, set the
   Blender scene frame, read the frame, and insert a location keyframe for every object.
3. **Smoothing pass.** Traverse each object's F-curves and apply Bézier interpolation
   with `AUTO_CLAMPED` handles so animation between frames is smooth rather than
   piecewise-linear.

The F-curve smoothing code handles both the Blender ≤4.x API (`action.fcurves`) and
the Blender 4.x+ slotted action API (iterating `action.layers → strips → channelbags
→ fcurves`) so the scripts remain forward-compatible.

### 3.2 Simple point-mass importer — `BlenderConvert/CSVtoBlender.py`

The simplest importer. Creates one UV sphere per body, scaling radius from the `h`
column (in km, converted to AU, then multiplied by `SCALE = 1.0`). Each sphere's
location is keyframed per CSV. Useful for a full-system overview where scale accuracy
matters more than visual detail.

### 3.3 Smoothed point-mass importer — `BlenderConvert/workinglargescaleimport.py`

Extends the simple importer with:
- `SCALE = 5000` — places the solar system at a comfortable scale for float32 precision
  while keeping objects visually navigable.
- Bézier F-curve smoothing via `smooth_location_fcurves()`, which handles both Blender
  action API generations.

### 3.4 Full point-mass importer — `BlenderConvert/OnlyEarth_ApophisTrueSize.py`

The most complete point-mass visualisation script. Key additions:

**`BodyModelConfig` dataclass.** Encapsulates all import settings for a detailed body
model (mesh path, format, object names, auto-centering, auto-scaling, shell scale).
This avoids global variable proliferation and makes it straightforward to add new body
models without restructuring the script.

**`import_body_model()` function.** Appends a `.blend`, FBX, or OBJ file into the
current scene and parents the mesh parts to a trajectory Empty. The function:
1. Attempts to match `part_names` by exact name, then case-insensitively, then by
   base name (stripping Blender's `.001` suffix). If no match and `blend_append_all_
   objects_if_unmatched = True`, appends every object (meshes only are parented).
2. Auto-centers the combined mesh bounding box onto the Empty's position.
3. Auto-scales all mesh parts uniformly so the reference mesh radius matches the CSV
   physical radius at the current `SCALE`.

**Apophis-centric recentering.** Rather than placing all bodies at their absolute AU
positions (which puts Apophis far from the origin where float32 is imprecise), the
script computes all body positions relative to Apophis for every frame:

```python
body_loc = (body_x_au - apophis_x_au) * SCALE
```

Apophis's Empty is always inserted at `(0, 0, 0)` each frame. This keeps the
asteroid at world origin — where Blender's float32 coordinate representation is most
precise — and the camera (parented to the Apophis Empty) does not need to travel.
The recentering is baked directly into the keyframes, so no runtime Python handler is
needed after import; the `.blend` file is self-contained.

**`IMPORT_CSV_INDICES`.** Only Sun (0), Earth (3), and Apophis (10) are processed.
Planets 1–2 and 5–9 are skipped. This reduces import time significantly because
detailed mesh models and keyframe data are only created for the bodies relevant to
the flyby animation.

### 3.5 Point-mass camera — `BlenderConvert/Camera.py`

Creates an `EarthCam` Empty parented to the Earth trajectory Empty, with a `TRACK_TO`
constraint pointing at Apophis. Pasted and run after `OnlyEarth_ApophisTrueSize.py`.

### 3.6 DEM grain importer — `BlenderConvert/DEMGrainsBlenderEarth.py`

Imports the rubble-pile grain cloud and the Earth model. Key design points:

**Grain objects.** One UV sphere is created per grain (`DEM_Grain_000` through
`DEM_Grain_063`). All spheres share a single Principled BSDF material (`DEM_Grain`)
with a grey-brown base colour appropriate for a carbonaceous asteroid. Spheres use
12 segments and 8 rings — sufficient for a 5–50 BU radius sphere in Cycles without
excess geometry.

**Position source.** Grain locations come from `x_vis/y_vis/z_vis` in each frame's grain `.npz`,
which are body-frame km positions pre-multiplied by `GRAIN_VIS_SCALE`. No solar-system
`SCALE` is applied: the grains cluster within ±25 BU of the origin, matching the
planet-free near-origin coordinate space.

**Earth model import.** `TheEarth1.blend` contains three shells: `Surface` (textured
photorealistic mesh with city-light emission), `Atmosphere` (Cycles volume-scatter
shader), and `Clouds` (procedural texture). The Earth is appended with `link=False`
so all materials and modifier stacks transfer intact.

The Earth's authored radius in `TheEarth1.blend` is measured automatically from the
`Surface` mesh AABB (~1274 BU). The target radius for import is:

```
target_radius = EARTH_PHYSICAL_RADIUS_KM × EARTH_VIS_SCALE = 6371 × 0.2 ≈ 1274 BU
```

This gives `scale_factor ≈ 1.0`, meaning the Earth is imported at its native authored
size. This is deliberate: the volume-scatter atmosphere's visual appearance depends on
the physical path length through the volume. Shrinking the model would reduce the path
length through the Atmosphere volume, making it appear thinner or blocky (below
Cycles' volume step size). Importing at native size preserves the atmosphere exactly as
it was designed in the `.blend`.

**Earth shell clearance.** The three Earth shells are nearly coincident in the source
file. In a rasterised renderer this causes Z-fighting; in Cycles (ray-traced) it causes
incorrect surface normal evaluation because a ray can pass through two faces at the
same hit point. The `EARTH_SHELL_SCALE` dictionary applies a small additional
outward scale to `Atmosphere` (×1.004) and `Clouds` (×1.002) to provide clearance
without visually detectable size change.

**Earth position.** Earth's location each frame is computed as:

```
earth_location_bu = (earth_km - apophis_km) × EARTH_VIS_SCALE
```

Earth is ~38 000 km from Apophis at closest approach, which maps to ~7600 BU —
well within Cycles' ray-march depth range.

**Earth rotation.** The Surface and Clouds shells get one orientation quaternion per
frame from `earth_orientation.earth_quaternion(time_s, EARTH_EPOCH_TDB)`, so both spin
rate and time of day are real:

```
q = R_z(90°) · R_z(−p_A) · R_x(−ε_A) · R_z(GMST(UT1))      UT1 = epoch + time_s − ΔT
```

`TheEarth1.blend` is Earth-fixed (+X Greenwich, +Z north; read from its UVs). GMST is
IAU 1982 (Meeus 12.4), ε_A and p_A are the mean obliquity and precession in longitude
of date, ΔT = 69 s, `time_s = 0` is the `.setup` epoch (2029-04-10 00:00 TDB). The
final R_z(90°) is because the sim frame is the J2000 ecliptic turned +90° about the
ecliptic pole (PHANTOM `set_binary` treats the Horizons node longitude as a position
angle, `big_omega = posang_ascnode + π/2`). Nutation and polar motion are left out
(< 0.01°). Check: at closest approach (21:44 UT, 13 Apr 2029) the sub-Apophis point is
42.5°W 28.6°N (mid-Atlantic), and Europe/Africa are on the night side. Hyperbola runs (no
Sun row) use the real orientation at t_real = 2029-04-13 21:46 TDB + (`time_s` minus the
fitted pericentre time), turned into the scene by the same rotation as the Sun (see
below). If the fit falls back (fewer than 3 frames or a degenerate orbit), the run keeps the
arbitrary-epoch Earth orientation, a fixed lamp direction and no Sun visual. The Atmosphere shell is not rotated: it is spherically symmetric. A bodies CSV without `time_s` gets no spin. Blender
interpolates the quaternion keys per component, which still turns the right way up to 360°
between keys and backwards beyond it, so `earth_orientation.SpinStepCheck` warns once per run
when keys are more than 180° of spin apart (uneven) or 360° (backwards).

**Moon and Sun visual body.** A grey UV sphere represents the Moon, scaled to
`MOON_PHYSICAL_RADIUS_KM × EARTH_VIS_SCALE`. The Sun's directional lamp
(`DEM_SunLight`) is oriented each frame to point from Apophis toward the Sun: the bodies
CSV `Sun` row for ephemeris runs, or, for hyperbola runs (no `Sun` row), the real 2029
direction. `sun_geometry.py` fits the Earth-relative hyperbola to every bodies CSV, puts
the real closest approach (2029-04-13 21:46 TDB, JPL Horizons) at the fitted pericentre,
and maps the real pericentre frame onto the fitted one; the Sun then turns at the mean
ecliptic rate. A run with fewer than 3 frames keeps the fixed
`APOPHIS_ONLY_SUN_DIRECTION`. An emissive white UV sphere (`Sun_Visual`) shows the Sun at
true angular size: it sits `SUN_VISUAL_DISTANCE_BU = 1.5e7` BU from Apophis along the Sun
direction, with radius 1.5e7 tan(0.2657 deg). It is visible to the camera only, so the
lamp alone lights and shadows the scene. Its emission gives the radiance that would
deliver the lamp's irradiance, L = E / (pi a^2) (a = angular radius), so it clips to
white like a real exposure; `SUN_DISK_BRIGHTNESS_SCALE` scales it for legibility. The
headless renders add a compositor Bloom (threshold 100, far above any lit surface) so
only the Sun glows.

**Viewport clip range.** Both the 3D viewport and all cameras are set to
`clip_start = 0.1`, `clip_end = 2 000 000 BU` automatically at the end of the script.
The far clip must reach Earth (~7600 BU at closest approach, receding to ~10 M BU
at the flyby edges). The EEVEE volumetric range is also set (`volumetric_end = 50 000
BU`) so the atmosphere appears correctly in the interactive EEVEE viewport preview,
even though the final render uses Cycles.

### 3.7 DEM camera — `BlenderConvert/DEMCamera.py`

Creates and keyframes the `DEM_TrackCam` camera independently from the grain import.
Key design decisions:

**Tracking the grain core, not the CoM.** During tidal breakup, the dense grain
nucleus migrates away from the mathematical mass-weighted CoM (the Blender origin).
By frame ~200, the core has drifted ~20 BU; by closest approach (~frame 1125) it sits
~95 BU from the origin. Aiming the camera at the origin would show empty space. The
script computes the "dense core" each frame as the centroid of the 80% of grains
nearest the CoM:

```python
pts.sort()                       # sort by distance from origin (CoM)
n = max(1, int(len(pts) * 0.80))
core = mean(pts[:n])             # centroid of closest 80%
```

This trims scattered ejecta and keeps the compact nucleus centred in frame.

**Camera placement geometry.** The camera is placed `CAM_DIST_BU = 150 BU` from the
grain core, along the anti-Earth direction offset by `CAM_ANGLE_DEG = 30°` toward the
ecliptic perpendicular. This keeps Earth visible in the frame (within the 70° FOV)
while the grain body fills the centre.

**Quaternion continuity.** Camera orientation is computed each frame independently
using `to_track_quat('-Z', 'Y')` (local -Z toward the grain core, local +Y toward
world +Z). To prevent the SLERP interpolation from taking the long arc between
antipodal quaternions (which produces a roll artifact), consecutive quaternions are
negated if their dot product is negative:

```python
if prev_q is not None and q.dot(prev_q) < 0.0:
    q.negate()
```

**Rotation interpolation.** Location uses Bézier (`AUTO_CLAMPED`) for smooth
translation. Rotation uses `LINEAR` (SLERP), avoiding Bézier's component-wise
interpolation which produces a barrel-roll artifact during the large ~102° pan at
closest approach.

**Fill light.** A point light (`DEM_CamFill`) is parented to the camera. Because it
co-moves with the camera each frame automatically via the parent relationship, no
additional keyframes are needed. This illuminates the camera-facing hemisphere of the
grain cloud.

### 3.8 Combined DEM script — `BlenderConvert/DEMGrainsBlenderEarthCam.py`

Merges `DEMGrainsBlenderEarth.py` and `DEMCamera.py` into a single script.
`SETUP_CAMERA = True/False` controls whether the camera is created. Equivalent in
output to running the two scripts sequentially; provided for convenience when a
single-script run is preferred.

### 3.9 Material propagation utility — `BlenderConvert/MaterialandSubsivision.py`

After import, all grain spheres share the same `DEM_Grain` material by assignment
in the import script. If additional modifiers (e.g. Subdivision Surface) or a
custom material are applied manually to one grain as a prototype, this utility
propagates them to all other grains:

```python
for obj in targets:           # all objects with prefix DEM_Grain_
    obj.data.materials.clear()
    for mat in source.data.materials:
        obj.data.materials.append(mat)
    obj.modifiers.clear()
    for src_mod in source.modifiers:
        new_mod = obj.modifiers.new(name=src_mod.name, type=src_mod.type)
        # copy all modifier properties via bl_rna introspection
```

This avoids manually editing 64 or 500 grain objects, which is the typical grain
count.

---

## 4. Data analysis — `Data analysis/FirstData.py`

**Purpose.** Loads the body-position CSVs from one or more simulation runs (or
Sobol sweep batches) and computes scalar flyby metrics for comparison across runs.

**`load_run()`.** Reads all CSVs in a directory in sorted order. For each frame,
extracts the Earth–Apophis separation:

```
dist = √((x_apophis - x_earth)² + (y_apophis - y_earth)² + (z_apophis - z_earth)²)
```

in both AU and km. Also computes the Sun–Apophis distance per frame. Returns a
pandas DataFrame with one row per dump.

**`compute_metrics()`.** Identifies the closest-approach frame as `idxmin()` of the
Earth–Apophis distance. Estimates relative velocity at closest approach using first
differences of position between consecutive frames (valid only if dumps are
evenly spaced in simulation time). Returns a summary dict including:
- Closest approach distance in AU and km
- Frame index of closest approach
- Speed at closest approach (AU per dump step)
- Mean, min, and max Sun–Apophis distance

**Visualisation.** Three matplotlib figures are produced:
1. Apophis trajectory in the ecliptic x–y plane, overlaid across runs.
2. Earth–Apophis distance over dump frames, with a reference line at the Moon's
   orbital distance (~0.00257 AU).
3. Bar chart of closest approach distance by run label.

**Cross-system note.** This script reads `csv_output/` (Pipeline A) or
`dem_bodies_output/` (Pipeline B) CSVs on the Windows filesystem. No WSL access
is needed at this stage; all data is already converted.

---

## 5. Key coordinate systems and scale conventions

| Space | Origin | Unit | Used by |
|---|---|---|---|
| PHANTOM code units | Barycentre | code unit | Raw dump; `udist` converts to cm |
| Solar system AU | Sun | AU | Bodies CSVs; point-mass Blender (`SCALE=5000`) |
| Solar system km | Sun | km | Bodies CSVs; `x_km`, `y_km`, `z_km` columns |
| Apophis CoM relative km | Apophis CoM | km | Grain `.npz` files; `x_rel_km` arrays |
| Blender grain frame (BU) | Apophis CoM (world origin) | BU = km × 50 | `x_vis` columns; DEM Blender scripts |
| Blender Earth frame (BU) | Apophis CoM (world origin) | BU = km × 0.2 | Earth Empty location in DEM scripts |
| Blender point-mass (BU) | Apophis (world origin, Apophis-centric) | BU = AU × 5000 | `OnlyEarth_ApophisTrueSize.py` |

---

## 6. Software dependencies

| Component | Software | Version constraint |
|---|---|---|
| PHANTOM dump reading | `sarracen` | Any recent; Windows `.venv` |
| CSV / npz processing | `pandas`, `numpy` | Any recent |
| Plotting | `matplotlib` | Any recent |
| 3D animation | Blender (Cycles renderer) | 3.x / 4.x; scripts handle both action API generations |
| Blender scripting | `bpy` (Blender-bundled Python) | Not installable via pip |

---

## 7. File cross-reference

| Script | Input | Output |
|---|---|---|
| `CSVconvert/ToCSVFirst.py` | WSL `solarsystem1_XXXXX` binary | `csv_output/*.csv` (11-row body CSVs) |
| `CSVconvert/DEMDumpConvert.py` | WSL `demtrial_XXXXX` or `sobol_XXXXX` binary | `DEMCSVs/<sim>/<run>_bodies_output/*.csv` + `_grains_output/*.npz` |
| `CSVconvert/grains_csv_to_npz.py` | CSV-era `DEMCSVs/**/*_grains_output/*.csv` | Same-stem `.npz` beside each CSV (one-off upgrade; CSVs kept) |
| `CSVconvert/Debug.py` | Single WSL binary dump | Console print (inspection only) |
| `BlenderConvert/CSVtoBlender.py` | `csv_output/` | Blender scene (11 spheres) |
| `BlenderConvert/workinglargescaleimport.py` | `csv_output/` or `ShortCSVlist/` | Blender scene (11 spheres, smoothed) |
| `BlenderConvert/OnlyEarth_ApophisTrueSize.py` | `csv_output/` + `.blend` models | Blender scene (Sun, Earth mesh, Apophis mesh) |
| `BlenderConvert/Camera.py` | Requires scene from `OnlyEarth_ApophisTrueSize.py` | EarthCam object |
| `BlenderConvert/DEMGrainsBlenderEarth.py` | `DEMCSVs/<sim>/<run>_grains_output/` + `_bodies_output/` | Blender scene (n_grains spheres + Earth + Sun lamp + Moon + Sun body) |
| `BlenderConvert/DEMCamera.py` | Requires scene from `DEMGrainsBlenderEarth.py` | DEM_TrackCam object |
| `BlenderConvert/DEMGrainsBlenderEarthCam.py` | Same as above | Combined scene + camera in one run |
| `BlenderConvert/MaterialandSubsivision.py` | Existing Blender scene with grain objects | Modified materials + modifiers on all grains |
| `Data analysis/FirstData.py` | Any `csv_output/` or `DEMCSVs/*_bodies_output/` | matplotlib figures + metrics table |
