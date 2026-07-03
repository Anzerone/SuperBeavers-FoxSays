from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    material = "Material"
    process = "Process"
    equipment = "Equipment"
    property = "Property"
    experiment = "Experiment"
    document = "Document"
    expert = "Expert"
    facility = "Facility"
    conclusion = "Conclusion"
    geo = "Geo"
    tag = "Tag"


class GraphNode(BaseModel):
    id: str
    label: str
    type: EntityType
    confidence: float = 0.8
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    label: str
    confidence: float = 0.8
    metadata: dict[str, Any] = Field(default_factory=dict)


class Evidence(BaseModel):
    source_id: str
    title: str
    page: int | None = None
    snippet: str
    confidence: float
    updated_at: str


class Fact(BaseModel):
    topic: str
    condition: str
    conclusion: str
    source: str
    confidence: float


class QueryIntent(BaseModel):
    intent: str = "knowledge_lookup"
    materials: list[str] = Field(default_factory=list)
    processes: list[str] = Field(default_factory=list)
    properties: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    geography: str | None = None
    time_range: str | None = None
    numeric_constraints: list[str] = Field(default_factory=list)
    numeric_filters: list[dict[str, Any]] = Field(default_factory=list)
    comparisons: list[dict[str, str]] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class AskRequest(BaseModel):
    question: str
    geography: str | None = None
    years: str | None = None
    verified_only: bool = True


class AskResponse(BaseModel):
    id: str
    question: str
    intent: QueryIntent
    answer: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    facts: list[Fact]
    evidence: list[Evidence]
    metrics: dict[str, int | float]
    graph_insights: dict[str, Any] = Field(default_factory=dict)


class Experiment(BaseModel):
    id: str
    title: str
    material: str
    process: str
    condition: str
    result: str
    property: str
    value: str | None = None
    geography: str = "unknown"
    year: int | None = None
    source: str
    confidence: float = 0.75


class GapCell(BaseModel):
    row: str
    col: str
    count: int
    status: str


class GapsResponse(BaseModel):
    rows: list[str]
    cols: list[str]
    cells: list[GapCell]


class TimelinePoint(BaseModel):
    year: int
    value: float
    label: str
    source: str


class IngestRequest(BaseModel):
    corpus_dir: str | None = None
    limit: int | None = None
    reset: bool = False


class IngestStatus(BaseModel):
    state: str
    files_seen: int = 0
    documents_loaded: int = 0
    experiments_loaded: int = 0
    warnings: list[str] = Field(default_factory=list)
