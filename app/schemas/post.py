from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shortcode: str
    url: str
    kind: str
    media_type: str | None = None
    title: str | None = None
    caption: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    image_paths: list[str] | None = None
    video_paths: list[str] | None = None
    duration: float | None = None
    posted_at: datetime | None = None