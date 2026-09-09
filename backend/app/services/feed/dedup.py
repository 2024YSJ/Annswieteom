from __future__ import annotations

import hashlib


def compute_dedup_key(
    source_key: str | None,
    title: str,
    subtitle: str,
    meta_lines: list[str],
) -> str:
    """같은 공고/정책을 다시 수집했을 때 같은 값이 나와야 하는 식별자.

    소스가 안정적인 id(또는 항목 고유 상세 URL)를 주면 그걸 쓰고, 없으면
    내용 해시로 대신한다. `k:`/`h:` 접두사를 붙여 두 방식을 섞어 저장해도
    서로 충돌하지 않게 한다.

    **해시 방식의 정직한 한계**: id 없는 카테고리(공채기업정보/구직자프로그램/
    강소기업/채용행사)는 소스가 문구를 한 줄만 고쳐도 새 항목으로 들어온다.
    반대로 키를 더 느슨하게(제목만 등) 잡으면 진짜 새 공고를 조용히 삼킨다.
    **중복 카드는 눈에 보이는 실패이고 누락은 안 보이는 실패**라, 보이는 쪽을
    택했다. 새로 들어온 행이 옛 행을 밀어내지 않도록 옛 행은 삭제가 아니라
    is_active=False로 내려간다(models/feed_item.py).

    워크넷 응답에는 채용행사의 `eventNo`, 공채속보의 `empSeqno`처럼 쓸 만한
    id가 실제로 들어 있지만, 지금 `JobInfoResult`가 그 필드를 안 들고 있다.
    파서에 `source_key`를 추가하는 건 job_info_client.py를 동시에 고치고 있는
    다른 작업과 겹쳐서 그쪽이 병합된 뒤로 미뤘다 — 그때 이 함수는 그대로 두고
    호출부에서 source_key만 넘겨주면 된다.
    """
    if source_key:
        return f"k:{source_key.strip()}"
    payload = "\n".join([title.strip(), subtitle.strip(), *(m.strip() for m in meta_lines)])
    return "h:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def build_embed_text(title: str, subtitle: str, meta_lines: list[str]) -> str:
    """임베딩에 넣을 문자열. feed_items.embed_text에 그대로 저장해서 다음
    수집 때 "다시 임베딩해야 하나"를 문자열 비교 한 번으로 판단한다."""
    return "\n".join(part for part in [title.strip(), subtitle.strip(), *(m.strip() for m in meta_lines)] if part)
