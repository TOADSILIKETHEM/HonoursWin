# TUI Bulk Render Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let one `sobol/tui_sim_render.py` launch render the same simulated run through any combination of four paths — per-sphere, composite (D3), GN-instanced real grains, and a static shape-model placeholder cloud.

**Architecture:** `BlenderConvert/DEMHeadlessRender.py` gains `--viz-path per_sphere|composite|instance` + `--manifest`; each path text-patches its own Blender script's config constants and `exec`s it, then the existing shared render tail runs. A new numpy-only `viz/viz_preprocess_grains_instance.py` writes per-frame instance point files from grain npz. The TUI replaces its single render call with a loop over a `RENDER_PATHS` registry: per path, optional preprocess subprocess (Windows `.venv` python or `blender.exe`) then headless render, with per-path results and partial-failure reporting.

**Tech Stack:** Python 3 (WSL), Textual 8.2.6, pytest (no pytest-asyncio — Pilot tests use `asyncio.run`), numpy, Blender 5.2.1 LTS headless (`--background --python`), WSL `/mnt/c` interop.

**Spec:** `docs/superpowers/specs/2026-09-15-tui-bulk-render-paths-design.md` (Windows `Code/` repo). Builds on v1 spec `docs/superpowers/specs/2026-09-14-sim-render-pipeline-tui-design.md`.

## Global Constraints

- Two git repos, both on branch `feature/sim-render-pipeline-tui` — continue on it in both:
  - Windows `C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code` (WSL view `/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code`) — `BlenderConvert/`, `viz/`.
  - WSL `/home/mboyle/Honours/sobol` — `tui_sim_render.py`, `tests/`.
- **Never modify, stage, stash or revert the user's uncommitted WIP:** WSL `Analysis/run_demtocsv_batch.py`, `CLAUDE.md`, `campaigns/*.md`, `run_torque_align_blender_reruns.py`, `staging_*`, untracked `tests/test_dem_headless_*.py`; Windows `BlenderConvert/DEMBulkVizBlender.py` (whole file) and `BlenderConvert/DEMBulkInstanceBlender.py` (its `VIZ_MANIFEST` line). Always `git add <explicit paths>`, never `git add -A` / `.`.
- `BlenderConvert/DEMBulkInstanceBlender.py` carries user WIP, so Task 4's change to it is **left uncommitted** — report that to the controller; do not commit that file.
- `docs/` in `Code/` is not git-tracked (deny-all `.gitignore`); Windows `CLAUDE.md` is gitignored; WSL `sobol/CLAUDE.md` has user WIP — doc edits in Task 7 are left uncommitted.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
  ```
- Blender exe (WSL view): `/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe`. Windows `blender.exe` cannot open `/mnt/c/...` paths — every path argument handed to a Windows process is converted with `tsr.to_windows_path()` (`C:/...`).
- Windows venv python (WSL view): `/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/.venv/Scripts/python.exe` (has numpy, scipy 1.17.1, scikit-image).
- Blender `--background --python` exits 0 on an uncaught exception; `DEMHeadlessRender.py`'s `__main__` try/except → `sys.exit(1)` must stay.
- `DEMGrainsBlenderEarthCam.py` / bulk scripts load `.blend` libraries, which changes Blender's cwd — resolve every path to absolute **before** `exec`.
- Path ids, fixed order: `per_sphere`, `composite`, `instance_grains`, `instance_static`.
- Output dirs under `Code/DEMCSVs/<batch>/`: `run_0001_viz/` (composite), `run_0001_viz_instance/` (instance_grains), `run_0001_viz_instance_static/` (instance_static), `run_0001_render_<path id>/` (renders). The v1 `run_0001_render/` becomes `run_0001_render_per_sphere/`.
- Plan ruling (spec said "one line per path"): the TUI status bar is 3 text lines tall, so the final summary joins per-path entries with `"; "` on one line; `PipelineResult.paths` keeps the structured per-path list.
- Test commands (WSL): `cd /home/mboyle/Honours/sobol && python3 -m pytest <file> -v`. From Windows PowerShell wrap as `wsl.exe -e bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest <file> -v"`.
- Blender integration tests skip when `blender.exe` or `/mnt/c/Users/22boy/AppData/Local/Temp` is missing, and write scratch output only under that Windows Temp dir.
- Read-only fixture run (4 frames, np500): `Code/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/` with `run_0001_grains_output/` (npz), `run_0001_bodies_output/` (csv), `run_0001_viz/` (existing composite manifest + `envelopes/000NN_f0.npz`). Never write into it.

---

### Task 1: Risk probe — do bulk frame handlers fire during a headless animation render?

Throwaway verification; **no commit, no repo files changed.** Everything after this task assumes the answer is yes.

**Files:**
- Create (scratch, Windows Temp): `C:/Users/22boy/AppData/Local/Temp/probe_composite_handler.py`

**Interfaces:**
- Consumes: nothing.
- Produces: a yes/no finding reported to the controller.

- [ ] **Step 1: Write the probe script**

Write this to `/mnt/c/Users/22boy/AppData/Local/Temp/probe_composite_handler.py`:

```python
import json, re, sys, traceback
from pathlib import Path

CODE = "C:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code"
RUN = CODE + "/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg"
MANIFEST = RUN + "/run_0001_viz/manifest.json"
OUT = Path("C:/Users/22boy/AppData/Local/Temp/probe_composite_out")
RESULT = Path("C:/Users/22boy/AppData/Local/Temp/probe_composite_result.json")

import bpy
import numpy as np

records = []

def _record(scene, *_args):
    obj = bpy.data.objects.get("VizFragment_00")
    if obj is None:
        return
    n = len(obj.data.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", co)
    records.append({"frame": scene.frame_current, "n": n,
                    "mean": co.reshape(-1, 3).mean(axis=0).tolist()})

try:
    script = Path(CODE + "/BlenderConvert/DEMBulkVizBlender.py")
    src = script.read_text(encoding="utf-8")
    src, n = re.subn(r"(?m)^VIZ_MANIFEST\s*=\s*\([^)]*\)", lambda m: f"VIZ_MANIFEST = {MANIFEST!r}", src)
    assert n == 1, n
    OUT.mkdir(parents=True, exist_ok=True)
    exec(compile(src, str(script), "exec"), {"__name__": "__main__", "__file__": str(script)})
    scene = bpy.context.scene
    scene.frame_end = scene.frame_start + 3
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.render.resolution_x, scene.render.resolution_y = 64, 36
    scene.render.use_lock_interface = True
    scene.render.image_settings.media_type = "IMAGE"
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(OUT) + "/frame_"
    bpy.app.handlers.render_post.append(_record)
    bpy.ops.render.render(animation=True)
    RESULT.write_text(json.dumps(records), encoding="utf-8")
except Exception:
    traceback.print_exc()
    sys.exit(1)
```

- [ ] **Step 2: Run it**

Run (WSL):
```bash
"/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe" --background \
  --python "C:/Users/22boy/AppData/Local/Temp/probe_composite_handler.py"; echo "exit=$?"
```
Expected: `exit=0`, 4 PNGs in `probe_composite_out/`, and `probe_composite_result.json` with 4 records (frames 1–4).

- [ ] **Step 3: Compare recorded meshes with the envelope files**

Run (WSL):
```bash
python3 - <<'EOF'
import json, numpy as np
run = "/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001_viz"
recs = json.load(open("/mnt/c/Users/22boy/AppData/Local/Temp/probe_composite_result.json"))
fids = json.load(open(run + "/manifest.json"))["frame_ids"]
for i, r in enumerate(recs):
    v = np.load(f"{run}/envelopes/{fids[i]}_f0.npz")["verts"].astype(np.float32)
    print(r["frame"], r["n"], len(v), np.allclose(r["mean"], v.mean(axis=0), atol=1e-3))
exp = [np.load(f"{run}/envelopes/{f}_f0.npz")["verts"].mean(axis=0) for f in fids[:4]]
print("fixture frames differ:", not np.allclose(exp[0], exp[3], atol=1e-4))
EOF
```
Expected: four lines each ending `True`, and `fixture frames differ: True`.

- [ ] **Step 4: Decide and report**

- **All four `True`:** handlers fire per rendered frame. Report "PASS" with the printed output. Continue to Task 2.
- **Any `False` (every frame shows frame-0 geometry, or wrong frame):** STOP. Report "FAIL" with the output. Do not start Task 2. The contingency (for the controller to rule on) is replacing `bpy.ops.render.render(animation=True)` in `DEMHeadlessRender.py` with an explicit loop: `for f in range(frame_start, frame_end + 1): scene.frame_set(f); scene.render.filepath = f"{out_dir}/frame_{f:04d}.png"; bpy.ops.render.render(write_still=True)`.
- If `fixture frames differ: False`, report that the fixture cannot distinguish frames and stop for a ruling.

- [ ] **Step 5: Clean up scratch**

```bash
rm -rf /mnt/c/Users/22boy/AppData/Local/Temp/probe_composite_out \
       /mnt/c/Users/22boy/AppData/Local/Temp/probe_composite_handler.py \
       /mnt/c/Users/22boy/AppData/Local/Temp/probe_composite_result.json
```

---

### Task 2: `DEMHeadlessRender.py` — `--viz-path` contract, patch table, composite integration

**Files:**
- Modify: `Code/BlenderConvert/DEMHeadlessRender.py` (docstring lines 1–22; add constants after line 39; replace `_parse_args` lines 193–206, `_patch_and_exec` lines 209–230, `main` lines 233–282)
- Test (create): `/home/mboyle/Honours/sobol/tests/test_dem_headless_paths.py`

**Interfaces:**
- Consumes: Task 1 PASS.
- Produces (used by Task 4 tests and Task 5 commands):
  - CLI: `--viz-path {per_sphere,composite,instance}` (default `per_sphere`), `--manifest PATH`; `--grains-dir` / `--bodies-dir` required only for `per_sphere`.
  - `VIZ_PATHS: tuple[str, ...] = ("per_sphere", "composite", "instance")`
  - `SCRIPT_FOR_VIZ_PATH: dict[str, str]`
  - `validate_args(args: argparse.Namespace) -> None` (raises `ValueError`)
  - `parse_resolution(text: str) -> tuple[int, int]` (raises `ValueError`)
  - `patch_script_source(viz_path: str, src: str, *, grains_dir: str | None = None, bodies_dir: str | None = None, manifest: str | None = None, camera_mode: str = "auto", resolution: tuple[int, int] | None = None) -> str` (raises `RuntimeError` when a pattern does not match exactly once)
  - `ensure_procedural_rock_material(blend_path=None) -> None`
  - Bulk scripts exec'd with `__file__` set; `scene.render.use_lock_interface = True` for non-per_sphere paths.

- [ ] **Step 1: Write the failing unit tests**

Create `/home/mboyle/Honours/sobol/tests/test_dem_headless_paths.py`:

```python
"""--viz-path contract for DEMHeadlessRender.py (TUI bulk render paths)."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

CODE = Path("/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code")
CODE_WIN = "C:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code"
BLENDERCONVERT = CODE / "BlenderConvert"
BLENDER_EXE = Path("/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe")
WIN_TEMP = Path("/mnt/c/Users/22boy/AppData/Local/Temp")
WIN_TEMP_WIN = "C:/Users/22boy/AppData/Local/Temp"
FIXTURE_RUN = CODE / "DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg"
FIXTURE_RUN_WIN = CODE_WIN + "/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg"

sys.path.insert(0, str(BLENDERCONVERT))
import DEMHeadlessRender as dhr  # noqa: E402


def _parse(extra_argv):
    backup = sys.argv[:]
    try:
        sys.argv = ["blender", "--background", "--python", "DEMHeadlessRender.py", "--",
                    "--output-dir", "/o"] + extra_argv
        return dhr._parse_args()
    finally:
        sys.argv = backup


def _manifest(tmp_path, viz_mode):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps({"viz_mode": viz_mode}), encoding="utf-8")
    return p


def test_viz_path_defaults_to_per_sphere():
    args = _parse(["--grains-dir", "/g", "--bodies-dir", "/b"])
    assert args.viz_path == "per_sphere"
    assert args.manifest is None


def test_per_sphere_requires_grains_and_bodies():
    with pytest.raises(ValueError, match="--grains-dir"):
        _parse(["--bodies-dir", "/b"])


def test_composite_requires_manifest():
    with pytest.raises(ValueError, match="--manifest"):
        _parse(["--viz-path", "composite"])


def test_manifest_must_exist(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        _parse(["--viz-path", "instance", "--manifest", str(tmp_path / "nope.json")])


def test_viz_mode_mismatch_rejected(tmp_path):
    m = _manifest(tmp_path, "instance")
    with pytest.raises(ValueError, match="viz_mode"):
        _parse(["--viz-path", "composite", "--manifest", str(m)])


def test_composite_with_matching_manifest_parses(tmp_path):
    m = _manifest(tmp_path, "composite")
    args = _parse(["--viz-path", "composite", "--manifest", str(m)])
    assert args.viz_path == "composite"
    assert args.grains_dir is None


def test_parse_resolution():
    assert dhr.parse_resolution("640x360") == (640, 360)
    with pytest.raises(ValueError):
        dhr.parse_resolution("640by360")


def _real_src(viz_path):
    return (BLENDERCONVERT / dhr.SCRIPT_FOR_VIZ_PATH[viz_path]).read_text(encoding="utf-8")


def test_patch_per_sphere_real_script():
    out = dhr.patch_script_source(
        "per_sphere", _real_src("per_sphere"),
        grains_dir="C:/g/", bodies_dir="C:/b/", camera_mode="grain_only",
    )
    assert "GRAINS_DIR = 'C:/g/'" in out
    assert "BODIES_CSV_DIR = 'C:/b/'" in out
    assert "CAMERA_MODE = 'grain_only'" in out


def test_patch_composite_real_script():
    out = dhr.patch_script_source(
        "composite", _real_src("composite"),
        manifest="C:/run_0001_viz/manifest.json", camera_mode="grain_only",
    )
    assert "VIZ_MANIFEST = 'C:/run_0001_viz/manifest.json'" in out
    assert "CAMERA_MODE = 'grain_only'" in out


def test_patch_instance_real_script():
    out = dhr.patch_script_source(
        "instance", _real_src("instance"),
        manifest="C:/v/manifest.json", camera_mode="auto", resolution=(640, 360),
    )
    assert "VIZ_MANIFEST = 'C:/v/manifest.json'" in out
    assert "\nSLOWMO_FACTOR = 1\n" in out
    assert "RENDER_RESOLUTION = (640, 360)" in out
    assert "CAMERA_MODE = None" in out  # auto leaves it untouched


def test_patch_windows_backslashes_are_literal():
    out = dhr.patch_script_source(
        "composite", "VIZ_MANIFEST = (\n    'x'\n)\nCAMERA_MODE = None\n",
        manifest="C:\\new\\manifest.json",
    )
    assert "VIZ_MANIFEST = 'C:\\\\new\\\\manifest.json'" in out


def test_patch_raises_when_pattern_missing():
    with pytest.raises(RuntimeError, match="VIZ_MANIFEST"):
        dhr.patch_script_source("composite", "CAMERA_MODE = None\n", manifest="C:/m.json")


def test_patch_raises_when_pattern_duplicated():
    src = "VIZ_MANIFEST = ('a')\nVIZ_MANIFEST = ('b')\nCAMERA_MODE = None\n"
    with pytest.raises(RuntimeError, match="2"):
        dhr.patch_script_source("composite", src, manifest="C:/m.json")


def test_ensure_procedural_rock_material_requires_bpy():
    assert dhr.bpy is None
    with pytest.raises(RuntimeError, match="bpy"):
        dhr.ensure_procedural_rock_material()


_RECORDER = '''
import json, sys, traceback
sys.path.insert(0, {bc!r})
import bpy
import numpy as np
import DEMHeadlessRender as dhr
records = []
def _record(scene, *_a):
    obj = bpy.data.objects.get({obj!r})
    if obj is None:
        return
    mesh = obj.data
    n = len(mesh.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", co)
    rec = {{"frame": scene.frame_current, "n": n, "mean": co.reshape(-1, 3).mean(axis=0).tolist()}}
    if "radius" in mesh.attributes:
        r = np.empty(n, dtype=np.float32)
        mesh.attributes["radius"].data.foreach_get("value", r)
        rec["radius_sum"] = float(r.sum())
    records.append(rec)
bpy.app.handlers.render_post.append(_record)
try:
    dhr.main()
except Exception:
    traceback.print_exc()
    sys.exit(1)
finally:
    open({out!r}, "w").write(json.dumps(records))
'''


def run_recorded_render(name, obj_name, dhr_args):
    """Run DEMHeadlessRender.main() under blender with a render_post recorder.
    Returns (CompletedProcess, records list, output dir WSL Path). Shared with Task 4."""
    out_dir = WIN_TEMP / f"dhr_{name}_out"
    if out_dir.exists():
        for f in out_dir.glob("*"):
            f.unlink()
    rec_path_win = f"{WIN_TEMP_WIN}/dhr_{name}_records.json"
    script = WIN_TEMP / f"dhr_{name}_recorder.py"
    script.write_text(
        _RECORDER.format(bc=CODE_WIN + "/BlenderConvert", obj=obj_name, out=rec_path_win),
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(BLENDER_EXE), "--background", "--python", f"{WIN_TEMP_WIN}/dhr_{name}_recorder.py", "--",
         "--output-dir", f"{WIN_TEMP_WIN}/dhr_{name}_out",
         "--resolution", "160x90", "--samples", "1"] + dhr_args,
        capture_output=True, text=True, check=False,
    )
    rec_file = WIN_TEMP / f"dhr_{name}_records.json"
    records = json.loads(rec_file.read_text()) if rec_file.is_file() else []
    return result, records, out_dir


@pytest.mark.skipif(not BLENDER_EXE.is_file(), reason="blender.exe not installed")
@pytest.mark.skipif(not WIN_TEMP.is_dir(), reason="Windows Temp not mounted")
def test_blender_composite_renders_each_envelope_frame():
    viz = FIXTURE_RUN / "run_0001_viz"
    fids = json.loads((viz / "manifest.json").read_text())["frame_ids"][:4]
    expected = [np.load(viz / "envelopes" / f"{fid}_f0.npz")["verts"].astype(np.float32).mean(axis=0)
                for fid in fids]
    assert not np.allclose(expected[0], expected[3], atol=1e-4), "fixture frames identical"

    result, records, out_dir = run_recorded_render(
        "composite", "VizFragment_00",
        ["--viz-path", "composite", "--manifest", FIXTURE_RUN_WIN + "/run_0001_viz/manifest.json",
         "--max-frames", "4"],
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, combined[-3000:]
    assert len(list(out_dir.glob("frame_*.png"))) == 4
    assert len(records) == 4
    for i, rec in enumerate(records):
        assert np.allclose(rec["mean"], expected[i], atol=1e-3), (i, rec, expected[i])
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_dem_headless_paths.py -v -k "not blender"`
Expected: FAIL — e.g. `AttributeError: module 'DEMHeadlessRender' has no attribute 'SCRIPT_FOR_VIZ_PATH'` and `_parse_args` rejecting missing `--grains-dir` via argparse `SystemExit`.

- [ ] **Step 3: Implement**

In `Code/BlenderConvert/DEMHeadlessRender.py`:

(a) Replace the module docstring and the stdlib imports (lines 1–27, up to but not including `try:` / `import bpy`) with:

```python
"""Headless DEM render (per-sphere, composite, or instance) — not pasted into the Scripting tab.

Run with:
    blender.exe --background --python BlenderConvert/DEMHeadlessRender.py -- \\
        --output-dir PATH \\
        [--viz-path per_sphere|composite|instance] \\
        [--grains-dir PATH --bodies-dir PATH]      (per_sphere) \\
        [--manifest PATH/manifest.json]            (composite / instance) \\
        [--resolution 1920x1080] [--samples 500] [--fps 24] \\
        [--max-frames N] [--camera-mode auto|grain_only] \\
        [--encode-video] [--video-fps N]

Text-patches the chosen Blender script's config constants and exec()s it —
the same technique sobol/Analysis/run_demtocsv_batch.py uses on
DEMDumpConvert.py:
  per_sphere -> DEMGrainsBlenderEarthCam.py  (GRAINS_DIR, BODIES_CSV_DIR, CAMERA_MODE)
  composite  -> DEMBulkVizBlender.py         (VIZ_MANIFEST, CAMERA_MODE)
  instance   -> DEMBulkInstanceBlender.py    (VIZ_MANIFEST, CAMERA_MODE,
                                              SLOWMO_FACTOR=1, RENDER_RESOLUTION)
Then applies World "Deep Dark Space with Stars.001" (same HDRI as
Apophisonly.blend), sets Cycles to OPTIX (else CUDA) GPU-only, and renders.

With --encode-video, the just-rendered frame_*.png sequence is combined
into an MP4 (H264) via Blender's own VSE-scripted ffmpeg (no separate
ffmpeg install needed/expected on this machine) — an optional final
stage, off by default so re-encoding isn't forced on every tuning pass.
"""
import argparse
import json
import re
import sys
import traceback
from pathlib import Path
```

(keep the existing `try: import bpy / except ImportError: bpy = None` block and the World / GPU / `encode_video` functions unchanged).

(b) After the `_HDRI_RELATIVE = Path(...)` block (line 39), add:

```python
VIZ_PATHS = ("per_sphere", "composite", "instance")
SCRIPT_FOR_VIZ_PATH = {
    "per_sphere": "DEMGrainsBlenderEarthCam.py",
    "composite": "DEMBulkVizBlender.py",
    "instance": "DEMBulkInstanceBlender.py",
}
# Same file and material name as DEMGrainsBlenderEarthCam.py's
# ROCK_MATERIAL_BLEND_PATH / ROCK_MATERIAL_NAME. DEMBulkInstanceBlender.py
# refuses to run without this material and deliberately never auto-appends
# it (several similarly named rock materials exist), so the headless wrapper
# appends it from this one known source before exec.
ROCK_MATERIAL_NAME = "Procedural rock"
_ROCK_MATERIAL_BLEND_RELATIVE = Path("Blenders/11.blend")

# All patterned constants sit at column 0 in their scripts, exactly once.
_GRAINS_DIR_RE = r"(?m)^GRAINS_DIR\s*=\s*\([^)]*\)"
_BODIES_CSV_DIR_RE = r"(?m)^BODIES_CSV_DIR\s*=\s*\([^)]*\)"
_VIZ_MANIFEST_RE = r"(?m)^VIZ_MANIFEST\s*=\s*\([^)]*\)"
_CAMERA_MODE_RE = r"(?m)^CAMERA_MODE\s*=\s*None\b"
_SLOWMO_FACTOR_RE = r"(?m)^SLOWMO_FACTOR\s*=\s*\d+"
_RENDER_RESOLUTION_RE = r"(?m)^RENDER_RESOLUTION\s*=\s*\([^)]*\)"
```

(c) Replace `_parse_args` and `_patch_and_exec` (lines 193–230) with:

```python
def validate_args(args) -> None:
    """Cross-flag rules argparse can't express. Raises ValueError."""
    if args.viz_path == "per_sphere":
        if not args.grains_dir or not args.bodies_dir:
            raise ValueError("--viz-path per_sphere requires --grains-dir and --bodies-dir")
        return
    if not args.manifest:
        raise ValueError(f"--viz-path {args.viz_path} requires --manifest")
    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        raise ValueError(f"--manifest not found: {manifest_path}")
    viz_mode = json.loads(manifest_path.read_text(encoding="utf-8")).get("viz_mode")
    if viz_mode != args.viz_path:
        raise ValueError(
            f"manifest viz_mode={viz_mode!r} does not match --viz-path {args.viz_path}"
        )


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--viz-path", choices=VIZ_PATHS, default="per_sphere")
    p.add_argument("--manifest", default=None)
    p.add_argument("--grains-dir", default=None)
    p.add_argument("--bodies-dir", default=None)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--samples", type=int, default=500)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--camera-mode", choices=("auto", "grain_only"), default="auto")
    p.add_argument("--encode-video", action="store_true", default=False)
    p.add_argument("--video-fps", type=int, default=None)
    args = p.parse_args(argv)
    validate_args(args)
    return args


def parse_resolution(text: str):
    m = re.match(r"^(\d+)x(\d+)$", text)
    if not m:
        raise ValueError(f"--resolution must be WxH (got {text!r})")
    return int(m.group(1)), int(m.group(2))


def _sub_exactly_once(pattern: str, replacement: str, src: str, label: str) -> str:
    n = len(re.findall(pattern, src))
    if n != 1:
        raise RuntimeError(f"{label} pattern matched {n} time(s), expected exactly 1")
    # A function replacement keeps backslashes in Windows paths literal.
    return re.sub(pattern, lambda _m: replacement, src)


def patch_script_source(viz_path, src, *, grains_dir=None, bodies_dir=None,
                        manifest=None, camera_mode="auto", resolution=None):
    """Return src with this path's config constants replaced. Pure — no bpy."""
    if viz_path == "per_sphere":
        src = _sub_exactly_once(_GRAINS_DIR_RE, f"GRAINS_DIR = {grains_dir!r}", src, "GRAINS_DIR")
        src = _sub_exactly_once(
            _BODIES_CSV_DIR_RE, f"BODIES_CSV_DIR = {bodies_dir!r}", src, "BODIES_CSV_DIR"
        )
    else:
        src = _sub_exactly_once(_VIZ_MANIFEST_RE, f"VIZ_MANIFEST = {manifest!r}", src, "VIZ_MANIFEST")
    if viz_path == "instance":
        # One timeline frame == one sim frame, so --max-frames and the TUI's
        # frame count stay correct.
        src = _sub_exactly_once(_SLOWMO_FACTOR_RE, "SLOWMO_FACTOR = 1", src, "SLOWMO_FACTOR")
        if resolution is not None:
            src = _sub_exactly_once(
                _RENDER_RESOLUTION_RE,
                f"RENDER_RESOLUTION = ({int(resolution[0])}, {int(resolution[1])})",
                src, "RENDER_RESOLUTION",
            )
    if camera_mode == "grain_only":
        # CAMERA_MODE is a separate switch from IMPORT_SOLAR_SYSTEM -- it
        # forces camera behavior, not whether solar-system bodies are imported.
        src = _sub_exactly_once(_CAMERA_MODE_RE, "CAMERA_MODE = 'grain_only'", src, "CAMERA_MODE")
    return src


def ensure_procedural_rock_material(blend_path=None) -> None:
    """Append "Procedural rock" from Blenders/11.blend unless already present."""
    if bpy is None:
        raise RuntimeError("bpy is required to append the Procedural rock material")
    if bpy.data.materials.get(ROCK_MATERIAL_NAME) is not None:
        return
    path = (
        Path(blend_path) if blend_path is not None
        else Path(__file__).resolve().parent / _ROCK_MATERIAL_BLEND_RELATIVE
    )
    if not path.is_file():
        raise RuntimeError(f"{path} not found -- needed for {ROCK_MATERIAL_NAME!r} (instance path)")
    found = False
    with bpy.data.libraries.load(str(path).replace("\\", "/"), link=False) as (data_from, data_to):
        if ROCK_MATERIAL_NAME in data_from.materials:
            data_to.materials = [ROCK_MATERIAL_NAME]
            found = True
    if not found or bpy.data.materials.get(ROCK_MATERIAL_NAME) is None:
        raise RuntimeError(f"material {ROCK_MATERIAL_NAME!r} not found in {path}")
```

(d) Replace `main` (lines 233–282) with:

```python
def main() -> None:
    args = _parse_args()
    res_x, res_y = parse_resolution(args.resolution)
    script_dir = Path(__file__).resolve().parent
    script_path = script_dir / SCRIPT_FOR_VIZ_PATH[args.viz_path]

    # Resolve every path *before* exec'ing the DEM script: those scripts load
    # .blend libraries (TheEarth1.blend, 11.blend) via
    # bpy.data.libraries.load(..., link=False), which changes Blender's
    # process working directory. A relative path resolved after that silently
    # lands under the wrong directory -- confirmed live in v1: PNGs wrote to
    # "C:\DEMCSVs\..." until output-dir resolution was hoisted above exec.
    out_dir = Path(args.output_dir).resolve()
    patch_kwargs = {"camera_mode": args.camera_mode, "resolution": (res_x, res_y)}
    if args.viz_path == "per_sphere":
        patch_kwargs["grains_dir"] = str(Path(args.grains_dir).resolve()).replace("\\", "/") + "/"
        patch_kwargs["bodies_dir"] = str(Path(args.bodies_dir).resolve()).replace("\\", "/") + "/"
    else:
        patch_kwargs["manifest"] = str(Path(args.manifest).resolve()).replace("\\", "/")

    if args.viz_path == "instance":
        ensure_procedural_rock_material()

    src = patch_script_source(
        args.viz_path, script_path.read_text(encoding="utf-8"), **patch_kwargs
    )
    exec(compile(src, str(script_path), "exec"), {"__name__": "__main__", "__file__": str(script_path)})
    setup_deep_dark_space_world()

    scene = bpy.context.scene
    if args.max_frames is not None:
        scene.frame_end = min(scene.frame_end, scene.frame_start + args.max_frames - 1)

    setup_cycles_gpu(scene)
    scene.cycles.samples = args.samples
    scene.render.resolution_x = res_x
    scene.render.resolution_y = res_y
    scene.render.resolution_percentage = 100
    scene.render.fps = args.fps
    if args.viz_path != "per_sphere":
        # The bulk scripts' frame_change_pre handlers rewrite mesh data between
        # frames during the animation render; lock the interface so the render
        # never reads half-updated geometry.
        scene.render.use_lock_interface = True

    out_dir.mkdir(parents=True, exist_ok=True)
    scene.render.image_settings.media_type = 'IMAGE'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(out_dir) + "/frame_"

    print(
        f"[DEMHeadlessRender] Rendering {args.viz_path} frames {scene.frame_start}-{scene.frame_end} "
        f"at {res_x}x{res_y}, {args.samples} samples, GPU, to {out_dir}"
    )
    bpy.ops.render.render(animation=True)
    n_frames = scene.frame_end - scene.frame_start + 1
    print(f"[DEMHeadlessRender] Done — {n_frames} frame(s) written to {out_dir}")

    if args.encode_video:
        video_fps = args.video_fps if args.video_fps is not None else args.fps
        encode_video(out_dir, n_frames, video_fps)
```

Leave the `if __name__ == "__main__":` block (lines 285–302) unchanged.

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_dem_headless_paths.py -v -k "not blender"`
Expected: all non-Blender tests PASS.

- [ ] **Step 5: Run the composite Blender integration test**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_dem_headless_paths.py -v -k blender_composite`
Expected: PASS (takes a few minutes — `DEMBulkVizBlender.py` keyframes Earth/camera).

- [ ] **Step 6: Run the existing headless tests to verify no regression**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_dem_headless_video.py tests/test_dem_headless_world.py tests/test_dem_headless_gpu.py -v`
Expected: PASS (they are untracked user files — run them, do not modify or commit them).

- [ ] **Step 7: Commit (two repos)**

Windows (PowerShell, in `Code/`):
```powershell
git add BlenderConvert/DEMHeadlessRender.py
git commit -m @'
Add --viz-path composite/instance to headless DEM render

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
'@
```
WSL:
```bash
cd /home/mboyle/Honours/sobol && git add tests/test_dem_headless_paths.py && git commit -F - <<'EOF'
Test DEMHeadlessRender --viz-path contract and composite headless render

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
EOF
```

---

### Task 3: `viz/viz_preprocess_grains_instance.py` — real-grain instance writer

**Files:**
- Create: `Code/viz/viz_preprocess_grains_instance.py`
- Test (create): `/home/mboyle/Honours/sobol/tests/test_viz_preprocess_grains_instance.py`

**Interfaces:**
- Consumes: `viz.path_utils.manifest_relpath(target: Path, base: Path) -> str` (existing).
- Produces:
  - CLI `--grains-dir --bodies-dir --output-dir [--max-frames N] [--sim-name S] [--run-name R]`; exit 0 on success, 1 on error.
  - `build_grains_instance(grains_dir, bodies_dir, output_dir, *, max_frames=None, sim_name=None, run_name=None) -> Path` (manifest path)
  - `GrainCountMismatch(ValueError)`
  - `main(argv=None) -> int`
  - Output: `<output-dir>/points/{i:05d}.npz` (`pos` float32 (N,3), `radius` float32 (N,)), `<output-dir>/manifest.json` with keys `schema_version, viz_mode="instance", static=false, source="grains", sim_name, run_name, n_frames, frame_ids, points_dir="points", n_points, grain_radius_vis, bodies_csv_dir, bodies_start_index=0`.

- [ ] **Step 1: Write the failing tests**

Create `/home/mboyle/Honours/sobol/tests/test_viz_preprocess_grains_instance.py`:

```python
"""Real-grain instance writer (viz/viz_preprocess_grains_instance.py)."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

CODE = Path("/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code")
_spec = importlib.util.spec_from_file_location(
    "viz_preprocess_grains_instance", CODE / "viz" / "viz_preprocess_grains_instance.py"
)
vgi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vgi)


def _write_grain_npz(path: Path, grain_ids, offset=0.0):
    gid = np.asarray(grain_ids, dtype=np.int64)
    np.savez_compressed(
        path,
        grain_id=gid,
        x_vis=gid * 1.0 + offset,
        y_vis=gid * 2.0,
        z_vis=gid * 3.0,
        Reff_vis=0.5 + 0.1 * gid,
        time_s=np.float64(0.0),
    )


def _run_dirs(tmp_path):
    batch = tmp_path / "sim_x"
    grains = batch / "run_0001_grains_output"
    bodies = batch / "run_0001_bodies_output"
    out = batch / "run_0001_viz_instance"
    grains.mkdir(parents=True)
    bodies.mkdir(parents=True)
    return grains, bodies, out


def test_writes_points_sorted_by_grain_id(tmp_path):
    grains, bodies, out = _run_dirs(tmp_path)
    _write_grain_npz(grains / "sobol_00000.npz", [2, 0, 1], offset=0.0)
    _write_grain_npz(grains / "sobol_00001.npz", [1, 2, 0], offset=10.0)

    manifest_path = vgi.build_grains_instance(grains, bodies, out)

    f0 = np.load(out / "points" / "00000.npz")
    f1 = np.load(out / "points" / "00001.npz")
    assert f0["pos"].dtype == np.float32 and f0["pos"].shape == (3, 3)
    assert f0["radius"].dtype == np.float32 and f0["radius"].shape == (3,)
    assert np.allclose(f0["pos"][:, 0], [0.0, 1.0, 2.0])
    assert np.allclose(f1["pos"][:, 0], [10.0, 11.0, 12.0])
    assert np.allclose(f0["pos"][:, 2], [0.0, 3.0, 6.0])
    assert np.allclose(f0["radius"], [0.5, 0.6, 0.7])
    assert manifest_path == out / "manifest.json"


def test_manifest_contents(tmp_path):
    grains, bodies, out = _run_dirs(tmp_path)
    _write_grain_npz(grains / "sobol_00000.npz", [0, 1, 2])
    _write_grain_npz(grains / "sobol_00001.npz", [0, 1, 2])

    m = json.loads(vgi.build_grains_instance(grains, bodies, out).read_text())

    assert m["schema_version"] == 1
    assert m["viz_mode"] == "instance"
    assert m["static"] is False
    assert m["source"] == "grains"
    assert m["sim_name"] == "sim_x"
    assert m["run_name"] == "run_0001"
    assert m["n_frames"] == 2
    assert m["frame_ids"] == ["00000", "00001"]
    assert m["points_dir"] == "points"
    assert m["n_points"] == 3
    assert m["grain_radius_vis"] == pytest.approx(0.6)
    assert m["bodies_csv_dir"] == "../run_0001_bodies_output"
    assert m["bodies_start_index"] == 0
    for key in ("synthetic", "motion_model", "angles_rad"):
        assert key not in m


def test_max_frames_truncates(tmp_path):
    grains, bodies, out = _run_dirs(tmp_path)
    for i in range(4):
        _write_grain_npz(grains / f"sobol_{i:05d}.npz", [0, 1])

    m = json.loads(vgi.build_grains_instance(grains, bodies, out, max_frames=2).read_text())

    assert m["n_frames"] == 2
    assert sorted(p.name for p in (out / "points").glob("*.npz")) == ["00000.npz", "00001.npz"]


def test_grain_count_mismatch_exits_1_without_manifest(tmp_path, capsys):
    grains, bodies, out = _run_dirs(tmp_path)
    _write_grain_npz(grains / "sobol_00000.npz", [0, 1, 2])
    _write_grain_npz(grains / "sobol_00001.npz", [0, 1])

    rc = vgi.main(["--grains-dir", str(grains), "--bodies-dir", str(bodies), "--output-dir", str(out)])

    assert rc == 1
    assert "frame 00001 has 2 grains, frame 00000 has 3" in capsys.readouterr().err
    assert not (out / "manifest.json").exists()


def test_empty_grains_dir_exits_1(tmp_path, capsys):
    grains, bodies, out = _run_dirs(tmp_path)
    rc = vgi.main(["--grains-dir", str(grains), "--bodies-dir", str(bodies), "--output-dir", str(out)])
    assert rc == 1
    assert "No grain npz files" in capsys.readouterr().err


def test_main_success_returns_0(tmp_path):
    grains, bodies, out = _run_dirs(tmp_path)
    _write_grain_npz(grains / "sobol_00000.npz", [0, 1])
    rc = vgi.main(["--grains-dir", str(grains), "--bodies-dir", str(bodies), "--output-dir", str(out),
                   "--sim-name", "S", "--run-name", "R"])
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text())
    assert (m["sim_name"], m["run_name"]) == ("S", "R")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_viz_preprocess_grains_instance.py -v`
Expected: FAIL at collection — `FileNotFoundError` for `viz_preprocess_grains_instance.py`.

- [ ] **Step 3: Implement**

Create `Code/viz/viz_preprocess_grains_instance.py`:

```python
#!/usr/bin/env python3
"""Grain npz -> per-frame GN instance point files for the real simulated grains.

Feeds BlenderConvert/DEMBulkInstanceBlender.py a ``viz_mode: "instance"``,
``static: false`` manifest in which every point is one real DEM grain (the
TUI's ``instance_grains`` render path) -- unlike viz_preprocess_lite.py's
static shape-model placeholder or synthetic_flyby_test.py's rigid tumble.
numpy only, so it runs in the Windows .venv (or any plain Python).

    python viz/viz_preprocess_grains_instance.py \\
        --grains-dir DEMCSVs/<sim>/run_XXXX_grains_output \\
        --bodies-dir DEMCSVs/<sim>/run_XXXX_bodies_output \\
        --output-dir DEMCSVs/<sim>/run_XXXX_viz_instance [--max-frames N]
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from viz.path_utils import manifest_relpath  # noqa: E402


class GrainCountMismatch(ValueError):
    """A frame's grain count differs from frame 0 (instance meshes need a fixed count)."""


def build_grains_instance(
    grains_dir: Path,
    bodies_dir: Path,
    output_dir: Path,
    *,
    max_frames: int | None = None,
    sim_name: str | None = None,
    run_name: str | None = None,
) -> Path:
    grains_dir = Path(grains_dir).resolve()
    bodies_dir = Path(bodies_dir).resolve()
    output_dir = Path(output_dir).resolve()

    grain_files = sorted(glob.glob(str(grains_dir / "*.npz")))
    if not grain_files:
        raise FileNotFoundError(
            f"No grain npz files in {grains_dir} (CSV-era folder? re-run DEMDumpConvert.py)"
        )
    if max_frames is not None:
        grain_files = grain_files[:max_frames]

    if run_name is None:
        name = grains_dir.name
        run_name = name.replace("_grains_output", "") if name.endswith("_grains_output") else name
    if sim_name is None:
        sim_name = grains_dir.parent.name

    points_dir = output_dir / "points"
    points_dir.mkdir(parents=True, exist_ok=True)

    frame_ids: list[str] = []
    n0: int | None = None
    grain_radius_vis = 0.0
    for i, path in enumerate(grain_files):
        fid = f"{i:05d}"
        d = np.load(path)
        # Instance i must be the same grain in every frame, or the GN
        # per-instance random rotation jumps between grains and flickers.
        order = np.argsort(np.asarray(d["grain_id"]), kind="stable")
        pos = np.column_stack([d["x_vis"], d["y_vis"], d["z_vis"]])[order].astype(np.float32)
        radius = np.asarray(d["Reff_vis"])[order].astype(np.float32)
        if n0 is None:
            n0 = len(pos)
            grain_radius_vis = float(np.median(radius))
        elif len(pos) != n0:
            raise GrainCountMismatch(f"frame {fid} has {len(pos)} grains, frame 00000 has {n0}")
        np.savez_compressed(points_dir / f"{fid}.npz", pos=pos, radius=radius)
        frame_ids.append(fid)

    manifest = {
        "schema_version": 1,
        "viz_mode": "instance",
        "static": False,
        "source": "grains",
        "sim_name": sim_name,
        "run_name": run_name,
        "n_frames": len(frame_ids),
        "frame_ids": frame_ids,
        "points_dir": "points",
        "n_points": n0,
        "grain_radius_vis": grain_radius_vis,
        "bodies_csv_dir": manifest_relpath(bodies_dir, output_dir),
        "bodies_start_index": 0,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--grains-dir", type=Path, required=True)
    p.add_argument("--bodies-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--sim-name", type=str, default=None)
    p.add_argument("--run-name", type=str, default=None)
    args = p.parse_args(argv)
    try:
        manifest_path = build_grains_instance(
            args.grains_dir, args.bodies_dir, args.output_dir,
            max_frames=args.max_frames, sim_name=args.sim_name, run_name=args.run_name,
        )
    except (FileNotFoundError, GrainCountMismatch) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_viz_preprocess_grains_instance.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Smoke-run under the Windows venv on the fixture**

Run (WSL):
```bash
cd /mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code && \
.venv/Scripts/python.exe viz/viz_preprocess_grains_instance.py \
  --grains-dir "C:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001_grains_output" \
  --bodies-dir "C:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001_bodies_output" \
  --output-dir "C:/Users/22boy/AppData/Local/Temp/vgi_smoke" --max-frames 2; echo "exit=$?"
cat /mnt/c/Users/22boy/AppData/Local/Temp/vgi_smoke/manifest.json
rm -rf /mnt/c/Users/22boy/AppData/Local/Temp/vgi_smoke
```
Expected: `exit=0`, manifest with `"n_frames": 2`, `"n_points"` ≈ 500, a `bodies_csv_dir` that is a relative `../../...` path or absolute `C:/...` path.

- [ ] **Step 6: Commit (two repos)**

Windows (PowerShell, in `Code/`):
```powershell
git add viz/viz_preprocess_grains_instance.py
git commit -m @'
Add real-grain instance preprocess (per-frame pos + radius points)

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
'@
```
WSL:
```bash
cd /home/mboyle/Honours/sobol && git add tests/test_viz_preprocess_grains_instance.py && git commit -F - <<'EOF'
Test real-grain instance preprocess writer

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
EOF
```

---

### Task 4: Per-grain radius in `DEMBulkInstanceBlender.py` + instance_grains headless render

**Files:**
- Modify: `Code/BlenderConvert/DEMBulkInstanceBlender.py` — `_build_point_cloud` (lines 146–172) and the point-cloud block in `main()` (lines 300–307). **Do not touch lines 36–60 (config, user WIP).**
- Test (modify): `/home/mboyle/Honours/sobol/tests/test_dem_headless_paths.py` (append)

**Interfaces:**
- Consumes: Task 2 `run_recorded_render(name, obj_name, dhr_args)` test helper and `--viz-path instance`; Task 3 `build_grains_instance(...)` output layout.
- Produces: `_build_point_cloud(pos, grain_radius_vis, subdiv, radii=None)`; instance point object named `DEM_InstancePoints` whose `radius` attribute equals the points file's `radius` when present.

- [ ] **Step 1: Write the failing integration test**

Append to `/home/mboyle/Honours/sobol/tests/test_dem_headless_paths.py`:

```python
@pytest.mark.skipif(not BLENDER_EXE.is_file(), reason="blender.exe not installed")
@pytest.mark.skipif(not WIN_TEMP.is_dir(), reason="Windows Temp not mounted")
def test_blender_instance_grains_uses_per_grain_radius_and_moves():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "viz_preprocess_grains_instance", CODE / "viz" / "viz_preprocess_grains_instance.py"
    )
    vgi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vgi)

    viz_dir = WIN_TEMP / "dhr_instance_grains_viz"
    if viz_dir.exists():
        import shutil
        shutil.rmtree(viz_dir)
    vgi.build_grains_instance(
        FIXTURE_RUN / "run_0001_grains_output",
        FIXTURE_RUN / "run_0001_bodies_output",
        viz_dir,
        max_frames=2,
    )
    p0 = np.load(viz_dir / "points" / "00000.npz")
    p1 = np.load(viz_dir / "points" / "00001.npz")

    result, records, out_dir = run_recorded_render(
        "instance_grains", "DEM_InstancePoints",
        ["--viz-path", "instance", "--manifest", f"{WIN_TEMP_WIN}/dhr_instance_grains_viz/manifest.json",
         "--max-frames", "2"],
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, combined[-3000:]
    assert len(list(out_dir.glob("frame_*.png"))) == 2
    assert len(records) == 2
    assert records[0]["n"] == len(p0["pos"])
    assert records[0]["radius_sum"] == pytest.approx(float(p0["radius"].sum()), rel=1e-4)
    assert np.allclose(records[0]["mean"], p0["pos"].mean(axis=0), atol=1e-3)
    assert np.allclose(records[1]["mean"], p1["pos"].mean(axis=0), atol=1e-3)
```

The fixture may be monodisperse, in which case `radius_sum` equals `n * grain_radius_vis` either way — so also add this direct check, which fails today because `_build_point_cloud` has no `radii` parameter:

```python
@pytest.mark.skipif(not BLENDER_EXE.is_file(), reason="blender.exe not installed")
@pytest.mark.skipif(not WIN_TEMP.is_dir(), reason="Windows Temp not mounted")
def test_blender_build_point_cloud_writes_given_radii():
    script = WIN_TEMP / "dhr_radii_check.py"
    script.write_text(
        "\n".join([
            "import sys, traceback",
            f"sys.path.insert(0, {CODE_WIN + '/BlenderConvert'!r})",
            "import bpy, numpy as np",
            "import DEMHeadlessRender as dhr",
            "try:",
            "    dhr.ensure_procedural_rock_material()",
            "    import DEMBulkInstanceBlender as dbi",
            "    pos = np.zeros((3, 3), dtype=np.float32)",
            "    radii = np.array([0.1, 0.2, 0.3], dtype=np.float32)",
            "    obj, _g = dbi._build_point_cloud(pos, 9.9, 0, radii=radii)",
            "    r = np.empty(3, dtype=np.float32)",
            "    obj.data.attributes['radius'].data.foreach_get('value', r)",
            "    assert np.allclose(r, radii), r",
            "    obj2, _g2 = dbi._build_point_cloud(pos, 9.9, 0)",
            "    r2 = np.empty(3, dtype=np.float32)",
            "    obj2.data.attributes['radius'].data.foreach_get('value', r2)",
            "    assert np.allclose(r2, 9.9), r2",
            "    print('RADII_OK')",
            "except Exception:",
            "    traceback.print_exc()",
            "    sys.exit(1)",
        ]) + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [str(BLENDER_EXE), "--background", "--python", f"{WIN_TEMP_WIN}/dhr_radii_check.py"],
        capture_output=True, text=True, check=False,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    assert result.returncode == 0, combined[-3000:]
    assert "RADII_OK" in combined
```

Note: importing `DEMBulkInstanceBlender` as a module does not run `main()` (guarded by `__main__`); its module-level `VIZ_MANIFEST` is only read inside `main()`.

- [ ] **Step 2: Run to verify failure**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_dem_headless_paths.py -v -k "radii or instance_grains"`
Expected: `test_blender_build_point_cloud_writes_given_radii` FAILS with `TypeError: _build_point_cloud() got an unexpected keyword argument 'radii'`. `test_blender_instance_grains_uses_per_grain_radius_and_moves` may already pass on a monodisperse fixture or fail on `radius_sum` on a polydisperse one — either is acceptable at this step.

- [ ] **Step 3: Implement**

In `Code/BlenderConvert/DEMBulkInstanceBlender.py`, replace `_build_point_cloud` (lines 146–172) with:

```python
def _build_point_cloud(pos, grain_radius_vis, subdiv, radii=None):
    """Point-cloud mesh + shared icosphere + GN 'Instance on Points', via P0_InstancingSpike.

    ``radii`` (float32, one per point) sets each instance's radius -- used by
    real-grain manifests (viz_preprocess_grains_instance.py) so polydisperse
    grains render at their own size. Without it every instance gets
    ``grain_radius_vis`` (static placeholder and synthetic manifests).
    """
    n_points = len(pos)
    mesh = bpy.data.meshes.new('DEM_InstancePoints_mesh')
    mesh.vertices.add(n_points)
    mesh.vertices.foreach_set('co', np.ascontiguousarray(pos).ravel())
    mesh.update()

    attr = mesh.attributes.new(p0.RADIUS_ATTR, 'FLOAT', 'POINT')
    if radii is None:
        radius_values = np.full(n_points, grain_radius_vis, dtype=np.float32)
    else:
        radius_values = np.ascontiguousarray(radii, dtype=np.float32)
        if len(radius_values) != n_points:
            raise ValueError(f'radii has {len(radius_values)} entries, pos has {n_points}')
    attr.data.foreach_set('value', radius_values)

    point_obj = bpy.data.objects.new('DEM_InstancePoints', mesh)
    bpy.context.scene.collection.objects.link(point_obj)

    material = _get_procedural_rock_material()
    ico_mesh = p0._make_icosphere(subdiv)
    ico_mesh.name = 'DEM_InstanceIco'
    ico_mesh.materials.append(material)
    instance_obj = bpy.data.objects.new('DEM_InstanceMesh', ico_mesh)
    bpy.context.scene.collection.objects.link(instance_obj)
    instance_obj.hide_render = True
    instance_obj.hide_viewport = True

    group, _modifier = p0.build_geometry_nodes(point_obj, instance_obj)
    group.name = 'DEM_InstanceOnPoints'
    _add_random_rotation(group)
    return point_obj, group
```

In `main()`, replace lines 300–307:

```python
    first_points_path = _points_path_for_frame(viz_dir, manifest, 0)
    pos = np.load(first_points_path)['pos']
    if len(pos) != manifest['n_points']:
        raise ValueError(
            f"{os.path.basename(first_points_path)} has {len(pos)} points but manifest "
            f"says n_points={manifest['n_points']}"
        )
    point_obj, _group = _build_point_cloud(pos, manifest['grain_radius_vis'], GRAIN_SUBDIV)
```

with:

```python
    first_points_path = _points_path_for_frame(viz_dir, manifest, 0)
    first_points = np.load(first_points_path)
    pos = first_points['pos']
    if len(pos) != manifest['n_points']:
        raise ValueError(
            f"{os.path.basename(first_points_path)} has {len(pos)} points but manifest "
            f"says n_points={manifest['n_points']}"
        )
    # Real-grain manifests carry a per-grain radius; a grain's radius never
    # changes over a run, so setting it once here is enough -- the frame
    # handler keeps updating only 'co'.
    radii = first_points['radius'] if 'radius' in first_points.files else None
    point_obj, _group = _build_point_cloud(pos, manifest['grain_radius_vis'], GRAIN_SUBDIV, radii=radii)
```

Also update the module docstring's second sentence (lines 3–6) to mention the new source:

```python
"""Bulk DEM visualisation -- pure point-cloud instancing (Option A, Objective 3).

Paste into Blender Scripting tab (or open the file directly). Reads a
``viz_mode: "instance"`` manifest from viz_preprocess_lite.py (static placeholder,
``static: true``), synthetic_flyby_test.py (per-frame rigid tumble test data,
``static: false``) or viz_preprocess_grains_instance.py (the real grains,
``static: false``, per-grain ``radius``). Existing per-sphere and composite
importers are unchanged.
"""
```

- [ ] **Step 4: Run to verify pass**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_dem_headless_paths.py -v -k "radii or instance_grains"`
Expected: both PASS.

- [ ] **Step 5: Verify the user's WIP line survived**

Run (PowerShell, in `Code/`): `git diff BlenderConvert/DEMBulkInstanceBlender.py`
Expected: the diff still contains the user's `VIZ_MANIFEST` change (`run_0001_viz_instance_flyby_test`) plus only the `_build_point_cloud` / `main()` / docstring hunks above.

- [ ] **Step 6: Commit the test only**

Do **not** commit `DEMBulkInstanceBlender.py` (user WIP in the same file). Report to the controller that it is modified and uncommitted.

WSL:
```bash
cd /home/mboyle/Honours/sobol && git add tests/test_dem_headless_paths.py && git commit -F - <<'EOF'
Test per-grain radius and instance_grains headless render

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
EOF
```

---

### Task 5: TUI pipeline core — render path registry, preprocess stage, partial failure

**Files:**
- Modify: `/home/mboyle/Honours/sobol/tui_sim_render.py` (imports lines 17–20; constants after line 93; dataclasses lines 148–182; `_render_output_dir` lines 229–232; render stage lines 252–287; `format_live_progress` lines 297–321; `run_pipeline` lines 324–411; `warn_if_high_grain_count` lines 417–428; `_launch` lines 693–700)
- Test (modify): `/home/mboyle/Honours/sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: Task 2 CLI (`--viz-path`, `--manifest`); Task 3 CLI; existing `viz/viz_preprocess.py` and `viz/viz_preprocess_lite.py` CLIs.
- Produces (used by Task 6):
  - `WIN_VENV_PYTHON: Path`, `DEFAULT_PLACEHOLDER_OBJ: str`, `RENDER_PATH_NAMES: tuple[str, ...]`, `RENDER_PATHS: dict[str, RenderPath]`
  - `RenderFormValues` new fields `paths: Tuple[str, ...] = ("per_sphere",)`, `envelope_method: str = "hull"`, `placeholder_obj: str = DEFAULT_PLACEHOLDER_OBJ`, `n_points: int = 1_000_000`
  - `RenderParams` new fields `viz_path: str = "per_sphere"`, `manifest: Optional[Path] = None`
  - `PathResult(name, ok, stage, message, n_frames=0, elapsed_s=0.0)`; `PipelineResult.paths: List[PathResult]`; overall `stage` is `"done"` or `"partial"` after convert
  - `PathContext(grains_dir, bodies_dir, batch_dir, run_name, render_form, n_expected_frames)`
  - `PreprocessError`, `run_preprocess_stage(cmd: List[str], output_dir: Path) -> Path`
  - `build_composite_preprocess_command(ctx, output_dir) -> List[str]`, `build_instance_grains_preprocess_command(ctx, output_dir)`, `build_instance_static_preprocess_command(ctx, output_dir)`
  - `run_render_path(spec, ctx, on_stage=None, index=1, total=1) -> PathResult`
  - `format_path_result(r: PathResult) -> str`
  - `_render_output_dir(batch_dir: Path, run_name: str, path_name: str) -> Path`
  - `on_stage` callbacks: `("preprocess", path=, index=, total=, output_dir=)` and `("render", n_expected=, path=, index=, total=, output_dir=)`
  - `format_live_progress(..., path_label: Optional[str] = None)` handles stage `"preprocess"`
  - `from_windows_path(s: str) -> Path`
  - `pipeline_warning(np_apophis: int, paths) -> str`

- [ ] **Step 1: Update existing tests for the new contract (they will fail until Step 3)**

In `tests/test_tui_sim_render.py`:

(a) Replace `test_render_output_dir` (lines 92–99) with:

```python
def test_render_output_dir():
    batch_dir = Path("/mnt/c/.../Code/DEMCSVs/sobol_20260914_120000_batch")
    out_dir = tsr._render_output_dir(batch_dir, "run_0001", "per_sphere")
    assert out_dir == batch_dir / "run_0001_render_per_sphere"
```

(b) Add after `_write_fake_npz` (line 307):

```python
def _write_fake_pngs(output_dir: Path, n: int) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for i in range(1, n + 1):
        (output_dir / f"frame_{i:04d}.png").write_bytes(b"")


def _ok_completed():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
```

(c) In `test_run_pipeline_stops_after_failed_render` replace the three final assertions with:

```python
    assert result.stage == "partial"
    assert result.ok is False
    assert result.paths[0].name == "per_sphere"
    assert result.paths[0].stage == "render"
    assert "some error" in result.message
    assert "per_sphere: failed at render:" in result.message
```

(d) In `test_run_pipeline_full_success` replace `fake_render` and the assertions with:

```python
    captured = {}
    def fake_render(params):
        captured["params"] = params
        _write_fake_pngs(params.output_dir, 1)
        return _ok_completed()
    monkeypatch.setattr(tsr, "run_render_stage", fake_render)

    sim_params = tsr.SimParams(output_root=Path("sobol_mass_runs/batch"))
    render_form = tsr.RenderFormValues(resolution="640x360", samples=8, camera_mode="grain_only")
    result = tsr.run_pipeline(sim_params, render_form, base_output_dir)

    assert result.stage == "done"
    assert result.ok is True
    assert [r.name for r in result.paths] == ["per_sphere"]
    rp = captured["params"]
    assert rp.viz_path == "per_sphere"
    assert rp.manifest is None
    assert rp.grains_dir == base_output_dir / "batch" / "run_0001_grains_output"
    assert rp.bodies_dir == base_output_dir / "batch" / "run_0001_bodies_output"
    assert rp.output_dir == base_output_dir / "batch" / "run_0001_render_per_sphere"
    assert rp.resolution == "640x360"
    assert rp.samples == 8
    assert rp.camera_mode == "grain_only"
```

(e) In `test_run_pipeline_success_message_counts_rendered_frames` replace the last two lines with:

```python
    output_dir = base_output_dir / "batch" / "run_0001_render_per_sphere"
    assert result.message.startswith("converted 3 frame(s); per_sphere: ok, 2 frame(s) in ")
    assert result.message.endswith(f"s to {output_dir}")
```

(f) In `test_run_pipeline_message_reports_encoded_video` replace the final `output_dir = ...` and assertion with:

```python
    output_dir = base_output_dir / "batch" / "run_0001_render_per_sphere"
    assert f"per_sphere: ok, 2 frame(s) in " in result.message
    assert result.message.endswith(f"s to {output_dir}, encoded to {output_dir / 'animation.mp4'}")
```

(g) `test_run_pipeline_message_flags_missing_video_when_requested`: no change needed (still asserts substrings).

(h) In `test_run_pipeline_notifies_stage_callbacks` replace the final two assertions with:

```python
    assert [s[0] for s in stages] == ["sim", "convert", "render"]
    assert stages[2][1]["n_expected"] == 3
    assert stages[2][1]["path"] == "per_sphere"
    assert (stages[2][1]["index"], stages[2][1]["total"]) == (1, 1)
    assert stages[2][1]["output_dir"] == base_output_dir / "batch" / "run_0001_render_per_sphere"
```

(i) Update the Pilot wait helper `_click_and_wait_for_settled_status` loop condition to also treat `"Preprocessing"` as transient:

```python
        while elapsed < timeout_s and (
            text.startswith("Dry run")
            or text.startswith("Running")
            or text.startswith("Converting")
            or text.startswith("Preprocessing")
            or text.startswith("Rendering")
        ):
```

- [ ] **Step 2: Write the new failing tests**

Append to `tests/test_tui_sim_render.py`:

```python
# --- Bulk render paths: commands, preprocess stage, partial failure -------

def _mnt_ctx(**form_kw):
    batch = Path("/mnt/c/DEMCSVs/batch")
    return tsr.PathContext(
        grains_dir=batch / "run_0001_grains_output",
        bodies_dir=batch / "run_0001_bodies_output",
        batch_dir=batch,
        run_name="run_0001",
        render_form=tsr.RenderFormValues(**form_kw),
        n_expected_frames=3,
    )


def test_render_path_registry_order_and_wiring():
    assert tsr.RENDER_PATH_NAMES == ("per_sphere", "composite", "instance_grains", "instance_static")
    assert tsr.RENDER_PATHS["per_sphere"].build_preprocess_command is None
    assert tsr.RENDER_PATHS["composite"].viz_dir_suffix == "_viz"
    assert tsr.RENDER_PATHS["composite"].headless_viz_path == "composite"
    assert tsr.RENDER_PATHS["instance_grains"].viz_dir_suffix == "_viz_instance"
    assert tsr.RENDER_PATHS["instance_grains"].headless_viz_path == "instance"
    assert tsr.RENDER_PATHS["instance_static"].viz_dir_suffix == "_viz_instance_static"
    assert tsr.RENDER_PATHS["instance_static"].headless_viz_path == "instance"


def test_render_form_values_new_defaults():
    r = tsr.RenderFormValues()
    assert r.paths == ("per_sphere",)
    assert r.envelope_method == "hull"
    assert r.placeholder_obj == tsr.DEFAULT_PLACEHOLDER_OBJ
    assert r.placeholder_obj.endswith("/apophis_v233s7.obj")
    assert r.placeholder_obj.startswith("C:/")
    assert r.n_points == 1_000_000


def test_composite_preprocess_command():
    ctx = _mnt_ctx(envelope_method="sdf", max_frames=3)
    cmd = tsr.build_composite_preprocess_command(ctx, ctx.batch_dir / "run_0001_viz")
    assert cmd[0] == str(tsr.WIN_VENV_PYTHON)
    assert cmd[1] == tsr.to_windows_path(tsr._REPO_WIN_CODE / "viz" / "viz_preprocess.py")
    assert cmd[cmd.index("--grains-dir") + 1] == "C:/DEMCSVs/batch/run_0001_grains_output"
    assert cmd[cmd.index("--bodies-dir") + 1] == "C:/DEMCSVs/batch/run_0001_bodies_output"
    assert cmd[cmd.index("--output-dir") + 1] == "C:/DEMCSVs/batch/run_0001_viz"
    assert cmd[cmd.index("--envelope-method") + 1] == "sdf"
    assert cmd[cmd.index("--max-frames") + 1] == "3"


def test_composite_preprocess_command_without_max_frames():
    ctx = _mnt_ctx()
    cmd = tsr.build_composite_preprocess_command(ctx, ctx.batch_dir / "run_0001_viz")
    assert "--max-frames" not in cmd
    assert cmd[cmd.index("--envelope-method") + 1] == "hull"


def test_instance_grains_preprocess_command():
    ctx = _mnt_ctx(max_frames=2)
    cmd = tsr.build_instance_grains_preprocess_command(ctx, ctx.batch_dir / "run_0001_viz_instance")
    assert cmd[0] == str(tsr.WIN_VENV_PYTHON)
    assert cmd[1] == tsr.to_windows_path(
        tsr._REPO_WIN_CODE / "viz" / "viz_preprocess_grains_instance.py"
    )
    assert cmd[cmd.index("--output-dir") + 1] == "C:/DEMCSVs/batch/run_0001_viz_instance"
    assert cmd[cmd.index("--max-frames") + 1] == "2"
    assert "--envelope-method" not in cmd


def test_instance_static_preprocess_command():
    ctx = _mnt_ctx(placeholder_obj="C:/shapes/a.obj", n_points=5000, max_frames=2)
    cmd = tsr.build_instance_static_preprocess_command(
        ctx, ctx.batch_dir / "run_0001_viz_instance_static"
    )
    assert cmd[0] == tsr.BLENDER_EXE
    assert cmd[1:4] == [
        "--background", "--python",
        tsr.to_windows_path(tsr._REPO_WIN_CODE / "viz" / "viz_preprocess_lite.py"),
    ]
    assert cmd[4] == "--"
    assert cmd[cmd.index("--shape-obj") + 1] == "C:/shapes/a.obj"
    assert cmd[cmd.index("--n-points") + 1] == "5000"
    assert cmd[cmd.index("--output-dir") + 1] == "C:/DEMCSVs/batch/run_0001_viz_instance_static"
    assert "--max-frames" not in cmd


def test_instance_static_preprocess_command_converts_wsl_obj_path():
    ctx = _mnt_ctx(placeholder_obj="/mnt/c/shapes/a.obj")
    cmd = tsr.build_instance_static_preprocess_command(ctx, ctx.batch_dir / "x")
    assert cmd[cmd.index("--shape-obj") + 1] == "C:/shapes/a.obj"


def test_build_render_command_bulk_path_uses_manifest():
    params = tsr.RenderParams(
        grains_dir=Path("/mnt/c/g"), bodies_dir=Path("/mnt/c/b"),
        output_dir=Path("/mnt/c/DEMCSVs/batch/run_0001_render_composite"),
        viz_path="composite", manifest=Path("/mnt/c/DEMCSVs/batch/run_0001_viz/manifest.json"),
    )
    cmd = tsr.build_render_command(params)
    assert cmd[4] == "--"
    assert cmd[cmd.index("--viz-path") + 1] == "composite"
    assert cmd[cmd.index("--manifest") + 1] == "C:/DEMCSVs/batch/run_0001_viz/manifest.json"
    assert "--grains-dir" not in cmd and "--bodies-dir" not in cmd
    assert cmd[cmd.index("--output-dir") + 1] == "C:/DEMCSVs/batch/run_0001_render_composite"


def test_build_render_command_per_sphere_passes_viz_path():
    params = tsr.RenderParams(
        grains_dir=Path("/mnt/c/g"), bodies_dir=Path("/mnt/c/b"), output_dir=Path("/mnt/c/o"),
    )
    cmd = tsr.build_render_command(params)
    assert cmd[cmd.index("--viz-path") + 1] == "per_sphere"
    assert "--manifest" not in cmd


def test_run_preprocess_stage_failure_raises_with_tail(monkeypatch, tmp_path):
    fake = subprocess.CompletedProcess(args=[], returncode=2, stdout="a\nqhull boom", stderr="")
    captured = {}
    def fake_run(cmd, **kw):
        captured.update(kw)
        return fake
    monkeypatch.setattr(tsr.subprocess, "run", fake_run)
    with pytest.raises(tsr.PreprocessError, match="qhull boom"):
        tsr.run_preprocess_stage(["python.exe"], tmp_path / "viz")
    assert captured["cwd"] == str(tsr._REPO_WIN_CODE)


def test_run_preprocess_stage_exit_0_without_manifest_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(tsr.subprocess, "run", lambda *a, **kw: _ok_completed())
    with pytest.raises(tsr.PreprocessError, match="preprocess wrote no manifest at"):
        tsr.run_preprocess_stage(["python.exe"], tmp_path / "viz")


def test_run_preprocess_stage_returns_manifest(monkeypatch, tmp_path):
    out = tmp_path / "viz"
    def fake_run(cmd, **kw):
        out.mkdir()
        (out / "manifest.json").write_text("{}")
        return _ok_completed()
    monkeypatch.setattr(tsr.subprocess, "run", fake_run)
    assert tsr.run_preprocess_stage(["python.exe"], out) == out / "manifest.json"


def _pipeline_setup(monkeypatch, tmp_path, n_npz=2):
    monkeypatch.setattr(tsr, "run_sim_stage", lambda params: _ok_record())
    base = tmp_path / "DEMCSVs"
    grains = base / "batch" / "run_0001_grains_output"
    monkeypatch.setattr(tsr, "run_convert_stage", lambda rec, b: _write_fake_npz(grains, n_npz))
    return base, tsr.SimParams(output_root=Path("sobol_mass_runs/batch"))


def _fake_preprocess_ok(cmd, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text("{}")
    return output_dir / "manifest.json"


def test_run_pipeline_partial_failure_continues_other_paths(monkeypatch, tmp_path):
    base, sim_params = _pipeline_setup(monkeypatch, tmp_path)

    def fake_pre(cmd, output_dir):
        if output_dir.name == "run_0001_viz":
            raise tsr.PreprocessError("exited 1:\nqhull boom")
        return _fake_preprocess_ok(cmd, output_dir)
    monkeypatch.setattr(tsr, "run_preprocess_stage", fake_pre)

    rendered = []
    def fake_render(params):
        rendered.append((params.viz_path, params.manifest))
        _write_fake_pngs(params.output_dir, 2)
        return _ok_completed()
    monkeypatch.setattr(tsr, "run_render_stage", fake_render)

    form = tsr.RenderFormValues(paths=("instance_grains", "per_sphere", "composite"))
    result = tsr.run_pipeline(sim_params, form, base)

    assert result.stage == "partial"
    assert result.ok is False
    assert [r.name for r in result.paths] == ["per_sphere", "composite", "instance_grains"]
    assert [r.ok for r in result.paths] == [True, False, True]
    assert result.paths[1].stage == "preprocess"
    assert rendered == [
        ("per_sphere", None),
        ("instance", base / "batch" / "run_0001_viz_instance" / "manifest.json"),
    ]
    assert "per_sphere: ok, 2 frame(s)" in result.message
    assert "composite: failed at preprocess:" in result.message
    assert "qhull boom" in result.message
    assert "instance_grains: ok, 2 frame(s)" in result.message


def test_run_pipeline_all_paths_ok_is_done(monkeypatch, tmp_path):
    base, sim_params = _pipeline_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(tsr, "run_preprocess_stage", _fake_preprocess_ok)
    out_dirs = []
    def fake_render(params):
        out_dirs.append(params.output_dir.name)
        _write_fake_pngs(params.output_dir, 1)
        return _ok_completed()
    monkeypatch.setattr(tsr, "run_render_stage", fake_render)

    form = tsr.RenderFormValues(paths=tsr.RENDER_PATH_NAMES)
    result = tsr.run_pipeline(sim_params, form, base)

    assert result.stage == "done" and result.ok is True
    assert out_dirs == [
        "run_0001_render_per_sphere", "run_0001_render_composite",
        "run_0001_render_instance_grains", "run_0001_render_instance_static",
    ]


def test_run_pipeline_zero_pngs_is_render_failure(monkeypatch, tmp_path):
    base, sim_params = _pipeline_setup(monkeypatch, tmp_path)
    monkeypatch.setattr(tsr, "run_render_stage", lambda params: _ok_completed())
    result = tsr.run_pipeline(sim_params, tsr.RenderFormValues(), base)
    assert result.ok is False
    assert result.paths[0].stage == "render"
    assert "render wrote no frames to" in result.message


def test_run_pipeline_rejects_empty_or_unknown_paths_before_sim(monkeypatch):
    sim_mock = MagicMock()
    monkeypatch.setattr(tsr, "run_sim_stage", sim_mock)
    with pytest.raises(ValueError, match="render path"):
        tsr.run_pipeline(tsr.SimParams(), tsr.RenderFormValues(paths=()), Path("/x"))
    with pytest.raises(ValueError, match="bogus"):
        tsr.run_pipeline(tsr.SimParams(), tsr.RenderFormValues(paths=("bogus",)), Path("/x"))
    sim_mock.assert_not_called()


def test_run_pipeline_stage_callbacks_per_path(monkeypatch, tmp_path):
    base, sim_params = _pipeline_setup(monkeypatch, tmp_path, n_npz=5)
    monkeypatch.setattr(tsr, "run_preprocess_stage", _fake_preprocess_ok)
    monkeypatch.setattr(
        tsr, "run_render_stage",
        lambda params: (_write_fake_pngs(params.output_dir, 1), _ok_completed())[1],
    )
    stages = []
    tsr.run_pipeline(
        sim_params, tsr.RenderFormValues(paths=("per_sphere", "composite"), max_frames=2), base,
        on_stage=lambda stage, **info: stages.append((stage, info)),
    )
    assert [s[0] for s in stages] == ["sim", "convert", "render", "preprocess", "render"]
    pre = stages[3][1]
    assert (pre["path"], pre["index"], pre["total"]) == ("composite", 2, 2)
    assert pre["output_dir"] == base / "batch" / "run_0001_viz"
    assert stages[4][1]["n_expected"] == 2
    assert stages[4][1]["output_dir"] == base / "batch" / "run_0001_render_composite"


def test_format_path_result():
    ok = tsr.PathResult(name="composite", ok=True, stage="done", message="3 frame(s) in 5s to X")
    bad = tsr.PathResult(name="instance_static", ok=False, stage="preprocess", message="boom")
    assert tsr.format_path_result(ok) == "composite: ok, 3 frame(s) in 5s to X"
    assert tsr.format_path_result(bad) == "instance_static: failed at preprocess: boom"


def test_format_live_progress_preprocess_with_label():
    text = tsr.format_live_progress(12.0, "preprocess", path_label="composite 2/3")
    assert text == "Preprocessing [composite 2/3]... 12s elapsed"


def test_format_live_progress_render_with_label():
    text = tsr.format_live_progress(3.0, "render", n_png=1, n_expected=4, path_label="per_sphere 1/2")
    assert text == "Rendering [per_sphere 1/2]... 3s elapsed, 1/4 frame(s)"


def test_from_windows_path():
    assert tsr.from_windows_path("C:/Users/x/a.obj") == Path("/mnt/c/Users/x/a.obj")
    assert tsr.from_windows_path("D:\\data\\b.obj") == Path("/mnt/d/data/b.obj")
    assert tsr.from_windows_path("/mnt/c/y") == Path("/mnt/c/y")


def test_pipeline_warning_only_for_per_sphere():
    assert tsr.pipeline_warning(5000, ("composite",)) == ""
    assert "5000" in tsr.pipeline_warning(5000, ("per_sphere", "composite"))
    assert tsr.pipeline_warning(500, ("per_sphere",)) == ""
```

- [ ] **Step 3: Run to verify failures**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v`
Expected: the new and updated tests FAIL (`AttributeError: module 'tui_sim_render' has no attribute 'PathContext'` etc.); untouched v1 tests still PASS.

- [ ] **Step 4: Implement**

In `/home/mboyle/Honours/sobol/tui_sim_render.py`:

(a) Imports (line 20): change to

```python
from typing import Callable, Dict, List, Optional, Tuple
```

(b) Update the module docstring (lines 2–4):

```python
"""Textual TUI: configure one PHANTOM DEM run, run it, convert dumps,
render it headless through any mix of per-sphere, composite, and
point-cloud (instanced real grains / static placeholder) paths. One run per
launch — see sobol/tui_run.py for the Sobol sweep TUI.
```

(c) After `DEM_HEADLESS_RENDER = ...` (line 93) add:

```python
# Executed directly from WSL like BLENDER_EXE (so a /mnt/c path); runs the
# composite and real-grain preprocess scripts, which need scipy / numpy that
# Blender's bundled Python lacks (composite) or that the Windows side owns.
WIN_VENV_PYTHON = _REPO_WIN_CODE / ".venv" / "Scripts" / "python.exe"
# Static placeholder shape model -- opened by Windows blender.exe, so a
# Windows-style path.
DEFAULT_PLACEHOLDER_OBJ = to_windows_path(
    _REPO_WIN_CODE / "BlenderConvert" / "Shapes"
    / "gbo.ast-apophis.jpl.radar.shape_model_v1.0"
    / "gbo.ast-apophis.jpl.radar.shape_model_v1.0" / "data" / "apophis_v233s7.obj"
)

_WIN_DRIVE_RE = re.compile(r"^([a-zA-Z]):[\\/](.*)$")


def from_windows_path(s: str) -> Path:
    """Windows <DRIVE>:/... (or <DRIVE>:\\...) -> WSL /mnt/<drive>/... Path.
    Anything else is returned as a Path unchanged."""
    m = _WIN_DRIVE_RE.match(s)
    if not m:
        return Path(s)
    return Path(f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/"))
```

(d) Replace the `RenderFormValues`, `RenderParams`, `PipelineResult` dataclasses (lines 148–182) with:

```python
@dataclass
class RenderFormValues:
    """Render-only inputs from the TUI's render form."""

    resolution: str = "1920x1080"
    samples: int = 500
    fps: int = 24
    max_frames: Optional[int] = None
    camera_mode: str = "auto"
    encode_video: bool = False
    video_fps: Optional[int] = None
    paths: Tuple[str, ...] = ("per_sphere",)
    envelope_method: str = "hull"
    placeholder_obj: str = DEFAULT_PLACEHOLDER_OBJ
    n_points: int = 1_000_000


@dataclass
class RenderParams:
    """Fully resolved inputs to build_render_command() / run_render_stage()."""

    grains_dir: Path
    bodies_dir: Path
    output_dir: Path
    resolution: str = "1920x1080"
    samples: int = 500
    fps: int = 24
    max_frames: Optional[int] = None
    camera_mode: str = "auto"
    encode_video: bool = False
    video_fps: Optional[int] = None
    viz_path: str = "per_sphere"  # DEMHeadlessRender.py --viz-path
    manifest: Optional[Path] = None  # required unless viz_path == "per_sphere"


@dataclass
class PathResult:
    name: str
    ok: bool
    stage: str  # "preprocess" | "render" | "done"
    message: str
    n_frames: int = 0
    elapsed_s: float = 0.0


@dataclass
class PipelineResult:
    stage: str  # "sim" | "convert" | "done" | "partial" | "error"
    ok: bool
    message: str
    record: Optional[RunRecord] = None
    paths: List[PathResult] = field(default_factory=list)
```

(e) Replace `_render_output_dir` (lines 229–232) with:

```python
def _render_output_dir(batch_dir: Path, run_name: str, path_name: str) -> Path:
    return batch_dir / f"{run_name}_render_{path_name}"
```

(f) Replace the render stage block (lines 252–287: `RenderError`, `build_render_command`, `run_render_stage`) with:

```python
class RenderError(RuntimeError):
    pass


class PreprocessError(RuntimeError):
    pass


def _output_tail(result: subprocess.CompletedProcess, n_lines: int = 40) -> str:
    # Blender / script print() output goes to stdout; an uncaught Python
    # traceback goes to stderr. A failure can land in either stream, so
    # combine both before taking the tail.
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    return "\n".join(combined.splitlines()[-n_lines:])


def build_render_command(params: RenderParams) -> List[str]:
    cmd = [
        BLENDER_EXE, "--background", "--python", DEM_HEADLESS_RENDER, "--",
        "--viz-path", params.viz_path,
    ]
    if params.viz_path == "per_sphere":
        cmd += [
            "--grains-dir", to_windows_path(params.grains_dir),
            "--bodies-dir", to_windows_path(params.bodies_dir),
        ]
    else:
        cmd += ["--manifest", to_windows_path(params.manifest)]
    cmd += [
        "--output-dir", to_windows_path(params.output_dir),
        "--resolution", params.resolution,
        "--samples", str(params.samples),
        "--fps", str(params.fps),
        "--camera-mode", params.camera_mode,
    ]
    if params.max_frames is not None:
        cmd += ["--max-frames", str(params.max_frames)]
    if params.encode_video:
        cmd += ["--encode-video"]
        if params.video_fps is not None:
            cmd += ["--video-fps", str(params.video_fps)]
    return cmd


def run_render_stage(params: RenderParams) -> subprocess.CompletedProcess:
    cmd = build_render_command(params)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RenderError(f"blender exited {result.returncode}:\n{_output_tail(result)}")
    return result


@dataclass
class PathContext:
    """Everything a render path needs once sim + convert have succeeded."""

    grains_dir: Path
    bodies_dir: Path
    batch_dir: Path  # <base_output_dir>/<batch name>
    run_name: str  # e.g. "run_0001"
    render_form: RenderFormValues
    n_expected_frames: int


def _max_frames_args(ctx: PathContext) -> List[str]:
    mf = ctx.render_form.max_frames
    return ["--max-frames", str(mf)] if mf is not None else []


def build_composite_preprocess_command(ctx: PathContext, output_dir: Path) -> List[str]:
    return [
        str(WIN_VENV_PYTHON), to_windows_path(_REPO_WIN_CODE / "viz" / "viz_preprocess.py"),
        "--grains-dir", to_windows_path(ctx.grains_dir),
        "--bodies-dir", to_windows_path(ctx.bodies_dir),
        "--output-dir", to_windows_path(output_dir),
        "--envelope-method", ctx.render_form.envelope_method,
    ] + _max_frames_args(ctx)


def build_instance_grains_preprocess_command(ctx: PathContext, output_dir: Path) -> List[str]:
    return [
        str(WIN_VENV_PYTHON),
        to_windows_path(_REPO_WIN_CODE / "viz" / "viz_preprocess_grains_instance.py"),
        "--grains-dir", to_windows_path(ctx.grains_dir),
        "--bodies-dir", to_windows_path(ctx.bodies_dir),
        "--output-dir", to_windows_path(output_dir),
    ] + _max_frames_args(ctx)


def build_instance_static_preprocess_command(ctx: PathContext, output_dir: Path) -> List[str]:
    # viz_preprocess_lite.py needs mathutils.bvhtree -> Blender's Python.
    # One static cloud regardless of frame count, so no --max-frames.
    return [
        BLENDER_EXE, "--background", "--python",
        to_windows_path(_REPO_WIN_CODE / "viz" / "viz_preprocess_lite.py"), "--",
        "--grains-dir", to_windows_path(ctx.grains_dir),
        "--bodies-dir", to_windows_path(ctx.bodies_dir),
        "--output-dir", to_windows_path(output_dir),
        "--shape-obj", to_windows_path(Path(ctx.render_form.placeholder_obj)),
        "--n-points", str(ctx.render_form.n_points),
    ]


def run_preprocess_stage(cmd: List[str], output_dir: Path) -> Path:
    """Run one preprocess subprocess from the Windows repo root; return its manifest path."""
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(_REPO_WIN_CODE))
    if result.returncode != 0:
        raise PreprocessError(f"exited {result.returncode}:\n{_output_tail(result)}")
    manifest = output_dir / "manifest.json"
    if not manifest.is_file():
        raise PreprocessError(f"preprocess wrote no manifest at {output_dir}")
    return manifest


@dataclass(frozen=True)
class RenderPath:
    name: str
    viz_dir_suffix: Optional[str]  # None = no preprocess stage
    build_preprocess_command: Optional[Callable[[PathContext, Path], List[str]]]
    headless_viz_path: str  # DEMHeadlessRender.py --viz-path


# Insertion order is the fixed run order.
RENDER_PATHS: Dict[str, RenderPath] = {
    "per_sphere": RenderPath("per_sphere", None, None, "per_sphere"),
    "composite": RenderPath("composite", "_viz", build_composite_preprocess_command, "composite"),
    "instance_grains": RenderPath(
        "instance_grains", "_viz_instance", build_instance_grains_preprocess_command, "instance",
    ),
    "instance_static": RenderPath(
        "instance_static", "_viz_instance_static", build_instance_static_preprocess_command, "instance",
    ),
}
RENDER_PATH_NAMES: Tuple[str, ...] = tuple(RENDER_PATHS)


def run_render_path(spec: RenderPath, ctx: PathContext, on_stage=None, index: int = 1, total: int = 1) -> PathResult:
    """[preprocess] -> render for one path. Never raises for stage failures."""
    t0 = time.monotonic()

    def notify(stage: str, **info) -> None:
        if on_stage is not None:
            on_stage(stage, path=spec.name, index=index, total=total, **info)

    manifest: Optional[Path] = None
    if spec.build_preprocess_command is not None:
        viz_dir = ctx.batch_dir / f"{ctx.run_name}{spec.viz_dir_suffix}"
        notify("preprocess", output_dir=viz_dir)
        try:
            manifest = run_preprocess_stage(spec.build_preprocess_command(ctx, viz_dir), viz_dir)
        except PreprocessError as exc:
            return PathResult(spec.name, False, "preprocess", str(exc), 0, time.monotonic() - t0)

    output_dir = _render_output_dir(ctx.batch_dir, ctx.run_name, spec.name)
    notify("render", n_expected=ctx.n_expected_frames, output_dir=output_dir)
    form = ctx.render_form
    params = RenderParams(
        grains_dir=ctx.grains_dir,
        bodies_dir=ctx.bodies_dir,
        output_dir=output_dir,
        resolution=form.resolution,
        samples=form.samples,
        fps=form.fps,
        max_frames=form.max_frames,
        camera_mode=form.camera_mode,
        encode_video=form.encode_video,
        video_fps=form.video_fps,
        viz_path=spec.headless_viz_path,
        manifest=manifest,
    )
    try:
        run_render_stage(params)
    except RenderError as exc:
        return PathResult(
            spec.name, False, "render", str(exc),
            count_matching(output_dir, "frame_*.png"), time.monotonic() - t0,
        )

    elapsed = time.monotonic() - t0
    n_frames = count_matching(output_dir, "frame_*.png")
    if n_frames == 0:
        return PathResult(spec.name, False, "render", f"render wrote no frames to {output_dir}", 0, elapsed)
    message = f"{n_frames} frame(s) in {elapsed:.0f}s to {output_dir}"
    if form.encode_video:
        video_path = output_dir / "animation.mp4"
        message += (
            f", encoded to {video_path}" if video_path.is_file()
            else f", video encode requested but {video_path} not found"
        )
    return PathResult(spec.name, True, "done", message, n_frames, elapsed)


def format_path_result(r: PathResult) -> str:
    if r.ok:
        return f"{r.name}: ok, {r.message}"
    return f"{r.name}: failed at {r.stage}: {r.message}"
```

(g) Replace `format_live_progress` (lines 297–321) with:

```python
def format_live_progress(
    elapsed_s: float,
    stage: str,
    *,
    n_dumps: int = 0,
    n_npz: int = 0,
    n_png: int = 0,
    n_expected: Optional[int] = None,
    warning: str = "",
    path_label: Optional[str] = None,
) -> str:
    """Status-bar text for the live-progress tick. Pure — no widget I/O."""
    elapsed = f"{elapsed_s:.0f}s elapsed"
    label = f" [{path_label}]" if path_label else ""
    if stage == "convert":
        count = f"{n_npz}/{n_expected} npz" if n_expected is not None else f"{n_npz} npz"
        body = f"Converting... {elapsed}, {count}"
    elif stage == "preprocess":
        body = f"Preprocessing{label}... {elapsed}"
    elif stage == "render":
        count = (
            f"{n_png}/{n_expected} frame(s)"
            if n_expected is not None
            else f"{n_png} frame(s)"
        )
        body = f"Rendering{label}... {elapsed}, {count}"
    else:
        body = f"Running sim... {elapsed}, {n_dumps} dump file(s)"
    return f"{warning}{body}"
```

(h) Replace `run_pipeline` (lines 324–411) with:

```python
def run_pipeline(
    sim_params: SimParams,
    render_form: RenderFormValues,
    base_output_dir: Path,
    on_stage=None,
) -> PipelineResult:
    """Sim -> convert -> each ticked render path ([preprocess] -> render).

    Sim or convert failure stops everything. A render-path failure is recorded
    on that path and the remaining paths still run (they are independent).

    on_stage(stage: str, **info) is optional. The TUI uses it to flip the
    status bar between dump / npz / preprocess / frame counts.
    """
    if not render_form.paths:
        raise ValueError("at least one render path must be selected")
    unknown = [p for p in render_form.paths if p not in RENDER_PATHS]
    if unknown:
        raise ValueError(f"unknown render path(s): {', '.join(unknown)}")

    def notify(stage: str, **info) -> None:
        if on_stage is not None:
            on_stage(stage, **info)

    notify("sim")
    record = run_sim_stage(sim_params)
    if record.status != "ok":
        return PipelineResult(
            stage="sim", ok=False,
            message=record.error or f"sim ended with status={record.status!r}",
            record=record,
        )

    n_dumps = count_matching(Path(record.run_dir), f"{sim_params.prefix}_[0-9]*")
    notify("convert", n_expected=n_dumps if n_dumps else None)

    try:
        run_convert_stage(record, base_output_dir)
    except ConvertError as exc:
        return PipelineResult(stage="convert", ok=False, message=str(exc), record=record)

    run_dir = Path(record.run_dir)
    grains_dir, bodies_dir = _grains_and_bodies_dirs(run_dir, base_output_dir, sim_params.output_root)

    # DEMDumpConvert.py never raises on a bad dump or an empty run -- it
    # prints and carries on -- so run_convert_stage() "succeeding" is not
    # proof any frame was actually converted. Catch that here rather than
    # let Blender fail minutes/hours later on "no grain npz files found".
    n_npz = count_matching(grains_dir, "*.npz")
    if n_npz == 0:
        return PipelineResult(
            stage="convert", ok=False,
            message=(
                f"no grain npz files found in {grains_dir} -- DEMDumpConvert.py "
                "ran without raising but converted nothing; check that the run "
                f"produced dumps matching its hardcoded \"sobol\" prefix "
                "(sobol_[0-9]*) with enough DEM grains"
            ),
            record=record,
        )
    n_expected_frames = n_npz
    if render_form.max_frames is not None:
        n_expected_frames = min(n_npz, render_form.max_frames)

    ctx = PathContext(
        grains_dir=grains_dir,
        bodies_dir=bodies_dir,
        batch_dir=base_output_dir / sim_params.output_root.name,
        run_name=run_dir.name,
        render_form=render_form,
        n_expected_frames=n_expected_frames,
    )
    specs = [RENDER_PATHS[name] for name in RENDER_PATH_NAMES if name in render_form.paths]
    results = [
        run_render_path(spec, ctx, on_stage=on_stage, index=i, total=len(specs))
        for i, spec in enumerate(specs, start=1)
    ]
    all_ok = all(r.ok for r in results)
    message = f"converted {n_npz} frame(s); " + "; ".join(format_path_result(r) for r in results)
    return PipelineResult(
        stage="done" if all_ok else "partial",
        ok=all_ok,
        message=message,
        record=record,
        paths=results,
    )
```

(i) Replace `warn_if_high_grain_count` (lines 417–428) with:

```python
def warn_if_high_grain_count(np_apophis: int) -> Optional[str]:
    """Non-blocking warning: the per-sphere path degrades above ~2000 grains
    (see CLAUDE.md's pipeline-comparison table)."""
    if np_apophis <= _PER_SPHERE_GRAIN_WARN_THRESHOLD:
        return None
    return (
        f"Warning: np_apophis={np_apophis} — per-sphere path is intended for "
        f"≤{_PER_SPHERE_GRAIN_WARN_THRESHOLD} grains; consider the composite or "
        "instance_grains path instead. "
    )


def pipeline_warning(np_apophis: int, paths) -> str:
    """Grain-count warning, only when the per-sphere path is ticked."""
    if "per_sphere" not in paths:
        return ""
    return warn_if_high_grain_count(np_apophis) or ""
```

(j) In `SimRenderTUIApp._launch`, replace lines 693–700:

```python
        demcsvs = _REPO_WIN_CODE / "DEMCSVs"
        grains_dir, _bodies_dir = _grains_and_bodies_dirs(
            self._pipeline_run_dir, demcsvs, sim_params.output_root,
        )
        self._pipeline_grains_dir = grains_dir
        self._pipeline_render_dir = _render_output_dir(
            self._pipeline_run_dir, demcsvs, sim_params.output_root,
        )
```

with:

```python
        demcsvs = _REPO_WIN_CODE / "DEMCSVs"
        grains_dir, _bodies_dir = _grains_and_bodies_dirs(
            self._pipeline_run_dir, demcsvs, sim_params.output_root,
        )
        self._pipeline_grains_dir = grains_dir
        # Set per path by the "render" stage callback (Task 6).
        self._pipeline_render_dir = None
```

and replace `warning = warn_if_high_grain_count(sim_params.sample.np_apophis) or ""` (line 688) with:

```python
        warning = pipeline_warning(sim_params.sample.np_apophis, render_form.paths)
```

- [ ] **Step 5: Run to verify pass**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v`
Expected: all PASS (existing tests, some updated, plus the new tests).

- [ ] **Step 6: Commit**

```bash
cd /home/mboyle/Honours/sobol && git add tui_sim_render.py tests/test_tui_sim_render.py && git commit -F - <<'EOF'
Run composite and point-cloud render paths from the sim+render pipeline

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
EOF
```

---

### Task 6: TUI form — path checkboxes, path-specific fields, validation, per-path progress

**Files:**
- Modify: `/home/mboyle/Honours/sobol/tui_sim_render.py` — `compose` Render section (after line 553), `_build_render_form` (lines 626–660), `__init__` state (after line 485), `_set_pipeline_stage` (lines 715–721), `_tick_progress` (lines 742–752), `_report_result` (lines 799–802)
- Test (modify): `/home/mboyle/Honours/sobol/tests/test_tui_sim_render.py` (append)

**Interfaces:**
- Consumes: Task 5 `RENDER_PATH_NAMES`, `RenderFormValues` fields, `WIN_VENV_PYTHON`, `DEFAULT_PLACEHOLDER_OBJ`, `from_windows_path`, `format_live_progress(path_label=)`, stage callback info keys `path/index/total/output_dir`, `PipelineResult.stage == "partial"`.
- Produces: widget ids `#path-per-sphere`, `#path-composite`, `#path-instance-grains`, `#path-instance-static`, `#envelope-method`, `#placeholder-obj`, `#n-points`; module constant `PATH_CHECKBOX_IDS: Dict[str, str]`; status text `"[Ns] Finished with failures: ..."` for partial results.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tui_sim_render.py`:

```python
# --- Task 6: render path form ----------------------------------------------

def _render_form_or_error(setup):
    async def _scenario():
        app = tsr.SimRenderTUIApp()
        async with app.run_test():
            setup(app)
            try:
                return app._build_render_form()
            except ValueError as exc:
                return exc
    return asyncio.run(_scenario())


def _tick(app, name, value=True):
    app.query_one(f"#{tsr.PATH_CHECKBOX_IDS[name]}", tsr.Checkbox).value = value


def test_path_checkbox_defaults():
    form = _render_form_or_error(lambda app: None)
    assert form.paths == ("per_sphere",)
    assert form.envelope_method == "hull"
    assert form.placeholder_obj == tsr.DEFAULT_PLACEHOLDER_OBJ
    assert form.n_points == 1_000_000


def test_no_path_ticked_is_error():
    err = _render_form_or_error(lambda app: _tick(app, "per_sphere", False))
    assert isinstance(err, ValueError)
    assert "render path" in str(err)


def test_composite_requires_venv_python(monkeypatch, tmp_path):
    monkeypatch.setattr(tsr, "WIN_VENV_PYTHON", tmp_path / "missing" / "python.exe")
    err = _render_form_or_error(lambda app: _tick(app, "composite"))
    assert isinstance(err, ValueError)
    assert "python.exe" in str(err)


def test_instance_grains_requires_venv_python(monkeypatch, tmp_path):
    monkeypatch.setattr(tsr, "WIN_VENV_PYTHON", tmp_path / "missing" / "python.exe")
    err = _render_form_or_error(lambda app: _tick(app, "instance_grains"))
    assert isinstance(err, ValueError)


def test_composite_with_venv_and_sdf(monkeypatch, tmp_path):
    exe = tmp_path / "python.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(tsr, "WIN_VENV_PYTHON", exe)

    def setup(app):
        _tick(app, "composite")
        app.query_one("#envelope-method", tsr.Select).value = "sdf"

    form = _render_form_or_error(setup)
    assert form.paths == ("per_sphere", "composite")
    assert form.envelope_method == "sdf"


def test_instance_static_missing_obj_is_error(tmp_path):
    def setup(app):
        _tick(app, "instance_static")
        app.query_one("#placeholder-obj", tsr.Input).value = str(tmp_path / "nope.obj")

    err = _render_form_or_error(setup)
    assert isinstance(err, ValueError)
    assert "placeholder_obj" in str(err)


def test_instance_static_nonpositive_n_points_is_error(tmp_path):
    obj = tmp_path / "a.obj"
    obj.write_text("v 0 0 0\n")

    def setup(app):
        _tick(app, "instance_static")
        app.query_one("#placeholder-obj", tsr.Input).value = str(obj)
        app.query_one("#n-points", tsr.Input).value = "0"

    assert isinstance(_render_form_or_error(setup), ValueError)


def test_instance_static_valid(tmp_path):
    obj = tmp_path / "a.obj"
    obj.write_text("v 0 0 0\n")

    def setup(app):
        _tick(app, "per_sphere", False)
        _tick(app, "instance_static")
        app.query_one("#placeholder-obj", tsr.Input).value = str(obj)
        app.query_one("#n-points", tsr.Input).value = "5000"

    form = _render_form_or_error(setup)
    assert form.paths == ("instance_static",)
    assert form.placeholder_obj == str(obj)
    assert form.n_points == 5000


def test_unticked_path_fields_are_not_validated():
    def setup(app):
        app.query_one("#n-points", tsr.Input).value = "garbage"
        app.query_one("#placeholder-obj", tsr.Input).value = "C:/nope.obj"

    form = _render_form_or_error(setup)
    assert form.paths == ("per_sphere",)


def test_envelope_method_select_disallows_blank():
    async def _scenario():
        app = tsr.SimRenderTUIApp()
        async with app.run_test():
            select = app.query_one("#envelope-method", tsr.Select)
            return select._allow_blank, select.value

    allow_blank, value = asyncio.run(_scenario())
    assert allow_blank is False
    assert value == "hull"


def test_set_pipeline_stage_preprocess_shows_path_label():
    async def _scenario():
        app = tsr.SimRenderTUIApp()
        async with app.run_test():
            app._pipeline_running = True
            app._pipeline_start = time.monotonic()
            app._pipeline_dry_run = False
            app._pipeline_warning = ""
            app._set_pipeline_stage(
                "preprocess",
                {"path": "composite", "index": 2, "total": 3, "output_dir": Path("/tmp/x_viz")},
            )
            return str(app.query_one("#status", tsr.Static).content)

    text = asyncio.run(_scenario())
    assert text.startswith("Preprocessing [composite 2/3]...")


def test_set_pipeline_stage_render_tracks_path_output_dir(tmp_path):
    render_dir = tmp_path / "run_0001_render_composite"
    render_dir.mkdir()
    (render_dir / "frame_0001.png").write_bytes(b"")

    async def _scenario():
        app = tsr.SimRenderTUIApp()
        async with app.run_test():
            app._pipeline_running = True
            app._pipeline_start = time.monotonic()
            app._pipeline_dry_run = False
            app._pipeline_warning = ""
            app._set_pipeline_stage(
                "render",
                {"n_expected": 3, "path": "composite", "index": 2, "total": 3, "output_dir": render_dir},
            )
            return app._pipeline_render_dir, str(app.query_one("#status", tsr.Static).content)

    tracked, text = asyncio.run(_scenario())
    assert tracked == render_dir
    assert "Rendering [composite 2/3]..." in text
    assert "1/3 frame(s)" in text


def test_report_result_partial_is_error_status():
    async def _scenario():
        app = tsr.SimRenderTUIApp()
        async with app.run_test():
            app._report_result(tsr.PipelineResult(
                stage="partial", ok=False,
                message="converted 3 frame(s); per_sphere: ok, 3 frame(s) in 1s to X; "
                        "composite: failed at preprocess: boom",
            ))
            s = app.query_one("#status", tsr.Static)
            return str(s.content), s.has_class("err")

    text, is_err = asyncio.run(_scenario())
    assert "Finished with failures:" in text
    assert "composite: failed at preprocess: boom" in text
    assert is_err is True
```

- [ ] **Step 2: Run to verify failures**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v -k "path or envelope or placeholder or n_points or partial or pipeline_stage"`
Expected: FAIL — `AttributeError: module 'tui_sim_render' has no attribute 'PATH_CHECKBOX_IDS'` / `NoMatches` for `#envelope-method`.

- [ ] **Step 3: Implement**

In `/home/mboyle/Honours/sobol/tui_sim_render.py`:

(a) After `RENDER_PATH_NAMES` (Task 5) add:

```python
PATH_CHECKBOX_IDS: Dict[str, str] = {
    "per_sphere": "path-per-sphere",
    "composite": "path-composite",
    "instance_grains": "path-instance-grains",
    "instance_static": "path-instance-static",
}
```

(b) In `__init__`, after `self._pipeline_dry_run: bool = False` (line 485) add:

```python
        self._pipeline_path_label: Optional[str] = None
```

(c) In `compose`, after the `video_fps` row (line 553) and before `with Horizontal(id="bar"):`, add:

```python
            yield Static("Render — paths (any combination; one sim feeds all)", classes="sec")
            yield _Row(
                "per_sphere",
                Checkbox("one sphere per grain", value=True, id=PATH_CHECKBOX_IDS["per_sphere"]),
                "≤~2000 grains",
            )
            yield _Row(
                "composite",
                Checkbox("envelope mesh + ejecta (D3)", value=False, id=PATH_CHECKBOX_IDS["composite"]),
                "any N",
            )
            yield _Row(
                "instance_grains",
                Checkbox("real grains, GN-instanced", value=False, id=PATH_CHECKBOX_IDS["instance_grains"]),
                "any N",
            )
            yield _Row(
                "instance_static",
                Checkbox("shape-model placeholder cloud", value=False, id=PATH_CHECKBOX_IDS["instance_static"]),
                "not sim motion",
            )
            yield _Row(
                "envelope_method",
                Select(
                    [("hull", "hull"), ("sdf", "sdf")],
                    value="hull", id="envelope-method", allow_blank=False,
                ),
                "composite",
            )
            yield _Row(
                "placeholder_obj", Input(DEFAULT_PLACEHOLDER_OBJ, id="placeholder-obj"), "instance_static",
            )
            yield _Row("n_points", Input("1000000", id="n-points"), "instance_static")
```

(d) In `_build_render_form`, replace the final `return RenderFormValues(...)` (lines 652–660) with:

```python
        paths = tuple(
            name for name in RENDER_PATH_NAMES
            if self.query_one(f"#{PATH_CHECKBOX_IDS[name]}", Checkbox).value
        )
        if not paths:
            raise ValueError("tick at least one render path")
        envelope_method = str(self.query_one("#envelope-method", Select).value)
        placeholder_obj = self._iv("placeholder-obj")
        n_points = 1_000_000
        # Path-specific fields are only validated when their path is ticked.
        if "instance_static" in paths:
            n_points = int(self._iv("n-points"))
            if n_points <= 0:
                raise ValueError(f"n_points must be > 0 (got {n_points})")
            if not placeholder_obj or not from_windows_path(placeholder_obj).is_file():
                raise ValueError(f"placeholder_obj not found: {placeholder_obj!r}")
        if {"composite", "instance_grains"} & set(paths) and not Path(WIN_VENV_PYTHON).is_file():
            raise ValueError(
                f"Windows venv python not found at {WIN_VENV_PYTHON} -- needed by the "
                "composite / instance_grains preprocess"
            )
        return RenderFormValues(
            resolution=resolution,
            samples=samples,
            fps=fps,
            max_frames=max_frames,
            camera_mode=str(camera_mode),
            encode_video=bool(encode_video),
            video_fps=video_fps,
            paths=paths,
            envelope_method=envelope_method,
            placeholder_obj=placeholder_obj,
            n_points=n_points,
        )
```

(e) In `_launch`, after `self._pipeline_n_expected = None` add `self._pipeline_path_label = None`.

(f) Replace `_set_pipeline_stage` (lines 715–721) with:

```python
    def _set_pipeline_stage(self, stage: str, info: Optional[dict] = None) -> None:
        """Called from the worker via call_from_thread when a stage starts."""
        self._pipeline_stage = stage
        info = info or {}
        if "n_expected" in info:
            self._pipeline_n_expected = info["n_expected"]
        if "path" in info:
            self._pipeline_path_label = f"{info['path']} {info['index']}/{info['total']}"
        if stage == "render" and "output_dir" in info:
            self._pipeline_render_dir = info["output_dir"]
        if self._pipeline_running and not self._pipeline_dry_run:
            self._tick_progress()
```

(g) In `_tick_progress`, add `path_label=self._pipeline_path_label,` to the `format_live_progress(...)` call (after `warning=self._pipeline_warning,`).

(h) In `_report_result`, replace the final `if result.ok: ... else: ...` (lines 799–802) with:

```python
        if result.ok:
            self._set_status(f"{time_prefix}Done ({result.stage}): {result.message}", error=False)
        elif result.stage == "partial":
            self._set_status(f"{time_prefix}Finished with failures: {result.message}", error=True)
        else:
            self._set_status(f"{time_prefix}Failed at {result.stage}: {result.message}", error=True)
```

- [ ] **Step 4: Run the full TUI suite**

Run: `cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/mboyle/Honours/sobol && git add tui_sim_render.py tests/test_tui_sim_render.py && git commit -F - <<'EOF'
Add render path checkboxes and per-path progress to sim+render TUI

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01W9zj5XsRvF2P6LycfqYnYj
EOF
```

---

### Task 7: Documentation

No code; **no commits** (all three files are gitignored or carry user WIP).

**Files:**
- Modify: WSL `/home/mboyle/Honours/sobol/CLAUDE.md` — section `## Architecture: sim + render pipeline TUI`, and the `tui_sim_render.py` Key commands comment block
- Modify: Windows `Code/CLAUDE.md` — subsection `### Sim + render pipeline TUI`, items 12 and 13 under `## Blender script architecture`, the viz path selection table
- Modify: WSL `/home/mboyle/Honours/CLAUDE.md` — the "Single-run shortcut" paragraph

**Interfaces:**
- Consumes: final behaviour from Tasks 2–6.
- Produces: docs only.

- [ ] **Step 1: WSL `sobol/CLAUDE.md`**

Read the whole `## Architecture: sim + render pipeline TUI` section first. Then:
- Replace the Stage 3 (render) description with:

```markdown
3. **Render paths.** Tick any combination on the form; one sim + one convert feed all of them, run in fixed order `per_sphere`, `composite`, `instance_grains`, `instance_static`. Each path is `[preprocess] → DEMHeadlessRender.py --viz-path …`:
   - `per_sphere` — no preprocess; `DEMGrainsBlenderEarthCam.py` (≤~2000 grains).
   - `composite` (D3) — `viz/viz_preprocess.py --envelope-method hull|sdf` in the Windows `.venv` python → `DEMBulkVizBlender.py`.
   - `instance_grains` — `viz/viz_preprocess_grains_instance.py` in the Windows `.venv` python (real grains, per-grain radius, sorted by `grain_id`) → `DEMBulkInstanceBlender.py` (`static: false`).
   - `instance_static` — `viz/viz_preprocess_lite.py --shape-obj --n-points` under `blender.exe --background` → `DEMBulkInstanceBlender.py` (`static: true`; placeholder, not sim motion).
   A failed path is recorded and the remaining paths still run; result `done` only when every ticked path succeeds, else `partial`.
```

- Replace the output layout paragraph's folder list with:

```markdown
Windows `Code/DEMCSVs/<batch>/`: `run_0001_{grains,bodies}_output/`, `run_0001_viz/` (composite), `run_0001_viz_instance/` (instance_grains), `run_0001_viz_instance_static/` (instance_static), and one `run_0001_render_<path>/` per ticked path with `frame_####.png` (+ `animation.mp4` if `encode_video`). **The v1 per-sphere folder `run_0001_render/` is now `run_0001_render_per_sphere/`.**
```

- Add to the form field list: the four path checkboxes (`per_sphere` ticked by default), `envelope_method` (hull), `placeholder_obj` (Windows copy of `apophis_v233s7.obj`), `n_points` (1000000); path-specific fields validated only when ticked; `.venv` python checked at click time for composite / instance_grains; `>2000` grain warning only when `per_sphere` is ticked.
- Add to the status behaviour: `Preprocessing [<path> i/n]...` and `Rendering [<path> i/n]... k/N frame(s)`; final `Finished with failures: …` for partial.
- Add to limits: instance camera tracks the grain CoM (origin), not the densest core — can sit between fragments on a breakup.
- Update the test line: mention `tests/test_dem_headless_paths.py` (Blender integration tests skip without `blender.exe`) and `tests/test_viz_preprocess_grains_instance.py`.
- In Key commands, extend the quick real test comment: `# all four paths: tick every render path box, max_frames 3 → four run_0001_render_<path>/ folders`.

- [ ] **Step 2: Windows `Code/CLAUDE.md`**

- In `### Sim + render pipeline TUI`, replace "Per-sphere only (`DEMGrainsBlenderEarthCam.py`) — the TUI warns, without blocking, above `np_apophis=2000`; use the composite or instancing path (and their own preprocess scripts) for higher grain counts." with:

```markdown
Render paths (any combination per launch): `per_sphere` (`DEMGrainsBlenderEarthCam.py`; warns above `np_apophis=2000` when ticked), `composite` (`viz/viz_preprocess.py` in `.venv` → `DEMBulkVizBlender.py`), `instance_grains` (`viz/viz_preprocess_grains_instance.py` in `.venv` → `DEMBulkInstanceBlender.py`), `instance_static` (`viz/viz_preprocess_lite.py` in Blender → `DEMBulkInstanceBlender.py`). Renders land in `run_0001_render_<path>/` (the per-sphere folder was `run_0001_render/` in v1); preprocess output in `run_0001_viz/`, `run_0001_viz_instance/`, `run_0001_viz_instance_static/`.
```

- Item 12 (`DEMBulkInstanceBlender.py`): append "Points files that carry a `radius` array (from `viz/viz_preprocess_grains_instance.py`) set a per-grain GN radius; otherwise every instance uses `grain_radius_vis`."
- Item 13 (`DEMHeadlessRender.py`): replace its first two sentences with "Headless-only render for all three Blender paths, driven by `sobol/tui_sim_render.py` (WSL). `--viz-path per_sphere` (default) text-patches `DEMGrainsBlenderEarthCam.py`'s `GRAINS_DIR`/`BODIES_CSV_DIR`/`CAMERA_MODE`; `--viz-path composite --manifest …` patches `DEMBulkVizBlender.py`'s `VIZ_MANIFEST`/`CAMERA_MODE`; `--viz-path instance --manifest …` appends "Procedural rock" from `Blenders/11.blend`, then patches `DEMBulkInstanceBlender.py`'s `VIZ_MANIFEST`/`CAMERA_MODE`/`SLOWMO_FACTOR=1`/`RENDER_RESOLUTION`. Each patterned constant must match exactly once. The chosen script is `exec()`d (same technique `run_demtocsv_batch.py` uses on `DEMDumpConvert.py`); bulk paths set `scene.render.use_lock_interface = True` because their frame handlers rewrite meshes mid-render." Keep the rest of item 13 (World, GPU, exit-code) as is.
- Viz path selection table, "Pure instancing" row, Preprocess column: append "; or `viz_preprocess_grains_instance.py` → per-frame real grains (`static: false`, per-grain radius)".
- In `## Directory layout`, under `viz/`, add the line: `    viz_preprocess_grains_instance.py  # grain npz → run_XXXX_viz_instance/ per-frame real-grain points (instancing path, numpy only)`.

- [ ] **Step 3: WSL root `/home/mboyle/Honours/CLAUDE.md`**

In the "Single-run shortcut" paragraph, replace the per-sphere-only wording with: "renders any mix of per-sphere, composite (D3), instanced real grains, and static placeholder paths from one sim; see `sobol/CLAUDE.md`."

- [ ] **Step 4: Verify line endings and report**

Run (WSL): `for f in /home/mboyle/Honours/sobol/CLAUDE.md /home/mboyle/Honours/CLAUDE.md; do grep -c $'\r' "$f"; done`
Expected: `0` for both (WSL files stay LF). Report the three edited files as uncommitted.

---

## Manual end-to-end (user, after Task 7)

One TUI launch (`cd /home/mboyle/Honours && python3 sobol/tui_sim_render.py`) with all four render path boxes ticked: `np_apophis 500`, `tmax 1`, `dtmax 0.5`, `ephemeris_cache_dir /home/mboyle/Honours/sobol`, `max_frames 3`, `resolution 640x360`, `samples 16`. Expect `Done (done)` and four `run_0001_render_<path>/` folders with 3 PNGs each.
