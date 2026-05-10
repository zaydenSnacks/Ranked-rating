"""Phase-2 Glicko-inspired credibility update plots.

Mirrors modules/credibility/dynamic.py. Constants must be kept in sync; see
viz/README.md for the maintenance contract.
"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

from ._common import add_description, save

# Constants — keep in sync with modules/credibility/dynamic.py
LEARNING_RATE = 0.05
RD_DECAY = 0.05
VOL_BUMP = 0.01
RD_FLOOR = 0.10
VOL_CAP = 0.15
SCORE_RANGE = 9.0
DAMPEN = 3.0


def step(cs: float, rd: float, vol: float, user_score: float, consensus: float, community_w: float
         ) -> tuple[float, float, float]:
    agreement = 1.0 - abs(user_score - consensus) / SCORE_RANGE
    nudge_scale = community_w / (community_w + DAMPEN)

    if agreement >= 0.5:
        delta = LEARNING_RATE * nudge_scale * (agreement - 0.5) * 2
        cs = min(1.0, cs + delta)
        rd = max(RD_FLOOR, rd - RD_DECAY * nudge_scale)
    else:
        delta = LEARNING_RATE * nudge_scale * (0.5 - agreement) * 2
        cs = max(0.0, cs - delta)
        vol = min(VOL_CAP, vol + VOL_BUMP * nudge_scale)
    return cs, rd, vol


def simulate(user_scores: np.ndarray, consensus: float, community_w: float
             ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cs, rd, vol = 0.5, 1.0, 0.06
    cs_t, rd_t, vol_t = [cs], [rd], [vol]
    for s in user_scores:
        cs, rd, vol = step(cs, rd, vol, float(s), consensus, community_w)
        cs_t.append(cs); rd_t.append(rd); vol_t.append(vol)
    return np.array(cs_t), np.array(rd_t), np.array(vol_t)


def plot_trajectories() -> None:
    """How (credibility, RD, volatility) evolve under repeated agreement vs. divergence."""
    n = 50
    consensus = 7.0
    community_w = 5.0

    rng = np.random.default_rng(0)
    # NB: agreement >= 0.5 requires |user − consensus| <= SCORE_RANGE/2 = 4.5,
    # so a "diverger" must be at least ~5 points off on the 1–10 scale.
    agreer = rng.normal(consensus, 0.4, n)         # mostly agrees
    diverger = rng.normal(consensus - 5.5, 0.4, n) # consistently far below
    mixed = np.concatenate([agreer[:25], diverger[:25]])

    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True)
    for label, scores in [("agreer", agreer), ("diverger", diverger), ("flips at n=25", mixed)]:
        cs, rd, vol = simulate(scores, consensus, community_w)
        axes[0].plot(cs, label=label)
        axes[1].plot(rd, label=label)
        axes[2].plot(vol, label=label)

    axes[0].set_ylabel("credibility_score"); axes[0].axhline(0.5, color="grey", linestyle=":")
    axes[1].set_ylabel("rating_deviation"); axes[1].axhline(RD_FLOOR, color="red", linestyle="--", label=f"floor={RD_FLOOR}")
    axes[2].set_ylabel("volatility"); axes[2].axhline(VOL_CAP, color="red", linestyle="--", label=f"cap={VOL_CAP}")
    axes[2].set_xlabel("rating events")
    for ax in axes:
        ax.legend(loc="best", fontsize=8)
    fig.suptitle(f"Glicko-inspired update — consensus={consensus}, community_w={community_w}")
    add_description(axes[0],
        "Three user archetypes over 50 rating events (consensus=7.0).\n"
        "agreer: rates near consensus → credibility rises, RD falls\n"
        "  to floor as the system grows confident in them.\n"
        "diverger: consistently ~5.5 below consensus → credibility\n"
        "  collapses, volatility climbs toward cap.\n"
        "flips at n=25: reversal visible in all three stats at once.",
        loc="lower left",
    )
    save(fig, "05_dynamic_trajectories.png")


def plot_dampen_effect() -> None:
    """How DAMPEN attenuates updates from low-weight communities."""
    community_w = np.linspace(0, 20, 200)
    nudge_scale = community_w / (community_w + DAMPEN)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(community_w, nudge_scale)
    ax.axvline(DAMPEN, color="red", linestyle="--", label=f"DAMPEN = {DAMPEN}")
    ax.set_xlabel("community effective weight")
    ax.set_ylabel("nudge scale")
    ax.set_title("DAMPEN prior — thin communities give weak signal\nnudge_scale = w / (w + DAMPEN)")
    ax.legend()
    add_description(ax,
        "DAMPEN=3.0 is a prior on how much to trust the community\n"
        "consensus. At community_weight=DAMPEN, nudge_scale=0.5 —\n"
        "only half-strength update. A restaurant with 1–2 raters\n"
        "barely moves your credibility regardless of how credible\n"
        "those raters are. Full signal only kicks in when the\n"
        "community pool is clearly larger than the prior.",
        loc="upper left",
    )
    save(fig, "06_dampen_effect.png")


def plot_agreement_curve() -> None:
    """Per-event delta to credibility_score as a function of |user − consensus|."""
    diff = np.linspace(0, SCORE_RANGE, 200)
    agreement = 1.0 - diff / SCORE_RANGE

    fig, ax = plt.subplots(figsize=(7, 4))
    for cw in [1.0, 3.0, 10.0]:
        scale = cw / (cw + DAMPEN)
        delta = np.where(
            agreement >= 0.5,
            LEARNING_RATE * scale * (agreement - 0.5) * 2,
            -LEARNING_RATE * scale * (0.5 - agreement) * 2,
        )
        ax.plot(diff, delta, label=f"community_w = {cw}")
    ax.axhline(0, color="grey", linewidth=0.5)
    ax.set_xlabel("|user_score − consensus|")
    ax.set_ylabel("Δ credibility_score")
    ax.set_title("per-event credibility delta (LEARNING_RATE = 0.05)")
    ax.legend()
    add_description(ax,
        "Each rating event shifts credibility_score by this delta.\n"
        "Agreement threshold is |diff| < 4.5 (half of score range).\n"
        "LEARNING_RATE=0.05 caps shifts to ±0.05 per event.\n"
        "Higher community_weight (more credible raters weighed in)\n"
        "amplifies the delta — agreeing with a credible community\n"
        "moves you more than agreeing with a single new user.",
        loc="upper right",
    )
    save(fig, "07_agreement_curve.png")


def main() -> None:
    plot_trajectories()
    plot_dampen_effect()
    plot_agreement_curve()


if __name__ == "__main__":
    main()
