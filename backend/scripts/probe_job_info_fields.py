# -*- coding: utf-8 -*-
"""고용24 wk/* 엔드포인트가 실제로 돌려주는 항목 필드를 덤프한다.

    cd backend && python scripts/probe_job_info_fields.py

`job_info_client.py`의 파서들은 각 카테고리에서 제목/부제/메타만 뽑아 쓰는데,
상세 링크를 붙이려면 응답에 어떤 id/URL 필드가 실제로 들어 있는지부터 알아야
한다(스펙이 말하는 eventNo/empSeqno가 정말 오는지). 추측으로 URL을 만들면
404로 가는 카드가 생기므로, 코드를 고치기 전에 이걸 먼저 돌린다.

인증키는 절대 출력하지 않는다 — 파라미터 dict을 통째로 찍지 말 것.
"""
import asyncio
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app.core.config import settings

BASE = "https://www.work24.go.kr/cm/openApi/call/wk"

# (카테고리, 엔드포인트, 항목 태그, 인증키 필드명)
TARGETS = [
    ("job_fair", f"{BASE}/callOpenApiSvcInfo210L11.do", "empEvent", "worknet_job_posting_api_key"),
    ("public_recruitment", f"{BASE}/callOpenApiSvcInfo210L21.do", "dhsOpenEmpInfo", "worknet_job_posting_api_key"),
    ("public_recruitment_company", f"{BASE}/callOpenApiSvcInfo210L31.do", "dhsOpenEmpHireInfo", "worknet_job_posting_api_key"),
    ("job_seeker_program", f"{BASE}/callOpenApiSvcInfo217L01.do", "empPgmSchdInvite", "worknet_job_seeker_program_api_key"),
    ("promising_sme", f"{BASE}/callOpenApiSvcInfo216L01.do", "smallGiant", "worknet_promising_sme_api_key"),
]


async def probe(category: str, url: str, item_tag: str, key_field: str) -> None:
    auth_key = getattr(settings, key_field, "")
    print(f"\n{'=' * 70}\n{category}  (<{item_tag}>)")
    if not auth_key:
        print(f"  [skip] {key_field} 미설정")
        return
    params = {"authKey": auth_key, "returnType": "XML", "callTp": "L", "startPage": "1", "display": "3"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, params=params)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - 진단용 스크립트
        print(f"  [http error] {type(exc).__name__}: {exc}")
        return

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        print(f"  [parse error] {exc}\n  본문 앞 300자: {resp.text[:300]!r}")
        return

    for tag in ("message", "error"):
        el = root.find(tag)
        if el is not None:
            print(f"  [api error] <{tag}>{(el.text or '').strip()}</{tag}>")
            return

    items = root.findall(f".//{item_tag}")
    print(f"  항목 {len(items)}건 (root=<{root.tag}>)")
    if not items:
        print(f"  루트 직계 자식: {[c.tag for c in root][:15]}")
        return

    for idx, item in enumerate(items[:2]):
        print(f"  --- item[{idx}] ---")
        for child in item:
            value = (child.text or "").strip()
            if len(value) > 90:
                value = value[:90] + "..."
            print(f"    {child.tag:32} = {value}")


async def main() -> None:
    for target in TARGETS:
        await probe(*target)


if __name__ == "__main__":
    asyncio.run(main())
