from fastapi import APIRouter
from app.router.api.posts import router as posts_router

api_router = APIRouter()

routers = [
    posts_router,
]

for router in routers:
    api_router.include_router(router)
