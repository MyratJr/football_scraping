from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shortcode: str
    url: str
    kind: str
    media_type: str | None = None
    title: str | None = None            # Turkmen when available, otherwise the English original
    caption: str | None = None
    title_en: str | None = None         # the original English text
    caption_en: str | None = None
    title_tk: str | None = Field(default=None, exclude=True)
    caption_tk: str | None = Field(default=None, exclude=True)
    video_path: str | None = None
    video_paths: list[str] | None = None
    thumbnail_path: str | None = None
    slides: list[dict] | None = None
    image_paths: list[str] | None = None
    duration: float | None = None
    posted_at: datetime | None = None

    @model_validator(mode="after")
    def _prefer_turkmen(self):
        self.title_en, self.caption_en = self.title, self.caption
        self.title = self.title_tk or self.title
        self.caption = self.caption_tk or self.caption
        return self