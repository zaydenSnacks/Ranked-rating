"""
Cluster coherence: average pairwise Pearson correlation between members'
rating vectors. High coherence = members agree closely with each other.

Coherence is the surfacing criterion — a small high-coherence cluster beats a
large low-coherence one (never member_count). Raw r is used, not the (r+1)/2
remap alignment uses: anti-correlated members should drag coherence negative,
and MIN_COHERENCE then reads as "members genuinely agree".
"""
from __future__ import annotations

import numpy as np

MIN_COHERENCE = 0.50  # below this a cluster is not "calibrated enough" to surface scores


def coherence_score(vectors: np.ndarray) -> float:
    """Average pairwise Pearson r over member rating vectors.

    Pure numpy (no DB) so viz can mirror it exactly. Clusters with fewer than
    2 members have no pairs and score 0.0. Zero-variance vectors (a member who
    gave every restaurant the same score) produce NaN correlations; those
    pairs contribute 0 — no signal, not agreement.
    """
    n = len(vectors)
    if n < 2:
        return 0.0
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(vectors)
    corr = np.nan_to_num(corr, nan=0.0)
    upper = corr[np.triu_indices(n, k=1)]
    return float(upper.mean())
