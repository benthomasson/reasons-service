"""State types for LangGraph graphs."""

from typing import NotRequired, TypedDict


class IngestState(TypedDict):
    project_id: str
    domain: str
    url: str
    depth: NotRequired[int]
    delay: NotRequired[float]
    selector: NotRequired[str]
    include: NotRequired[str]
    exclude: NotRequired[str]
    use_sitemap: NotRequired[bool]
    model: NotRequired[str]
    batch_size: NotRequired[int]
    sources_fetched: int
    entries_created: int
    current_batch: int
    total_batches: int
    errors: list[str]


class BeliefsState(TypedDict):
    project_id: str
    batch_size: NotRequired[int]
    model: NotRequired[str]
    proposed_beliefs: list[dict]
    review_decisions: dict
    accepted_count: int
    rejected_count: int
    errors: list[str]


class AssessmentState(TypedDict):
    project_id: str
    assessment_type: str
    model: NotRequired[str]
    domain: NotRequired[str]
    objectives: list[dict]
    questions: list[dict]
    beliefs_context: str
    results: list[dict]
    score: dict
    nogoods_discovered: list[dict]
