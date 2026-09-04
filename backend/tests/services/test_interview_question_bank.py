from __future__ import annotations

from app.models.activity_category import CATEGORY_TYPES
from app.services.interview_question_bank import BASE_QUESTIONS, next_base_question


def test_every_category_type_has_base_questions():
    for category_type in CATEGORY_TYPES:
        assert category_type in BASE_QUESTIONS
        assert len(BASE_QUESTIONS[category_type]) >= 3


def test_fact_types_unique_within_each_category():
    for category_type, questions in BASE_QUESTIONS.items():
        fact_types = [q.fact_type for q in questions]
        assert len(fact_types) == len(set(fact_types)), f"duplicate fact_type in {category_type}"


def test_next_base_question_returns_first_unanswered():
    first = next_base_question("part_time", set())
    assert first == BASE_QUESTIONS["part_time"][0]


def test_next_base_question_skips_answered_fact_types():
    answered = {BASE_QUESTIONS["part_time"][0].fact_type}
    nxt = next_base_question("part_time", answered)
    assert nxt == BASE_QUESTIONS["part_time"][1]


def test_next_base_question_returns_none_when_exhausted():
    all_fact_types = {q.fact_type for q in BASE_QUESTIONS["part_time"]}
    assert next_base_question("part_time", all_fact_types) is None


def test_next_base_question_falls_back_to_other_for_unknown_category_type():
    assert next_base_question("nonexistent_type", set()) == BASE_QUESTIONS["other"][0]
