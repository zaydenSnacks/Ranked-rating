"""Phase-2b clustering plots.

Mirrors modules/clustering/{discover,assign,coherence,consensus}.py and the
surfacing rule in modules/ranking/ranking.py. Pure numpy re-implementations —
constants and formula shapes must be kept in sync by hand; see viz/README.md.
"""
from __future__ import annotations

import itertools

import numpy as np
import matplotlib.pyplot as plt

from ._common import add_description, save

# Constants — keep in sync with modules/clustering/ and modules/ranking/ranking.py
K_INITIAL              = 4     # discover.py
MIN_RATINGS_FOR_VECTOR = 3     # discover.py
KMEANS_SEED            = 0     # discover.py
MIN_COHERENCE          = 0.50  # coherence.py
MIN_PAIR_OVERLAP       = 3     # coherence.py
MIN_CONTRIBUTING_PAIRS = 3     # coherence.py
MIN_RATERS_PER_CLUSTER = 5     # consensus.py
PRIOR_WEIGHT           = 3.0   # consensus.py / ranking.py
GLOBAL_AVG             = 7.0   # illustrative only


# ── production-math mirrors ───────────────────────────────────────────────────

def kmeans(X: np.ndarray, k: int, seed: int = KMEANS_SEED, max_iter: int = 100):
    """Mirror of discover.kmeans — plain Lloyd's, empty-cluster reseeding."""
    n = X.shape[0]
    k = min(k, n)
    rng = np.random.default_rng(seed)
    centroids = X[rng.choice(n, size=k, replace=False)].astype(float)
    labels = None
    for _ in range(max_iter):
        dists = np.linalg.norm(X[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = dists.argmin(axis=1)
        for j in range(k):
            if not np.any(new_labels == j):
                farthest = dists[np.arange(n), new_labels].argmax()
                new_labels[farthest] = j
        if labels is not None and np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(k):
            centroids[j] = X[labels == j].mean(axis=0)
    return labels, centroids


def coherence_score(vectors: np.ndarray) -> float:
    """Mirror of coherence.coherence_score — average pairwise Pearson r over
    each pair's *co-rated* restaurants. viz members are dense (every member rates
    every restaurant), so each pair's overlap is the full vector and the sparsity
    gates always pass; they're mirrored here for parity with production, which
    sees sparse real data. Zero-variance pairs contribute 0. See viz/README.md."""
    vectors = np.asarray(vectors)
    n = len(vectors)
    if n < 2 or vectors.shape[1] < MIN_PAIR_OVERLAP:
        return 0.0
    corrs: list[float] = []
    for i, j in itertools.combinations(range(n), 2):
        a, b = vectors[i], vectors[j]
        if a.std() == 0 or b.std() == 0:
            corrs.append(0.0)
        else:
            corrs.append(float(np.corrcoef(a, b)[0, 1]))
    if len(corrs) < MIN_CONTRIBUTING_PAIRS:
        return 0.0
    return float(np.mean(corrs))


def assignment_confidence(x: np.ndarray, centroids: np.ndarray, label: int) -> float:
    """Mirror of assign.assignment_confidence — 1 − d_nearest/d_second."""
    if len(centroids) < 2:
        return 1.0
    dists = np.linalg.norm(centroids - x, axis=1)
    d_assigned = dists[label]
    d_other = np.min(np.delete(dists, label))
    if d_other == 0.0:
        return 0.0
    return float(np.clip(1.0 - d_assigned / d_other, 0.0, 1.0))


def cluster_consensus(scores: np.ndarray, weights: np.ndarray, global_avg: float) -> float:
    """Mirror of consensus.compute_cluster_scores — Bayesian prior within cluster."""
    return (PRIOR_WEIGHT * global_avg + np.sum(scores * weights)) / (PRIOR_WEIGHT + np.sum(weights))


# ── plots ─────────────────────────────────────────────────────────────────────

def plot_kmeans_discovery() -> None:
    """Two taste groups in 2-restaurant rating space; k-means finds them unlabeled."""
    rng = np.random.default_rng(7)
    calibrated = rng.normal([3.0, 8.5], 0.7, size=(40, 2))   # harsh on A, loves B
    casual     = rng.normal([8.0, 8.0], 0.7, size=(120, 2))  # everything is great
    X = np.clip(np.vstack([calibrated, casual]), 1, 10)
    labels, centroids = kmeans(X, k=2)

    fig, ax = plt.subplots(figsize=(7, 5))
    for j, color in zip(range(2), ["#1f77b4", "#ff7f0e"]):
        pts = X[labels == j]
        ax.scatter(pts[:, 0], pts[:, 1], s=18, alpha=0.6, color=color,
                   label=f"cluster {j} (n={len(pts)})")
    ax.scatter(centroids[:, 0], centroids[:, 1], marker="X", s=180, color="black",
               zorder=5, label="centroids")
    ax.set_xlabel("rating of restaurant A (chain)")
    ax.set_ylabel("rating of restaurant B (craft)")
    ax.set_title("cluster discovery — k-means on rating vectors, no labels")
    ax.set_xlim(0.5, 10.5); ax.set_ylim(0.5, 10.5)
    ax.legend(loc="lower left")
    add_description(ax,
        "Each dot is a user, positioned by how they rated two\n"
        "restaurants. The casual majority (3× larger) rates both\n"
        "high; the calibrated minority separates them. K-means\n"
        "recovers the groups from rating patterns alone — no\n"
        "demographic questions, no labels. Volume changes a\n"
        "cluster's size, not its existence.",
        loc="lower right",
    )
    save(fig, "10_kmeans_discovery.png")


def plot_coherence() -> None:
    """Coherence vs member noise — and why a mixed cluster collapses."""
    rng = np.random.default_rng(3)
    base = np.array([2.0, 9.0, 4.0, 8.0, 6.0, 3.0])   # shared taste pattern
    anti = 12.0 - base                                  # opposing taste
    sigmas = np.linspace(0.0, 4.0, 40)

    def avg_coherence(make_members) -> np.ndarray:
        out = []
        for sigma in sigmas:
            trials = [coherence_score(make_members(sigma)) for _ in range(30)]
            out.append(np.mean(trials))
        return np.array(out)

    pure = avg_coherence(lambda s: base + rng.normal(0, s, size=(8, base.size)))
    mixed = avg_coherence(lambda s: np.vstack([
        base + rng.normal(0, s, size=(4, base.size)),
        anti + rng.normal(0, s, size=(4, base.size)),
    ]))

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(sigmas, pure, label="8 members sharing one taste pattern")
    ax.plot(sigmas, mixed, label="4 + 4 members with opposing patterns")
    ax.axhline(MIN_COHERENCE, color="grey", linestyle=":",
               label=f"MIN_COHERENCE = {MIN_COHERENCE}")
    ax.set_xlabel("per-member rating noise σ")
    ax.set_ylabel("coherence (avg pairwise Pearson r)")
    ax.set_title("cluster coherence — agreement survives noise, disagreement doesn't")
    ax.legend()
    add_description(ax,
        "Coherence is the surfacing criterion. A genuine taste\n"
        "group stays above MIN_COHERENCE until members get very\n"
        "noisy. A cluster k-means got wrong (two opposing tastes\n"
        "jammed together) nets out near zero — its scores never\n"
        "surface. Raw r is used, not (r+1)/2: opposition must\n"
        "read as ≤0, not as half-agreement.",
        loc="upper right",
    )
    save(fig, "11_coherence.png")


def plot_assignment_confidence() -> None:
    """Confidence along the line between two centroids."""
    centroid_a = np.array([3.0, 8.5])
    centroid_b = np.array([8.0, 8.0])
    centroids = np.vstack([centroid_a, centroid_b])

    t = np.linspace(-0.3, 1.3, 400)  # extend past both centroids
    points = centroid_a + t[:, None] * (centroid_b - centroid_a)
    conf = np.array([
        assignment_confidence(p, centroids, int(np.linalg.norm(centroids - p, axis=1).argmin()))
        for p in points
    ])

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(t, conf)
    ax.axvline(0.0, color="#1f77b4", linestyle=":", label="centroid A")
    ax.axvline(1.0, color="#ff7f0e", linestyle=":", label="centroid B")
    ax.axvline(0.5, color="grey", linestyle="--", alpha=0.6, label="midpoint (confidence 0)")
    ax.set_xlabel("position along the A→B line (0 = at A, 1 = at B)")
    ax.set_ylabel("assignment confidence")
    ax.set_title("assignment confidence = 1 − d_nearest / d_second_nearest")
    ax.legend(loc="lower left")
    add_description(ax,
        "A user exactly between two clusters gets confidence 0 —\n"
        "the assignment is recorded but flagged as arbitrary.\n"
        "Confidence climbs toward 1 as the user's rating vector\n"
        "approaches one centroid and beyond it. Planted trusted\n"
        "sources bypass this and get 1.0: their placement is a\n"
        "prior, not a distance measurement.",
        loc="upper right",
    )
    save(fig, "12_assignment_confidence.png")


def plot_cluster_surfacing() -> None:
    """The Taco Bell mechanic: which score surfaces as calibrated coherence varies."""
    casual_consensus = 8.4      # big casual cluster loves the chain
    casual_coherence = 0.42     # below MIN_COHERENCE — can never surface
    calibrated_scores = np.full(MIN_RATERS_PER_CLUSTER, 5.1)
    calibrated_weights = np.full(MIN_RATERS_PER_CLUSTER, 0.6)
    calibrated_consensus = cluster_consensus(calibrated_scores, calibrated_weights, GLOBAL_AVG)
    bayesian_fallback = 7.9     # global weighted average, dominated by casual volume

    coh = np.linspace(0.0, 1.0, 400)
    surfaced = np.where(coh >= MIN_COHERENCE, calibrated_consensus, bayesian_fallback)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(coh, surfaced, label="surfaced score for the chain restaurant", linewidth=2)
    ax.axvline(MIN_COHERENCE, color="grey", linestyle=":", label=f"MIN_COHERENCE = {MIN_COHERENCE}")
    ax.axhline(bayesian_fallback, color="#ff7f0e", linestyle="--", alpha=0.5,
               label=f"Bayesian fallback ≈ {bayesian_fallback} (volume wins)")
    ax.axhline(calibrated_consensus, color="#1f77b4", linestyle="--", alpha=0.5,
               label=f"calibrated cluster consensus ≈ {calibrated_consensus:.1f}")
    ax.set_xlabel("coherence of the calibrated cluster")
    ax.set_ylabel("final restaurant score")
    ax.set_ylim(4, 9)
    ax.set_title("cluster surfacing — coherence gate decides whose score counts")
    ax.legend(loc="center left", fontsize=8)
    add_description(ax,
        f"The casual cluster (coherence {casual_coherence}) can never\n"
        "surface — it fails MIN_COHERENCE no matter how many\n"
        "members it has. Once the calibrated cluster is coherent\n"
        f"enough and has ≥ {MIN_RATERS_PER_CLUSTER} raters on this restaurant, its\n"
        f"consensus IS the score: the chain drops 7.9 → {calibrated_consensus:.1f}\n"
        "(the within-cluster prior keeps it above the raw 5.1).\n"
        "Member count appears nowhere in this decision.",
        loc="lower right",
    )
    save(fig, "13_cluster_surfacing.png")


def main() -> None:
    plot_kmeans_discovery()
    plot_coherence()
    plot_assignment_confidence()
    plot_cluster_surfacing()


if __name__ == "__main__":
    main()
