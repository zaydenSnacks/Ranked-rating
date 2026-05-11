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
