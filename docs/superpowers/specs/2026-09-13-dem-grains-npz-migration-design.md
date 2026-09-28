# DEM grains CSV → npz migration — design

**Precedes:** the "full simulation and rendering pipeline" work (configure a
PHANTOM run → run it → render headless in Blender). That design was paused
mid-brainstorm: building the pipeline on grain CSVs would bake in a format
about to be replaced. This spec is the prerequisite. The pipeline design
resumes after it lands, with npz as the native grains format.

## Goal

Stop writing per-frame DEM grain data as text CSV. Write it as compressed
binary `.npz` instead: same fields, same one-file-per-dump layout, smaller
and faster to load.

Measured on a real frame (`torque_align_obj/run_0001`, 501 grains × 23
columns, 2026-09-13):

| Format | Size | Load time |
|--------|------|-----------|
| CSV | 200 KB | 8.1 ms |
| `np.savez` | 98 KB | — |
| `np.savez_compressed` | 43 KB | 3.9 ms |

Compressed npz is 4.6× smaller and loads 2× faster, and every value
round-trips exactly. The whole 217-frame run drops from 43.4 MB to about
9 MB. Grain file size scales linearly with `np_apophis`, so the saving grows
with the higher grain counts the pipeline work is aimed at.

## Context

- `CSVconvert/DEMtoCSV.py` reads PHANTOM dumps with `sarracen` and writes two
  files per dump: an 11-row bodies CSV and an `n_grains`-row grains CSV. It
  runs two ways:
  - **Primary:** WSL `sobol/Analysis/run_demtocsv_batch.py` reads the
    script's source, patches `INPUT_DIR` / `BASE_OUTPUT_DIR` /
    `MIN_DEM_GRAINS`, and runs it with
    `exec(compile(...), {"__name__": "__main__"})`. `__file__` is **not**
    defined in that namespace.
  - **Fallback:** run directly on Windows with the `.venv`.
- **Grain-file readers (all of them).** Every one globs `*.csv` in a
  `_grains_output/` folder:

  | File | What it reads | How |
  |------|---------------|-----|
  | `BlenderConvert/DEMGrainsBlenderEarthCam.py` | all columns it needs, every frame; `_grain_core` for the camera | `pd.read_csv` + `iterrows()`; `csv.DictReader` |
  | `BlenderConvert/DEMGrainsBlenderEarth.py` | same import logic, no camera | `pd.read_csv` + `iterrows()` |
  | `BlenderConvert/DEMCamera.py` | `x_vis/y_vis/z_vis` per frame for `_grain_core` | `csv.DictReader` |
  | `BlenderConvert/DEMBulkVizBlender.py` | `x_vis/y_vis/z_vis` per frame for the camera core | `pd.read_csv(usecols=...)` |
  | `viz/viz_preprocess.py` | `_load_grains_csv`: `x_rel_km…`, `Reff_km`, `m`, `vx…`, `grain_id` | `pd.read_csv` |
  | `viz/viz_preprocess_lite.py` | `reference_scale_from_run`: frame 1 `x_vis…`, `Reff_vis` (also used by `viz/synthetic_flyby_test.py`) | `pd.read_csv` |

  Nothing on the WSL side reads grain CSVs
  (`sobol/run_torque_align_blender_reruns.py` only prints a message that
  names `DEMtoCSV.py`). `Data analysis/FirstData.py` reads bodies CSVs only.
- **Bodies are matched to grains by filename.** Both per-sphere importers
  find a frame's bodies CSV with
  `os.path.join(BODIES_CSV_DIR, os.path.basename(grains_path))`. Today both
  files are `sobol_XXXXX.csv`, so this works. Once grains are
  `sobol_XXXXX.npz`, the lookup finds nothing, and the importers **silently**
  drop Earth, Moon, Sun and the Sun lamp: `_detect_solar_system_bodies`
  returns `False` and the script runs in `apophis_only` mode with no error.
  This migration must change the lookup to swap the extension.
- The Blender scripts above are pasted into the Scripting tab. Pasted text
  has no `__file__`, and `DEMGrainsBlenderEarth(Cam).py` and `DEMCamera.py`
  have no `sys.path` setup at all. `numpy` is available in Blender's bundled
  Python.
- The instancing viz path (`viz_preprocess_lite.py`,
  `synthetic_flyby_test.py`) and the composite assets already use
  `np.savez_compressed`. This migration brings the grains stage in line.
- Decisions locked in (via clarifying questions):
  - **Grains only.** Bodies stay CSV: 11 rows per frame is not a space
    problem, and bodies CSVs are shared with the point-mass pipeline and
    `FirstData.py`.
  - **Clean break, no dual-read.** Updated readers read npz only. Existing
    CSV run folders stay on disk but are no longer read. To use an old run,
    re-run the conversion against its WSL dumps.

## Schema

One file per dump, written with `np.savez_compressed`, in the same folder
(`DEMCSVs/<sim>/<run>_grains_output/`) with the same basename as today and a
`.npz` extension (`sobol_00003.npz`).

One array per column that `DEMtoCSV.py` writes today. No columns added or
dropped, and no dtype changes: every float stays `float64`. The measurement
above confirmed that `float64` round-trips exactly, so any reader's output is
bit-identical to the CSV version.

| Key | dtype | Shape | Notes (unchanged from CSV) |
|-----|-------|-------|------|
| `grain_id` | `int64` | `(n,)` | `0…n-1` |
| `time_s` | `float64` | `()` | scalar; the CSV repeated it on every row |
| `x_au`, `y_au`, `z_au` | `float64` | `(n,)` | absolute heliocentric; not for grain placement |
| `x_km`, `y_km`, `z_km` | `float64` | `(n,)` | absolute, km |
| `x_rel_km`, `y_rel_km`, `z_rel_km` | `float64` | `(n,)` | relative to Apophis CoM |
| `Reff_km` | `float64` | `(n,)` | grain effective radius |
| `h_km` | `float64` | `(n,)` | smoothing length, km |
| `x_vis`, `y_vis`, `z_vis` | `float64` | `(n,)` | `x_rel_km × GRAIN_VIS_SCALE`; Blender location |
| `Reff_vis` | `float64` | `(n,)` | `Reff_km × GRAIN_VIS_SCALE`; Blender radius |
| `m` | `float64` | `(n,)` | code-unit mass |
| `vx`, `vy`, `vz` | `float64` | `(n,)` | NaN-filled if absent from the dump |
| `spinx`, `spiny`, `spinz` | `float64` | `(n,)` | NaN-filled if absent |

`time_s` becomes a 0-d array because an npz stores arrays, and repeating a
scalar `n` times wastes space. Readers that need it use `float(d['time_s'])`.
No current grain reader uses `time_s`; the importers take time from the
bodies CSV.

Save arrays only. `np.load` defaults to `allow_pickle=False`, and nothing in
this schema needs pickling.

## Architecture

```
CSVconvert/DEMtoCSV.py ──np.savez_compressed──▶ <run>_grains_output/sobol_XXXXX.npz
                                                         │
                                  np.load (directly, in each reader)
        ┌───────────────┬───────────────┬────────────────┼─────────────────┬──────────────────┐
DEMGrainsBlender   DEMGrainsBlender  DEMCamera.py  DEMBulkVizBlender.py  viz_preprocess.py  viz_preprocess_lite.py
   EarthCam.py        Earth.py
```

**No shared helper module.** Each reader calls `np.load` directly. The
earlier draft proposed `viz/grain_npz.py` with read/write wrappers, but that
module would have to be importable from two places where it cannot be
reached cleanly:

1. `DEMtoCSV.py` under `run_demtocsv_batch.py`'s `exec()`, where `__file__`
   is undefined, so the `Path(__file__).parents[1]` repo-root pattern raises
   `NameError`.
2. Four pasted-into-Blender scripts with no `__file__` and no `sys.path`
   setup. Each would need a hard-coded fallback path.

The wrappers would only add key-set validation. `np.load` already gives a
clear error for a missing key (`KeyError: 'x_vis is not a file in the
archive'`). The writer builds all 24 arrays in a single dict literal. One
shared module is not worth that plumbing in five files. The schema is
documented in one place, the `CLAUDE.md` table, with `DEMtoCSV.py` as the
reference implementation.

## Component changes

**`CSVconvert/DEMtoCSV.py`**
- Build the grains data as a `dict` of numpy arrays instead of a DataFrame.
  Missing `vx…spinz` become `np.full(n_dem, np.nan)`, since a scalar `np.nan`
  only broadcast inside the DataFrame. `grain_id` becomes
  `np.arange(n_dem, dtype=np.int64)`. `time_s` becomes `np.float64(time_s)`.
- Write with `np.savez_compressed(grains_out, **grains)`, where `grains_out`
  is `basename + ".npz"`.
- Bodies DataFrame and `bodies_df.to_csv(...)` are unchanged.
- The summary print already uses in-memory arrays; only the "Written:" path
  changes.
- The filename stays `DEMtoCSV.py`. It still writes the bodies CSV, and
  `run_demtocsv_batch.py` and the docs hard-code the name. A rename is not
  worth that churn.
- No change needed in `run_demtocsv_batch.py`. It patches only the three
  config lines, and all three are unchanged.

**`BlenderConvert/DEMGrainsBlenderEarthCam.py`** and
**`BlenderConvert/DEMGrainsBlenderEarth.py`** (same edits, applied to both)
- `import numpy as np`.
- Grain glob `*.csv` → `*.npz`. Rename `csv_files` → `grain_files`.
- `_bodies_csv_for(grains_path)`: look up
  `os.path.splitext(os.path.basename(grains_path))[0] + '.csv'`. **This fixes
  the silent Earth/Sun/Moon drop.**
- Sphere-creation pass: `first = np.load(grain_files[0])`,
  `n_grains = len(first['grain_id'])`, then loop with
  `zip(first['grain_id'], first['Reff_vis'], first['x_vis'], first['y_vis'], first['z_vis'])`
  instead of `iterrows()`.
- Keyframe pass: same change per frame. The body-CSV block in the same loop
  is unchanged apart from the `_bodies_csv_for` fix.
- `_grain_core` (EarthCam only): load `x_vis/y_vis/z_vis` with `np.load`,
  sort by distance with `np.argsort`, and take the mean of the closest
  `fraction`. Keep `n = max(1, int(len * fraction))` so the result is
  identical. Return a `Vector`.
- Error text that says "No CSVs found" → "No grain npz files found… run
  DEMtoCSV.py first".
- **Do not** wrap either script in `main()`. That refactor belongs to the
  sim+render pipeline design.

**`BlenderConvert/DEMCamera.py`**
- Grain glob `*.csv` → `*.npz`. Update the `GRAIN_CSV_DIR` comment and error
  text. The variable name stays, because users edit it by name and it must
  match `GRAINS_CSV_DIR` in the importer.
- `_grain_core`: same vectorised `np.load` version as above.

**`BlenderConvert/DEMBulkVizBlender.py`**
- `main()`: grain glob `*.csv` → `*.npz`.
- `_core_fn`: replace `pd.read_csv(usecols=[...])` with
  `np.column_stack([d['x_vis'], d['y_vis'], d['z_vis']])` from
  `d = np.load(path)`. `cinematic.grain_core` already takes an `(n, 3)`
  array, so nothing else changes.
- If `SETUP_CAMERA` is on but no grain files are found, print a warning
  naming the grains folder. Today the camera is skipped silently.
- Remove the `pandas` import if nothing else uses it.

**`viz/viz_preprocess.py`**
- Rename `_load_grains_csv` → `_load_grains`. Build the same
  `{pos, radii, mass, vel, grain_id}` dict from `np.load`:
  `np.column_stack` for `pos` and `vel`, `np.nan_to_num` on `vel` as today.
  The `m` and `grain_id` fallbacks stay: `if 'm' in d.files`.
- Glob `*.npz`. Rename `csv_files` → `grain_files`. Error text "No grain npz
  files in …".
- Update the module docstring and the `--grains-dir` help text. Remove the
  `pandas` import (nothing else uses it).
- `--input-mode` choices become `("npz", "dump")` with default `"npz"`, and
  the manifest records `"input_mode": "npz"`. Nothing reads that field. The
  manifest keys `grains_csv_dir` / `bodies_csv_dir` keep their names, because
  `DEMBulkVizBlender.py` reads `grains_csv_dir`.
- Downstream `_process_frame` code is untouched.

**`viz/viz_preprocess_lite.py`**
- `reference_scale_from_run`: glob `*.npz`, `np.load` the first file, and
  keep the same required-key check, now against `d.files`. The return value
  is unchanged, so `viz/synthetic_flyby_test.py` needs no edit.
- The bodies-CSV glob in this file is unchanged.

**`CLAUDE.md`**
- Line 34 (project overview) and line 366 (pure instancing): "grain/body
  CSVs" → "grain npz / body CSVs".
- Directory layout (line 75): `<run>_grains_output/   # one .npz per dump (n_grains entries)`.
- Pipeline B diagram (line 130): `…_grains_output/*.npz   (n_grains entries; one per DEM grain)`.
- "Grains CSV" section (line 194): retitle "Grains npz", replace the table
  with the schema table above (it adds `time_s`, `x/y/z_km`, `h_km`, `m`,
  which the current doc table omits), and add one line on reading it with
  `np.load` and `float(d['time_s'])`.
- Composite prerequisites (line 267) and frame-index note (line 317): "grain
  CSVs" → "grain npz files".
- Line 512 (`DEMGrainsBlenderEarth.py` entry): "Reads CSVs from" → "Reads
  grain npz files from".
- Add one line under DEM-specific notes: bodies are matched to grains by
  basename with the extension swapped, and old CSV-format grain folders must
  be reconverted.

**`docs/BATCHES_VIZ.md`**
- Line 79: "per sorted grain CSV" → "per sorted grain npz file".

**Not changed:** `run_demtocsv_batch.py`, `synthetic_flyby_test.py`,
`DEMCinematicSetup.py` (reads bodies only), `P0_InstancingSpike.py` (no grain
files), `FirstData.py`, the point-mass pipeline, and historical plan and spec
documents.

## Error handling

- **No grain files in the folder**, including a folder that still holds
  only old CSVs: five readers already raise on an empty glob. Reword each
  message to mention npz and reconversion so a stale folder is diagnosed at
  once. `DEMBulkVizBlender.py` instead skips its tracking camera silently; it
  now prints a warning.
- **Missing key** (file from an older or foreign schema): `np.load` raises
  `KeyError` naming the key. The existing `m` / `grain_id` / velocity
  fallbacks in `viz_preprocess.py` stay.
- **Corrupt or truncated npz:** `np.load` raises (`BadZipFile` / `ValueError`)
  on the first access. This is the same fail-loudly behaviour as a corrupt
  CSV today. `DEMtoCSV.py`'s per-dump `try/except` still catches failures
  while writing.
- **Mixed folder** (old `.csv` and new `.npz` side by side after
  reconverting in place): readers glob `*.npz` only. Frame order is still
  correct because the stems are unchanged. Reconverting into a fresh
  `--base-output-dir` avoids the mix entirely.
- **Missing bodies file for a frame:** unchanged behaviour. Earth and Sun are
  skipped for that frame. After the extension fix, this happens only when the
  bodies CSV is genuinely absent.

## Out of scope

- Bodies CSVs, the point-mass pipeline, and `FirstData.py`.
- Reconverting existing `DEMCSVs/` run folders.
- The sim+render pipeline TUI and headless render driver, which resume as
  their own design afterwards.
- Refactoring the per-sphere importers into callable `main(config)`
  functions, which is planned as part of the pipeline work.
- Renaming `DEMtoCSV.py`.

## Testing

The step-by-step procedure, scripts and commands are in
`docs/superpowers/plans/2026-09-13-dem-grains-npz-migration.md`.

Use `_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001`.
Its 4 dumps are still on WSL, its bodies CSVs include Earth, and it is small
enough for fast headless Blender checks. (`torque_align_obj/run_0001`'s
dumps no longer exist, so it cannot be reconverted.) Before changing any
code, regenerate a CSV reference from those dumps with the unchanged
`DEMtoCSV.py`, and capture every reader's output from it. Compare the
post-migration outputs against that reference.

sarracen returns `float64` for every sink column (checked 2026-09-13), so the
CSV ↔ npz comparison is exact. Everything downstream of a reader is compared
with a tiny tolerance instead. Building `(n, 3)` arrays with
`np.column_stack` gives a different memory layout from pandas, which can
change summation order. On this run it moved frame 1's `rg_ratio` from
`0.9711788878254409` to `0.9711788878254412`.

1. **Convert.** From WSL, run `run_demtocsv_batch.py` on the run's dumps
   with a fresh `--base-output-dir` (`DEMCSVs/_npz_check/npz`). Confirm the
   grains folder holds 4 `.npz` files and no `.csv`, and the bodies folder
   holds 4 `.csv` files.
2. **Round-trip.** Run an ad hoc script in the scratchpad, not a committed
   test. For three frames (first, middle, last), load the baseline CSV with
   `pd.read_csv(..., float_precision="round_trip")` and the npz with
   `np.load`. Assert `np.array_equal(..., equal_nan=True)` for every shared
   column, and assert `time_s` matches the CSV's first row. The default
   pandas float parser can differ in the last bit, so `round_trip` is
   required for an exact comparison.
3. **Composite preprocess.** Run `viz_preprocess.py` against the CSV
   reference *before* the change, then against the npz folder after it.
   File sets and integer arrays must match exactly. Floats in
   `metrics/*.json`, `envelopes/*.npz` and `ejecta/*.npz` must match within
   a relative tolerance of `1e-12`. In the manifest, only `input_mode` may
   differ.
4. **Instancing preprocess.** Call `reference_scale_from_run` on both
   folders, before and after the change. `n` must be equal. The two radii
   must match within a relative tolerance of `1e-12`, because pandas and
   numpy means can differ in the last digit.
5. **Per-sphere import, run headless.** Run `DEMGrainsBlenderEarthCam.py`
   with `blender --background --python`, paths set to the npz folder.
   - Grain object count equals `n_grains`.
   - `DEM_Grain_000`'s location at frames 1 and 100 equals that frame's
     `x_vis/y_vis/z_vis`.
   - The `Earth`, `Moon` and `Sun_Visual` objects exist and have location
     keyframes. **This check catches the basename bug.**
   - The console prints "full solar system", not "apophis_only".
6. **Other readers.**
   - `DEMGrainsBlenderEarth.py`: repeat the step 5 checks.
   - `DEMCamera.py`: run after step 5's import without the camera, and
     confirm `DEM_TrackCam` has keyframes on every frame.
   - `DEMBulkVizBlender.py`: point it at step 3's manifest, and confirm the
     camera is keyframed and aimed at the grain core. Compare every object's
     transform on every frame with a run against the CSV reference; they
     must match within `1e-9` BU.
