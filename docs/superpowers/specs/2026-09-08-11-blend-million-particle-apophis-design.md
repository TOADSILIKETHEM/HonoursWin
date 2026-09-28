# 11.blend million-particle Apophis swap — design

## Goal

Produce a new Blender scene that is `BlenderConvert/Blenders/11.blend`'s flyby
(Earth/Moon/Sun, `DEM_TrackCam`, 217-frame timeline sourced from
`DEMCSVs/torque_align_obj/run_0001`) with its 504-object per-grain Apophis
representation replaced by a single Geometry-Nodes-instanced, million-point
Apophis shaped from the real JPL radar shape model, treated as a **static,
non-deforming rigid body**.

## Context

- `11.blend` was built by the embedded `DEMGrainsBlenderEarthCam.py` +
  `MaterialandSubsivision.py` scripts (both still saved as text blocks inside
  the file itself) against
  `DEMCSVs/torque_align_obj/run_0001_{grains,bodies}_output/` — the "OBJ
  aligned_near_h" run (~11.2° obliquity, P=1.52 hr, kc=1e7, np=500, 217
  frames; Table 6.1 / Figure 7.1 material per the embedded script's comment).
- Verified directly against the file: the 500-grain cluster's centroid sits
  at the origin at every frame (rmax 10.844 BU at frame 1, growing to 18.470
  BU by frame 217 from mild tidal stretching) — Earth and the Sun move around
  Apophis, not the other way around, matching the point-mass pipeline's
  Apophis-centered convention. A rigid, non-deforming swap therefore needs
  **no trajectory or rotation animation at all** — it can simply sit still
  where the old cluster already sat.
- Individual grain mesh diameter in `11.blend` is 1.9056 BU → radius 0.9528
  BU. This is the real per-grain visual scale for np=500 in this run, and is
  the correct anchor for volume-conserving grain-radius scaling at N=1e6 —
  *not* `P0_InstancingSpike.py`'s own `REF_GRAIN_RADIUS_VIS = 2.4`, which was
  chosen arbitrarily for its synthetic benchmark pile.
- The million-particle Apophis (`BlenderConvert/P0_Apophis_1M.blend`) is
  unrelated code: `P0_InstancingSpike.py`'s GN "Instance on Points" benchmark
  scene (`build_scene()`), fed real shape-derived point positions by
  `p0_blend_apophis.py` (rejection-samples 1,000,000 points inside
  `apophis_v233s7.obj` using a BVH inside/outside test). That file has no
  Earth/camera/animation of its own — one static frame, scaled to an
  arbitrary 15.0 BU benchmark body radius, built as a Cycles instancing
  feasibility spike (Objective 3 Option A), not for this deliverable.
- Decisions locked in for this design: static rigid body (no internal
  deformation across the 217 frames); delete the 504-grain cluster rather
  than keep it hidden alongside the new one; source scale/reference grain
  radius from `torque_align_obj/run_0001`.

## Approach

One-off headless script run via `blender --background --python <script>`
(never opens a GUI, never touches the original `11.blend`):

1. Open a **copy** of `11.blend`.
2. Delete all `DEM_Grain_*` objects and the (now empty) `DEM_Grains`
   collection.
3. Rejection-sample 1,000,000 points inside `apophis_v233s7.obj` (same BVH
   inside-test as `p0_blend_apophis.py`), scaled so the shape's far-most
   vertex sits at **10.844 BU** (this run's real frame-1 cluster radius)
   instead of P0's arbitrary 15.0, centred at the origin.
4. Build the point cloud + shared icosphere instance mesh + GN "Instance on
   Points" modifier by importing `P0_InstancingSpike.py` and calling its
   `_make_icosphere()` / `build_geometry_nodes()` helpers directly — **not**
   `build_scene()`, which creates its own scratch scene plus a camera and sun
   we don't want. The new objects link into `11.blend`'s existing `Scene`.
5. Per-point radius: `0.9528 * (500 / 1_000_000) ** (1/3)` BU — the same
   volume-conserving formula as `grain_radius_for()`, anchored on this run's
   real reference radius instead of the benchmark's default.
6. Assign the `Procedural rock` material — already present as a material in
   `11.blend` — to the new instance mesh. Add the
   `Object Info (Random) → Vector Math (Scale) → Mapping.Location` per-grain
   offset already validated live on `P0_Apophis_1M.blend`, to avoid the
   clone-tiling look across a million shared-mesh instances.
7. Leave Earth/Moon/Sun/`DEM_TrackCam`/lighting/timeline exactly as they are
   in `11.blend`.
8. Save as a new file: `BlenderConvert/Blenders/11_MillionApophis.blend`
   (name open to change).
9. Render two verification frames (1 and 217) at a modest resolution/sample
   count.

## Out of scope

- Any internal deformation, breakup, or spin of the 1,000,000-point cloud —
  explicitly deferred by the "static rigid body" decision.
- Wiring `DEMCSVs` time-series data into a million-point cloud frame-by-frame
  — that is the unbuilt Option A "pure instancing" pipeline referenced in
  `CLAUDE.md` (`viz_preprocess_lite.py` / `DEMBulkInstanceBlender.py`), not
  this task.
- Editing `P0_InstancingSpike.py` itself — it is reused by import only, to
  avoid any risk to the validated benchmark script.

## Testing / verification

- Headless render of frame 1 and frame 217 (low-cost resolution/samples) to
  confirm: no clone-tiling artifact, plausible scale relative to Earth, the
  `Procedural rock` material renders as expected, no z-fighting or visible
  seams at the shape boundary.
- User opens the resulting `.blend` in the GUI to confirm before any further
  work (e.g. full-resolution renders) proceeds.
