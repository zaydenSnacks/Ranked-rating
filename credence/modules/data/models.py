from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class User(Base):
    __tablename__ = "users"

    id:         Mapped[int] = mapped_column(Integer, primary_key=True)
    name:       Mapped[str] = mapped_column(String,  nullable=False)
    email:      Mapped[str] = mapped_column(String,  nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String,  nullable=False)


class Cuisine(Base):
    __tablename__ = "cuisines"

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True)
    name:        Mapped[str]           = mapped_column(String,  nullable=False, unique=True)
    description: Mapped[str | None]    = mapped_column(String)


class CuisineDistance(Base):
    __tablename__ = "cuisine_distances"

    cuisine_a_id: Mapped[int]   = mapped_column(Integer, ForeignKey("cuisines.id"), primary_key=True)
    cuisine_b_id: Mapped[int]   = mapped_column(Integer, ForeignKey("cuisines.id"), primary_key=True)
    distance:     Mapped[float] = mapped_column(Float,   nullable=False)


class Restaurant(Base):
    __tablename__ = "restaurants"

    id:         Mapped[int]        = mapped_column(Integer, primary_key=True)
    name:       Mapped[str]        = mapped_column(String,  nullable=False)
    cuisine_id: Mapped[int]        = mapped_column(Integer, ForeignKey("cuisines.id"), nullable=False)
    location:   Mapped[str | None] = mapped_column(String)
    created_at: Mapped[str]        = mapped_column(String,  nullable=False)


class TrustedSource(Base):
    __tablename__ = "trusted_sources"

    id:       Mapped[int]        = mapped_column(Integer, primary_key=True)
    user_id:  Mapped[int]        = mapped_column(Integer, ForeignKey("users.id"), nullable=False, unique=True)
    added_at: Mapped[str]        = mapped_column(String,  nullable=False)
    notes:    Mapped[str | None] = mapped_column(String)


class RatingEvent(Base):
    __tablename__ = "rating_events"

    id:            Mapped[int]   = mapped_column(Integer, primary_key=True)
    user_id:       Mapped[int]   = mapped_column(Integer, ForeignKey("users.id"),       nullable=False)
    restaurant_id: Mapped[int]   = mapped_column(Integer, ForeignKey("restaurants.id"), nullable=False)
    score:         Mapped[float] = mapped_column(Float,   nullable=False)
    created_at:    Mapped[str]   = mapped_column(String,  nullable=False)


class UserCredibility(Base):
    __tablename__ = "user_credibility"

    user_id:           Mapped[int]   = mapped_column(Integer, ForeignKey("users.id"),    primary_key=True)
    cuisine_id:        Mapped[int]   = mapped_column(Integer, ForeignKey("cuisines.id"), primary_key=True)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    rating_deviation:  Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    volatility:        Mapped[float] = mapped_column(Float, nullable=False, default=0.06)
    last_updated:      Mapped[str]   = mapped_column(String, nullable=False)


class CredibilityHistory(Base):
    __tablename__ = "credibility_history"

    id:                Mapped[int]   = mapped_column(Integer, primary_key=True)
    user_id:           Mapped[int]   = mapped_column(Integer, ForeignKey("users.id"),    nullable=False)
    cuisine_id:        Mapped[int]   = mapped_column(Integer, ForeignKey("cuisines.id"), nullable=False)
    credibility_score: Mapped[float] = mapped_column(Float, nullable=False)
    rating_deviation:  Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at:       Mapped[str]   = mapped_column(String, nullable=False)


class Cluster(Base):
    __tablename__ = "clusters"

    id:              Mapped[int]        = mapped_column(Integer, primary_key=True)
    cuisine_id:      Mapped[int]        = mapped_column(Integer, ForeignKey("cuisines.id"), nullable=False, index=True)
    label:           Mapped[str | None] = mapped_column(String)
    coherence_score: Mapped[float]      = mapped_column(Float,   nullable=False, default=0.0)
    member_count:    Mapped[int]        = mapped_column(Integer, nullable=False, default=0)
    created_at:      Mapped[str]        = mapped_column(String,  nullable=False)


class UserClusterAssignment(Base):
    __tablename__ = "user_cluster_assignments"

    user_id:     Mapped[int]   = mapped_column(Integer, ForeignKey("users.id"),    primary_key=True)
    cuisine_id:  Mapped[int]   = mapped_column(Integer, ForeignKey("cuisines.id"), primary_key=True)
    cluster_id:  Mapped[int]   = mapped_column(Integer, ForeignKey("clusters.id"), nullable=False, index=True)
    confidence:  Mapped[float] = mapped_column(Float,   nullable=False)
    assigned_at: Mapped[str]   = mapped_column(String,  nullable=False)


class ClusterRestaurantScore(Base):
    __tablename__ = "cluster_restaurant_scores"

    cluster_id:    Mapped[int]   = mapped_column(Integer, ForeignKey("clusters.id"),    primary_key=True)
    restaurant_id: Mapped[int]   = mapped_column(Integer, ForeignKey("restaurants.id"), primary_key=True, index=True)
    consensus:     Mapped[float] = mapped_column(Float,   nullable=False)
    rater_count:   Mapped[int]   = mapped_column(Integer, nullable=False)
    last_updated:  Mapped[str]   = mapped_column(String,  nullable=False)
