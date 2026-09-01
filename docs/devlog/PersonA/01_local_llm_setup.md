# A-1. 로컬 LLM 서버 준비 devlog

체크리스트: `docs/checklists/person_A_infra_ai/01_local_llm_setup.md`
브랜치: 없음 (로컬 설치)
날짜: 2026-09-01
상태: 완료

## 완료 항목

- [x] Ollama 설치 확인 (`ollama version is 0.30.6`)
- [x] `ollama serve` 백그라운드 실행 → `http://localhost:11434` 정상 응답
- [x] `exaone3.5:latest` (= 7.8B Q4_K_M, 4.8GB) — 이미 설치돼 있었음
- [x] `qwen2.5:14b` (9.0GB) 다운로드 완료
- [x] `bge-m3` 임베딩 모델 다운로드 완료
- [x] 모델 비교 테스트 실행
- [x] **최종 모델 확정: `qwen2.5:14b`**

## 모델 비교 결과

테스트 프롬프트: "편의점 아르바이트 주 5일, 하루 6시간 — frequency 초안 한 문장"

| 항목 | EXAONE 3.5 7.8B | **Qwen2.5 14B** |
|---|---|---|
| 응답 시간 | ~5.5초 | **~4.0초** |
| 한국어 자연스러움 | 자연스러우나 장황 | **자연스럽고 간결** |
| JSON 스키마 준수 | **실패** — `based_on`에 `"specific_learning_effort"` 같은 임의 값 생성 | **통과** — `"generic_pattern"` 정확히 출력 |
| 사실 충실도 | 입력에 없는 수치 추가 (hallucination 위험) | 입력 사실만 충실히 반영 |

**선택 이유**: JSON 스키마 준수가 정직성 가드레일 파이프라인의 핵심 요건이므로 Qwen 선택.

## 테스트 과정에서 발견한 사항

- Ollama `/api/generate` (flat prompt) 방식은 두 모델 모두 혼란스러워함
- `/api/chat` (system + user 메시지 분리) 방식에서 품질이 대폭 향상됨
- → `local_ollama.py`를 `/api/generate` → `/api/chat`으로 수정 (`501305f` 커밋)
- PowerShell 콘솔 기본 인코딩이 cp949라 한글 출력이 깨짐 → `[Console]::OutputEncoding = UTF8` 설정 필요

## B에게 공유할 값

```
LOCAL_LLM_MODEL_NAME=qwen2.5:14b
```

## 현재 Ollama 모델 목록

```
NAME                  SIZE
qwen2.5:14b           9.0 GB
exaone3.5:latest      4.8 GB
bge-m3                (임베딩용)
```
