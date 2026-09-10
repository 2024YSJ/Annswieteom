"""사용자가 말한 지역명 → 고용24 지역 조건 변환.

LLM에게 코드를 외우게 하지 않는다. LLM은 질문에서 지역명("경기 북부",
"서울")만 뽑고, 코드 변환은 여기 있는 결정적 테이블이 담당한다 — 잘못된
코드는 에러가 아니라 조용한 0건으로 돌아오기 때문에(실측: 콤마로 이어붙인
`11,41`은 0건, 반복 파라미터는 첫 값만 적용) 코드를 모델 출력에 맡길 수 없다.

아래 코드는 전부 국민내일배움카드/사업주훈련 엔드포인트로 직접 호출해
확인한 값이다(devlog 20). 특히:
  - 강원은 42가 아니라 **51**(강원특별자치도), 전북은 45가 아니라 **52**다.
    구 코드는 에러 없이 0건을 돌려준다.
  - 광주(29)는 두 엔드포인트 모두에서 0건이었다. 코드가 틀린 건지 해당
    기간에 과정이 없는 건지 구분할 방법이 없어 일단 표에 두되, 조회 계층이
    "필터 결과가 0건이면 필터 없이 재시도"로 방어한다.
  - 경기 북부 시·군 코드 8개(의정부/동두천/고양/구리/남양주/파주/양주/포천)는
    해당 시·군만 정확히 돌려주는 것을 확인했고, 연천·가평은 0건이었다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 광역시/도 (srchTraArea1)
_WIDE_AREA_CODES: dict[str, str] = {
    "서울": "11",
    "부산": "26",
    "대구": "27",
    "인천": "28",
    "광주": "29",
    "대전": "30",
    "울산": "31",
    "세종": "36",
    "경기": "41",
    "강원": "51",
    "충북": "43",
    "충남": "44",
    "전북": "52",
    "전남": "46",
    "경북": "47",
    "경남": "48",
    "제주": "50",
}

# 시/군/구 (srchTraArea2) — 광역 코드와 함께 보내야 한다.
_GYEONGGI_NORTH_CITIES: dict[str, str] = {
    "의정부": "41150",
    "동두천": "41250",
    "고양": "41280",
    "구리": "41310",
    "남양주": "41360",
    "파주": "41480",
    "양주": "41630",
    "포천": "41650",
    "연천": "41800",
    "가평": "41820",
}

_GYEONGGI_SOUTH_CITIES: dict[str, str] = {
    "수원": "41110",
    "성남": "41130",
    "안양": "41170",
    "부천": "41190",
    "광명": "41210",
    "평택": "41220",
    "안산": "41270",
    "과천": "41290",
    "오산": "41370",
    "시흥": "41390",
    "군포": "41410",
    "용인": "41460",
    "화성": "41590",
}

_CITY_CODES: dict[str, str] = {**_GYEONGGI_NORTH_CITIES, **_GYEONGGI_SOUTH_CITIES}

# 권역명 → (광역 코드, 그 권역에 속한 시·군 이름). 시·군 코드마다 호출을
# 쪼개면(권역 하나가 10개) 훈련과정은 엔드포인트가 4개라 호출이 40회로
# 폭발한다 — 그래서 광역으로 한 번만 조회하고 주소를 여기 이름들로
# 후필터링한다. 후필터링을 하니 그 호출은 pageSize를 키워서 받는다.
_REGION_GROUPS: dict[str, tuple[str, tuple[str, ...]]] = {
    "경기 북부": ("41", tuple(_GYEONGGI_NORTH_CITIES)),
    "경기 남부": ("41", tuple(_GYEONGGI_SOUTH_CITIES)),
}

# 수도권은 광역 자체가 3개라 그룹이 아니라 광역 3개로 펼친다.
_METROPOLITAN_AREA_CODES = (("서울", "11"), ("경기", "41"), ("인천", "28"))


@dataclass(frozen=True)
class RegionFilter:
    """고용24 호출 하나에 실을 지역 조건.

    `allowed_cities`가 비어 있지 않으면 광역으로 넓게 조회한 뒤 주소를 그
    이름들로 걸러내야 한다는 뜻이다(권역 질문). 비어 있으면 API 파라미터만으로
    이미 정확히 좁혀진 상태다.
    """

    area1: str
    area2: str | None = None
    allowed_cities: tuple[str, ...] = ()
    # 표시/진단용 이름일 뿐이라 동등성에서 뺀다 — 서로 다른 표현("고양",
    # "고양시")이 같은 코드로 풀리면 같은 호출이므로 중복 제거에 걸려야 한다.
    label: str = field(default="", compare=False)

    def as_params(self) -> dict[str, str]:
        params = {"srchTraArea1": self.area1}
        if self.area2:
            params["srchTraArea2"] = self.area2
        return params

    @property
    def needs_address_filter(self) -> bool:
        return bool(self.allowed_cities)

    def matches_address(self, address: str) -> bool:
        if not self.allowed_cities:
            return True
        return any(city in address for city in self.allowed_cities)


def _known_region_names() -> tuple[str, ...]:
    names: list[str] = ["수도권"]
    for name in (*_REGION_GROUPS, *_WIDE_AREA_CODES, *_CITY_CODES):
        if name not in names:
            names.append(name)
    return tuple(names)


#: 추출 프롬프트에 그대로 넘기는 어휘 — LLM이 이 목록 밖의 지역명을 만들면
#: 코드 변환에 실패해 조용히 무시되므로, 목록을 보여주고 그 안에서만 고르게 한다.
KNOWN_REGION_NAMES: tuple[str, ...] = _known_region_names()


def resolve_region_filters(region_names: list[str], limit: int) -> list[RegionFilter]:
    """지역명 목록을 호출 단위 조건 목록으로 바꾼다.

    알 수 없는 지역명은 조용히 건너뛴다 — 억지로 코드를 추측해 보내면 0건이
    되어 "그 지역에 정보가 없다"로 잘못 보이기 때문이다. 하나도 못 알아보면
    빈 목록을 돌려주고, 조회 계층은 지역 조건 없이 조회한다.
    """
    filters: list[RegionFilter] = []
    for raw in region_names:
        name = raw.strip()
        if not name:
            continue

        if name == "수도권":
            filters.extend(RegionFilter(area1=code, label=label) for label, code in _METROPOLITAN_AREA_CODES)
            continue

        group = _REGION_GROUPS.get(name)
        if group is not None:
            area1, cities = group
            filters.append(RegionFilter(area1=area1, allowed_cities=cities, label=name))
            continue

        bare = name.removesuffix("시").removesuffix("군").removesuffix("구") or name
        city_code = _CITY_CODES.get(bare)
        if city_code is not None:
            filters.append(RegionFilter(area1=city_code[:2], area2=city_code, label=bare))
            continue

        wide = _WIDE_AREA_CODES.get(name) or _WIDE_AREA_CODES.get(name[:2])
        if wide is not None:
            filters.append(RegionFilter(area1=wide, label=name))

    deduped: list[RegionFilter] = []
    for f in filters:
        if f not in deduped:
            deduped.append(f)
    return deduped[:limit]
