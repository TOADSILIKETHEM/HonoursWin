"""One-off upgrade: write a same-stem .npz next to each CSV-era grain CSV.

CSVs are never modified or deleted. Matches the 24-key schema DEMDumpConvert.py
writes (grain_id int64; time_s float64 scalar; everything else float64,
shape (n,)). Old CSVs may predate a column -- that key is NaN-filled and
noted per folder.

Usage:
    python CSVconvert/grains_csv_to_npz.py <grains_dir> [<grains_dir> ...]
    python CSVconvert/grains_csv_to_npz.py --all <root>   # recursive *_grains_output search
    python CSVconvert/grains_csv_to_npz.py --all DEMCSVs --overwrite
    python CSVconvert/grains_csv_to_npz.py --all DEMCSVs --dry-run

--overwrite replaces existing .npz (default: skip a stem that already has one).
--dry-run lists what would be written without writing anything.
"""
import argparse
import os
import sys

import numpy as np
import pandas as pd

# Schema order must match DEMDumpConvert.py's `grains = {...}` dict exactly.
KEYS = [
    "grain_id", "time_s", "x_au", "y_au", "z_au", "x_km", "y_km", "z_km",
    "x_rel_km", "y_rel_km", "z_rel_km", "Reff_km", "h_km",
    "x_vis", "y_vis", "z_vis", "Reff_vis", "m",
    "vx", "vy", "vz", "spinx", "spiny", "spinz",
]
_FLOAT_KEYS = [k for k in KEYS if k not in ("grain_id", "time_s")]

EXCLUDE_DIRNAME = "_npz_check"


def find_grains_dirs(root):
    """Recursively find every '*_grains_output' dir under root, excluding _npz_check."""
    found = []
    for dirpath, dirnames, _filenames in os.walk(root):
        parts = dirpath.replace("\\", "/").split("/")
        if EXCLUDE_DIRNAME in parts:
            dirnames[:] = []  # don't descend into _npz_check at all
            continue
        for d in dirnames:
            if d.endswith("_grains_output"):
                found.append(os.path.join(dirpath, d))
    return sorted(found)


def _bodies_dir_for(grains_dir):
    """Sibling '<run>_bodies_output' next to a '<run>_grains_output' dir, or None."""
    grains_dir = grains_dir.rstrip("/\\")
    if not grains_dir.endswith("_grains_output"):
        return None
    parent = os.path.dirname(grains_dir)
    run = os.path.basename(grains_dir)[: -len("_grains_output")]
    candidate = os.path.join(parent, f"{run}_bodies_output")
    return candidate if os.path.isdir(candidate) else None


def _time_s_from_bodies(bodies_dir, stem):
    """Look up time_s from the same-stem bodies CSV, if it has that column."""
    if bodies_dir is None:
        return np.nan
    path = os.path.join(bodies_dir, stem + ".csv")
    if not os.path.isfile(path):
        return np.nan
    df = pd.read_csv(path, float_precision="round_trip")
    if "time_s" not in df.columns or len(df) == 0:
        return np.nan
    return float(df["time_s"].iloc[0])


def _build_grains_dict(df, stem, bodies_dir, filled):
    """Map a grain CSV DataFrame to the 24-key schema. Records NaN-filled keys into `filled`."""
    n = len(df)
    grains = {}

    if "grain_id" in df.columns:
        grains["grain_id"] = df["grain_id"].to_numpy().astype(np.int64)
    else:
        grains["grain_id"] = np.arange(n, dtype=np.int64)
        filled.add("grain_id")

    if "time_s" in df.columns:
        vals = df["time_s"].to_numpy(dtype=np.float64)
        if n > 0 and not np.all(vals == vals[0]):
            print(f"    WARNING [{stem}]: time_s not constant within frame, using first value")
        time_s = float(vals[0]) if n > 0 else np.nan
    else:
        time_s = _time_s_from_bodies(bodies_dir, stem)
        filled.add("time_s")
    grains["time_s"] = np.float64(time_s)

    for key in _FLOAT_KEYS:
        if key in df.columns:
            grains[key] = df[key].to_numpy().astype(np.float64)
        else:
            grains[key] = np.full(n, np.nan, dtype=np.float64)
            filled.add(key)

    return grains


def _verify(npz_path, expected):
    """Reload the just-written npz and check keys, dtypes, shapes, and exact values."""
    with np.load(npz_path, allow_pickle=False) as d:
        if sorted(d.files) != sorted(KEYS):
            return f"key set mismatch: {sorted(d.files)}"
        for key in KEYS:
            arr = d[key]
            want_dtype = np.int64 if key == "grain_id" else np.float64
            want_shape = () if key == "time_s" else (len(expected["grain_id"]),)
            if arr.dtype != want_dtype:
                return f"{key}: dtype {arr.dtype} != {want_dtype}"
            if arr.shape != want_shape:
                return f"{key}: shape {arr.shape} != {want_shape}"
            if not np.array_equal(arr, expected[key], equal_nan=True):
                return f"{key}: values differ from source"
    return None


def process_folder(grains_dir, overwrite, dry_run):
    """Returns (n_csv, n_written, n_skipped, filled_keys_seen, n_failed)."""
    csvs = sorted(
        f for f in os.listdir(grains_dir) if f.lower().endswith(".csv")
    )
    n_csv = len(csvs)
    if n_csv == 0:
        print(f"{grains_dir}: 0 csv, nothing to do")
        return 0, 0, 0, set(), 0

    bodies_dir = _bodies_dir_for(grains_dir)
    n_written = 0
    n_skipped = 0
    n_failed = 0
    filled_keys_seen = set()

    for csv_name in csvs:
        stem = os.path.splitext(csv_name)[0]
        csv_path = os.path.join(grains_dir, csv_name)
        npz_path = os.path.join(grains_dir, stem + ".npz")

        if os.path.exists(npz_path) and not overwrite:
            n_skipped += 1
            continue

        if dry_run:
            action = "overwrite" if os.path.exists(npz_path) else "write"
            print(f"    [dry-run] would {action} {npz_path}")
            n_written += 1
            continue

        df = pd.read_csv(csv_path, float_precision="round_trip")
        filled = set()
        grains = _build_grains_dict(df, stem, bodies_dir, filled)
        filled_keys_seen |= filled

        # np.savez_compressed appends ".npz" itself if the name doesn't already
        # end with it, so the temp name must end in ".npz" too (not ".npz.tmp").
        tmp_path = os.path.join(grains_dir, stem + ".tmp.npz")
        try:
            np.savez_compressed(tmp_path, **grains)
            os.replace(tmp_path, npz_path)
        except Exception as e:
            print(f"    ERROR [{stem}]: failed to write npz: {e}")
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            n_failed += 1
            continue

        error = _verify(npz_path, grains)
        if error is not None:
            print(f"    ERROR [{stem}]: verification failed: {error}")
            os.remove(npz_path)
            n_failed += 1
            continue

        n_written += 1

    if filled_keys_seen and not dry_run:
        print(f"    filled with NaN: {sorted(filled_keys_seen)}")

    suffix = " (DRY RUN)" if dry_run else ""
    print(f"{grains_dir}: {n_csv} csv, {n_written} npz written, {n_skipped} skipped{suffix}")
    return n_csv, n_written, n_skipped, filled_keys_seen, n_failed


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dirs", nargs="*", help="one or more <run>_grains_output folders")
    parser.add_argument("--all", metavar="ROOT", help="recursively find every *_grains_output under ROOT")
    parser.add_argument("--overwrite", action="store_true", help="replace existing .npz files")
    parser.add_argument("--dry-run", action="store_true", help="list what would be written, write nothing")
    args = parser.parse_args()

    grains_dirs = list(args.dirs)
    if args.all:
        grains_dirs += find_grains_dirs(args.all)
    # de-duplicate, preserve order
    seen = set()
    grains_dirs = [d for d in grains_dirs if not (d in seen or seen.add(d))]

    if not grains_dirs:
        print("No grains_output folders given (pass paths or --all ROOT).")
        sys.exit(1)

    total_failed = 0
    partial_folders = []
    for grains_dir in grains_dirs:
        if not os.path.isdir(grains_dir):
            print(f"{grains_dir}: not a directory, skipping")
            continue
        n_csv, n_written, n_skipped, _filled, n_failed = process_folder(
            grains_dir, args.overwrite, args.dry_run
        )
        total_failed += n_failed
        if not args.dry_run and n_csv > 0:
            n_npz_final = len([f for f in os.listdir(grains_dir) if f.lower().endswith(".npz")])
            if n_npz_final != n_csv:
                partial_folders.append((grains_dir, n_csv, n_npz_final))

    if partial_folders:
        print("\nWARNING: partial npz set (readers will silently load fewer frames):")
        for d, n_csv, n_npz in partial_folders:
            print(f"  {d}: {n_csv} csv but {n_npz} npz")

    if total_failed:
        print(f"\n{total_failed} file(s) failed verification and were removed.")
        sys.exit(1)

    print("\nDone.")


if __name__ == "__main__":
    main()
