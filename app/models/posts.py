from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Text
from sqlalchemy import JSON 
from sqlmodel import Field, SQLModel

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Post(SQLModel, table=True):
    __tablename__ = "instagram_posts"

    id: int | None = Field(default=None, primary_key=True)
    shortcode: str = Field(unique=True, index=True, max_length=32)
    url: str
    status: str = Field(default="pending", index=True)  # pending | done | failed

    title: str | None = None
    caption: str | None = Field(default=None, sa_column=Column(Text))
    video_path: str | None = None
    thumbnail_path: str | None = None
    duration: float | None = None
    error: str | None = Field(default=None, sa_column=Column(Text))

    kind: str = Field(default="reel", max_length=10)      # reel | post (from the URL)
    media_type: str | None = Field(default=None)           # video | image | gallery
    image_paths: list[str] | None = Field(default=None, sa_column=Column(JSON))
    video_paths: list[str] | None = Field(default=None, sa_column=Column(JSON))

    slides: list[dict] | None = Field(default=None, sa_column=Column(JSON))

    title_tk: str | None = None
    caption_tk: str | None = Field(default=None, sa_column=Column(Text))
    tk_attempts: int = Field(default=0, sa_column_kwargs={"server_default": "0"})
    
    posted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    created_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(default_factory=utcnow, sa_column=Column(DateTime(timezone=True)))

def post_url(shortcode: str, kind: str) -> str:
    return f"https://www.instagram.com/{'reel' if kind == 'reel' else 'p'}/{shortcode}/"