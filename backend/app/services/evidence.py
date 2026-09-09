from __future__ import annotations

from collections.abc import Iterable

#: 문장 하나가 무엇에 기대고 있는지의 등급. 문장별 근거 목록의 source_type에서
#: 파생되는 값이라 별도 컬럼으로 저장하지 않는다.
#:
#: - record_backed: 인용한 근거 중 최소 하나가 사용자의 실제 기록물(블로그·자격증·
#:   문서)에서 나왔다. 출처 URL과 게시일이 붙는 유일한 등급이고, 채용담당자
#:   입장에서 검증 가능한 유일한 등급이기도 하다.
#: - self_reported: 전부 본인 진술이다(user_confirmed/user_edited). 거짓이라는
#:   뜻이 아니라 "확인할 제3의 근거가 없다"는 뜻이다.
#: - unsupported: 인용한 확정 사실이 아예 없다. 정직성 가드레일상 나와서는 안
#:   되는 상태이고(문서 생성은 confirmed_facts만 입력으로 받는다), 나왔다면 근거가
#:   되던 사실이 나중에 삭제됐다는 신호다.
EVIDENCE_GRADES = ("record_backed", "self_reported", "unsupported")


def grade_for(source_types: Iterable[str]) -> str:
    types = list(source_types)
    if not types:
        return "unsupported"
    if "record_cited" in types:
        return "record_backed"
    return "self_reported"
