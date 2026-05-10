from pathlib import Path

import matplotlib.pyplot as plt

OUTPUT = Path(__file__).parent / "output"
OUTPUT.mkdir(exist_ok=True)


def save(fig: plt.Figure, name: str) -> Path:
    path = OUTPUT / name
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path
