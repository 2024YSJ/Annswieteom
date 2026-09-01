# A-1. 로컬 LLM 서버 준비 devlog

체크리스트: `docs/checklists/person_A_infra_ai/01_local_llm_setup.md`
날짜: 2026-09-01

---

## Ollama 실행

Ollama는 설치 후 백그라운드 서비스로 자동 등록되지만, 이 PC에서는 자동 시작이 꺼져 있었다. PowerShell에서 `Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden`으로 백그라운드 실행했고, `http://localhost:11434`가 `"Ollama is running"`을 반환하면 정상 상태다.

## 모델 다운로드

`exaone3.5:latest`는 이미 설치돼 있었다. `ollama show exaone3.5:latest`로 확인하니 `parameters: 7.8B`, `quantization: Q4_K_M`으로, 체크리스트가 요구하는 7.8B Q4_K_M 버전이 맞다. `qwen2.5:14b`(9.0GB)와 임베딩용 `bge-m3`는 `ollama pull`로 추가 다운로드했다.

## 모델 비교 테스트

두 모델을 비교하기 위해 Ollama의 HTTP API를 직접 호출했다. 처음엔 `/api/generate`(flat prompt)를 썼는데 두 모델 모두 JSON 형식을 지키지 못하고 엉뚱한 언어로 응답했다. `/api/chat` 엔드포인트로 바꾸고 system 메시지에 "한국어로, JSON만 출력"을 명시하자 품질이 크게 개선됐다.

같은 프롬프트("편의점 아르바이트 주 5일 하루 6시간 — frequency 초안 한 문장")로 두 모델의 응답을 비교했다:

- **EXAONE 3.5 7.8B**: 5.4초, 한국어 자연스러움. 그러나 `based_on` 필드에 `"specific_learning_effort"` 같이 스키마에 없는 임의 값을 생성했다. 두 번 모두 같은 패턴으로 실패했다.
- **Qwen2.5 14B**: 4.0초로 더 빠르고, `"based_on": "generic_pattern"`을 정확히 출력했다. 입력에 없는 수치나 추가 사실을 만들어내지 않았다.

JSON 스키마 준수는 정직성 가드레일 파이프라인에서 필수 조건이다. `based_on` 값이 임의 문자열이면 파이프라인이 이를 파싱할 수 없어 오류가 난다. 이 기준에서 **Qwen2.5 14B로 확정**했다.

## 확인된 모델 목록

```
NAME                  SIZE     비고
qwen2.5:14b           9.0 GB   확정 LLM
exaone3.5:latest      4.8 GB   비교 대상 (미사용)
bge-m3                          임베딩용 (A-3에서 사용)
```

## B에게 공유

`LOCAL_LLM_MODEL_NAME=qwen2.5:14b`를 B의 `.env`에 반영해야 한다.
