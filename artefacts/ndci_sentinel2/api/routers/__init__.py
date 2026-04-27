from .water_quality import router as water_quality_router
from .tiles import router as tiles_router
from .predictions import router as predictions_router
from .workers import router as workers_router
from .notifications import router as notifications_router
from .analytics import router as analytics_router

__all__ = [
    "water_quality_router",
    "tiles_router",
    "predictions_router",
    "workers_router",
    "notifications_router",
    "analytics_router",
]
