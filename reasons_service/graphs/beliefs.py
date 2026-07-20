"""Beliefs graph: propose beliefs from entries, human review, accept."""

from uuid import UUID

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy import select

from reasons_service.core.propose import propose_from_entries
from reasons_service.db.connection import get_sync_session
from reasons_service.db.models import Entry
from reasons_service.graphs.state import BeliefsState
from reasons_service.rms import api as rms_api


def propose_beliefs(state: BeliefsState) -> dict:
    """Batch entries and extract belief candidates via LLM."""
    project_id = state["project_id"]
    batch_size = state.get("batch_size", 5)
    model = state.get("model")

    # Read all entries for this project
    with get_sync_session() as session:
        entries = session.execute(
            select(Entry)
            .where(Entry.project_id == UUID(project_id))
            .order_by(Entry.topic)
        ).scalars().all()

        entry_dicts = [
            {
                "id": entry.id,
                "topic": entry.topic,
                "title": entry.title,
                "content": entry.content,
            }
            for entry in entries
        ]

    if not entry_dicts:
        return {
            "proposed_beliefs": [],
            "errors": ["No entries found for this project"],
        }

    # Extract beliefs via LLM
    beliefs = propose_from_entries(entry_dicts, model=model, batch_size=batch_size)

    # Write proposed beliefs as RMS nodes (OUT until accepted)
    for belief in beliefs:
        try:
            rms_api.add_node(
                UUID(project_id),
                node_id=belief["id"],
                text=belief["text"],
                source=belief.get("source", ""),
            )
            # Mark as OUT until human review accepts
            rms_api.retract_node(UUID(project_id), belief["id"])
        except Exception:
            pass  # Skip duplicates

    return {
        "proposed_beliefs": beliefs,
        "errors": [],
    }


def human_review(state: BeliefsState) -> dict:
    """Pause for human review of proposed beliefs."""
    proposed = state.get("proposed_beliefs", [])
    if not proposed:
        return {"review_decisions": {}}

    review = interrupt({
        "proposed_beliefs": proposed,
        "message": f"Review {len(proposed)} proposed beliefs",
    })
    return {"review_decisions": review}


def accept_beliefs(state: BeliefsState) -> dict:
    """Update RMS nodes based on review decisions."""
    project_id = state["project_id"]
    decisions = state.get("review_decisions", {})

    accepted = 0
    rejected = 0

    for belief_id, decision in decisions.items():
        try:
            if decision == "accept":
                rms_api.assert_node(UUID(project_id), belief_id)
                accepted += 1
            elif decision == "reject":
                # Already OUT from proposal — leave it
                rejected += 1
        except KeyError:
            continue

    return {
        "accepted_count": accepted,
        "rejected_count": rejected,
    }


# Build the graph
builder = StateGraph(BeliefsState)
builder.add_node("propose_beliefs", propose_beliefs)
builder.add_node("human_review", human_review)
builder.add_node("accept_beliefs", accept_beliefs)

builder.set_entry_point("propose_beliefs")
builder.add_edge("propose_beliefs", "human_review")
builder.add_edge("human_review", "accept_beliefs")
builder.add_edge("accept_beliefs", END)

# For LangGraph Platform (provides its own checkpointer)
beliefs_graph = builder.compile()

# For direct API use (we provide our own checkpointer for interrupt support)
_api_graph = None


def get_beliefs_graph():
    """Get beliefs graph compiled with PostgresSaver checkpointer.

    interrupt() requires a checkpointer to persist state while paused.
    LangGraph Platform provides its own; for direct API use we need ours.
    """
    global _api_graph
    if _api_graph is None:
        from reasons_service.graphs.checkpointer import get_checkpointer
        _api_graph = builder.compile(checkpointer=get_checkpointer())
    return _api_graph
