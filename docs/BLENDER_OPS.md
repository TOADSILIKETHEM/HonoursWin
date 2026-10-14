# Blender + viz operations (Code)

On-demand how-to moved from `CLAUDE.md` on 2026-09-25 (commands converted to WSL form). Hub: `../CLAUDE.md`. Data folders (`DEMCSVs/`, `BlenderConvert/Blenders|Shapes`, `.venv`) live in the OneDrive data folder `$D`, not this WSL repo.

## Key commands

**Shell setup (WSL, from `~/Honours/Code`).** Commands below use:
```bash
D=/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code          # OneDrive data folder
B="/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"         # Windows Blender
```
WSL `python3` has sarracen, pandas, numpy, scipy, matplotlib, Pillow. **Not** installed in WSL: `scikit-image` (only `--envelope-method sdf` needs it) and `astropy` (only `sbmt_mosaic.py`) — `pip install --user --break-system-packages scikit-image astropy` if needed. The Windows `.venv` (in `$D/.venv`) is only used by the TUI preprocess stage. `blender.exe` needs Windows-form paths: wrap every path in `"$(wslpath -w ...)"`.

Another machine: `$D` / `$B` = `data_dir` / `blender_exe` in `Code/local_paths.json` (`python3 sobol/setup_paths.py --check` prints them); Scripting-tab runs outside this checkout need `HONOURS_CODE_DIR` set before Blender starts. Quickstart: `../README.md`.

Convert point-mass PHANTOM dumps to CSV (legacy; the `solarsystem/` dumps are no longer on disk):
```bash
python3 CSVconvert/ToCSVFirst.py
```
Output goes to `$D/csv_output/`. Edit `INPUT_DIR` and `DUMP_PATTERN` in the script if dump location changes.

Convert DEM PHANTOM dumps to bodies CSV + grains npz — **primary (from WSL Honours project root):**
```bash
python3 sobol/Analysis/run_demtocsv_batch.py --min-dem-grains 450 \
  --base-output-dir "/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/torque_align_obj" \
  sobol_mass_runs/sobol_20260601_171137_torque_align_blender_vis_obj/run_0001 \
  sobol_mass_runs/sobol_20260601_171137_torque_align_blender_vis_obj/run_0002
```

Convert DEM — **fallback (edit `INPUT_DIR` etc. in the script):**
```bash
python3 CSVconvert/DEMDumpConvert.py
```
Output goes to `DEMCSVs/<sim_name>/<run>_bodies_output/` (CSV) and `_grains_output/` (`.npz`). Set `MIN_DEM_GRAINS` to just below `np_apophis` (~450 for np=500).

**Upgrade CSV-era grain folders** — a one-off script for grain folders that predate the npz migration and whose WSL dumps no longer exist, so `DEMDumpConvert.py` can't be re-run against them:
```bash
python3 CSVconvert/grains_csv_to_npz.py --all "$D/DEMCSVs"
```
Writes a same-stem `.npz` next to each grain CSV — the CSVs are kept, never modified or deleted. Parses with `pd.read_csv(..., float_precision='round_trip')`, which is exact against the values `DEMDumpConvert.py` itself would have written. A column an old CSV predates (e.g. `time_s`) is filled with NaN and noted per folder. If a folder ends up with fewer `.npz` than `.csv` (an interrupted run), the readers will silently load fewer frames than expected — rerun the script on that folder (it skips stems that already have an `.npz`, or pass `--overwrite` to redo them).

Legacy point-mass plots — loads per-dump bodies-CSV folders; `runs` dict holds `/path/to/...` placeholders:
```bash
python3 "Data analysis/FirstData.py"
```

### Bulk composite viz (preprocess → Blender)

**Prerequisites:** grain npz files from `DEMDumpConvert.py` (must include `m`, `x_rel_km`, `Reff_km`, `x_vis`, `Reff_vis`). Run from `~/Honours/Code` with WSL `python3` (verified 2026-09-25, hull).

**Step 1 — preprocess** (writes `run_XXXX_viz/` next to the grains/bodies folders):

```bash
python3 viz/viz_preprocess.py \
  --grains-dir "$D/DEMCSVs/<sim>/run_XXXX_grains_output" \
  --bodies-dir "$D/DEMCSVs/<sim>/run_XXXX_bodies_output" \
  --output-dir "$D/DEMCSVs/<sim>/run_XXXX_viz" \
  --envelope-method hull
```

**Regression example** (`_verify_lattice_fix`, np500, 4 frames):

```bash
R="$D/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg"
python3 viz/viz_preprocess.py --grains-dir "$R/run_0001_grains_output" \
  --bodies-dir "$R/run_0001_bodies_output" --output-dir "$R/run_0001_viz" --envelope-method hull
```

**Step 2 — Blender:** open `BlenderConvert/DEMBulkVizBlender.py` in the Scripting tab, set `VIZ_MANIFEST` to the absolute path of `run_XXXX_viz/manifest.json`, click **Run Script** (Cycles). Scrub the timeline — a frame handler updates envelope meshes and ejecta instances per frame.

**`viz_preprocess.py` CLI flags:**

| Flag | Default | Purpose |
|------|---------|---------|
| `--grains-dir` | *(required)* | `run_XXXX_grains_output/` |
| `--output-dir` | *(required)* | `run_XXXX_viz/` (created if missing) |
| `--bodies-dir` | inferred | `run_XXXX_bodies_output/` — stored in manifest for Earth/camera |
| `--envelope-method` | `hull` | `hull` = convex hull (fast, P0); `sdf` = sphere-union SDF (slower, smoother) |
| `--ejecta-max-instances` | `50000` | Cap GN ejecta instances; mass-weighted subsample if exceeded |
| `--fragment-min-mass-frac` | `0.05` | Minimum fragment mass fraction for separate envelope |
| `--grain-vis-scale` | `50` | Must match `GRAIN_VIS_SCALE` in `DEMDumpConvert.py` |
| `--max-frames` | all grain npz files | Limit frames (dev/testing) |
| `--sim-name`, `--run-name` | from paths | Override manifest metadata |
| `--input-mode dump` | — | **Not implemented** (gated on Objective 2; skip per-frame-file bottleneck at ~1M grains) |

**Preprocess output layout** (`run_XXXX_viz/`):

```
manifest.json              # frame list, paths, viz_mode: "composite"
envelopes/00000_f0.npz     # main-body envelope (verts, faces, fragment_id, …)
envelopes/00000_f1.npz     # secondary fragment (breakup only)
ejecta/00000.npz           # pos, radius, grain_id (vis units, instanced in GN)
metrics/00000.json         # rg_ratio, unbound_fraction, n_fragments, n_ejecta
```

Frame index `00000`… matches sorted order of grain npz filenames (same order as per-sphere importers).

**`DEMBulkVizBlender.py` configuration** (top of script):

| Variable | Typical value | Notes |
|----------|---------------|-------|
| `VIZ_MANIFEST` | absolute path to `manifest.json` | **Required** |
| `BODIES_CSV_DIR` | `None` | Resolved from manifest (`../run_XXXX_bodies_output`) |
| `IMPORT_SOLAR_SYSTEM` | `None` | Auto-detect from bodies CSV row count; `False` for `apophis_only` |
| `SETUP_CAMERA` | `True` | Grain-core + Earth tracking camera |
| `CAMERA_MODE` | `None` | `None` = auto; `'grain_only'` for apophis-only runs |
| `USE_FRAME_CHANGE_HANDLER` | `True` | Updates meshes on timeline scrub |

Uses `TheEarth1.blend` and the same Earth/camera defaults as `DEMGrainsBlenderEarthCam.py`.

**Viz path selection (per run).** Path table (per-sphere / composite / `instance_grains` / `instance_static`), D3 status, the branch-on-`viz_mode` rule and `--input-mode dump` status: WSL `docs/SHARED_FACTS.md` § Visualisation paths. Per-path Windows how-to: sections below.

### Pure instancing viz (Option A — static placeholder point cloud)

**Prerequisites:** grain npz and body CSV files from `DEMDumpConvert.py` (for scale reference — see `reference_scale_from_run()`), plus a triangulated shape-model OBJ (e.g. the JPL Apophis radar shape). Because `viz/viz_preprocess_lite.py` imports `viz/shape_sampling.py`, which needs `mathutils.bvhtree` for the BVH interior-point test, this preprocessing step runs under **Blender's bundled Python**, not the plain `.venv` — the same constraint as `P0_InstancingSpike.py`.

**Step 1 — preprocess** (writes `run_XXXX_viz_instance/` next to the grains/bodies folders):

```bash
"$B" --background --python "$(wslpath -w viz/viz_preprocess_lite.py)" -- \
  --grains-dir "$(wslpath -w "$D/DEMCSVs/<sim>/run_XXXX_grains_output")" \
  --bodies-dir "$(wslpath -w "$D/DEMCSVs/<sim>/run_XXXX_bodies_output")" \
  --output-dir "$(wslpath -w "$D/DEMCSVs/<sim>/run_XXXX_viz_instance")" \
  --shape-obj "$(wslpath -w "$D/BlenderConvert/Shapes/<...>.obj")" \
  --n-points 1000000
```

This rejection-samples the shape OBJ into a static point cloud, scaled to the run's frame-1 cluster radius and grain radius (volume-conserving at whatever `--n-points` is requested), and writes a `viz_mode: "instance"` manifest. `--sim-name`, `--run-name`, and `--seed` are optional overrides; `--n-points` defaults to 1,000,000.

**Step 2 — Blender:** open `BlenderConvert/DEMBulkInstanceBlender.py` in the Scripting tab (or run it the same way as `P0_InstancingSpike.py` if working headless), set `VIZ_MANIFEST` to the absolute path of `run_XXXX_viz_instance/manifest.json`, click **Run Script** (Cycles). This is the same manifest-driven convention as the composite path — `DEMBulkInstanceBlender.py` reads `viz_mode` and refuses a manifest that isn't `"instance"`.

**Prerequisite the script does not auto-satisfy:** the "Procedural rock" material must already be present in the current file's material list (append it via File > Append > Material from `BlenderConvert/Blenders/11.blend`, or `P0_Apophis_1M.blend`) — several similarly named rock materials exist under `BlenderConvert/Blenders/assets/materials/`, so this is deliberately not auto-appended to avoid silently picking the wrong one.

**What this path currently is and isn't:** `viz_preprocess_lite.py`'s output is a *static placeholder* — one frame's worth of points sampled once inside the shape model and held fixed across the whole timeline (`manifest['static']: true`); only the Earth/Sun/Moon/camera keyframing animates per frame, exactly as it does for the composite path. `DEMBulkInstanceBlender.py` itself now supports `static: false` manifests too (`_instance_frame_change_handler` reloads and re-uploads the point cloud's vertex buffer every frame — point count and `grain_radius_vis` stay fixed for the run, only positions change). Two sources feed `static: false` today: `viz/viz_preprocess_grains_instance.py` (real per-frame grains from converted `.npz`, per-grain `radius`, DEM run size ~500 grains; numpy only, runs in `.venv`) and the synthetic test below. Direct million-grain dump ingestion (`--input-mode dump`) is still not implemented.

### Objective 3 — Option A synthetic flyby test (`viz/synthetic_flyby_test.py`)

Exercises the `static: false` per-frame loading path end-to-end at 1,000,000 points before any real per-frame DEM simulation data exists. Reuses `viz_preprocess_lite.py`'s shape sampling (same static rigid shape, same volume-conserving `grain_radius_vis`) but writes one points file **per frame** — a rigid-body rotation of the same base shape about a fixed axis — instead of one static file, and sets `static: false`. This is a stand-in for real motion, not a simulation: the manifest carries `"synthetic": true` and `"motion_model": "rigid_tumble"` so nothing downstream can mistake it for real data, and `DEMBulkInstanceBlender.py` prints a note when it loads one.

```bash
"$B" --background --python "$(wslpath -w viz/synthetic_flyby_test.py)" -- \
  --grains-dir "$(wslpath -w "$D/DEMCSVs/<sim>/run_XXXX_grains_output")" \
  --bodies-dir "$(wslpath -w "$D/DEMCSVs/<sim>/run_XXXX_bodies_output")" \
  --output-dir "$(wslpath -w "$D/DEMCSVs/<sim>/run_XXXX_viz_instance_flyby_test")" \
  --shape-obj "$(wslpath -w "$D/BlenderConvert/Shapes/<...>.obj")" \
  --n-points 1000000 --start-frame 0 --max-frames 48
```

Writes `run_XXXX_viz_instance_flyby_test/points/{frame_id}.npz` (one per frame) and a `manifest.json` with `points_dir: "points"` instead of the static path's single `points_path`, plus `bodies_start_index` (see below). `--max-frames` defaults to 48, not the run's full frame count — at 1,000,000 points a compressed per-frame `.npz` is several MB, so the full ~200-frame `torque_align_obj/run_0001` would be gigabytes; raise it deliberately if you want a longer clip. The tumble rate is driven by each frame's real `time_s` from the bodies CSVs when present (`--spin-period-hours`, default 30.4 — Apophis's approximate real rotation period); `torque_align_obj/run_0001`'s bodies CSVs have no `time_s` column, so the script falls back to spreading a fixed 1.5 rotations evenly across whatever frame range you asked for, and says so.

**`--start-frame`** selects which sorted body CSV maps to the manifest's first frame — e.g. `--start-frame 150 --max-frames 67` on a 217-frame run covers its last 67 frames (a close-approach window) instead of the first 48. This matters because Apophis-frame body-CSV indices don't correspond 1:1 to "time from the start of the clip" once you slice a sub-range: `DEMCinematicSetup.keyframe_bodies_and_earth()` takes a `start_index` parameter for exactly this (default 0, so every other caller is unaffected), and the manifest's `bodies_start_index` field is what tells `DEMBulkInstanceBlender.py` to pass it through. Forgetting this — i.e. slicing the points/frame_ids but still keyframing Earth from body-CSV index 0 — silently reproduces the *first* N frames of Earth's motion under the asteroid's tail-window tumble, which looks like "Earth barely moves" even though real Earth motion is happening, just from the wrong slice of the run.

Verified 2026-09-12 against `torque_align_obj/run_0001`: first at `--n-points 1000000 --max-frames 48` (frames 0–47) — point positions confirmed changing frame-to-frame (pure rotation about the fixed axis), Cycles renders at frame 1 vs. 24 show a visibly different silhouette, but Earth stays a near-invisible speck (~300,000–400,000 BU away) since that window is the slow/distant part of the encounter. Then at `--start-frame 150 --max-frames 67` (frames 150–216, the real close approach): Earth's keyframed distance drops to ~8,360 BU at frame 40 of the clip (Earth's ~1274 BU radius subtends ~17° from there) and the render shows Earth growing from a distant dot to a large lit disc and back — confirming both the per-frame point-cloud reload and the `start_index` fix. Per-frame `scene.frame_set()` cost (disk load + `foreach_set` + `mesh.update()` + GN re-eval) measured at ~0.2 s for 1,000,000 points, in line with the P0 spike's ~100 ms in-memory update estimate plus the added `.npz` read.

The manifest also carries `angles_rad` — the exact tumble angle (radians) at each real frame, about `spin_axis` — alongside the per-frame `.npz` files. This exists so a slow-motion playback stretch (below) can interpolate the tumble exactly instead of only ever snapping between discrete per-frame snapshots.

### Objective 3 — Option A slow-motion playback and video export (`DEMBulkInstanceBlender.py`)

**Slow-motion stretch.** `DEMBulkInstanceBlender.py` has `SLOWMO_FACTOR` (default 4) and `TARGET_FPS` (default 60) config vars: they stretch the same real frame range over `n_frames * SLOWMO_FACTOR` timeline frames using Blender's built-in time remap (`render.frame_map_old/new`), so the same simulated duration plays slower/smoother at a higher frame rate. Set `SLOWMO_FACTOR = 1` to disable.

- **Ordering matters.** `main()` keyframes Earth/Moon/Sun/camera at 1:1 time *first*, then enables the remap only afterward. `keyframe_bodies_and_earth()` and `setup_camera()` both call `scene.frame_set()` internally while authoring (to sample Earth's just-created position for the camera track); if the remap were already active during that authoring loop, those calls would sample at the *squashed* remapped time instead of the intended raw frame, silently aiming the camera using the wrong slice of Earth's motion (confirmed live: camera ended up pointing 180° away from Earth, `dot=-0.88`, until the ordering was fixed). Both functions now document this hazard directly.
- **Point-cloud interpolation.** For a synthetic `rigid_tumble` manifest (has `angles_rad`), `_instance_frame_change_handler` evaluates the exact tumble angle at the fractional real frame. Real-grain manifests from `viz_preprocess_grains_instance.py` carry per-frame `handle` arrays (`manifest['interpolation']`): the preprocess solves the per-sphere path's location F-curves (Bezier, AUTO_CLAMPED, **Continuous Acceleration** auto-smoothing — the Blender 5.2 default and the installed prefs; `viz/fcurve_handles.py`, checked against `FCurve.evaluate`) and the handler evaluates that cubic, so grains move exactly as the per-sphere objects do between sim frames. The real-frame index comes from `_key_index()` (remapped time incl. subframe, the time F-curves are evaluated at); before 2026-09-27 it ignored the remap and ran (SLOWMO−1)/SLOWMO frames ahead of Earth/camera. Older manifests without handles still hold each frame.
- `RENDER_RESOLUTION` (default `(1920, 1080)`) is also now an explicit config var, set every run — previously the script left resolution as whatever the scene last had, which silently produced a 640×360 render from an unrelated leftover setting.

**Combining a rendered image sequence into a video.** No separate `ffmpeg` install needed or expected on this machine (checked: not on `PATH`) — Blender ships its own and can write video directly through the Video Sequence Editor (VSE), scripted, without opening the VSE UI:

```python
import bpy, os
scene = bpy.context.scene
seq_ed = scene.sequence_editor or scene.sequence_editor_create()
strip = seq_ed.strips.new_image(name="seq", filepath=first_frame_path, channel=1, frame_start=1)
for fn in remaining_filenames:
    strip.elements.append(fn)          # bare filename, same folder as first_frame_path
strip.frame_final_duration = n_frames
scene.frame_start, scene.frame_end = 1, n_frames
scene.render.use_sequencer = True
scene.render.image_settings.media_type = 'VIDEO'   # must be set before file_format=='FFMPEG' is selectable
scene.render.image_settings.file_format = 'FFMPEG'
scene.render.ffmpeg.format, scene.render.ffmpeg.codec = 'MPEG4', 'H264'
scene.render.fps = 24  # lower fps over the same frame count = longer playback, same content
bpy.ops.render.render(animation=True)
```

Two version-specific gotchas hit live in this session (Blender 5.2.1 LTS):
- `SequenceEditor.sequences` was renamed to `.strips` (`seq_ed.sequences.new_image` raises `'SequenceEditor' object has no attribute 'sequences'`; use `seq_ed.strips`).
- `image_settings.file_format`'s enum is filtered by `image_settings.media_type` (`'IMAGE'` vs `'VIDEO'`) — if `media_type` is left at `'VIDEO'` from an earlier video render, assigning `file_format = 'PNG'` raises `enum "PNG" not found in ('FFMPEG',)`. Set `media_type = 'IMAGE'` first for a single-frame PNG check-render, `'VIDEO'` first for an FFmpeg export.

**Long animation renders should run non-blocking.** `bpy.ops.render.render('INVOKE_DEFAULT', animation=True)` starts the render job without blocking the calling script/tool call; poll progress with `bpy.app.is_job_running('RENDER')` (`True`/`False`) rather than waiting on the call to return. `bpy.context.window_manager.is_job_running` does not exist as an attribute — the job-status check is on `bpy.app`, not `bpy.context.window_manager`.

### Sim + render pipeline TUI (WSL orchestrator, one command end-to-end)

WSL `sobol/tui_sim_render.py` runs one DEM run end-to-end (sim → convert → headless render, any mix of the four render paths). Launch, form, stages, output layout: `../sobol/CLAUDE.md`. Path names: `SHARED_FACTS.md`. Merge state: WSL `docs/CONTEXT_CHANGELOG.md`.

Blender side of it: `BlenderConvert/DEMHeadlessRender.py` (item 13), run by `blender.exe` via its `\\wsl.localhost\...` path; it loads HDRI / `11.blend` from `DEMHeadlessRender.ASSETS_DIR` (OneDrive `BlenderConvert/`, override `$HONOURS_BLENDER_ASSETS_DIR`). Preprocess scripts under `viz/` run in the OneDrive `.venv` (`viz_preprocess.py`, `viz_preprocess_grains_instance.py`) or Blender (`viz_preprocess_lite.py`), cwd = this repo.

### GN instancing performance spike (`P0_InstancingSpike.py`)

Benchmarks Geometry Nodes **Instance on Points** at 10³–10⁶ grains in Cycles, to decide whether the Option A pure-instancing path is viable. Measures Python update time, depsgraph re-evaluation, viewport redraw, Cycles render time, process RAM and GPU VRAM.

**Unlike every other `BlenderConvert/` script, this one runs headless** — it needs no GUI and no BlenderMCP connection:

```bash
"$B" --background --python "$(wslpath -w BlenderConvert/P0_InstancingSpike.py)"
```

That sweeps every entry in `CONFIGS` × `RENDER_DEVICES` and writes the report. It creates a scratch scene (`P0_Spike_Scene`), restores the previous scene afterwards, and never saves the `.blend` — safe to run against an open project.

**Step-by-step** (Scripting tab, or over MCP to avoid one long blocking call):

```python
import sys; sys.path.insert(0, r"\\wsl.localhost\Ubuntu\home\mboyle\Honours\Code\BlenderConvert")
import P0_InstancingSpike as p0
p0.run_one(100_000, subdiv=1, device="GPU")   # appends one row
p0.write_report()                              # regenerate the table
```

Results accumulate in the OneDrive `docs/p0_instancing_results.json` (`RESULTS_DIR`; report + renders stay in OneDrive, not git) keyed by `(N, subdiv, device)`, so partial runs across several invocations still build one complete table, and re-running a configuration replaces its row.

**Configuration** (top of script):

| Variable | Default | Notes |
|----------|---------|-------|
| `RESULTS_DIR` | `Code/docs` | Where the JSON + markdown + `p0_renders/` land |
| `CONFIGS` | 10³–10⁶ × subdiv 0/1 | `(n_points, subdiv)` pairs, cheapest first |
| `RENDER_DEVICE` / `RENDER_DEVICES` | `"GPU"` / `("GPU","CPU")` | **Must be set explicitly** — see gotcha below |
| `RENDER_MAX_N` | `1_000_000` | Skip the render above this N (update/viewport still measured) |
| `RENDER_SAMPLES`, `RENDER_RESOLUTION` | `32`, `960×540` | Deliberately low; real shots cost more |
| `BODY_RADIUS_VIS`, `REF_N`, `REF_GRAIN_RADIUS_VIS` | `15.0`, `500`, `2.4` | Synthetic pile geometry, anchored on the np500 reference so grain radius shrinks with *N* at constant total volume |
| `GRAIN_MESH_SUBDIV` | per-config | Icosphere subdivisions: 0 → 20 tris, 1 → 80, 2 → 320 |

**Gotcha — a new scene defaults to CPU.** `bpy.data.scenes.new()` sets `cycles.device = 'CPU'` regardless of user preferences, so any script building its own scene must set the device explicitly or it silently benchmarks the CPU. The results table records `device_effective` read back from the scene, not the requested value.

**Outputs** (all generated — regenerate rather than hand-edit):

```
docs/P0_INSTANCING_SPIKE.md      # environment, results table, embedded renders, caveats
docs/p0_instancing_results.json  # raw rows
docs/p0_renders/*.png            # any PNG dropped here is embedded in the report
```

#### Objective 3 — Option A P0 result (measured 2026-09-07)

Blender 5.2.1 LTS, RTX 4050 Laptop (6 GB, CUDA), i7-12650H, 960×540 @ 32 samples:

| N | subdiv | tris | GPU s/frame | update ms | depsgraph ms | VRAM Δ |
|---|--------|------|-------------|-----------|--------------|--------|
| 100,000 | 1 | 8M | 1.6 | 10.1 | 1.4 | 683 MB |
| 1,000,000 | 0 | 20M | 5.3 | 101.9 | 12.3 | 993 MB |
| 1,000,000 | 1 | 80M | 5.2 | 96.8 | 11.6 | 1004 MB |

**Verdict: instancing passes its go/no-go gate.** No ceiling at 10⁶ — 80M instanced triangles render in ~5 s using 1.0 GB of 6 GB VRAM.

- **Python update cost is not the bottleneck** the Option A spec feared: `foreach_set` + `mesh.update()` + GN re-evaluation is ~110 ms/frame at 10⁶, roughly 2% of render time. The spec's fallbacks (subsample for preview, revert to envelopes) are unnecessary for batch rendering.
- **Subdivision is effectively free** — subdiv 1 matched subdiv 0 at 10⁶ (5.2 s vs 5.3 s); cost tracks rays and instance transforms, not triangle count. Do not ship the faceted subdiv 0.
- **The pile does read as a solid body at 10⁶** (`docs/p0_renders/`): np500 shows obvious blocks, 10⁶ shows a coherent body with granular regolith texture, and even a close pass (1.6× body radius) reads as coarse gravel. A true hero close-up still wants the composite envelope.
- **Caveat:** 32 samples at 960×540 is a low bar — thesis-resolution shots scale the render up; the ~110 ms instancing overhead does not.
- **Still unmeasured: viewport FPS.** `wm.redraw_timer` needs a real 3D viewport, so headless leaves those columns blank. This is the spec's "render-feasible but viewport unusable" risk, still open — run the spike from a GUI Blender session to fill it in.

SBMT mosaic texture (standalone, not Blender):
```bash
python3 BlenderConvert/sbmt_mosaic.py \
  --input ./backplanes --output ./phobos_texture \
  --width 8192 --height 4096 [--albedo-csv phobos_..._v004.csv]
```

## Blender script architecture

All scripts in `BlenderConvert/` are pasted into Blender's **Scripting** workspace and run with the **Run Script** button. They are **not** standalone Python scripts (they require `bpy`).

**Point-mass pipeline scripts (simplest → most capable):**

1. **`CSVtoBlender.py`** — One UV sphere per body, keyframes each CSV. `SCALE=1.0`. `CSV_DIR` → `csv_output/`.

2. **`workinglargescaleimport.py`** — Bezier F-curve smoothing. `SCALE=5000`. Handles legacy and Blender 4.x+ slotted action system.

3. **`OnlyEarth_ApophisTrueSize.py`** — Most complete point-mass importer. `BodyModelConfig` dataclass, `import_body_model()`, `_recenter_to_apophis()` frame handler. `IMPORT_CSV_INDICES` = Sun(0), Earth(3), Apophis(10).

4. **`Camera.py`** — `EarthCam` parented to Earth. Run after `OnlyEarth_ApophisTrueSize.py`.

5. **`Viewport.py`** — Clip range + centre viewport on Apophis.

**DEM pipeline scripts:**

7. **`DEMGrainsBlenderEarthCam.py`** — Per-sphere grains + Earth + integrated DEM camera in one script. **Grain material** (`DEM_Grain`, "Shared grain material" section): appends the same node-based **"Procedural rock"** material (`ROCK_MATERIAL_NAME`) from `Blenders/11.blend` (`ROCK_MATERIAL_BLEND_PATH`) that the million-particle instancing path (item 12) requires pre-appended — Voronoi/Noise/Bump nodes only, no image textures, so no missing-file risk — `.copy()`d and renamed to `DEM_Grain` so it stays independently editable. Falls back to the old flat `GRAIN_COLOR` Principled BSDF (with a WARNING print) if `11.blend` or the material name is missing. **Per-grain random rotation:** "Procedural rock" is driven by Object texture coordinates, so unrotated spheres all show the identical pattern (clone-tiling look). Each sphere gets a fixed random orientation (uniform 0–2π per axis, passed as `primitive_uv_sphere_add(rotation=…)`), drawn up front from `np.random.default_rng(GRAIN_RANDOM_ROTATION_SEED)` (default `0`) so reruns match. Rotation is never keyframed — only location animates — so the pattern stays locked to its grain. Same fix as item 12's `_add_random_rotation`. Set `GRAIN_RANDOM_ROTATION = False` to reproduce pre-2026-09-18 renders exactly. Verified 2026-09-18 on `DEMCSVs/run_0001_*` (503 grains): 503/503 grains rotated; close-up A/B shows the repeated bright-centre pattern gone. **Pitfall:** grains-only test datasets whose bodies CSVs put every body at the origin (e.g. `DEMCSVs/MiaDEM_bodies_output`) render pure white on this path. The 20000 BU emissive `Sun_Body` sphere then surrounds the camera, whatever the camera mode — use a real sweep run instead.

9. **`MaterialandSubsivision.py`** — Shared modifiers and materials on all grain objects. Run after import.

10. **`DEMBulkVizBlender.py`** — Bulk composite path: set `VIZ_MANIFEST` to `run_XXXX_viz/manifest.json`; frame handler animates envelope meshes + Geometry Nodes ejecta instancing. See **Bulk composite viz** in Key commands. Does **not** replace per-sphere importers.

11. **`DEMCinematicSetup.py`** — Shared cinematic module, not run standalone: imported by both `DEMBulkVizBlender.py` and `DEMBulkInstanceBlender.py`. Earth spin + time of day come from **`earth_orientation.py`** (pure Python, also used by `DEMGrainsBlenderEarthCam.py`; tests `sobol/tests/test_earth_orientation.py`). Set `EARTH_EPOCH_TDB` if a run's `.setup` `epoch` is not 2029-04-10. A WARNING prints if keys are > 90° of spin apart. Holds the Earth/Moon/Sun placeholder, body-CSV keyframing, grain-core tracking camera (`setup_camera()`, `grain_core()`; the camera aims through a Track To constraint `DEM_AimAtCore` on the Empty `DEM_CameraAim`, keyed at the core, so it stays on the body between keys under `--slowmo` or motion blur: the keyed LINEAR rotation alone drifted up to 4.5° off between keys), the `frame_handler_suspended()` context manager used to detach a per-frame handler around setup loops, and `register_self_as_auto_run_module()` (see **Frame-handler animation does not survive closing Blender** below).

**Frame-handler animation does not survive closing Blender.** Both bulk paths animate their meshes/point cloud with a `bpy.app.handlers.frame_change_pre` callback plus module-level Python state — neither is saved in the `.blend`. `@bpy.app.handlers.persistent` only keeps the callback alive across *File > Open* within one running Blender process; quitting and relaunching Blender.exe starts a fresh process with no handler and no state, so a saved `.blend` reopens with the envelope/ejecta/point-cloud frozen at whatever frame was showing on save (the asteroid stops "spinning"). This is the same bug class `OnlyEarth_ApophisTrueSize.py` hit and fixed for the point-mass path by baking positions into real keyframes instead of a handler (see its closing `print()` for the "no Python handler required" note). For the bulk paths, `main()` instead calls `DEMCinematicSetup.register_self_as_auto_run_module()` right after registering the handler — it flags the running script's own Text block (`text.use_module = True`) so Blender re-executes it on file load, rebuilding state and re-registering the handler. **This only takes effect if Blender's "Auto Run Python Scripts" preference (Edit > Preferences > Save & Load) is enabled, or the file/folder is a trusted source** — otherwise the flag is inert and the original symptom returns. It is a no-op when run via `blender --background --python` (no Text Editor context), which is fine since that always starts `main()` fresh anyway.

12. **`DEMBulkInstanceBlender.py`** — Pure-instancing bulk path (Option A), parallel to `DEMBulkVizBlender.py`: set `VIZ_MANIFEST` to a `viz_mode: "instance"` manifest from `viz_preprocess_lite.py` (static), `viz/viz_preprocess_grains_instance.py` (per-frame real grains) or `viz/synthetic_flyby_test.py` (per-frame test data), click **Run Script** (Cycles). Builds a single GN "Instance on Points" point cloud (via `P0_InstancingSpike.build_geometry_nodes()`) with a per-instance rotation (the points file's `rot` when present, else random) to avoid a clone-tiling look, and requires the "Procedural rock" material to already be appended. Supports both `static: true` (point cloud fixed all timeline, only Earth/Sun/Moon/camera animate) and `static: false` (`_instance_frame_change_handler` reloads the point cloud's vertex buffer from `points_dir/{frame_id}.npz` every frame, or interpolates it analytically for a synthetic `rigid_tumble` manifest). Also sets an explicit `RENDER_RESOLUTION` every run, and supports a `SLOWMO_FACTOR`/`TARGET_FPS` playback time-remap. Points files that carry a `radius` array (from `viz/viz_preprocess_grains_instance.py`) set a per-grain GN radius; otherwise every instance uses `grain_radius_vis`. See **Pure instancing viz**, **Option A synthetic flyby test**, and **Option A slow-motion playback and video export** in Key commands.
    - **Parity with per-sphere (`instance_grains`):** same 12×8 flat UV sphere, per-grain Euler rotation (same seeded draw), rock texture scaled by the instancer `radius` (instances are unit meshes), the same Bezier F-curve motion (handles from `viz/fcurve_handles.py`, evaluated with its `evaluate`), and the same Sun lamp / Moon / Sun_Visual / fill light / grain-core camera from `DEMCinematicSetup.py`. Instance-only grain tint: `GRAIN_COLOUR_VARIATION` stays `True` (HSV + multiply between `GRAIN_VAR_TINT_A` and `GRAIN_VAR_TINT_B`, Object Info Random). The hero script has no tint, so rendered pixels are not compared. `sobol/tests/test_instance_parity.py` checks geometry and scene with the tint on: grain surfaces agree to < 1e-3 BU, and scene object matrices, lights and camera match.
    - **Changing grain set:** the preprocess gives every grain that ever appears a point, writes a per-frame `present` mask (points key) and `variable_grain_set` (manifest), holds absent slots at the nearest present position with zero handles, and solves handles over each grain's own frames. The script wires `present` into Instance on Points' `Selection` and aims the camera at present grains only. Per-sphere (`DEMGrainsBlenderEarthCam.py`) builds the same grain set and keys `hide_render`/`hide_viewport` (constant) for grains that join or leave, only on frame 1 and where visibility changes. A grain that leaves and returns raises `GrainReappeared` in both. A frame with no grains aims the camera at the origin (Apophis CoM) in both. Points files without `present` draw every point.
    - **Still per-sphere only (GUI):** (1) reopened GUI `.blend` needs "Auto Run Python Scripts" (frame handler, not keyframes); (2) no selectable per-grain objects for hand-edited hero shots. Preprocess holds all frames in memory for the handle solve; million-grain runs would need chunking.
    - `_viz_instance/` folders built before 2026-09-27 have no `handle`/`rot`: they still render (held frames, random rotation; prints a NOTE). Re-run the preprocess for parity.

13. **`DEMHeadlessRender.py`** — Headless-only render for composite and instance, driven by `sobol/tui_sim_render.py` (WSL). `--viz-path composite|instance` (default `instance`). `--viz-path composite --manifest …` patches `DEMBulkVizBlender.py`'s `VIZ_MANIFEST`/`CAMERA_MODE`; `--viz-path instance --manifest …` appends "Procedural rock" from `Blenders/11.blend`, then patches `DEMBulkInstanceBlender.py`'s `VIZ_MANIFEST`/`CAMERA_MODE`/`SLOWMO_FACTOR=1`/`RENDER_RESOLUTION`. `GRAIN_COLOUR_VARIATION` is not patched. `DEMGrainsBlenderEarthCam.py` is the GUI hero script, not a CLI path; `patch_script_source("per_sphere")` still rewrites its `GRAINS_DIR`/`BODIES_CSV_DIR`/`CAMERA_MODE`/`MAX_FRAMES` so the parity test can build the reference scene and call `render_prepared_scene`. Each patterned constant must match exactly once. The chosen script is `exec()`d (same technique `run_demtocsv_batch.py` uses on `DEMDumpConvert.py`); bulk paths set `scene.render.use_lock_interface = True` because their frame handlers rewrite meshes mid-render. It always assigns World `Deep Dark Space with Stars.001` from `Blenders/assets/hdrs/deep-dark-space-…/deep-dark-space-with-stars_4K_….exr` (matches `Blenders/Apophisonly.blend`; missing EXR warns and sets a plain black World), sets view transform AgX, stops with the reason if the viz script left no scene camera (`require_camera()`; the startup Camera is removed before exec), calls `setup_cycles_gpu()` (first backend with devices of **OPTIX**, **CUDA**, HIP, ONEAPI, METAL; GPU devices on, CPU hybrid **off**; raises if no GPU — `scene.cycles.device = 'GPU'` alone is not enough) or, with `--device cpu`, `setup_cycles_cpu()` (`--device` defaults to `cycles_device` in `Code/local_paths.json`). `--slowmo N` (instance only, default 1) patches `SLOWMO_FACTOR = N` instead of 1: N timeline frames per dump over the same sim time, in-betweens on the grains' Bezier curves (interpolated, not simulated); the render starts at timeline frame N (= dump 1, `apply_slowmo_range`), so a run of n dumps gives (n-1)·N+1 frames named `frame_000N`…; `RenderParams.slowmo` passes it from Python drivers; the TUI `slowmo` field and `render_dumps.py --slowmo` set it for instance paths and write to `run_NNNN_render_<path>_slowmoN/`. `--resume` (`RenderParams.resume`) keeps `frame_*.png` already in `--output-dir` and renders only the missing frames (`render.use_overwrite = False`), for carrying on an interrupted render; the encode still needs the full count on disk. Every path renders with `apply_render_speedups()`: persistent data on, image textures capped at 4K per image by `cap_image_textures()` (`TEXTURE_MAX_PX`; names containing `TEXTURE_CAP_EXEMPT` = "clouds" keep full size, 8192×4096; Cycles `texture_limit_render` left OFF since it is global), and `coarsen_adaptive_subdivision()` (adaptive dicing floored at 4 px/edge; off on objects whose material has no displacement, i.e. the volume Atmosphere). `TheEarth1.blend` dices Surface/Clouds/Atmosphere at 1 px, so memory grew with Earth's screen size (40k flyby approach: 10 → 20 GB, 15 → 58 s/frame, Windows swapping; persistent data only kept it resident). GPU renders also set `denoising_use_gpu` (`apply_gpu_denoise()`; OIDN on the CPU was ~7 of 9.5 s per frame). Before these (Earth's 10K–21K maps + volume atmosphere overflowed the 6 GB RTX 4050; 40k flyby frame 41 → 16 s, max pixel diff 1/255; 2026-10-13). It sets resolution/samples/fps, and renders a PNG sequence via `bpy.ops.render.render(animation=True)`. Wraps `main()` so any exception prints a traceback and exits 1 — Blender `--background --python` otherwise exits 0 on an uncaught exception. See **Sim + render pipeline TUI** below.
    - **`--encode-video` (optional, off by default) / `--video-fps N`** — after the PNG sequence is written, `encode_video()` combines `out_dir`'s `frame_*.png` into `out_dir/animation.mp4` (H264) using the same VSE-scripted-ffmpeg technique documented right below ("Combining a rendered image sequence into a video") — no separate `blender.exe` invocation, same process. `--video-fps` defaults to `--fps` if not given. Raises if the on-disk frame count doesn't match what was just rendered (a silent partial encode would be worse than a loud failure). `sobol/tui_sim_render.py`'s TUI exposes this as an `encode_video` checkbox + `video_fps` field on the Render section.
    - **From `feature/render-pipeline-improvements` (merged into `master` 2026-10-03):**
      - `--max-frames` clamps `scene.frame_end`. Composite/instance load frames lazily in `frame_change_pre`. The hero script's `MAX_FRAMES` limits how many grain files it keyframes; the parity check patches that constant.
      - `main()` first sets stdout/stderr to line buffering (`_line_buffer_std_streams()`). Blender's Python block-buffers stdout into a pipe and ignores `PYTHONUNBUFFERED`, so without this the TUI's `render.log` / live status line only got output at exit.

**Benchmark / measurement scripts:**

14. **`P0_InstancingSpike.py`** — GN-instancing cost benchmark, **the exception to the paste-into-Scripting-tab rule**: it runs under `blender --background --python` with no GUI, and is the fastest way to validate any `bpy` code in this repo without opening Blender. Builds its own scratch scene from synthetic points, restores the previous scene, never saves. Reads no simulation data. See **GN instancing performance spike** in Key commands.

15. **`viz/synthetic_flyby_test.py`** — Also runs under `blender --background --python` (needs `viz/shape_sampling.py`'s `mathutils.bvhtree`), same as `viz_preprocess_lite.py`. Writes per-frame `static: false` test manifests for `DEMBulkInstanceBlender.py` — a rigid tumble of the same static placeholder shape, not real simulation data. See **Option A synthetic flyby test** in Key commands.

### Configuration pattern

When switching datasets:
- **Bulk composite:** `VIZ_MANIFEST` in `DEMBulkVizBlender.py` — path to `run_XXXX_viz/manifest.json` (see `docs/BATCHES_VIZ.md`)
- **DEM per-sphere scripts:** `GRAINS_DIR`, `BODIES_CSV_DIR` — paths to `run_XXXX_*_output/` folders (see `docs/BATCHES_VIZ.md`)
- **Point-mass scripts:** `CSV_DIR`, `SCALE` (5000 typical), `RADIUS_UNIT`
- Body model paths in `OnlyEarth_ApophisTrueSize.py`


## SBMT mosaic (`sbmt_mosaic.py`)

Standalone tool for equirectangular surface texture from SBMT backplanes (Phobos/Deimos).

- **Input**: `.fit`/`.fits` or ENVI `.hdr` + data pairs.
- **Output**: `_16bit.png` (Non-Color in Blender), `_8bit.png`, `_coverage.png`.
- Dependencies: `astropy`, `numpy`, `Pillow`, `scipy`.

