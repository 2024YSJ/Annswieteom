# -*- coding: utf-8 -*-
"""온통청년 정책 전체를 훑어 자격조건 코드의 실제 분포를 집계한다.

    cd backend && python scripts/tally_youthcenter_codes.py [출력.json]

정책 자격조건(학력·전공·취업상태·특화분야·혼인·소득)은 `0049010` 같은 코드로만
오고, 코드→라벨 표(API코드정보.xlsx)는 로그인 뒤에만 받을 수 있다. 추측한 표로
매칭을 짜면 **조용히** 틀린 티어에 정책이 들어가므로, 코드를 쓰는 로직을 만들기
전에 이걸 먼저 돌린다. 코드마다 샘플 정책을 남겨 두어 youthcenter.go.kr 상세
화면에 표시되는 라벨과 대조할 수 있게 한다.

읽기 전용이다. 인증키는 절대 출력하지 않는다 — 파라미터 dict을 통째로 찍지 말 것.
"""
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app.core.config import settings

ENDPOINT = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
PAGE_SIZE = 100
SAMPLES_PER_CODE = 3

# 쉼표로 여러 코드가 오는 필드와 단일 코드 필드
MULTI_FIELDS = ("jobCd", "schoolCd", "plcyMajorCd", "sbizCd")
SINGLE_FIELDS = ("mrgSttsCd", "earnCndSeCd", "sprtTrgtAgeLmtYn", "aplyPrdSeCd", "lclsfNm")


def _split(raw: object) -> list[str]:
    return [c.strip() for c in str(raw or "").split(",") if c.strip()]


class PageError(Exception):
    """페이지 실패. **URL을 절대 담지 않는다** — httpx 예외 메시지에는 쿼리스트링
    (= 인증키)이 통째로 들어 있어서, 그대로 올리면 traceback에 키가 찍힌다
    (2026-09-11 실제로 한 번 찍혔다)."""


async def fetch_page(client: httpx.AsyncClient, page: int, page_size: int = PAGE_SIZE) -> dict:
    params = {
        "apiKeyNm": settings.youthcenter_api_key,
        "pageNum": str(page),
        "pageSize": str(page_size),
        "rtnType": "json",
    }
    try:
        resp = await client.get(ENDPOINT, params=params)
    except httpx.HTTPError as exc:
        raise PageError(f"page={page} size={page_size} transport error {type(exc).__name__}") from None
    if resp.status_code >= 400:
        raise PageError(f"page={page} size={page_size} http {resp.status_code} body={resp.text[:120]!r}")
    payload = resp.json()
    if payload.get("resultCode") != 200:
        raise PageError(f"page={page} size={page_size} api {payload.get('resultCode')}: {payload.get('resultMessage')}")
    return payload


async def main(out_path: str | None) -> None:
    if not settings.youthcenter_api_key:
        print("[skip] youthcenter_api_key 미설정")
        return

    counts: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    age_combos: Counter = Counter()
    earn_combos: Counter = Counter()
    zip_stats: Counter = Counter()
    zip_prefix2: Counter = Counter()
    zip_len_hist: Counter = Counter()
    total = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        first = await fetch_page(client, 1)
        tot_count = int(first["result"]["pagging"]["totCount"])
        pages = (tot_count + PAGE_SIZE - 1) // PAGE_SIZE
        print(f"totCount={tot_count}, pages={pages}")

        failed_pages: list[str] = []
        for page in range(1, pages + 1):
            try:
                payload = first if page == 1 else await fetch_page(client, page)
            except PageError as exc:
                # 한 페이지가 400이어도 나머지 분포는 유효하다 — 기록만 하고 계속.
                print(f"  [fail] {exc}")
                failed_pages.append(str(exc))
                continue
            for item in payload.get("result", {}).get("youthPolicyList", []) or []:
                total += 1
                sample = f"{item.get('plcyNo')} | {item.get('plcyNm')}"

                for field in MULTI_FIELDS:
                    codes = _split(item.get(field))
                    counts[f"{field}#n"][len(codes)] += 1
                    for code in codes:
                        counts[field][code] += 1
                        if len(samples[field][code]) < SAMPLES_PER_CODE:
                            samples[field][code].append(sample)
                for field in SINGLE_FIELDS:
                    code = str(item.get(field) or "").strip() or "(empty)"
                    counts[field][code] += 1
                    if len(samples[field][code]) < SAMPLES_PER_CODE:
                        samples[field][code].append(sample)

                age_combos[
                    (
                        item.get("sprtTrgtAgeLmtYn"),
                        "min0" if str(item.get("sprtTrgtMinAge") or "0") == "0" else "min>0",
                        "max0" if str(item.get("sprtTrgtMaxAge") or "0") == "0" else "max>0",
                    )
                ] += 1
                earn_combos[
                    (
                        item.get("earnCndSeCd"),
                        "min0" if str(item.get("earnMinAmt") or "0") == "0" else "min>0",
                        "max0" if str(item.get("earnMaxAmt") or "0") == "0" else "max>0",
                        "etc" if str(item.get("earnEtcCn") or "").strip() else "no-etc",
                    )
                ] += 1

                zips = _split(item.get("zipCd"))
                zip_len_hist[min(len(zips) // 50 * 50, 300)] += 1
                if not zips:
                    zip_stats["empty"] += 1
                for z in zips:
                    zip_prefix2[z[:2]] += 1
                    zip_stats["len5" if len(z) == 5 else f"len{len(z)}"] += 1
                    zip_stats["ends0" if z.endswith("0") else "ends_nonzero"] += 1

    report = {
        "total": total,
        # 온통청년은 가끔 한 페이지만 400이나 403(invalid api key)을 낸다 — 같은 키로
        # 앞뒤 페이지는 성공하므로 키 문제가 아니라 서버 쪽 제한으로 보인다.
        # 분포 해석 시 빠진 100건이 있음을 알 수 있게 남긴다.
        "failed_pages": failed_pages,
        "counts": {k: dict(v.most_common()) for k, v in counts.items()},
        "samples": {k: dict(v) for k, v in samples.items()},
        "age_combos": {" / ".join(map(str, k)): v for k, v in age_combos.most_common()},
        "earn_combos": {" / ".join(map(str, k)): v for k, v in earn_combos.most_common()},
        "zip_stats": dict(zip_stats),
        "zip_prefix2": dict(sorted(zip_prefix2.items())),
        "zip_count_histogram(bucket=50)": dict(sorted(zip_len_hist.items())),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"wrote {out_path}")
    else:
        print(text)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
