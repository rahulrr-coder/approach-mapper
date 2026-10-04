import pytest
from pydantic import ValidationError

from app.schemas import Approach


def good():
    return {
        "domain": "coding",
        "problem_restated": "Find two numbers that add to a target.",
        "given_and_goal": {"given": ["array", "target"], "find": "indices"},
        "clues": [{"clue": "two numbers", "suggests": "pairs / lookup"}],
        "pattern": {"name": "Hash map lookup", "why_it_fits": "need complement fast"},
        "steps": [{"n": 1, "title": "Complement", "think": "What pairs with x?", "do": "Compute target - x"}],
        "mindmap": {
            "nodes": [
                {"id": "n1", "label": "Start", "kind": "start"},
                {"id": "n2", "label": "Seen complement?", "kind": "question"},
                {"id": "n3", "label": "Return pair", "kind": "end"},
            ],
            "edges": [{"from": "n1", "to": "n2"}, {"from": "n2", "to": "n3", "label": "yes"}],
        },
        "hint_ladder": ["1", "2", "3", "4"],
    }


def test_valid():
    a = Approach.model_validate(good())
    assert a.cost_note is None and a.unreadable_parts == []


def test_edge_unknown_node():
    d = good()
    d["mindmap"]["edges"].append({"from": "n1", "to": "zzz"})
    with pytest.raises(ValidationError):
        Approach.model_validate(d)


def test_needs_one_start_and_an_end():
    d = good()
    d["mindmap"]["nodes"][0]["kind"] = "action"
    with pytest.raises(ValidationError):
        Approach.model_validate(d)


def test_hint_ladder_exactly_four():
    d = good()
    d["hint_ladder"] = ["1", "2", "3"]
    with pytest.raises(ValidationError):
        Approach.model_validate(d)
