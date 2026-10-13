# Blender visualisation datasets

Paths relative to `Code/DEMCSVs/`. After WSL conversion, each run has `<run>_bodies_output/` and `<run>_grains_output/` subfolders.

| Folder | WSL batch | Runs | Role | Blender notes |
|--------|-----------|------|------|---------------|
| `torque_align_obj/` | `sobol_20260601_171137_torque_align_blender_vis_obj` | run_0001 (~11°, intact), run_0002 (~177°, breakup) | OBJ crop, P=1.52 h, kc=10⁷, np≈500 | Thesis Table 6.1 / Figs 6.6–6.7; per-sphere or bulk composite |
| `torque_align_obj/run_0001_viz_instance/` | `sobol_20260601_171137_torque_align_blender_vis_obj` | run_0001 | 1,000,000-point static placeholder cloud — rejection-sampled inside the JPL Apophis radar shape OBJ, scaled from run_0001's real grain npz / body CSV files | Pure-instancing (Option A) form of the same run_0001 dataset documented above; `viz_mode: "instance"` manifest for `DEMBulkInstanceBlender.py` — see CLAUDE.md "Pure instancing viz" |
| `torque_align_obj/run_0001_viz_instance_flyby_test/` | same as above | run_0001 | 1,000,000-point synthetic rigid tumble, per-frame (`static: false`, `synthetic: true`) — test data, not sim motion | Likely related 1M files (link not recorded): `BlenderConvert/Blenders/flyby_spinning_1M.blend`, `BlenderConvert/Blenders/Renders/Million.png` — see CLAUDE.md "Option A synthetic flyby test" |
| `sobol_20260916_185123_sim_render/` | `sobol_mass_runs/sobol_20260916_185123_sim_render` | run_0001 | First real end-to-end TUI run (np_apophis 500), 2026-09-16 | `run_0001_render_composite/` + `run_0001_render_per_sphere/`: 217 PNGs + `animation.mp4` each |
| `torque_align_obj_fine_dt/` | `sobol_20260601_204015_torque_align_obj_breakup_fine_dt` | run_0001 breakup only | dtmax ≈ 5 min | High frame-rate breakup animation |
| `sobol_20260629_132547_blender_vis_earth_aligned_np500/` | `sobol_20260629_132547_blender_vis_earth_aligned_np500` | run_0001 | Earth-aligned spin vis | Check script comments for figure target |
| `sobol_20260608_163227_torque_align_obj_fine_dt_nospin_np500/` | matching WSL batch | run_0001 | Fine-dt, no-spin variant | Compare to fine_dt with spin |
| `sobol_20261008_193158_breakup_np10k_rp8000/` | same name in `sobol_mass_runs/` | run_0001 | np10k (10,957) frictionless settled body, hyperbola rp 8,000 km, tidal breakup (`../../docs/BATCHES.md`) | `run_0001_render_instance_grains/`: 62 frames, 256 samples + `animation.mp4` + `animation_20fps.mp4` (ffmpeg re-encode, 2026-10-13) |
| `sobol_20261009_104305_breakup_np10k_fric_boulders_rp8000/` | same name in `sobol_mass_runs/` | run_0001 | Same flyby, friction + frictional settle (8,352) + bonded lobes and boulders | `run_0001_render_instance_grains/`: 62 frames, 500 samples + `animation.mp4` (render-only rerun after a CUDA OOM at frame 18). `run_0001_render_instance_grains_slowmo4/`: x4 slowmo, **unfinished** 30/245 frames, no mp4 (WSL `docs/CONTEXT_CHANGELOG.md` 2026-10-12) |
| `mia_ozstar40k_settle/` | `sobol_mass_runs/mia_ozstar40k_settle` (hardlinks to `~/Honours/mia_ozstar/40k/settle/`) | run_0001 | Mia's OzSTAR 40k bundle: cloud collapse, 112,529 grains, `apophis_00000`–`21` (`../../docs/CONTEXT_CHANGELOG.md` 2026-10-10) | `run_0001_render_instance_grains/`: 22 frames, 500 samples, 8 fps + `animation.mp4`; fixed camera, body shrinks in frame |
| `mia_ozstar40k_fly_fb40_x0.5/` | `~/Honours/mia_ozstar/40k/fly_fb40_x0.5` via `sobol/render_dumps.py --encounter hyperbola` | run_0001 | Mia's 40k fb40 body flown at x 0.5 (3 M_E Earth, scaled; changelog 2026-10-12) | `run_0001_render_instance_grains/`: 51 frames + `animation.mp4`; frames 1–9 dark by design (back-lit approach) |
| `mia_ozstar40k_fb40_resettle/` | `sobol_mass_runs/mia_ozstar40k_fb40_resettle` (hardlinks to `~/Honours/mia_ozstar/40k/fb40/`) | run_0001 | Same bundle: cropped body (32,530 grains), 40% in boulders, re-settle `body_00000`–`30` | `run_0001_render_instance_grains/`: 31 frames, 500 samples, 8 fps + `animation.mp4`; body small in frame, boulders not coloured, little motion |
| `_verify_lattice_fix/` | `sobol_mass_runs/_verify_lattice_fix/...` | run_0001 (baseline_58deg, np500, 4 dumps) | Dev/regression for bulk viz (P0–P3) | grain npz / bodies CSV + `run_0001_viz/` after preprocess |

All `*_grains_output/` folders in the table above were CSV-only until the 2026-09-13 CSV→npz migration; running `CSVconvert/grains_csv_to_npz.py` (their WSL dumps are gone, so `DEMDumpConvert.py` can't be re-run) added a same-stem `.npz` next to every grain CSV without touching the CSVs. Readers use the `.npz`.

Legacy flat folders (`run_0001_*`, `MiaDEM_*`, `DEMvis_*`, `1000np *`) predate the `DEMCSVs/<sim>/` layout — prefer the rows above for thesis figures. They also now hold both CSV and npz after the same upgrade.

## Viz path selection

Path table (per-sphere / composite / `instance_grains` / `instance_static`) and D3 status: `../../docs/SHARED_FACTS.md` § Visualisation paths. All paths are **additive** — per-sphere importers are unchanged. Pure-instancing CLI + config: `BLENDER_OPS.md` "Pure instancing viz" section; example dataset: `torque_align_obj/run_0001_viz_instance/` above.

## Bulk composite workflow

### 1. Convert dumps (if not already done)

```bash
python3 sobol/Analysis/run_demtocsv_batch.py --min-dem-grains 450 \
  --base-output-dir "/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/_verify_lattice_fix" \
  sobol_mass_runs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001
```

### 2. Preprocess (WSL `python3`)

From `~/Honours/Code` (`sdf` needs `pip install --user --break-system-packages scikit-image`; `hull` works as-is):

```bash
D=/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code
R="$D/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg"
python3 viz/viz_preprocess.py --grains-dir "$R/run_0001_grains_output" \
  --bodies-dir "$R/run_0001_bodies_output" --output-dir "$R/run_0001_viz" --envelope-method hull
```

Use `--envelope-method sdf` for smoother envelopes (slower). Optional: `--max-frames 1` for a single-frame test.

**Generic template:**

```bash
python3 viz/viz_preprocess.py \
  --grains-dir "$D/DEMCSVs/<sim>/run_XXXX_grains_output" \
  --bodies-dir "$D/DEMCSVs/<sim>/run_XXXX_bodies_output" \
  --output-dir "$D/DEMCSVs/<sim>/run_XXXX_viz" \
  [--envelope-method hull|sdf] [--ejecta-max-instances 50000] [--max-frames N]
```

### 3. Output layout (`run_XXXX_viz/`)

```
run_XXXX_viz/
  manifest.json              # viz_mode: "composite"; frame_ids; relative grains/bodies dir paths
  envelopes/
    00000_f0.npz             # fragment 0 envelope (verts, faces, mass_frac, …)
    00000_f1.npz             # fragment 1+ (breakup / centre-split)
  ejecta/
    00000.npz                # pos, radius, grain_id (vis units)
  metrics/
    00000.json               # rg_ratio, unbound_fraction, n_fragments, n_ejecta
```

One frame index (`00000`, `00001`, …) per sorted grain npz file in `_grains_output/`.

### 4. Blender (bulk composite)

1. Open Blender (Cycles).
2. Scripting tab → open `BlenderConvert/DEMBulkVizBlender.py`.
3. Set `VIZ_MANIFEST` to the **absolute** path of `run_XXXX_viz/manifest.json`, e.g.:

   ```
   c:/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/_verify_lattice_fix/sobol_20260705_131545_baseline_58deg/run_0001_viz/manifest.json
   ```

4. For `apophis_only` runs (no solar-system bodies in bodies CSV): set `IMPORT_SOLAR_SYSTEM = False` and optionally `CAMERA_MODE = 'grain_only'`.
5. Click **Run Script**. Scrub timeline — envelope meshes deform; ejecta appear as GN-instanced spheres on breakup.

Earth model: `BlenderConvert/TheEarth1.blend` (appended automatically when solar system is detected).

## Per-sphere workflow (manual GUI; TUI default is `instance_grains`, per-sphere = parity reference)

1. Open `BlenderConvert/DEMGrainsBlenderEarthCam.py`
2. Set `GRAINS_DIR` and `BODIES_CSV_DIR` to the chosen `run_XXXX_*_output/` paths
3. Run script in Blender Scripting tab (Cycles)
4. Optional: `MaterialandSubsivision.py` after import

## WSL convert command (template)

```bash
python3 sobol/Analysis/run_demtocsv_batch.py --min-dem-grains 450 \
  --base-output-dir "/mnt/c/Users/22boy/OneDrive/Documents/GC-Max_desktop/Honours/Code/DEMCSVs/<folder>" \
  sobol_mass_runs/<batch>/run_XXXX
```

Full CLI and config reference: `../CLAUDE.md` (Bulk composite viz section).
