"""프로필 속성의 어휘 — 추출 프롬프트와 프로필 편집 화면이 같은 목록을 쓴다.

일부러 가벼운 잎 모듈로 둔다. LLM 프로바이더(local_ollama)가 프롬프트에 이
목록을 싣고, 속성 서비스(attributes.py)는 그 프로바이더를 부르므로, 둘 다 여기만
보게 하면 순환 import가 생기지 않는다.

목록이 있는 키는 LLM이 **목록 안의 표현만** 고르게 한다(regions.py와 같은
원칙: 코드는 서버가 붙인다). 학력·전공·취업상태·특화분야·혼인은 온통청년 코드와
1:1로 대응하는 라벨이라 그대로 매칭 입력이 된다.
"""
from __future__ import annotations

from app.services.feed import youthcenter_codes as yc
from app.services.job_pipeline.regions import KNOWN_REGION_NAMES


def _choices(table: dict[str, str]) -> tuple[str, ...]:
    # "제한없음"과 "기타"는 사용자 쪽 값으로 의미가 없다.
    return tuple(label for code, label in table.items() if code not in yc.UNRESTRICTED and label != "기타")


REGION_CHOICES: tuple[str, ...] = tuple(KNOWN_REGION_NAMES)
EDUCATION_CHOICES = _choices(yc.SCHOOL)
MAJOR_CHOICES = _choices(yc.MAJOR)
EMPLOYMENT_CHOICES = _choices(yc.JOB_STATUS)
SPECIAL_CHOICES = _choices(yc.SPECIAL)
MARITAL_CHOICES = _choices(yc.MARITAL)
EMPLOYMENT_TYPE_CHOICES: tuple[str, ...] = ("정규직", "계약직", "인턴", "아르바이트", "프리랜서")

#: 목록에서만 고르는 키. 여기 없는 키(희망직무·기술·자격증·관심분야 등)는 짧은 자유 텍스트다.
CHOICES: dict[str, tuple[str, ...]] = {
    "residence_region": REGION_CHOICES,
    "desired_region": REGION_CHOICES,
    "education_level": EDUCATION_CHOICES,
    "major_field": MAJOR_CHOICES,
    "employment_status": EMPLOYMENT_CHOICES,
    "desired_employment_type": EMPLOYMENT_TYPE_CHOICES,
    "special_groups": SPECIAL_CHOICES,
    "marital_status": MARITAL_CHOICES,
}

#: 라벨 → 온통청년 코드. 매칭에 쓰이는 키만.
_CODE_TABLES: dict[str, dict[str, str]] = {
    "education_level": yc.SCHOOL,
    "major_field": yc.MAJOR,
    "employment_status": yc.JOB_STATUS,
    "special_groups": yc.SPECIAL,
    "marital_status": yc.MARITAL,
}

KEY_LABELS: dict[str, str] = {
    "birth_year": "출생연도",
    "residence_region": "거주지",
    "desired_region": "희망 근무지역",
    "education_level": "학력",
    "major_field": "전공 계열",
    "employment_status": "취업 상태",
    "desired_job": "희망 직무",
    "desired_employment_type": "희망 고용형태",
    "skills": "보유 기술",
    "certificates": "자격증",
    "interests": "관심 분야",
    "annual_income": "연소득",
    "special_groups": "해당 대상",
    "marital_status": "혼인 여부",
}


def label_to_code(key: str, label: str) -> str | None:
    table = _CODE_TABLES.get(key)
    if table is None:
        return None
    for code, value in table.items():
        if value == label:
            return code
    return None
