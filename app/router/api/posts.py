from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException

from app.core.container import Container
from app.schemas.post import PostRead
from app.services.post_service import PostService

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=list[PostRead])
@inject
async def list_posts(
    limit: int = 20,
    offset: int = 0,
    service: PostService = Depends(Provide[Container.post_service]),
):
    return await service.list(limit, offset)


@router.get("/{shortcode}", response_model=PostRead)
@inject
async def get_post(shortcode: str, service: PostService = Depends(Provide[Container.post_service])):
    post = await service.get(shortcode)
    if not post:
        raise HTTPException(404, "Post not found")
    return post