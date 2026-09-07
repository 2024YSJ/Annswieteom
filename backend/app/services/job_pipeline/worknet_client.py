from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from app.core.config import settings
from app.services.llm.base import JobPosting, JobPreferences


class WorknetJobPostingClient:
    """Thin wrapper over the 워크넷(고용24) 채용정보 Open API (`wantedApi.do`,
    `callTp=L` — job listing search). Read-only, XML response, no SDK — same
    httpx + Settings + DI-factory pattern as
    `app.services.storage.SupabaseStorage`.

    v1 simplification: 워크넷은 지역/학력/경력을 내부 코드값으로 요구하지만,
    그 코드 매핑 테이블을 구축하는 건 그 자체로 별도 작업 규모라 후속 과제로
    미루고, 자유 텍스트를 `keyword` 파라미터에 실어 검색한다.
    """

    def __init__(self) -> None:
        self._base_url = settings.worknet_api_base_url
        self._api_key = settings.worknet_api_key

    async def search(self, preferences: JobPreferences, limit: int = 15) -> list[JobPosting]:
        keyword_parts = [preferences.location, preferences.education_level, *preferences.work_style_tags]
        keyword = " ".join(part for part in keyword_parts if part).strip()

        params: dict[str, str] = {
            "authKey": self._api_key,
            "callTp": "L",
            "returnType": "XML",
            "startPage": "1",
            "display": str(limit),
        }
        if keyword:
            params["keyword"] = keyword

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(self._base_url, params=params)
            resp.raise_for_status()
            return _parse_postings(resp.text)


def _text(item: ET.Element, tag: str) -> str:
    found = item.find(tag)
    return (found.text or "").strip() if found is not None and found.text else ""


def _parse_postings(xml_text: str) -> list[JobPosting]:
    root = ET.fromstring(xml_text)
    # Searched with `.//wanted` (not a fixed root/child path) since the exact
    # wrapping element name in 워크넷's XML envelope wasn't directly
    # observable during planning (only field names were confirmed via public
    # write-ups, not the wrapper) — this needs a one-time check against a
    # real response once a WORKNET_API_KEY is available, per the plan's v1
    # simplification note.
    postings: list[JobPosting] = []
    for item in root.findall(".//wanted"):
        sal_type = _text(item, "salTpNm")
        sal = _text(item, "sal")
        min_sal = _text(item, "minSal")
        max_sal = _text(item, "maxSal")
        salary_text = sal or (f"{min_sal}~{max_sal}" if min_sal or max_sal else "")
        if sal_type:
            salary_text = f"{sal_type} {salary_text}".strip()

        postings.append(
            JobPosting(
                source="worknet",
                external_id=_text(item, "wantedAuthNo"),
                title=_text(item, "title"),
                company=_text(item, "company"),
                salary_text=salary_text,
                location=_text(item, "region"),
                education_requirement=_text(item, "minEdubg"),
                career_requirement=_text(item, "career"),
                work_type=_text(item, "holidayTpNm"),
                url=_text(item, "wantedInfoUrl"),
            )
        )
    return postings


def get_job_search_client() -> WorknetJobPostingClient:
    """FastAPI DI hook — routes should depend on this (not import
    WorknetJobPostingClient directly) so tests can override it with a fake,
    same pattern as get_storage / get_llm_provider."""
    return WorknetJobPostingClient()
