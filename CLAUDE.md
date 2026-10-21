# CLAUDE.md — Code (post-processing repo)

PHANTOM dumps → bodies CSV + grains npz → Blender renders; composite/instance_grains preprocess can read the dumps directly (`viz/dump_frames.py`, `viz/viz_preprocess_dump.py` = one read per dump for both). Parent hub: `../CLAUDE.md`. Shared facts (layout, viz path names, D3 = composite): `../docs/SHARED_FACTS.md`. Context protocol: `../docs/AGENT_CONTEXT.md`.

## Code vs data (since 2026-09-25)

| What | Where | Backup |
|------|-------|--------|
| Code + context (`*.py`, `CLAUDE.md`, `docs/*.md`) | WSL `~/Honours/Code` | git → GitHub `HonoursWin` (`onedrive` remote = old copy) |
| Data: `DEMCSVs/`, `csv_output/`, `ShortCSVlist/`, `.blend`, `BlenderConvert/{Blenders,Shapes,assets}`, `.venv`, renders, `docs/p0_*` | OneDrive `C:\Users\22boy\OneDrive\Documents\GC-Max_desktop\Honours\Code` (WSL `/mnt/c/...`) | OneDrive |

- Windows tools (`blender.exe`, `.venv` python) reach code via `\\wsl.localhost\Ubuntu\home\mboyle\Honours\Code` (WSL must be running).
- Machine paths (data, assets, `blender.exe`, preprocess python, Cycles device): `honours_paths.py` = env > gitignored `local_paths.json` > Max-laptop defaults (no file = unchanged). Write/check with `sobol/setup_paths.py [--check]`. Windows children get `HONOURS_*` via `WSLENV` (`child_env`). Missing assets fall back: stand-in rock material, bare-sphere Earth, black sky. Other-machine quickstart: `README.md`; example pack: `make_asset_pack.py` → `<data>/share/honours_viz_pack.zip` (no materials/textures/HDRI).
- **Stale-copy trap:** old `.py` files still sit in OneDrive `BlenderConvert/` until retired. Opening a script there, or reopening a `.blend` saved with an auto-run Text block, runs the frozen copy. Open scripts from the WSL path; re-save such `.blend` files.

## Confirm before assuming

- **Cycles, not EEVEE.** Never offer an EEVEE-only diagnosis (Z-fighting depth buffer, froxels).
- **Blender version** — last confirmed 2026-09-07: 5.2.1 LTS, `C:\Program Files\Blender Foundation\Blender 5.2\blender.exe`, Python 3.13, numpy bundled, pandas added by hand (`AppData\Roaming\Blender Foundation\Blender\5.2\scripts\addons\modules`; stock Blender lacks it), no psutil; RTX 4050 6 GB, OPTIX/CUDA. API era: `group.interface.new_socket`, "Specular IOR Level", `SequenceEditor.strips`.
- **Which `.blend` / scene / object**, and how it looked in the source file.
- **Which `DEMCSVs/` run** (intact vs breakup, fine-dt vs standard, which `run_XXXX_*_output/`).
- Glitch → **simplest cause first** (coincident geometry / Z-fighting, shared radius) before precision/engine theories.
- **Units:** `udist = 1 km`, `umass = M☉`, `G = 1` → `*_km` / `Reff_km` columns **are** code units. Do not "fix" `eps = ½v² − m/r`. Verify against data before claiming a unit bug. Detail: `docs/PIPELINE_REFERENCE.md`.

## Layout (code only; data folders listed above)

```
BlenderConvert/   Blender scripts (paste into Scripting tab unless noted headless)
CSVconvert/       DEMDumpConvert.py (DEM → CSV + npz), ToCSVFirst.py (point-mass), grains_csv_to_npz.py
viz/              bulk-viz preprocess: viz_preprocess.py (composite), viz_preprocess_grains_instance.py (+ fcurve_handles.py),
                  viz_preprocess_lite.py + synthetic_flyby_test.py (Blender Python), dem_fof, envelope, shape_sampling, path_utils, constants
Data analysis/    legacy: FirstData.py (point-mass bodies-CSV folders → closest-approach plots; `runs` = placeholders), run_sobol_phantom.sh (pre-runner prototype)
Rcode/, Learning.py, cursorrules   legacy
docs/             BATCHES_VIZ.md (canonical datasets), PIPELINE_REFERENCE.md, BLENDER_OPS.md (WSL commands), README.md (index)
```

## Pipelines (one line each; diagrams + schemas: `docs/PIPELINE_REFERENCE.md`)

- **A point-mass:** `solarsystem1_*` dumps → `ToCSVFirst.py` → `csv_output/` (11-row bodies) → `OnlyEarth_ApophisTrueSize.py`.
- **B DEM (current):** `sobol_mass_runs/<batch>/run_XXXX/` → WSL `sobol/Analysis/run_demtocsv_batch.py` (execs `CSVconvert/DEMDumpConvert.py`) → `DEMCSVs/<sim>/<run>_{bodies,grains}_output/` → composite / instancing Blender scripts (headless) or the per-sphere GUI hero script. Converter reads grains as sinks (sink DEM) or `idem` particles (particle DEM, `Reff = h`); model from run `sobol.setup` — see `../docs/SHARED_FACTS.md`.
  Hyperbola runs (`encounter.json` mode `hyperbola`, from `sobol/run_mass_sobol_phantom.py --encounter hyperbola`): bodies CSV = `Earth` + `Apophis` only (converter names the lone `phantomflyby` sink "Earth", not "Sun"). Blender skips the Moon sphere (no `Moon` row). The Sun and Earth's orientation are the real 2029 ones: `BlenderConvert/sun_geometry.py` fits the Earth-relative hyperbola to every bodies CSV, puts the real closest approach (2029-04-13 21:46 TDB) at the fitted pericentre, and rotates the real Sun direction into the scene. The lamp follows it; a true-size Sun sphere (`Sun_Visual`, 0.27 deg radius, `SUN_VISUAL_DISTANCE_BU` away) is seen by the camera only (no light, shadow or reflection), and the headless driver adds bloom, an imperfect-iris starburst (`sun_flare_psf.py`) and ghosts when it exists (`SUN_GLARE_*`). Fewer than 3 frames: fixed `APOPHIS_ONLY_SUN_DIRECTION` with a warning and no Sun sphere (as for `apophis_only`). Particle-DEM `grain_id` = PHANTOM `iorig`.
- **C SPH+DEM:** excluded from scope. Do not implement.
- Bodies CSV row 10 (Apophis) is a synthetic grain CoM. Grains: `.npz` only; place with `x_vis` (= `x_rel_km × GRAIN_VIS_SCALE=50`), never `x_au`. Grain ↔ bodies files pair by **stem** (`sobol_00003.npz` ↔ `.csv`).
- One-command run (sim → convert → headless render): WSL `sobol/tui_sim_render.py` → `../sobol/CLAUDE.md`.

## Scripts (how-to, flags, config vars: `docs/BLENDER_OPS.md`)

| Script | Role |
|--------|------|
| `DEMGrainsBlenderEarthCam.py` | GUI hero shot: one sphere per grain + Earth + camera (≤~2000 grains). "Procedural rock" from `Blenders/11.blend`, seeded per-grain rotation; hides grains while absent. Not a TUI path. Parity reference for `instance_grains` |
| `DEMBulkVizBlender.py` | Composite (D3): envelope meshes + GN ejecta; set `VIZ_MANIFEST` |
| `DEMBulkInstanceBlender.py` | Pure instancing, `static: true/false`; needs "Procedural rock" pre-appended; `SLOWMO_FACTOR`, `RENDER_RESOLUTION`. Real grains match the hero script except the instance-only tint `GRAIN_COLOUR_VARIATION` (`../docs/SHARED_FACTS.md` § Visualisation paths); scene pieces from `DEMCinematicSetup.py` (`ensure_sun_lamp`/`ensure_moon`/`ensure_sun_visual`/`add_camera_fill_light`) |
| `DEMCinematicSetup.py` | Shared Earth/Moon/Sun + camera module (imported, not run) |
| `DEMHeadlessRender.py` | Headless driver for the TUI: `--viz-path composite\|instance` (default `instance`), text-patches + `exec`s the script, HDRI world, OPTIX/CUDA GPU-only, optional `--encode-video`; `--camera-mode auto|grain_only|earth_fixed|earth_chase` (one per run; `earth_chase` = behind Apophis aimed at Earth, framing `viz/camera_framing.py`) + `--camera-fov DEG`. Does not patch `GRAIN_COLOUR_VARIATION` |
| `../render_queue.py` (Code root, stdlib only) | Second-machine renderer: runs Blender on jobs `sobol/render_dumps.py --queue` wrote to `<data>/DEMCSVs/_render_queue/` (OneDrive); `--watch MIN`, `--list`, `--max-frames N` test. Setup (Windows, no WSL): `docs/DESKTOP_RENDER.md` |
| `P0_InstancingSpike.py` | Headless GN-instancing benchmark → OneDrive `docs/P0_*` (generated, not git) |
| `OnlyEarth_ApophisTrueSize.py`, `CSVtoBlender.py`, `workinglargescaleimport.py`, `Camera.py`, `Viewport.py` | Point-mass pipeline |
| `MaterialandSubsivision.py` | Post-import modifiers/materials on grains |
| `sbmt_mosaic.py` | Standalone SBMT texture mosaic (not Blender) |

- Bulk-path frame handlers do **not** survive quitting Blender unless "Auto Run Python Scripts" is on (`register_self_as_auto_run_module()`).
- Validate `bpy` code headless: `blender --background --python <script>` (no `bpy.context.window`; viewport FPS is GUI-only).
- `blender --background --python` exits 0 on uncaught exceptions unless `--python-exit-code 1`.

## Environment

- `.venv` (OneDrive, Windows): sarracen/pandas/scipy/scikit-image for the TUI preprocess stage. Not for `bpy`. WSL `python3` also has sarracen (runs `DEMDumpConvert.py`).
- `.gitignore` is deny-all + allowlist. New code dir needs `!dir/` + `dir/*` + `!dir/*.ext`. Docs dirs are whitelisted explicitly (`docs/`, `.cursor/rules/`).
- 8 legacy files are committed with CRLF (`.gitattributes` says LF) — renormalize in a separate commit before editing them.
