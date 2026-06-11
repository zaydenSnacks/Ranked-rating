import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="credence — credibility-weighted restaurant ratings")
console = Console()


def _session():
    from modules.data.db import Session
    return Session()


@app.command()
def init_db():
    """Create all tables (safe to re-run)."""
    from modules.data.db import Base, engine
    from modules.data import models  # noqa: F401 — registers all ORM classes with Base
    Base.metadata.create_all(engine)
    console.print("[green]✓[/green] tables created")


@app.command()
def seed():
    """Seed trusted sources with low rating_deviation."""
    from modules.credibility.seeds import seed_trusted_sources
    with _session() as s:
        count = seed_trusted_sources(s)
        s.commit()
    console.print(f"[green]✓[/green] {count} trusted-source credibility rows written")


@app.command()
def cluster():
    """Run k-means clustering across all cuisines (rebuilds all cluster state)."""
    from modules.clustering.discover import recluster_all
    from modules.data.models import Cuisine
    with _session() as s:
        results = recluster_all(s)
        names = {c.id: c.name for c in s.query(Cuisine)}
        s.commit()

    table = Table(title="clustering run", show_header=True)
    table.add_column("cuisine")
    table.add_column("users",     justify="right")
    table.add_column("clusters",  justify="right")
    table.add_column("planted",   justify="right")
    table.add_column("score rows", justify="right")
    for cuisine_id, stats in results.items():
        if stats is None:
            table.add_row(names[cuisine_id], "—", "—", "—", "—")
        else:
            table.add_row(
                names[cuisine_id], str(stats["users"]), str(stats["clusters"]),
                str(stats["planted"]), str(stats["score_rows"]),
            )
    console.print(table)


@app.command()
def user_clusters(
    user_id: int = typer.Argument(..., help="user ID"),
):
    """Show the user's cluster assignment per cuisine."""
    from sqlalchemy import select
    from modules.data.models import Cluster, Cuisine, User, UserClusterAssignment
    with _session() as s:
        user = s.get(User, user_id)
        if user is None:
            console.print(f"[red]user {user_id} not found[/red]"); raise typer.Exit(1)

        rows = s.execute(
            select(Cuisine.name, Cluster.label, UserClusterAssignment.confidence,
                   Cluster.coherence_score, Cluster.member_count)
            .join(Cluster, UserClusterAssignment.cluster_id == Cluster.id)
            .join(Cuisine, UserClusterAssignment.cuisine_id == Cuisine.id)
            .where(UserClusterAssignment.user_id == user_id)
            .order_by(Cuisine.name)
        ).all()
        user_name = user.name

    if not rows:
        console.print(f"{user_name} has no cluster assignments — run [bold]cluster[/bold] first")
        return

    table = Table(title=f"{user_name}  (id={user_id})", show_header=True)
    table.add_column("cuisine")
    table.add_column("cluster")
    table.add_column("confidence", justify="right")
    table.add_column("coherence",  justify="right")
    table.add_column("members",    justify="right")
    for r in rows:
        table.add_row(r.name, r.label, f"{r.confidence:.2f}", f"{r.coherence_score:.2f}", str(r.member_count))
    console.print(table)


@app.command()
def import_yelp(
    path:             str = typer.Option(..., "--path", help="directory containing the Yelp Academic Dataset JSON files"),
    city:             str = typer.Option(None, help="only import businesses in this city"),
    max_reviews:      int = typer.Option(None, help="cap on qualifying reviews considered (for iteration)"),
    min_user_reviews: int = typer.Option(3, help="drop users with fewer qualifying reviews than this"),
):
    """Import the Yelp Academic Dataset (one-shot; see DECISIONS.md)."""
    from pathlib import Path
    from modules.data.importers.yelp import BUSINESS_FILE, REVIEW_FILE, import_yelp as run_import

    base = Path(path)
    business_path, review_path = base / BUSINESS_FILE, base / REVIEW_FILE
    for p in (business_path, review_path):
        if not p.exists():
            console.print(f"[red]{p} not found[/red]"); raise typer.Exit(1)

    with _session() as s:
        try:
            stats = run_import(
                s, business_path, review_path,
                city=city, max_reviews=max_reviews, min_user_reviews=min_user_reviews,
            )
        except (RuntimeError, ValueError) as e:
            console.print(f"[red]{e}[/red]"); raise typer.Exit(1)
        s.commit()

    console.print(
        f"[green]✓[/green] imported {stats['restaurants']} restaurants, "
        f"{stats['users']} users, {stats['events']} rating events"
    )
    skipped = {k: v for k, v in stats.items() if k.startswith("skipped_") and v}
    if skipped:
        console.print("  skipped: " + ", ".join(f"{k[8:]}={v}" for k, v in skipped.items()))


@app.command()
def rate(
    user_id:       int   = typer.Argument(..., help="user ID"),
    restaurant_id: int   = typer.Argument(..., help="restaurant ID"),
    score:         float = typer.Argument(..., help="score 1–10"),
):
    """Submit a rating and update credibility."""
    from modules.actions import submit_rating
    from modules.data.models import UserCredibility, Restaurant, User
    with _session() as s:
        user       = s.get(User, user_id)
        restaurant = s.get(Restaurant, restaurant_id)
        if user is None:
            console.print(f"[red]user {user_id} not found[/red]"); raise typer.Exit(1)
        if restaurant is None:
            console.print(f"[red]restaurant {restaurant_id} not found[/red]"); raise typer.Exit(1)

        event      = submit_rating(s, user_id, restaurant_id, score)
        rec        = s.get(UserCredibility, (user_id, restaurant.cuisine_id))
        event_id   = event.id
        user_name  = user.name
        cuisine_id = restaurant.cuisine_id
        cred_line  = (
            f"score={rec.credibility_score:.3f}  RD={rec.rating_deviation:.3f}  vol={rec.volatility:.3f}"
            if rec else None
        )
        s.commit()

    console.print(f"[green]✓[/green] rating #{event_id} saved")
    if cred_line:
        console.print(f"  credibility ({user_name}, cuisine {cuisine_id}): {cred_line}")


@app.command()
def score(
    restaurant_id: int = typer.Argument(..., help="restaurant ID"),
):
    """Print the credibility-weighted score for a restaurant."""
    from modules.ranking.ranking import restaurant_score
    from modules.data.models import Restaurant, RatingEvent, UserCredibility
    from sqlalchemy import select, func
    with _session() as s:
        restaurant = s.get(Restaurant, restaurant_id)
        if restaurant is None:
            console.print(f"[red]restaurant {restaurant_id} not found[/red]"); raise typer.Exit(1)

        weighted = restaurant_score(s, restaurant_id)

        rows = s.execute(
            select(RatingEvent.user_id, RatingEvent.score)
            .where(RatingEvent.restaurant_id == restaurant_id)
        ).all()
        rating_count = len(rows)

        table = Table(title=f"{restaurant.name}  (id={restaurant_id})", show_header=True)
        table.add_column("user_id", justify="right")
        table.add_column("score",   justify="right")
        table.add_column("credibility", justify="right")
        table.add_column("RD",      justify="right")

        for row in rows:
            rec = s.get(UserCredibility, (row.user_id, restaurant.cuisine_id))
            cs  = f"{rec.credibility_score:.3f}" if rec else "—"
            rd  = f"{rec.rating_deviation:.3f}"  if rec else "—"
            table.add_row(str(row.user_id), f"{row.score:.1f}", cs, rd)

    console.print(table)
    console.print(f"\nweighted score: [bold]{weighted:.3f}[/bold]  ({rating_count} ratings)")


if __name__ == "__main__":
    app()
