# Million-Particle DEM Visualisation — Design Spec

**Date:** 2026-09-07 (revised)  
**Scope:** SCI4502 Objective 3 — automated Blender visualisation at 10⁵–10⁶ grains  
**Status:** Revised after external review — ready for implementation plan (P0–P3); P4 gated on Objective 2

**Design principle — additive, not replacement:** This plan adds a **bulk** visualisation path for high-*N* runs. It does **not** retire or rewrite the existing production pipeline. `DEMtoCSV.py`, `DEMGrainsBlenderEarth*.py`, `DEMCamera.py`, `MaterialandSubsivision.py`, and the point-mass scripts remain the default for ≤~2000-grain work, regression tests, and hero per-sphere shots. New code (`viz_preprocess.py`, `DEMBulkVizBlender.py`, `Code/viz/dem_fof.py`) is selected per run via `_viz/manifest.json` (`viz_mode: "composite"`) or explicit config — not by removing the old importers.

---

## Problem

The current Blender pipeline (`DEMGrainsBlenderEarth*.py`) creates one UV-sphere **object per grain**, keyframed per dump. This works for S1-scale runs (~500–2000 grains) but cannot scale to 100k–1M particles: RAM, `.blend` size, viewport responsiveness, and Cycles scene-graph cost all explode.

**Fidelity requirement (from user):**

| Phase | What matters visually |
|-------|----------------------|
| Intact / deforming pile | External shape and bulk deformation — internal grain detail not needed |
| Breakup / disruption | Individual ejected grains and separated fragments must be visible |
| Centre split (two ~equal fragments) | Both fragments must be represented — a single “main body” envelope is wrong |

---

## Prerequisites — upstream simulation (Objective 2)

**This spec designs the visualisation pipeline; it does not assume million-grain PHANTOM dumps exist today.**

Objective 3 (viz) depends on Objective 2 (raise particle count without changing physics). From `SCI4502_SCOPE_CONTEXT.md`:

- Replace O(N²) **sink-particle** pairwise gravity with **tree-indexed particles** (PHANTOM kd-tree).
- Success criterion: a campaign completes the full encounter at **1,000,000 particles**, with wall-clock vs *N* measured at each stage.

**Current blockers (verified):**

| Blocker | Detail |
|---------|--------|
| Compile-time cap | `sobol/Makefile` defaults `MAXPTMASS=3000` — sink array size at build time; production runs are ~500–2000 grains |
| Algorithmic cost | Sink-as-DEM grains use PHANTOM's N-body sink framework; scaling 2k → 1M is ~250,000× worse if interactions remain O(N²), before DEM contact stiffness and timestep constraints |
| Data may not exist | **P4 (1M end-to-end) is gated on Objective 2 completing** and supervisor confirmation that tree-indexed runs produce usable full dumps |

**What can proceed now:** P0–P3 on existing ≤2000-grain data. None of the Blender-side architecture depends on actually reaching 10⁶ grains yet.

---

## Recommended approach: layered composite (no hard mode switch)

Render **all layers every frame**; visibility is data-driven, not a global mesh↔particle toggle.

```
┌─────────────────────────────────────────────────────────┐
│  Layer A — Fragment envelopes (1…K meshes per frame)   │
│  One smooth surface per significant FOF cluster          │
├─────────────────────────────────────────────────────────┤
│  Layer B — Ejecta instances (Geometry Nodes)           │
│  Grains not assigned to any kept cluster               │
└─────────────────────────────────────────────────────────┘
```

**Why not a hard switch?** A threshold on `unbound_fraction` or `dispersion_ratio` causes popping and misses transitional frames (necking before separation). Composite layers stay faithful: envelopes track bound fragments; ejecta appear as soon as grains leave all kept clusters.

**Centre split:** enumerate **all** FOF clusters above a mass threshold, not only the largest. Two ~50/50 fragments → two envelopes. Necking (single connected cluster) → one deforming envelope.

---

## Architecture

```
PHANTOM dump
    │
    ├─► DEMtoCSV.py              (existing — per-grain CSV for analysis & legacy Blender; fine for ≤2k)
    │
    └─► viz_preprocess.py        (NEW — Windows .venv; reads CSV in P0–P2, direct dump in P4)
            │  Code/viz/dem_fof.py (canonical FOF module)
            ▼
        DEMCSVs/<sim>/<run>_viz/
            manifest.json
            envelopes/           frame_XXXX.npz  (K meshes × verts/faces)
            ejecta/              frame_XXXX.npz  (positions, radii, optional grain_id)
            metrics/             frame_XXXX.json (rg_ratio, unbound_frac, n_fragments)
            │
            ▼
        DEMBulkVizBlender.py       (NEW — paste into Blender Scripting tab)
            Geometry Nodes instancing + envelope mesh objects
            reuses DEMCamera / Earth import from existing scripts
```

**Existing per-sphere pipeline is preserved** for ≤~2k grains and regression tests. Path selection is per run — not a repo-wide switch:

| Path | When | Blender script | Preprocess |
|------|------|----------------|------------|
| **Per-sphere (default, unchanged)** | ≤~2000 grains; hero shots; regression | `DEMGrainsBlenderEarth*.py` | `DEMtoCSV.py` only |
| **Composite bulk** | High-*N*; smooth intact envelope + ejecta | `DEMBulkVizBlender.py` | `viz_preprocess.py` → `_viz/` with `viz_mode: "composite"` |
| **Pure instancing** | High-*N*; breakup / centre-split fidelity | `DEMBulkInstanceBlender.py` | `viz_preprocess_lite.py` → `_viz/` with `viz_mode: "instance"` |

No existing script is deleted. Point at the appropriate manifest (or set paths manually) for the run you are rendering.

**Repo boundary:** `Code/` and WSL `sobol/` are **separate git repos**. FOF logic lives in `Code/viz/dem_fof.py` (canonical for Windows preprocess). WSL analysis (`run_mass_sobol_phantom.py`) imports the same module via UNC path or a documented copy/sync step — not the other way around.

---

## Component 1 — `viz_preprocess.py`

### Input

**P0–P2 (≤2000 grains):** grains CSV per dump (`x_rel_km`, `y_rel_km`, `z_rel_km`, `Reff_km`, `grain_id`, mass if available). CSV I/O is acceptable at this scale and keeps parity with `DEMtoCSV.py`.

**P4 (100k–1M grains):** **direct PHANTOM dump read via sarracen is required**, not optional. At 1M rows a single grains CSV is ~150–300 MB; a 100-frame run is tens of GB of CSV before `_viz/` output exists. CSV remains for analysis and legacy Blender import, but bulk preprocess must bypass it at scale.

Positions for envelope construction use **body-frame km** (`x_rel_km` …). Output vertices are multiplied by `GRAIN_VIS_SCALE` (50.0, shared constant with `DEMtoCSV.py`) before writing assets.

### Clustering (`Code/viz/dem_fof.py`)

Refactor FOF helpers from `sobol/run_mass_sobol_phantom.py` into **`Code/viz/dem_fof.py`** (canonical). WSL analysis reuses via UNC import or periodic sync — do not treat `sobol/Analysis/dem_fof.py` as the primary location.

**Mandatory P1 refactor — vectorized connectivity:** the existing `_main_body_mask_fof` uses `cKDTree.query_pairs` (fine) but resolves clusters with a **pure-Python union-find loop over every pair**. At 10⁶ grains this can be millions of Python iterations per frame. During extraction, replace the pair loop with **`scipy.sparse.csgraph.connected_components`** (or equivalent vectorized union-find). Do this in P1, not after profiling at scale.

Functions:

| Function | Source | Role |
|----------|--------|------|
| `_fof_cluster_labels` | **new** | return cluster id per grain at a given link length |
| `_main_body_mask_fof_adaptive` | existing | adaptive link length |
| `_significant_fragment_masks` | **new** | filter clusters by mass ≥ `FRAGMENT_MIN_MASS_FRAC` |
| `_main_body_mask_fof` | existing | largest cluster only (legacy analysis compat) |

**Parameters** (match analysis defaults unless overridden):

- `MAIN_BODY_INTACT_DISP_RATIO` — if `rg_ratio` below this, treat all grains as one fragment (intact pile).
- `FRAGMENT_MIN_MASS_FRAC = 0.05` — clusters below 5% total mass → ejecta layer, not envelope.
- `MAIN_BODY_LINK_FACTOR_*`, `MAIN_BODY_MIN_CLUSTER_FRAC` — same as analysis.

**Per-grain assignment:**

1. Compute `rg_ratio` from mass-weighted radius of gyration vs frame 0.
2. If intact → one cluster (all grains).
3. Else → adaptive FOF → label all clusters → keep those with mass fraction ≥ threshold.
4. **Ejecta mask:** grains whose cluster label is not in kept set, plus high-specific-energy grains within kept clusters (same energy test as `_unbound_mass_main_body`).

### Envelope mesh generation

For each kept cluster, build an external surface from grain spheres `(pos, Reff_km)`.

**P0 spike — convex hull:** 3D convex hull of grain centres inflated by max `Reff` — fast, less accurate at concavities; sufficient for intact deformation proof-of-concept on np500 data.

**P2 — sphere-union SDF + marching cubes:** metaball / implicit surface with **explicit acceleration** (required before scale testing):

Naive evaluation — `min_i (|p - c_i| - r_i)` at every grid point over all grains — is O(grid_points × N) and **will fail at 10⁵–10⁶ grains**. P2 must implement one of:

1. **KD-tree narrow band (recommended):** build `cKDTree` on grain centres. For each voxel in a narrow band around the surface (|SDF| < ε), query only grains within `r_max + voxel_diagonal` of the voxel centre; evaluate union SDF over that subset only.
2. **Coarse splatting pass:** rasterize grain spheres into a low-res occupancy/SDF grid first; refine only occupied cells at higher resolution.
3. **Hierarchical bounds:** octree or chunked processing over spatial bins so each voxel never sees the full grain set.

Pipeline after accelerated SDF: marching cubes (`skimage.measure.marching_cubes` or `mcubes`) at isosurface 0; optional Laplacian smoothing (1–2 iterations).

Output per fragment per frame: `verts` (N×3 float32 BU), `faces` (M×3 uint32).

### Ejecta subset

For Layer B, write only ejecta grains:

- `pos_vis` (N×3 float32), `radius_vis` (N float32), optional `grain_id` (N uint32).

Cap optional `EJECTA_MAX_INSTANCES` (e.g. 50k) for viewport sanity — if exceeded, subsample by mass or random with seed; log warning in manifest.

### Output layout

```
DEMCSVs/<sim_name>/<run_name>_viz/
  manifest.json
  envelopes/
    00000_f0.npz   # fragment 0, dump index 0
    00000_f1.npz   # fragment 1, dump index 0 (centre split)
    ...
  ejecta/
    00000.npz
  metrics/
    00000.json
```

**`manifest.json` (stable schema v1):**

```json
{
  "schema_version": 1,
  "viz_mode": "composite",
  "sim_name": "...",
  "run_name": "...",
  "grain_vis_scale": 50.0,
  "n_frames": 120,
  "frame_ids": ["00000", "00001", "..."],
  "fragment_min_mass_frac": 0.05,
  "ejecta_max_instances": 50000,
  "input_mode": "csv",
  "bodies_csv_dir": "../run_0001_bodies_output",
  "grains_csv_dir": "../run_0001_grains_output"
}
```

`input_mode`: `"csv"` (P0–P2) or `"dump"` (P4).

**Per-envelope `.npz`:** `verts`, `faces`, `fragment_id`, `mass_frac`, `n_grains`.

**Per-ejecta `.npz`:** `pos`, `radius`, optional `grain_id`.

**Per-metrics `.json`:** `rg_ratio`, `unbound_fraction`, `n_fragments`, `n_ejecta`.

### CLI

```powershell
# P0–P2: CSV input
.venv\Scripts\Activate.ps1
python viz/viz_preprocess.py \
  --grains-dir DEMCSVs/<sim>/<run>_grains_output \
  --output-dir DEMCSVs/<sim>/<run>_viz \
  [--fragment-min-mass-frac 0.05] \
  [--ejecta-max-instances 50000]

# P4: direct dump input (required at scale)
python viz/viz_preprocess.py \
  --dump-dir //wsl.localhost/Ubuntu/home/mboyle/Honours/sobol_mass_runs/<batch>/run_XXXX \
  --output-dir DEMCSVs/<sim>/<run>_viz \
  --input-mode dump
```

Batch wrapper mirrors `run_demtocsv_batch.py` (WSL or Windows).

---

## Component 2 — `DEMBulkVizBlender.py`

Blender script (requires `bpy`, `numpy`). Paste into Scripting tab like existing DEM scripts.

### Configuration

```python
VIZ_MANIFEST = r".../DEMCSVs/<sim>/<run>_viz/manifest.json"
BODIES_CSV_DIR = r".../run_0001_bodies_output"   # Earth, camera — same as existing
IMPORT_SOLAR_SYSTEM = None   # auto-detect
CAMERA_MODE = None           # auto
```

### Scene graph

| Object | Purpose |
|--------|---------|
| `VizFragment_00` … `VizFragment_K` | Envelope meshes; vertex positions updated per frame |
| `VizEjecta` | Single mesh with 1 vertex per ejecta grain; Geometry Nodes instances UV sphere at each point |
| Earth / Sun / camera | Reuse logic from `DEMGrainsBlenderEarthCam.py` |

### Envelope animation

For each frame `t`:

1. Load `envelopes/{t:05d}_f{k}.npz`.
2. Create mesh objects on frame 0; subsequent frames update via `mesh.vertices.foreach_set("co", ...)` + `mesh.update()`.
3. Keyframe **object** transform only if fragment CoM motion is stored separately (v1: bake CoM into verts in preprocessor — object stays at origin in Apophis frame, matching current grain scripts).

Dynamic fragment count: if frame `t` has more fragments than `t-1`, create new mesh objects; if fewer, hide extras (don't delete — avoids Blender ID churn).

### Ejecta instancing

- Base mesh: point cloud at ejecta positions (1 vert per grain).
- Geometry Nodes modifier: **Instance on Points** → UV sphere scaled by `radius` attribute.
- Per frame: update point positions via `foreach_set`; single draw call for all ejecta.

Material: shared rock shader from `MaterialandSubsivision.py` pattern (one material, no per-instance object).

### Performance targets

| Scale | Envelopes | Ejecta instances | Expected | Notes |
|-------|-----------|------------------|----------|-------|
| 500 grains (regression) | 1 | 0–50 | Real-time viewport | P0–P3 target data |
| 100k grains | 1–3 | 0–5k | Viewport usable; render OK | Requires Obj 2 intermediate runs |
| 1M grains | 1–5 | 0–50k (capped) | Preprocess + render feasible **if** Obj 2 dumps exist and P2 SDF acceleration works | **P4 only; not schedulable until Obj 2** |

Blender-side load stays low (envelopes + capped ejecta instances). Preprocess wall-clock at 1M is dominated by accelerated SDF and vectorized FOF, not object count.

---

## Component 3 — integration with existing code

| File | Change |
|------|--------|
| `CSVconvert/DEMtoCSV.py` | No schema change required. Optional: write `mass` column if not already present (needed for FOF mass weighting). Remains primary path for ≤2k analysis CSV. |
| `DEMGrainsBlenderEarth*.py` | Unchanged. Document `VIZ_MODE` selection in `CLAUDE.md`. |
| `DEMBulkVizBlender.py` | **New** |
| `viz/viz_preprocess.py` | **New** |
| `Code/viz/dem_fof.py` | **New (canonical)** — vectorized FOF; refactored from `run_mass_sobol_phantom.py` |
| WSL `run_mass_sobol_phantom.py` | Import or sync `Code/viz/dem_fof.py`; remove duplicated FOF loop |
| `docs/BATCHES_VIZ.md` | Add `_viz/` output paths |
| `CLAUDE.md` | Document bulk pipeline, Obj 2 prerequisite, repo boundary |

---

## Testing strategy

1. **Regression:** existing `run_0001` np500 CSV → per-sphere import still works unchanged.
2. **Deformation:** intact np500–2000 run — single envelope tracks bulge/spin deformation vs per-sphere reference (subset comparison).
3. **Centre split:** run with known binary breakup — two envelopes, roughly equal `mass_frac`; no “missing half”.
4. **Ejecta:** frame with high `unbound_fraction` — instances visible, not absorbed into envelope.
5. **FOF perf (P1):** vectorized clustering on np2000 completes in seconds per frame, not minutes.
6. **SDF perf (P2):** accelerated envelope on np2000; profile before attempting 100k.
7. **Scale end-to-end (P4):** 100k–1M direct-dump preprocess + Blender manifest load — **only after Objective 2 produces matching runs**.

---

## Implementation phases

| Phase | Deliverable | Success | Gate |
|-------|-------------|---------|------|
| **P0 — Spike** | `viz_preprocess.py` on np500 CSV; convex-hull envelope; manual Blender load | Envelope deforms over dumps | None — start here |
| **P1 — FOF fragments** | `Code/viz/dem_fof.py` with **vectorized** clustering; multi-envelope + ejecta split; centre-split test | Two envelopes on split run; np2000 FOF in seconds/frame | None |
| **P2 — Surface quality** | Sphere-union SDF with **KD-tree narrow-band** (or splatting); marching cubes | Concave neck visible on np500–2000; profiled cost model for 100k | P1 complete |
| **P3 — Blender automation** | `DEMBulkVizBlender.py` + camera/Earth on np500 `_viz/` manifest | End-to-end render one animation without manual Blender steps | P2 complete |
| **P4 — Scale** | Direct sarracen dump input (**required**); batch preprocess; ejecta cap; 100k–1M validation | Objective 3 success criterion on a real 1M Obj 2 run | **Objective 2 complete**; Daniel/supervisor sign-off on tree-indexed dumps |

**Scheduling note:** P0–P3 can run in parallel with Objective 2 simulation work. Do not schedule P4 until million-grain dumps exist and P2 acceleration is profiled on the largest available run.

---

## Resolved decisions (post-review)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Envelope P0 | Convex hull | Cheap spike on existing data |
| Envelope P2+ | Accelerated sphere-union SDF | Naive grid×grains fails at 10⁶ |
| SDF acceleration | KD-tree narrow band (default) | Only evaluate nearby grains per voxel |
| FOF connectivity | `scipy.sparse.csgraph.connected_components` | Replace Python pair loop in P1 |
| FOF module location | **`Code/viz/dem_fof.py`** (canonical) | Separate git repos; Windows preprocess is primary consumer |
| WSL analysis sync | Import via UNC or documented copy | Avoid `sobol/` as source of truth for viz code |
| Preprocess input P0–P2 | Grains CSV | Parity with `DEMtoCSV.py`; ≤2k scale |
| Preprocess input P4 | **Direct sarracen dump (required)** | CSV at 1M × 100 frames is tens of GB |
| Fragment mass threshold | 5% | Centre-split fidelity |
| Ejecta cap | 50 000 | Viewport/render sanity |

---

## Success criterion (Objective 3)

> A million-particle run renders end-to-end **without manual intervention in Blender** — preprocess batch → open template `.blend` → run `DEMBulkVizBlender.py` → render animation.

**Prerequisite:** an Objective 2 tree-indexed campaign has produced full PHANTOM dumps at ~10⁶ grains. Until then, partial success is P3 on ≤2000-grain data plus P2 cost models extrapolated to 100k.

Centre split and ejecta fidelity are qualitative acceptance tests on known breakup runs, not automated pixel diff.
