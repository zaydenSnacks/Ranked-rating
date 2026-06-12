"""Entry point — regenerate every plot in viz/output/.

Usage (from credence/):
    python -m viz.generate
"""
from . import clustering, components, dynamic, ranking
from ._common import OUTPUT


def main() -> None:
    components.main()
    dynamic.main()
    ranking.main()
    clustering.main()
    print(f"wrote plots to {OUTPUT}")


if __name__ == "__main__":
    main()
