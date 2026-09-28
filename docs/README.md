# Code — detail docs

| File | Role |
|------|------|
| `AGENT_CONTEXT.md` | Pointer to `../../docs/AGENT_CONTEXT.md` |
| `../../docs/SHARED_FACTS.md` | Shared facts. |
| `CONTEXT_CHANGELOG.md` | Pointer to WSL dated notes |
| `BATCHES_VIZ.md` | Canonical Blender datasets under `DEMCSVs/` (incl. first real TUI run); per-sphere and bulk composite workflows. Path table: WSL `SHARED_FACTS.md` |
| `P0_INSTANCING_SPIKE.md` | **Generated into OneDrive `docs/`** (gitignored here) — measured GN-instancing cost curve at 10³–10⁶ grains + reference renders. Objective 3 Option A go/no-go. Regenerate via `BlenderConvert/P0_InstancingSpike.py`; do not hand-edit |
| `p0_instancing_results.json` | **Generated**, stays in OneDrive `docs/` — raw spike measurements, one row per `(N, subdiv, device)` |
| `p0_renders/` | **Generated** (OneDrive `docs/`, not in git) — reference PNGs embedded into `P0_INSTANCING_SPIKE.md` |
| `superpowers/specs/` | Archive — Objective 3 design specs (composite vs Option A). Decided since: D3 = composite, instancing extra (`SHARED_FACTS.md`). Do not cite unless named |
| `AUDIT_2026-09-07.md` | Dated snapshot — pre-sync stale-term audit (resolved) |
| `BLENDER_PIPELINE_DIAGRAM.md` / `.png` | Dated snapshot 2026-09-11 — viz data-flow diagram; partly stale (see its banner) |
| `OPTION_A_PIPELINE_CODE_REVIEW.md` | Dated snapshot 2026-09-11 — review of `spike/option-a-gn-instancing-p0` |
| `../CLAUDE.md` | Hub: code vs data, confirm rules, script index |
| `PIPELINE_REFERENCE.md` | Pipeline diagrams, bodies CSV / grains npz schemas, code units, DEM notes, body models |
| `BLENDER_OPS.md` | Commands + how-to: convert, bulk composite, instancing, synthetic flyby, slow-mo/video, P0 spike, per-script detail |

Simulation campaign catalogue (all metrics): `../../docs/BATCHES.md`
