import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import settings

# 로깅 설정이 없던 동안 app.* 로거의 info는 전부 버려졌다(루트 기본 레벨이 WARNING).
# 루트가 아니라 "app"만 여는 이유: 루트를 INFO로 올리면 httpx가 요청 URL을 INFO로
# 찍는데, 고용24 호출은 authKey를 쿼리스트링에 실어 보내서 키가 Render 로그에 남는다.
_app_logger = logging.getLogger("app")
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _app_logger.addHandler(_handler)
    _app_logger.setLevel(logging.INFO)
    _app_logger.propagate = False

app = FastAPI(title="Annswieteom API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allow_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
