from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("football", broker=settings.REDIS_URL, backend=settings.REDIS_URL,
                    include=["app.tasks.scrape_tasks"])

celery_app.conf.update(
    timezone="UTC",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "check-new-posts-every-5-min": {
            "task": "tasks.check_new_posts",
            "schedule": 300.0,
            "options": {"expires": 240},  # drop stale runs if the worker was busy
        }
    },
)