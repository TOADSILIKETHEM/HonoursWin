# Instance-pipeline cinematic integration — design

**Supersedes:** `2026-09-08-11-blend-million-particle-apophis-design.md`. That
spec's `11_MillionApophis.blend` one-off task is replaced by this general
pipeline; `11.blend`'s run (`torque_align_obj/run_0001`) becomes this
pipeline's first test case instead of a standalone script.

## Goal

Give the pure-instancing (Option A) point-cloud path the same cinematic
integration the composite path already has — Earth/Moon/Sun, tracking camera,
lighting, timeline — via a shared module, without touching the proven
per-sphere importer. Build the general pipeline now, driven by a static
placeholder point cloud, so swapping in real per-frame million-grain
simulation data later needs no redesign.

## Context

- Three viz back ends exist: per-sphere (`DEMGrainsBlenderEarthCam.py`,
  proven, left alone), composite (`viz_preprocess.py` →
  `DEMBulkVizBlender.py`, already has full cinematic wiring), and pure
  instancing (`CLAUDE.md`'s `viz_preprocess_lite.py` /
  `DEMBulkInstanceBlender.py`, not built — only the `P0_InstancingSpike.py`
  measurement harness exists, with no Earth/camera/timeline of its own).
- `DEMBulkVizBlender.py`'s cinematic logic (`_detect_solar_system`,
  `_ensure_earth_placeholder`, `_keyframe_bodies_and_earth`,
  `_setup_simple_camera`, `_frame_handler_suspended`,
  `_viz_frame_change_handler` registration) is currently private to that
  script, duplicated from the per-sphere importer. It is the extraction
  source for the shared module.
- No real per-frame million-grain simulation data exists yet. Today's point
  cloud is a static JPL-radar-shape-cropped sample (the logic already proven
  in the scratchpad `p0_blend_apophis.py`), standing in for future real data.
  The architecture must treat "static placeholder" and "real time-varying
  data" as two implementations of the same manifest contract, so only
  `viz_preprocess_lite.py` changes when real data arrives.
- Decisions locked in (via clarifying questions): extract a shared cinematic
  module first; this replaces the `11_MillionApophis` one-off spec;
  `DEMGrainsBlenderEarthCam.py` stays untouched.

## Approaches considered

**Approach 2 (rejected): inline, no preprocessing step.** Have
`DEMBulkInstanceBlender.py` read shape OBJs / grain CSVs directly and build
the point cloud itself, skipping a `viz_preprocess_lite.py` stage. Simpler
short-term, but breaks the manifest-driven convention the composite path
already uses, and hardcodes today's placeholder-generation logic into the
Blender script — exactly the coupling this design exists to avoid.

**Approach 1 (chosen): manifest-driven, matching the existing composite
pattern.** A `viz_preprocess_lite.py` preprocessing stage writes a
`viz_mode: "instance"` manifest + `_viz/points.npz`, consumed by
`DEMBulkInstanceBlender.py` exactly as `DEMBulkVizBlender.py` consumes
`viz_mode: "composite"` manifests. Keeps both bulk paths structurally
parallel and keeps the Blender-side script ignorant of how points were
generated (placeholder sampling today, real CSV ingestion later).

## Architecture

```
run's grains/bodies CSVs  ─┐
  (reference scale only)   │
                            ├─→ viz_preprocess_lite.py ─→ _viz/ (manifest.json + points.npz)
JPL shape OBJ ──────────────┘                                         │
                                                                       ▼
                                              DEMBulkInstanceBlender.py
                                                       │
                                    imports BlenderConvert/DEMCinematicSetup.py
                                    imports P0_InstancingSpike.py (_make_icosphere,
                                                                    build_geometry_nodes)
                                                       │
                                                       ▼
                                    full cinematic .blend: Earth/Moon/Sun,
                                    tracking camera, lighting, timeline,
                                    GN-instanced point-cloud Apophis
```

## Components

### 1. `BlenderConvert/DEMCinematicSetup.py` (new)

Extracted from `DEMBulkVizBlender.py`'s existing functions:
`_detect_solar_system`, `_ensure_earth_placeholder`,
`_keyframe_bodies_and_earth`, `_setup_simple_camera`,
`_frame_handler_suspended`. Generalized signatures take primitives (bodies
dir, frame ids, a bounding radius for camera framing) rather than anything
specific to envelopes or ejecta, so a caller supplies only what it has.

`DEMBulkVizBlender.py` is refactored to call this module instead of its
private copies — a mechanical extraction, not a behavior change; its own
`_update_envelope_obj`/`_update_ejecta_obj`/GN-ejecta code stays in place.
`DEMGrainsBlenderEarthCam.py` is not touched — it keeps its own independent
cinematic logic per the explicit decision to leave it alone.

### 2. Manifest extension: `viz_mode: "instance"`

Mirrors the existing `"composite"` schema (`schema_version`, `viz_mode`,
frame list, relative `bodies_dir`). New fields:

- `static`: `true` today.
- `points_path`: relative path, meaning depends on `static`.
  - `static: true` — a single file, `_viz/points.npz` (`pos` Nx3 float32 vis
    units only; all points share one radius). Read once, reused for every
    frame — avoids 217× duplication of a multi-hundred-MB array.
  - `static: false` (future) — a directory, `_viz/points/`, holding one
    `NNNNN.npz` per frame (same `NNNNN` indexing as `envelopes/` and
    `ejecta/`). `DEMBulkInstanceBlender.py`'s per-frame hook loads
    `points_path/{frame:05d}.npz` instead of the cached static array.
- `grain_radius_vis`: precomputed volume-conserving radius for the shared
  instance mesh — the single source of truth for point size; per-point npz
  radius arrays are not used while every grain in a run shares one size.

### 3. `viz/viz_preprocess_lite.py` (new)

Placeholder-source mode only, for now:

- Reuses the shape-sampling logic proven in the scratchpad
  `p0_blend_apophis.py` (BVH-based rejection sampling of N points inside a
  JPL shape OBJ), moved into `viz/shape_sampling.py` as a real, importable
  function instead of scratch code.
- CLI shape matches `viz_preprocess.py`'s existing pattern:
  `--grains-dir`, `--bodies-dir`, `--output-dir`, plus `--shape-obj` and
  `--n-points`.
- Reference cluster radius and per-grain radius are **computed from
  whichever run's grains/bodies CSVs are passed in** (frame-1 cluster rmax,
  and per-grain radius from the grains CSV's `Reff_vis`), generalizing the
  previous one-off spec's hardcoded `10.844 BU` / `0.9528 BU` (which were
  specific to `torque_align_obj/run_0001`) into a real calculation any run
  can supply.
- `grain_radius_for(n_points)` reuses `P0_InstancingSpike.py`'s
  volume-conserving formula, re-anchored on the run's real reference values
  instead of the benchmark's arbitrary `REF_N=500` / `REF_GRAIN_RADIUS_VIS=2.4`.
- A real "ingest actual per-frame million-grain CSVs" mode is explicitly
  **out of scope** — documented as an unimplemented `--input-mode` flag
  (matching `viz_preprocess.py`'s existing unimplemented `--input-mode
  dump`), deferred until such simulations exist. Nothing else in this design
  needs to change shape when that mode is added.

### 4. `BlenderConvert/DEMBulkInstanceBlender.py` (new)

- Reads the `viz_mode: "instance"` manifest.
- Calls `DEMCinematicSetup` for Earth/Moon/Sun, camera, lighting, timeline.
- Builds the point cloud mesh + shared icosphere instance mesh + GN
  "Instance on Points" modifier via `P0_InstancingSpike.py`'s
  `_make_icosphere()` and `build_geometry_nodes()` (imported, not
  duplicated) — not `build_scene()`, which creates an unwanted scratch
  scene/camera/sun.
- Applies the `Procedural rock` material plus the per-instance random
  offset already validated live on `P0_Apophis_1M.blend`, to avoid a
  clone-tiling look across shared-mesh instances.
- Registers a per-frame update hook mirroring
  `_update_envelope_obj`/`_update_ejecta_obj`'s structure. Today, with
  `static: true`, it is a no-op after initial build. When `static: false`
  exists in a future manifest, this hook becomes the only place that needs
  new code to load a real per-frame point array.

## Error handling

- `viz_preprocess_lite.py` fails loudly (not silently falls back) if the
  reference run's grains CSV is missing required columns (`Reff_vis`) or the
  shape OBJ fails to load/is non-manifold for the BVH inside-test — matching
  `viz_preprocess.py`'s existing per-fragment `try/except` pattern is not
  applicable here since there's only one shape, not per-fragment envelopes.
- `DEMBulkInstanceBlender.py` validates `manifest["viz_mode"] == "instance"`
  before touching anything else (mirroring how `DEMBulkVizBlender.py` should
  reject a `"composite"` manifest, per `CLAUDE.md`'s note that scripts must
  branch on `viz_mode`, not folder name).

## Testing

- `viz_preprocess_lite.py` against `torque_align_obj/run_0001`: manifest
  fields correct; point count = N; computed grain radius matches the old
  spec's hand-derived `0.9528 * (500/1e6)**(1/3)` BU as a regression check.
- `blender --background --python DEMBulkInstanceBlender.py` against that
  manifest: Earth/camera present; GN instance count = N via depsgraph
  (`sum(1 for i in dg.object_instances if i.is_instance)`, the same
  technique used in `p0_blend_apophis.py`); low-res render at frame 1 and
  frame 217.
- Regression: `DEMBulkVizBlender.py` still runs correctly against an
  existing composite manifest after the `DEMCinematicSetup` extraction.

## Out of scope

- Real per-frame million-grain CSV ingestion mode of `viz_preprocess_lite.py`
  — documented as a deferred flag, not implemented, since the simulation
  data doesn't exist yet.
- Retrofitting `DEMGrainsBlenderEarthCam.py` to use the shared module —
  explicitly declined; it stays independent.
- Any breakup, deformation, or spin of the point cloud — it remains a
  static rigid body, as in the superseded one-off spec.
- Editing `P0_InstancingSpike.py` itself — reused by import only.

## Disposition of the superseded spec

`2026-09-08-11-blend-million-particle-apophis-design.md` is left in place
with this file superseding it (noted at the top of this document); it is not
deleted, since it still records real, verified facts about `11.blend` and
`torque_align_obj/run_0001` (frame-1 cluster radius, grain diameter) that
this design's testing section reuses as regression values.
