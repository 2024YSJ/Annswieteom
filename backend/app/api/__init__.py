from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.interview import router as interview_router
from app.api.records import router as records_router
from app.api.sessions import router as sessions_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(sessions_router)
api_router.include_router(interview_router)
api_router.include_router(records_router)

__all__ = ["api_router"]
