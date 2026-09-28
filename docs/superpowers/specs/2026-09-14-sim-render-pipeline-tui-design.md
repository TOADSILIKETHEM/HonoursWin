# Sim + render pipeline TUI — design spec

**Date:** 2026-09-14
**Scope note:** This feature spans both repos — the orchestrator TUI lives in
the WSL `Honours` repo (`sobol/`), the new headless render script lives in
this Windows repo (`BlenderConvert/`). Saved here because this repo already
has the `docs/superpowers/specs/` convention (see the Objective 3 Option A
specs in this directory); the WSL repo does not currently have an equivalent
directory. If that assumption is wrong, move/duplicate accordingly — it does
not change the design itself.

## Goal

A single Textual TUI, `sobol/tui_sim_render.py` (WSL), that takes one
PHANTOM DEM run from "configure" to "rendered PNG sequence" without manual
steps in between: configure simulation parameters → run PHANTOM → convert
dumps to bodies CSV + grains npz → render a Blender per-sphere clip headless
→ report the output frame directory. One run per launch, not a sweep —
`sobol/tui_run.py` already covers Sobol sweeps.

## Non-goals (explicitly out of scope for this spec)

- Composite (`DEMBulkVizBlender.py`) or instancing (`DEMBulkInstanceBlender.py`)
  render paths — per-sphere (`DEMGrainsBlenderEarthCam.py`) only.
- Batch/queue mode (multiple sims per launch).
- Automatic video encoding (VSE→FFmpeg) — output stops at a PNG sequence;
  the manual VSE steps already documented in this repo's `CLAUDE.md` cover
  turning that into a video, as a separate follow-up action.
- Parallel/distributed execution — this pipeline runs one sim and one render,
  sequentially, in the foreground.

These may become follow-up specs; nothing here should make them harder to
add later (see **Extension points** at the end).

## Architecture

```
sobol/tui_sim_render.py  (WSL, Textual)
  │
  ├─ 1. Sim config form → RunSample (run_mass_sobol_phantom.py)
  │       preflight() + run_one_case()          [reused, not reimplemented]
  │       → run_dir with sobol_* dumps
  │
  ├─ 2. Convert step (automatic, no form) →
  │       run_demtocsv_batch.run_dem_dump_convert()   [reused]
  │       → DEMCSVs/<sim>/<run>_bodies_output/*.csv
  │       → DEMCSVs/<sim>/<run>_grains_output/*.npz
  │
  ├─ 3. Render config form → resolution / samples / fps / max-frames
  │       → subprocess: blender.exe --background --python
  │             BlenderConvert/DEMHeadlessRender.py -- <args>
  │
  └─ 4. Report: output PNG dir + frame count + elapsed time, or the first
          failing stage's error, in the TUI status bar.
```

`DEMHeadlessRender.py` (new, Windows repo, `BlenderConvert/`) is the only
new Blender-side file. It does not reimplement scene-building: it text-patches
`DEMGrainsBlenderEarthCam.py`'s `GRAINS_DIR`/`BODIES_CSV_DIR` constants and
`exec()`s it — the same technique `sobol/Analysis/run_demtocsv_batch.py`
already uses on `DEMDumpConvert.py`. This means grains + Earth + camera are
built exactly as they are for the interactive Scripting-tab path; only the
render settings and the render call are new code.

**UI flow:** single screen, all fields (sim + render) visible at once —
same one-screen-then-submit model as `tui_run.py`, not a multi-step wizard.
On submit (real run or dry run), stages 1→2→3 run in sequence in one worker
thread; the form is not re-shown between stages.

## Component 1 — Sim config + run (`tui_sim_render.py`, WSL)

Reuses `run_mass_sobol_phantom.py`'s existing single-run machinery (the same
functions `sobol/run_torque_align_blender_reruns.py` already calls):

```python
from run_mass_sobol_phantom import RunSample, preflight, run_one_case
```

Form fields map directly to `RunSample` dataclass fields (all `Optional`,
`None` = leave template unchanged) — fixed values only, no min/max, no Sobol
sampling, since this is a single run:

| Form field | `RunSample` field | Notes |
|---|---|---|
| Use DEM | `use_dem` | bool |
| np_apophis | `np_apophis` | int |
| Spin period (hr) | `apophis_spin_period` | float |
| Spin torque-align (deg) | `apophis_spin_torque_align_deg` | float, 0=+h .. 180=-h |
| kt_cgs | `kt_cgs` | float, 0 = no cohesion |
| dn_cohes_factor → coh_gap_max_cgs | `coh_gap_max_cgs` | computed via the existing keyword-only helper `coh_gap_max_cgs_from_dn(dn=dn_value, np_apophis=np_apophis)` (already imported by `run_torque_align_blender_reruns.py`) if the user enters `dn` instead of a raw cgs value |
| tmax (hr) | `tmax_hours` | float |
| dtmax (hr) | `dtmax_hours` | float |
| Use shape crop + shape file path | `use_shape_crop` + separate `shape_file: Optional[str]` passed to `run_one_case()` | mirrors `tui_run.py`'s existing `vary-use-shape-crop`/`shape-file` gating |
| Sink IDs (Earth/Apophis) | passed as `earth_sink_id`/`apophis_sink_id` to `run_one_case()`, not on `RunSample` | defaults `EARTH_SINK_ID_DEFAULT`/`APOPHIS_SINK_ID_DEFAULT` from `run_mass_sobol_phantom` |
| Ephemeris cache dir | passed as `ephemeris_cache_dir` to `run_one_case()`, not on `RunSample` | optional; blank = skip Horizons download, same semantics as `tui_run.py`'s `eph-cache` field |
| Batch label / prefix / base_dir / phantom_dir / output_root | plain strings, same as `tui_run.py`'s Paths section | |
| Dry run | not a `RunSample` field — a second submit button (**Dry Run**, alongside **Run Pipeline**), same as `tui_run.py`'s Run/Dry-run buttons | sets `dry_run=True` on the sim call only; stages 2-3 never run either way once stage 1 reports `record.status != "ok"` |

**Grain-count guardrail (per-sphere path only):** this path is per-sphere
(`DEMGrainsBlenderEarthCam.py`), and per this repo's own convention (see
`CLAUDE.md`'s pipeline-comparison table) per-sphere is meant for ≤~2000
grains — composite/instancing exist precisely because per-sphere degrades
above that. A high `np_apophis` can still successfully simulate and convert,
then make the render stage impractically slow or exhaust GPU memory. The TUI
warns (non-blocking — this is meant to stay a "hero shot" tool, not enforce
a hard policy) when `np_apophis > 2000`: prepend `"Warning: np_apophis={n} — `
`per-sphere path is intended for ≤2000 grains; consider the composite or `
`instancing path instead. "` to the status message before running.

On submit:

```python
sample = RunSample(use_dem=..., np_apophis=..., ...)
base_setup, base_input, phantomsetup_bin, phantom_bin = preflight(
    argparse.Namespace(prefix=prefix, phantom_dir=phantom_dir, dry_run=dry_run),
    base_dir, output_root,
)
record = run_one_case(
    run_id=1,
    sample=sample,
    base_setup=base_setup,
    base_input=base_input,
    output_root=output_root,
    prefix=prefix,
    phantomsetup_bin=phantomsetup_bin,
    phantom_bin=phantom_bin,
    ref_mass_kg=None,
    dry_run=dry_run,
    earth_sink_id=earth_sink_id,
    apophis_sink_id=apophis_sink_id,
    ephemeris_cache_dir=ephemeris_cache_dir,
    shape_file=shape_file,
)
```

`record.status` is checked before proceeding: anything other than `"ok"`
(e.g. `"prepared_only"` for dry-run, or an error status) stops the pipeline
there and shows `record.error` in the status bar — component 2 never runs
against a failed or dry-run-only sim.

**Live progress:** `run_one_case()` runs `phantomsetup`/`phantom` as blocking
subprocesses internally (this is how `run_mass_sobol_phantom.py` already
works — it is not async). Run it in a worker thread via Textual's
`run_worker(..., thread=True)` so the UI stays responsive, and poll
`run_dir` for dump-file count growth to show a coarse progress line — do not
attempt to parse `phantom.log` for fine-grained progress; that is a much
larger feature and out of scope here.

## Component 2 — Convert (WSL, no form)

Runs automatically after a successful sim, no user input needed:

```python
from Analysis.run_demtocsv_batch import (
    run_dem_dump_convert,
    DEFAULT_DEM_DUMP_CONVERT,
    DEFAULT_BASE_OUT,
    _min_dem_grains_from_setup,
)

min_grains = _min_dem_grains_from_setup(Path(record.run_dir))
run_dem_dump_convert(
    input_dir=Path(record.run_dir),
    dump_convert_path=DEFAULT_DEM_DUMP_CONVERT,
    base_output_dir=DEFAULT_BASE_OUT,
    min_dem_grains=min_grains,
)
```

This writes into `DEMCSVs/<sim_name>/<run_name>_bodies_output/` and
`_grains_output/` under the same `/mnt/c/.../Code/DEMCSVs` path both repos
already share — `<sim_name>` is `output_root.name` (the timestamped batch
dir the TUI created), `<run_name>` is `run_0001`.

**Post-convert path wiring (feeds Component 3/5):** the TUI does not receive
these paths back from `run_dem_dump_convert()` (it has no return value) — it
re-derives them from the same naming rule `DEMDumpConvert.py` itself uses
(`CSVconvert/DEMDumpConvert.py:19-22`: `<sim_name>` = `INPUT_DIR`'s parent
folder name, `<run_name>` = `INPUT_DIR`'s own folder name):

```python
run_dir = Path(record.run_dir)          # output_root / "run_0001"
sim_name = output_root.name             # matches DEMDumpConvert.py's own derivation
run_name = run_dir.name                 # "run_0001"
grains_dir = DEFAULT_BASE_OUT / sim_name / f"{run_name}_grains_output"
bodies_dir = DEFAULT_BASE_OUT / sim_name / f"{run_name}_bodies_output"
```

**Render output directory convention:** not user-entered — derived the same
way, alongside the `_output` folders rather than inside either of them:

```python
output_dir = DEFAULT_BASE_OUT / sim_name / f"{run_name}_render"
```

i.e. `DEMCSVs/<sim_name>/run_0001_render/`, a sibling of
`run_0001_grains_output/` and `run_0001_bodies_output/`.

`run_dem_dump_convert()` calls `exec()` on `DEMDumpConvert.py` in-process
and lets it print/raise directly — wrap the call in `try/except Exception`
and surface the exception text in the TUI status bar; there is no structured
return value to check (this mirrors how `run_demtocsv_batch.py`'s own
`main()` already treats it — no exception handling there either, it just
lets a bad conversion crash the batch script, which is acceptable for a
single foreground run here too, caught only so the TUI doesn't hard-crash).

## Component 3 — Render config (TUI form)

New form fields, plain values (no Sobol/min-max semantics — this is a
render, not a simulation parameter):

| Field | Type | Default | Notes |
|---|---|---|---|
| Resolution | string `WxH` | `1920x1080` | parsed to `(int, int)`; reject non-matching input |
| Samples | int | `128` | Cycles `scene.cycles.samples` |
| FPS | int | `24` | `scene.render.fps` — metadata for later manual video assembly, does not affect which frames render |
| Max frames | int, optional | blank = all | clamps `scene.frame_end` for a quick preview render |
| Camera mode | Select: `(auto)` / `grain_only` | `(auto)` | passed straight through to `DEMGrainsBlenderEarthCam.py`'s existing `CAMERA_MODE` switch (line 97: `None`/`'earth_track'`/`'grain_only'`), which controls camera behavior only; `IMPORT_SOLAR_SYSTEM` (a separate switch controlling whether Earth/Sun/Moon are imported at all) is left at its own auto-detect and is not touched by this field |

## Component 4 — Headless render (`BlenderConvert/DEMHeadlessRender.py`, new)

Runs under `blender.exe --background --python DEMHeadlessRender.py -- <args>`
— the same headless-only convention as `P0_InstancingSpike.py` and
`viz/viz_preprocess_lite.py`. Not pasted into the Scripting tab.

**CLI arguments** (parsed from `sys.argv` after `--`, same pattern as
`viz/viz_preprocess_lite.py`):

```
--grains-dir PATH        (required) run_XXXX_grains_output/
--bodies-dir PATH        (required) run_XXXX_bodies_output/
--output-dir PATH        (required) where rendered PNGs land
--resolution WxH         (default 1920x1080)
--samples N              (default 128)
--fps N                  (default 24)
--max-frames N           (optional; default = full frame range)
--camera-mode MODE       ("auto" or "grain_only"; default "auto")
```

**Implementation:**

```python
import argparse, re, sys
from pathlib import Path
import bpy

def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--grains-dir", required=True)
    p.add_argument("--bodies-dir", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--camera-mode", choices=("auto", "grain_only"), default="auto")
    return p.parse_args(argv)

def _patch_and_exec(script_path: Path, grains_dir: str, bodies_dir: str, camera_mode: str):
    src = script_path.read_text(encoding="utf-8")
    # GRAINS_DIR / BODIES_CSV_DIR are multi-line parenthesized string literals
    # (see BlenderConvert/DEMGrainsBlenderEarthCam.py:21-28) — replace the
    # whole `NAME = ( ... )` block, not a single line, unlike the single-line
    # constants run_demtocsv_batch.py patches in DEMDumpConvert.py.
    src = re.sub(
        r"GRAINS_DIR\s*=\s*\([^)]*\)",
        f"GRAINS_DIR = {grains_dir!r}",
        src, count=1,
    )
    src = re.sub(
        r"BODIES_CSV_DIR\s*=\s*\([^)]*\)",
        f"BODIES_CSV_DIR = {bodies_dir!r}",
        src, count=1,
    )
    if camera_mode == "grain_only":
        # CAMERA_MODE (line ~97) is a separate single-line switch from
        # IMPORT_SOLAR_SYSTEM — it forces the camera behavior, not whether
        # solar-system bodies are imported. Leave IMPORT_SOLAR_SYSTEM alone.
        src = re.sub(
            r"CAMERA_MODE\s*=\s*None",
            "CAMERA_MODE = 'grain_only'",
            src, count=1,
        )
    exec(compile(src, str(script_path), "exec"), {"__name__": "__main__"})

def main():
    args = _parse_args()
    m = re.match(r"^(\d+)x(\d+)$", args.resolution)
    if not m:
        raise ValueError(f"--resolution must be WxH (got {args.resolution!r})")
    res_x, res_y = int(m.group(1)), int(m.group(2))

    script_path = Path(__file__).parent / "DEMGrainsBlenderEarthCam.py"
    grains_dir = str(Path(args.grains_dir).resolve()).replace("\\", "/") + "/"
    bodies_dir = str(Path(args.bodies_dir).resolve()).replace("\\", "/") + "/"
    _patch_and_exec(script_path, grains_dir, bodies_dir, args.camera_mode)

    scene = bpy.context.scene
    if args.max_frames is not None:
        scene.frame_end = min(scene.frame_end, scene.frame_start + args.max_frames - 1)

    scene.render.engine = 'CYCLES'
    scene.cycles.samples = args.samples
    scene.cycles.device = 'GPU'
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.fps = args.fps

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.media_type = 'IMAGE'
    scene.render.filepath = str(out_dir) + "/frame_"

    print(f"[DEMHeadlessRender] Rendering frames {scene.frame_start}-{scene.frame_end} "
          f"at {res_x}x{res_y}, {args.samples} samples, to {out_dir}")
    bpy.ops.render.render(animation=True)
    print(f"[DEMHeadlessRender] Done — {scene.frame_end - scene.frame_start + 1} frame(s) "
          f"written to {out_dir}")

if __name__ == "__main__":
    main()
```

Notes on choices baked into the code above, so they don't get silently
"simplified away" during implementation:

- The `[^)]*` in both `re.sub` patterns is safe only because neither string
  literal contains a `)` character (true today — both are plain filesystem
  paths). If a future path legitimately contained one, this regex would
  need tightening; not a concern for current data.
- `scene.cycles.device = 'GPU'` follows the `P0_InstancingSpike.py` gotcha
  (**A new scene defaults to CPU**) defensively — the `--background` startup
  scene's actual default is unconfirmed, so setting it explicitly costs
  nothing and avoids silently benchmarking/rendering on CPU.
- `media_type = 'IMAGE'` is set explicitly per the version gotcha already
  documented in this repo's `CLAUDE.md` (`file_format` enum is filtered by
  `media_type`) — irrelevant today since this script never touches `VIDEO`
  mode, but cheap insurance against Blender's scene-default `media_type`
  having been left on `VIDEO` by a previous interactive session that saved
  over the startup file.
- `scene.render.filepath` ending in `frame_` (no digits) lets Blender's own
  `#`-padding auto-append the frame number — standard Blender convention,
  not spelled out further here.

## Path translation (WSL ↔ Windows)

Both repos already share `DEMCSVs/` at
`/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs`
(WSL) / `C:/Users/.../Code/DEMCSVs` (Windows) — same bytes on disk, WSL's
`/mnt/c/` mount is the only difference. `tui_sim_render.py` needs one small
helper to turn its WSL-side `Path` into the string Windows's `blender.exe`
expects:

```python
def to_windows_path(p: Path) -> str:
    s = str(p.resolve())
    if s.startswith("/mnt/") and len(s) > 6 and s[5] == "/":
        drive = s[5].upper()
        return f"{drive}:{s[6:]}"
    return s  # already a Windows-style path (e.g. passed in directly)
```

(This is deliberately simpler than shelling out to `wslpath -w` — no
subprocess round-trip needed for a mount that's always `/mnt/<letter>/...`
in this environment.)

## Component 5 — Invoking Blender from the TUI

```python
BLENDER_EXE = "/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"
DEM_HEADLESS_RENDER = to_windows_path(_REPO_WIN_CODE / "BlenderConvert" / "DEMHeadlessRender.py")

cmd = [
    BLENDER_EXE, "--background", "--python", DEM_HEADLESS_RENDER, "--",
    "--grains-dir", to_windows_path(grains_dir),
    "--bodies-dir", to_windows_path(bodies_dir),
    "--output-dir", to_windows_path(output_dir),
    "--resolution", resolution_str,
    "--samples", str(samples),
    "--fps", str(fps),
    "--camera-mode", camera_mode,
]
if max_frames is not None:
    cmd += ["--max-frames", str(max_frames)]

result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    # Blender's own print() progress lines (including everything
    # DEMGrainsBlenderEarthCam.py prints while exec()'d) go to stdout;
    # an uncaught Python exception's traceback goes to stderr. A failure
    # can show up in either stream, so combine both before taking the
    # tail rather than reading stderr alone.
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    tail = "\n".join(combined.splitlines()[-40:])
    # ... surface `tail` in the status bar
```

`_REPO_WIN_CODE` is a new constant at the top of `tui_sim_render.py`:
the Windows-side Code repo root, `Path("/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code")`
— hardcoded the same way `DEFAULT_DEM_DUMP_CONVERT`/`DEFAULT_BASE_OUT` are
already hardcoded in `run_demtocsv_batch.py`, not derived.

Run this subprocess in the same worker thread as the sim (component 1),
sequenced after components 1-2 succeed, so the TUI event loop is never
blocked.

## Error handling summary

| Stage | Failure mode | Behavior |
|---|---|---|
| Sim | `record.status != "ok"` | Stop; show `record.error` (or "dry run — nothing to convert" for `prepared_only`); components 2-3 never start |
| Convert | `run_dem_dump_convert()` raises | Stop; show exception text; render never starts |
| Render | `blender.exe` exits non-zero | Show last ~40 lines of combined stdout+stderr (Blender's own print output and a Python traceback can land in either stream); output dir is left as-is (partial frames, if any) for inspection |
| Render | `blender.exe` not found at `BLENDER_EXE` | Fail fast before running the sim at all — checked once at TUI startup, same spirit as `tui_run.py`'s import-time textual check |

## Verification plan (before wiring the full TUI)

1. **`DEMHeadlessRender.py` smoke test**, standalone, against an existing
   converted run (`torque_align_obj/run_0001`, already on disk from prior
   sessions):
   ```
   & "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
     --background --python BlenderConvert\DEMHeadlessRender.py -- `
     --grains-dir DEMCSVs\torque_align_obj\run_0001_grains_output `
     --bodies-dir DEMCSVs\torque_align_obj\run_0001_bodies_output `
     --output-dir DEMCSVs\torque_align_obj\_headless_render_smoketest `
     --resolution 960x540 --samples 16 --max-frames 3
   ```
   Confirms: patched constants take effect, 3 PNGs are written, exit code 0.
2. **End-to-end dry-run**: launch `tui_sim_render.py`, fill the sim form,
   tick "dry run" — confirms component 1 stops cleanly at `prepared_only`
   without attempting convert/render.
3. **End-to-end real run**: a short `tmax_hours`/coarse `dtmax_hours`
   real PHANTOM run (few dumps) through all three stages, confirming the
   reported output dir actually contains the expected PNG count.

## Extension points (not built now, but not blocked by this design)

- Composite/instancing render paths: component 3's form gains a path
  selector; component 4 gains sibling scripts (`DEMHeadlessRenderComposite.py`
  etc.) or a `--viz-mode` flag, each still following the same
  patch-and-exec-or-manifest convention already established per path.
- Video encode: an optional post-render step reusing the VSE→FFmpeg pattern
  already documented in this repo's `CLAUDE.md`, gated by a checkbox.
- Batch/queue: component 1's form becomes repeatable, looping components
  1-4 per queued sample — the per-run functions here already take explicit
  `run_id`/paths, so nothing here assumes single-run.
- Render progress streaming: `run_render_stage()` currently blocks on
  `subprocess.run(capture_output=True)`, so the TUI shows nothing until
  Blender exits. A future version could `Popen` + stream stdout line-by-line
  into a log widget for long renders.
- Mid-pipeline cancel: not supported in v1 (accepted for a single-run
  foreground tool) — a future version would need to track and terminate the
  `phantom`/`blender.exe` child process on a Cancel button.
- "Skip sim, render existing run" mode: point the render stage directly at
  an existing `run_XXXX_grains_output/`/`_bodies_output/` pair, skipping
  components 1-2 entirely — useful for iterating on render settings without
  re-running PHANTOM each time.
