import pytest

from app.llm import LLMError, parse


def test_not_a_problem_is_declined():
    with pytest.raises(LLMError) as e:
        parse('```json\n{"not_a_problem": "It is a contest announcement."}\n```')
    assert e.value.status == 422 and "announcement" in e.value.message
