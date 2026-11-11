from dependency_injector import containers, providers

from app.core.config import get_settings
from app.core.database import Database
from app.repositories.post_repository import PostRepository
from app.services.post_service import PostService
from app.services.translation_service import TranslationService


settings = get_settings()
    

class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        modules=["app.router.api.posts"],  # strings, so there's no circular import
    )


    db = providers.Singleton(
        Database,
        db_url=settings.DB_URL,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        app_name=settings.APP_NAME,
    )

    post_repository = providers.Factory(
        PostRepository,
        session_factory=db.provided.session_factory,
    )

    post_service = providers.Factory(
        PostService,
        post_repository=post_repository,
    )
    translation_service = providers.Factory(TranslationService)