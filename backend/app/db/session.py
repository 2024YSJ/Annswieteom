from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


def get_background_session_factory() -> async_sessionmaker:
    """응답 뒤에 도는 BackgroundTasks용 세션 팩토리 DI 훅.

    요청 세션(get_db)은 응답과 함께 닫히므로 백그라운드 작업은 자기 세션을 연다.
    AsyncSessionLocal을 직접 import하면 테스트의 get_db 오버라이드가 닿지 않아
    테스트 DB가 아닌 설정 DB로 붙는다 — 이 훅을 오버라이드하면 같은 DB를 쓴다.
    """
    return AsyncSessionLocal
