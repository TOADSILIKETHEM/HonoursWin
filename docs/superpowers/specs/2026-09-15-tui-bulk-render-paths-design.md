# Sim + render TUI — composite and point-cloud render paths (design)

Date: 2026-09-15
Status: approved in brainstorming, awaiting spec review
Builds on: `2026-09-14-sim-render-pipeline-tui-design.md` (v1: sim → convert →
per-sphere headless render)

## Goal

Let one `sobol/tui_sim_render.py` launch render the same simulated run through
any combination of four visualisation paths, instead of per-sphere only:

| Path id | What it shows | Preprocess | Blender script |
|---|---|---|---|
| `per_sphere` | one UV sphere per grain (v1 behaviour) | none | `DEMGrainsBlenderEarthCam.py` |
| `composite` | D3 — deforming envelope mesh(es) + GN ejecta | `viz/viz_preprocess.py` (Windows `.venv`) | `DEMBulkVizBlender.py` |
| `instance_grains` | the real simulated grains, GN-instanced, moving per frame, per-grain radius | **new** `viz/viz_preprocess_grains_instance.py` (Windows `.venv`) | `DEMBulkInstanceBlender.py` (`static: false`) |
| `instance_static` | dense shape-model placeholder cloud, fixed all clip | `viz/viz_preprocess_lite.py` (Blender bundled Python) | `DEMBulkInstanceBlender.py` (`static: true`) |

One sim and one convert feed every ticked path.

## Non-goals

- Upsampled real motion (a dense cloud advected by real grain motion — the
  `--input-mode` extension of `viz_preprocess_lite.py`).
- Breakup-aware camera for the instance paths (see Known limits).
- "Render an existing run" (skip sim) mode, mid-run cancel, streamed Blender
  log, timeouts — unchanged from v1.
- Refactoring the bulk Blender scripts into importable `main(config)`
  functions (rejected approach C: they carry the user's uncommitted WIP).
- Removing the per-sphere full-timeline keyframing cost when `max_frames` is
  set.

## Approach

Approach A from brainstorming: a single headless entry point.
`BlenderConvert/DEMHeadlessRender.py` gains `--viz-path`; each path text-patches
its own Blender script's config constants and `exec`s it (the v1 technique),
then the existing shared tail (World HDRI, GPU, samples, resolution, PNG
sequence, optional MP4) runs unchanged. The TUI loops over per-path specs.

Rejected: B (one headless wrapper per path — three entry points plus a helper
refactor for no user-visible gain); C (see Non-goals).

---

## Section 1 — TUI form and stage chain (`sobol/tui_sim_render.py`)

### Form

Paths and Sim sections unchanged. Render section:

- Shared fields, unchanged, applying to every ticked path: `camera_mode`,
  `resolution`, `samples`, `fps`, `max_frames`, `encode_video`, `video_fps`.
- New **Render paths** checkbox group: `per_sphere` (ticked by default),
  `composite`, `instance_grains`, `instance_static`. At least one must be
  ticked, else validation error on click.
- `envelope_method`: `Select`, `allow_blank=False`, options `hull` (default)
  / `sdf`. Used only when `composite` is ticked.
- `placeholder_obj`: `Input`, default the Windows path
  `C:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/BlenderConvert/Shapes/gbo.ast-apophis.jpl.radar.shape_model_v1.0/gbo.ast-apophis.jpl.radar.shape_model_v1.0/data/apophis_v233s7.obj`
  (derived from `_REPO_WIN_CODE`, not hardcoded twice). Used only when
  `instance_static` is ticked.
- `n_points`: `Input`, default `1000000`, int > 0. Used only when
  `instance_static` is ticked.
- Path-specific fields are validated only when their path is ticked, at
  click time, before the sim starts.
- The existing `np_apophis > 2000` warning is emitted only when `per_sphere`
  is ticked.

### Stage chain

```
sim → convert → for path in ticked paths (fixed order
                per_sphere, composite, instance_grains, instance_static):
                    [preprocess_<path>] → render_<path>
```

- Sim failure or convert failure (including the v1 zero-npz check) stops the
  whole pipeline, as in v1.
- A path failure (preprocess or render) is recorded against that path and the
  **remaining paths still run** — paths are independent.
- Overall result: `stage="done"`, `ok=True` only when every ticked path
  succeeded; otherwise `stage="partial"`, `ok=False`. Message is one line per
  path, e.g.
  `per_sphere: ok, 3 frame(s) in 212s` /
  `composite: failed at preprocess: <tail>`.
- Status bar: `preprocess [composite 2/3]` with elapsed time, then
  `render [composite 2/3]` with the live `frame_*.png` count against the
  expected frame count (v1 progress mechanism, per path).

### Output layout

Windows `Code/DEMCSVs/<batch name>/`:

```
run_0001_grains_output/              run_0001_bodies_output/        (v1, unchanged)
run_0001_viz/                        composite preprocess
run_0001_viz_instance/               instance_grains preprocess
run_0001_viz_instance_static/        instance_static preprocess
run_0001_render_per_sphere/          run_0001_render_composite/
run_0001_render_instance_grains/     run_0001_render_instance_static/
```

Each render folder holds `frame_####.png` and, if `encode_video`,
`animation.mp4`.

**Breaking change:** the v1 per-sphere folder `run_0001_render/` becomes
`run_0001_render_per_sphere/`. Nothing downstream reads the v1 name.

`max_frames` is also passed as `--max-frames` to the composite and
instance_grains preprocess. It is not passed to instance_static (one static
cloud regardless of frame count).

### Code shape

- New `RenderPath` spec (dataclass): `name`, optional
  `preprocess(ctx) -> Path` (returns the `manifest.json` path),
  `build_render_command(ctx, manifest) -> List[str]`, `render_dir_suffix`.
- A module-level registry `RENDER_PATHS` in the fixed order above.
- `run_pipeline` replaces its single render block with a loop over the ticked
  specs and aggregates per-path results. The v1 `PipelineResult` gains
  `paths: List[PathResult]` where `PathResult(name, ok, stage, message,
  n_frames, elapsed_s)`; `stage` is `"preprocess"`, `"render"` or `"done"`.
- `RenderFormValues` gains `paths: Tuple[str, ...]`, `envelope_method: str`,
  `placeholder_obj: str`, `n_points: int`.
- Preprocess subprocess calls reuse v1's `to_windows_path` for every path
  argument and the same "last 40 lines of stdout+stderr" error tail as
  `RenderError` (new `PreprocessError`).
- New constant `WIN_VENV_PYTHON = _REPO_WIN_CODE / ".venv/Scripts/python.exe"`
  (a `/mnt/c` path, executed directly like `BLENDER_EXE`).

Preprocess commands (all arguments Windows paths):

| Path | Command |
|---|---|
| composite | `WIN_VENV_PYTHON <Code>/viz/viz_preprocess.py --grains-dir G --bodies-dir B --output-dir <run>_viz --envelope-method {hull,sdf} [--max-frames N]` |
| instance_grains | `WIN_VENV_PYTHON <Code>/viz/viz_preprocess_grains_instance.py --grains-dir G --bodies-dir B --output-dir <run>_viz_instance [--max-frames N]` |
| instance_static | `BLENDER_EXE --background --python <Code>/viz/viz_preprocess_lite.py -- --grains-dir G --bodies-dir B --output-dir <run>_viz_instance_static --shape-obj OBJ --n-points N` |

Preprocess working directory: `_REPO_WIN_CODE` (the scripts insert their own
repo root on `sys.path`; running from the repo root matches the documented
Windows commands).

---

## Section 2 — headless render contract (`BlenderConvert/DEMHeadlessRender.py`)

### CLI

Existing flags unchanged. New:

```
--viz-path {per_sphere,composite,instance}   default per_sphere
--manifest <path to manifest.json>           required for composite / instance
```

`--grains-dir` / `--bodies-dir` become required **only** for `per_sphere`
(validated after parsing, not by argparse `required=`).

Rejected at argument time, exit 1 before any scene work:
- `composite` / `instance` without `--manifest`, or with a non-existent file;
- `per_sphere` without `--grains-dir` / `--bodies-dir`;
- manifest `viz_mode` not matching the path (`composite` ↔ `"composite"`,
  `instance` ↔ `"instance"`).

Both TUI instance paths use `--viz-path instance`; the manifest's `static`
field distinguishes them.

### Patch table

Each pattern must match exactly once, else `RuntimeError` (v1 rule).

| `--viz-path` | Script exec'd | Constants patched |
|---|---|---|
| `per_sphere` | `DEMGrainsBlenderEarthCam.py` | `GRAINS_DIR`, `BODIES_CSV_DIR`, `CAMERA_MODE` (only for `grain_only`) — v1, unchanged |
| `composite` | `DEMBulkVizBlender.py` | `VIZ_MANIFEST = (...)` → manifest path; `CAMERA_MODE = None` → `'grain_only'` (only for `grain_only`) |
| `instance` | `DEMBulkInstanceBlender.py` | `VIZ_MANIFEST = (...)`; `CAMERA_MODE` (as above); `SLOWMO_FACTOR = <int>` → `1`; `RENDER_RESOLUTION = (...)` → `(W, H)` |

All other constants are left as on disk (e.g. the user's
`EJECTA_ICO_SUBDIV`). `SLOWMO_FACTOR = 1` keeps one timeline frame = one sim
frame so `--max-frames` and the TUI frame count stay correct. `TARGET_FPS` is
not patched — the shared tail sets `scene.render.fps` afterwards.

### Instance pre-exec step

Before exec'ing `DEMBulkInstanceBlender.py`, append material
`"Procedural rock"` from `BlenderConvert/Blenders/11.blend` (same file and
name as `DEMGrainsBlenderEarthCam.py`'s `ROCK_MATERIAL_BLEND_PATH` /
`ROCK_MATERIAL_NAME`), unless already present. If the file or material is
missing → `RuntimeError` → exit 1. No fallback: the instance script refuses
to run without it.

### Shared tail

Unchanged order from v1: `setup_deep_dark_space_world()`, max-frames clamp,
`setup_cycles_gpu()`, samples, resolution, fps, PNG output, `render(animation=True)`,
optional `encode_video()`.

Added for `composite` and `instance` only:
`scene.render.use_lock_interface = True` — their `frame_change_pre` handlers
rewrite mesh data between frames during the animation render.

Unchanged: `out_dir` resolved before exec (cwd changes on `.blend` load);
`__main__` try/except → traceback → `sys.exit(1)`. The bulk scripts'
`register_self_as_auto_run_module()` is a no-op in background mode.

### Risk to verify first

That the bulk scripts' frame handlers fire on each frame of
`bpy.ops.render.render(animation=True)` under `--background`, so rendered
frame N shows envelope / points frame N, not frame 0. This is the first task
of the implementation plan; everything else depends on it.

---

## Section 3 — real-grain instance writer and radius support

### New `viz/viz_preprocess_grains_instance.py`

Dependencies: numpy, `viz.path_utils` only. Runs in the Windows `.venv`.

CLI:
```
--grains-dir (required)  --bodies-dir (required)  --output-dir (required)
[--max-frames N]  [--sim-name S]  [--run-name R]
```

Behaviour:
1. Sort `*.npz` in `--grains-dir` by filename (same order as the per-sphere
   and composite paths); truncate to `--max-frames`. Zero files → exit 1.
2. For each frame `i`: load, order all arrays by `grain_id`, write
   `<output-dir>/points/{i:05d}.npz` with `np.savez_compressed`:
   - `pos` float32 (N, 3) from `x_vis`, `y_vis`, `z_vis`
   - `radius` float32 (N,) from `Reff_vis`
   Ordering by `grain_id` keeps instance *i* the same grain every frame so the
   GN per-instance random rotation is stable (no flicker).
3. If any frame's grain count differs from frame 0 → exit 1 with
   `frame <id> has <n> grains, frame 00000 has <n0>`.
4. Write `<output-dir>/manifest.json`:

```json
{
  "schema_version": 1,
  "viz_mode": "instance",
  "static": false,
  "source": "grains",
  "sim_name": "...",
  "run_name": "...",
  "n_frames": 3,
  "frame_ids": ["00000", "00001", "00002"],
  "points_dir": "points",
  "n_points": 501,
  "grain_radius_vis": 2.4,
  "bodies_csv_dir": "../run_0001_bodies_output",
  "bodies_start_index": 0
}
```

- `grain_radius_vis` = median `Reff_vis` of frame 0 (fallback for readers
  without per-point radius support).
- `bodies_csv_dir` via `viz.path_utils.manifest_relpath`.
- `sim_name` / `run_name` default from the grains-dir path, same derivation
  as `viz_preprocess.py`.
- No `synthetic`, `motion_model` or `angles_rad` keys, so
  `DEMBulkInstanceBlender.py` uses its held-frame reload branch (exact with
  `SLOWMO_FACTOR = 1`).

### Change to `BlenderConvert/DEMBulkInstanceBlender.py`

- `_build_point_cloud(pos, grain_radius_vis, subdiv, radii=None)`: fill the
  GN `radius` attribute from `radii` (float32, length N) when given, else
  `np.full(N, grain_radius_vis)` as today.
- `main()`: after loading `first_points_path`, pass
  `radii = npz['radius'] if 'radius' in npz else None`; if present, check
  `len(radii) == len(pos)` else `ValueError`.
- `_instance_frame_change_handler`: unchanged (updates `co` only; grain radii
  do not change over a run).
- Static and synthetic manifests: identical behaviour (no `radius` key).
- Must not touch the user's uncommitted `VIZ_MANIFEST` line.

### instance_static

No code change: existing `viz_preprocess_lite.py` invoked as in Section 1.

### Known limits

- Instance camera tracks the origin (grain CoM). Matches per-sphere for an
  intact body; for a real breakup the CoM can sit between fragments, whereas
  composite tracks the densest 80% core. Documented, not fixed.
- instance_static is a placeholder: it does not show simulated grain motion.

---

## Section 4 — error handling and testing

### Errors

| Stage | Failure condition | Reported |
|---|---|---|
| click-time validation | no path ticked; bad `n_points`; `placeholder_obj` missing (instance_static); `WIN_VENV_PYTHON` missing (composite or instance_grains) | status bar error, sim not started |
| preprocess | non-zero exit | `<path>: failed at preprocess: <last 40 lines>` |
| preprocess | exit 0 but no `manifest.json` | `<path>: preprocess wrote no manifest at <dir>` |
| instance_grains writer | grain count mismatch across frames | exit 1 (→ preprocess failure) |
| render | non-zero exit | `<path>: failed at render: <last 40 lines>` |
| render | exit 0 but 0 `frame_*.png` | `<path>: render wrote no frames to <dir>` |
| render (instance) | `Procedural rock` / `11.blend` missing | Blender exit 1 with that message |

Failed paths keep their partial folders; nothing is auto-deleted. Each
`PathResult` records `elapsed_s`.

### Tests (all in WSL `sobol/tests/`, Windows scripts imported via `/mnt/c`)

1. `test_tui_sim_render.py` (extend; mocked, no PHANTOM/Blender):
   - each `RenderPath` builds the documented preprocess and render commands
     with Windows paths;
   - ticked paths run in fixed order; zero ticked → validation error;
   - partial failure: composite preprocess fails, per_sphere and
     instance_grains still render, result `stage="partial"`, `ok=False`;
   - preprocess exit 0 without manifest → path failure;
   - click-time validation of `WIN_VENV_PYTHON` and `placeholder_obj`,
     only when the relevant path is ticked;
   - per-sphere render dir is `run_0001_render_per_sphere`;
   - `max_frames` forwarded to composite and instance_grains preprocess only;
   - `>2000` warning only when per_sphere ticked;
   - existing v1 tests updated for the new result shape, not deleted.
2. `test_dem_headless_paths.py` (new):
   - `--viz-path` / `--manifest` / `--grains-dir` combination validation;
   - `viz_mode` mismatch rejected;
   - each path's patch table applied to the **real on-disk script text**
     matches every pattern exactly once (guards future edits to the bulk
     scripts).
3. `test_viz_preprocess_grains_instance.py` (new, numpy only):
   - synthetic grain npz in `tmp_path` with shuffled `grain_id`;
   - output sorted by `grain_id`; `pos` (N,3) float32 and `radius` (N,)
     float32; manifest keys and values; `--max-frames`; grain-count mismatch
     → non-zero exit; empty grains dir → non-zero exit.
4. Blender integration (skip when `blender.exe` not mounted):
   - 3-frame composite render from a tiny fixture run: PNG 1 and PNG 3 differ
     (handler fires during animation render) — the Section 2 risk check;
   - 2-frame instance_grains render: the scene's point-cloud `radius`
     attribute equals the fixture radii.

### Manual end-to-end (user)

One TUI launch, all four paths ticked: `np_apophis 500`, `tmax 1`,
`dtmax 0.5`, `ephemeris_cache_dir /home/mboyle/Honours/sobol`,
`max_frames 3`, `640x360`, `samples 16`. Expect four
`run_0001_render_<path>/` folders with 3 PNGs each and `stage="done"`.

### Docs

- WSL `sobol/CLAUDE.md`: TUI section — render paths, form fields, output
  layout (incl. the per-sphere folder rename), partial-failure behaviour.
- Windows `CLAUDE.md`: item 12 per-grain radius support; item 13
  `--viz-path` / `--manifest`; the new writer in the viz path selection table
  and Key commands; TUI subsection output layout.

## Repos and constraints

- WSL `sobol/` (branch `feature/sim-render-pipeline-tui` or a follow-on
  branch): `tui_sim_render.py`, tests.
- Windows `Code/`: `DEMHeadlessRender.py`, `DEMBulkInstanceBlender.py`,
  new `viz/viz_preprocess_grains_instance.py`.
- The user's uncommitted edits in `DEMBulkVizBlender.py` and
  `DEMBulkInstanceBlender.py` must be preserved; no staging, stashing or
  reverting of them. No commits without explicit instruction.
- `docs/` is not git-tracked in `Code/` (deny-all `.gitignore`); this spec
  stays untracked.
