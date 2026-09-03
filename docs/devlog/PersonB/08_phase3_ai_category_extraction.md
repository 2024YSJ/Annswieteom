# Phase 3. AI 카테고리 추출 devlog

관련 spec: [docs/specs/phase3_ai_category_extraction.md](../../specs/phase3_ai_category_extraction.md)
날짜: 2026-09-03

---

원래 마일스톤 체크리스트에는 없던 항목이라 대응하는 checklist 파일이 없다.

## 완료 항목

- `LLMProvider`에 `extract_categories` 능력 추가(`base.py`/`fallback.py`/`local_ollama.py`/`gemini_provider.py`), 새 프롬프트 `extract_categories.jinja`
- 새 `POST /sessions/{id}/categories/extract`(DB에 아무것도 안 씀, `CATEGORY_SELECT`에서만 호출 가능) + `CategoryInput`에 `custom_label` 추가해서 기존 `POST /categories`가 그대로 저장하도록 확장
- `CategorySection.tsx` 전면 교체 — 체크박스 8개 → 자유 텍스트 + AI 추출 + 편집 가능한 제안 목록
- 백엔드 테스트 4개 추가(`test_category_extraction.py`), `session-flow.spec.ts`를 새 흐름에 맞게 갱신
- 실 로컬 Ollama(`qwen2.5:14b`)로 "편의점 아르바이트 + 자격증 취득"이 섞인 자유 텍스트를 넣고 실제로 두 개의 서로 다른 카테고리로 정확히 분리 추출되는 것, 그 뒤 두 카테고리 각각의 인터뷰 루프와 문서 생성까지 전체 재확인

## 핵심 결정 사항과 이유

**추출은 한 번에(single-shot)로, DB에는 아무것도 안 씀.** 사용자에게 두 가지 선택지(한 번에 추출 / AI와 여러 턴 대화하며 점진적으로 좁히기)를 직접 물어봤고 한 번에 추출을 선택받았다 — 여러 턴 대화는 그 자체로 대화 기록/턴 상태를 새로 설계해야 하는 별도 규모의 작업이라 판단했기 때문. `POST /categories/extract`가 아무것도 저장하지 않는 것은 새로운 원칙이 아니라 이 프로젝트 전체를 관통하는 정직성 가드레일(`confirmed_facts`에만 확정된 사실이 들어감)을 카테고리 레벨에도 그대로 적용한 것뿐이다.

**`category_type` 8종 제약은 그대로 두고 `custom_label`만 활용.** `custom_label` 컬럼은 사실 Phase 1 이전부터 스키마에 있었지만 한 번도 채워진 적이 없었다 — 이번에 그 용도를 실제로 살렸다. 프론트엔드가 이미 어디서든 `custom_label ?? CATEGORY_LABELS[category_type]`로 표시하고 있었기 때문에(Phase 2 작업 때 이미 그렇게 짜여 있었음), 이 필드만 채워 넣으면 화면 전체에 자유로운 이름이 자연스럽게 반영됐다 — DB 마이그레이션도, 다른 컴포넌트 수정도 필요 없었다. Phase 2 devlog에서 이미 "CategorySection만 교체 가능하도록 분리해뒀다"고 남겨둔 설계가 실제로 그대로 맞아떨어진 것도 확인.

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 실 Ollama로 확인 중, "성과" 항목 하나가 `由于限制，最后一部分未翻译完整...` 같은 중국어 섞인 깨진 문장으로 나오고, 최종 문서에서 그 문장이 "⚠ 확인이 더 필요한 문장"으로 표시됨 | 로컬 모델(`qwen2.5:14b`)이 그 한 번의 생성에서 실제로 품질이 떨어지는 출력을 냄 — 코드 버그가 아니라 순수 모델 변동성 | 고칠 대상이 아님 — 오히려 기존 `consistency_check`(문장-근거 코사인 유사도) 가드레일이 의도대로 그 이상한 문장을 정확히 잡아내 사용자에게 "확인 필요"로 표시한 것 확인. **이번 확인의 부산물**: 정직성/일관성 가드레일이 실제 모델의 실제 저품질 출력에 대해서도 살아있게 작동한다는 걸 처음으로 실제 환경에서 목격 |

## 남은 작업

없음 — Phase 3 범위 전체 완료. 다음은 Phase 4(기록물 업로드를 채팅 입력창의 첨부 버튼으로 이동) — 착수 시 별도 spec 문서 작성 예정.
