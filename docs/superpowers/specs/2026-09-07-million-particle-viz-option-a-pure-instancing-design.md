# Million-Particle DEM Visualisation — Option A: Pure Point-Instancing

**Date:** 2026-09-07 (revised after accuracy review)
**Scope:** SCI4502 Objective 3 — automated Blender visualisation at 10⁵–10⁶ grains
**Status:** Alternative option — for comparison against `2026-09-07-million-particle-viz-design.md` (the "layered composite" plan). Not yet chosen; not yet implemented.
**Relationship to existing spec:** This document does **not** replace `2026-09-07-million-particle-viz-design.md`. It proposes a materially simpler architecture for the same Objective 3 goal, to be evaluated against it before either is committed to an implementation plan.

**Design principle — additive, not replacement:** Like the layered-composite spec, Option A is an **additional** path — not a rewrite of current Blender or CSV tooling. `DEMtoCSV.py`, `DEMGrainsBlenderEarth*.py`, `DEMCamera.py`, `MaterialandSubsivision.py`, and the point-mass scripts stay unchanged and remain the default for ≤~2000-grain runs. New code (`viz_preprocess_lite.py`, `DEMBulkInstanceBlender.py`) is selected per run via `_viz/manifest.json` (`viz_mode: "instance"`) or explicit config. All three paths (per-sphere, composite bulk, pure instancing) can coexist in the repo; shot planning picks the appropriate one.

---

## Problem

Same as the existing spec: `DEMGrainsBlenderEarth*.py` creates one Blender **object** per grain, which cannot scale past ~2000 grains (RAM, `.blend` size, viewport responsiveness, Cycles scene-graph cost).

**Fidelity requirement (unchanged, from user):**

| Phase | What matters visually |
|-------|----------------------|
| Intact / deforming pile | External shape and bulk deformation — internal grain detail not needed |
| Breakup / disruption | Individual ejected grains and separated fragments must be visible |
| Centre split (two ~equal fragments) | Both fragments must be represented — a single "main body" envelope is wrong |

---

## Prerequisites — upstream simulation (Objective 2)

Identical to the existing spec: this document designs the visualisation pipeline; it does not assume million-grain PHANTOM dumps exist today. Same blockers (`MAXPTMASS=3000` compile cap, O(N²) sink cost, Objective 2 gate on P4). See `2026-09-07-million-particle-viz-design.md` §Prerequisites for full detail — not duplicated here.

**What can proceed now:** all phases below except final 1M validation can run on existing ≤2000-grain data.

---

## Core idea: never build a surface

The existing spec's central move is: cluster grains (FOF), reconstruct a smooth envelope per fragment (SDF + marching cubes), and instance only the leftover ejecta. That buys a smooth-looking bulk body but costs an entire numerical geometry pipeline (vectorized union-find, KD-tree narrow-band SDF evaluation, marching cubes, dynamic mesh object churn per frame).

**Option A's premise: don't reconstruct a surface at all.** Render every grain, every phase, the same way — one small instanced sphere per grain, always. No clustering, no isosurface, no distinction between "envelope" and "ejecta" layers.

This works because Cycles + Geometry Nodes instancing avoids the per-grain **object** overhead that breaks the current pipeline. Whether it fully satisfies the fidelity requirement depends on **particle count, grain radius, and camera distance** — not on instancing alone.

- **Intact pile (far / moderate camera):** at very high *N*, smaller physical grains (same body volume) produce a denser sphere packing; at typical encounter camera distance the pile may read as a solid deforming body. This is **not** guaranteed at np500–2000 with current `GRAIN_VIS_SCALE=50` — there `Reff_vis ≈ 2.4 BU` on a ~15 BU body, so individual spheres remain obvious unless the camera is far or out of focus.
- **Intact pile (close camera):** always discrete spheres with per-sphere shading bumps — no smooth crust. Envelope reconstruction (existing spec) is required for hero close-ups.
- **Breakup / ejecta / centre split:** grains are never merged into an envelope, so separation needs no FOF layer assignment. **Caveat:** an optional `--max-instances` subsample (see below) would break breakup fidelity and must not be used on disruption shots.

**Risks to flag explicitly (central trade-offs vs layered composite):**

| Risk | Detail |
|------|--------|
| Close-range fidelity | Discrete spheres, not a smooth surface |
| np500–2k regression scale | Looks like spheres (same as current per-object import) — not a test of "emergent solid" |
| Bumpy macro surface | Even at 10⁶ grains, specular highlights on each instance can read as faceted regolith, not a smooth shell |
| Viewport vs render | GN instancing may be **render-feasible** while the viewport remains unusable for 10⁵–10⁶ animated points — P0 must measure both |
| Subsample cap | Uniform `--max-instances` saves cost but violates ejecta / centre-split fidelity if used on breakup frames |

---

## Architecture

```
PHANTOM dump
    │
    ├─► DEMtoCSV.py              (existing — unchanged, still used for ≤2k and analysis)
    │
    └─► viz_preprocess_lite.py   (NEW — Windows .venv; reads CSV in P0–P2, direct dump in P4)
            │
            ▼
        DEMCSVs/<sim>/<run>_viz/
            manifest.json
            frames/
              00000.npz   # pos_vis (N×3 float32), radius_vis (N float32)
              00001.npz
              ...
            │
            ▼
        DEMBulkInstanceBlender.py   (NEW — paste into Blender Scripting tab)
            One point-cloud mesh + Geometry Nodes "Instance on Points"
            reuses DEMCamera / Earth import from existing scripts
```

Compare to the existing spec's architecture: no `Code/viz/dem_fof.py`, no `envelopes/` output, no `ejecta/` vs envelope split, no FOF/SDF cost model. `viz_preprocess_lite.py` is a much smaller program than `viz_preprocess.py` in the existing spec — it writes exactly the columns Blender needs to instance spheres, nothing else.

---

## Component 1 — `viz_preprocess_lite.py`

### Input

Same staged approach as the existing spec:

- **P0–P2 (≤2000 grains):** grains CSV per dump (`x_rel_km`, `y_rel_km`, `z_rel_km`, `Reff_km`).
- **P4 (100k–1M grains):** direct PHANTOM dump read via sarracen — required at scale, same reasoning as the existing spec (CSV at 1M rows × 100 frames is tens of GB).

### Processing

There is no clustering step. Per frame:

1. Read grain positions (body-frame km) and radii.
2. Multiply by `GRAIN_VIS_SCALE` (50.0, same shared constant as `DEMtoCSV.py` and the existing spec) → `pos_vis`, `radius_vis`.
3. Write `frames/{t:05d}.npz`: `pos` (N×3 float32), `radius` (N float32).

No mass-weighted centroid, no FOF, no `rg_ratio`, no fragment labeling. (These remain available from the existing WSL analysis scripts for the thesis's physics analysis — this pipeline is rendering-only and does not need to duplicate them.)

### Optional: instance cap (last resort — fidelity trade-off)

If P0 profiling shows render or viewport cost is unacceptable even with low-poly instance meshes, add `--max-instances` (mass- or random-weighted, seeded). **Unlike** the composite spec's ejecta-only cap, a uniform subsample removes grains from intact piles and fragments alike — acceptable only for exploratory viewport previews or distant "bulk shape" shots, **not** for breakup / centre-split thesis figures. Log warnings in `manifest.json` when subsampling is active.

### Output layout

```
DEMCSVs/<sim_name>/<run_name>_viz/
  manifest.json
  frames/
    00000.npz
    00001.npz
    ...
```

**`manifest.json`:**

```json
{
  "schema_version": 1,
  "viz_mode": "instance",
  "sim_name": "...",
  "run_name": "...",
  "grain_vis_scale": 50.0,
  "n_frames": 120,
  "frame_ids": ["00000", "00001", "..."],
  "n_grains": 501,
  "input_mode": "csv",
  "bodies_csv_dir": "../run_0001_bodies_output",
  "grains_csv_dir": "../run_0001_grains_output",
  "max_instances": null
}
```

**`viz_mode: "instance"`** distinguishes this layout from the composite spec (`viz_mode: "composite"`). Both may use the same `_viz/` directory convention; Blender scripts must branch on `viz_mode`, not on folder name alone.

Roughly half the fields of the composite manifest — no fragment/ejecta/metrics metadata because clustering is not part of this pipeline. Keep `grains_csv_dir` even though frames are `.npz`: the existing camera helper `_grain_core()` in `DEMGrainsBlenderEarthCam.py` currently reads grain CSVs; at ≤2k P2 can reuse that path, while at P4 scale the Blender script must compute core position from loaded `pos` arrays instead.

### Data volume (sanity check)

At 1M grains: `pos` + `radius` = 4 float32 per grain = 16 bytes/grain → ~16 MB/frame. A 100-frame run is ~1.6 GB total — small enough to keep on local disk without the "tens of GB" problem the existing spec raises for raw grains CSV at this scale.

### CLI

```powershell
.venv\Scripts\Activate.ps1
python viz/viz_preprocess_lite.py `
  --grains-dir DEMCSVs/<sim>/<run>_grains_output `
  --output-dir DEMCSVs/<sim>/<run>_viz

# P4: direct dump input
python viz/viz_preprocess_lite.py `
  --dump-dir //wsl.localhost/Ubuntu/home/mboyle/Honours/sobol_mass_runs/<batch>/run_XXXX `
  --output-dir DEMCSVs/<sim>/<run>_viz `
  --input-mode dump
```

---

## Component 2 — `DEMBulkInstanceBlender.py`

Blender script (requires `bpy`, `numpy`). Paste into Scripting tab like existing DEM scripts.

### Configuration

```python
VIZ_MANIFEST = r".../DEMCSVs/<sim>/<run>_viz/manifest.json"
BODIES_CSV_DIR = r".../run_0001_bodies_output"   # Earth, camera — same as existing
IMPORT_SOLAR_SYSTEM = None   # auto-detect (same as DEMGrainsBlenderEarthCam.py)
CAMERA_MODE = None           # auto: earth_track if Earth present, else grain_only
GRAIN_MESH_SUBDIV = 1        # icosphere subdivision — P0 sweeps 0, 1, 2
USE_FRAME_CHANGE_HANDLER = True  # load npz per frame at render/scrub time
```

### Scene graph

| Object | Purpose |
|--------|---------|
| `DEMPointCloud` | Single mesh, 1 vertex per grain; point-domain `radius` float attribute |
| Geometry Nodes modifier on `DEMPointCloud` | `Instance on Points` → shared icosphere; scale from `radius` via **Scale Instances** (or equivalent) |
| Earth / Sun / camera | Reuse logic from `DEMGrainsBlenderEarthCam.py` |

No `VizFragment_00..K` objects, no dynamic object creation/deletion per frame — exactly **one** grain mesh object for the whole run. This removes the composite spec's dynamic fragment bookkeeping entirely.

**Vertex count is fixed** after first frame (same *N* as simulation). If dump grain count ever changes mid-run (unusual for fixed `np_apophis` campaigns), resize the mesh once and rebuild the GN tree — do not assume *N* is constant without checking `manifest.json` → `n_grains` per frame in P4.

### Per-frame animation

Same model as the composite spec's ejecta layer — **baked vertex motion**, not shape keys:

1. On `frame_change_pre` (or explicit pre-render loop): load `frames/{t:05d}.npz`.
2. `mesh.vertices.foreach_set("co", pos.ravel())`.
3. Update point attribute: `mesh.attributes["radius"].data.foreach_set("value", radius)` (create attribute on first frame if missing).
4. `mesh.update()` — GN modifier re-evaluates instance transforms for the new point positions.

Single code path for every phase (intact, breaking up, dispersed). No branch on fragment count or unbound fraction.

**Python update cost (often underestimated):** `foreach_set` on 10⁵–10⁶ vertices is typically **milliseconds to multiple seconds per frame** depending on hardware and Blender version — separate from Cycles ray-tracing cost. P0 must time this explicitly. If scrubbing is too slow, options are: (a) render via batch `frame_set` + write PNG without interactive viewport, (b) lower `--max-instances` for preview only, (c) fall back to composite envelopes for intact-phase shots.

**Camera core tracking:** reuse `_grain_core()` from CSV at ≤2k; at scale, compute the same centroid from the loaded `pos` array (closest fraction to origin in body frame) so P4 does not depend on grains CSV.

### Triangle-budget check (feasible — not proven)

Cycles renders GN **instances** without creating 1M Blender objects; cost scales roughly with `(instance count × instance mesh complexity × shading cost)`, not scene-graph object count. Reference numbers for P0 to validate on **project hardware** (do not treat as pass/fail thresholds):

| Instance mesh | Tris / instance | 1M instances (total) |
|---------------|-----------------|----------------------|
| Ico sphere subdiv 0 | 20 | ~20M |
| Ico sphere subdiv 1 | 80 | ~80M |
| Ico sphere subdiv 2 | 320 | ~320M |

20M–80M instanced triangles **may** be renderable on a modern GPU with patience (minutes per frame at full HD is plausible). Viewport interaction at 10⁵–10⁶ GN points is often **much worse** than final Cycles render — measure both in P0. Subdiv 0 is the default starting point for the spike.

Instancing does **not** guarantee a single static BVH for all time: per-frame point motion forces GN/Cycles to update instance transforms (and possibly refit acceleration structures) every frame. Still far cheaper than 1M keyframed objects, but not free.

### Material

One shared rock/regolith material on the **instance mesh** (assigned once to the icosphere used by GN). Copy shader settings from an existing `DEM_Grain_*` object manually or from a template `.blend` — `MaterialandSubsivision.py` propagates materials across separate grain **objects** and is not directly applicable to GN instancing without adaptation.

---

## Component 3 — integration with existing code

| File | Change |
|------|--------|
| `CSVconvert/DEMtoCSV.py` | Unchanged. Remains primary path for ≤2k analysis CSV. |
| `DEMGrainsBlenderEarth*.py` | Unchanged. |
| `DEMBulkInstanceBlender.py` | **New** |
| `viz/viz_preprocess_lite.py` | **New** |
| `docs/BATCHES_VIZ.md` | Add `_viz/` output paths (same directory convention as the existing spec, different contents) |
| `CLAUDE.md` | Document bulk pipeline selection alongside whichever option is chosen |

No `Code/viz/dem_fof.py`, no WSL sync/import step — this option has no clustering code to share between repos.

---

## Testing strategy

1. **Regression:** existing `run_0001` np500 CSV → per-sphere import still works unchanged.
2. **Visual parity spike (P0):** render np500–2000 via `DEMBulkInstanceBlender.py` side by side with the existing per-sphere importer — instancing should look identical at this scale (it's the same spheres, different mechanism).
3. **Deformation:** intact np500–2000 run — bulk shape reads as deforming at typical camera distance; explicitly check how it looks at close range (this is the known risk — capture reference frames for the thesis writeup either way).
4. **Centre split:** run with known binary breakup — both fragments visible with no extra logic (nothing to fail here, since nothing merges grains).
5. **Performance spike (P0, critical path):** minimal `DEMBulkInstanceBlender.py` stub + GN setup; synthetic or replicated positions at 10³, 10⁴, 10⁵, 10⁶ points. Measure on **project hardware** with **Cycles** (this project's render engine):
   - viewport FPS while scrubbing timeline (with GN modifier live);
   - `foreach_set` + `mesh.update()` wall time per frame;
   - Cycles render time per frame (subdiv 0 and 1, 128 samples or project default);
   - peak RAM (Blender process + GPU).
   If 10⁶ fails render or Python update exceeds acceptable batch-render budget, Option A does not replace envelope work for full-fidelity output — document the ceiling and compare to composite spec costs.
6. **Scale end-to-end (P4):** 100k–1M direct-dump preprocess + Blender manifest load — only after Objective 2 produces matching runs, same gate as the existing spec.

---

## Implementation phases

| Phase | Deliverable | Success | Gate |
|-------|-------------|---------|------|
| **P0 — Performance spike** | Minimal GN stub (no preprocess yet): synthetic/replicated points at 10³–10⁶; subdiv 0/1; measure viewport scrub, Python update time, Cycles render, RAM | Documented cost curve on project hardware; **go/no-go at 10⁵–10⁶**, or clear ceiling | None — start here, before any other Option A work |
| **P1 — Preprocessor** | `viz_preprocess_lite.py` on np500–2000 CSV | Manifest + frames match existing grain positions | P0 shows instancing is viable |
| **P2 — Blender automation** | `DEMBulkInstanceBlender.py` + camera/Earth on np500–2000 `_viz/` manifest | End-to-end render one animation without manual Blender steps | P1 complete |
| **P3 — Close-range visual check** | Reference renders at close camera distance on intact pile | Documented answer to the "does it look like a solid body up close" risk — informs thesis shot planning either way | P2 complete |
| **P4 — Scale** | Direct sarracen dump input; batch preprocess; optional instance cap if P0 numbers demand it; 100k–1M validation | Objective 3 success criterion on a real 1M Objective 2 run | Objective 2 complete; Daniel/supervisor sign-off on tree-indexed dumps |

**Note the inverted risk order versus the existing spec:** the existing spec's biggest unknowns (FOF perf, SDF perf) are deferred to P1–P2 after committing to the architecture. Option A's biggest unknown (does GN instancing hold up at 10⁶) is P0, before writing any real pipeline code — because if it doesn't hold up, nothing else in this document is worth building.

---

## Comparison at a glance

| | Existing spec (layered composite) | Option A (pure instancing) |
|---|---|---|
| Clustering (FOF) | Required, custom, vectorized | None |
| Surface reconstruction | Required (SDF + marching cubes) | None |
| New WSL/Windows shared module | `Code/viz/dem_fof.py` | None |
| Blender scene objects | 1–5 envelope meshes + 1 ejecta cloud, dynamic count | 1 point mesh + GN, fixed |
| Manifest complexity | Fragment + ejecta + metrics per frame | Position + radius per frame; `viz_mode: "instance"` |
| Intact pile at thesis camera (far) | Smooth envelope | Dense spheres — may read as solid at high *N* |
| Close-range / hero shot | Smooth reconstructed surface | Discrete bumpy spheres |
| np500–2k comparison | Envelope vs per-sphere reference | Same spheres as current import (mechanism only) |
| Breakup / centre split | FOF multi-envelope + ejecta | Automatic (no clustering) unless subsampled |
| Preprocess at 1M | FOF + SDF (heavy CPU) | Positions only (~16 MB/frame — accurate) |
| Biggest untested assumption | KD-tree narrow-band SDF perf at 10⁶ (P2) | GN + Python update + Cycles at 10⁶ (P0) |
| Engineering surface area | Large | Small (if P0 passes) |

---

## Success criterion (Objective 3)

Same as the existing spec: a million-particle run renders end-to-end without manual Blender intervention. Under Option A, "partial success" before Objective 2 completes is P2–P3 on ≤2000-grain data plus a P0 performance number extrapolated toward 10⁶.

---

## Review verdict (2026-09-07)

**Accurate:** Problem statement, Objective 2 gate, architecture simplification, centre-split without FOF, npz data-volume estimate (~16 MB/frame at 1M), P0-before-build risk ordering, and the core trade-off (smooth envelope vs discrete spheres).

**Overstated (corrected above):** "Sub-visible spheres" at all scales; "20M triangles well within GPU" without viewport/Python-update caveats; "MaterialandSubsivision.py pattern" applies directly to GN; manifest schema compatible with composite spec without `viz_mode`.

**Feasibility summary:**

| Scale | Option A verdict |
|-------|------------------|
| ≤2k (P1–P3) | **Feasible** — equivalent to current per-sphere look; validates automation only |
| 10⁵ grains | **Plausible** — likely renderable with low-poly instances; viewport may need batch render |
| 10⁶ grains | **Unproven** — P0 go/no-go; if render passes but viewport fails, still OK for Objective 3 batch animation |
| Hero close-up intact pile | **Poor fit** — use composite spec or current per-sphere import |
| Breakup / centre split | **Good fit** — if full *N* rendered (no subsample cap) |

**Recommended decision path:** Run Option A P0 (1–2 days, minimal code) **in parallel with** composite P0 (convex-hull envelope on np500). They test different risks. Choose hybrid policy if both pass: **Option A for breakup runs; composite (or per-sphere ≤2k) for intact hero shots** — not mutually exclusive at the manifest/`viz_mode` level.

---

## Open question for decision

Both documents target the same Objective 3 success criterion from different risk profiles. The deciding question is empirical and cheap to answer: **run Option A's P0 spike** (GN stub + synthetic points on project hardware) before committing to either architecture. If instancing holds up at 10⁵–10⁶ for batch Cycles renders, Option A supersedes most of the composite spec's P1–P2 work for **disruption-focused** figures. If it doesn't, or if close-range smooth intact shots are required, the composite spec's envelope reconstruction remains necessary. P0 results should be recorded in a short table (N, subdiv, viewport FPS, update ms, render s/frame, RAM) attached to whichever implementation plan follows.
