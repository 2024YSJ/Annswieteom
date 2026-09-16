from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.coverage import router as coverage_router
from app.api.demo import router as demo_router
from app.api.document import router as document_router
from app.api.feed import router as feed_router
from app.api.health import router as health_router
from app.api.interview import router as interview_router
from app.api.job_search import router as job_search_router
from app.api.profile import router as profile_router
from app.api.records import router as records_router
from app.api.sessions import router as sessions_router
from app.api.trust import global_router as trust_global_router, session_router as trust_session_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(profile_router)
api_router.include_router(feed_router)
api_router.include_router(sessions_router)
api_router.include_router(interview_router)
api_router.include_router(records_router)
api_router.include_router(document_router)
api_router.include_router(coverage_router)
api_router.include_router(job_search_router)
api_router.include_router(trust_session_router)
api_router.include_router(trust_global_router)
api_router.include_router(demo_router)

__all__ = ["api_router"]
