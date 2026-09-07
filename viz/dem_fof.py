"""Friends-of-friends clustering for DEM grain visualisation.

Canonical module for Windows preprocess. Vectorised connectivity via
``scipy.sparse.csgraph.connected_components`` (replaces Python union-find loop).
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np
from scipy.spatial import cKDTree
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components

from viz.constants import (
    MAIN_BODY_INTACT_DISP_RATIO,
    MAIN_BODY_LINK_FACTOR_INIT,
    MAIN_BODY_LINK_FACTOR_MAX,
    MAIN_BODY_MIN_CLUSTER_FRAC,
)


def mass_weighted_rg(pos: np.ndarray, mass: np.ndarray) -> float:
    """Mass-weighted radius of gyration."""
    m_tot = float(mass.sum())
    if m_tot <= 0.0:
        return float("nan")
    rcom = (pos * mass[:, None]).sum(axis=0) / m_tot
    dr = pos - rcom
    r2 = (dr * dr).sum(axis=1)
    return math.sqrt(float((mass * r2).sum()) / m_tot)


def fof_cluster_labels(b_pos: np.ndarray, link_factor: float) -> np.ndarray:
    """Return cluster label (0…K-1) per grain at a fixed link factor."""
    n = len(b_pos)
    if n < 2:
        return np.zeros(n, dtype=np.int32)

    tree = cKDTree(b_pos)
    dists, _ = tree.query(b_pos, k=2)
    nn_dist = dists[:, 1]
    link_length = link_factor * float(np.median(nn_dist))

    pairs = list(tree.query_pairs(link_length))
    if not pairs:
        return np.arange(n, dtype=np.int32)

    rows = [i for i, j in pairs] + [j for i, j in pairs]
    cols = [j for i, j in pairs] + [i for i, j in pairs]
    data = np.ones(len(rows), dtype=np.uint8)
    graph = csr_matrix((data, (rows, cols)), shape=(n, n))
    _, labels = connected_components(graph, directed=False)
    return labels.astype(np.int32, copy=False)


def main_body_mask_fof(b_pos: np.ndarray, link_factor: float) -> np.ndarray:
    """Largest friends-of-friends cluster at a fixed link factor."""
    labels = fof_cluster_labels(b_pos, link_factor)
    if len(labels) == 0:
        return np.array([], dtype=bool)
    unique, counts = np.unique(labels, return_counts=True)
    largest = unique[np.argmax(counts)]
    return labels == largest


def main_body_mask_fof_adaptive(b_pos: np.ndarray, b_mass: np.ndarray) -> np.ndarray:
    """FOF main body with increasing link length until cluster is substantial."""
    del b_mass  # mass not used in link-length search (matches analysis)
    n = len(b_pos)
    if n < 2:
        return np.ones(n, dtype=bool)
    min_count = max(2, int(math.ceil(MAIN_BODY_MIN_CLUSTER_FRAC * n)))
    link_factor = MAIN_BODY_LINK_FACTOR_INIT
    mb = main_body_mask_fof(b_pos, link_factor)
    while int(mb.sum()) < min_count and link_factor < MAIN_BODY_LINK_FACTOR_MAX:
        link_factor = min(link_factor * 2.0, MAIN_BODY_LINK_FACTOR_MAX)
        mb = main_body_mask_fof(b_pos, link_factor)
    return mb


def main_body_mask(
    b_pos: np.ndarray,
    b_mass: np.ndarray,
    *,
    rg_ratio: Optional[float] = None,
) -> np.ndarray:
    """Boolean mask of the main Apophis rubble fragment at one dump."""
    n = len(b_pos)
    if n < 2:
        return np.ones(n, dtype=bool)
    if rg_ratio is not None and rg_ratio < MAIN_BODY_INTACT_DISP_RATIO:
        return np.ones(n, dtype=bool)
    return main_body_mask_fof_adaptive(b_pos, b_mass)


def fof_cluster_labels_adaptive(b_pos: np.ndarray, b_mass: np.ndarray) -> np.ndarray:
    """Cluster labels using the same adaptive link-length search as main-body FOF."""
    del b_mass
    n = len(b_pos)
    if n < 2:
        return np.zeros(n, dtype=np.int32)
    min_count = max(2, int(math.ceil(MAIN_BODY_MIN_CLUSTER_FRAC * n)))
    link_factor = MAIN_BODY_LINK_FACTOR_INIT
    labels = fof_cluster_labels(b_pos, link_factor)
    largest_count = int(np.bincount(labels).max()) if labels.size else 0
    while largest_count < min_count and link_factor < MAIN_BODY_LINK_FACTOR_MAX:
        link_factor = min(link_factor * 2.0, MAIN_BODY_LINK_FACTOR_MAX)
        labels = fof_cluster_labels(b_pos, link_factor)
        largest_count = int(np.bincount(labels).max())
    return labels


def significant_fragment_masks(
    labels: np.ndarray,
    mass: np.ndarray,
    min_mass_frac: float,
    *,
    rg_ratio: Optional[float] = None,
) -> List[np.ndarray]:
    """Return boolean masks for clusters with mass fraction >= threshold."""
    n = len(mass)
    if n == 0:
        return []
    if rg_ratio is not None and rg_ratio < MAIN_BODY_INTACT_DISP_RATIO:
        return [np.ones(n, dtype=bool)]

    m_tot = float(mass.sum())
    if m_tot <= 0.0:
        return [np.ones(n, dtype=bool)]

    masks: List[np.ndarray] = []
    for label in np.unique(labels):
        mask = labels == label
        if float(mass[mask].sum()) / m_tot >= min_mass_frac:
            masks.append(mask)
    return masks


def high_energy_mask_in_cluster(
    pos: np.ndarray,
    mass: np.ndarray,
    vel: np.ndarray,
    cluster_mask: np.ndarray,
) -> np.ndarray:
    """Grains in cluster with positive specific energy in the cluster CoM frame."""
    out = np.zeros(len(pos), dtype=bool)
    if not cluster_mask.any():
        return out

    m_main = float(mass[cluster_mask].sum())
    if m_main <= 0.0:
        return out

    main_pos = pos[cluster_mask]
    main_vel = vel[cluster_mask]
    main_mass = mass[cluster_mask]

    rcom = (main_pos * main_mass[:, None]).sum(axis=0) / m_main
    vcom = (main_vel * main_mass[:, None]).sum(axis=0) / m_main
    dr = main_pos - rcom
    dv = main_vel - vcom
    r = np.linalg.norm(dr, axis=1)
    v2 = (dv * dv).sum(axis=1)
    safe_r = np.where(r > 0.0, r, 1.0)
    eps = np.where(r > 0.0, 0.5 * v2 - m_main / safe_r, -1.0)
    local = eps > 0.0
    out[np.where(cluster_mask)[0][local]] = True
    return out


def unbound_mass_main_body(
    pos: np.ndarray,
    mass: np.ndarray,
    vel: np.ndarray,
    *,
    main_body_mask: Optional[np.ndarray] = None,
) -> float:
    """Mass not on the main fragment (matches WSL analysis)."""
    m_tot = float(mass.sum())
    if m_tot <= 0.0:
        return 0.0
    mb = main_body_mask if main_body_mask is not None else main_body_mask_fof_adaptive(pos, mass)
    unbound = float(mass[~mb].sum())
    m_main = float(mass[mb].sum())
    if m_main <= 0.0:
        return unbound

    main_pos = pos[mb]
    main_vel = vel[mb]
    main_mass = mass[mb]
    rcom = (main_pos * main_mass[:, None]).sum(axis=0) / m_main
    vcom = (main_vel * main_mass[:, None]).sum(axis=0) / m_main
    dr = main_pos - rcom
    dv = main_vel - vcom
    r = np.linalg.norm(dr, axis=1)
    v2 = (dv * dv).sum(axis=1)
    safe_r = np.where(r > 0.0, r, 1.0)
    eps = np.where(r > 0.0, 0.5 * v2 - m_main / safe_r, -1.0)
    unbound += float(main_mass[eps > 0.0].sum())
    return unbound


def assign_fragments_and_ejecta(
    pos: np.ndarray,
    mass: np.ndarray,
    vel: np.ndarray,
    rg_ratio: float,
    min_mass_frac: float,
) -> Tuple[List[np.ndarray], np.ndarray, np.ndarray]:
    """Split grains into envelope fragment masks and an ejecta boolean mask.

    Returns ``(fragment_masks, ejecta_mask, cluster_labels)``.
    """
    n = len(mass)
    if n == 0:
        return [], np.array([], dtype=bool), np.array([], dtype=np.int32)

    if rg_ratio < MAIN_BODY_INTACT_DISP_RATIO:
        all_mask = np.ones(n, dtype=bool)
        energy = high_energy_mask_in_cluster(pos, mass, vel, all_mask)
        fragment_masks = [all_mask & ~energy] if (all_mask & ~energy).any() else [all_mask]
        return fragment_masks, energy, np.zeros(n, dtype=np.int32)

    labels = fof_cluster_labels_adaptive(pos, mass)
    sig_masks = significant_fragment_masks(labels, mass, min_mass_frac, rg_ratio=rg_ratio)
    ejecta = np.zeros(n, dtype=bool)
    fragment_masks: List[np.ndarray] = []

    kept_labels = set()
    for mask in sig_masks:
        label_ids = np.unique(labels[mask])
        kept_labels.update(int(x) for x in label_ids)
        energy = high_energy_mask_in_cluster(pos, mass, vel, mask)
        envelope = mask & ~energy
        if envelope.any():
            fragment_masks.append(envelope)
        ejecta |= energy

    small_cluster = ~np.isin(labels, list(kept_labels))
    ejecta |= small_cluster

    if not fragment_masks:
        fragment_masks = sig_masks

    return fragment_masks, ejecta, labels
