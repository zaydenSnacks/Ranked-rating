"""Phase-1 credibility component plots.

Mirrors modules/credibility/{expertise,proximity,score}.py. The math is
re-implemented in numpy here on purpose — viz/ should not import from
modules/, so plots stay runnable without a database.
"""
from __future__ import annotations

import numpy as np
import matplotlib.pyplot as plt

from ._common import save

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
    save(fig, "04_alignment_redistribution.png")


def main() -> None:
    plot_expertise()
    plot_proximity_decay()
    plot_credibility_surface()
    plot_alignment_redistribution()


if __name__ == "__main__":
    main()
