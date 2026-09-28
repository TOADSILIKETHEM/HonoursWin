# DEM Grains CSV → npz Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `CSVconvert/DEMtoCSV.py` writes per-frame DEM grain data as compressed `.npz` instead of CSV, and all six grain readers read it, with output that matches the CSV era.

**Architecture:** The converter writes one `np.savez_compressed` file per dump into the same `_grains_output/` folder. Each reader calls `np.load` directly; there is no shared helper module. Bodies stay CSV. Verification is before/after: Task 1 regenerates a CSV reference from real WSL dumps with the unchanged code and captures every reader's output. Each later task changes one reader group and compares its output against that capture.

**Tech Stack:** Python 3 + numpy + pandas + sarracen (WSL, for conversion); Windows `.venv` (numpy, pandas, scipy); Blender 5.2.1 LTS bundled Python (headless `--background`).

**Spec:** `docs/superpowers/specs/2026-09-13-dem-grains-npz-migration-design.md`

## Global Constraints

- Run every command from `C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code` in PowerShell, unless the command is `wsl.exe …`.
- Blender executable: `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe` (5.2.1 LTS). Always pass `--background --factory-startup --python-exit-code 1`.
- **Do not commit or push anything.** The user tests first and commits only when they ask.
- **Leave existing uncommitted work alone.** `DEMBulkVizBlender.py` and `viz/viz_preprocess.py` already hold uncommitted changes. Edit on top of them; never stash, revert or checkout.
- Grains become npz. Bodies stay CSV. No dual CSV/npz reading. No shared `viz/grain_npz.py` module. No pickled objects.
- npz keys, exactly these 24: `grain_id time_s x_au y_au z_au x_km y_km z_km x_rel_km y_rel_km z_rel_km Reff_km h_km x_vis y_vis z_vis Reff_vis m vx vy vz spinx spiny spinz`.
- dtypes: `grain_id` is `int64`; `time_s` is a 0-d `float64`; every other key is `float64`, shape `(n,)`.
- Do not rename these: `DEMtoCSV.py`, the config variables `GRAINS_CSV_DIR` / `BODIES_CSV_DIR` / `GRAIN_CSV_DIR`, or the manifest keys `grains_csv_dir` / `bodies_csv_dir`.
- Do not modify anything in the WSL repo (`\\wsl.localhost\Ubuntu\home\mboyle\Honours`).
- No new dependencies. pytest is not installed. Checks are plain Python scripts in `DEMCSVs\_npz_check\tools\`; that folder is gitignored and is test scaffolding, not deliverable code.
- Test run: WSL `sobol_mass_runs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001`. It has 4 dumps (`sobol_00000`…`sobol_00003`), `np_apophis=500`, and `apophis_only=F`, so its bodies CSVs include Earth.
- Tolerances:
  - CSV ↔ npz values: exact.
  - Preprocess outputs: relative `1e-12`, because array layout changes summation order.
  - Blender transforms: absolute `1e-9` BU.

## File Structure

| Path | Change | Responsibility |
|------|--------|----------------|
| `CSVconvert/DEMtoCSV.py` | Modify | Build grain arrays and write `<dump>.npz`; the bodies CSV is unchanged |
| `viz/viz_preprocess.py` | Modify | `_load_grains` reads npz; glob `*.npz`; `--input-mode` npz |
| `viz/viz_preprocess_lite.py` | Modify | `reference_scale_from_run` reads npz |
| `BlenderConvert/DEMGrainsBlenderEarthCam.py` | Modify | npz grains, bodies lookup by stem, vectorised `_grain_core` |
| `BlenderConvert/DEMGrainsBlenderEarth.py` | Modify | npz grains, bodies lookup by stem |
| `BlenderConvert/DEMCamera.py` | Modify | npz grains, vectorised `_grain_core` |
| `BlenderConvert/DEMBulkVizBlender.py` | Modify | camera core from npz; warn when no grain files |
| `CLAUDE.md`, `docs/BATCHES_VIZ.md` | Modify | Grains schema and wording (both files are untracked by git) |
| `DEMCSVs/_npz_check/tools/*.py` | Create | Test harness; gitignored |

Test data layout (all created by the tasks, all under `DEMCSVs\_npz_check\`):

```
csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\   ← CSV reference (Task 1, unchanged code)
csv\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output\
csv\sobol_20260705_131545_baseline_58deg\run_0001_viz\             ← preprocess reference (Task 1)
npz\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\   ← migrated output (Task 2)
npz\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output\
npz\sobol_20260705_131545_baseline_58deg\run_0001_viz\             ← preprocess after (Task 3)
configs\  snapshots\  results\  tools\
```

---

### Task 1: Test harness and CSV-era baseline

Every capture in this task uses the **unchanged** code. Do not edit any repo file in this task.

**Files:**
- Create: `DEMCSVs/_npz_check/tools/run_patched.py`
- Create: `DEMCSVs/_npz_check/tools/make_blender_configs.py`
- Create: `DEMCSVs/_npz_check/tools/check_snapshot.py`
- Create: `DEMCSVs/_npz_check/tools/compare_snapshots.py`
- Create: `DEMCSVs/_npz_check/tools/compare_viz.py`
- Create: `DEMCSVs/_npz_check/tools/refscale.py`
- Create: `DEMCSVs/_npz_check/tools/compare_refscale.py`
- Create: `DEMCSVs/_npz_check/tools/check_roundtrip.py`

**Interfaces:**
- Consumes: nothing.
- Produces, for Tasks 2–5:
  - `run_patched.py -- <config.json>`: runs pasted-style Blender scripts with config overrides, then writes a scene snapshot.
  - `make_blender_configs.py before|after`: writes `configs\{earthcam,earth_plus_camera,bulkviz}_{before|after}.json`.
  - `check_snapshot.py <snap> [--grains-csv F] [--require NAME ...] [--camera-not NAME]`
  - `compare_snapshots.py <before> <after>`
  - `compare_viz.py <before_viz> <after_viz>`
  - `refscale.py -- <grains_dir> <out.json>` (Blender Python)
  - `compare_refscale.py <before> <after>`
  - `check_roundtrip.py <csv_grains> <npz_grains> <csv_bodies> <npz_bodies>`
  - Every checker prints `MATCH` or `PASS` and exits 0 on success; on failure it prints the differences and exits 1.
  - Baseline files: `csv\…\run_0001_{grains,bodies,viz}`, `results\refscale_before.json`, and `snapshots\{earthcam,earth_plus_camera,bulkviz}_before.json`.

- [ ] **Step 1: Create the harness runner**

`DEMCSVs/_npz_check/tools/run_patched.py`:

```python
"""Run pasted-into-Blender scripts headlessly with config overrides, then snapshot the scene.

Usage: blender --background --factory-startup --python-exit-code 1 --python run_patched.py -- config.json
config = {"steps": [{"script": path, "overrides": {NAME: value}}],
          "snapshot": {"out": path, "frames": [1, 2, ...]}}
"""
import json
import re
import sys
from pathlib import Path

import bpy


def patch_source(src, overrides):
    for name, value in overrides.items():
        pattern = re.compile(rf'^{name}\s*=\s*(\([^)]*\)|[^\n]*)$', re.MULTILINE)
        src, n = pattern.subn(lambda _m: f'{name} = {value!r}', src, count=1)
        if n != 1:
            raise SystemExit(f'override {name} not found at top level')
    return src


def run_step(step):
    path = Path(step['script']).resolve()
    src = patch_source(path.read_text(encoding='utf-8'), step.get('overrides', {}))
    print(f'=== run_patched: {path.name}')
    exec(compile(src, str(path), 'exec'), {'__name__': '__main__', '__file__': str(path)})


def snapshot(spec):
    scene = bpy.context.scene
    names = sorted(o.name for o in bpy.data.objects)
    out = {
        'frame_start': scene.frame_start,
        'frame_end': scene.frame_end,
        'camera': scene.camera.name if scene.camera else None,
        'objects': names,
        'frames': {},
    }
    for frame in spec['frames']:
        scene.frame_set(frame)
        out['frames'][str(frame)] = {
            n: {
                'loc': [float(x) for x in bpy.data.objects[n].matrix_world.translation],
                'rot': [float(x) for x in bpy.data.objects[n].matrix_world.to_quaternion()],
            }
            for n in names
        }
    out_path = Path(spec['out'])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=1), encoding='utf-8')
    print(f'snapshot: {len(names)} objects x {len(spec["frames"])} frames -> {out_path}')


cfg = json.loads(Path(sys.argv[sys.argv.index('--') + 1]).read_text(encoding='utf-8'))
for step in cfg['steps']:
    run_step(step)
snapshot(cfg['snapshot'])
```

- [ ] **Step 2: Create the config generator**

`DEMCSVs/_npz_check/tools/make_blender_configs.py`:

```python
"""Write Blender harness configs for one phase: 'before' reads csv/, 'after' reads npz/."""
import json
import sys
from pathlib import Path

CODE = Path('C:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code')
CHECK = CODE / 'DEMCSVs' / '_npz_check'
RUN = 'sobol_20260705_131545_baseline_58deg'
FRAMES = [1, 2, 3, 4]

phase = sys.argv[1]
if phase not in ('before', 'after'):
    raise SystemExit('usage: make_blender_configs.py before|after')
data = CHECK / ('csv' if phase == 'before' else 'npz') / RUN
grains = (data / 'run_0001_grains_output').as_posix() + '/'
bodies = (data / 'run_0001_bodies_output').as_posix() + '/'
bc = (CODE / 'BlenderConvert').as_posix()

configs = {
    'earthcam': [
        {'script': f'{bc}/DEMGrainsBlenderEarthCam.py',
         'overrides': {'GRAINS_CSV_DIR': grains, 'BODIES_CSV_DIR': bodies}},
    ],
    'earth_plus_camera': [
        {'script': f'{bc}/DEMGrainsBlenderEarth.py',
         'overrides': {'GRAINS_CSV_DIR': grains, 'BODIES_CSV_DIR': bodies}},
        {'script': f'{bc}/DEMCamera.py', 'overrides': {'GRAIN_CSV_DIR': grains}},
    ],
    'bulkviz': [
        {'script': f'{bc}/DEMBulkVizBlender.py',
         'overrides': {'VIZ_MANIFEST': (data / 'run_0001_viz' / 'manifest.json').as_posix()}},
    ],
}
out_dir = CHECK / 'configs'
out_dir.mkdir(parents=True, exist_ok=True)
for name, steps in configs.items():
    cfg = {'steps': steps,
           'snapshot': {'out': (CHECK / 'snapshots' / f'{name}_{phase}.json').as_posix(),
                        'frames': FRAMES}}
    path = out_dir / f'{name}_{phase}.json'
    path.write_text(json.dumps(cfg, indent=2), encoding='utf-8')
    print('wrote', path)
```

- [ ] **Step 3: Create the snapshot checkers**

`DEMCSVs/_npz_check/tools/check_snapshot.py`:

```python
"""Sanity-check one scene snapshot: grain object count, required objects, active camera."""
import argparse
import json

p = argparse.ArgumentParser()
p.add_argument('snapshot')
p.add_argument('--grains-csv', help='a grain CSV whose row count is the expected DEM_Grain_ count')
p.add_argument('--require', nargs='*', default=[])
p.add_argument('--camera-not', help='fail if the active camera has this name')
args = p.parse_args()

snap = json.load(open(args.snapshot, encoding='utf-8'))
problems = []
if args.grains_csv:
    with open(args.grains_csv, encoding='utf-8') as fh:
        expected = sum(1 for _ in fh) - 1
    got = sum(n.startswith('DEM_Grain_') for n in snap['objects'])
    if got != expected:
        problems.append(f'DEM_Grain_ objects: {got}, expected {expected}')
missing = [r for r in args.require if r not in snap['objects']]
if missing:
    problems.append(f'missing required objects: {missing}')
if args.camera_not and snap['camera'] == args.camera_not:
    problems.append(f'active camera is {snap["camera"]!r}')
print(f'objects={len(snap["objects"])} camera={snap["camera"]!r} frames={snap["frame_start"]}-{snap["frame_end"]}')
print('\n'.join(problems) if problems else 'PASS')
raise SystemExit(1 if problems else 0)
```

`DEMCSVs/_npz_check/tools/compare_snapshots.py`:

```python
"""Exit 0 iff two scene snapshots match: same objects, frame range, camera; transforms within ABS_TOL."""
import json
import math
import sys

ABS_TOL = 1e-9  # BU; grain-core centroids may differ in the last float digit (summation order)

before, after = (json.load(open(p, encoding='utf-8')) for p in sys.argv[1:3])
errors = []
for key in ('frame_start', 'frame_end', 'camera'):
    if before[key] != after[key]:
        errors.append(f'{key}: {before[key]!r} vs {after[key]!r}')
if before['objects'] != after['objects']:
    errors.append(f'objects before-only={sorted(set(before["objects"]) - set(after["objects"]))} '
                  f'after-only={sorted(set(after["objects"]) - set(before["objects"]))}')
worst = 0.0
for frame, objs in before['frames'].items():
    for name, tr in objs.items():
        other = after['frames'].get(frame, {}).get(name)
        if other is None:
            continue
        for field in ('loc', 'rot'):
            diff = max(abs(x - y) for x, y in zip(tr[field], other[field]))
            worst = max(worst, diff)
            if not all(math.isclose(x, y, rel_tol=0.0, abs_tol=ABS_TOL)
                       for x, y in zip(tr[field], other[field])):
                errors.append(f'frame {frame} {name}.{field}: {tr[field]} vs {other[field]}')
print(f'max |diff| = {worst:.3e}')
print('\n'.join(errors[:25]) if errors else 'MATCH')
sys.exit(1 if errors else 0)
```

- [ ] **Step 4: Create the preprocess and round-trip checkers**

`DEMCSVs/_npz_check/tools/compare_viz.py`:

```python
"""Exit 0 iff two viz_preprocess output dirs match: file sets and ints exact, floats within REL_TOL."""
import json
import math
import sys
from pathlib import Path

import numpy as np

REL_TOL = 1e-12  # (n,3) array layout can change summation order -> last-digit differences
IGNORED_MANIFEST_KEYS = {'input_mode'}


def same_json(a, b):
    if isinstance(a, dict):
        return isinstance(b, dict) and a.keys() == b.keys() and all(same_json(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return isinstance(b, list) and len(a) == len(b) and all(same_json(x, y) for x, y in zip(a, b))
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, rel_tol=REL_TOL, abs_tol=REL_TOL)
    return a == b


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file())


before, after = Path(sys.argv[1]), Path(sys.argv[2])
errors = []
if files(before) != files(after):
    errors.append(f'file sets differ: {sorted(set(files(before)) ^ set(files(after)))}')
for rel in files(before):
    a, b = before / rel, after / rel
    if not b.exists():
        continue
    if rel == 'manifest.json':
        ma, mb = (json.loads(p.read_text(encoding='utf-8')) for p in (a, b))
        for k in sorted((ma.keys() | mb.keys()) - IGNORED_MANIFEST_KEYS):
            if not same_json(ma.get(k), mb.get(k)):
                errors.append(f'manifest[{k}]: {ma.get(k)!r} vs {mb.get(k)!r}')
    elif rel.endswith('.json'):
        if not same_json(json.loads(a.read_text(encoding='utf-8')),
                         json.loads(b.read_text(encoding='utf-8'))):
            errors.append(f'{rel}: values differ')
    elif rel.endswith('.npz'):
        za, zb = np.load(a), np.load(b)
        if sorted(za.files) != sorted(zb.files):
            errors.append(f'{rel}: keys {sorted(za.files)} vs {sorted(zb.files)}')
            continue
        for k in za.files:
            x, y = za[k], zb[k]
            if x.shape != y.shape or x.dtype != y.dtype:
                errors.append(f'{rel}:{k} shape/dtype {x.shape} {x.dtype} vs {y.shape} {y.dtype}')
            elif np.issubdtype(x.dtype, np.floating):
                if not np.allclose(x, y, rtol=REL_TOL, atol=REL_TOL, equal_nan=True):
                    errors.append(f'{rel}:{k} max|diff|={np.nanmax(np.abs(x - y)):.3e}')
            elif not np.array_equal(x, y):
                errors.append(f'{rel}:{k} integer values differ')
print('\n'.join(errors[:25]) if errors else 'MATCH')
sys.exit(1 if errors else 0)
```

`DEMCSVs/_npz_check/tools/refscale.py`:

```python
"""Blender-Python helper: write reference_scale_from_run(grains_dir) to JSON.

Usage: blender --background --factory-startup --python-exit-code 1 --python refscale.py -- <grains_dir> <out.json>
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, 'C:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code')
from viz.viz_preprocess_lite import reference_scale_from_run  # noqa: E402

grains_dir, out = sys.argv[sys.argv.index('--') + 1:][:2]
result = list(reference_scale_from_run(grains_dir))
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(json.dumps(result), encoding='utf-8')
print('reference_scale_from_run ->', result)
```

`DEMCSVs/_npz_check/tools/compare_refscale.py`:

```python
"""Exit 0 iff two reference_scale_from_run results match: n exact, radii within REL_TOL."""
import json
import math
import sys

REL_TOL = 1e-12  # pandas mean vs numpy mean can differ in the last digit

a, b = (json.load(open(p, encoding='utf-8')) for p in sys.argv[1:3])
ok = a[2] == b[2] and all(math.isclose(x, y, rel_tol=REL_TOL) for x, y in zip(a[:2], b[:2]))
print(f'before={a} after={b}')
print('MATCH' if ok else 'DIFFER')
sys.exit(0 if ok else 1)
```

`DEMCSVs/_npz_check/tools/check_roundtrip.py`:

```python
"""Exit 0 iff every grain CSV has an npz twin with identical values and the schema's keys and
dtypes, the npz grains folder holds no CSVs, and the bodies CSVs are byte-identical."""
import filecmp
import glob
import os
import sys

import numpy as np
import pandas as pd

KEYS = ['grain_id', 'time_s', 'x_au', 'y_au', 'z_au', 'x_km', 'y_km', 'z_km',
        'x_rel_km', 'y_rel_km', 'z_rel_km', 'Reff_km', 'h_km',
        'x_vis', 'y_vis', 'z_vis', 'Reff_vis', 'm', 'vx', 'vy', 'vz', 'spinx', 'spiny', 'spinz']

csv_grains, npz_grains, csv_bodies, npz_bodies = sys.argv[1:5]


def stems(paths):
    return [os.path.splitext(os.path.basename(p))[0] for p in paths]


errors = []
csvs = sorted(glob.glob(os.path.join(csv_grains, '*.csv')))
npzs = sorted(glob.glob(os.path.join(npz_grains, '*.npz')))
if not csvs or stems(csvs) != stems(npzs):
    errors.append(f'grain frame sets differ: csv={stems(csvs)} npz={stems(npzs)}')
if glob.glob(os.path.join(npz_grains, '*.csv')):
    errors.append('npz grains folder still contains .csv files')
for c, z in zip(csvs, npzs):
    df = pd.read_csv(c, float_precision='round_trip')
    d = np.load(z)
    if sorted(d.files) != sorted(KEYS):
        errors.append(f'{os.path.basename(z)}: keys {sorted(d.files)}')
        continue
    if d['time_s'].shape != () or d['time_s'].dtype != np.float64 \
            or float(d['time_s']) != float(df['time_s'].iloc[0]):
        errors.append(f'{os.path.basename(z)}: time_s {d["time_s"]!r} vs {df["time_s"].iloc[0]!r}')
    for k in KEYS:
        if k == 'time_s':
            continue
        want = np.int64 if k == 'grain_id' else np.float64
        if d[k].dtype != want or d[k].shape != (len(df),):
            errors.append(f'{os.path.basename(z)}:{k} dtype/shape {d[k].dtype} {d[k].shape}')
        elif not np.array_equal(d[k], df[k].to_numpy(), equal_nan=True):
            errors.append(f'{os.path.basename(z)}:{k} values differ')
bodies_a = sorted(glob.glob(os.path.join(csv_bodies, '*.csv')))
bodies_b = sorted(glob.glob(os.path.join(npz_bodies, '*.csv')))
if not bodies_a or stems(bodies_a) != stems(bodies_b):
    errors.append('bodies file sets differ')
for x, y in zip(bodies_a, bodies_b):
    if not filecmp.cmp(x, y, shallow=False):
        errors.append(f'bodies CSV differs: {os.path.basename(x)}')
print(f'{len(npzs)} grain npz / {len(bodies_b)} bodies CSV checked')
print('\n'.join(errors[:25]) if errors else 'PASS')
sys.exit(1 if errors else 0)
```

- [ ] **Step 5: Regenerate the CSV reference with the unchanged converter**

```powershell
wsl.exe -e bash -lc "cd ~/Honours && python3 sobol/Analysis/run_demtocsv_batch.py --base-output-dir /mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/_npz_check/csv sobol_mass_runs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001"
Get-ChildItem DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output, DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output | Select-Object Directory, Name
```

Expected: the log prints `Found 4 dump file(s)` and no `ERROR:` line. Each folder lists `sobol_00000.csv` … `sobol_00003.csv`. `DEMtoCSV.py` prints per-dump errors but still exits 0, so the file listing is the real check.

- [ ] **Step 6: Capture the preprocess reference**

```powershell
.venv\Scripts\python.exe viz\viz_preprocess.py --grains-dir DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output --bodies-dir DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output --output-dir DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_viz --envelope-method hull
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_viz.py DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_viz DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_viz
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\refscale.py -- DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output DEMCSVs\_npz_check\results\refscale_before.json
```

Expected:
- Four `[0000N] fragments=…` lines, then `Wrote manifest -> …`.
- The self-compare prints `MATCH`, which confirms the checker runs.
- Blender prints `reference_scale_from_run -> [<radius>, <grain radius>, <n>]`, with `n` around 500.

- [ ] **Step 7: Capture the Blender reference snapshots**

```powershell
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\make_blender_configs.py before
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\earthcam_before.json
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\earth_plus_camera_before.json
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\bulkviz_before.json
```

Expected: each run ends with `snapshot: <N> objects x 4 frames -> …` and exits 0. The per-sphere runs create about 500 spheres and can take a minute or two each. If any run raises, stop and report the traceback. The baseline must exist before any code changes.

- [ ] **Step 8: Sanity-check the baseline**

```powershell
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_snapshot.py DEMCSVs\_npz_check\snapshots\earthcam_before.json --grains-csv DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\sobol_00000.csv --require Earth Moon Sun_Visual DEM_SunLight DEM_TrackCam --camera-not Camera
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_snapshot.py DEMCSVs\_npz_check\snapshots\earth_plus_camera_before.json --grains-csv DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\sobol_00000.csv --require Earth Moon Sun_Visual DEM_SunLight DEM_TrackCam --camera-not Camera
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_snapshot.py DEMCSVs\_npz_check\snapshots\bulkviz_before.json --require VizEjecta DEM_TrackCam --camera-not Camera
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_snapshots.py DEMCSVs\_npz_check\snapshots\earthcam_before.json DEMCSVs\_npz_check\snapshots\earthcam_before.json
```

Expected: three `PASS` results, then `max |diff| = 0.000e+00` and `MATCH`. If any check fails, stop and report. A baseline that is missing the grains, Earth, or the tracking camera cannot validate the migration.

- [ ] **Step 9: No commit**

Leave everything uncommitted (Global Constraints). `DEMCSVs\_npz_check\` is gitignored.

---

### Task 2: Converter writes grain npz

**Files:**
- Modify: `CSVconvert/DEMtoCSV.py` (lines 11–16: header comment; lines 269–323: grains block and writes)
- Modify: `CLAUDE.md` (directory layout, Pipeline B diagram, grains schema section, DEMtoCSV output line)

**Interfaces:**
- Consumes: `check_roundtrip.py` and the CSV reference from Task 1.
- Produces: `DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\sobol_0000{0..3}.npz` with the 24-key schema, plus an identical `run_0001_bodies_output\*.csv`.

- [ ] **Step 1: Run the round-trip check to confirm it fails**

```powershell
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_roundtrip.py DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_grains_output DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output
```

Expected: FAIL (exit 1) with `grain frame sets differ: csv=[…4 stems…] npz=[]`.

- [ ] **Step 2: Update the header comment in `DEMtoCSV.py`**

Replace lines 11–16:

```python
# Root folder for all DEM CSV output.
# Subfolders are created automatically:
#   DEMCSVs\<sim_name>\<run_name>_bodies_output\
#   DEMCSVs\<sim_name>\<run_name>_grains_output\
```

with:

```python
# Root folder for all DEM output (bodies as CSV, grains as .npz).
# Subfolders are created automatically:
#   DEMCSVs\<sim_name>\<run_name>_bodies_output\   one <dump>.csv per dump
#   DEMCSVs\<sim_name>\<run_name>_grains_output\   one <dump>.npz per dump
```

Leave the next two comment lines (`# where <sim_name> is …` / `# <run_name> is …`) unchanged.

- [ ] **Step 3: Replace the grains DataFrame and CSV write with npz arrays**

In `CSVconvert/DEMtoCSV.py`, replace the block that begins at `        # Body-frame positions in km (relative to Apophis CoM)` (line 269). It ends with `        grains_df.to_csv(grains_out, index=False)` (line 323), and it includes the `grains_df = pd.DataFrame({...})` literal and the `# ── Write CSVs ──` header. Replace it with:

```python
        # Body-frame positions in km (relative to Apophis CoM)
        x_rel_km = (g["x"].values - com_x) * to_km
        y_rel_km = (g["y"].values - com_y) * to_km
        z_rel_km = (g["z"].values - com_z) * to_km
        reff_km  = g["Reff"].values * to_km

        def _optional(col):
            # Velocity and spin can be absent (mini dumps); NaN-fill keeps the key set fixed.
            if col in g.columns:
                return g[col].values.astype(np.float64)
            return np.full(n_dem, np.nan)

        # One array per field; schema documented in CLAUDE.md "Grains npz".
        # x_au is absolute: all grains agree to many d.p., so never place grains
        # with it. x_vis = x_rel_km * GRAIN_VIS_SCALE stays near the Blender
        # origin, where float32 object coordinates keep full precision.
        grains = {
            "grain_id": np.arange(n_dem, dtype=np.int64),
            "time_s":   np.float64(time_s),
            "x_au":     (g["x"].values * to_au).astype(np.float64),
            "y_au":     (g["y"].values * to_au).astype(np.float64),
            "z_au":     (g["z"].values * to_au).astype(np.float64),
            "x_km":     (g["x"].values * to_km).astype(np.float64),
            "y_km":     (g["y"].values * to_km).astype(np.float64),
            "z_km":     (g["z"].values * to_km).astype(np.float64),
            "x_rel_km": x_rel_km.astype(np.float64),
            "y_rel_km": y_rel_km.astype(np.float64),
            "z_rel_km": z_rel_km.astype(np.float64),
            "Reff_km":  reff_km.astype(np.float64),
            "h_km":     (g["h"].values * to_km).astype(np.float64),
            "x_vis":    (x_rel_km * GRAIN_VIS_SCALE).astype(np.float64),
            "y_vis":    (y_rel_km * GRAIN_VIS_SCALE).astype(np.float64),
            "z_vis":    (z_rel_km * GRAIN_VIS_SCALE).astype(np.float64),
            "Reff_vis": (reff_km * GRAIN_VIS_SCALE).astype(np.float64),
            "m":        g["m"].values.astype(np.float64),
            "vx":       _optional("vx"),
            "vy":       _optional("vy"),
            "vz":       _optional("vz"),
            "spinx":    _optional("spinx"),
            "spiny":    _optional("spiny"),
            "spinz":    _optional("spinz"),
        }

        # ── Write outputs: bodies CSV, grains npz ─────────────────────────────
        basename   = os.path.basename(dump)
        bodies_out = os.path.join(BODIES_OUTPUT_DIR, basename + ".csv")
        grains_out = os.path.join(GRAINS_OUTPUT_DIR, basename + ".npz")

        bodies_df.to_csv(bodies_out, index=False)
        np.savez_compressed(grains_out, **grains)
```

The summary `print(...)` after this block is unchanged; it already prints `grains_out`.

Confirm no CSV-era grain names remain:

```powershell
Select-String -Path CSVconvert\DEMtoCSV.py -Pattern "grains_df|grains_out, index"
```

Expected: no output.

- [ ] **Step 4: Convert the test run with the new code**

```powershell
wsl.exe -e bash -lc "cd ~/Honours && python3 sobol/Analysis/run_demtocsv_batch.py --base-output-dir /mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/_npz_check/npz sobol_mass_runs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001"
```

Expected: `Found 4 dump file(s)`, four per-dump summaries whose `Written:` lines end in `.csv` then `.npz`, and no `ERROR:` line.

If you fix a bug and re-run, first delete only this plan's output folder:

```powershell
Remove-Item -Recurse -Force DEMCSVs\_npz_check\npz
```

- [ ] **Step 5: Run the round-trip check to confirm it passes**

```powershell
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_roundtrip.py DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_grains_output DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output
```

Expected: `4 grain npz / 4 bodies CSV checked` then `PASS`.

- [ ] **Step 6: Update the grains documentation in `CLAUDE.md`**

Make four edits.

(a) Directory layout. Replace

`      <run>_grains_output/   # n_grains rows per dump (typical ~500 OBJ crop)`

with

`      <run>_grains_output/   # one .npz per dump, n_grains entries (typical ~500 OBJ crop)`

(b) Pipeline B diagram. Replace

`  DEMCSVs/<sim_name>/<run_name>_grains_output/*.csv   (n_grains rows; one per DEM grain)`

with

`  DEMCSVs/<sim_name>/<run_name>_grains_output/*.npz   (n_grains entries; one per DEM grain)`

(c) Grains schema. Replace everything from the heading `### Grains CSV (\`DEMCSVs/*_grains_output/\`) — DEM pipeline only` down to and including the table row `| \`spinx\`, \`spiny\`, \`spinz\` | (code units) | Spin |` with:

```markdown
### Grains npz (`DEMCSVs/*_grains_output/`) — DEM pipeline only

One compressed `.npz` per dump (same basename as the bodies CSV, e.g. `sobol_00003.npz`), written by `DEMtoCSV.py` with `np.savez_compressed`. Each key is one array of length `n_grains` (typical ~500 for OBJ crop), except `time_s`. Read it with `d = np.load(path)`; no pandas is needed. CSV-era grain folders are not read by the current scripts. Reconvert them from the WSL dumps.

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
```

Leave the `**Code units — \`udist\` is 1 km …` paragraph that follows the table unchanged.

(d) DEMtoCSV fallback output line. Replace

`Output goes to \`DEMCSVs/<sim_name>/<run>_bodies_output/\` and \`_grains_output/\`.`

with

`Output goes to \`DEMCSVs/<sim_name>/<run>_bodies_output/\` (CSV) and \`_grains_output/\` (\`.npz\`).`

Keep the rest of that line (`Set \`MIN_DEM_GRAINS\` …`) unchanged.

- [ ] **Step 7: No commit**

---

### Task 3: Preprocess readers (`viz_preprocess.py`, `viz_preprocess_lite.py`)

**Files:**
- Modify: `viz/viz_preprocess.py` (line 2 docstring; line 14 `import pandas`; lines 36–58 `_load_grains_csv`; lines 181–207; line 266; lines 296–307)
- Modify: `viz/viz_preprocess_lite.py` (line 33 `import pandas`; lines 54–73 `reference_scale_from_run`)
- Modify: `CLAUDE.md` (lines mentioning grain CSVs for the preprocess paths)
- Modify: `docs/BATCHES_VIZ.md` (lines 28, 69, 79)

**Interfaces:**
- Consumes: the npz folder from Task 2; `compare_viz.py`, `refscale.py`, `compare_refscale.py`, `csv\…\run_0001_viz` and `results\refscale_before.json` from Task 1.
- Produces:
  - `viz.viz_preprocess._load_grains(path: Path) -> dict` with keys `pos (n,3) float64`, `radii (n,) float64`, `mass (n,) float64`, `vel (n,3) float64`, `grain_id (n,) uint32`.
  - `viz.viz_preprocess_lite.reference_scale_from_run(grains_dir) -> (float, float, int)`, unchanged signature.
  - `DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_viz\manifest.json`, used by Task 5.

- [ ] **Step 1: Run preprocess on the npz folder to confirm it fails**

```powershell
.venv\Scripts\python.exe viz\viz_preprocess.py --grains-dir DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_grains_output --bodies-dir DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output --output-dir DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_viz --envelope-method hull
```

Expected: FAIL with `FileNotFoundError: No grain CSVs in …`.

- [ ] **Step 2: Change the loader in `viz/viz_preprocess.py`**

Line 2: replace

`"""Preprocess DEM grain CSVs (or PHANTOM dumps) into bulk Blender viz assets."""`

with

`"""Preprocess DEM grain npz files (or PHANTOM dumps) into bulk Blender viz assets."""`

Delete line 14, `import pandas as pd`.

Replace the whole `def _load_grains_csv(path: Path) -> dict:` function (lines 36–58) with:

```python
def _load_grains(path: Path) -> dict:
    d = np.load(path)
    n = len(d["x_rel_km"])
    pos = np.column_stack([d["x_rel_km"], d["y_rel_km"], d["z_rel_km"]]).astype(np.float64)
    radii = d["Reff_km"].astype(np.float64)
    mass = d["m"].astype(np.float64) if "m" in d.files else np.ones(n)
    vel_keys = ("vx", "vy", "vz")
    if all(k in d.files for k in vel_keys):
        vel = np.nan_to_num(np.column_stack([d[k] for k in vel_keys]).astype(np.float64), nan=0.0)
    else:
        vel = np.zeros((n, 3), dtype=np.float64)
    grain_id = (
        d["grain_id"].astype(np.uint32)
        if "grain_id" in d.files
        else np.arange(n, dtype=np.uint32)
    )
    return {
        "pos": pos,
        "radii": radii,
        "mass": mass,
        "vel": vel,
        "grain_id": grain_id,
    }
```

- [ ] **Step 3: Change the frame loop, manifest and CLI in `viz/viz_preprocess.py`**

In `run_preprocess`, replace

```python
    csv_files = sorted(glob.glob(str(grains_dir / "*.csv")))
    if not csv_files:
        raise FileNotFoundError(f"No grain CSVs in {grains_dir}")
```

with

```python
    grain_files = sorted(glob.glob(str(grains_dir / "*.npz")))
    if not grain_files:
        raise FileNotFoundError(
            f"No grain npz files in {grains_dir} (CSV-era folder? re-run DEMtoCSV.py)"
        )
```

Replace

```python
    if max_frames is not None:
        csv_files = csv_files[:max_frames]
```

with

```python
    if max_frames is not None:
        grain_files = grain_files[:max_frames]
```

Replace

```python
    for i, csv_path in enumerate(csv_files):
        frame_id = f"{i:05d}"
        frame_ids.append(frame_id)
        grains = _load_grains_csv(Path(csv_path))
```

with

```python
    for i, grain_path in enumerate(grain_files):
        frame_id = f"{i:05d}"
        frame_ids.append(frame_id)
        grains = _load_grains(Path(grain_path))
```

In the manifest dict, replace `        "input_mode": "csv",` with `        "input_mode": "npz",`. Keep the `bodies_csv_dir` and `grains_csv_dir` key names.

In `main()`, replace

```python
    p.add_argument(
        "--input-mode",
        choices=("csv", "dump"),
        default="csv",
        help="dump mode reserved for P4 (not implemented yet)",
    )
```

with

```python
    p.add_argument(
        "--input-mode",
        choices=("npz", "dump"),
        default="npz",
        help="npz = DEMtoCSV.py grain files; dump mode reserved for P4 (not implemented yet)",
    )
```

and replace

`        print("[ERROR] --input-mode dump is P4 (Objective 2 gate); use CSV for P0–P3.", file=sys.stderr)`

with

`        print("[ERROR] --input-mode dump is P4 (Objective 2 gate); use grain npz files for P0–P3.", file=sys.stderr)`

Confirm nothing stale remains:

```powershell
Select-String -Path viz\viz_preprocess.py -Pattern "pd\.|csv_files|csv_path|_load_grains_csv|\*\.csv"
```

Expected: no output.

- [ ] **Step 4: Change `reference_scale_from_run` in `viz/viz_preprocess_lite.py`**

Delete line 33, `import pandas as pd`.

Replace the whole `def reference_scale_from_run(grains_dir):` function (lines 54–73) with:

```python
def reference_scale_from_run(grains_dir):
    """(reference_cluster_radius_bu, reference_grain_radius_bu, reference_n) from frame 1.

    Cluster radius is the frame-1 grains' max distance from the origin in
    x_vis/y_vis/z_vis (already Apophis-CoM-centered, per the grains npz
    convention); grain radius is the mean of Reff_vis -- uniform per run in
    practice, mean guards against float noise.
    """
    grains_dir = Path(grains_dir)
    files = sorted(glob.glob(str(grains_dir / '*.npz')))
    if not files:
        raise FileNotFoundError(
            f'No grain npz files in {grains_dir} (CSV-era folder? re-run DEMtoCSV.py)'
        )
    d = np.load(files[0])
    for key in ('x_vis', 'y_vis', 'z_vis', 'Reff_vis'):
        if key not in d.files:
            raise ValueError(f'{files[0]} missing required key {key!r}')
    pts = np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']]).astype(np.float64)
    cluster_radius = float(np.linalg.norm(pts, axis=1).max())
    grain_radius = float(d['Reff_vis'].mean())
    return cluster_radius, grain_radius, len(d['Reff_vis'])
```

Confirm nothing stale remains:

```powershell
Select-String -Path viz\viz_preprocess_lite.py -Pattern "pd\.|read_csv"
```

Expected: no output. The bodies-CSV `glob` further down the file stays.

- [ ] **Step 5: Run preprocess and compare against the reference**

```powershell
.venv\Scripts\python.exe viz\viz_preprocess.py --grains-dir DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_grains_output --bodies-dir DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_bodies_output --output-dir DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_viz --envelope-method hull
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_viz.py DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_viz DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_viz
```

Expected: four frame lines with the same `fragments=` / `ejecta=` counts as Task 1 Step 6, then `MATCH`.

- [ ] **Step 6: Run `reference_scale_from_run` and compare against the reference**

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\refscale.py -- DEMCSVs\_npz_check\npz\sobol_20260705_131545_baseline_58deg\run_0001_grains_output DEMCSVs\_npz_check\results\refscale_after.json
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_refscale.py DEMCSVs\_npz_check\results\refscale_before.json DEMCSVs\_npz_check\results\refscale_after.json
```

Expected: `MATCH`.

- [ ] **Step 7: Update the preprocess wording in the docs**

`CLAUDE.md`:
- Project overview paragraph: replace `sized from a real run's grain/body CSVs` with `sized from a real run's grain npz / body CSV files`.
- Also in that paragraph: replace `Real per-frame million-grain CSV/dump ingestion` with `Real per-frame million-grain npz/dump ingestion`, and `skip the per-frame-CSV bottleneck at that scale` with `skip the per-frame-file bottleneck at that scale`.
- Bulk composite prerequisites: replace `**Prerequisites:** grain CSVs from \`DEMtoCSV.py\`` with `**Prerequisites:** grain npz files from \`DEMtoCSV.py\``.
- Frame index note: replace `matches sorted order of grain CSV filenames` with `matches sorted order of grain npz filenames`.
- Pure instancing prerequisites: replace `grain and body CSVs from \`DEMtoCSV.py\`` with `grain npz and body CSV files from \`DEMtoCSV.py\``.
- "What this path currently is and isn't" paragraph: replace `real per-frame million-grain CSV/dump ingestion` with `real per-frame million-grain npz/dump ingestion`.
- Handoff workflow, step 2: replace `**Convert to CSV** — primary:` with `**Convert dumps** — primary:`.

`docs/BATCHES_VIZ.md`:
- Line 28: `### 1. Convert to CSV (if not already done)` → `### 1. Convert dumps (if not already done)`
- Line 69: `manifest.json              # viz_mode: "composite"; frame_ids; relative CSV paths` → `manifest.json              # viz_mode: "composite"; frame_ids; relative grains/bodies dir paths`
- Line 79: `One frame index (\`00000\`, \`00001\`, …) per sorted grain CSV in \`_grains_output/\`.` → `One frame index (\`00000\`, \`00001\`, …) per sorted grain npz file in \`_grains_output/\`.`

Check:

```powershell
Select-String -Path CLAUDE.md, docs\BATCHES_VIZ.md -Pattern "grain CSV|grains CSV|grain/body CSV|Convert to CSV"
```

Expected: no output.

- [ ] **Step 8: No commit**

---

### Task 4: Per-sphere Blender importers and standalone camera

**Files:**
- Modify: `BlenderConvert/DEMGrainsBlenderEarthCam.py` (imports lines 8–17; lines 116–139; 157; 212–226; 255–305; 750–798; 914–927)
- Modify: `BlenderConvert/DEMGrainsBlenderEarth.py` (imports lines 1–9; lines 148–171; 189; 640–693; 816; 830)
- Modify: `BlenderConvert/DEMCamera.py` (imports lines 1–6; line 29; lines 112–136; 144–147; around 213–220)
- Modify: `CLAUDE.md` (Blender script list item 6; DEM-specific notes)

**Interfaces:**
- Consumes: the npz folder from Task 2; `make_blender_configs.py`, `run_patched.py`, `check_snapshot.py`, `compare_snapshots.py`, `snapshots\earthcam_before.json` and `snapshots\earth_plus_camera_before.json` from Task 1.
- Produces: `snapshots\earthcam_after.json` and `snapshots\earth_plus_camera_after.json` that match the before snapshots.

- [ ] **Step 1: Generate after-phase configs and confirm the importers fail on npz**

```powershell
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\make_blender_configs.py after
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\earthcam_after.json
```

Expected: FAIL (non-zero exit) with `FileNotFoundError: No CSVs found in …run_0001_grains_output/`.

- [ ] **Step 2: Switch `DEMGrainsBlenderEarthCam.py` to npz, leaving the bodies lookup unfixed for now**

This step deliberately leaves `_bodies_csv_for` as it is, so Step 3 can show the silent Earth-drop bug.

Imports: delete line 9, `import csv`. Insert `import numpy as np` directly above `import pandas as pd`.

Replace lines 116–124:

```python
csv_files = sorted(glob.glob(os.path.join(GRAINS_CSV_DIR, '*.csv')))

if not csv_files:
    raise FileNotFoundError(
        f'No CSVs found in {GRAINS_CSV_DIR}\n'
        'Run CSVconvert/DEMtoCSV.py first to generate dem_grains_output/.'
    )

print(f'Found {len(csv_files)} grain CSV(s).')
```

with:

```python
grain_files = sorted(glob.glob(os.path.join(GRAINS_CSV_DIR, '*.npz')))

if not grain_files:
    raise FileNotFoundError(
        f'No grain npz files found in {GRAINS_CSV_DIR}\n'
        'Run CSVconvert/DEMtoCSV.py first (CSV-era grain folders must be reconverted).'
    )

print(f'Found {len(grain_files)} grain npz file(s).')
```

Line 157: replace `    else _detect_solar_system_bodies(csv_files)` with `    else _detect_solar_system_bodies(grain_files)`.

Replace the whole `def _grain_core(csv_path, fraction):` function (lines 212–226) with:

```python
def _grain_core(grain_path, fraction):
    """Centroid of the closest `fraction` of grains to the CoM (origin)."""
    d = np.load(grain_path)
    pts = np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']])
    order = np.argsort(np.sqrt((pts * pts).sum(axis=1)), kind='stable')
    n = max(1, int(len(pts) * fraction))
    return Vector(pts[order[:n]].mean(axis=0).tolist())
```

In `setup_dem_track_camera`:
- Replace `            f'WARNING: scene has {n_frames} frames but {n_csvs} grain CSVs. '` with `            f'WARNING: scene has {n_frames} frames but {n_csvs} grain files. '`.
- Replace

```python
        csv_path = grain_files[i]
        scene.frame_set(frame)

        core_pos = _grain_core(csv_path, CORE_GRAIN_FRACTION)
```

with

```python
        grain_path = grain_files[i]
        scene.frame_set(frame)

        core_pos = _grain_core(grain_path, CORE_GRAIN_FRACTION)
```

Replace the first pass (lines 750–768, from `first_df = pd.read_csv(csv_files[0])` to just before `    for c in list(obj.users_collection):`):

```python
first_df = pd.read_csv(csv_files[0])
n_grains = len(first_df)
print(f'Creating {n_grains} grain spheres from {os.path.basename(csv_files[0])} ...')

for _, row in first_df.iterrows():
    gid    = int(row['grain_id'])
    name   = f'DEM_Grain_{gid:03d}'
    radius = float(row['Reff_vis'])
    loc    = (float(row['x_vis']), float(row['y_vis']), float(row['z_vis']))

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius, segments=12, ring_count=8, location=loc
    )
```

with:

```python
first = np.load(grain_files[0])
n_grains = len(first['grain_id'])
print(f'Creating {n_grains} grain spheres from {os.path.basename(grain_files[0])} ...')

for gid, radius, x, y, z in zip(first['grain_id'], first['Reff_vis'],
                                first['x_vis'], first['y_vis'], first['z_vis']):
    name = f'DEM_Grain_{int(gid):03d}'

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=float(radius), segments=12, ring_count=8,
        location=(float(x), float(y), float(z)),
    )
```

The following lines (`obj = bpy.context.object`, unlink/link, material) are unchanged.

Replace the start of the second pass (lines 778–798, from `print(f'Keyframing {len(csv_files)} frames ...')` through the grain `keyframe_insert` loop):

```python
print(f'Keyframing {len(csv_files)} frames ...')

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end   = len(csv_files)

for frame_num, csv_file in enumerate(csv_files, start=1):
    df = pd.read_csv(csv_file)
    bpy.context.scene.frame_set(frame_num)

    for _, row in df.iterrows():
        gid  = int(row['grain_id'])
        name = f'DEM_Grain_{gid:03d}'
        obj  = bpy.data.objects.get(name)
        if obj is None:
            continue
        obj.location = (
            float(row['x_vis']),
            float(row['y_vis']),
            float(row['z_vis']),
        )
        obj.keyframe_insert(data_path='location', frame=frame_num)
```

with:

```python
print(f'Keyframing {len(grain_files)} frames ...')

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end   = len(grain_files)

for frame_num, grain_file in enumerate(grain_files, start=1):
    d = np.load(grain_file)
    bpy.context.scene.frame_set(frame_num)

    for gid, x, y, z in zip(d['grain_id'], d['x_vis'], d['y_vis'], d['z_vis']):
        obj = bpy.data.objects.get(f'DEM_Grain_{int(gid):03d}')
        if obj is None:
            continue
        obj.location = (float(x), float(y), float(z))
        obj.keyframe_insert(data_path='location', frame=frame_num)
```

In the same loop body, replace `        bodies_path = _bodies_csv_for(csv_file)` with `        bodies_path = _bodies_csv_for(grain_file)`.

In the final prints and the camera call, replace each `len(csv_files)` with `len(grain_files)`, and `setup_dem_track_camera(earth_empty, csv_files)` with `setup_dem_track_camera(earth_empty, grain_files)`.

Check:

```powershell
Select-String -Path BlenderConvert\DEMGrainsBlenderEarthCam.py -Pattern "csv_files|csv_file\b|csv_path|csv\.|iterrows|grain CSV"
```

Expected: no output.

- [ ] **Step 3: Run the importer and confirm Earth is silently dropped**

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\earthcam_after.json
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_snapshot.py DEMCSVs\_npz_check\snapshots\earthcam_after.json --grains-csv DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\sobol_00000.csv --require Earth Moon Sun_Visual DEM_SunLight DEM_TrackCam --camera-not Camera
```

Expected:
- Blender exits 0 and prints `Run mode: apophis_only (grains only).`.
- `check_snapshot.py` FAILS with `missing required objects: ['Earth', 'Moon', 'Sun_Visual']`.

This is the bug. If Earth is present here instead, stop and report: the bodies lookup does not work the way the spec describes.

- [ ] **Step 4: Fix the bodies lookup in `DEMGrainsBlenderEarthCam.py`**

Replace:

```python
def _bodies_csv_for(grains_path):
    """Return the matching bodies CSV path, or None if it does not exist."""
    if not _bodies_available:
        return None
    p = os.path.join(BODIES_CSV_DIR, os.path.basename(grains_path))
    return p if os.path.exists(p) else None
```

with:

```python
def _bodies_csv_for(grains_path):
    """Return the bodies CSV sharing the grain file's stem, or None if it does not exist."""
    if not _bodies_available:
        return None
    stem = os.path.splitext(os.path.basename(grains_path))[0]
    p = os.path.join(BODIES_CSV_DIR, stem + '.csv')
    return p if os.path.exists(p) else None
```

- [ ] **Step 5: Re-run and compare against the reference**

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\earthcam_after.json
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_snapshot.py DEMCSVs\_npz_check\snapshots\earthcam_after.json --grains-csv DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\sobol_00000.csv --require Earth Moon Sun_Visual DEM_SunLight DEM_TrackCam --camera-not Camera
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_snapshots.py DEMCSVs\_npz_check\snapshots\earthcam_before.json DEMCSVs\_npz_check\snapshots\earthcam_after.json
```

Expected: Blender prints `Run mode: full solar system.`, `check_snapshot.py` prints `PASS`, and `compare_snapshots.py` prints `max |diff|` ≤ `1e-9`, then `MATCH`.

- [ ] **Step 6: Apply the same migration to `DEMGrainsBlenderEarth.py`**

Imports: insert `import numpy as np` directly above line 4, `import pandas as pd`. This file has no `import csv`.

Replace lines 148–156:

```python
csv_files = sorted(glob.glob(os.path.join(GRAINS_CSV_DIR, '*.csv')))

if not csv_files:
    raise FileNotFoundError(
        f'No CSVs found in {GRAINS_CSV_DIR}\n'
        'Run CSVconvert/DEMtoCSV.py first to generate dem_grains_output/.'
    )

print(f'Found {len(csv_files)} grain CSV(s).')
```

with:

```python
grain_files = sorted(glob.glob(os.path.join(GRAINS_CSV_DIR, '*.npz')))

if not grain_files:
    raise FileNotFoundError(
        f'No grain npz files found in {GRAINS_CSV_DIR}\n'
        'Run CSVconvert/DEMtoCSV.py first (CSV-era grain folders must be reconverted).'
    )

print(f'Found {len(grain_files)} grain npz file(s).')
```

Replace lines 166–171:

```python
def _bodies_csv_for(grains_path):
    """Return the matching bodies CSV path, or None if it does not exist."""
    if not _bodies_available:
        return None
    p = os.path.join(BODIES_CSV_DIR, os.path.basename(grains_path))
    return p if os.path.exists(p) else None
```

with:

```python
def _bodies_csv_for(grains_path):
    """Return the bodies CSV sharing the grain file's stem, or None if it does not exist."""
    if not _bodies_available:
        return None
    stem = os.path.splitext(os.path.basename(grains_path))[0]
    p = os.path.join(BODIES_CSV_DIR, stem + '.csv')
    return p if os.path.exists(p) else None
```

Line 189: replace `    else _detect_solar_system_bodies(csv_files)` with `    else _detect_solar_system_bodies(grain_files)`.

Replace lines 640–652 (from `first_df = pd.read_csv(csv_files[0])` through the `bpy.ops.mesh.primitive_uv_sphere_add(...)` call):

```python
first_df = pd.read_csv(csv_files[0])
n_grains = len(first_df)
print(f'Creating {n_grains} grain spheres from {os.path.basename(csv_files[0])} ...')

for _, row in first_df.iterrows():
    gid    = int(row['grain_id'])
    name   = f'DEM_Grain_{gid:03d}'
    radius = float(row['Reff_vis'])
    loc    = (float(row['x_vis']), float(row['y_vis']), float(row['z_vis']))

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=radius, segments=12, ring_count=8, location=loc
    )
```

with:

```python
first = np.load(grain_files[0])
n_grains = len(first['grain_id'])
print(f'Creating {n_grains} grain spheres from {os.path.basename(grain_files[0])} ...')

for gid, radius, x, y, z in zip(first['grain_id'], first['Reff_vis'],
                                first['x_vis'], first['y_vis'], first['z_vis']):
    name = f'DEM_Grain_{int(gid):03d}'

    bpy.ops.mesh.primitive_uv_sphere_add(
        radius=float(radius), segments=12, ring_count=8,
        location=(float(x), float(y), float(z)),
    )
```

Replace lines 668–689 (from `print(f'Keyframing {len(csv_files)} frames ...')` through the grain `keyframe_insert` loop):

```python
print(f'Keyframing {len(csv_files)} frames ...')

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end   = len(csv_files)

for frame_num, csv_file in enumerate(csv_files, start=1):
    df = pd.read_csv(csv_file)
    bpy.context.scene.frame_set(frame_num)

    # Grain positions.
    for _, row in df.iterrows():
        gid  = int(row['grain_id'])
        name = f'DEM_Grain_{gid:03d}'
        obj  = bpy.data.objects.get(name)
        if obj is None:
            continue
        obj.location = (
            float(row['x_vis']),
            float(row['y_vis']),
            float(row['z_vis']),
        )
        obj.keyframe_insert(data_path='location', frame=frame_num)
```

with:

```python
print(f'Keyframing {len(grain_files)} frames ...')

bpy.context.scene.frame_start = 1
bpy.context.scene.frame_end   = len(grain_files)

for frame_num, grain_file in enumerate(grain_files, start=1):
    d = np.load(grain_file)
    bpy.context.scene.frame_set(frame_num)

    # Grain positions.
    for gid, x, y, z in zip(d['grain_id'], d['x_vis'], d['y_vis'], d['z_vis']):
        obj = bpy.data.objects.get(f'DEM_Grain_{int(gid):03d}')
        if obj is None:
            continue
        obj.location = (float(x), float(y), float(z))
        obj.keyframe_insert(data_path='location', frame=frame_num)
```

Line 693: replace `        bodies_path = _bodies_csv_for(csv_file)` with `        bodies_path = _bodies_csv_for(grain_file)`. Lines 816 and 830: replace `len(csv_files)` with `len(grain_files)`.

Check:

```powershell
Select-String -Path BlenderConvert\DEMGrainsBlenderEarth.py -Pattern "csv_files|csv_file\b|iterrows|grain CSV"
```

Expected: no output.

- [ ] **Step 7: Migrate `DEMCamera.py`**

Imports: replace line 5, `import csv`, with `import numpy as np`.

Line 29: replace `# Path to the grain CSVs — MUST match GRAINS_CSV_DIR in DEMGrainsBlenderEarth.py.` with `# Path to the grain npz folder — MUST match GRAINS_CSV_DIR in DEMGrainsBlenderEarth.py.`

Replace lines 112–119:

```python
# ── Load grain CSVs (sorted, same order as DEMGrainsBlenderEarth.py) ─────────
grain_files = sorted(glob.glob(os.path.join(GRAIN_CSV_DIR, '*.csv')))
if not grain_files:
    raise RuntimeError(
        f'No grain CSVs found in {GRAIN_CSV_DIR}\n'
        'Set GRAIN_CSV_DIR to match GRAINS_CSV_DIR in DEMGrainsBlenderEarth.py.'
    )
print(f'Found {len(grain_files)} grain CSV(s) in {GRAIN_CSV_DIR}')
```

with:

```python
# ── Load grain npz files (sorted, same order as DEMGrainsBlenderEarth.py) ────
grain_files = sorted(glob.glob(os.path.join(GRAIN_CSV_DIR, '*.npz')))
if not grain_files:
    raise RuntimeError(
        f'No grain npz files found in {GRAIN_CSV_DIR}\n'
        'Set GRAIN_CSV_DIR to match GRAINS_CSV_DIR in DEMGrainsBlenderEarth.py '
        '(CSV-era grain folders must be reconverted with DEMtoCSV.py).'
    )
print(f'Found {len(grain_files)} grain npz file(s) in {GRAIN_CSV_DIR}')
```

Replace the whole `def _grain_core(csv_path, fraction):` function (lines 122–136) with:

```python
def _grain_core(grain_path, fraction):
    """Return the centroid of the closest `fraction` of grains to the CoM."""
    d = np.load(grain_path)
    pts = np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']])
    order = np.argsort(np.sqrt((pts * pts).sum(axis=1)), kind='stable')
    n = max(1, int(len(pts) * fraction))
    return Vector(pts[order[:n]].mean(axis=0).tolist())
```

Replace `        f'WARNING: scene has {n_frames} frames but {n_csvs} grain CSVs. '` with `        f'WARNING: scene has {n_frames} frames but {n_csvs} grain files. '`.

In the keyframe loop (around line 217), rename the variable `csv_path` to `grain_path`: both the assignment `csv_path   = grain_files[i]` and its use in the `_grain_core(...)` call.

Check:

```powershell
Select-String -Path BlenderConvert\DEMCamera.py -Pattern "csv_path|csv\.|grain CSV|\*\.csv"
```

Expected: no output. `math` may now be unused in `_grain_core`; leave the `import math`, because the rest of the script uses `math.radians` and friends.

- [ ] **Step 8: Run the Earth + Camera pair and compare against the reference**

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\earth_plus_camera_after.json
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_snapshot.py DEMCSVs\_npz_check\snapshots\earth_plus_camera_after.json --grains-csv DEMCSVs\_npz_check\csv\sobol_20260705_131545_baseline_58deg\run_0001_grains_output\sobol_00000.csv --require Earth Moon Sun_Visual DEM_SunLight DEM_TrackCam --camera-not Camera
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_snapshots.py DEMCSVs\_npz_check\snapshots\earth_plus_camera_before.json DEMCSVs\_npz_check\snapshots\earth_plus_camera_after.json
```

Expected: `PASS`, then `MATCH`.

- [ ] **Step 9: Update the per-sphere docs in `CLAUDE.md`**

Blender script list, item 6: replace `Reads CSVs from \`GRAINS_CSV_DIR\`` with `Reads grain npz files from \`GRAINS_CSV_DIR\` (variable name kept from the CSV era)`.

Under `### DEM-specific notes`, add this paragraph after the `**Mini-dump guard:**` paragraph:

```markdown
**Grain ↔ bodies file matching:** per-sphere importers pair each frame's grain file with the bodies CSV of the same stem (`sobol_00003.npz` ↔ `sobol_00003.csv`), swapping the extension. A lookup by full filename finds nothing and silently drops Earth/Moon/Sun (the script falls back to `apophis_only` mode without an error) — keep the stem-based lookup.
```

- [ ] **Step 10: No commit**

---

### Task 5: Bulk composite importer camera (`DEMBulkVizBlender.py`)

**Files:**
- Modify: `BlenderConvert/DEMBulkVizBlender.py` (line 16 `import pandas`; line 279 glob; lines 324–332 camera block)

**Interfaces:**
- Consumes: `npz\…\run_0001_viz\manifest.json` from Task 3; `configs\bulkviz_after.json` from Task 4 Step 1; `snapshots\bulkviz_before.json` and the checkers from Task 1.
- Produces: `snapshots\bulkviz_after.json` that matches the before snapshot.

- [ ] **Step 1: Run the unchanged importer on the npz manifest and confirm the camera is missing**

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\bulkviz_after.json
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_snapshots.py DEMCSVs\_npz_check\snapshots\bulkviz_before.json DEMCSVs\_npz_check\snapshots\bulkviz_after.json
```

Expected: Blender exits 0, because the camera is skipped silently. The compare FAILS: `camera` differs, and the before-only objects include the tracking camera.

- [ ] **Step 2: Read the camera core from npz and warn when no grain files are found**

Replace line 279:

`    grain_files = sorted(glob.glob(os.path.join(grains_dir, '*.csv')))`

with:

```python
    grain_files = sorted(glob.glob(os.path.join(grains_dir, '*.npz')))
    if SETUP_CAMERA and not grain_files:
        print(f'WARNING: no grain npz files in {grains_dir}; tracking camera skipped '
              '(CSV-era folder? re-run DEMtoCSV.py).')
```

Replace:

```python
            def _core_fn(i, _files=grain_files):
                pts = pd.read_csv(
                    _files[i], usecols=['x_vis', 'y_vis', 'z_vis']
                ).to_numpy(dtype=np.float64)
                return cinematic.grain_core(pts, CORE_GRAIN_FRACTION)
```

with:

```python
            def _core_fn(i, _files=grain_files):
                d = np.load(_files[i])
                pts = np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']]).astype(np.float64)
                return cinematic.grain_core(pts, CORE_GRAIN_FRACTION)
```

Delete line 16, `import pandas as pd`; the old `_core_fn` was its only use. Confirm:

```powershell
Select-String -Path BlenderConvert\DEMBulkVizBlender.py -Pattern "pd\.|import pandas"
```

Expected: no output.

- [ ] **Step 3: Re-run and compare against the reference**

```powershell
& "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe" --background --factory-startup --python-exit-code 1 --python DEMCSVs\_npz_check\tools\run_patched.py -- DEMCSVs\_npz_check\configs\bulkviz_after.json
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\check_snapshot.py DEMCSVs\_npz_check\snapshots\bulkviz_after.json --require VizEjecta DEM_TrackCam --camera-not Camera
.venv\Scripts\python.exe DEMCSVs\_npz_check\tools\compare_snapshots.py DEMCSVs\_npz_check\snapshots\bulkviz_before.json DEMCSVs\_npz_check\snapshots\bulkviz_after.json
```

Expected: no `WARNING: no grain npz files` line, `PASS`, then `MATCH`.

- [ ] **Step 4: Final sweep for leftover grain-CSV reads**

```powershell
Select-String -Path CSVconvert\*.py, viz\*.py, BlenderConvert\*.py -Pattern "grains?_output.*\.csv|GRAINS?_CSV_DIR, '\*\.csv'|grains_dir / .\*\.csv|grain CSV"
```

Expected: no output. Matches on bodies CSVs, such as `bodies_dir / '*.csv'`, are correct and are not caught by this pattern.

- [ ] **Step 5: No commit**

---

## Handoff to the user (after Task 5)

Report to the user:
1. The results of every `PASS` / `MATCH` check above.
2. The files changed (all uncommitted):
   - `CSVconvert/DEMtoCSV.py`
   - `viz/viz_preprocess.py`
   - `viz/viz_preprocess_lite.py`
   - `BlenderConvert/DEMGrainsBlenderEarthCam.py`
   - `BlenderConvert/DEMGrainsBlenderEarth.py`
   - `BlenderConvert/DEMCamera.py`
   - `BlenderConvert/DEMBulkVizBlender.py`
   - `CLAUDE.md` and `docs/BATCHES_VIZ.md` (untracked by git)
3. A reminder that `viz/viz_preprocess.py` and `DEMBulkVizBlender.py` already had uncommitted Option A changes before this work. A commit of those files will include both sets of changes.
4. A suggested GUI check: open `DEMGrainsBlenderEarthCam.py` in the Scripting tab, set `GRAINS_CSV_DIR` / `BODIES_CSV_DIR` to `DEMCSVs/_npz_check/npz/sobol_20260705_131545_baseline_58deg/run_0001_{grains,bodies}_output/`, click **Run Script**, then scrub frames 1–4 and confirm the grains, Earth and the camera.
5. Existing CSV-era grain folders (for example `torque_align_obj/run_0001`) are no longer readable. Reconverting needs the WSL dumps, and `torque_align_obj`'s dumps no longer exist. Its `run_0001_viz_instance*` assets are already built and unaffected, but `viz_preprocess_lite.py` / `synthetic_flyby_test.py` cannot be re-run on that run.
6. `DEMCSVs\_npz_check\` is test scaffolding. Ask before deleting it. Commit only when the user asks.
