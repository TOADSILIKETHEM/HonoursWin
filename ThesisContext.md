# Thesis Context: Apophis 2029 Flyby Modelling
## SCI4502 Honours — Maxwell Boyle & Mia Eng, Monash University
### Supervisors: Daniel Price, Andy Tomkins, Rachel Kirby

> **Agent ops:** use `CLAUDE.md` and `docs/BATCHES_VIZ.md` — not this file.
> **Campaign/metrics truth:** WSL `docs/BATCHES.md`. **S2 scope:** WSL `ThesisStuff/SCI4502_SCOPE_CONTEXT.md`.

This document consolidates scientific and research context for thesis writing. It is not a code reference.

---

## 1. Core Research Question

**How do spin rate and cohesion shift the effective tidal disruption boundary for a rubble-pile asteroid during the 2029 Apophis Earth flyby?**

The classical Roche limit assumes a non-rotating, cohesionless body. Apophis is neither. A fast-spinning rubble pile is already under centrifugal tensile stress before the encounter — Earth's tidal field only needs to supply marginal additional stress to destabilise a body already near its spin-modified limit. Cohesion acts as an internal binding force that shifts the boundary inward. The thesis maps where this modified boundary lies, and what Earth's tidal contribution is relative to spin-induced instability.

**Disruption condition (conceptual):**
```
Tidal stress + Centrifugal stress  >  Self-gravity + Cohesion
```

At ~38,000 km flyby distance, tidal stress is weak relative to near-Roche encounters. Whether it matters depends on whether the body is already near its spin-modified stability threshold.

**Research gap:** Most existing disruption studies (Hirabayashi & Kim 2021; DeMartini et al.) treat Apophis either as a homogeneous fluid or use pkdgrav DEM without a coupled SPH phase. This thesis uses PHANTOM's in-tree DEM module (developed and extended by the student with supervisor Daniel) to model a discrete rubble pile within the same N-body solar system framework used for the flyby trajectory, giving a self-consistent treatment of tidal + spin dynamics.

---

## 2. Apophis Physical Properties

| Property | Value | Notes |
|----------|-------|-------|
| Shape | Bilobed | `apophis_v233s7.obj`, long axis ~410 m |
| Effective radius | 0.17 km (Horizons ephemeris) | Used for gravity; separate from shape file |
| Bulk density target | ~1300 kg/m³ | Literature Apophis estimate |
| Real spin period | ~30 hr | Used as baseline; well below any disruption threshold |
| Grain count (DEM model) | ~500 grains | `np_apophis=500`; `np_apophis=64` used in early tests |
| Particle diameter (500 grains, bilobed) | ~46 m | Order-of-magnitude; packing-dependent |

**Shape file:** `Shapes/apophis.shape` references `apophis_v233s7.obj` (0.205 km mesh scale). `scale_r_apophis ≈ 1.205` is required to match the lattice cube to the mesh long axis when using the OBJ crop.

---

## 3. Flyby Geometry

| Parameter | Value |
|-----------|-------|
| Closest approach distance | ~37,998–38,000 km (simulations) |
| Closest approach epoch | ~day 3.9 of a 4.5-day simulation window |
| Flyby date | April 2029 |
| Simulation `tmax` | 4.5 days for flyby runs; 12 hr for spin-only runs |
| Ephemeris | JPL Horizons; pre-cached `.txt` files in `sobol/` |

The ~38,000 km closest approach is ~2.5× the classical Roche limit for a cohesionless body. The encounter is not expected to produce classical disruption at the real 30 hr spin. Tidal effects are measurable as geometric spreading and spin change.

---

## 4. Simulation Models

### Model A — Point Mass (baseline)
- Apophis treated as a single sink particle.
- No internal structure, no disruption physics.
- Used to verify flyby trajectory and closest-approach distance.
- Pipelines done; Blender animation available.

### Model B — DEM Rubble Pile (primary model)
- Apophis represented as ~500 equal-mass sink particles interacting via PHANTOM's in-tree DEM module.
- Contact spring stiffness `kc` (dyne/cm) controls grain-grain cohesion.
- Shape either a sphere lattice (fast) or cropped to literature bilobed OBJ mesh.
- Spin initialised with `apply_apophis_spin` in `setup_solarsystem.f90`.
- Spin axis set via ecliptic obliquity/azimuth or torque-alignment relative to the Earth–Apophis orbital plane.
- Full solar-system N-body context: all 10 planetary bodies present unless `apophis_only=T`.
- Status: working and producing results. Several completed campaigns (see Section 6).

### Model C — Combined DEM+SPH (planned)
- SPH fluid phase (fine-grained matrix) + DEM boulders in the same PHANTOM run.
- Intended to capture the grain matrix + discrete boulder structure of a real rubble pile.
- Not yet implemented; this is the planned final model.

---

## 5. Disruption Physics Framework

### Spin-Modified Roche Limit
Classical Roche limit: `d_Roche = r × (2 M_Earth / M_Apophis)^(1/3)`. Assumes no spin. Fast spin adds centrifugal tensile stress — the body effectively "feels" more disrupted before the encounter begins. The effective disruption boundary moves outward (disruption at larger distances) with increasing spin rate.

### Cohesion
Grain-grain cohesion provides internal tensile strength that resists disruption. Higher `kc` → higher bulk cohesive strength → disruption boundary moves inward. At the real flyby distance (~38,000 km) with realistic 30 hr spin, cohesion is irrelevant because spin stability is already guaranteed (see `flyby_kc_v3` null result below).

### kc (PHANTOM contact spring stiffness) → Bulk Cohesive Strength

`kc` is the contact spring stiffness in dyne/cm patched into PHANTOM `.in` files. Bulk cohesive strength scales approximately as:

**σ_c ≈ kc / d_particle**

With `np_apophis=500` on the bilobed shape, d_particle ≈ 46 m ≈ 4600 cm. Conversion is order-of-magnitude only (depends on packing and the DEM contact model in `dem.f90`).

| kc (dyne/cm) | ~Bulk σ_c | Physical interpretation |
|--------------|-----------|------------------------|
| 0 | 0 Pa | Cohesionless rubble pile |
| 3.5×10⁶ | ~8 Pa | Weak regolith-scale cohesion |
| ~10⁷ | ~22 Pa | Typical small rubble-pile estimate |
| ~10⁸ | ~220 Pa | Strong; above most published upper bounds |

**Literature anchor (Sánchez & Scheeres 2014):** bulk cohesion for small rubble piles from van der Waals regolith forces is ~25–200 Pa. The kc sweep brackets this range in bulk terms.

### Disruption Metrics

**`size_ratio`** — peak-over-run radius of gyration of the DEM grains ÷ initial value.
- ~1.0: intact
- 1.1–1.3: geometric spreading / tidal deformation
- >>1: breakup / mass ejection in progress

**`unbound_fraction`** — peak fraction of grains with positive specific energy in the CoM frame.
- 0: all grains gravitationally bound (may still be deformed)
- >0: mass loss / true disruption

**Critical thesis distinction:** `unbound_fraction = 0` does not mean nothing happened. In the `flyby_spin_earth` campaign, `size_ratio` reaches 1.24 at the fastest tested spin (2.07 hr) while `unbound_fraction = 0` throughout — the body deforms and spreads tidally but no mass escapes. Thesis wording must distinguish **geometric spreading** from **unbound disruption**.

### Spin Period Metrics

**`settled_spin_period_hr`** — mean spin period of bound grains before the encounter. Detects the "settled" pre-flyby spin state after DEM rearrangement.

**`post_flyby_spin_period_hr`** — mean spin period of bound grains after closest approach. The difference `post_flyby − settled` isolates tidal spin-up/down.

**Important physical effect:** Even with no tides, DEM rearrangement shortens the spin period over time — internal mass redistribution lowers the moment of inertia while angular momentum is conserved, increasing ω. A multi-percent difference between `settled_spin_period_hr` and the input `apophis_spin_period` reflects simulation physics (grain settling), not a code bug.

---

## 6. Completed Simulation Campaigns

All batches are under `Honours/sobol_mass_runs/` in WSL.

### `sobol_20260530_155434_spin_kc0_12hr`
- **Setup:** No Earth (`apophis_only=T`), spin swept 0.66–5 hr, kc=0, 12 hr `tmax`.
- **Purpose:** Establish the intrinsic spin disruption threshold without Earth.
- **Result:** Catastrophic threshold ~2 hr spin period.
- **Caveat:** 12 hr `tmax` does not match the 4.5-day flyby runs — Priority 2 will provide the matched-`tmax` control.

### `sobol_20260530_spin_kc1e7_12hr`
- **Setup:** Same as above but kc~10⁷ dyne/cm.
- **Purpose:** Test whether cohesion shifts the intrinsic threshold.
- **Result:** Slight shift vs kc=0; cohesion provides modest additional stability.

### `sobol_20260531_153147_flyby_kc_v3`
- **Setup:** Earth present, spin fixed at real ~30 hr, kc ∈ [0, 10⁸], 16 Sobol runs.
- **Purpose:** Test whether cohesion matters at the real flyby geometry.
- **Result:** CA ≈ 37,998 km, disp ≈ 1.025, unbound = 0 for all runs. **S_kc ≈ 0.**
- **Thesis interpretation:** At 30 hr spin, Apophis is ~15× below the spin-modified threshold. Cohesion has no effect on an outcome that is already guaranteed by spin stability. This is a **valid null result**: cohesion is irrelevant at real Apophis spin during the flyby.

### `sobol_20260531_172510_flyby_spin_earth`
- **Setup:** Earth present, kc=0, spin swept 2–4 hr (Sobol), 16 runs, `np_apophis=500`.
- **Purpose:** Map how tidal + spin effects combine at elevated spin rates.
- **Result:** Size ratio rises below ~2.5–2.6 hr spin (peak size ratio=1.24 at 2.07 hr). CA flat across all runs. Unbound fraction = 0 throughout.
- **Spin range justification:** Spins 2–4 hr sit above the ~2 hr no-Earth catastrophic threshold. Spins below ~2 hr were excluded because they disrupt independently and would confound Earth-attribution.
- **Thesis note:** This shows **tidal deformation** (not disruption) increases near the spin-modified boundary. The Earth-attribution claim requires Priority 2 (same spins, no Earth, matched `tmax`) to confirm what is tidal vs what is spin-only.

### `sobol_20260601_140230_flyby_spin_torque_align_k1e7`
- **Setup:** Earth present, kc=10⁷, spin period fixed 1.52 hr, 24 runs. Single swept dimension: `apophis_spin_torque_align_deg` ∈ [0°, 180°].
- **Purpose:** Test dependence of outcome on spin axis orientation relative to the encounter geometry.
- **Spin axis convention:** The angle is measured from +ĥ, where ĥ = unit(r × v) is the Earth–Apophis relative orbital angular momentum. 0° = spin aligned with orbital sense; 180° = opposite.
- **Result:** Strong orientation dependence. Near 180° ("opposite") → breakup. Near 0° ("aligned") → mostly intact. Sphere lattice geometry.
- **Documentation:** `sobol/campaigns/flyby_spin_torque_align_k1e7.md`

### `sobol_20260601_151818_torque_align_blender_vis`
- **Setup:** Two re-runs from above batch: run 4 (~11.2°, near aligned, intact) and run 19 (~177.5°, near opposite, breakup). Sphere lattice, dumps retained for Blender.
- **Purpose:** Visualisation of the two end-member outcomes.

### `sobol_20260601_171137_torque_align_blender_vis_obj`
- **Setup:** Same two cases with literature OBJ bilobed mesh (~501 grains, `scale_r_apophis≈1.205`).
- **Results:**
  - run_0001 (~11.2°, aligned): disp≈1.28, unbound≈0.02 — mostly intact.
  - run_0002 (~177.5°, opposite): disp≈54, unbound≈0.93 — catastrophic breakup.
- **Converted data location:** `Code/DEMCSVs/torque_align_obj/` (Windows side; bodies CSV, grains npz).
- **Documentation:** `sobol/campaigns/torque_align_blender_vis_obj.md`

### `sobol_20260601_204015_torque_align_obj_breakup_fine_dt`
- **Setup:** OBJ breakup case only (run_0002, ~177.5°), finer dump cadence (5 min vs 30 min) for high-frame-rate Blender animation.
- **Converted data location:** `Code/DEMCSVs/torque_align_obj_fine_dt/` (Windows side; bodies CSV, grains npz).

### `sobol_20260604_170327_spin_detect_apo_only_30hr`
- **Setup:** Short `apophis_only` DEM, 30 hr spin. Validation run only.
- **Purpose:** Verify that `settled_spin_period_hr` detection matches setup input to ~0.1% on early dumps.

---

## 7. Planned Campaigns

### Priority 2 — No-Earth Control (matched `tmax`)
- **Setup:** No Earth (`apophis_only=T`), same spin range as `flyby_spin_earth` (2–4 hr), kc=0, **4.5-day `tmax`** (matching flyby batch).
- **Purpose:** Provide the Earth-absent control at matched simulation time. The difference between `flyby_spin_earth` and Priority 2 curves isolates the **tidal contribution to the disruption boundary**.
- **Planned thesis figure:** `size_ratio` vs `apophis_spin_period` with two curves: Earth present vs Earth absent. The horizontal offset between the curves is Earth's tidal effect.

### Priority 3 — 2D Spin × kc Map
- **Setup:** Earth present, spin ~1–3 hr, kc varies.
- **Purpose:** Map the 2D parameter space near the Earth-modified disruption boundary. Quantify how cohesion shifts the tidal boundary at fast spin.
- **Depends on:** Priority 2 first locating where the boundary is.

### Model C — Combined DEM+SPH
- Fine-grained SPH matrix + DEM boulders in a single PHANTOM run.
- No timeline yet; subject to module development.

---

## 8. Sensitivity Analysis

**Method:** Sobol variance decomposition with Saltelli sampling (SALib library). First-order (S1) and total-order (ST) indices per parameter. Second-order indices available but not primary focus.

**Swept dimensions (examples from past batches):**
- `apophis_spin_period` (hr)
- `kc_cgs` (dyne/cm, contact spring stiffness)
- `apophis_spin_torque_align_deg` (spin axis angle)
- `scale_rho` / mass-related parameters (earlier point-mass sweeps)

**Response variables of interest:**
- `closest_approach_km` / `closest_approach_au` — orbital metric
- `size_ratio` — structural integrity
- `unbound_fraction` — true mass-loss disruption
- `settled_spin_period_hr` / `post_flyby_spin_period_hr` — tidal spin change

**Status:** Infrastructure fully working. Thesis-quality Saltelli sweeps not yet designed or run; these will be the Priority 2/3 campaigns once the parameter space is better understood from completed exploratory batches.

---

## 9. Spin Axis Geometry

The torque-align parameter `apophis_spin_torque_align_deg` orients the spin axis relative to the encounter geometry:

- **ĥ** = unit(**r** × **v**) = Earth–Apophis orbital angular momentum direction at setup epoch
- **0° (aligned):** spin axis parallel to +ĥ — rotating "with" the encounter orbit
- **180° (opposite):** spin axis antiparallel to ĥ — rotating against the encounter orbit
- Intermediate angles are set by Rodrigues rotation of ĥ about the Earth–Apophis separation vector r̂

The torque-align campaign established a strong orientation dependence: the "opposite" configuration is dramatically more susceptible to tidal breakup than the "aligned" configuration at the same spin rate, kc, and flyby geometry. This is physically interpretable — the torque from the tidal field acts oppositely relative to the spin angular momentum depending on orientation.

**Real Apophis spin orientation:** The real Apophis spin axis is defined by ecliptic obliquity/azimuth (separate from the torque-align convention). The torque-align sweeps are a systematic exploration of orientation sensitivity, not a replication of the real spin axis.

---

## 10. Visualisation Assets

| Asset | Location (Windows) | Description |
|-------|---------------------|-------------|
| Torque-align aligned case (sphere) | `DEMCSVs/run_0001_*` | Intact, ~11.2°, sphere lattice |
| Torque-align breakup case (sphere) | `DEMCSVs/run_0002_*` | Breakup, ~177.5°, sphere lattice |
| Torque-align aligned (OBJ bilobed) | `DEMCSVs/torque_align_obj/run_0001_*` | Intact, bilobed shape |
| Torque-align breakup (OBJ bilobed) | `DEMCSVs/torque_align_obj/run_0002_*` | Breakup, bilobed shape |
| Breakup fine-dt (OBJ bilobed) | `DEMCSVs/torque_align_obj_fine_dt/run_0001_*` | Breakup at 5 min cadence |
| Point-mass flyby | `csv_output/`, `ShortCSVlist/` | Full solar system, 11 bodies |

**Blender scripts for rendering:**
- `DEMGrainsBlenderEarth.py` — DEM grains + Earth mesh, no camera
- `DEMGrainsBlenderEarthCam.py` — same with integrated camera
- `DEMCamera.py` — standalone camera for DEM scenes
- `OnlyEarth_ApophisTrueSize.py` — point-mass full pipeline
- `MaterialandSubsivision.py` — post-import: applies shared modifiers/materials to grain particles

**Render engine:** Cycles (not EEVEE). All volumetric and lighting work is Cycles-specific.

---

## 11. Key Interpretive Notes for Thesis Writing

**On the `flyby_kc_v3` null result:**
S_kc ≈ 0 is not a failure. At real 30 hr spin, the body is ~15× slower than the ~2 hr spin disruption threshold. Cohesion cannot matter for an outcome that spin stability already guarantees. The null result is physically meaningful: it confirms that at real Apophis conditions, cohesion is not the relevant parameter — spin is.

**On `unbound_fraction = 0` in `flyby_spin_earth`:**
The body deforms and spreads (size_ratio up to 1.24) without any mass escaping. This is tidal distortion of a bound body, not disruption. Thesis wording: "tidal deformation" or "geometric spreading", not "disruption" or "breakup" for this campaign.

**On the torque-align breakup (OBJ case):**
run_0002 (opposite spin, 177.5°) reaches disp≈54 and unbound≈0.93 — near-total disruption. This is the most dramatic result in the dataset and is suitable for a thesis figure / animation showing grain dispersal.

**On spin rearrangement vs tidal spin change:**
DEM grain rearrangement shortens the spin period even with no external tides (L conserved, I decreases as grains settle). When comparing `settled_spin_period_hr` to the input spin or to `post_flyby_spin_period_hr`, attribute multi-percent differences in the pre-flyby period to settling physics, not a simulation artefact. True tidal spin change is `post_flyby − settled`.

**On the bilobed neck:**
The neck region of the bilobed shape may concentrate tidal stress. This has not yet been isolated in a dedicated sweep — it is flagged as potential future work or a discussion point about where disruption initiates.

**On model limitations:**
- PHANTOM has no native solid-body mechanics. The DEM module adds contact-spring grain interactions but does not include fracture, plastic yield, or deviatoric stress in the continuum sense. This is appropriate for a rubble pile (discrete contacts) but should be noted as a limitation vs FEM approaches (e.g. Hirabayashi & Kim 2021).
- Sphere-lattice runs use uniform grain sizes. The OBJ-mesh runs use the literature bilobed shape but still equal-mass grains. Neither captures grain size distribution.
- The ~500-grain resolution is a computational compromise; higher resolution would better resolve the neck and surface layers.

---

## 12. Literature References

- **Hirabayashi & Kim (2021)** — FEM stress modelling of Apophis under tidal loading. Key comparison for continuum vs discrete methods.
- **DeMartini et al.** — tidal resurfacing of rubble-pile asteroids using DEM/pkdgrav. Close predecessor to this work.
- **Sánchez & Scheeres (2014)** — van der Waals regolith cohesion for small rubble piles; bulk cohesion ~25–200 Pa. Anchor for the kc sweep range.
- **Raducan et al.** — DART mission material model context.
- **Thomas & Cheng et al.** — DART mission outcomes and lessons.
- **Luther et al.** — SPH/DEM impact models in the DART context.
- **Stickle et al.** — homogeneous continuum limitations; meteorite analogue bias.
- **OSIRIS-APEX mission** — NASA mission to characterise Apophis in situ after the 2029 flyby. This thesis produces predictions that OSIRIS-APEX will eventually test.

**Core research gap (thesis framing):** Existing material models are calibrated to high-velocity impact conditions (DART, meteorite impacts). Tidal loading during a slow, sub-Roche flyby is a fundamentally different stress regime. The mismatch between impact-validated parameters and tidal loading conditions motivates this work.

---

## 13. Thesis Status

| Component | Status |
|-----------|--------|
| Point-mass simulation | Done |
| DEM rubble-pile simulation | Done (several campaigns) |
| Combined DEM+SPH simulation | Planned (module development ongoing) |
| Priority 2 — no-Earth control runs | Not yet run |
| Priority 3 — 2D spin×kc map | Not yet run |
| Thesis-quality Saltelli sensitivity sweeps | Not yet designed/run |
| Visualisation pipeline (Blender) | Mainly complete |
| Data analysis / plotting | Infrastructure done |
| Literature review | Draft in progress |
| Thesis writing | Not started |

---

## 14. Simulation Parameter Ranges (Reference)

| Parameter | Sweep range | Fixed value (if not swept) |
|-----------|-------------|---------------------------|
| `apophis_spin_period` (hr) | 0.66–5 (spin runs); 2–4 (flyby) | 30 hr (real Apophis); 1.52 hr (torque-align) |
| `kc_cgs` (dyne/cm) | 0–10⁸ | 0 (cohesionless); 10⁷ (typical) |
| `apophis_spin_torque_align_deg` | 0–180° | — |
| `np_apophis` | 64, 500 (tested) | 500 (thesis runs) |
| `tmax` | — | 12 hr (spin-only); 4.5 day (flyby) |
| Earth present | — | `apophis_only=T` for spin-only |
| Shape | Sphere lattice / OBJ bilobed | — |

---

## 15. Cross-System Workflow Summary

```
WSL (simulation):
  PHANTOM (SETUP=solarsystem) + DEM module
    ↓  binary dumps in sobol_mass_runs/<batch>/run_XXXX/
  run_demtocsv_batch.py
    ↓  bodies CSVs + grain .npz written to /mnt/c/.../Code/DEMCSVs/<label>/

Windows (post-processing):
  DEMGrainsBlenderEarth(Cam).py  →  Blender animation
  MaterialandSubsivision.py      →  shared materials on grains
  Data analysis/FirstData.py     →  plots from sobol_mass_outputs.csv
  sobol/Analysis/Analysis.py     →  Sobol/Saltelli indices
```
