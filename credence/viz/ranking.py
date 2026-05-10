"""Ranking-formula plots.

Phase 1: weighted average vs. simple average.
Phase 2: Bayesian prior shrinkage toward the global average (per SPEC §phase 2).
"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

from ._common import add_description, save

PRIOR_WEIGHT = 3.0
GLOBAL_AVG = 7.0


def plot_weighted_vs_simple() -> None:
    """Two raters — credible rater says X, low-credibility rater says Y. Plot the score."""
    rater_a = 9.0
    rater_b = 4.0
    w_a = np.linspace(0, 1, 200)
    w_b = 0.3  # low credibility rater stays fixed

    weighted = (w_a * rater_a + w_b * rater_b) / np.maximum(w_a + w_b, 1e-9)
    simple = np.full_like(w_a, (rater_a + rater_b) / 2)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(w_a, weighted, label=f"weighted (rater B fixed at w={w_b})")
    ax.plot(w_a, simple, linestyle="--", label="simple average")
    ax.set_xlabel("rater A credibility weight")
    ax.set_ylabel("restaurant score")
    ax.set_title(f"weighted vs simple average — A rated {rater_a}, B rated {rater_b}")
    ax.legend()
    add_description(ax,
        "When rater A is low-credibility, weighted ≈ simple average.\n"
        "As A's credibility grows, the weighted score tracks their\n"
        "rating (9.0) and discounts B's outlier (4.0). Simple\n"
        "average is always (9+4)/2=6.5 regardless of who is\n"
        "the more credible rater — it treats all opinions equally.",
        loc="upper left",
    )
    save(fig, "08_weighted_vs_simple.png")


def plot_bayesian_prior() -> None:
    """Phase-2 Bayesian prior pulls thin-data ratings toward the global average."""
    n_ratings = np.arange(1, 30)
    fig, ax = plt.subplots(figsize=(7, 4))

    for raw in [9.5, 5.0, 3.0]:
        # all raters equal weight = 1 for simplicity
        total_w = n_ratings * 1.0
        score = (PRIOR_WEIGHT * GLOBAL_AVG + raw * total_w) / (PRIOR_WEIGHT + total_w)
        ax.plot(n_ratings, score, label=f"raw avg = {raw}")

    ax.axhline(GLOBAL_AVG, color="grey", linestyle=":", label=f"global avg = {GLOBAL_AVG}")
    ax.set_xlabel("number of ratings")
    ax.set_ylabel("posterior score")
    ax.set_title(f"Bayesian shrinkage (prior_weight = {PRIOR_WEIGHT})")
    ax.legend()
    add_description(ax,
        "prior_weight=3.0 pulls restaurants with few ratings toward\n"
        "the global average (7.0). After 1 rating, a raw 9.5\n"
        "becomes ≈7.6 — the prior dominates. By ~10 ratings the\n"
        "posterior closely tracks the raw score. This prevents a\n"
        "single glowing review from surfacing a restaurant at the\n"
        "top of rankings before enough evidence has accumulated.",
        loc="lower left",
    )
    save(fig, "09_bayesian_prior.png")


def main() -> None:
    plot_weighted_vs_simple()
    plot_bayesian_prior()


if __name__ == "__main__":
    main()
