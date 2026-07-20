"""Ingest graph: fetch documentation sources and summarize into entries."""

from math import ceil
from uuid import UUID

from langgraph.graph import END, StateGraph
from sqlalchemy import select

from reasons_service.core.fetch import fetch_docs
from reasons_service.core.summarize import summarize_batch as run_summarize
from reasons_service.db.connection import get_sync_session
from reasons_service.db.models import Entry, Project, Source, entry_sources
from reasons_service.graphs.state import IngestState

DEFAULT_BATCH_SIZE = 10


def init_project(state: IngestState) -> dict:
    """Validate that the project exists and set initial counters."""
    project_id = state["project_id"]

    with get_sync_session() as session:
        project = session.get(Project, UUID(project_id))
        if not project:
            return {"errors": [f"Project {project_id} not found"]}

    return {
        "sources_fetched": 0,
        "entries_created": 0,
        "current_batch": 0,
        "total_batches": 0,
        "errors": [],
    }


def fetch_sources(state: IngestState) -> dict:
    """Fetch documentation from URL, convert HTML to markdown, store in DB."""
    if state.get("errors"):
        return {}

    url = state["url"]
    depth = state.get("depth", 2)
    delay = state.get("delay", 1.0)
    selector = state.get("selector", "main,article,.content,body")
    include = state.get("include")
    exclude = state.get("exclude")
    use_sitemap = state.get("use_sitemap", False)

    # Fetch docs from URL (returns list of dicts)
    results = fetch_docs(
        url=url,
        depth=depth,
        delay=delay,
        selector=selector,
        include=include,
        exclude=exclude,
        use_sitemap=use_sitemap,
    )

    if not results:
        return {"errors": ["No documents fetched from URL"], "sources_fetched": 0}

    # Insert into sources table
    project_id = state["project_id"]
    sources_fetched = 0

    with get_sync_session() as session:
        for doc in results:
            existing = session.execute(
                select(Source).where(
                    Source.project_id == UUID(project_id),
                    Source.slug == doc["slug"],
                )
            ).scalar_one_or_none()

            if existing:
                # Update existing source
                existing.content = doc["content"]
                existing.word_count = doc.get("word_count")
                existing.url = doc.get("url")
            else:
                source = Source(
                    project_id=UUID(project_id),
                    url=doc.get("url"),
                    slug=doc["slug"],
                    content=doc["content"],
                    word_count=doc.get("word_count"),
                )
                session.add(source)
            sources_fetched += 1

        session.commit()

    # Calculate batches for summarization
    batch_size = state.get("batch_size", DEFAULT_BATCH_SIZE)
    total_batches = ceil(sources_fetched / batch_size) if sources_fetched > 0 else 0

    return {
        "sources_fetched": sources_fetched,
        "total_batches": total_batches,
    }


def summarize_batch(state: IngestState) -> dict:
    """Summarize one batch of sources into entries using LLM."""
    if state.get("errors"):
        return {}

    project_id = state["project_id"]
    current_batch = state.get("current_batch", 0)
    batch_size = state.get("batch_size", DEFAULT_BATCH_SIZE)
    offset = current_batch * batch_size

    # Get the next batch of sources (ordered by slug, offset by batch)
    with get_sync_session() as session:
        sources = session.execute(
            select(Source)
            .where(Source.project_id == UUID(project_id))
            .order_by(Source.slug)
            .offset(offset)
            .limit(batch_size)
        ).scalars().all()

        if not sources:
            # No more sources to process
            return {
                "current_batch": state.get("total_batches", 0),
            }

        # Convert to dicts for the summarize function
        source_dicts = [
            {
                "id": str(source.id),
                "slug": source.slug,
                "content": source.content,
            }
            for source in sources
        ]

    # Run summarization (calls LLM for each source)
    model = state.get("model")
    domain = state.get("domain", "general")
    entries = run_summarize(source_dicts, domain=domain, model=model)

    # Insert entries into DB
    entries_created = state.get("entries_created", 0)

    with get_sync_session() as session:
        for entry_dict in entries:
            entry = Entry(
                id=entry_dict["id"],
                project_id=UUID(project_id),
                topic=entry_dict["topic"],
                title=entry_dict["title"],
                content=entry_dict["content"],
                source_id=UUID(entry_dict["source_id"]) if entry_dict.get("source_id") else None,
            )
            session.merge(entry)  # idempotent — handles re-runs after crash

            # Also populate the many-to-many join table
            if entry_dict.get("source_id"):
                existing = session.execute(
                    select(entry_sources.c.source_id).where(
                        entry_sources.c.entry_id == entry_dict["id"],
                        entry_sources.c.entry_project_id == UUID(project_id),
                        entry_sources.c.source_id == UUID(entry_dict["source_id"]),
                    )
                ).scalar_one_or_none()
                if existing is None:
                    session.execute(
                        entry_sources.insert().values(
                            entry_id=entry_dict["id"],
                            entry_project_id=UUID(project_id),
                            source_id=UUID(entry_dict["source_id"]),
                        )
                    )
        session.commit()

    entries_created += len(entries)

    return {
        "entries_created": entries_created,
        "current_batch": current_batch + 1,
    }


def should_continue_summarizing(state: IngestState) -> str:
    """Check if there are more batches to summarize."""
    if state.get("errors"):
        return END
    if state["current_batch"] < state["total_batches"]:
        return "summarize_batch"
    return END


# Build the graph
builder = StateGraph(IngestState)
builder.add_node("init_project", init_project)
builder.add_node("fetch_sources", fetch_sources)
builder.add_node("summarize_batch", summarize_batch)

builder.set_entry_point("init_project")
builder.add_edge("init_project", "fetch_sources")
builder.add_edge("fetch_sources", "summarize_batch")
builder.add_conditional_edges("summarize_batch", should_continue_summarizing)

ingest_graph = builder.compile()
