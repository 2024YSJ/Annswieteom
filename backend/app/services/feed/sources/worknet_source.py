from __future__ import annotations

from app.core.config import settings
from app.services.feed.sources.base import FeedItemData, FeedSource
from app.services.job_pipeline.job_info_client import CATEGORY_SEARCH_FUNCTIONS

#: 카테고리별로 어느 인증키를 보는지. 워크넷은 카테고리마다 따로 신청하고
#: 담당자 심사를 거쳐 별도 키가 나오므로(devlog 15/16), "워크넷 키 하나"가
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
    """워크넷/고용24 6개 카테고리를 피드용으로 감싼 어댑터.

    HTTP 코드가 한 줄도 없다 — 기존 `job_info_client.CATEGORY_SEARCH_FUNCTIONS`를
    그대로 호출하고 결과를 `FeedItemData`로 옮기기만 한다. 파서를 복제하면
    워크넷 XML 스키마가 바뀔 때마다 두 곳을 고쳐야 하고, 반드시 한 곳을 잊는다.

    항목별 안정 id(`eventNo`/`empSeqno`)는 아직 안 쓴다 — `JobInfoResult`가
    그 필드를 안 들고 있고, 그 파일은 지금 다른 작업이 크게 고치는 중이라
    병합 후에 붙인다. 그때까지는 상세 URL이 있으면 그걸, 없으면 내용 해시를
    식별자로 쓴다(services/feed/dedup.py).
    """

    name = "worknet"
    categories = tuple(_KEY_FIELDS_BY_CATEGORY)

    def is_category_configured(self, category: str) -> bool:
        return any(getattr(settings, field, "") for field in _KEY_FIELDS_BY_CATEGORY[category])

    def is_configured(self) -> bool:
        return any(self.is_category_configured(c) for c in self.categories)

    async def fetch(self, category: str) -> list[FeedItemData]:
        results = await CATEGORY_SEARCH_FUNCTIONS[category]()
        return [
            FeedItemData(
                source=self.name,
                category=category,
                title=r.title,
                subtitle=r.subtitle,
                meta_lines=list(r.meta_lines),
                detail_url=r.detail_url,
                # 상세 URL은 항목마다 고유해서 사실상의 안정 id 역할을 한다.
                source_key=r.detail_url or None,
            )
            for r in results
            if r.title
        ]


_: FeedSource = WorknetFeedSource()
