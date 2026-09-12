"""Ollama 호스트(생성 + 임베딩)로 나가는 모든 요청이 공유하는 직렬화 게이트.

2026-09-12 검증에서 확인된 사실: Spark의 Ollama 러너는 슬롯이 1개뿐이고
(`--parallel 1`), 재적재 직후("cold") 1024토큰 넘는 첫 요청을 받으면 CUDA
illegal memory access로 죽는다(ollama/ollama#17434, 같은 GB10/sm_121 하드웨어에서
재현·확인됨). 이 게이트는 그 크래시 자체를 막지 못한다 — 근본 수정은 Spark에서
`OLLAMA_FLASH_ATTENTION=0`으로 해야 한다(운영 체크리스트 참고).

이 게이트가 줄이는 건 **실패 반경**이다. `/interview/answer`는 응답을 커밋한 뒤
백그라운드로 활동기간 추론·프로필 속성 추출을 예약하고(interview.py), 사용자는
응답을 받는 즉시 다음 요청을 보낼 수 있다 — FastAPI의 BackgroundTasks는 이후
요청과 동기화되지 않으므로, 실질적으로 같은 Ollama 러너에 여러 요청이 동시에
가 있게 된다. 러너가 그 순간 죽으면 그 전부가 함께 실패한다(실측: 순차 8.3% →
동시 3건 33.3%). 이 게이트로 우리 쪽 요청을 1개씩만 내보내면, 크래시 한 번이
죽이는 요청도 최대 1개로 줄어든다.

한계: 프로세스 전역이라 Render 인스턴스가 여러 개면 인스턴스 단위로만 막는다.
데모 규모(인스턴스 1개)에서는 충분하다.
"""
from __future__ import annotations

import asyncio

OLLAMA_GATE = asyncio.Semaphore(1)
