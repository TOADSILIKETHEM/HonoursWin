import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import glob
import os

# ── Body index map ─────────────────────────────────────────────────────────────
BODIES = {
    0:  'Sun',
    1:  'Mercury',
    2:  'Venus',
    3:  'Earth',
    4:  'Moon',
    5:  'Mars',
    6:  'Jupiter',
    7:  'Saturn',
    8:  'Uranus',
    9:  'Neptune',
    10: 'Apophis'
}
APOPHIS_IDX = 10
EARTH_IDX   = 3
AU_TO_KM    = 1.496e8   # 1 au in km

# ── Load a full simulation run from a folder of CSVs ──────────────────────────
def load_run(csv_dir, label):
    """
    Load all CSV dumps from a directory into a dict keyed by frame number.
    Returns a list of dicts, one per timestep, with positions and distances.
    """
    files = sorted(glob.glob(os.path.join(csv_dir, "*.csv")))
    records = []

    for frame, f in enumerate(files):
        df = pd.read_csv(f)

        # Positions of key bodies
        apophis = df.iloc[APOPHIS_IDX]
        earth   = df.iloc[EARTH_IDX]
        sun     = df.iloc[0]

        # Earth-Apophis separation in au and km
        dx = apophis['x_au'] - earth['x_au']
        dy = apophis['y_au'] - earth['y_au']
        dz = apophis['z_au'] - earth['z_au']
        earth_apophis_dist_au = np.sqrt(dx**2 + dy**2 + dz**2)
        earth_apophis_dist_km = earth_apophis_dist_au * AU_TO_KM

        # Apophis distance from Sun
        sx = apophis['x_au'] - sun['x_au']
        sy = apophis['y_au'] - sun['y_au']
        sz = apophis['z_au'] - sun['z_au']
        sun_apophis_dist_au = np.sqrt(sx**2 + sy**2 + sz**2)

        records.append({
            'run':                    label,
            'frame':                  frame,
            'apophis_x':              apophis['x_au'],
            'apophis_y':              apophis['y_au'],
            'apophis_z':              apophis['z_au'],
            'earth_x':                earth['x_au'],
            'earth_y':                earth['y_au'],
            'earth_z':                earth['z_au'],
            'earth_apophis_dist_au':  earth_apophis_dist_au,
            'earth_apophis_dist_km':  earth_apophis_dist_km,
            'sun_apophis_dist_au':    sun_apophis_dist_au,
        })

    return pd.DataFrame(records)


# ── Compute derived metrics for one run ───────────────────────────────────────
def compute_metrics(run_df):
    """
    From a run dataframe, compute key scalar metrics for comparison.
    """
    min_idx  = run_df['earth_apophis_dist_au'].idxmin()
    closest  = run_df.loc[min_idx]

    # Approximate velocity from finite differences between frames
    # (only meaningful if dumps are evenly spaced in time)
    if len(run_df) > 1:
        dx = run_df['apophis_x'].diff()
        dy = run_df['apophis_y'].diff()
        dz = run_df['apophis_z'].diff()
        run_df['apophis_speed_au_per_step'] = np.sqrt(dx**2 + dy**2 + dz**2)
        speed_at_closest = run_df.loc[min_idx, 'apophis_speed_au_per_step']
    else:
        speed_at_closest = np.nan

    return {
        'run':                       run_df['run'].iloc[0],
        'closest_approach_au':       closest['earth_apophis_dist_au'],
        'closest_approach_km':       closest['earth_apophis_dist_km'],
        'closest_approach_frame':    int(closest['frame']),
        'speed_at_closest_au_step':  speed_at_closest,
        'mean_sun_dist_au':          run_df['sun_apophis_dist_au'].mean(),
        'min_sun_dist_au':           run_df['sun_apophis_dist_au'].min(),
        'max_sun_dist_au':           run_df['sun_apophis_dist_au'].max(),
    }


# ── Load multiple runs ─────────────────────────────────────────────────────────
# Edit these paths and labels to match your actual simulation directories
runs = {
    'baseline':     '/path/to/run_baseline/csv/',
    'high_density': '/path/to/run_high_density/csv/',
    'low_density':  '/path/to/run_low_density/csv/',
}

all_data    = []
all_metrics = []

for label, csv_dir in runs.items():
    df = load_run(csv_dir, label)
    all_data.append(df)
    all_metrics.append(compute_metrics(df))
    print(f"[{label}] loaded {len(df)} frames")

combined = pd.concat(all_data, ignore_index=True)
metrics  = pd.DataFrame(all_metrics)

print("\n── Summary Metrics ──────────────────────────────")
print(metrics.to_string(index=False))


# ── Plot 1: Apophis trajectory (x-y plane) ─────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 8))
for label, group in combined.groupby('run'):
    ax.plot(group['apophis_x'], group['apophis_y'], label=label, lw=2)

# Plot Earth orbit for reference
earth_ref = combined[combined['run'] == list(runs.keys())[0]]
ax.plot(earth_ref['earth_x'], earth_ref['earth_y'],
        'b--', alpha=0.4, label='Earth orbit')

ax.scatter([0], [0], c='yellow', s=200, zorder=5, label='Sun')
ax.set_xlabel('x (au)')
ax.set_ylabel('y (au)')
ax.set_title('Apophis Trajectory — Run Comparison')
ax.legend()
ax.set_aspect('equal')
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig('trajectory_comparison.png', dpi=150)
plt.show()


# ── Plot 2: Earth-Apophis distance over time ────────────────────────────────
fig, ax = plt.subplots(figsize=(10, 5))
for label, group in combined.groupby('run'):
    ax.plot(group['frame'], group['earth_apophis_dist_au'], label=label, lw=2)

ax.axhline(y=0.00257, color='r', linestyle=':', label='Moon distance (~0.00257 au)')
ax.set_xlabel('Dump frame')
ax.set_ylabel('Earth–Apophis distance (au)')
ax.set_title('Earth–Apophis Separation Over Time')
ax.legend()
ax.grid(True, alpha=0.3)
plt.tight_layout()
plt.savefig('distance_comparison.png', dpi=150)
plt.show()


# ── Plot 3: Closest approach bar chart ─────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 4))
ax.bar(metrics['run'], metrics['closest_approach_km'] / 1000,
       color='steelblue', edgecolor='black')
ax.set_ylabel('Closest approach (1000s of km)')
ax.set_title('Closest Earth–Apophis Approach by Run')
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
plt.savefig('closest_approach_comparison.png', dpi=150)
plt.show()