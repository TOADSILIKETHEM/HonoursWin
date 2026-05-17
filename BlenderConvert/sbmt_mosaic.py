#!/usr/bin/env python3
"""
sbmt_mosaic.py
==============
Route B: build a seamless equirectangular surface texture for Phobos or Deimos
from a folder of SBMT "Generate Backplanes" exports.

WHAT THIS DOES
--------------
SBMT's per-facet albedo CSV is only a low-frequency scalar. This script instead
mosaics the *real spacecraft imagery* SBMT holds. For every image you export
from SBMT with backplanes, each pixel carries its own surface latitude/longitude
and its incidence/emission/phase angles. This script:

  1. Reads each backplane cube (FITS cube, multi-extension FITS, or ENVI BSQ/BIP/BIL).
  2. Photometrically normalises every image to a common geometry using a
     Lommel-Seeliger disk function (standard for airless regolith bodies),
     so images taken under different illumination blend without patchwork.
  3. Scatters every valid pixel into an equirectangular accumulation grid at
     its own (lon -> u, lat -> v), weighted by viewing quality.
  4. Divides accumulated value by accumulated weight -> seamless mosaic.
  5. Optionally fills gaps with the per-facet albedo CSV as a fallback base layer.
  6. Writes the texture as 16-bit (data) and 8-bit (viewport) PNG, plus a
     coverage / weight map so you can see exactly where real imagery exists.

BACKPLANE PLANE ORDER  (verified from SBMT User Manual, "Generate Backplanes",
all values 4-byte float):
  1  image pixel value
  2  x intercept (km, body-fixed)
  3  y intercept (km, body-fixed)
  4  z intercept (km, body-fixed)
  5  latitude  (body-centric, degrees)
  6  longitude (degrees east, 0-360)
  7  radial distance (km)
  8  solar incidence angle (degrees)
  9  emission angle (degrees)
  10 solar phase angle (degrees)
  11 horizontal pixel scale (km)
  12 vertical pixel scale (km)
  13 surface slope relative to gravity (degrees)
  14 elevation relative to gravity (m)
  15 gravitational acceleration (m/s^2)
  16 gravitational potential (J/kg)
Plane indices are 1-based above; the PLANES dict below uses 0-based.

The script does NOT assume FITS-cube vs multi-extension-FITS vs ENVI layout;
it auto-detects. It also does not assume the band count is exactly 16 - it
checks and warns, since SBMT versions differ.

USAGE
-----
  python3 sbmt_mosaic.py --input ./backplanes --output ./phobos_texture \
      --width 8192 --height 4096 [--albedo-csv phobos_..._v004.csv]

Put every backplane export in --input. Accepted: .fit/.fits (cube or
multi-extension) and ENVI pairs (.hdr + data file, any extension or none).
"""

import argparse
import glob
import os
import sys
import warnings

import numpy as np

# ----------------------------------------------------------------------------
# Backplane plane indices (0-based). Edit here if a future SBMT build reorders.
# ----------------------------------------------------------------------------
PLANES = {
    "value":     0,
    "lat":       4,
    "lon":       5,
    "incidence": 7,
    "emission":  8,
    "phase":     9,
}
EXPECTED_BANDS = 16

# SBMT writes -1.0e32 (or similar large negative) for "no intercept" pixels.
# We treat any pixel whose lat/lon is non-finite OR whose value/lat/lon equals
# a sentinel-like extreme as invalid. This is detected adaptively per file.
SENTINEL_ABS = 1.0e30


# ============================================================================
# READERS  --  auto-detect FITS cube / multi-extension FITS / ENVI
# ============================================================================
def _read_fits(path):
    """Return ndarray (bands, ny, nx) from a FITS cube or multi-extension FITS."""
    from astropy.io import fits

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with fits.open(path) as hdul:
            image_hdus = [h for h in hdul
                          if getattr(h, "data", None) is not None]
            if not image_hdus:
                raise ValueError(f"{path}: no image data in any HDU")

            # Case A: a single HDU holding a 3D cube -> (bands, ny, nx)
            for h in image_hdus:
                if h.data.ndim == 3:
                    return np.asarray(h.data, dtype=np.float64)

            # Case B: a single HDU holding a 2D plane only (value-only export)
            if len(image_hdus) == 1 and image_hdus[0].data.ndim == 2:
                d = np.asarray(image_hdus[0].data, dtype=np.float64)
                return d[np.newaxis, :, :]

            # Case C: multi-extension FITS, one 2D plane per HDU
            planes = [np.asarray(h.data, dtype=np.float64)
                      for h in image_hdus if h.data.ndim == 2]
            if planes:
                shapes = {p.shape for p in planes}
                if len(shapes) != 1:
                    raise ValueError(
                        f"{path}: multi-extension planes differ in shape {shapes}")
                return np.stack(planes, axis=0)

    raise ValueError(f"{path}: unrecognised FITS structure")


def _find_envi_header(data_path):
    """ENVI stores a sidecar .hdr. Find it for a given data file."""
    stem, _ = os.path.splitext(data_path)
    for cand in (data_path + ".hdr", stem + ".hdr"):
        if os.path.exists(cand):
            return cand
    return None


def _parse_envi_header(hdr_path):
    """Minimal ENVI .hdr parser -> dict. Handles brace-wrapped multi-line values."""
    text = open(hdr_path, "r", errors="ignore").read()
    fields, i = {}, 0
    # Normalise: join lines, then split on key = value with optional { } blocks.
    # Simple state machine over the raw text.
    tokens = text.replace("\r", "")
    lines = tokens.split("\n")
    buf, key = None, None
    for line in lines:
        if buf is not None:
            buf += " " + line
            if "}" in line:
                fields[key] = buf[buf.index("{") + 1: buf.rindex("}")].strip()
                buf, key = None, None
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().lower(), v.strip()
        if v.startswith("{") and "}" not in v:
            buf, key = v, k
        elif v.startswith("{"):
            fields[k] = v[v.index("{") + 1: v.rindex("}")].strip()
        else:
            fields[k] = v
    return fields


# ENVI data type code -> numpy dtype
_ENVI_DTYPE = {
    "1": np.uint8, "2": np.int16, "3": np.int32, "4": np.float32,
    "5": np.float64, "12": np.uint16, "13": np.uint32,
}


def _read_envi(hdr_path):
    """Return ndarray (bands, ny, nx) from an ENVI .hdr + data file."""
    h = _parse_envi_header(hdr_path)
    nx = int(h["samples"])
    ny = int(h["lines"])
    nb = int(h["bands"])
    dtype = _ENVI_DTYPE[h["data type"].strip()]
    interleave = h.get("interleave", "bsq").strip().lower()
    byte_order = int(h.get("byte order", "0"))

    # Locate the binary data file: same stem as .hdr, or .hdr minus '.hdr'.
    stem = hdr_path[:-4] if hdr_path.lower().endswith(".hdr") else hdr_path
    data_file = None
    for cand in (stem, stem + ".img", stem + ".dat", stem + ".raw", stem + ".bsq"):
        if os.path.exists(cand) and cand != hdr_path:
            data_file = cand
            break
    if data_file is None:  # last resort: any sibling that isn't the header
        sibs = [p for p in glob.glob(stem + "*") if not p.lower().endswith(".hdr")]
        if sibs:
            data_file = sibs[0]
    if data_file is None:
        raise FileNotFoundError(f"No ENVI data file alongside {hdr_path}")

    raw = np.fromfile(data_file, dtype=dtype)
    if byte_order == 1:                       # big-endian on disk
        raw = raw.byteswap()
    raw = raw.astype(np.float64)

    if interleave == "bsq":                   # band, line, sample
        cube = raw.reshape(nb, ny, nx)
    elif interleave == "bil":                 # line, band, sample
        cube = raw.reshape(ny, nb, nx).transpose(1, 0, 2)
    elif interleave == "bip":                 # line, sample, band
        cube = raw.reshape(ny, nx, nb).transpose(2, 0, 1)
    else:
        raise ValueError(f"{hdr_path}: unknown interleave '{interleave}'")
    return np.ascontiguousarray(cube)


def load_cube(path):
    """Dispatch on extension. Returns (bands, ny, nx) float64."""
    low = path.lower()
    if low.endswith((".fit", ".fits", ".fts")):
        return _read_fits(path)
    if low.endswith(".hdr"):
        return _read_envi(path)
    # data file given directly: look for its sidecar header
    hdr = _find_envi_header(path)
    if hdr:
        return _read_envi(hdr)
    raise ValueError(f"Cannot determine format for {path}")


def discover_inputs(folder):
    """Return a de-duplicated list of cube paths. ENVI is keyed by .hdr."""
    fits_files = []
    for ext in ("*.fit", "*.fits", "*.fts", "*.FIT", "*.FITS"):
        fits_files += glob.glob(os.path.join(folder, ext))
    envi_hdrs = glob.glob(os.path.join(folder, "*.hdr")) + \
                glob.glob(os.path.join(folder, "*.HDR"))
    return sorted(set(fits_files)) + sorted(set(envi_hdrs))


# ============================================================================
# PHOTOMETRY
# ============================================================================
def lommel_seeliger(inc_deg, emi_deg):
    """
    Lommel-Seeliger disk function: D = mu0 / (mu0 + mu),
    with mu0 = cos(incidence), mu = cos(emission).

    This is the standard single-scattering law for dark, airless regolith
    surfaces (Phobos albedo ~0.07, Deimos ~0.068). Dividing each image's
    brightness by D removes the illumination-geometry component, leaving
    intrinsic surface reflectance that is consistent across images taken
    at different times. Without this step a mosaic shows obvious tile seams.
    """
    mu0 = np.cos(np.radians(inc_deg))
    mu  = np.cos(np.radians(emi_deg))
    mu0 = np.clip(mu0, 1e-3, 1.0)        # ignore terminator / shadowed pixels
    mu  = np.clip(mu,  1e-3, 1.0)
    return mu0 / (mu0 + mu)


def quality_weight(inc_deg, emi_deg, max_inc, max_emi):
    """
    Per-pixel blend weight. Favours pixels that are well-lit and viewed
    near-nadir; smoothly downweights grazing geometry; hard-zero beyond limits.

      weight = cos(emission) * cos(incidence)   within limits, else 0

    cos(emission) penalises foreshortened limb pixels (low spatial fidelity);
    cos(incidence) penalises poorly-lit pixels (low SNR, long shadows).
    """
    inc = np.asarray(inc_deg, dtype=np.float64)
    emi = np.asarray(emi_deg, dtype=np.float64)
    w = np.cos(np.radians(emi)) * np.cos(np.radians(inc))
    w[~np.isfinite(w)] = 0.0
    w[inc > max_inc] = 0.0
    w[emi > max_emi] = 0.0
    w[inc < 0] = 0.0
    w[emi < 0] = 0.0
    return np.clip(w, 0.0, 1.0)


# ============================================================================
# MOSAIC CORE
# ============================================================================
def process_cube(cube, acc, wacc, cov, W, H,
                  max_inc, max_emi, photometric=True):
    """Scatter one backplane cube's pixels into the global accumulators."""
    nb = cube.shape[0]
    if nb < EXPECTED_BANDS:
        print(f"    ! only {nb} bands (expected {EXPECTED_BANDS}); "
              f"skipping if required planes absent")
        needed = max(PLANES.values())
        if nb <= needed:
            print(f"    ! cube lacks plane index {needed}; SKIPPED")
            return 0

    val = cube[PLANES["value"]]
    lat = cube[PLANES["lat"]]
    lon = cube[PLANES["lon"]]
    inc = cube[PLANES["incidence"]]
    emi = cube[PLANES["emission"]]

    # Valid-pixel mask: finite, on-body (sentinels are huge-magnitude), lit.
    valid = (
        np.isfinite(val) & np.isfinite(lat) & np.isfinite(lon) &
        np.isfinite(inc) & np.isfinite(emi) &
        (np.abs(lat) < SENTINEL_ABS) & (np.abs(lon) < SENTINEL_ABS) &
        (np.abs(val) < SENTINEL_ABS) &
        (lat >= -90.0) & (lat <= 90.0) &
        (val > 0.0)
    )
    if not np.any(valid):
        return 0

    v = val[valid].astype(np.float64)
    la = lat[valid].astype(np.float64)
    lo = np.mod(lon[valid].astype(np.float64), 360.0)   # wrap into 0-360
    ic = inc[valid].astype(np.float64)
    em = emi[valid].astype(np.float64)

    # Photometric normalisation -> intrinsic reflectance
    if photometric:
        D = lommel_seeliger(ic, em)
        good = D > 1e-3
        v, la, lo, ic, em = v[good], la[good], lo[good], ic[good], em[good]
        v = v / D[good]

    if v.size == 0:
        return 0

    w = quality_weight(ic, em, max_inc, max_emi)
    keep = w > 0.0
    v, la, lo, w = v[keep], la[keep], lo[keep], w[keep]
    if v.size == 0:
        return 0

    # Equirectangular pixel mapping. Longitude 0->W across; lat +90 at row 0.
    u = np.clip((lo / 360.0 * W).astype(np.int64), 0, W - 1)
    rrow = np.clip(((90.0 - la) / 180.0 * H).astype(np.int64), 0, H - 1)
    flat = rrow * W + u

    np.add.at(acc,  flat, v * w)
    np.add.at(wacc, flat, w)
    np.add.at(cov,  flat, 1.0)
    return int(v.size)


def normalise_for_blend(acc, wacc):
    """Weighted mean per cell; NaN where no coverage."""
    out = np.full_like(acc, np.nan)
    hit = wacc > 0
    out[hit] = acc[hit] / wacc[hit]
    return out


# ============================================================================
# ALBEDO-CSV FALLBACK  (re-uses the per-facet SPC albedo as a base layer)
# ============================================================================
def albedo_base_layer(csv_path, W, H):
    """
    Build a low-frequency equirectangular grid from the SBMT per-facet albedo
    CSV (the file you already have). Used only to fill cells with no real
    image coverage so the texture degrades gracefully instead of showing holes.
    """
    import pandas as pd
    from scipy.ndimage import gaussian_filter

    df = pd.read_csv(csv_path, skiprows=[1],
                     usecols=["Latitude", "Longitude", "Albedo"],
                     dtype=np.float64)
    lon = np.mod(df["Longitude"].values, 360.0)
    lat = df["Latitude"].values
    alb = df["Albedo"].values

    u = np.clip((lon / 360.0 * W).astype(np.int64), 0, W - 1)
    r = np.clip(((90.0 - lat) / 180.0 * H).astype(np.int64), 0, H - 1)

    acc = np.zeros(H * W); cnt = np.zeros(H * W)
    np.add.at(acc, r * W + u, alb)
    np.add.at(cnt, r * W + u, 1.0)
    grid = np.where(cnt > 0, acc / np.maximum(cnt, 1), 0.0).reshape(H, W)

    # Inpaint sparse gaps so the base layer itself is hole-free.
    mask = (cnt.reshape(H, W) > 0).astype(np.float64)
    bv = gaussian_filter(grid * mask, sigma=6)
    bw = gaussian_filter(mask, sigma=6)
    filled = np.where(mask > 0, grid,
                      np.where(bw > 1e-3, bv / bw, float(np.nanmean(alb))))
    return filled


# ============================================================================
# OUTPUT
# ============================================================================
def save_outputs(mosaic, coverage, out_prefix, base_layer=None):
    """Write 16-bit data PNG, 8-bit viewport PNG, and coverage PNG."""
    from PIL import Image
    from scipy.ndimage import gaussian_filter

    H, W = mosaic.shape
    out_dir = os.path.dirname(os.path.abspath(out_prefix))
    os.makedirs(out_dir, exist_ok=True)

    filled = mosaic.copy()
    hole = ~np.isfinite(filled)

    if base_layer is not None and np.any(hole):
        # Match base-layer brightness to the mosaic where they overlap,
        # then drop it into the holes.
        ov = np.isfinite(mosaic) & np.isfinite(base_layer)
        if np.any(ov):
            m_mean, b_mean = np.nanmean(mosaic[ov]), np.nanmean(base_layer[ov])
            scale = m_mean / b_mean if b_mean > 0 else 1.0
        else:
            scale = 1.0
        filled[hole] = base_layer[hole] * scale
        print(f"  gap-fill: {hole.sum()} cells filled from albedo CSV "
              f"(scale {scale:.3f})")
    elif np.any(hole):
        # No base layer: soft-inpaint from surrounding mosaic data.
        m = np.isfinite(filled).astype(np.float64)
        v = np.where(m > 0, filled, 0.0)
        bv = gaussian_filter(v, sigma=8)
        bw = gaussian_filter(m, sigma=8)
        fallback = np.nanmean(mosaic[np.isfinite(mosaic)])
        safe_bw = np.where(bw > 1e-3, bw, 1.0)
        inpainted = np.where(bw > 1e-3, bv / safe_bw, fallback)
        filled[hole] = inpainted[hole]
        print(f"  gap-fill: {hole.sum()} cells soft-inpainted (no CSV given)")

    finite = filled[np.isfinite(filled)]
    lo, hi = np.percentile(finite, 1.0), np.percentile(finite, 99.0)
    if hi <= lo:
        hi = lo + 1.0

    # 16-bit linear data texture (use as Non-Color in Blender)
    n16 = np.clip((filled - lo) / (hi - lo), 0, 1)
    Image.fromarray((n16 * 65535).astype(np.uint16)).save(
        out_prefix + "_16bit.png")

    # 8-bit viewport texture
    Image.fromarray((n16 * 255).astype(np.uint8), mode="L").save(
        out_prefix + "_8bit.png")

    # Coverage map: how many image pixels landed in each cell (log-scaled)
    cov_log = np.log1p(coverage)
    cmax = cov_log.max() if cov_log.max() > 0 else 1.0
    Image.fromarray((cov_log / cmax * 255).astype(np.uint8), mode="L").save(
        out_prefix + "_coverage.png")

    return out_prefix + "_16bit.png", out_prefix + "_8bit.png", \
        out_prefix + "_coverage.png"


# ============================================================================
# MAIN
# ============================================================================
def main():
    ap = argparse.ArgumentParser(
        description="Route B: photometric equirectangular mosaic "
                    "from SBMT backplane exports.")
    ap.add_argument("--input", required=True,
                    help="Folder containing backplane exports (FITS/ENVI).")
    ap.add_argument("--output", required=True,
                    help="Output path prefix, e.g. ./phobos_texture")
    ap.add_argument("--width", type=int, default=8192,
                    help="Texture width in pixels (default 8192).")
    ap.add_argument("--height", type=int, default=4096,
                    help="Texture height in pixels (default 4096).")
    ap.add_argument("--max-incidence", type=float, default=80.0,
                    help="Discard pixels with incidence above this (deg).")
    ap.add_argument("--max-emission", type=float, default=70.0,
                    help="Discard pixels with emission above this (deg).")
    ap.add_argument("--no-photometric", action="store_true",
                    help="Disable Lommel-Seeliger normalisation (not advised).")
    ap.add_argument("--albedo-csv", default=None,
                    help="Optional SBMT per-facet albedo CSV for gap-filling.")
    args = ap.parse_args()

    W, H = args.width, args.height
    if W != 2 * H:
        print(f"WARNING: width {W} != 2*height {H}. Equirectangular textures "
              f"should be 2:1. Continuing anyway.")

    inputs = discover_inputs(args.input)
    if not inputs:
        sys.exit(f"No FITS or ENVI files found in {args.input}")
    print(f"Found {len(inputs)} backplane export(s) in {args.input}")
    print(f"Mosaic grid: {W} x {H}  "
          f"(photometric={'OFF' if args.no_photometric else 'ON'})")

    acc  = np.zeros(H * W, dtype=np.float64)
    wacc = np.zeros(H * W, dtype=np.float64)
    cov  = np.zeros(H * W, dtype=np.float64)

    used, total_px = 0, 0
    for k, path in enumerate(inputs, 1):
        name = os.path.basename(path)
        try:
            cube = load_cube(path)
        except Exception as e:
            print(f"  [{k}/{len(inputs)}] {name}: READ FAILED - {e}")
            continue
        n = process_cube(cube, acc, wacc, cov, W, H,
                         args.max_incidence, args.max_emission,
                         photometric=not args.no_photometric)
        print(f"  [{k}/{len(inputs)}] {name}: {cube.shape[0]} bands, "
              f"{n:,} pixels contributed")
        used += (n > 0)
        total_px += n

    if used == 0:
        sys.exit("No usable pixels from any input. Check backplane plane order "
                 "(see PLANES dict) and that exports include all 16 planes.")

    print(f"\n{used}/{len(inputs)} cubes contributed; "
          f"{total_px:,} pixels total")

    mosaic = normalise_for_blend(acc, wacc).reshape(H, W)
    coverage = cov.reshape(H, W)
    covered = np.isfinite(mosaic).sum()
    print(f"Coverage: {covered:,}/{H*W:,} cells "
          f"({100.0*covered/(H*W):.1f}% of the sphere has real imagery)")

    base = None
    if args.albedo_csv:
        if os.path.exists(args.albedo_csv):
            print(f"Loading albedo base layer from {args.albedo_csv}")
            base = albedo_base_layer(args.albedo_csv, W, H)
        else:
            print(f"WARNING: --albedo-csv not found: {args.albedo_csv}")

    f16, f8, fcov = save_outputs(mosaic, coverage, args.output, base)
    print(f"\nWrote:\n  {f16}\n  {f8}\n  {fcov}")
    print("\nIn Blender: load the 16-bit PNG as the Base Colour image, set its "
          "Colour Space to Non-Color, and apply it to the UV-mapped OBJ.")


if __name__ == "__main__":
    main()
