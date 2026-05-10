"""Phase-1 credibility component plots.

Mirrors modules/credibility/{expertise,proximity,score}.py. The math is
re-implemented in numpy here on purpose — viz/ should not import from
modules/, so plots stay runnable without a database.
"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

from ._common import add_description, save

# Constants — keep in sync with modules/credibility/
MAX_N = 20
THRESHOLD = 0.6
W_ALIGN, W_EXP, W_PROX = 0.50, 0.30, 0.20


def expertise(n: np.ndarray) -> np.ndarray:
    return np.log(n + 1) / np.log(MAX_N + 1)


def plot_expertise() -> None:
    n = np.arange(0, 50)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(n, np.clip(expertise(n), 0, 1), label="log(n+1)/log(21)")
    ax.axvline(MAX_N, color="grey", linestyle="--", label=f"MAX_N = {MAX_N}")
    ax.axhline(1.0, color="grey", linestyle=":")
    ax.set_xlabel("ratings in cuisine (n)")
    ax.set_ylabel("expertise score")
    ax.set_title("expertise: log-normalized rating count")
    ax.set_ylim(0, 1.1)
    ax.legend()
    add_description(ax,
        "expertise_score grows log-fast: the first few ratings\n"
        "matter more than the next fifteen combined. At MAX_N=20\n"
        "the score saturates at 1.0 — extra ratings beyond that\n"
        "add no signal. This soft cap keeps heavy raters from\n"
        "dominating over newcomers with strong, focused opinions.",
        loc="lower right",
    )
    save(fig, "01_expertise.png")


def plot_proximity_decay() -> None:
    """Per-cuisine contribution as a function of distance, holding expertise=1."""
    d = np.linspace(0, 1, 200)
    contribution = np.where(d < THRESHOLD, 1 - d, 0)

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(d, contribution, label="(1 − distance) · 𝟙[d < 0.6]")
    ax.axvline(THRESHOLD, color="red", linestyle="--", label=f"THRESHOLD = {THRESHOLD}")
    ax.set_xlabel("distance to adjacent cuisine")
    ax.set_ylabel("contribution per cuisine (expertise=1)")
    ax.set_title("proximity: distance decay with hard threshold")
    ax.legend()
    add_description(ax,
        "Expertise in a nearby cuisine partially transfers here.\n"
        "Contribution decays linearly with distance and cuts off\n"
        "hard at THRESHOLD=0.6 — cuisines beyond that count for\n"
        "nothing, even with extensive experience there. A Japanese\n"
        "expert gets some Korean credit; a French expert gets none.",
        loc="upper right",
    )
    save(fig, "02_proximity_decay.png")


def plot_credibility_surface() -> None:
    """Credibility as a function of expertise and alignment, fixed proximity."""
    e = np.linspace(0, 1, 100)
    a = np.linspace(0, 1, 100)
    E, A = np.meshgrid(e, a)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    for ax, prox in zip(axes, [0.0, 0.5]):
        w = np.clip(W_ALIGN * A + W_EXP * E + W_PROX * prox, 0, 1)
        c = ax.contourf(E, A, w, levels=20, cmap="viridis")
        ax.set_xlabel("expertise")
        ax.set_ylabel("alignment")
        ax.set_title(f"credibility surface (proximity = {prox})")
        fig.colorbar(c, ax=ax, label="credibility w")

    fig.suptitle(
        f"w = clamp({W_ALIGN}·alignment + {W_EXP}·expertise + {W_PROX}·proximity, 0, 1)"
    )
    add_description(axes[0],
        "Credibility is a weighted average of three signals.\n"
        "Alignment (y-axis): how closely this user agrees with\n"
        "trusted sources on restaurants they've both rated.\n"
        "Expertise (x-axis): how many restaurants in this cuisine\n"
        "they've rated. High credibility requires both — expertise\n"
        "without alignment, or alignment without experience, caps out.",
        loc="lower left",
    )
    save(fig, "03_credibility_surface.png")


def plot_alignment_redistribution() -> None:
    """When alignment is unavailable, α's weight redistributes onto β,γ."""
    e = np.linspace(0, 1, 100)
    fig, ax = plt.subplots(figsize=(7, 4))

    for prox in [0.0, 0.25, 0.5, 1.0]:
        # redistributed: w = (β·e + γ·p) / (β + γ)
        w = (W_EXP * e + W_PROX * prox) / (W_EXP + W_PROX)
        ax.plot(e, w, label=f"proximity = {prox}")

    ax.set_xlabel("expertise")
    ax.set_ylabel("credibility (alignment unavailable)")
    ax.set_title("fallback when overlap < 3 trusted ratings\nα's weight redistributes onto β, γ")
    ax.set_ylim(0, 1.05)
    ax.legend()
    add_description(ax,
        "When a user has rated fewer than 3 restaurants that\n"
        "trusted sources also rated, alignment can't be computed.\n"
        "Rather than treating the missing 0.50 weight as zero,\n"
        "it redistributes to expertise and proximity proportionally\n"
        "so the score stays in [0,1]. A brand-new user with no\n"
        "overlap is scored purely on experience and adjacency.",
        loc="lower right",
    )
    save(fig, "04_alignment_redistribution.png")


def main() -> None:
    plot_expertise()
    plot_proximity_decay()
    plot_credibility_surface()
    plot_alignment_redistribution()


if __name__ == "__main__":
    main()
