"""Pipeline trigger API routes."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from langgraph.types import Command

from reasons_service.db.connection import get_session, get_sync_session
from reasons_service.db.models import PipelineRun, Project
from reasons_service.rms import api as rms_api
from reasons_service.graphs.assessment import assessment_graph
from reasons_service.graphs.beliefs import get_beliefs_graph
from reasons_service.graphs.ingest import ingest_graph

router = APIRouter(prefix="/api/projects/{project_id}", tags=["pipeline"])


class IngestRequest(BaseModel):
    url: str
    depth: int = 2
    delay: float = 1.0
    selector: str = "main,article,.content,body"
    include: str | None = None
    exclude: str | None = None
    use_sitemap: bool = False
    model: str | None = None
    batch_size: int = 10


class ProposeRequest(BaseModel):
    batch_size: int = 5
    model: str | None = None


class ReviewRequest(BaseModel):
    decisions: dict  # {belief_id: "accept"|"reject"}


class CoverageRequest(BaseModel):
    objectives: list[dict]  # [{domain, text}]
    model: str | None = None


class ExamRequest(BaseModel):
    questions: list[dict]  # [{text, choices, correct, objective}]
    model: str | None = None


def _run_ingest(project_id: str, data: dict, run_id: str):
    """Run the ingest graph synchronously (called from background task)."""
    state = {
        "project_id": project_id,
        "domain": "",
        "url": data["url"],
        "depth": data.get("depth", 2),
        "delay": data.get("delay", 1.0),
        "selector": data.get("selector", "main,article,.content,body"),
        "sources_fetched": 0,
        "entries_created": 0,
        "current_batch": 0,
        "total_batches": 0,
        "errors": [],
    }

    # Add optional fields
    if data.get("include"):
        state["include"] = data["include"]
    if data.get("exclude"):
        state["exclude"] = data["exclude"]
    if data.get("use_sitemap"):
        state["use_sitemap"] = data["use_sitemap"]
    if data.get("model"):
        state["model"] = data["model"]
    if data.get("batch_size"):
        state["batch_size"] = data["batch_size"]

    try:
        result = ingest_graph.invoke(state)

        # Update pipeline run with results
        with get_sync_session() as session:
            run = session.get(PipelineRun, UUID(run_id))
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                run.progress = {
                    "sources_fetched": result.get("sources_fetched", 0),
                    "entries_created": result.get("entries_created", 0),
                }
                if result.get("errors"):
                    run.error = "; ".join(result["errors"])
                    run.status = "error"
                session.commit()
    except Exception as e:
        with get_sync_session() as session:
            run = session.get(PipelineRun, UUID(run_id))
            if run:
                run.status = "error"
                run.error = str(e)
                run.completed_at = datetime.now(timezone.utc)
                session.commit()


@router.post("/ingest")
async def start_ingest(
    project_id: UUID,
    data: IngestRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Start the ingest pipeline (fetch + summarize)."""
    # Verify project exists
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Create pipeline run record
    run = PipelineRun(
        project_id=project_id,
        graph_name="ingest",
        thread_id=str(uuid4()),
        status="running",
        progress={},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    # Run graph in background
    background_tasks.add_task(
        _run_ingest, str(project_id), data.model_dump(), str(run.id)
    )

    return {
        "status": "started",
        "run_id": str(run.id),
        "thread_id": run.thread_id,
    }


@router.get("/pipeline/{run_id}")
async def get_pipeline_status(
    project_id: UUID,
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Get the status of a pipeline run."""
    run = await session.get(PipelineRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(status_code=404, detail="Pipeline run not found")

    return {
        "id": str(run.id),
        "graph": run.graph_name,
        "status": run.status,
        "progress": run.progress,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }


def _run_propose(project_id: str, data: dict, run_id: str, thread_id: str):
    """Run the beliefs graph until interrupt (called from background task)."""
    state = {
        "project_id": project_id,
        "proposed_beliefs": [],
        "review_decisions": {},
        "accepted_count": 0,
        "rejected_count": 0,
        "errors": [],
    }
    if data.get("batch_size"):
        state["batch_size"] = data["batch_size"]
    if data.get("model"):
        state["model"] = data["model"]

    config = {"configurable": {"thread_id": thread_id}}

    try:
        # Graph runs propose_beliefs then pauses at interrupt() in human_review
        get_beliefs_graph().invoke(state, config=config)

        # If we get here, graph hit interrupt — update status
        with get_sync_session() as session:
            run = session.get(PipelineRun, UUID(run_id))
            if run:
                run.status = "awaiting_review"
                run.progress = {"phase": "review"}
                session.commit()
    except Exception as e:
        with get_sync_session() as session:
            run = session.get(PipelineRun, UUID(run_id))
            if run:
                run.status = "error"
                run.error = str(e)
                run.completed_at = datetime.now(timezone.utc)
                session.commit()


@router.post("/beliefs/propose")
async def propose_beliefs(
    project_id: UUID,
    data: ProposeRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Start the beliefs extraction pipeline."""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    thread_id = str(uuid4())
    run = PipelineRun(
        project_id=project_id,
        graph_name="beliefs",
        thread_id=thread_id,
        status="running",
        progress={"phase": "proposing"},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    background_tasks.add_task(
        _run_propose, str(project_id), data.model_dump(), str(run.id), thread_id
    )

    return {
        "status": "started",
        "run_id": str(run.id),
        "thread_id": thread_id,
    }


@router.get("/beliefs/proposed")
async def get_proposed_beliefs(project_id: UUID):
    """Get proposed beliefs awaiting review (OUT nodes from the latest proposal)."""
    result = await asyncio.to_thread(
        rms_api.list_nodes, project_id, status="OUT"
    )
    return {
        "beliefs": [
            {
                "id": n["id"],
                "text": n["text"],
                "truth_value": n["truth_value"],
            }
            for n in result["nodes"]
        ]
    }


@router.post("/beliefs/review")
async def submit_review(
    project_id: UUID,
    data: ReviewRequest,
    session: AsyncSession = Depends(get_session),
):
    """Submit belief review decisions (resumes interrupted beliefs graph).

    Finds the paused beliefs graph thread and resumes it with the decisions.
    """
    # Find the awaiting_review pipeline run to get thread_id
    result = await session.execute(
        select(PipelineRun).where(
            PipelineRun.project_id == project_id,
            PipelineRun.graph_name == "beliefs",
            PipelineRun.status == "awaiting_review",
        ).order_by(PipelineRun.started_at.desc())
    )
    run = result.scalars().first()
    if not run:
        raise HTTPException(
            status_code=404,
            detail="No beliefs pipeline awaiting review",
        )

    thread_id = run.thread_id
    config = {"configurable": {"thread_id": thread_id}}

    # Resume the graph — interrupt() returns data.decisions to human_review node,
    # then accept_beliefs runs and updates claims in DB
    try:
        graph_result = await asyncio.to_thread(
            get_beliefs_graph().invoke,
            Command(resume=data.decisions), config,
        )

        # Update pipeline run
        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        run.progress = {
            "phase": "completed",
            "accepted": graph_result.get("accepted_count", 0),
            "rejected": graph_result.get("rejected_count", 0),
        }
        await session.commit()

        return {
            "status": "completed",
            "accepted": graph_result.get("accepted_count", 0),
            "rejected": graph_result.get("rejected_count", 0),
        }
    except Exception as e:
        run.status = "error"
        run.error = str(e)
        run.completed_at = datetime.now(timezone.utc)
        await session.commit()
        raise HTTPException(status_code=500, detail=str(e))


def _run_assessment(project_id: str, assessment_type: str, data: dict, run_id: str):
    """Run the assessment graph synchronously (called from background task)."""
    state = {
        "project_id": project_id,
        "assessment_type": assessment_type,
        "objectives": data.get("objectives", []),
        "questions": data.get("questions", []),
        "beliefs_context": "",
        "results": [],
        "score": {},
        "nogoods_discovered": [],
    }
    if data.get("model"):
        state["model"] = data["model"]
    if data.get("domain"):
        state["domain"] = data["domain"]

    try:
        result = assessment_graph.invoke(state)

        with get_sync_session() as session:
            run = session.get(PipelineRun, UUID(run_id))
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                run.progress = {"score": result.get("score", {})}
                session.commit()
    except Exception as e:
        with get_sync_session() as session:
            run = session.get(PipelineRun, UUID(run_id))
            if run:
                run.status = "error"
                run.error = str(e)
                run.completed_at = datetime.now(timezone.utc)
                session.commit()


@router.post("/assess/coverage")
async def start_coverage(
    project_id: UUID,
    data: CoverageRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Run certification coverage analysis."""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run = PipelineRun(
        project_id=project_id,
        graph_name="assessment",
        thread_id=str(uuid4()),
        status="running",
        progress={"type": "coverage"},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    background_tasks.add_task(
        _run_assessment,
        str(project_id),
        "coverage",
        {**data.model_dump(), "domain": project.domain},
        str(run.id),
    )

    return {
        "status": "started",
        "run_id": str(run.id),
    }


@router.post("/assess/exam")
async def start_exam(
    project_id: UUID,
    data: ExamRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    """Run practice exam."""
    project = await session.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    run = PipelineRun(
        project_id=project_id,
        graph_name="assessment",
        thread_id=str(uuid4()),
        status="running",
        progress={"type": "exam"},
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    background_tasks.add_task(
        _run_assessment,
        str(project_id),
        "exam",
        {**data.model_dump(), "domain": project.domain},
        str(run.id),
    )

    return {
        "status": "started",
        "run_id": str(run.id),
    }
