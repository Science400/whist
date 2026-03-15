from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from backend.database import Base


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Show(Base):
    __tablename__ = "shows"

    id = Column(Integer, primary_key=True, index=True)
    tmdb_id = Column(Integer, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    poster_path = Column(String)
    status = Column(String, default="")           # legacy — use user_status
    user_status = Column(String)                  # airing | watching | finished | watchlist | abandoned
    type = Column(String, nullable=False)         # tv | movie
    added_at = Column(String, default=_utcnow)
    last_watched_at = Column(String)
    watch_pace = Column(String, default="binge")      # binge | fast | weekly
    first_air_date = Column(String)                   # YYYY-MM-DD from TMDB, or None
    watched = Column(Boolean, default=False)          # movies only: watched flag
    watched_at = Column(String)                       # movies only: ISO 8601 date

    episodes = relationship("Episode", back_populates="show")


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (
        UniqueConstraint("tmdb_show_id", "season_number", "episode_number"),
        # Composite index for the "seen in" subquery: WHERE watched=1 → tmdb_show_id
        Index("ix_episodes_watched_tmdb", "watched", "tmdb_show_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    show_id = Column(Integer, ForeignKey("shows.id"), nullable=False)
    tmdb_show_id = Column(Integer, nullable=False, index=True)
    season_number = Column(Integer, nullable=False)
    episode_number = Column(Integer, nullable=False)
    title = Column(String)
    air_date = Column(String)
    watched = Column(Boolean, default=False, nullable=False)
    watched_at = Column(String)

    show = relationship("Show", back_populates="episodes")


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, index=True)
    tmdb_id = Column(Integer, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    profile_path = Column(String)
    birthday = Column(String)                 # YYYY-MM-DD, nullable
    imdb_id = Column(String)
    credits_cached_at = Column(String)

    credits = relationship("PersonCredit", back_populates="person")


class PersonCredit(Base):
    __tablename__ = "person_credits"
    __table_args__ = (
        # Composite index for the "seen in" main query
        Index("ix_person_credits_person_show", "person_tmdb_id", "show_tmdb_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    person_tmdb_id = Column(Integer, ForeignKey("people.tmdb_id"), nullable=False)
    show_tmdb_id = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    character = Column(String)
    type = Column(String, nullable=False)         # tv | movie
    first_air_date = Column(String)               # YYYY-MM-DD or None

    person = relationship("Person", back_populates="credits")


class WatchHistory(Base):
    __tablename__ = "watch_history"
    __table_args__ = (
        Index("ix_watch_history_episode",
              "tmdb_show_id", "season_number", "episode_number"),
    )

    id             = Column(Integer, primary_key=True, index=True)
    tmdb_show_id   = Column(Integer, nullable=False)
    season_number  = Column(Integer, nullable=False)
    episode_number = Column(Integer, nullable=False)
    watched_at     = Column(String)  # YYYY-MM-DD or None


class EpisodeCredit(Base):
    __tablename__ = "episode_credits"
    __table_args__ = (
        Index("ix_episode_credits_person", "person_tmdb_id"),
        UniqueConstraint("person_tmdb_id", "show_tmdb_id", "season_number", "episode_number"),
    )

    id             = Column(Integer, primary_key=True, index=True)
    person_tmdb_id = Column(Integer, nullable=False)
    show_tmdb_id   = Column(Integer, nullable=False)
    season_number  = Column(Integer, nullable=False)
    episode_number = Column(Integer, nullable=False)
    character      = Column(String)


class ShowWiki(Base):
    __tablename__ = "show_wikis"

    id = Column(Integer, primary_key=True, index=True)
    show_tmdb_id = Column(Integer, nullable=False, index=True)
    label = Column(String, nullable=False)       # user-defined, e.g. "Memory Alpha"
    url = Column(String, nullable=False)         # show-level URL
    season_url_template = Column(String)         # optional, e.g. ".../Season_{season}"


class ShowCast(Base):
    __tablename__ = "show_cast"
    __table_args__ = (
        Index("ix_show_cast_show_person", "show_tmdb_id", "person_tmdb_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    show_tmdb_id = Column(Integer, nullable=False)
    person_tmdb_id = Column(Integer, nullable=False)
    character = Column(String)
    order = Column(Integer)
