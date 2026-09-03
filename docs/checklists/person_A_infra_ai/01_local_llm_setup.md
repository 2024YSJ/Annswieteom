# A-1. 로컬 LLM 서버 준비 (Ollama 설치 및 모델 확정)

근거: 명세서 3절, 4절(6번 항목), 10-3절
선행 조건: 없음 (가장 먼저 시작 가능)
브랜치: 없음 — 로컬 설치·모델 다운로드일 뿐 저장소에 반영될 코드가 없다
시점: 1주차

> **개념부터**: Ollama는 "AI 모델에게 질문을 보내면 답을 준다"는 역할을 하는 프로그램으로, 설치만 하면 백그라운드에서 계속 켜져 있는 서버가 된다. 지금은 아직 외부에 노출하지 않고, 당신의 PC 안에서만 테스트한다.

## 1. 설치

- [x] [ollama.com/download/windows](https://ollama.com/download/windows)에서 설치 파일 다운로드 및 실행
- [x] 설치 완료 후 작업 표시줄에 Ollama 아이콘이 떠 있는지 확인 (자동으로 백그라운드 실행됨 — 따로 실행할 필요 없음)
- [x] PowerShell에서 확인: `ollama --version`
- [x] 브라우저 주소창에 `http://localhost:11434` 입력 → "Ollama is running" 문구 확인

## 2. 후보 모델 다운로드

- [x] EXAONE 3.5 7.8B-Instruct 다운로드: `ollama pull exaone3.5:7.8b`
- [x] Qwen2.5 14B-Instruct 다운로드: `ollama pull qwen2.5:14b` (실제 태그명은 Ollama 라이브러리에서 확인)
- [x] 각 모델은 4비트 양자화(GGUF Q4_K_M) 버전을 기본으로 사용 (Ollama 기본 태그가 보통 이에 해당 — 태그 상세 확인)
- [x] 다운로드 완료 후 `ollama list`로 두 모델이 모두 보이는지 확인

## 3. 모델 비교 테스트

- [x] `ollama run exaone3.5:7.8b`로 실행해 실제 인터뷰에서 나올 법한 질문 샘플(예: "구직 공백기에 아르바이트를 했다는 사실을 바탕으로 한 문장짜리 초안을 만들어줘") 몇 개를 입력해보고 응답 품질·속도 확인
- [x] 동일 질문을 `ollama run qwen2.5:14b`에도 입력해 비교
- [x] 비교 기준: (1) 한국어 자연스러움, (2) 응답 속도(4090에서 체감), (3) 지시사항 준수(JSON 형식 출력 요청 시 실제로 JSON만 내놓는지) — devlog([02_llm_adapter_layer.md](../../devlog/PersonA/02_llm_adapter_layer.md)) 참고: `/api/generate`로는 두 모델 다 JSON 스키마를 못 지켜서 `/api/chat`으로 전환
- [x] 팀과 상의해 최종 모델 하나 확정, `backend/.env`의 `LOCAL_LLM_MODEL_NAME`에 기록할 값 결정 → `qwen2.5:14b` 확정 (커밋 `501305f`)

## 4. 임베딩 모델도 함께 준비 (11절 선행 작업)

- [x] `ollama pull bge-m3` — 이후 [03_embedding_pipeline.md](03_embedding_pipeline.md)에서 사용

## 검증 기준

- [x] `http://localhost:11434`가 정상 응답한다
- [x] `ollama list`에 최종 확정된 LLM 모델과 `bge-m3`가 모두 보인다
- [x] 확정된 모델명을 B에게 공유해 `.env.example`의 `LOCAL_LLM_MODEL_NAME` 예시값을 갱신하도록 한다 → `.env.example`에 `qwen2.5:14b` 반영됨
