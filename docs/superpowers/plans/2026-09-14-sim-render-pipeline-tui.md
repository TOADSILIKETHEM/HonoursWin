# Sim + Render Pipeline TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single Textual TUI, `sobol/tui_sim_render.py` (WSL), that configures one PHANTOM DEM run, runs it, converts the dumps to bodies CSV + grains npz, and renders a per-sphere Blender clip headless — one command, one run, no manual steps in between.

**Architecture:** A new headless-only Blender script, `BlenderConvert/DEMHeadlessRender.py` (Windows repo), text-patches and `exec()`s the existing `DEMGrainsBlenderEarthCam.py` (same trick `run_demtocsv_batch.py` already uses on `DEMDumpConvert.py`), then configures Cycles render settings and renders a PNG sequence. A new WSL Textual TUI drives three stages — sim (reusing `run_mass_sobol_phantom.py`'s existing `preflight()`/`run_one_case()`), convert (reusing `run_demtocsv_batch.py`'s `run_dem_dump_convert()`), render (subprocess to `blender.exe`) — each wrapped in a small testable Python function before any UI is built, so the pipeline logic is fully unit-tested with mocks before it's wired to widgets.

**Tech Stack:** Python 3 (WSL side: whatever `run_mass_sobol_phantom.py` already targets; Windows side: Blender 5.2.1 LTS bundled Python), Textual (already a dependency of `sobol/tui_run.py`), pytest (already used in `sobol/tests/`), Blender's `bpy` (Windows side only, not unit-testable — verified via headless smoke test).

**Spec:** `docs/superpowers/specs/2026-09-14-sim-render-pipeline-tui-design.md`

## Global Constraints

- Per-sphere render path only (`DEMGrainsBlenderEarthCam.py`) — no composite, no instancing, no batch/queue mode, no automatic video encode. (spec Non-goals)
- One run per TUI launch, not a sweep — `sobol/tui_run.py` already covers sweeps. (spec Goal)
- `BLENDER_EXE = "/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"` — confirmed present and reachable from WSL via `/mnt/c/` interop (verified live 2026-09-14). (spec Component 5)
- Render defaults: resolution `1920x1080`, samples `128`, fps `24`, camera mode `auto`. (spec Component 3)
- `EARTH_SINK_ID_DEFAULT = 4`, `APOPHIS_SINK_ID_DEFAULT = 11`, `DEFAULT_DN_COHES_FACTOR = 0.1` — exact values from `sobol/run_mass_sobol_phantom.py`. (spec Component 1)
- `GRAINS_DIR`/`BODIES_CSV_DIR` in `DEMGrainsBlenderEarthCam.py` are multi-line parenthesized string literals (lines 21-28) — must be patched with a regex spanning the whole `NAME = ( ... )` block, not a single-line replace. `CAMERA_MODE` (line 97) is a separate single-line switch, patched independently and only for `--camera-mode grain_only`. (spec Component 4, corrected during planning — see inline comment in Task 1)
- `scene.cycles.device` must be set explicitly to `'GPU'` (new/startup scenes default to CPU — same gotcha documented for `P0_InstancingSpike.py`). `scene.render.image_settings.media_type` must be set to `'IMAGE'` before `file_format = 'PNG'` (version-specific enum-filtering gotcha already documented in this repo's `CLAUDE.md`). (spec Component 4)
- Convert-stage output lands at `DEMCSVs/<sim_name>/<run_name>_{bodies,grains}_output/`, where `<sim_name>` = the sim's `output_root.name` and `<run_name>` = `run_dir.name` (verified from `CSVconvert/DEMDumpConvert.py` lines 13-21). (derived during planning)
- Every git commit message ends with the attribution footer given in this session's system reminder (`Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` + `Claude-Session:` line) — reproduced verbatim in each commit step below.

---

### Task 1: `BlenderConvert/DEMHeadlessRender.py` — headless per-sphere render script

**Files:**
- Create: `BlenderConvert/DEMHeadlessRender.py`

**Interfaces:**
- Consumes: `BlenderConvert/DEMGrainsBlenderEarthCam.py` unmodified (read as text, patched in memory, `exec()`'d) — specifically its `GRAINS_DIR` (lines 21-24), `BODIES_CSV_DIR` (lines 25-28), and `CAMERA_MODE` (line 97) top-level assignments, and the fact that it sets `bpy.context.scene.frame_start = 1` / `frame_end = len(grain_files)` itself (lines 772-773) before this script touches the scene.
- Produces: a CLI contract other tasks depend on as a string constant only (never imported as Python — this file only runs inside Blender): `blender.exe --background --python DEMHeadlessRender.py -- --grains-dir PATH --bodies-dir PATH --output-dir PATH [--resolution WxH] [--samples N] [--fps N] [--max-frames N] [--camera-mode auto|grain_only]`. Exit code 0 on success, non-zero (via uncaught exception) on failure. Writes `output-dir/frame_XXXX.png` per frame.

- [ ] **Step 1: Write the script**

```python
"""Headless per-sphere DEM render — not pasted into the Scripting tab.

Run with:
    blender.exe --background --python BlenderConvert/DEMHeadlessRender.py -- \\
        --grains-dir PATH --bodies-dir PATH --output-dir PATH \\
        [--resolution 1920x1080] [--samples 128] [--fps 24] \\
        [--max-frames N] [--camera-mode auto|grain_only]

Text-patches BlenderConvert/DEMGrainsBlenderEarthCam.py's GRAINS_DIR /
BODIES_CSV_DIR / CAMERA_MODE constants and exec()s it — the same technique
sobol/Analysis/run_demtocsv_batch.py already uses on DEMDumpConvert.py —
so grains + Earth + camera are built exactly as the interactive
Scripting-tab path builds them. Only render settings and the render call
are new here.
"""
import argparse
import re
import sys
from pathlib import Path

import bpy


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--grains-dir", required=True)
    p.add_argument("--bodies-dir", required=True)
    p.add_argument("--output-dir", required=True)
    p.add_argument("--resolution", default="1920x1080")
    p.add_argument("--samples", type=int, default=128)
    p.add_argument("--fps", type=int, default=24)
    p.add_argument("--max-frames", type=int, default=None)
    p.add_argument("--camera-mode", choices=("auto", "grain_only"), default="auto")
    return p.parse_args(argv)


def _patch_and_exec(script_path: Path, grains_dir: str, bodies_dir: str, camera_mode: str) -> None:
    src = script_path.read_text(encoding="utf-8")

    # GRAINS_DIR / BODIES_CSV_DIR are multi-line parenthesized string
    # literals (DEMGrainsBlenderEarthCam.py:21-28) -- replace the whole
    # "NAME = ( ... )" block. Safe because neither literal contains ")".
    src, n = re.subn(r"GRAINS_DIR\s*=\s*\([^)]*\)", f"GRAINS_DIR = {grains_dir!r}", src, count=1)
    if n != 1:
        raise RuntimeError(f"GRAINS_DIR pattern not found in {script_path}")
    src, n = re.subn(r"BODIES_CSV_DIR\s*=\s*\([^)]*\)", f"BODIES_CSV_DIR = {bodies_dir!r}", src, count=1)
    if n != 1:
        raise RuntimeError(f"BODIES_CSV_DIR pattern not found in {script_path}")

    if camera_mode == "grain_only":
        # CAMERA_MODE (line ~97) is a separate single-line switch from
        # IMPORT_SOLAR_SYSTEM -- it forces camera behavior, not whether
        # solar-system bodies are imported.
        src, n = re.subn(r"CAMERA_MODE\s*=\s*None", "CAMERA_MODE = 'grain_only'", src, count=1)
        if n != 1:
            raise RuntimeError(f"CAMERA_MODE pattern not found in {script_path}")

    exec(compile(src, str(script_path), "exec"), {"__name__": "__main__"})


def main() -> None:
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
    scene.render.image_settings.media_type = 'IMAGE'
    scene.render.image_settings.file_format = 'PNG'
    scene.render.filepath = str(out_dir) + "/frame_"

    print(
        f"[DEMHeadlessRender] Rendering frames {scene.frame_start}-{scene.frame_end} "
        f"at {res_x}x{res_y}, {args.samples} samples, to {out_dir}"
    )
    bpy.ops.render.render(animation=True)
    n_frames = scene.frame_end - scene.frame_start + 1
    print(f"[DEMHeadlessRender] Done — {n_frames} frame(s) written to {out_dir}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the smoke test against existing real data**

`torque_align_obj/run_0001_{grains,bodies}_output` already exist on disk from prior sessions. Run from the `Code/` repo root:

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" `
  --background --python BlenderConvert\DEMHeadlessRender.py -- `
  --grains-dir DEMCSVs\torque_align_obj\run_0001_grains_output `
  --bodies-dir DEMCSVs\torque_align_obj\run_0001_bodies_output `
  --output-dir DEMCSVs\torque_align_obj\_headless_render_smoketest `
  --resolution 960x540 --samples 16 --max-frames 3
```

Expected: exit code 0, console shows `[DEMHeadlessRender] Rendering frames 1-3 at 960x540, 16 samples, to ...` then `Done — 3 frame(s) written to ...`, and `DEMCSVs\torque_align_obj\_headless_render_smoketest\` contains exactly 3 `frame_*.png` files.

- [ ] **Step 3: Clean up the smoke-test output (scratch, not a deliverable)**

```bash
rm -rf "DEMCSVs/torque_align_obj/_headless_render_smoketest"
```

- [ ] **Step 4: Commit**

```bash
git add BlenderConvert/DEMHeadlessRender.py
git commit -m "$(cat <<'EOF'
Add headless per-sphere DEM render script for the sim+render pipeline

Text-patches and exec()s DEMGrainsBlenderEarthCam.py (same technique
run_demtocsv_batch.py uses on DEMDumpConvert.py), then configures Cycles
render settings and renders a PNG sequence. No GUI/Scripting-tab needed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)"
```

---

### Task 2: `sobol/tui_sim_render.py` skeleton — constants, dataclasses, `to_windows_path()`

**Files:**
- Create: `sobol/tui_sim_render.py`
- Create: `sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: nothing from other tasks yet.
- Produces (used by Tasks 3-8): module-level constants `BLENDER_EXE: str`, `DEM_HEADLESS_RENDER: str`, `_REPO_WIN_CODE: Path`; function `to_windows_path(p: Path) -> str`; dataclasses `SimParams`, `RenderFormValues`, `RenderParams`, `PipelineResult` (fields exactly as declared below — later tasks add methods/functions around them but do not rename fields).

- [ ] **Step 1: Write the failing test**

Create `sobol/tests/test_tui_sim_render.py`:

```python
"""Tests for tui_sim_render.py (sim+render pipeline TUI)."""
import sys
from pathlib import Path

# Run from sobol/ so the module is importable, same convention as
# sobol/tests/test_metric_fixes.py.
sys.path.insert(0, str(Path(__file__).parent.parent))
import tui_sim_render as tsr


def test_to_windows_path_translates_mnt_c():
    result = tsr.to_windows_path(Path("/mnt/c/Users/22boy/DEMCSVs/run_0001"))
    assert result == "C:/Users/22boy/DEMCSVs/run_0001"


def test_to_windows_path_passthrough_for_windows_style():
    # Already Windows-style (e.g. passed in directly) -> returned unchanged
    # apart from Path's own normalization, which does not apply here since
    # the string never starts with "/mnt/".
    result = tsr.to_windows_path(Path("C:/Users/22boy/DEMCSVs/run_0001"))
    assert result == "C:/Users/22boy/DEMCSVs/run_0001"


def test_sim_params_defaults():
    p = tsr.SimParams()
    assert p.prefix == "sobol"
    assert p.dry_run is False
    assert p.earth_sink_id == 4
    assert p.apophis_sink_id == 11


def test_render_form_values_defaults():
    r = tsr.RenderFormValues()
    assert r.resolution == "1920x1080"
    assert r.samples == 128
    assert r.fps == 24
    assert r.max_frames is None
    assert r.camera_mode == "auto"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'tui_sim_render'`.

- [ ] **Step 3: Write minimal implementation**

Create `sobol/tui_sim_render.py`:

```python
#!/usr/bin/env python3
"""Textual TUI: configure one PHANTOM DEM run, run it, convert dumps,
render a per-sphere Blender clip headless. One run per launch — see
sobol/tui_run.py for the Sobol sweep TUI.

Launch:
    python3 sobol/tui_sim_render.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from run_mass_sobol_phantom import (  # noqa: E402
    RunSample,
    RunRecord,
    EARTH_SINK_ID_DEFAULT,
    APOPHIS_SINK_ID_DEFAULT,
    DEFAULT_DN_COHES_FACTOR,
)

# Windows-side Code repo root, reached over the WSL /mnt/c/ interop mount —
# hardcoded the same way sobol/Analysis/run_demtocsv_batch.py hardcodes
# DEFAULT_DEM_DUMP_CONVERT / DEFAULT_BASE_OUT, not derived.
_REPO_WIN_CODE = Path(
    "/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code"
)
BLENDER_EXE = "/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe"
DEM_HEADLESS_RENDER = str(_REPO_WIN_CODE / "BlenderConvert" / "DEMHeadlessRender.py")


def to_windows_path(p: Path) -> str:
    """WSL /mnt/<drive>/... path -> Windows <DRIVE>:/... path string.

    Deliberately simpler than shelling out to `wslpath -w` -- the mount is
    always /mnt/<single-letter>/... in this environment.
    """
    s = str(Path(p).resolve())
    if s.startswith("/mnt/") and len(s) > 6 and s[5] == "/":
        drive = s[5].upper()
        return f"{drive}:{s[6:]}"
    return s


@dataclass
class SimParams:
    """Fixed-value inputs for one PHANTOM run (no Sobol sampling)."""

    prefix: str = "sobol"
    base_dir: Path = field(default_factory=lambda: Path("."))
    phantom_dir: Path = field(default_factory=lambda: Path("."))
    output_root: Path = field(default_factory=lambda: Path("sobol_mass_runs"))
    ephemeris_cache_dir: Optional[Path] = None
    dry_run: bool = False
    earth_sink_id: int = EARTH_SINK_ID_DEFAULT
    apophis_sink_id: int = APOPHIS_SINK_ID_DEFAULT
    shape_file: Optional[str] = None
    sample: RunSample = field(default_factory=RunSample)


@dataclass
class RenderFormValues:
    """Render-only inputs from the TUI's render form."""

    resolution: str = "1920x1080"
    samples: int = 128
    fps: int = 24
    max_frames: Optional[int] = None
    camera_mode: str = "auto"


@dataclass
class RenderParams:
    """Fully resolved inputs to build_render_command() / run_render_stage()."""

    grains_dir: Path
    bodies_dir: Path
    output_dir: Path
    resolution: str = "1920x1080"
    samples: int = 128
    fps: int = 24
    max_frames: Optional[int] = None
    camera_mode: str = "auto"


@dataclass
class PipelineResult:
    stage: str  # "sim" | "convert" | "render" | "done"
    ok: bool
    message: str
    record: Optional[RunRecord] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
wsl.exe bash -lc "cd /home/mboyle/Honours && git add sobol/tui_sim_render.py sobol/tests/test_tui_sim_render.py && git commit -m \"\$(cat <<'EOF'
Add sim+render pipeline TUI skeleton: constants, dataclasses, path helper

First piece of the single-run sim-to-render pipeline TUI. to_windows_path()
bridges WSL /mnt/c/ paths to the Windows blender.exe path format needed by
later stages.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)\""
```

---

### Task 3: Sim stage — `run_sim_stage()`

**Files:**
- Modify: `sobol/tui_sim_render.py`
- Modify: `sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: `SimParams` (Task 2); `preflight`, `run_one_case` from `run_mass_sobol_phantom` (exact signatures: `preflight(args: argparse.Namespace, base_dir: Path, output_root: Path) -> Tuple[Path, Path, Path, Path]`; `run_one_case(run_id, sample, base_setup, base_input, output_root, prefix, phantomsetup_bin, phantom_bin, ref_mass_kg, dry_run, earth_sink_id, apophis_sink_id, ephemeris_cache_dir=None, shape_file=None, literature_scale_r_allowed=True) -> RunRecord`).
- Produces: `run_sim_stage(params: SimParams) -> RunRecord`, imported/used unmodified by Task 6.

- [ ] **Step 1: Write the failing test**

Append to `sobol/tests/test_tui_sim_render.py`:

```python
import argparse
from unittest.mock import MagicMock


def test_run_sim_stage_forwards_params(monkeypatch):
    fake_paths = (Path("base.setup"), Path("base.in"), Path("phantomsetup"), Path("phantom"))
    fake_preflight = MagicMock(return_value=fake_paths)
    fake_record = tsr.RunRecord(
        run_id=1, mass_input_kg=float("nan"), run_dir="sobol_mass_runs/run_0001",
        status="ok", closest_approach_km=1234.5, closest_approach_au=0.01,
        error="",
    )
    fake_run_one_case = MagicMock(return_value=fake_record)
    monkeypatch.setattr(tsr, "preflight", fake_preflight)
    monkeypatch.setattr(tsr, "run_one_case", fake_run_one_case)

    params = tsr.SimParams(prefix="sobol", earth_sink_id=4, apophis_sink_id=11)
    result = tsr.run_sim_stage(params)

    assert result is fake_record
    fake_preflight.assert_called_once()
    preflight_args = fake_preflight.call_args[0][0]
    assert isinstance(preflight_args, argparse.Namespace)
    assert preflight_args.prefix == "sobol"
    assert preflight_args.dry_run is False

    fake_run_one_case.assert_called_once()
    _, kwargs = fake_run_one_case.call_args
    assert kwargs["run_id"] == 1
    assert kwargs["sample"] is params.sample
    assert kwargs["earth_sink_id"] == 4
    assert kwargs["apophis_sink_id"] == 11
    assert kwargs["dry_run"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v -k test_run_sim_stage_forwards_params"`
Expected: FAIL — `AttributeError: module 'tui_sim_render' has no attribute 'run_sim_stage'` (also no `preflight`/`run_one_case` names to monkeypatch yet).

- [ ] **Step 3: Write minimal implementation**

Add to the `run_mass_sobol_phantom` import block in `sobol/tui_sim_render.py` (replace the existing import statement from Task 2):

```python
from run_mass_sobol_phantom import (  # noqa: E402
    RunSample,
    RunRecord,
    EARTH_SINK_ID_DEFAULT,
    APOPHIS_SINK_ID_DEFAULT,
    DEFAULT_DN_COHES_FACTOR,
    preflight,
    run_one_case,
)
import argparse
```

Then append after the dataclasses:

```python
def run_sim_stage(params: SimParams) -> RunRecord:
    """Run one PHANTOM case from params.sample. Blocking — call from a worker thread."""
    base_setup, base_input, phantomsetup_bin, phantom_bin = preflight(
        argparse.Namespace(
            prefix=params.prefix,
            phantom_dir=str(params.phantom_dir),
            dry_run=params.dry_run,
        ),
        params.base_dir,
        params.output_root,
    )
    return run_one_case(
        run_id=1,
        sample=params.sample,
        base_setup=base_setup,
        base_input=base_input,
        output_root=params.output_root,
        prefix=params.prefix,
        phantomsetup_bin=phantomsetup_bin,
        phantom_bin=phantom_bin,
        ref_mass_kg=None,
        dry_run=params.dry_run,
        earth_sink_id=params.earth_sink_id,
        apophis_sink_id=params.apophis_sink_id,
        ephemeris_cache_dir=params.ephemeris_cache_dir,
        shape_file=params.shape_file,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
wsl.exe bash -lc "cd /home/mboyle/Honours && git add sobol/tui_sim_render.py sobol/tests/test_tui_sim_render.py && git commit -m \"\$(cat <<'EOF'
Add sim stage wrapper (run_sim_stage) to sim+render pipeline TUI

Thin wrapper around run_mass_sobol_phantom.preflight()/run_one_case() for
a single fixed-value run (run_id=1, no Sobol sampling) -- reuses the exact
functions run_torque_align_blender_reruns.py already calls, so PHANTOM
invocation logic is not reimplemented.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)\""
```

---

### Task 4: Convert stage — `run_convert_stage()` and output-path helpers

**Files:**
- Modify: `sobol/tui_sim_render.py`
- Modify: `sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: `RunRecord` (from Task 3's `run_sim_stage()` return value, fields `.status`, `.run_dir`); `run_dem_dump_convert`, `DEFAULT_DEM_DUMP_CONVERT`, `_min_dem_grains_from_setup` from `sobol/Analysis/run_demtocsv_batch.py` (exact signature: `run_dem_dump_convert(input_dir: Path, dump_convert_path: Path, base_output_dir: Path, min_dem_grains: Optional[int]) -> None`, raises on failure, no return value).
- Produces: exception class `ConvertError`; function `run_convert_stage(record: RunRecord, base_output_dir: Path) -> None`; helpers `_grains_and_bodies_dirs(run_dir: Path, base_output_dir: Path, output_root: Path) -> Tuple[Path, Path]` and `_render_output_dir(run_dir: Path, base_output_dir: Path, output_root: Path) -> Path` — both used by Task 6.

- [ ] **Step 1: Write the failing test**

Append to `sobol/tests/test_tui_sim_render.py`:

```python
import pytest


def test_grains_and_bodies_dirs():
    run_dir = Path("/mnt/c/.../sobol_mass_runs/sobol_20260914_120000_batch/run_0001")
    base_output_dir = Path("/mnt/c/.../Code/DEMCSVs")
    output_root = Path("/mnt/c/.../sobol_mass_runs/sobol_20260914_120000_batch")

    grains_dir, bodies_dir = tsr._grains_and_bodies_dirs(run_dir, base_output_dir, output_root)

    assert grains_dir == base_output_dir / "sobol_20260914_120000_batch" / "run_0001_grains_output"
    assert bodies_dir == base_output_dir / "sobol_20260914_120000_batch" / "run_0001_bodies_output"


def test_render_output_dir():
    run_dir = Path("/mnt/c/.../sobol_mass_runs/sobol_20260914_120000_batch/run_0001")
    base_output_dir = Path("/mnt/c/.../Code/DEMCSVs")
    output_root = Path("/mnt/c/.../sobol_mass_runs/sobol_20260914_120000_batch")

    out_dir = tsr._render_output_dir(run_dir, base_output_dir, output_root)

    assert out_dir == base_output_dir / "sobol_20260914_120000_batch" / "run_0001_render"


def test_run_convert_stage_calls_converter(monkeypatch):
    fake_convert = MagicMock()
    fake_min_grains = MagicMock(return_value=450)
    monkeypatch.setattr(tsr, "run_dem_dump_convert", fake_convert)
    monkeypatch.setattr(tsr, "_min_dem_grains_from_setup", fake_min_grains)

    record = tsr.RunRecord(
        run_id=1, mass_input_kg=float("nan"), run_dir="sobol_mass_runs/batch/run_0001",
        status="ok", closest_approach_km=1.0, closest_approach_au=0.01, error="",
    )
    tsr.run_convert_stage(record, base_output_dir=Path("/mnt/c/.../Code/DEMCSVs"))

    fake_min_grains.assert_called_once_with(Path("sobol_mass_runs/batch/run_0001"))
    fake_convert.assert_called_once_with(
        input_dir=Path("sobol_mass_runs/batch/run_0001"),
        dump_convert_path=tsr.DEFAULT_DEM_DUMP_CONVERT,
        base_output_dir=Path("/mnt/c/.../Code/DEMCSVs"),
        min_dem_grains=450,
    )


def test_run_convert_stage_wraps_converter_exception(monkeypatch):
    def boom(**kwargs):
        raise ValueError("bad dump")
    monkeypatch.setattr(tsr, "run_dem_dump_convert", boom)
    monkeypatch.setattr(tsr, "_min_dem_grains_from_setup", lambda run_dir: None)

    record = tsr.RunRecord(
        run_id=1, mass_input_kg=float("nan"), run_dir="sobol_mass_runs/batch/run_0001",
        status="ok", closest_approach_km=1.0, closest_approach_au=0.01, error="",
    )
    with pytest.raises(tsr.ConvertError, match="bad dump"):
        tsr.run_convert_stage(record, base_output_dir=Path("/mnt/c/.../Code/DEMCSVs"))


def test_run_convert_stage_skips_when_sim_not_ok(monkeypatch):
    fake_convert = MagicMock()
    monkeypatch.setattr(tsr, "run_dem_dump_convert", fake_convert)

    record = tsr.RunRecord(
        run_id=1, mass_input_kg=float("nan"), run_dir="sobol_mass_runs/batch/run_0001",
        status="prepared_only", closest_approach_km=float("nan"),
        closest_approach_au=float("nan"), error="",
    )
    with pytest.raises(tsr.ConvertError, match="prepared_only"):
        tsr.run_convert_stage(record, base_output_dir=Path("/mnt/c/.../Code/DEMCSVs"))
    fake_convert.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v -k convert or grains_and_bodies or render_output_dir"`
Expected: FAIL — `AttributeError: module 'tui_sim_render' has no attribute '_grains_and_bodies_dirs'` (and similarly for the others).

- [ ] **Step 3: Write minimal implementation**

Add near the top of `sobol/tui_sim_render.py`, alongside the other `sys.path.insert`:

```python
sys.path.insert(0, str(Path(__file__).parent / "Analysis"))
from run_demtocsv_batch import (  # noqa: E402
    run_dem_dump_convert,
    DEFAULT_DEM_DUMP_CONVERT,
    _min_dem_grains_from_setup,
)
```

Append after `run_sim_stage()`:

```python
class ConvertError(RuntimeError):
    pass


def _grains_and_bodies_dirs(run_dir: Path, base_output_dir: Path, output_root: Path):
    """DEMDumpConvert.py's own naming rule (CSVconvert/DEMDumpConvert.py:19-22):
    <sim_name> = INPUT_DIR's parent name, <run_name> = INPUT_DIR's own name.
    """
    sim_name = output_root.name
    run_name = run_dir.name
    grains_dir = base_output_dir / sim_name / f"{run_name}_grains_output"
    bodies_dir = base_output_dir / sim_name / f"{run_name}_bodies_output"
    return grains_dir, bodies_dir


def _render_output_dir(run_dir: Path, base_output_dir: Path, output_root: Path) -> Path:
    sim_name = output_root.name
    run_name = run_dir.name
    return base_output_dir / sim_name / f"{run_name}_render"


def run_convert_stage(record: RunRecord, base_output_dir: Path) -> None:
    """Convert one run's dumps to bodies CSV + grains npz. Raises ConvertError on any failure."""
    if record.status != "ok":
        raise ConvertError(f"sim did not complete (status={record.status!r}); skipping convert")
    run_dir = Path(record.run_dir)
    min_grains = _min_dem_grains_from_setup(run_dir)
    try:
        run_dem_dump_convert(
            input_dir=run_dir,
            dump_convert_path=DEFAULT_DEM_DUMP_CONVERT,
            base_output_dir=base_output_dir,
            min_dem_grains=min_grains,
        )
    except Exception as exc:
        raise ConvertError(f"conversion failed: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
wsl.exe bash -lc "cd /home/mboyle/Honours && git add sobol/tui_sim_render.py sobol/tests/test_tui_sim_render.py && git commit -m \"\$(cat <<'EOF'
Add convert stage wrapper (run_convert_stage) to sim+render pipeline TUI

Wraps run_demtocsv_batch.run_dem_dump_convert() with a ConvertError that
carries the underlying exception text, and adds output-path helpers that
encode DEMDumpConvert.py's own <sim_name>/<run_name>_*_output naming rule
so later stages don't have to re-derive it.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)\""
```

---

### Task 5: Render stage — `build_render_command()` and `run_render_stage()`

**Files:**
- Modify: `sobol/tui_sim_render.py`
- Modify: `sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: `RenderParams` (Task 2); `BLENDER_EXE`, `DEM_HEADLESS_RENDER` (Task 2); `to_windows_path()` (Task 2).
- Produces: exception class `RenderError`; functions `build_render_command(params: RenderParams) -> List[str]` and `run_render_stage(params: RenderParams) -> subprocess.CompletedProcess`, used by Task 6.

- [ ] **Step 1: Write the failing test**

Append to `sobol/tests/test_tui_sim_render.py`:

```python
import subprocess


def test_build_render_command_without_max_frames():
    params = tsr.RenderParams(
        grains_dir=Path("/mnt/c/DEMCSVs/batch/run_0001_grains_output"),
        bodies_dir=Path("/mnt/c/DEMCSVs/batch/run_0001_bodies_output"),
        output_dir=Path("/mnt/c/DEMCSVs/batch/run_0001_render"),
        resolution="1280x720", samples=64, fps=30, camera_mode="auto",
    )
    cmd = tsr.build_render_command(params)

    assert cmd[0] == tsr.BLENDER_EXE
    assert cmd[1:4] == ["--background", "--python", tsr.DEM_HEADLESS_RENDER]
    assert cmd[4] == "--"
    assert "--grains-dir" in cmd and "C:/DEMCSVs/batch/run_0001_grains_output" in cmd
    assert "--resolution" in cmd and "1280x720" in cmd
    assert "--samples" in cmd and "64" in cmd
    assert "--fps" in cmd and "30" in cmd
    assert "--camera-mode" in cmd and "auto" in cmd
    assert "--max-frames" not in cmd


def test_build_render_command_with_max_frames():
    params = tsr.RenderParams(
        grains_dir=Path("/mnt/c/DEMCSVs/batch/run_0001_grains_output"),
        bodies_dir=Path("/mnt/c/DEMCSVs/batch/run_0001_bodies_output"),
        output_dir=Path("/mnt/c/DEMCSVs/batch/run_0001_render"),
        max_frames=3,
    )
    cmd = tsr.build_render_command(params)
    idx = cmd.index("--max-frames")
    assert cmd[idx + 1] == "3"


def test_run_render_stage_success(monkeypatch):
    fake_result = subprocess.CompletedProcess(args=["blender"], returncode=0, stdout="ok", stderr="")
    monkeypatch.setattr(tsr.subprocess, "run", lambda *a, **kw: fake_result)

    params = tsr.RenderParams(
        grains_dir=Path("/mnt/c/g"), bodies_dir=Path("/mnt/c/b"), output_dir=Path("/mnt/c/o"),
    )
    result = tsr.run_render_stage(params)
    assert result is fake_result


def test_run_render_stage_failure_raises_with_combined_tail(monkeypatch):
    # Blender's own print() output goes to stdout; a Python traceback goes to
    # stderr -- a failure can show up in either, so both must be checked.
    stdout_text = "\n".join(f"stdout line {i}" for i in range(30))
    stderr_text = "\n".join(f"stderr line {i}" for i in range(30))
    fake_result = subprocess.CompletedProcess(
        args=["blender"], returncode=1, stdout=stdout_text, stderr=stderr_text,
    )
    monkeypatch.setattr(tsr.subprocess, "run", lambda *a, **kw: fake_result)

    params = tsr.RenderParams(
        grains_dir=Path("/mnt/c/g"), bodies_dir=Path("/mnt/c/b"), output_dir=Path("/mnt/c/o"),
    )
    with pytest.raises(tsr.RenderError) as excinfo:
        tsr.run_render_stage(params)
    msg = str(excinfo.value)
    assert "stderr line 29" in msg  # last lines of the combined text are kept
    assert "stdout line 0" not in msg  # only the last ~40 combined lines survive


def test_run_render_stage_failure_reads_stdout_only_traceback(monkeypatch):
    # Regression case: some failures print everything to stdout with an
    # empty stderr (e.g. exec()'d script prints its own error and returns
    # non-zero without raising) -- stderr-only capture would show nothing.
    fake_result = subprocess.CompletedProcess(
        args=["blender"], returncode=1, stdout="GRAINS_DIR pattern not found", stderr="",
    )
    monkeypatch.setattr(tsr.subprocess, "run", lambda *a, **kw: fake_result)

    params = tsr.RenderParams(
        grains_dir=Path("/mnt/c/g"), bodies_dir=Path("/mnt/c/b"), output_dir=Path("/mnt/c/o"),
    )
    with pytest.raises(tsr.RenderError, match="GRAINS_DIR pattern not found"):
        tsr.run_render_stage(params)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v -k render_command or run_render_stage"`
Expected: FAIL — `AttributeError: module 'tui_sim_render' has no attribute 'build_render_command'`.

- [ ] **Step 3: Write minimal implementation**

Add `import subprocess` to the top imports of `sobol/tui_sim_render.py`, and `from typing import List` to the existing `typing` import line. Append after `run_convert_stage()`:

```python
class RenderError(RuntimeError):
    pass


def build_render_command(params: RenderParams) -> List[str]:
    cmd = [
        BLENDER_EXE, "--background", "--python", DEM_HEADLESS_RENDER, "--",
        "--grains-dir", to_windows_path(params.grains_dir),
        "--bodies-dir", to_windows_path(params.bodies_dir),
        "--output-dir", to_windows_path(params.output_dir),
        "--resolution", params.resolution,
        "--samples", str(params.samples),
        "--fps", str(params.fps),
        "--camera-mode", params.camera_mode,
    ]
    if params.max_frames is not None:
        cmd += ["--max-frames", str(params.max_frames)]
    return cmd


def run_render_stage(params: RenderParams) -> subprocess.CompletedProcess:
    cmd = build_render_command(params)
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Blender's own print() output (including everything
        # DEMGrainsBlenderEarthCam.py prints while exec()'d) goes to stdout;
        # an uncaught Python traceback goes to stderr. A failure can land in
        # either stream, so combine both before taking the tail.
        combined = (result.stdout or "") + "\n" + (result.stderr or "")
        tail = "\n".join(combined.splitlines()[-40:])
        raise RenderError(f"blender exited {result.returncode}:\n{tail}")
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
wsl.exe bash -lc "cd /home/mboyle/Honours && git add sobol/tui_sim_render.py sobol/tests/test_tui_sim_render.py && git commit -m \"\$(cat <<'EOF'
Add render stage wrapper (build_render_command, run_render_stage)

build_render_command() is a pure function (easy to unit test in full);
run_render_stage() shells out to Windows blender.exe via the /mnt/c/
interop path and raises RenderError with the last ~40 lines of combined
stdout+stderr on a non-zero exit (Blender's own print output and a Python
traceback can each land in either stream).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)\""
```

---

### Task 6: Pipeline orchestrator — `run_pipeline()`

**Files:**
- Modify: `sobol/tui_sim_render.py`
- Modify: `sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: `run_sim_stage`, `run_convert_stage`, `run_render_stage` (Tasks 3-5, called by name so tests can monkeypatch each independently), `_grains_and_bodies_dirs`, `_render_output_dir` (Task 4), `SimParams`, `RenderFormValues`, `RenderParams`, `PipelineResult` (Task 2).
- Produces: `run_pipeline(sim_params: SimParams, render_form: RenderFormValues, base_output_dir: Path) -> PipelineResult`, called directly by the Textual worker in Task 8.

- [ ] **Step 1: Write the failing test**

Append to `sobol/tests/test_tui_sim_render.py`:

```python
def _ok_record(run_dir="sobol_mass_runs/batch/run_0001"):
    return tsr.RunRecord(
        run_id=1, mass_input_kg=float("nan"), run_dir=run_dir, status="ok",
        closest_approach_km=1.0, closest_approach_au=0.01, error="",
    )


def test_run_pipeline_stops_after_failed_sim(monkeypatch):
    bad_record = tsr.RunRecord(
        run_id=1, mass_input_kg=float("nan"), run_dir="sobol_mass_runs/batch/run_0001",
        status="phantomsetup_failed", closest_approach_km=float("nan"),
        closest_approach_au=float("nan"), error="phantomsetup exited 1",
    )
    monkeypatch.setattr(tsr, "run_sim_stage", lambda params: bad_record)
    convert_mock = MagicMock()
    render_mock = MagicMock()
    monkeypatch.setattr(tsr, "run_convert_stage", convert_mock)
    monkeypatch.setattr(tsr, "run_render_stage", render_mock)

    result = tsr.run_pipeline(tsr.SimParams(), tsr.RenderFormValues(), Path("/mnt/c/.../DEMCSVs"))

    assert result.stage == "sim"
    assert result.ok is False
    assert "phantomsetup exited 1" in result.message
    convert_mock.assert_not_called()
    render_mock.assert_not_called()


def test_run_pipeline_stops_after_failed_convert(monkeypatch):
    monkeypatch.setattr(tsr, "run_sim_stage", lambda params: _ok_record())

    def boom_convert(record, base_output_dir):
        raise tsr.ConvertError("conversion failed: bad dump")
    monkeypatch.setattr(tsr, "run_convert_stage", boom_convert)
    render_mock = MagicMock()
    monkeypatch.setattr(tsr, "run_render_stage", render_mock)

    result = tsr.run_pipeline(tsr.SimParams(), tsr.RenderFormValues(), Path("/mnt/c/.../DEMCSVs"))

    assert result.stage == "convert"
    assert result.ok is False
    assert "bad dump" in result.message
    render_mock.assert_not_called()


def test_run_pipeline_stops_after_failed_render(monkeypatch):
    monkeypatch.setattr(tsr, "run_sim_stage", lambda params: _ok_record())
    monkeypatch.setattr(tsr, "run_convert_stage", lambda record, base_output_dir: None)

    def boom_render(params):
        raise tsr.RenderError("blender exited 1:\nsome error")
    monkeypatch.setattr(tsr, "run_render_stage", boom_render)

    result = tsr.run_pipeline(tsr.SimParams(), tsr.RenderFormValues(), Path("/mnt/c/.../DEMCSVs"))

    assert result.stage == "render"
    assert result.ok is False
    assert "some error" in result.message


def test_run_pipeline_full_success(monkeypatch):
    record = _ok_record()
    monkeypatch.setattr(tsr, "run_sim_stage", lambda params: record)
    monkeypatch.setattr(tsr, "run_convert_stage", lambda rec, base_output_dir: None)

    captured = {}
    def fake_render(params):
        captured["params"] = params
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    monkeypatch.setattr(tsr, "run_render_stage", fake_render)

    sim_params = tsr.SimParams(output_root=Path("sobol_mass_runs/batch"))
    render_form = tsr.RenderFormValues(resolution="640x360", samples=8, camera_mode="grain_only")
    result = tsr.run_pipeline(sim_params, render_form, Path("/mnt/c/.../DEMCSVs"))

    assert result.stage == "done"
    assert result.ok is True
    rp = captured["params"]
    assert rp.grains_dir == Path("/mnt/c/.../DEMCSVs") / "batch" / "run_0001_grains_output"
    assert rp.bodies_dir == Path("/mnt/c/.../DEMCSVs") / "batch" / "run_0001_bodies_output"
    assert rp.output_dir == Path("/mnt/c/.../DEMCSVs") / "batch" / "run_0001_render"
    assert rp.resolution == "640x360"
    assert rp.samples == 8
    assert rp.camera_mode == "grain_only"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v -k run_pipeline"`
Expected: FAIL — `AttributeError: module 'tui_sim_render' has no attribute 'run_pipeline'`.

- [ ] **Step 3: Write minimal implementation**

Append to `sobol/tui_sim_render.py`, after `run_render_stage()`:

```python
def run_pipeline(sim_params: SimParams, render_form: RenderFormValues, base_output_dir: Path) -> PipelineResult:
    """Sim -> convert -> render, stopping at the first failed stage."""
    record = run_sim_stage(sim_params)
    if record.status != "ok":
        return PipelineResult(
            stage="sim", ok=False,
            message=record.error or f"sim ended with status={record.status!r}",
            record=record,
        )

    try:
        run_convert_stage(record, base_output_dir)
    except ConvertError as exc:
        return PipelineResult(stage="convert", ok=False, message=str(exc), record=record)

    run_dir = Path(record.run_dir)
    grains_dir, bodies_dir = _grains_and_bodies_dirs(run_dir, base_output_dir, sim_params.output_root)
    output_dir = _render_output_dir(run_dir, base_output_dir, sim_params.output_root)
    render_params = RenderParams(
        grains_dir=grains_dir,
        bodies_dir=bodies_dir,
        output_dir=output_dir,
        resolution=render_form.resolution,
        samples=render_form.samples,
        fps=render_form.fps,
        max_frames=render_form.max_frames,
        camera_mode=render_form.camera_mode,
    )
    try:
        run_render_stage(render_params)
    except RenderError as exc:
        return PipelineResult(stage="render", ok=False, message=str(exc), record=record)

    return PipelineResult(stage="done", ok=True, message=f"rendered to {output_dir}", record=record)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: PASS (18 tests).

- [ ] **Step 5: Commit**

```bash
wsl.exe bash -lc "cd /home/mboyle/Honours && git add sobol/tui_sim_render.py sobol/tests/test_tui_sim_render.py && git commit -m \"\$(cat <<'EOF'
Add pipeline orchestrator (run_pipeline) chaining sim -> convert -> render

Stops at the first failed stage and reports which one via PipelineResult.
This is the function the Textual UI's worker thread will call directly --
fully covered by mocked-stage tests before any widget exists.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)\""
```

---

### Task 7: Preflight check — `blender.exe` reachability at startup

**Files:**
- Modify: `sobol/tui_sim_render.py`
- Modify: `sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: `BLENDER_EXE` (Task 2).
- Produces: `check_blender_exe(path: str = BLENDER_EXE) -> None`, raises `FileNotFoundError` with a clear message if missing; called once at TUI startup in Task 8, before the sim form is even shown (spec's error-handling table: "Fail fast before running the sim at all").

- [ ] **Step 1: Write the failing test**

Append to `sobol/tests/test_tui_sim_render.py`:

```python
def test_check_blender_exe_raises_when_missing(tmp_path):
    missing = tmp_path / "does_not_exist" / "blender.exe"
    with pytest.raises(FileNotFoundError, match=str(missing)):
        tsr.check_blender_exe(str(missing))


def test_check_blender_exe_passes_when_present(tmp_path):
    fake_exe = tmp_path / "blender.exe"
    fake_exe.write_text("not a real binary, just needs to exist")
    tsr.check_blender_exe(str(fake_exe))  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v -k check_blender_exe"`
Expected: FAIL — `AttributeError: module 'tui_sim_render' has no attribute 'check_blender_exe'`.

- [ ] **Step 3: Write minimal implementation**

Append to `sobol/tui_sim_render.py`, after the `BLENDER_EXE`/`DEM_HEADLESS_RENDER` constants:

```python
def check_blender_exe(path: str = BLENDER_EXE) -> None:
    if not Path(path).is_file():
        raise FileNotFoundError(
            f"blender.exe not found at {path} -- confirm the Blender 5.2.1 LTS "
            "install path (see CLAUDE.md) or update BLENDER_EXE in tui_sim_render.py."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: PASS (20 tests).

- [ ] **Step 5: Commit**

```bash
wsl.exe bash -lc "cd /home/mboyle/Honours && git add sobol/tui_sim_render.py sobol/tests/test_tui_sim_render.py && git commit -m \"\$(cat <<'EOF'
Add check_blender_exe() startup preflight for sim+render pipeline TUI

Fails fast with a clear message if blender.exe isn't at the expected path,
before the sim form is even shown -- avoids running a real PHANTOM sim only
to discover the render stage can never succeed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)\""
```

---

### Task 8: Textual UI — form, worker thread, status reporting

**Files:**
- Modify: `sobol/tui_sim_render.py`
- Modify: `sobol/tests/test_tui_sim_render.py`

**Interfaces:**
- Consumes: everything from Tasks 2-7 (`SimParams`, `RenderFormValues`, `run_pipeline`, `check_blender_exe`, `RunSample`, `DEFAULT_DN_COHES_FACTOR`). Also imports `coh_gap_max_cgs_from_dn` from `run_mass_sobol_phantom` (keyword-only signature: `coh_gap_max_cgs_from_dn(*, dn: float, np_apophis: int, scale_r_apophis: float = 1.0, r_apophis_km: float = HORIZONS_APOPHIS_RADIUS_KM) -> float`).
- Produces: `SimRenderTUIApp` (Textual `App` subclass) and `main()` entry point. Nothing downstream depends on this task — it is the top of the stack.

- [ ] **Step 1: Write the app**

Add these imports to the top of `sobol/tui_sim_render.py` (alongside the existing ones):

```python
try:
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, ScrollableContainer
    from textual.widgets import Button, Footer, Header, Input, Select, Static
except ImportError:
    sys.exit(
        "textual is not installed.\n"
        "Run:  pip install textual\n"
        "(sobol/tui_run.py already depends on it, so it should already be present.)"
    )

from run_mass_sobol_phantom import coh_gap_max_cgs_from_dn  # noqa: E402
```

Append this pure helper (no `bpy`/Textual dependency, easy to unit-test on its own) right after `check_blender_exe()`:

```python
_PER_SPHERE_GRAIN_WARN_THRESHOLD = 2000


def warn_if_high_grain_count(np_apophis: int) -> Optional[str]:
    """Non-blocking warning: this pipeline is per-sphere only (see CLAUDE.md's
    pipeline-comparison table) -- composite/instancing exist precisely
    because per-sphere degrades above ~2000 grains.
    """
    if np_apophis <= _PER_SPHERE_GRAIN_WARN_THRESHOLD:
        return None
    return (
        f"Warning: np_apophis={np_apophis} — per-sphere path is intended for "
        f"≤{_PER_SPHERE_GRAIN_WARN_THRESHOLD} grains; consider the composite or "
        "instancing path instead. "
    )
```

Append the `_Row` helper (duplicated from `sobol/tui_run.py` deliberately — it's ~15 lines and self-contained; `tui_run.py` doesn't export it, and this feature doesn't touch that file) and the app class at the end of `sobol/tui_sim_render.py`:

```python
class _Row(Horizontal):
    """Label + interactive widget on a single row. Same layout as tui_run.py's _Row."""

    DEFAULT_CSS = """
    _Row { height: 3; }
    _Row .rl { width: 26; content-align: right middle; padding-right: 1; color: $text-muted; }
    _Row .rw { width: 1fr; }
    _Row .rh { width: 15; content-align: left middle; padding-left: 1; color: $text-muted; text-style: italic; }
    """

    def __init__(self, label: str, widget, hint: str = "", **kw) -> None:
        super().__init__(**kw)
        self._label = label
        self._widget = widget
        self._hint = hint

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="rl")
        self._widget.add_class("rw")
        yield self._widget
        if self._hint:
            yield Static(self._hint, classes="rh")


class SimRenderTUIApp(App[None]):
    """Configure one PHANTOM DEM run -> run -> convert -> render, in one screen."""

    TITLE = "PHANTOM \u00b7 Sim + Render"
    SUB_TITLE = "configure -> run -> convert -> render"

    DEFAULT_CSS = """
    Screen { background: $surface; }
    #scroll { height: 1fr; border: solid $primary; margin: 0 1; padding: 0 2; }
    .sec { color: $accent; text-style: bold; padding: 1 0 0 0; }
    #bar { height: 5; padding: 1 2; background: $surface-darken-1; border-top: solid $primary; align: center middle; }
    #status { width: 1fr; content-align: left middle; padding-left: 2; }
    .err { color: $error; }
    .ok  { color: $success; }
    Button { margin: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Header()
        with ScrollableContainer(id="scroll"):
            yield Static("Sim — paths", classes="sec")
            yield _Row("prefix", Input("sobol", id="prefix"))
            yield _Row("base_dir", Input(".", id="base-dir"), "dir")
            yield _Row("phantom_dir", Input(".", id="phantom-dir"), "dir")
            yield _Row("output_root", Input("sobol_mass_runs", id="output-root"), "dir")
            yield _Row(
                "ephemeris_cache_dir",
                Input("", id="eph-cache", placeholder="(none — skips Horizons download)"),
                "optional dir",
            )

            yield Static("Sim — parameters", classes="sec")
            yield _Row("np_apophis", Input("500", id="np-apophis"), "int")
            yield _Row("spin_period (hr)", Input("", id="spin-period", placeholder="(template default)"), "hr")
            yield _Row("spin_torque_align (deg)", Input("", id="spin-torque-align", placeholder="0-180"), "deg")
            yield _Row("kt_cgs", Input("0", id="kt-cgs"), "dyne/cm")
            yield _Row("dn_cohes_factor", Input(str(DEFAULT_DN_COHES_FACTOR), id="dn-cohes-factor"), "float")
            yield _Row("tmax (hr)", Input("", id="tmax-hours", placeholder="(template default)"), "hr")
            yield _Row("dtmax (hr)", Input("", id="dtmax-hours", placeholder="(template default)"), "hr")
            yield _Row("sink_earth_id", Input(str(EARTH_SINK_ID_DEFAULT), id="sink-earth"), "int")
            yield _Row("sink_apophis_id", Input(str(APOPHIS_SINK_ID_DEFAULT), id="sink-apophis"), "int")

            yield Static("Render", classes="sec")
            yield _Row("resolution", Input("1920x1080", id="resolution"), "WxH")
            yield _Row("samples", Input("128", id="samples"), "int")
            yield _Row("fps", Input("24", id="fps"), "int")
            yield _Row("max_frames", Input("", id="max-frames", placeholder="(all frames)"), "int, optional")
            yield _Row(
                "camera_mode",
                Select([("auto", "auto"), ("grain_only", "grain_only")], value="auto", id="camera-mode"),
            )

        with Horizontal(id="bar"):
            yield Button("Run Pipeline", id="btn-run", variant="success")
            yield Button("Dry Run", id="btn-dryrun", variant="warning")
            yield Button("Quit", id="btn-quit", variant="error")
            yield Static("Ready.", id="status")
        yield Footer()

    def on_mount(self) -> None:
        try:
            check_blender_exe()
        except FileNotFoundError as exc:
            self._set_status(str(exc), error=True)

    def _set_status(self, msg: str, *, error: bool = False) -> None:
        s = self.query_one("#status", Static)
        s.update(msg)
        s.remove_class("err", "ok")
        s.add_class("err" if error else "ok")

    def _iv(self, wid: str) -> str:
        return self.query_one(f"#{wid}", Input).value.strip()

    def _build_sim_params(self, dry_run: bool) -> SimParams:
        np_apophis = int(self._iv("np-apophis"))
        dn = float(self._iv("dn-cohes-factor") or DEFAULT_DN_COHES_FACTOR)
        kt_cgs = float(self._iv("kt-cgs") or "0")
        coh_gap_max_cgs = (
            coh_gap_max_cgs_from_dn(dn=dn, np_apophis=np_apophis) if kt_cgs > 0 else None
        )
        sample = RunSample(
            use_dem=True,
            np_apophis=np_apophis,
            apophis_spin_period=float(self._iv("spin-period")) if self._iv("spin-period") else None,
            apophis_spin_torque_align_deg=(
                float(self._iv("spin-torque-align")) if self._iv("spin-torque-align") else None
            ),
            kt_cgs=kt_cgs,
            coh_gap_max_cgs=coh_gap_max_cgs,
            tmax_hours=float(self._iv("tmax-hours")) if self._iv("tmax-hours") else None,
            dtmax_hours=float(self._iv("dtmax-hours")) if self._iv("dtmax-hours") else None,
        )
        eph_cache_raw = self._iv("eph-cache")
        return SimParams(
            prefix=self._iv("prefix"),
            base_dir=Path(self._iv("base-dir")),
            phantom_dir=Path(self._iv("phantom-dir")),
            output_root=Path(self._iv("output-root")),
            ephemeris_cache_dir=Path(eph_cache_raw) if eph_cache_raw else None,
            dry_run=dry_run,
            earth_sink_id=int(self._iv("sink-earth")),
            apophis_sink_id=int(self._iv("sink-apophis")),
            sample=sample,
        )

    def _build_render_form(self) -> RenderFormValues:
        max_frames_raw = self._iv("max-frames")
        camera_mode = self.query_one("#camera-mode", Select).value
        return RenderFormValues(
            resolution=self._iv("resolution"),
            samples=int(self._iv("samples")),
            fps=int(self._iv("fps")),
            max_frames=int(max_frames_raw) if max_frames_raw else None,
            camera_mode=str(camera_mode),
        )

    @on(Button.Pressed, "#btn-run")
    def _on_run(self) -> None:
        self._launch(dry_run=False)

    @on(Button.Pressed, "#btn-dryrun")
    def _on_dryrun(self) -> None:
        self._launch(dry_run=True)

    @on(Button.Pressed, "#btn-quit")
    def _on_quit(self) -> None:
        self.exit(None)

    def _launch(self, dry_run: bool) -> None:
        try:
            sim_params = self._build_sim_params(dry_run)
            render_form = self._build_render_form()
        except ValueError as exc:
            self._set_status(f"Error: {exc}", error=True)
            return
        warning = warn_if_high_grain_count(sim_params.sample.np_apophis) or ""
        self._set_status(f"{warning}{'Dry run...' if dry_run else 'Running...'}")
        self._run_pipeline_worker(sim_params, render_form)

    @work(thread=True)
    def _run_pipeline_worker(self, sim_params: SimParams, render_form: RenderFormValues) -> None:
        result = run_pipeline(sim_params, render_form, _REPO_WIN_CODE / "DEMCSVs")
        self.call_from_thread(self._report_result, result)

    def _report_result(self, result: PipelineResult) -> None:
        if result.ok:
            self._set_status(f"Done ({result.stage}): {result.message}", error=False)
        else:
            self._set_status(f"Failed at {result.stage}: {result.message}", error=True)


def main() -> None:
    SimRenderTUIApp().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write the integration test**

Append to `sobol/tests/test_tui_sim_render.py`:

```python
import pytest


def test_warn_if_high_grain_count_below_threshold():
    assert tsr.warn_if_high_grain_count(500) is None
    assert tsr.warn_if_high_grain_count(2000) is None  # boundary is inclusive


def test_warn_if_high_grain_count_above_threshold():
    msg = tsr.warn_if_high_grain_count(5000)
    assert msg is not None
    assert "5000" in msg
    assert "2000" in msg


@pytest.mark.asyncio
async def test_dry_run_stops_before_convert_and_render(monkeypatch):
    dry_run_record = tsr.RunRecord(
        run_id=1, mass_input_kg=float("nan"), run_dir="sobol_mass_runs/batch/run_0001",
        status="prepared_only", closest_approach_km=float("nan"),
        closest_approach_au=float("nan"), error="",
    )
    monkeypatch.setattr(tsr, "run_sim_stage", lambda params: dry_run_record)
    convert_mock = MagicMock()
    render_mock = MagicMock()
    monkeypatch.setattr(tsr, "run_convert_stage", convert_mock)
    monkeypatch.setattr(tsr, "run_render_stage", render_mock)
    monkeypatch.setattr(tsr, "check_blender_exe", lambda *a, **kw: None)

    app = tsr.SimRenderTUIApp()
    async with app.run_test() as pilot:
        await pilot.click("#btn-dryrun")
        await pilot.pause(0.2)  # let the worker thread + call_from_thread land

        status = app.query_one("#status", tsr.Static)
        assert "Failed at sim" in status.renderable or "prepared_only" in str(status.renderable)

    convert_mock.assert_not_called()
    render_mock.assert_not_called()
```

Note: this test requires `pytest-asyncio` (Textual's `run_test()` is async). If it isn't already installed in the WSL Python environment, install it: `pip3 install pytest-asyncio` and confirm/add `asyncio_mode = auto` under `[tool.pytest.ini_options]` in `sobol/pyproject.toml` if one exists, otherwise add a `sobol/pytest.ini` with:

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Run test to verify it passes**

Run: `wsl.exe bash -lc "cd /home/mboyle/Honours/sobol && python3 -m pytest tests/test_tui_sim_render.py -v"`
Expected: PASS (23 tests, including the new async one). If `pytest-asyncio` was just installed, re-run once after adding the ini setting.

- [ ] **Step 4: Manual end-to-end verification (not automatable — needs a real PHANTOM binary + real Blender)**

1. Launch: `wsl.exe bash -lc "cd /home/mboyle/Honours && python3 sobol/tui_sim_render.py"`
2. Set `np_apophis=500` (the project's standard OBJ-crop grain count — see `CLAUDE.md`'s "typical ~500"), `dtmax_hours=0.5`, `tmax_hours=1.0` (short run), leave everything else default, set `max_frames=3`, `resolution=640x360`, `samples=16`.
3. Press **Dry Run** — status should show a failure at stage `sim` mentioning `prepared_only`/no error, confirming components 2-3 never ran (check no new dirs appear under `output_root` beyond the prepared one, and no Blender process starts).
4. Press **Run Pipeline** — wait for PHANTOM to finish (should be fast at these settings), then confirm the status bar reports `Done (done): rendered to .../run_0001_render`, and that directory contains 3 `frame_*.png` files.
5. Confirm the output directory matches the pattern from Task 4's helpers: `DEMCSVs/<output_root name>/run_0001_render/`.

- [ ] **Step 5: Commit**

```bash
wsl.exe bash -lc "cd /home/mboyle/Honours && git add sobol/tui_sim_render.py sobol/tests/test_tui_sim_render.py sobol/pytest.ini && git commit -m \"\$(cat <<'EOF'
Wire Textual UI for the sim+render pipeline TUI

Single-screen form (sim params + render params, including ephemeris cache
dir) over run_pipeline() from the prior tasks. Reuses tui_run.py's _Row
layout pattern (duplicated, not imported, to avoid touching the working
sweep TUI for this feature). Dry-run and real-run share the same
worker-thread path; failure is reported per-stage in the status bar, and
a non-blocking warning fires above the per-sphere path's ~2000-grain
practical ceiling.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_019zxzGNqhW7MAdfm15iHE6s
EOF
)\""
```

---

### Task 9: Document the pipeline in `CLAUDE.md` (Windows repo)

**Files:**
- Modify: `CLAUDE.md` (Windows, gitignored — kept accurate on disk per this repo's established convention even though `git add` will refuse it; see the "Directory layout"/"Blender script architecture" precedent for every other pipeline addition in this file)

**Interfaces:**
- Consumes: nothing — this is documentation, not code.
- Produces: nothing consumed by another task; this is the last task.

- [ ] **Step 1: Add `DEMHeadlessRender.py` to the numbered Blender script list**

In the "Blender script architecture" section, after the existing entry `12. **DEMBulkInstanceBlender.py**...`, add:

```markdown
13. **`DEMHeadlessRender.py`** — Headless-only per-sphere render, driven by `sobol/tui_sim_render.py` (WSL) rather than pasted into the Scripting tab. Text-patches `DEMGrainsBlenderEarthCam.py`'s `GRAINS_DIR`/`BODIES_CSV_DIR`/`CAMERA_MODE` constants and `exec()`s it (same technique `run_demtocsv_batch.py` uses on `DEMDumpConvert.py`), then sets Cycles resolution/samples/fps and renders a PNG sequence via `bpy.ops.render.render(animation=True)`. See **Sim + render pipeline TUI** below.
```

(Renumber the existing "Benchmark / measurement scripts" heading and its two entries, `P0_InstancingSpike.py` and `synthetic_flyby_test.py`, from 13/14 to 14/15.)

- [ ] **Step 2: Add a new "Sim + render pipeline TUI" subsection under Key commands**

After the "Pure instancing viz" subsection (before "GN instancing performance spike"), add:

```markdown
### Sim + render pipeline TUI (WSL orchestrator, one command end-to-end)

`sobol/tui_sim_render.py` (WSL repo) configures one PHANTOM DEM run, runs
it, converts the dumps, and renders a per-sphere Blender clip headless —
one run per launch (`sobol/tui_run.py` covers Sobol sweeps). It calls
`run_mass_sobol_phantom.py`'s `preflight()`/`run_one_case()` and
`run_demtocsv_batch.py`'s `run_dem_dump_convert()` directly (no
reimplementation), then shells out to Windows `blender.exe` via the WSL
`/mnt/c/` interop mount to run `BlenderConvert/DEMHeadlessRender.py`.

```bash
cd /home/mboyle/Honours
python3 sobol/tui_sim_render.py
```

Per-sphere only (`DEMGrainsBlenderEarthCam.py`) — the TUI warns, without
blocking, above `np_apophis=2000`; use the composite or instancing path
(and their own preprocess scripts) for higher grain counts. Output PNG
sequence lands at `DEMCSVs/<sim_name>/<run_name>_render/`, a sibling of
the `_grains_output/`/`_bodies_output/` folders `run_dem_dump_convert()`
already writes. No automatic video encode — see "Combining a rendered
image sequence into a video" above for the manual follow-up step.

Design spec: `docs/superpowers/specs/2026-09-14-sim-render-pipeline-tui-design.md`.
```

- [ ] **Step 3: Commit**

`CLAUDE.md` is gitignored (deny-all-with-allowlist `.gitignore`, confirmed via `git check-ignore -v CLAUDE.md`) — there is nothing to stage or commit for this task. The edit stands on disk only, same as every other `CLAUDE.md` update made in this project's history. Skip `git add`/`git commit` for this task entirely.

---

## Self-Review Notes (writing-plans skill checklist, already applied)

- **Spec coverage:** Component 1 (sim form) -> Tasks 2, 3, 8. Component 2 (convert) -> Task 4. Component 3 (render form) -> Task 8. Component 4 (`DEMHeadlessRender.py`) -> Task 1. Component 5 (invoking Blender) -> Tasks 2, 5. Error handling table -> Task 6's four tests map 1:1 to its four rows (the fourth row, "blender.exe not found," is instead covered by Task 7's preflight check, checked once at startup per the spec's own wording). Verification plan items 1/2/3 -> Task 1 Step 2, Task 8 Step 4 (dry-run + real run) respectively.
- **Placeholder scan:** no TBD/TODO; every code step is complete, runnable code with exact values, not descriptions.
- **Type consistency:** `RunRecord`/`RunSample` fields used exactly as `run_mass_sobol_phantom.py` defines them (verified by reading the source, not guessed). `RenderParams`/`RenderFormValues`/`SimParams`/`PipelineResult` field names introduced in Task 2 are used identically in every later task — no renames.
- **Correction applied during planning:** the spec's Component 4 code incorrectly patched `IMPORT_SOLAR_SYSTEM` for `--camera-mode grain_only`; `DEMGrainsBlenderEarthCam.py` line 97 has a separate `CAMERA_MODE` variable for exactly this purpose. Task 1 and the spec document have both been corrected to patch `CAMERA_MODE` instead.

### Addendum: external review pass (post-write-up, before implementation)

A second review of the spec caught issues the self-review above missed. Each is addressed:

| # | Issue | Resolution |
|---|---|---|
| 1 | Spec's Component 3 table still said `grain_only` forces `IMPORT_SOLAR_SYSTEM = False`, contradicting the already-fixed Component 4 code | Fixed: spec's Component 3 table now names `CAMERA_MODE` and explicitly says `IMPORT_SOLAR_SYSTEM` is untouched. |
| 2 | Post-convert path derivation (`grains_dir`/`bodies_dir`) had no snippet in the spec, unlike Components 1-2 | Fixed: added a "Post-convert path wiring" subsection to spec Component 2 with the exact derivation, matching the plan's `_grains_and_bodies_dirs()` (Task 4) — same logic, now documented in both places. |
| 3 | Render output directory convention was never defined | Fixed: `DEMCSVs/<sim_name>/<run_name>_render/` (sibling of `_grains_output/`/`_bodies_output/`) — added to the spec and already implemented as `_render_output_dir()` in the plan's Task 4. |
| 4 | Blender failures can print to stdout, not just stderr — `run_render_stage()`'s original `result.stderr`-only tail could miss the actual error | Fixed in both spec and plan (Task 5): combine `stdout + stderr` before taking the last ~40 lines; added a regression test (`test_run_render_stage_failure_reads_stdout_only_traceback`) for the stdout-only-failure case. |
| 5 | No guardrail against using the per-sphere path with a grain count that makes it impractical | Added `warn_if_high_grain_count()` (Task 8) — non-blocking status-bar warning above `np_apophis=2000`, matching this repo's own per-sphere-vs-composite/instancing cutoff (`CLAUDE.md`'s pipeline-comparison table). Not a hard block: this stays a "hero shot" tool, and the threshold is a practical guideline, not a correctness constraint. |
| 6 | UI flow timing (one screen vs. wizard) was implicit | Made explicit in the spec's Architecture section: single screen, all fields at once, submit runs all three stages in sequence in one worker thread — this is what Task 8 already built. |
| 7 | Component 1's form table didn't list `ephemeris_cache_dir` (accepted by `run_one_case()`) or an explicit "dry run" control | `ephemeris_cache_dir` added as a real gap: new field in Task 8's compose() and `_build_sim_params()`, plus a row in the spec's Component 1 table. "Dry run" was already covered by the existing **Dry Run** button (mirrors `tui_run.py`'s Run/Dry-run pair) — documented explicitly in the spec table rather than changed, since a second checkbox would just duplicate the button. |

Declined / deferred, with reasoning:

- **Minor #1 (public alias for `_min_dem_grains_from_setup`):** not made. `run_demtocsv_batch.py`'s own `main()` already treats this name as internal-but-reusable; adding a public alias for one new caller is scope creep on a file this plan doesn't otherwise need to touch.
- **Minor #2 (streamed render progress) and #3 (mid-pipeline cancel):** accepted as v1 limitations, now listed explicitly under the spec's Extension points rather than left implicit.
- **Minor #4 (update `CLAUDE.md`):** not declined — added as Task 9.
- **Minor #5 (`exec()` regex fragility guard):** already handled before this review — Task 1's `_patch_and_exec()` uses `re.subn` and raises `RuntimeError` if a pattern doesn't match exactly once, rather than silently `exec()`-ing an unpatched script.
- **Minor #6 (`tui_run.py` subprocesses instead of using a worker thread):** deliberate difference, unchanged — `tui_run.py` shells out to a whole separate `run_mass_sobol_phantom.py` process because it can trigger a multi-run parallel sweep; this TUI calls `run_one_case()` in-process because it's always exactly one run, and a worker thread is the simpler fit for keeping the Textual event loop responsive around a single blocking call.
- **Recommendation ("assert `scene.render.engine == 'CYCLES'` in the smoke test"):** not added as a separate check — `DEMHeadlessRender.py` (Task 1) sets `scene.render.engine = 'CYCLES'` unconditionally itself, so this holds by construction rather than by assumption; the reviewer's concern (`DEMGrainsBlenderEarthCam.py` doesn't set it) is exactly why the headless script sets it after the `exec()`, not before.
- **Recommendation (bump manual e2e's `np_apophis` from 250 to something more representative):** done — Task 8 Step 4 now uses `np_apophis=500`, this repo's standard OBJ-crop grain count.
- **Future idea ("skip sim, render existing run" mode):** added to the spec's Extension points; not implemented now (out of scope per the spec's own Non-goals — this plan renders only a run it just produced).
