from __future__ import annotations

from app.services.job_search_question_bank import JOB_SEARCH_QUESTIONS, next_question


def test_next_question_returns_first_when_none_completed():
    question = next_question([])
    assert question is not None
    assert question.field == "keyword"


def test_next_question_skips_completed_fields_in_order():
    question = next_question(["keyword", "location"])
    assert question is not None
    assert question.field == "salary"


def test_next_question_returns_none_when_all_completed():
    all_fields = [q.field for q in JOB_SEARCH_QUESTIONS]
    assert next_question(all_fields) is None


def test_question_fields_are_unique():
    fields = [q.field for q in JOB_SEARCH_QUESTIONS]
    assert len(fields) == len(set(fields))
