from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Football Scraper"
    DESCRIPTION: str = "Scrapes football reels from Instagram"
    VERSION: str = "0.1.0"

    DB_URL: str = "postgresql+asyncpg://postgres:63365663@localhost:5432/football"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False
    REDIS_URL: str = "redis://127.0.0.1:6380/0"

    # IG_PROFILE: str = "fabriziorom"
    # IG_PROFILE: str = "championsleague"
    IG_PROFILE: str = "433"
    IG_COOKIES_TXT: str = "secrets/instagram_cookies.txt"        # for yt-dlp
    IG_STORAGE_STATE: str = "secrets/instagram_state.json"       # for playwright
    MEDIA_DIR: str = "media"
    CORS_ORIGINS: str = "http://localhost:3000"

    FACE_FILTER_ENABLED: bool = True
    FACE_REFERENCE_DIR: str = "app/reference_faces"
    FACE_MATCH_THRESHOLD: float = 0.45   # cosine similarity, tune with the script below
    FACE_VIDEO_FRAMES: int = 12   
    IG_SCRAPE_LIMIT: int = 20

    FACE_MODEL_DIR: str = "models_cache/insightface"

    DEBUG: bool = False
    

    def get_cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]
    

@lru_cache
def get_settings() -> Settings:
    return Settings()