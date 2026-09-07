# 질문 구체화 강화 — 고정/AI 질문 예산 분리 + 규칙 기반 백업

사용자 피드백: "문서를 보며 필기했다", "기획 및 개발을 맡았다" 같은 폭넓은 답변에 대해
AI가 더 집요하게 파고들어야 하고, 완성본이 STAR 형식을 실제로 따르는지 의문.

## 문제 진단

인터뷰 깊이는 서로 독립된 LLM 판단 세 개(`judge_drilldown`, `judge_sufficiency`,
`followup_question`)가 각자 결정하는데, 전부 `ActivityCategory.questions_asked` 하나(고정+AI
합산, 상한 6)를 공유했다. `project`/`freelance`/`other`처럼 고정 질문이 5개인 카테고리는
AI가 파고들 여지가 사실상 1턴뿐이었고, 예산이 바닥나면 **"성과/결과"(STAR의 Result에
해당하는 마지막 고정 질문)가 아직 안 나왔어도 강제로 다음 카테고리로 넘어가 버렸다** — STAR
완성도를 의심하게 만든 근본 원인.

## 구현

- **예산 분리(계획 B)**: `ActivityCategory.questions_asked`는 이제 고정 질문 전용(상한 없음
  — 카테고리 유형별 고정 목록 자체가 짧고 유한하므로 굳이 상한이 필요 없다), 새 컬럼
  `followup_questions_asked`가 AI 추가(드릴다운+후속) 질문 전용이며
  `interview_orchestrator.MAX_FOLLOWUP_QUESTIONS_PER_CATEGORY = 3`으로만 상한을 건다
  (마이그레이션 `c9d0e1f2a3b4`). `interview_confirm`의 분기를 다시 짜서: 고정 질문이 남아있는
  동안은 AI 예산과 무관하게 **무조건** 다음 고정 질문으로 진행하고(단, 남은 AI 예산이 있을
  때만 드릴다운 판단을 시도), 고정 질문을 다 쓴 뒤에는 AI 예산이 남아있을 때만
  `judge_sufficiency`를 호출한다 — 예산이 없으면 호출 자체를 생략하고 바로 다음 카테고리로.
  결과적으로 STAR의 Result에 해당하는 마지막 고정 질문은 AI가 아무리 자주 끼어들어도 절대
  건너뛰지 않는다(계획 A가 요구했던 "Result 없이 카테고리가 끝나는" 최악의 경우를, 별도의
  강제 규칙 없이 이 재설계만으로 구조적으로 없앴다).
- **규칙 기반 백업(계획 C)**: `judge_drilldown`이 `AllProvidersFailedError`로 아예 호출
  불가능할 때(로컬 dev처럼 폴백 provider도 플레이스홀더 키라 못 살아나는 상황), 방금 확정된
  답변의 글자 수가 20자 미만이면 LLM 호출 없이 정형화된 구체화 질문("조금 더 구체적으로
  말씀해주시겠어요?...")을 하나 끼워넣는다(`_is_vague_answer`, `_GENERIC_PROBE_QUESTION`).
  정교한 판단은 아니지만, 모든 provider가 막힌 상황에서도 최소한의 구체화는 보장한다.
- **계획 A(STAR 커버리지 강제)**: 별도 코드 없이 위 예산 분리의 자연스러운 결과로 이미
  충족된다 — 카테고리 유형별 고정 질문 세트(`interview_question_bank.py`)가 이미 전부
  achievement/outcome 질문을 하나씩 포함하고, 이제 그게 예산 때문에 스킵되는 경로가 없다.

## 검증

- `test_interview.py`: 기존 두 테스트의 스테일해진 monkeypatch(`MAX_QUESTIONS_PER_CATEGORY`를
  8로 올려 총 예산 문제를 피해가던 것) 제거 — 새 설계에서는 애초에 필요 없다. 낡은
  `test_max_questions_per_category_forces_advance_even_with_llm_never_satisfied`(고정 질문이
  안 나왔어도 예산 때문에 끝나야 한다고 주장하던, 이제는 틀린 전제의 테스트)를
  `test_followup_budget_caps_ai_questions_but_never_skips_a_fixed_one`로 교체 — LLM이 답변마다
  드릴다운을 원해도 고정 질문 4개는 전부 나오고, AI 질문은 정확히 예산만큼만(3개) 끼어드는지
  확인. 새 회귀 테스트 2개(`test_drilldown_heuristic_backup_probes_a_vague_answer_when_all_llm_providers_fail`,
  `..._does_not_probe_a_detailed_answer`)로 규칙 기반 백업이 짧은 답변엔 반응하고 긴 답변엔
  과잉반응하지 않는지 확인. 백엔드 전체 162개 통과.
- 로컬 dev DB에 마이그레이션 적용, 실제 로컬 Ollama(`qwen2.5:3b-instruct`)로 라이브 스모크 —
  세션 생성부터 첫 고정 질문까지 크래시 없이 정상 동작 확인. 여러 턴에 걸쳐 같은 답변을
  반복 제출했을 때 모델이 실제로 관련 없는 질문에 대해 빈 후보 목록을 반환하는(억지로
  사실을 지어내지 않는) 것도 확인 — 정직성 가드레일이 여전히 잘 작동함.

## 남은 일 (계획 D — 아직 미착수)
- 프로덕션 모델(Gemini/14b 터널)로 실제 세션을 몇 개 완주시켜, 사람이 직접 STAR
  커버리지·구체성을 채점하는 실측 비교(적용 전/후)는 아직 하지 않았다 — 로컬 dev 환경은
  `GEMINI_API_KEY`가 플레이스홀더라 폴백이 안 되므로, 이 실측은 진짜 키가 있는 환경에서
  해야 한다.
- **로컬 개발 서버 재기동 필요**: 이번 변경으로 `activity_categories`에 컬럼이 추가됐다 —
  `--reload`로 떠 있던 기존 백엔드 프로세스(포트 8000, PID 26904)가 새 ORM 매핑을 못 받아들여
  카테고리 생성 시 `NotNullViolationError`로 500을 낸다(재현·확인함). 이 프로세스를 이
  세션에서 안전하게 재기동시키지 못해(taskkill/PowerShell 양쪽에서 PID를 찾지 못함 — WSL
  등 이 환경에서 안 보이는 프로세스 소유 관계로 추정) 그대로 두고, 별도 포트(8001)에 새
  프로세스를 띄워 검증한 뒤 정리했다. 사용자가 직접 기존 서버를 재시작해야 한다.
