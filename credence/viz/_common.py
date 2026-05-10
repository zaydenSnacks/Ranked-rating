from pathlib import Path

import matplotlib.pyplot as plt

OUTPUT = Path(__file__).parent / "output"
OUTPUT.mkdir(exist_ok=True)

_LOCS = {
    "lower right": (0.98, 0.03, "right", "bottom"),
    "lower left":  (0.02, 0.03, "left",  "bottom"),
    "upper right": (0.98, 0.97, "right", "top"),
    "upper left":  (0.02, 0.97, "left",  "top"),
}


def add_description(ax: plt.Axes, text: str, loc: str = "lower right") -> None:
    """Place a plain-language description box inside the axes."""
    x, y, ha, va = _LOCS[loc]
    ax.text(
        x, y, text,
        transform=ax.transAxes,
        fontsize=7.5,
        ha=ha, va=va,
        linespacing=1.5,
        bbox=dict(boxstyle="round,pad=0.5", facecolor="white", edgecolor="#bbbbbb", alpha=0.92),
        zorder=10,
    )


def save(fig: plt.Figure, name: str) -> Path:
    path = OUTPUT / name
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path
