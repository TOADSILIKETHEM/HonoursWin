# Instance-pipeline cinematic integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the pure-instancing (Option A) point-cloud path the same Earth/camera/lighting/timeline cinematic integration the composite path already has, via a shared module, driven today by a static placeholder point cloud that a future real per-frame million-grain data source can drop into without redesign.

**Architecture:** A new `viz/viz_preprocess_lite.py` (run under Blender's bundled Python, needs `mathutils.bvhtree`) rejection-samples a JPL shape OBJ into a static point cloud, scaled and sized from a real run's grains/bodies CSVs, and writes a `viz_mode: "instance"` manifest + `_viz/points.npz`. A new `BlenderConvert/DEMBulkInstanceBlender.py` reads that manifest and builds the scene using a new shared `BlenderConvert/DEMCinematicSetup.py` (Earth/Moon/Sun, camera, timeline — extracted from `DEMBulkVizBlender.py`) plus `P0_InstancingSpike.py`'s proven GN "Instance on Points" helpers.

**Tech Stack:** Python (Blender 5.2.1 LTS bundled interpreter, Python 3.13), `bpy`/`mathutils`, `numpy`, `pandas`, Cycles.

**Spec:** `docs/superpowers/specs/2026-09-08-instance-pipeline-cinematic-integration-design.md`

## Global Constraints

- Render engine is **Cycles**, never EEVEE.
- Blender version: 5.2.1 LTS at `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` (Python 3.13). Node-group sockets use `group.interface.new_socket(...)`, not `group.inputs.new`. Principled BSDF exposes "Specular IOR Level".
- `BlenderConvert/*.py` scripts are pasted/opened into Blender's Scripting tab and run with **Run Script** — they are not standalone Python (need `bpy`). The two exceptions, matching `P0_InstancingSpike.py`'s existing precedent, are `viz/viz_preprocess_lite.py` and any headless verification script in this plan: these run via `blender --background --python <script> -- <args>`.
- `DEMGrainsBlenderEarthCam.py` is **not touched** by this plan — it keeps its own independent cinematic logic.
- **Never commit or push** until the user has tested and explicitly asks.
- No test framework exists in this repo (no pytest, no `tests/`). Verification follows the project's existing convention: runnable scripts with `assert` statements and printed diagnostics (see `p0_blend_apophis.py`, `P0_InstancingSpike.py`), run headless via `blender --background --python`.
- Temp/throwaway verification scripts go in the session scratchpad, not the repo.

---

## File Structure

| File | Responsibility |
|------|-----------------|
| `BlenderConvert/DEMCinematicSetup.py` (new) | Shared Earth/Moon/Sun placeholder, body-CSV keyframing, tracking-camera setup, frame-handler-suspend helper. No knowledge of envelopes/ejecta/points. |
| `BlenderConvert/DEMBulkVizBlender.py` (modify) | Composite path — refactored to call `DEMCinematicSetup` instead of its own private copies. No behavior change. |
| `viz/shape_sampling.py` (new) | JPL shape OBJ loading + BVH-based rejection sampling of points inside a closed shell (moved from the `p0_blend_apophis.py` scratchpad). |
| `viz/viz_preprocess_lite.py` (new) | Placeholder-mode preprocessing CLI: builds a static point cloud from a shape OBJ, scaled/sized from a real run's CSVs, writes a `viz_mode: "instance"` manifest. |
| `BlenderConvert/DEMBulkInstanceBlender.py` (new) | Instance path — reads the manifest, calls `DEMCinematicSetup`, builds the GN point cloud via `P0_InstancingSpike.py` helpers. |

---

### Task 1: Extract `DEMCinematicSetup.py` from `DEMBulkVizBlender.py`

**Files:**
- Create: `BlenderConvert/DEMCinematicSetup.py`
- Modify: `BlenderConvert/DEMBulkVizBlender.py`

**Interfaces:**
- Produces (consumed by Task 4, and by `DEMBulkVizBlender.py` itself):
  - `detect_solar_system(bodies_dir: str) -> bool`
  - `grain_core(points_vis: np.ndarray, fraction: float) -> mathutils.Vector`
  - `ensure_earth_placeholder(has_solar: bool, bodies_dir: str) -> bpy.types.Object | None`
  - `keyframe_bodies_and_earth(bodies_dir: str, frame_count: int, has_solar: bool, earth_empty=None) -> bpy.types.Object | None`
  - `setup_camera(frame_count: int, core_fn: Callable[[int], Vector], earth_empty, has_solar: bool, camera_mode: str | None = None) -> None`
  - `frame_handler_suspended(handler: Callable) -> contextmanager`

This is a mechanical extraction — every function body is copied verbatim from `DEMBulkVizBlender.py`'s current implementation, with two generalizations: `keyframe_bodies_and_earth` takes `frame_count: int` instead of a `grain_files` list (it only ever used `len(grain_files)`), and `setup_camera` takes a `core_fn(i) -> Vector` callback instead of hardcoding a per-frame CSV read, so callers with no per-frame grain CSVs (the instance path) can supply a constant. Six unused config constants present in `DEMBulkVizBlender.py`'s current config block (`EARTH_MODEL_PATH`, `EARTH_PART_NAMES`, `EARTH_SHELL_SCALE`, `EARTH_ROTATE_CLOUDS`, `MOON_PHYSICAL_RADIUS_KM`, `MOON_COLOR`, `SUN_BODY_RADIUS_BU`, `SUN_COLOR`, `SUN_EMISSION_STRENGTH`, `APOPHIS_ONLY_SUN_DIRECTION`) are dead — no function in the file reads them — and are dropped rather than carried forward, since they were already unused before this refactor.

- [ ] **Step 1: Write the regression baseline script**

Before touching any code, capture the current composite-path behavior so the refactor can be checked against it. Save to the scratchpad (not the repo):

```python
# scratchpad/verify_composite_baseline.py
"""Run DEMBulkVizBlender.py against the existing regression manifest and
record Earth/camera/timeline state, to diff against the post-refactor run."""
import bpy, json, sys

MANIFEST = (
    "c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/"
    "_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001_viz/manifest.json"
)

sys.path.insert(0, r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code\BlenderConvert")
import DEMBulkVizBlender  # noqa: E402  (VIZ_MANIFEST default must be pointed at MANIFEST first, or edit the module attribute below)
DEMBulkVizBlender.VIZ_MANIFEST = MANIFEST
DEMBulkVizBlender.main()

scene = bpy.context.scene
earth = bpy.data.objects.get("Earth")
cam = bpy.data.objects.get("DEM_TrackCam")
result = {
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "earth_loc_f1": list(earth.matrix_world.translation) if earth else None,
    "cam_loc_f1": list(cam.matrix_world.translation) if cam else None,
    "cam_rot_f1": list(cam.rotation_quaternion) if cam else None,
}
scene.frame_set(scene.frame_end)
result["earth_loc_flast"] = list(earth.matrix_world.translation) if earth else None
result["cam_loc_flast"] = list(cam.matrix_world.translation) if cam else None
print("BASELINE", json.dumps(result))
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_composite_baseline.py`

Note the printed `BASELINE {...}` line — this is the value the post-refactor run must reproduce exactly (Earth/camera positions are deterministic given the same manifest and CSVs).

- [ ] **Step 2: Create `DEMCinematicSetup.py`**

```python
"""Shared cinematic scene-building for DEM bulk viz Blender scripts.

Earth/Moon/Sun placeholder, body-CSV keyframing, and a grain-core tracking
camera — extracted from DEMBulkVizBlender.py so DEMBulkInstanceBlender.py
(and any future bulk-viz path) can reuse it without duplicating cinematic
logic. DEMGrainsBlenderEarthCam.py is intentionally not built on this module
-- it keeps its own independent, proven implementation.
"""

import contextlib
import glob
import math
import os

import bpy
import mathutils
import numpy as np
import pandas as pd
from mathutils import Vector

# -- Configuration (same defaults DEMBulkVizBlender.py already used) --------
EARTH_PHYSICAL_RADIUS_KM = 6371.0
EARTH_VIS_SCALE = 0.2
EARTH_SIDEREAL_DAY_S = 86164.0905
EARTH_SPIN_AXIS = (0.0, -0.3979, 0.9174)
EARTH_ROTATION_OFFSET_DEG = 0.0
EARTH_EMPTY_NAME = 'Earth'
SUN_LAMP_ENERGY = 10.0
SUN_LAMP_ANGLE = 0.00931
SUN_VIS_SCALE = 0.003
CAMERA_NAME = 'DEM_TrackCam'
CAMERA_FOV_DEG = 70.0
CAM_DIST_BU = 150.0
CAM_ANGLE_DEG = 30.0
CAM_GRAIN_ONLY_AZIMUTH_DEG = 45.0
CAM_GRAIN_ONLY_ELEVATION_DEG = 20.0
CAM_CLIP_START = 0.01
CAM_CLIP_END = 20_000_000.0
# -----------------------------------------------------------------------------


def detect_solar_system(bodies_dir):
    csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    if not csvs:
        return False
    try:
        names = set(pd.read_csv(csvs[0], usecols=['name'])['name'].astype(str))
    except (ValueError, KeyError, OSError):
        return False
    return 'Earth' in names or 'Sun' in names


def grain_core(points_vis, fraction):
    """Centroid of the innermost ``fraction`` of points, by distance from origin."""
    if len(points_vis) == 0:
        return Vector((0.0, 0.0, 0.0))
    n = max(1, min(len(points_vis), int(len(points_vis) * fraction)))
    d2 = (points_vis * points_vis).sum(axis=1)
    inner = points_vis[np.argpartition(d2, n - 1)[:n]]
    return Vector(inner.mean(axis=0))


def ensure_earth_placeholder(has_solar, bodies_dir):
    """Create a minimal Earth Empty + UV sphere if solar-system bodies are available."""
    if not has_solar or not os.path.isdir(bodies_dir):
        return None
    earth_empty = bpy.data.objects.get(EARTH_EMPTY_NAME)
    if earth_empty is not None:
        return earth_empty
    bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0.0, 0.0, 0.0))
    earth_empty = bpy.context.object
    earth_empty.name = EARTH_EMPTY_NAME
    radius_bu = EARTH_PHYSICAL_RADIUS_KM * EARTH_VIS_SCALE
    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius_bu, segments=32, ring_count=16, location=(0.0, 0.0, 0.0)
    )
    surf = bpy.context.object
    surf.name = 'Surface'
    surf.parent = earth_empty
    print(f'Earth placeholder created (radius {radius_bu:.1f} BU).')
    return earth_empty


def keyframe_bodies_and_earth(bodies_dir, frame_count, has_solar, earth_empty=None):
    """Minimal bodies keyframing for Earth / Moon / Sun (subset of DEMGrainsBlenderEarthCam)."""
    if not has_solar or not os.path.isdir(bodies_dir):
        return earth_empty

    if earth_empty is None:
        earth_empty = bpy.data.objects.get(EARTH_EMPTY_NAME)
    sun_lamp = bpy.data.objects.get('DEM_SunLight')
    if sun_lamp is None and has_solar:
        lamp_data = bpy.data.lights.new('DEM_SunLight', 'SUN')
        lamp_data.energy = SUN_LAMP_ENERGY
        lamp_data.angle = SUN_LAMP_ANGLE
        sun_lamp = bpy.data.objects.new('DEM_SunLight', lamp_data)
        bpy.context.scene.collection.objects.link(sun_lamp)
    moon_empty = bpy.data.objects.get('Moon')
    sun_body = bpy.data.objects.get('Sun_Visual')

    bodies_csvs = sorted(glob.glob(os.path.join(bodies_dir, '*.csv')))
    n = min(frame_count, len(bodies_csvs))
    if n == 0:
        return earth_empty

    spin_axis = Vector(EARTH_SPIN_AXIS).normalized()
    offset_rad = math.radians(EARTH_ROTATION_OFFSET_DEG)

    for i in range(n):
        frame = bpy.context.scene.frame_start + i
        bpy.context.scene.frame_set(frame)
        df = pd.read_csv(bodies_csvs[i])
        apo = df[df['name'] == 'Apophis']
        if apo.empty:
            continue
        apo = apo.iloc[0]

        if earth_empty is not None and 'Earth' in df['name'].values:
            earth = df[df['name'] == 'Earth'].iloc[0]
            ex = (float(earth['x_km']) - float(apo['x_km'])) * EARTH_VIS_SCALE
            ey = (float(earth['y_km']) - float(apo['y_km'])) * EARTH_VIS_SCALE
            ez = (float(earth['z_km']) - float(apo['z_km'])) * EARTH_VIS_SCALE
            earth_empty.location = (ex, ey, ez)
            earth_empty.keyframe_insert(data_path='location', frame=frame)
            if 'time_s' in earth.index and pd.notna(earth['time_s']):
                t_s = float(earth['time_s'])
                angle = (t_s / EARTH_SIDEREAL_DAY_S) * 2.0 * math.pi + offset_rad
                q = mathutils.Quaternion(spin_axis, angle)
                for child in earth_empty.children_recursive:
                    if child.name.startswith('Surface') or child.name.startswith('Clouds'):
                        child.rotation_quaternion = q
                        child.keyframe_insert(data_path='rotation_quaternion', frame=frame)

        if sun_lamp is not None and 'Sun' in df['name'].values:
            sun = df[df['name'] == 'Sun'].iloc[0]
            sx = float(sun['x_km']) - float(apo['x_km'])
            sy = float(sun['y_km']) - float(apo['y_km'])
            sz = float(sun['z_km']) - float(apo['z_km'])
            direction = Vector((sx, sy, sz))
            if direction.length > 1e-6:
                direction.normalize()
                sun_lamp.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
                sun_lamp.keyframe_insert(data_path='rotation_euler', frame=frame)

        if moon_empty is not None and 'Moon' in df['name'].values:
            moon = df[df['name'] == 'Moon'].iloc[0]
            mx = (float(moon['x_km']) - float(apo['x_km'])) * EARTH_VIS_SCALE
            my = (float(moon['y_km']) - float(apo['y_km'])) * EARTH_VIS_SCALE
            mz = (float(moon['z_km']) - float(apo['z_km'])) * EARTH_VIS_SCALE
            moon_empty.location = (mx, my, mz)
            moon_empty.keyframe_insert(data_path='location', frame=frame)

        if sun_body is not None and 'Sun' in df['name'].values:
            sun = df[df['name'] == 'Sun'].iloc[0]
            sx = (float(sun['x_km']) - float(apo['x_km'])) * SUN_VIS_SCALE
            sy = (float(sun['y_km']) - float(apo['y_km'])) * SUN_VIS_SCALE
            sz = (float(sun['z_km']) - float(apo['z_km'])) * SUN_VIS_SCALE
            sun_body.location = (sx, sy, sz)
            sun_body.keyframe_insert(data_path='location', frame=frame)

    return earth_empty


def setup_camera(frame_count, core_fn, earth_empty, has_solar, camera_mode=None):
    """Keyframe a tracking camera. ``core_fn(i)`` returns the frame-``i`` aim point."""
    scene = bpy.context.scene
    cam_data = bpy.data.cameras.get(CAMERA_NAME) or bpy.data.cameras.new(CAMERA_NAME)
    cam_data.lens_unit = 'FOV'
    cam_data.angle = math.radians(CAMERA_FOV_DEG)
    cam_data.clip_start = CAM_CLIP_START
    cam_data.clip_end = CAM_CLIP_END
    cam_obj = bpy.data.objects.get(CAMERA_NAME)
    if cam_obj is None:
        cam_obj = bpy.data.objects.new(CAMERA_NAME, cam_data)
        scene.collection.objects.link(cam_obj)
    else:
        cam_obj.data = cam_data
    cam_obj.rotation_mode = 'QUATERNION'
    scene.camera = cam_obj

    use_earth = (
        camera_mode == 'earth_track'
        if camera_mode in ('earth_track', 'grain_only')
        else (earth_empty is not None and has_solar)
    )
    n = min(scene.frame_end - scene.frame_start + 1, frame_count)
    _Z = Vector((0.0, 0.0, 1.0))
    _X = Vector((1.0, 0.0, 0.0))
    angle_rad = math.radians(CAM_ANGLE_DEG)
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

    for i in range(n):
        frame = scene.frame_start + i
        scene.frame_set(frame)
        core = core_fn(i)
        if use_earth and earth_empty is not None:
            earth_pos = earth_empty.matrix_world.translation.copy()
            earth_vec = earth_pos - core
            dist = earth_vec.length
            earth_from_core = earth_vec / dist if dist > 1e-6 else _X.copy()
            offset_dir = earth_from_core.cross(_Z)
            if offset_dir.length < 1e-4:
                offset_dir = earth_from_core.cross(_X)
            offset_dir.normalize()
            cam_pos = core + offset_dir * (CAM_DIST_BU * cos_a) + _Z * (CAM_DIST_BU * sin_a)
            look = (core - cam_pos).normalized()
            q = look.to_track_quat('-Z', 'Y')
        else:
            az = math.radians(CAM_GRAIN_ONLY_AZIMUTH_DEG)
            el = math.radians(CAM_GRAIN_ONLY_ELEVATION_DEG)
            offset = Vector((
                math.cos(el) * math.cos(az),
                math.cos(el) * math.sin(az),
                math.sin(el),
            )).normalized()
            cam_pos = core + offset * CAM_DIST_BU
            look = (core - cam_pos).normalized()
            q = look.to_track_quat('-Z', 'Y')
        cam_obj.location = cam_pos
        cam_obj.rotation_quaternion = q
        cam_obj.keyframe_insert(data_path='location', frame=frame)
        cam_obj.keyframe_insert(data_path='rotation_quaternion', frame=frame)


@contextlib.contextmanager
def frame_handler_suspended(handler):
    """Detach ``handler`` around setup loops that call scene.frame_set().

    Keyframing and camera setup step every frame; with a per-frame handler
    attached, each step would reload that frame's data from disk for nothing.
    """
    handlers = bpy.app.handlers.frame_change_pre
    attached = handler in handlers
    if attached:
        handlers.remove(handler)
    try:
        yield
    finally:
        if attached and handler not in handlers:
            handlers.append(handler)
```

- [ ] **Step 3: Refactor `DEMBulkVizBlender.py` to use it**

Add near the top imports (after the existing `import` block, before `# Configuration`):

```python
import sys

BLENDER_CONVERT_DIR = 'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert'
if BLENDER_CONVERT_DIR not in sys.path:
    sys.path.insert(0, BLENDER_CONVERT_DIR)
import DEMCinematicSetup as cinematic  # noqa: E402
```

Delete these lines from the configuration block (lines 36-61 in the current file — the Earth/Sun/Moon/camera constants now owned by `DEMCinematicSetup`, keeping `CORE_GRAIN_FRACTION` since it configures how *this* caller picks a `grain_core` fraction, not generic camera math):

```python
EARTH_MODEL_PATH = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert/TheEarth1.blend'
)
EARTH_PART_NAMES = ['Surface', 'Atmosphere', 'Clouds']
EARTH_PHYSICAL_RADIUS_KM = 6371.0
EARTH_VIS_SCALE = 0.2
EARTH_SHELL_SCALE = {'Atmosphere': 1.004, 'Clouds': 1.002}
EARTH_SIDEREAL_DAY_S = 86164.0905
EARTH_SPIN_AXIS = (0.0, -0.3979, 0.9174)
EARTH_ROTATION_OFFSET_DEG = 0.0
EARTH_ROTATE_CLOUDS = True
EARTH_EMPTY_NAME = 'Earth'
MOON_PHYSICAL_RADIUS_KM = 1737.53
MOON_COLOR = (0.55, 0.55, 0.55, 1.0)
SUN_LAMP_ENERGY = 10.0
SUN_LAMP_ANGLE = 0.00931
SUN_VIS_SCALE = 0.003
SUN_BODY_RADIUS_BU = 10000.0
SUN_COLOR = (1.0, 1.0, 1.0, 1.0)
SUN_EMISSION_STRENGTH = 6000.0
APOPHIS_ONLY_SUN_DIRECTION = (1.0, 0.0, 0.0)
CAMERA_NAME = 'DEM_TrackCam'
CAMERA_FOV_DEG = 70.0
CAM_DIST_BU = 150.0
CAM_ANGLE_DEG = 30.0
CORE_GRAIN_FRACTION = 0.80
CAM_GRAIN_ONLY_AZIMUTH_DEG = 45.0
CAM_GRAIN_ONLY_ELEVATION_DEG = 20.0
CAM_CLIP_START = 0.01
CAM_CLIP_END = 20_000_000.0
```

Replace with just:

```python
CORE_GRAIN_FRACTION = 0.80
```

Delete these functions entirely (now in `DEMCinematicSetup`): `_detect_solar_system`, `_grain_core_from_csv`, `_frame_handler_suspended`, `_ensure_earth_placeholder`, `_keyframe_bodies_and_earth`, `_setup_simple_camera`.

Replace `main()`'s body from:

```python
    has_solar = (
        bool(IMPORT_SOLAR_SYSTEM)
        if IMPORT_SOLAR_SYSTEM is not None
        else _detect_solar_system(bodies_dir)
    )
```

with:

```python
    has_solar = (
        bool(IMPORT_SOLAR_SYSTEM)
        if IMPORT_SOLAR_SYSTEM is not None
        else cinematic.detect_solar_system(bodies_dir)
    )
```

and replace:

```python
    earth_empty = _ensure_earth_placeholder(has_solar, bodies_dir)
    with _frame_handler_suspended():
        earth_empty = _keyframe_bodies_and_earth(bodies_dir, grain_files, has_solar, earth_empty)
        if SETUP_CAMERA and grain_files:
            _setup_simple_camera(grain_files, earth_empty, has_solar)
        scene.frame_set(scene.frame_start)
```

with:

```python
    earth_empty = cinematic.ensure_earth_placeholder(has_solar, bodies_dir)
    with cinematic.frame_handler_suspended(_viz_frame_change_handler):
        earth_empty = cinematic.keyframe_bodies_and_earth(
            bodies_dir, len(frame_ids), has_solar, earth_empty
        )
        if SETUP_CAMERA and grain_files:
            def _core_fn(i, _files=grain_files):
                pts = pd.read_csv(
                    _files[i], usecols=['x_vis', 'y_vis', 'z_vis']
                ).to_numpy(dtype=np.float64)
                return cinematic.grain_core(pts, CORE_GRAIN_FRACTION)
            cinematic.setup_camera(
                len(grain_files), _core_fn, earth_empty, has_solar, camera_mode=CAMERA_MODE
            )
        scene.frame_set(scene.frame_start)
```

- [ ] **Step 4: Run the regression script again and diff**

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_composite_baseline.py`

Expected: the printed `BASELINE {...}` JSON is byte-for-byte identical (same floats) to Step 1's output — the refactor changed no behavior. If any field differs, the extraction introduced a regression; do not proceed until it matches.

- [ ] **Step 5: Commit**

```bash
git add BlenderConvert/DEMCinematicSetup.py BlenderConvert/DEMBulkVizBlender.py
git commit -m "refactor: extract shared cinematic setup from DEMBulkVizBlender.py

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RKov96Ynx5hxHrG2GeSXWY"
```

(Do not push. Do not commit until the user has tested this against their own open Blender session, per standing project rule.)

---

### Task 2: `viz/shape_sampling.py`

**Files:**
- Create: `viz/shape_sampling.py`

**Interfaces:**
- Produces (consumed by Task 3):
  - `load_obj_shape(path: str) -> tuple[np.ndarray, np.ndarray]` — `(verts Nx3 float64, faces Mx3 int32)`
  - `center_and_scale(verts: np.ndarray, target_radius: float) -> tuple[np.ndarray, float]` — `(scaled_verts, scale_factor)`
  - `build_bvh(verts: np.ndarray, faces: np.ndarray) -> mathutils.bvhtree.BVHTree`
  - `points_inside_shape(bvh: BVHTree, points: np.ndarray) -> np.ndarray` (bool, shape `(N,)`)
  - `sample_points_in_shape(verts: np.ndarray, faces: np.ndarray, n_points: int, seed: int = 0, batch_size: int = 400_000) -> np.ndarray` (`(n_points, 3)` float32)
- Consumes: `mathutils.bvhtree.BVHTree` (`bpy`-bundled) — this module only runs under Blender's Python.

This logic is moved verbatim (generalized to drop the hardcoded OBJ path and per-batch printing) from the scratchpad script `p0_blend_apophis.py`, which already proved it correct by building `BlenderConvert/P0_Apophis_1M.blend`.

- [ ] **Step 1: Write the failing verification script**

```python
# scratchpad/verify_shape_sampling.py
"""Headless check: sample 2,000 points inside the real Apophis shape model
and confirm every one is inside, and the cluster radius matches the target."""
import sys
sys.path.insert(0, r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code")
from viz.shape_sampling import load_obj_shape, center_and_scale, build_bvh, points_inside_shape, sample_points_in_shape
import numpy as np

OBJ = (
    r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code\BlenderConvert\Shapes"
    r"\gbo.ast-apophis.jpl.radar.shape_model_v1.0"
    r"\gbo.ast-apophis.jpl.radar.shape_model_v1.0\data\apophis_v233s7.obj"
)

verts, faces = load_obj_shape(OBJ)
assert len(verts) > 1000 and len(faces) > 1000, f"unexpected shape size: {len(verts)} verts {len(faces)} faces"

verts_scaled, scale = center_and_scale(verts, target_radius=10.844)
assert abs(np.linalg.norm(verts_scaled, axis=1).max() - 10.844) < 1e-6

pos = sample_points_in_shape(verts_scaled, faces, n_points=2000, seed=0)
assert pos.shape == (2000, 3)
bvh = build_bvh(verts_scaled, faces)
inside = points_inside_shape(bvh, pos.astype(np.float64))
assert inside.all(), f"{(~inside).sum()} sampled points landed outside the shell"
print("OK: shape_sampling verified")
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_shape_sampling.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'viz.shape_sampling'`.

- [ ] **Step 2: Implement `viz/shape_sampling.py`**

```python
"""JPL shape-model OBJ loading and BVH-based interior point sampling.

Moved from an exploratory scratchpad script into a reusable module for
viz_preprocess_lite.py's placeholder point-cloud generation. Needs
mathutils.bvhtree, so this module only runs under Blender's bundled Python
-- not the plain Windows venv.
"""

import numpy as np
from mathutils.bvhtree import BVHTree


def load_obj_shape(path):
    """Read an OBJ's vertices and triangle faces (ignores everything else)."""
    verts, faces = [], []
    with open(path) as fh:
        for line in fh:
            if line.startswith('v '):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith('f '):
                faces.append([int(t.split('/')[0]) - 1 for t in line.split()[1:4]])
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int32)


def center_and_scale(verts, target_radius):
    """Center on the bounding box and scale so the far-most vertex sits at ``target_radius``.

    Returns ``(scaled_verts, scale_factor)``.
    """
    centre = 0.5 * (verts.min(axis=0) + verts.max(axis=0))
    v = verts - centre
    scale = target_radius / np.linalg.norm(v, axis=1).max()
    return v * scale, scale


def build_bvh(verts, faces):
    return BVHTree.FromPolygons([tuple(v) for v in verts], [tuple(f) for f in faces])


def points_inside_shape(bvh, points):
    """Signed-distance sign test against the closed shell (per-point BVH nearest-face query)."""
    out = np.empty(len(points), dtype=bool)
    for i, p in enumerate(points):
        loc, nrm, _idx, _dist = bvh.find_nearest(tuple(p))
        out[i] = ((p[0] - loc.x) * nrm.x + (p[1] - loc.y) * nrm.y + (p[2] - loc.z) * nrm.z) < 0.0
    return out


def sample_points_in_shape(verts, faces, n_points, seed=0, batch_size=400_000):
    """Rejection-sample ``n_points`` inside the closed shell defined by ``verts``/``faces``.

    ``verts`` must already be in the caller's target units/scale (see
    :func:`center_and_scale`); a winding-inverted mesh (centroid classified
    outside) raises AssertionError.
    """
    bvh = build_bvh(verts, faces)
    assert points_inside_shape(bvh, np.zeros((1, 3)))[0], (
        'winding inverted: centre classified outside'
    )
    lo, hi = verts.min(axis=0), verts.max(axis=0)
    rng = np.random.default_rng(seed)
    kept, got = [], 0
    while got < n_points:
        cand = rng.uniform(lo, hi, size=(batch_size, 3))
        good = cand[points_inside_shape(bvh, cand)]
        kept.append(good)
        got += len(good)
    return np.concatenate(kept)[:n_points].astype(np.float32)
```

- [ ] **Step 3: Run the verification script and confirm it passes**

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_shape_sampling.py`
Expected: `OK: shape_sampling verified`

- [ ] **Step 4: Commit**

```bash
git add viz/shape_sampling.py
git commit -m "feat: add shape-model rejection sampling for the instance viz path

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RKov96Ynx5hxHrG2GeSXWY"
```

---

### Task 3: `viz/viz_preprocess_lite.py`

**Files:**
- Create: `viz/viz_preprocess_lite.py`

**Interfaces:**
- Consumes: `viz.shape_sampling.{load_obj_shape, center_and_scale, sample_points_in_shape}` (Task 2).
- Produces: an `output_dir/manifest.json` with `viz_mode: "instance"` and an `output_dir/points.npz` (`pos` key only), consumed by Task 4's `DEMBulkInstanceBlender.py`.
- Manifest schema (per the design spec):
  ```json
  {
    "schema_version": 1,
    "viz_mode": "instance",
    "sim_name": "...",
    "run_name": "...",
    "n_frames": <int>,
    "frame_ids": ["00000", "00001", ...],
    "bodies_csv_dir": "<relative path>",
    "static": true,
    "points_path": "points.npz",
    "grain_radius_vis": <float>,
    "n_points": <int>,
    "reference_cluster_radius_vis": <float>,
    "reference_grain_radius_vis": <float>,
    "reference_n": <int>,
    "shape_obj": "<path as given>"
  }
  ```

Runs under Blender's bundled Python (needs `viz.shape_sampling`'s `mathutils.bvhtree` dependency), invoked as `blender --background --python viz/viz_preprocess_lite.py -- <args>`, matching `P0_InstancingSpike.py`'s precedent for the one script in this repo that can't run in the plain venv.

- [ ] **Step 1: Write the failing verification script**

```python
# scratchpad/verify_preprocess_lite.py
"""Headless check: preprocess run_0001 into a placeholder instance manifest
and confirm the reference-scale numbers match the values hand-derived in the
superseded 11_MillionApophis spec (frame-1 cluster radius 10.844 BU, grain
radius 0.9528 BU for np=500)."""
import sys, json
sys.path.insert(0, r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code")
from viz.viz_preprocess_lite import reference_scale_from_run, grain_radius_for, run_preprocess_lite
from pathlib import Path

ROOT = Path(r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code")
GRAINS = ROOT / "DEMCSVs/torque_align_obj/run_0001_grains_output"
BODIES = ROOT / "DEMCSVs/torque_align_obj/run_0001_bodies_output"
SHAPE = (ROOT / "BlenderConvert/Shapes/gbo.ast-apophis.jpl.radar.shape_model_v1.0"
         "/gbo.ast-apophis.jpl.radar.shape_model_v1.0/data/apophis_v233s7.obj")
OUT = ROOT / "scratchpad" / "run_0001_viz_instance_test"

cluster_r, grain_r, ref_n = reference_scale_from_run(GRAINS, BODIES)
assert abs(cluster_r - 10.844) < 0.01, f"cluster radius {cluster_r} != ~10.844"
assert abs(grain_r - 0.9528) < 0.001, f"grain radius {grain_r} != ~0.9528"
assert ref_n == 500, f"ref_n {ref_n} != 500"

r_1e6 = grain_radius_for(1_000_000, ref_n, grain_r)
assert abs(r_1e6 - 0.9528 * (500 / 1_000_000) ** (1 / 3)) < 1e-6

manifest_path = run_preprocess_lite(GRAINS, BODIES, OUT, SHAPE, n_points=2000, seed=0)
manifest = json.loads(manifest_path.read_text())
assert manifest["viz_mode"] == "instance"
assert manifest["static"] is True
assert manifest["n_points"] == 2000
assert (OUT / "points.npz").is_file()

import numpy as np
pos = np.load(OUT / "points.npz")["pos"]
assert pos.shape == (2000, 3)
print("OK: viz_preprocess_lite verified", manifest["grain_radius_vis"])
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_preprocess_lite.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'viz.viz_preprocess_lite'`.

- [ ] **Step 2: Implement `viz/viz_preprocess_lite.py`**

```python
#!/usr/bin/env python3
"""Preprocess a placeholder point cloud into a bulk instancing manifest (Option A).

Rejection-samples a shape OBJ into a static million-point cloud, scaled and
sized from a real run's grains/bodies CSVs, and writes a `viz_mode: "instance"`
manifest that DEMBulkInstanceBlender.py consumes exactly as
DEMBulkVizBlender.py consumes a `viz_mode: "composite"` manifest.

Runs under Blender's bundled Python (needs mathutils.bvhtree via
viz/shape_sampling.py), not the plain venv:

    & "C:\\Program Files\\Blender Foundation\\Blender 5.2\\blender.exe" --background --python viz/viz_preprocess_lite.py -- \\
        --grains-dir DEMCSVs/torque_align_obj/run_0001_grains_output \\
        --bodies-dir DEMCSVs/torque_align_obj/run_0001_bodies_output \\
        --output-dir DEMCSVs/torque_align_obj/run_0001_viz_instance \\
        --shape-obj "BlenderConvert/Shapes/.../apophis_v233s7.obj" \\
        --n-points 1000000

Real per-frame million-grain CSV ingestion (`static: false`) is not
implemented -- deferred until such simulation data exists.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.shape_sampling import (  # noqa: E402
    center_and_scale,
    load_obj_shape,
    sample_points_in_shape,
)


def _blender_argv(argv):
    """Strip Blender's own args, returning everything after the ``--`` separator."""
    if '--' in argv:
        return argv[argv.index('--') + 1:]
    return argv[1:]


def reference_scale_from_run(grains_dir, bodies_dir):
    """(reference_cluster_radius_bu, reference_grain_radius_bu, reference_n) from frame 1.

    Cluster radius is the frame-1 grains' max distance from the origin in
    x_vis/y_vis/z_vis (already Apophis-CoM-centered, per the grains CSV
    convention); grain radius is the mean of Reff_vis -- uniform per run in
    practice, mean guards against float noise.
    """
    grains_dir = Path(grains_dir)
    csvs = sorted(glob.glob(str(grains_dir / '*.csv')))
    if not csvs:
        raise FileNotFoundError(f'No grain CSVs in {grains_dir}')
    df = pd.read_csv(csvs[0])
    for col in ('x_vis', 'y_vis', 'z_vis', 'Reff_vis'):
        if col not in df.columns:
            raise ValueError(f'{csvs[0]} missing required column {col!r}')
    pts = df[['x_vis', 'y_vis', 'z_vis']].to_numpy(dtype=np.float64)
    cluster_radius = float(np.linalg.norm(pts, axis=1).max())
    grain_radius = float(df['Reff_vis'].mean())
    return cluster_radius, grain_radius, len(df)


def grain_radius_for(n_points, ref_n, ref_grain_radius_vis):
    """Volume-conserving grain radius at ``n_points``, anchored on the run's own reference."""
    return ref_grain_radius_vis * (ref_n / float(n_points)) ** (1.0 / 3.0)


def run_preprocess_lite(
    grains_dir,
    bodies_dir,
    output_dir,
    shape_obj,
    n_points,
    *,
    sim_name=None,
    run_name=None,
    seed=0,
):
    grains_dir = Path(grains_dir).resolve()
    bodies_dir = Path(bodies_dir).resolve()
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if run_name is None:
        name = grains_dir.name
        run_name = name.replace('_grains_output', '') if name.endswith('_grains_output') else name
    if sim_name is None:
        sim_name = grains_dir.parent.name

    cluster_radius, grain_radius, ref_n = reference_scale_from_run(grains_dir, bodies_dir)
    print(f'reference: cluster_radius={cluster_radius:.4f} BU '
          f'grain_radius={grain_radius:.4f} BU (n={ref_n}, run={run_name})')

    verts, faces = load_obj_shape(str(shape_obj))
    verts, scale = center_and_scale(verts, cluster_radius)
    print(f'shape: {len(verts)} verts scaled by {scale:.6f} to fit cluster_radius')

    pos = sample_points_in_shape(verts, faces, n_points, seed=seed)
    points_path = output_dir / 'points.npz'
    np.savez_compressed(points_path, pos=pos)
    print(f'wrote {len(pos):,} points -> {points_path}')

    grain_radius_vis = grain_radius_for(n_points, ref_n, grain_radius)

    bodies_csvs = sorted(glob.glob(str(bodies_dir / '*.csv')))
    frame_ids = [f'{i:05d}' for i in range(len(bodies_csvs))]

    rel_bodies = os.path.relpath(bodies_dir, output_dir).replace(os.sep, '/')
    manifest = {
        'schema_version': 1,
        'viz_mode': 'instance',
        'sim_name': sim_name,
        'run_name': run_name,
        'n_frames': len(frame_ids),
        'frame_ids': frame_ids,
        'bodies_csv_dir': rel_bodies,
        'static': True,
        'points_path': 'points.npz',
        'grain_radius_vis': grain_radius_vis,
        'n_points': n_points,
        'reference_cluster_radius_vis': cluster_radius,
        'reference_grain_radius_vis': grain_radius,
        'reference_n': ref_n,
        'shape_obj': str(shape_obj),
    }
    manifest_path = output_dir / 'manifest.json'
    with open(manifest_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, indent=2)
    print(f'Wrote manifest -> {manifest_path}')
    return manifest_path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--grains-dir', type=Path, required=True)
    p.add_argument('--bodies-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--shape-obj', type=Path, required=True)
    p.add_argument('--n-points', type=int, default=1_000_000)
    p.add_argument('--sim-name', type=str, default=None)
    p.add_argument('--run-name', type=str, default=None)
    p.add_argument('--seed', type=int, default=0)
    args = p.parse_args(_blender_argv(sys.argv))

    print(f'viz_preprocess_lite: {args.grains_dir} + {args.shape_obj} -> {args.output_dir}')
    run_preprocess_lite(
        args.grains_dir, args.bodies_dir, args.output_dir, args.shape_obj,
        args.n_points, sim_name=args.sim_name, run_name=args.run_name, seed=args.seed,
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
```

- [ ] **Step 3: Run the verification script and confirm it passes**

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_preprocess_lite.py`
Expected: `OK: viz_preprocess_lite verified 0.10556...` (the 2000-point grain radius; not the full 1e6 value from `r_1e6`, which is only asserted, not printed).

- [ ] **Step 4: Commit**

```bash
git add viz/viz_preprocess_lite.py
git commit -m "feat: add placeholder-mode preprocessing for the instance viz path

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RKov96Ynx5hxHrG2GeSXWY"
```

---

### Task 4: `BlenderConvert/DEMBulkInstanceBlender.py`

**Files:**
- Create: `BlenderConvert/DEMBulkInstanceBlender.py`

**Interfaces:**
- Consumes:
  - `DEMCinematicSetup.{detect_solar_system, ensure_earth_placeholder, keyframe_bodies_and_earth, setup_camera, frame_handler_suspended}` (Task 1)
  - `P0_InstancingSpike.{_make_icosphere(subdiv, radius=1.0), build_geometry_nodes(point_obj, instance_obj) -> (group, modifier), RADIUS_ATTR}` (existing, unmodified)
  - `viz/viz_preprocess_lite.py`'s manifest + `points.npz` output (Task 3)
- Produces: a `.blend` scene with `DEM_InstancePoints` (GN-instanced point cloud), Earth/camera/timeline, ready to render.

The "Procedural rock" material is **looked up by name, not appended from a guessed asset file** — the repo has several similarly-named rock materials under `BlenderConvert/Blenders/assets/materials/`, and the design spec's reference to "already validated live on P0_Apophis_1M.blend" describes a manual, interactive step, not a script-driven one. Verification (Step 3 below) appends it once from `P0_Apophis_1M.blend` into the test file before running.

- [ ] **Step 1: Write the failing verification script**

```python
# scratchpad/verify_instance_blender.py
"""Headless check: run DEMBulkInstanceBlender.py against the Task 3 test
manifest and confirm Earth/camera exist and the GN instance count matches
the point count."""
import bpy, sys, json

ROOT = r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code"

# Prerequisite: append 'Procedural rock' from P0_Apophis_1M.blend so the
# instance script's material lookup succeeds.
with bpy.data.libraries.load(ROOT + r"\BlenderConvert\P0_Apophis_1M.blend", link=False) as (src, dst):
    if "Procedural rock" in src.materials:
        dst.materials = ["Procedural rock"]

sys.path.insert(0, ROOT + r"\BlenderConvert")
import DEMBulkInstanceBlender as instmod
instmod.VIZ_MANIFEST = ROOT + r"\scratchpad\run_0001_viz_instance_test\manifest.json"
instmod.main()

manifest = json.load(open(instmod.VIZ_MANIFEST, encoding="utf-8"))
n_points = manifest["n_points"]

assert bpy.data.objects.get("Earth") is not None, "Earth placeholder missing"
assert bpy.data.objects.get("DEM_TrackCam") is not None, "camera missing"

bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
n_inst = sum(1 for i in dg.object_instances if i.is_instance)
assert n_inst == n_points, f"expected {n_points} GN instances, got {n_inst}"
print(f"OK: DEMBulkInstanceBlender verified ({n_inst} instances)")
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_instance_blender.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'DEMBulkInstanceBlender'`. (Task 3's `scratchpad/run_0001_viz_instance_test/manifest.json` from its own verification run must already exist — rerun Task 3's Step 3 first if it was cleaned up.)

- [ ] **Step 2: Implement `BlenderConvert/DEMBulkInstanceBlender.py`**

```python
"""Bulk DEM visualisation -- pure point-cloud instancing (Option A, Objective 3).

Paste into Blender Scripting tab (or open the file directly). Reads a
``viz_mode: "instance"`` manifest from viz_preprocess_lite.py. Existing
per-sphere and composite importers are unchanged.
"""

import glob
import json
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

BLENDER_CONVERT_DIR = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert'
)
if BLENDER_CONVERT_DIR not in sys.path:
    sys.path.insert(0, BLENDER_CONVERT_DIR)

import DEMCinematicSetup as cinematic  # noqa: E402
import P0_InstancingSpike as p0  # noqa: E402

# -- Configuration ------------------------------------------------------------
VIZ_MANIFEST = (
    'c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/'
    'torque_align_obj/run_0001_viz_instance/manifest.json'
)
BODIES_CSV_DIR = None
IMPORT_SOLAR_SYSTEM = None
SETUP_CAMERA = True
GRAIN_SUBDIV = 1
PROCEDURAL_ROCK_MAT_NAME = 'Procedural rock'
# -----------------------------------------------------------------------------

_viz_state = {
    'manifest': None,
    'viz_dir': None,
    'points_path': None,
    'static': True,
    'loaded_frame': -1,
}


def _load_manifest(path):
    with open(path, encoding='utf-8') as fh:
        manifest = json.load(fh)
    if manifest.get('viz_mode') != 'instance':
        raise ValueError(
            f'manifest viz_mode={manifest.get("viz_mode")!r} (expected "instance"); '
            f'use DEMBulkVizBlender.py for "composite" manifests.'
        )
    viz_dir = os.path.dirname(os.path.abspath(path))
    return manifest, viz_dir


def _resolve_bodies_dir(manifest, viz_dir):
    if BODIES_CSV_DIR:
        return BODIES_CSV_DIR
    rel = manifest.get('bodies_csv_dir', '')
    return os.path.normpath(os.path.join(viz_dir, rel))


def _get_procedural_rock_material():
    """Look up the 'Procedural rock' material already validated on P0_Apophis_1M.blend.

    Not auto-appended: several similarly-named rock materials exist under
    BlenderConvert/Blenders/assets/materials/, so guessing the source .blend
    would risk silently picking the wrong one. Append it manually (File >
    Append > Material, from P0_Apophis_1M.blend or 11.blend) before running
    this script if it is not already present.
    """
    mat = bpy.data.materials.get(PROCEDURAL_ROCK_MAT_NAME)
    if mat is None:
        raise RuntimeError(
            f'{PROCEDURAL_ROCK_MAT_NAME!r} material not found. Append it from '
            f'P0_Apophis_1M.blend or 11.blend (File > Append > Material) before '
            f'running this script.'
        )
    return mat


def _cleanup_previous():
    """Remove datablocks from a prior run so re-running this script is idempotent.

    bpy.data.meshes.new() / node_groups.new() always create a new datablock
    (never reuse by name), so without this a re-run leaks
    DEM_InstanceMesh.001, P0_InstanceOnPoints.001, ... on every click of
    Run Script -- the same class of bug DEMBulkVizBlender.py's GN node-group
    already had fixed.
    """
    for name in ('DEM_InstancePoints', 'DEM_InstanceMesh'):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    for name in ('DEM_InstancePoints_mesh', 'P0_IcoMesh'):
        mesh = bpy.data.meshes.get(name)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    group = bpy.data.node_groups.get('P0_InstanceOnPoints')
    if group is not None and group.users == 0:
        bpy.data.node_groups.remove(group)


def _build_point_cloud(pos, grain_radius_vis, subdiv):
    """Point-cloud mesh + shared icosphere + GN 'Instance on Points', via P0_InstancingSpike."""
    n_points = len(pos)
    mesh = bpy.data.meshes.new('DEM_InstancePoints_mesh')
    mesh.vertices.add(n_points)
    mesh.vertices.foreach_set('co', np.ascontiguousarray(pos).ravel())
    mesh.update()

    attr = mesh.attributes.new(p0.RADIUS_ATTR, 'FLOAT', 'POINT')
    attr.data.foreach_set('value', np.full(n_points, grain_radius_vis, dtype=np.float32))

    point_obj = bpy.data.objects.new('DEM_InstancePoints', mesh)
    bpy.context.scene.collection.objects.link(point_obj)

    material = _get_procedural_rock_material()
    ico_mesh = p0._make_icosphere(subdiv)
    ico_mesh.materials.append(material)
    instance_obj = bpy.data.objects.new('DEM_InstanceMesh', ico_mesh)
    bpy.context.scene.collection.objects.link(instance_obj)
    instance_obj.hide_render = True
    instance_obj.hide_viewport = True

    group, _modifier = p0.build_geometry_nodes(point_obj, instance_obj)
    return point_obj, group


@bpy.app.handlers.persistent
def _instance_frame_change_handler(scene):
    """Per-frame update hook. No-op today (manifest['static'] == True).

    When a future manifest sets 'static': False, this becomes the only place
    that needs new code -- load points_path/{frame:05d}.npz for the current
    frame and re-upload it, mirroring DEMBulkVizBlender.py's
    _update_ejecta_obj.
    """
    return


def main():
    manifest_path = os.path.abspath(VIZ_MANIFEST)
    manifest, viz_dir = _load_manifest(manifest_path)
    frame_ids = manifest['frame_ids']
    bodies_dir = _resolve_bodies_dir(manifest, viz_dir)

    has_solar = (
        bool(IMPORT_SOLAR_SYSTEM)
        if IMPORT_SOLAR_SYSTEM is not None
        else cinematic.detect_solar_system(bodies_dir)
    )
    print(f'DEMBulkInstanceBlender: {manifest["sim_name"]}/{manifest["run_name"]} '
          f'({len(frame_ids)} frames, mode={manifest.get("viz_mode")}, '
          f'static={manifest.get("static")})')

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(1, len(frame_ids))
    scene.render.fps = 24

    _cleanup_previous()

    points_path = os.path.join(viz_dir, manifest['points_path'])
    data = np.load(points_path)
    pos = data['pos']
    point_obj, _group = _build_point_cloud(pos, manifest['grain_radius_vis'], GRAIN_SUBDIV)
    print(f'point cloud: {len(pos):,} points, grain_radius={manifest["grain_radius_vis"]:.4f} BU')

    _viz_state.update({
        'manifest': manifest,
        'viz_dir': viz_dir,
        'points_path': points_path,
        'static': bool(manifest.get('static', True)),
        'loaded_frame': -1,
    })

    if _instance_frame_change_handler in bpy.app.handlers.frame_change_pre:
        bpy.app.handlers.frame_change_pre.remove(_instance_frame_change_handler)
    if not _viz_state['static']:
        bpy.app.handlers.frame_change_pre.append(_instance_frame_change_handler)

    earth_empty = cinematic.ensure_earth_placeholder(has_solar, bodies_dir)
    with cinematic.frame_handler_suspended(_instance_frame_change_handler):
        earth_empty = cinematic.keyframe_bodies_and_earth(
            bodies_dir, len(frame_ids), has_solar, earth_empty
        )
        if SETUP_CAMERA:
            def _core_fn(_i):
                return Vector((0.0, 0.0, 0.0))  # static rigid body, centered on Apophis CoM
            cinematic.setup_camera(len(frame_ids), _core_fn, earth_empty, has_solar)
        scene.frame_set(scene.frame_start)

    print(f'Done. "{point_obj.name}" GN-instanced, {len(pos):,} points.')


main()
```

- [ ] **Step 3: Run the verification script and confirm it passes**

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\verify_instance_blender.py`
Expected: `OK: DEMBulkInstanceBlender verified (2000 instances)`

- [ ] **Step 4: Commit**

```bash
git add BlenderConvert/DEMBulkInstanceBlender.py
git commit -m "feat: add DEMBulkInstanceBlender.py for the pure-instancing viz path

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RKov96Ynx5hxHrG2GeSXWY"
```

---

### Task 5: Full-scale end-to-end verification against `run_0001`

**Files:** none created or modified — this task runs the pipeline built in Tasks 1-4 at real scale and confirms it renders. Not a code task; no commit.

**Interfaces:** none new — exercises Tasks 1-4's public interfaces at `n_points=1_000_000` instead of Task 3/4's 2,000-point smoke-test scale.

- [ ] **Step 1: Run the real preprocessing pass**

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python viz\viz_preprocess_lite.py -- `
  --grains-dir DEMCSVs\torque_align_obj\run_0001_grains_output `
  --bodies-dir DEMCSVs\torque_align_obj\run_0001_bodies_output `
  --output-dir DEMCSVs\torque_align_obj\run_0001_viz_instance `
  --shape-obj "BlenderConvert\Shapes\gbo.ast-apophis.jpl.radar.shape_model_v1.0\gbo.ast-apophis.jpl.radar.shape_model_v1.0\data\apophis_v233s7.obj" `
  --n-points 1000000
```

Expected: prints `reference: cluster_radius=10.8440 BU grain_radius=0.9528 BU (n=500, run=run_0001)` (matching the superseded spec's hand-derived values) and `wrote 1,000,000 points -> ...points.npz`.

- [ ] **Step 2: Render frame 1 and the last available frame headlessly**

```python
# scratchpad/render_instance_check.py
import bpy, sys
ROOT = r"C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code"
with bpy.data.libraries.load(ROOT + r"\BlenderConvert\P0_Apophis_1M.blend", link=False) as (src, dst):
    if "Procedural rock" in src.materials:
        dst.materials = ["Procedural rock"]
sys.path.insert(0, ROOT + r"\BlenderConvert")
import DEMBulkInstanceBlender as instmod
instmod.VIZ_MANIFEST = ROOT + r"\DEMCSVs\torque_align_obj\run_0001_viz_instance\manifest.json"
instmod.main()

scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = 960, 540
scene.cycles.samples = 32
for frame in (scene.frame_start, scene.frame_end):
    scene.frame_set(frame)
    scene.render.filepath = ROOT + rf"\docs\p0_renders\instance_pipeline_f{frame:04d}.png"
    bpy.ops.render.render(write_still=True)
    print(f"rendered frame {frame} -> {scene.render.filepath}")
```

Run: `& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --python scratchpad\render_instance_check.py`

- [ ] **Step 3: Manual review**

Open `docs/p0_renders/instance_pipeline_f0001.png` and the last-frame render. Confirm: no clone-tiling artifact, plausible scale relative to Earth, the "Procedural rock" material renders as expected, no z-fighting at the shape boundary — matching the superseded spec's original verification checklist.

- [ ] **Step 4: Report to the user**

Do not commit the generated `DEMCSVs/torque_align_obj/run_0001_viz_instance/` output or the render PNGs without being asked — per the standing "never commit until the user has tested and explicitly asks" rule, hand the renders to the user for review first.

---

## Self-Review Notes

- **Spec coverage:** every component in the design spec (shared cinematic module, `viz_mode: "instance"` manifest with `static`/`points_path`, `viz_preprocess_lite.py`'s run-driven reference scale, `DEMBulkInstanceBlender.py`'s use of `P0_InstancingSpike.py` helpers, no-op per-frame hook, out-of-scope items) has a task. The spec's `_viz/points/NNNNN.npz` future convention for `static: false` is documented in `DEMBulkInstanceBlender.py`'s handler docstring but not implemented, matching the spec's explicit deferral.
- **Type consistency:** `frame_count` (not `grain_files`) is used consistently across `DEMCinematicSetup.keyframe_bodies_and_earth`/`setup_camera` and both callers. `core_fn(i) -> Vector` matches in both `DEMBulkVizBlender.py` (CSV-driven) and `DEMBulkInstanceBlender.py` (constant origin).
- **Deviation from the spec, called out explicitly:** the spec's Component 3 implied `viz_preprocess_lite.py` would run in the plain venv like `viz_preprocess.py`. It cannot — the shape-sampling BVH inside-test needs `mathutils.bvhtree`, which only exists inside Blender's Python. This plan runs it headless via `blender --background --python`, the same pattern `P0_InstancingSpike.py` already established as this repo's precedent for `bpy`-dependent scripts that aren't pasted into the Scripting tab. The CLI flag shape itself is unchanged.
- **Material sourcing resolved, not fabricated:** the spec said to reuse the "Procedural rock" material "already validated live" — since several similarly-named rock materials exist as separate asset `.blend` files in this repo and none is confirmed as the exact source, `DEMBulkInstanceBlender.py` looks the material up by name and fails loudly if absent, rather than guessing which asset file to append from. This is called out as a manual one-time prerequisite in Task 4/5's verification steps.
