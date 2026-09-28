# Option A Blender Viz Pipeline — Code Review

**Date:** 2026-09-11  
**Branch:** `spike/option-a-gn-instancing-p0`  
**Base commit:** `c6783bb` ("Add layered-composite bulk viz path")  
**Reviewer:** automated review (post-implementation)

**TLDR:** The Option A instancing pipeline matches the plan and the shared cinematic extraction is solid, but do not merge yet — `DEMBulkInstanceBlender.py` imports untracked `P0_InstancingSpike.py`, important unstaged `viz/` fixes are outside the staged commit, and there are portability/DRY gaps to close first.

---

## Scope reviewed

| Area | Files |
|------|-------|
| **Staged** | `DEMBulkInstanceBlender.py`, `DEMBulkVizBlender.py`, `DEMCinematicSetup.py`, `shape_sampling.py`, `viz_preprocess_lite.py` |
| **Unstaged** | `viz/dem_fof.py`, `viz/envelope.py`, `viz/viz_preprocess.py` |
| **Untracked** | `P0_InstancingSpike.py` (production dependency), `_inspect_sinks.py` (debug — skipped) |

Base: `c6783bb` → working tree (~895 lines changed across 8 tracked files).

---

## Strengths

**Plan alignment is strong.** All six requirements from `CLAUDE.md` are delivered:

- **Composite path** preserved; `DEMBulkVizBlender.py` refactored without changing its manifest contract (`viz_mode: "composite"`).
- **Option A path** wired end-to-end: `viz_preprocess_lite.py` → `points.npz` + instance manifest → `DEMBulkInstanceBlender.py` with GN Instance on Points.
- **`static: false` guard** is explicit and correct (`DEMBulkInstanceBlender.py:173-177`).
- **Shared cinematic** cleanly extracted to `DEMCinematicSetup.py` with `frame_handler_suspended()` — a real bug fix for keyframing loops that call `scene.frame_set()`.
- **P0 spike** is thorough: Cycles GPU device set explicitly, scratch-scene isolation, incremental JSON results, and documented go/no-go outcome.

**Composite-path hardening (unstaged but valuable):**

- Envelope topology fix: remapping `hull.simplices` through `hull.vertices` — without this, Blender gets out-of-range face indices.
- Envelope frame-update fix: BLAKE2b topology key so same vertex/face *counts* no longer reuse stale topology across frames.
- `dem_fof.py` vectorisation (`query_pairs` ndarray, parallel `k=2` query).
- `viz_preprocess.py`: per-fragment envelope try/except, Efraimidis–Spirakis ejecta subsampling, cross-drive-safe `_manifest_path()`.

**Instance-path design choices are sound:**

- Volume-conserving `grain_radius_for()` anchored on the reference run's `ref_n` / `Reff_vis`.
- Per-instance random rotation wired into GN (anti-tiling requirement).
- `_cleanup_previous()` for idempotent re-runs.
- Material lookup fails loudly instead of auto-appending the wrong rock material.

---

## Issues

### Critical (must fix before merge)

1. **Production imports untracked benchmark module**
   - `DEMBulkInstanceBlender.py:23` — `import P0_InstancingSpike as p0`
   - `P0_InstancingSpike.py` is **untracked** (`??`). Any clone/checkout without that file breaks Option A entirely. A benchmark module is not a stable production API.
   - **Fix:** Stage and commit `P0_InstancingSpike.py`, or extract `build_geometry_nodes` / `_make_icosphere` into a shared module (e.g. `BlenderConvert/gn_instancing.py`) that both P0 and production import.

2. **Envelope hull face indices (unstaged)**
   - `viz/envelope.py:59-64` — convex hull used `hull.simplices` against compacted `hull.vertices` without remapping.
   - Produces invalid face indices; Blender may render garbage or silently repair geometry.
   - **Fix:** Include unstaged `envelope.py` in the merge commit — this is a correctness fix, not optional polish.

3. **Topology reuse may skip vertex updates (staged composite)**
   - `DEMBulkVizBlender.py:201-212` — topology keyed on face bytes + vertex count only.
   - Acceptable for hull P0; if vertex positions change with identical topology (possible for SDF), coordinates won't update.
   - **Fix:** Document limitation, or also hash vertex positions if SDF envelopes go to production.

### Important (should fix)

| Issue | Location | Fix |
|-------|----------|-----|
| Hard-coded absolute `BLENDER_CONVERT_DIR` | Both bulk scripts `:16-20` | Derive from `Path(__file__).resolve().parent` |
| Asymmetric `viz_mode` handling | Composite warns (`:55-56`); instance raises | Make both raise `ValueError` |
| Two GN tree implementations | Composite inline ico vs Option A `Object Info` | Extract shared builder when touching GN again |
| No cross-drive fallback in lite preprocess | `viz_preprocess_lite.py:120` | Reuse `_manifest_path()` from `viz_preprocess.py` |
| Staged/unstaged split | `dem_fof.py`, `envelope.py`, `viz_preprocess.py` unstaged | Stage and commit together with Option A work |
| Slow BVH sampling loop | `shape_sampling.py` — pure Python per-point | Acceptable for one-time preprocess; add progress reporting |

### Minor

- `P0_InstanceOnPoints` orphan datablocks on interrupted runs — purge in `_cleanup_previous()`.
- Instance uses `if __name__ == '__main__'`; composite calls `main()` unconditionally — align pattern.
- Instance sets `scene.render.engine = 'CYCLES'`; composite does not — set in both or document.
- `viz_preprocess_lite.py` — no early check that `shape_obj` exists.

---

## Recommendations (streamlining)

1. **Single commit scope** — Stage `P0_InstancingSpike.py` plus unstaged `viz/dem_fof.py`, `viz/envelope.py`, `viz/viz_preprocess.py`. The envelope fixes are regression-prevention for composite, not unrelated churn.

2. **Extract GN builder** — Move `build_geometry_nodes`, `_make_icosphere`, `RADIUS_ATTR` out of `P0_InstancingSpike.py` into `BlenderConvert/gn_instancing.py`. Keeps the benchmark measuring the same code production runs.

3. **Portable `sys.path`** — Replace hard-coded paths with `Path(__file__).resolve().parent` in both bulk Blender scripts.

4. **Share `_manifest_path()`** — One helper used by both preprocess scripts.

5. **Strict `viz_mode` in composite** — Change the warning at `DEMBulkVizBlender.py:55-56` to `raise ValueError` mirroring the instance importer.

---

## Assessment

**Ready to merge? No — merge with fixes.**

**Reasoning:** Functionally the Option A architecture matches the spec and the shared cinematic extraction is clean. The P0 gate is credibly implemented. However:

- The production path **depends on an untracked file** — that alone blocks merge.
- Important **composite-path correctness fixes** sit unstaged outside the staged commit.
- **Hard-coded paths** and **production→benchmark import coupling** will cause friction on the next machine or refactor.

**After:** (1) track `P0_InstancingSpike.py` or extract shared GN module, (2) include unstaged `viz/` fixes, (3) fix `sys.path` portability and `viz_preprocess_lite` cross-drive manifest paths — then this is **ready to merge**.
