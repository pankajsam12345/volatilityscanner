from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery("volscanner", broker=settings.redis_url, backend=settings.redis_url, include=["app.tasks.jobs"])
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "refresh-market-snapshots": {"task": "app.tasks.jobs.refresh_all_snapshots", "schedule": 300.0},
    "recompute-opportunities": {"task": "app.tasks.jobs.recompute_all_opportunities", "schedule": 300.0},
    "check-alerts": {"task": "app.tasks.jobs.check_alerts", "schedule": settings.alert_check_interval_seconds},
}
