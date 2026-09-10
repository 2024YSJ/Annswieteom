from __future__ import annotations

from app.core.config import settings
from app.services.feed.sources.base import FeedItemData, FeedSource
from app.services.job_pipeline.job_info_client import CATEGORY_SEARCH_FUNCTIONS

#: 피드가 카테고리당 받아오는 건수. `job_info_client._FETCH_LIMIT`(20)을 안 쓰고
#: 여기서 따로 정하는 이유는, 그 상수가 대화형 취업 정보 검색과 공유되고 그쪽은
#: 목록 전체가 로컬 LLM 프롬프트에 통째로 들어가기 때문이다(devlog 18/20).
#: 피드는 LLM을 거치지 않고 DB에 쌓기만 하므로 더 많이 받아도 안전하고, 그래야
#: 메인 화면의 "더보기"가 몇 번 누르고 바닥나지 않는다.
FEED_FETCH_LIMIT = 50

#: 카테고리별로 어느 인증키를 보는지. 고용24는 카테고리마다 따로 신청하고
#: 담당자 심사를 거쳐 별도 키가 나오므로(devlog 15/16), "고용24 키 하나"가
#: 아니라 이 단위로 설정 여부를 판단해야 한다. 훈련과정은 4개 엔드포인트를
#: 합친 것이라 그중 하나만 있어도 뭔가는 가져올 수 있다.
_KEY_FIELDS_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "job_fair": ("worknet_job_posting_api_key",),
    "public_recruitment": ("worknet_job_posting_api_key",),
    "public_recruitment_company": ("worknet_job_posting_api_key",),
    "job_seeker_program": ("worknet_job_seeker_program_api_key",),
    "promising_sme": ("worknet_promising_sme_api_key",),
    "training_course": (
        "worknet_tomorrow_learning_card_api_key",
        "worknet_employer_training_api_key",
        "worknet_consortium_training_api_key",
        "worknet_work_study_training_api_key",
    ),
}


class WorknetFeedSource:
    """고용24(구 워크넷) 6개 카테고리를 피드용으로 감싼 어댑터.

    HTTP 코드가 한 줄도 없다 — 기존 `job_info_client.CATEGORY_SEARCH_FUNCTIONS`를
    그대로 호출하고 결과를 `FeedItemData`로 옮기기만 한다. 파서를 복제하면
    고용24 XML 스키마가 바뀔 때마다 두 곳을 고쳐야 하고, 반드시 한 곳을 잊는다.

    항목별 안정 id는 이제 `JobInfoResult.source_key`로 올라온다(채용행사
    `eventNo`, 공채속보 `empSeqno`, 공채기업정보 `empCoNo`, 강소기업 `busiNo`).
    구직자프로그램과 훈련과정은 응답에 id가 없어 여전히 내용 해시로 갈음한다
    (services/feed/dedup.py).
    """

    name = "worknet"
    categories = tuple(_KEY_FIELDS_BY_CATEGORY)

    def is_category_configured(self, category: str) -> bool:
        return any(getattr(settings, field, "") for field in _KEY_FIELDS_BY_CATEGORY[category])

    def is_configured(self) -> bool:
        return any(self.is_category_configured(c) for c in self.categories)

    async def fetch(self, category: str) -> list[FeedItemData]:
        func = CATEGORY_SEARCH_FUNCTIONS[category]
        # 훈련과정만 시그니처가 다르다(limit이 아니라 조회 조건을 받고, 크기는
        # 엔드포인트별 상한으로 내부에서 정해진다).
        results = await (func() if category == "training_course" else func(limit=FEED_FETCH_LIMIT))
        return [
            FeedItemData(
                source=self.name,
                category=category,
                title=r.title,
                subtitle=r.subtitle,
                meta_lines=list(r.meta_lines),
                detail_url=r.detail_url,
                # 소스가 준 항목 id를 먼저 쓴다. 없으면 상세 URL이 항목마다
                # 고유하므로 사실상의 안정 id 역할을 한다.
                source_key=r.source_key or r.detail_url or None,
            )
            for r in results
            if r.title
        ]


_: FeedSource = WorknetFeedSource()
