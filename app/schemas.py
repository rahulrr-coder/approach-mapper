from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class GivenGoal(BaseModel):
    given: list[str]
    find: str


class Clue(BaseModel):
    clue: str
    suggests: str


class Pattern(BaseModel):
    name: str
    why_it_fits: str


class Step(BaseModel):
    n: int
    title: str
    think: str
    do: str


class Node(BaseModel):
    id: str
    label: str
    kind: Literal["start", "question", "action", "pattern", "end"]


class Edge(BaseModel):
    from_: str = Field(alias="from")
    to: str
    label: Optional[str] = None

    model_config = {"populate_by_name": True}


class Mindmap(BaseModel):
    nodes: list[Node]
    edges: list[Edge]

    @model_validator(mode="after")
    def check_graph(self):
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            raise ValueError("mindmap node ids must be unique")
        if sum(n.kind == "start" for n in self.nodes) != 1:
            raise ValueError("mindmap needs exactly one start node")
        if not any(n.kind == "end" for n in self.nodes):
            raise ValueError("mindmap needs at least one end node")
        for e in self.edges:
            if e.from_ not in ids or e.to not in ids:
                raise ValueError(f"edge {e.from_}->{e.to} references an unknown node id")
        return self


class Approach(BaseModel):
    category: Literal["math", "science", "coding", "other"] = "other"
    domain: str  # free-text label, e.g. "calculus", "mechanics", "graphs"
    problem_restated: str
    given_and_goal: GivenGoal
    clues: list[Clue]
    pattern: Pattern
    steps: list[Step] = Field(min_length=1)
    mindmap: Mindmap
    hint_ladder: list[str] = Field(min_length=4, max_length=4)
    cost_note: Optional[str] = None  # time/space for code; method cost otherwise
    pitfalls: list[str] = []
    similar_problems: list[str] = []
    unreadable_parts: list[str] = []

    @field_validator("category", mode="before")
    @classmethod
    def coerce_category(cls, v):
        v = str(v).strip().lower()
        return v if v in {"math", "science", "coding", "other"} else "other"
