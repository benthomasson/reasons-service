"""Data access API routes — sources, entries, claims, search."""

import asyncio
from uuid import UUID

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from reasons_service.auth import verify_auth, verify_auth_or_public
from reasons_service.rbac import Action, Role, UserInfo, require_action
from pydantic import BaseModel
from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from reasons_service.chunking import chunk_markdown
from reasons_service.config import settings
from reasons_service.db.connection import get_session, get_sync_session
from reasons_service.db.models import Domain, Entry, Proposal, Source, SourceChunk, Summary, Topic, User, entry_sources, summary_sources
from reasons_service.db.search import fts_clause
from reasons_service.rms import api as rms_api

router = APIRouter(prefix="/api/domains/{domain_id}", tags=["data"])

MAX_PAGE_LIMIT = 1000


def _clamp_pagination(limit: int, offset: int) -> tuple[int, int]:
    return max(1, min(limit, MAX_PAGE_LIMIT)), max(0, offset)


@router.get("/sources")
async def list_sources(
    domain_id: UUID,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    limit, offset = _clamp_pagination(limit, offset)
    base = select(Source).where(Source.domain_id == domain_id)
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0
    result = await session.execute(
        select(Source.id, Source.slug, Source.url, Source.word_count, Source.fetched_at)
        .where(Source.domain_id == domain_id)
        .order_by(Source.fetched_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "items": [dict(r._mapping) for r in result.all()],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/sources/{slug}")
async def get_source(domain_id: UUID, slug: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Source).where(Source.domain_id == domain_id, Source.slug == slug)
    )
    source = result.scalar_one_or_none()
    if not source:
        return {"error": "Source not found"}
    # Count linked entries
    entry_count_result = await session.execute(
        select(func.count()).select_from(entry_sources).where(
            entry_sources.c.source_id == source.id
        )
    )
    return {
        "slug": source.slug,
        "url": source.url,
        "word_count": source.word_count,
        "entry_count": entry_count_result.scalar(),
        "fetched_at": source.fetched_at.isoformat() if source.fetched_at else None,
    }


@router.get("/sources/{slug}/entries")
async def list_source_entries(
    domain_id: UUID,
    slug: str,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List all entries linked to a source."""
    limit, offset = _clamp_pagination(limit, offset)
    source = await session.execute(
        select(Source.id).where(Source.domain_id == domain_id, Source.slug == slug)
    )
    source_id = source.scalar_one_or_none()
    if source_id is None:
        return {"error": "Source not found"}
    base = (
        select(Entry.id, Entry.topic, Entry.title, Entry.created_at)
        .join(entry_sources, (entry_sources.c.entry_id == Entry.id) & (entry_sources.c.entry_domain_id == Entry.domain_id))
        .where(entry_sources.c.source_id == source_id)
    )
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0
    result = await session.execute(base.order_by(Entry.created_at.desc()).limit(limit).offset(offset))
    return {
        "items": [dict(r._mapping) for r in result.all()],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/entries")
async def list_entries(
    domain_id: UUID,
    topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    limit, offset = _clamp_pagination(limit, offset)
    base = select(Entry).where(Entry.domain_id == domain_id)
    if topic:
        base = base.where(Entry.topic == topic)
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0
    q = base.options(selectinload(Entry.sources)).order_by(Entry.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(q)
    entries = result.scalars().all()
    return {
        "items": [
            {
                "id": e.id,
                "topic": e.topic,
                "title": e.title,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "source_slugs": [s.slug for s in e.sources],
            }
            for e in entries
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/entries/{entry_id}")
async def get_entry(domain_id: UUID, entry_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Entry)
        .options(selectinload(Entry.sources))
        .where(Entry.domain_id == domain_id, Entry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        return {"error": "Entry not found"}
    return {
        "id": entry.id,
        "topic": entry.topic,
        "title": entry.title,
        "content": entry.content,
        "created_at": entry.created_at.isoformat(),
        "sources": [
            {"slug": s.slug, "url": s.url, "word_count": s.word_count}
            for s in entry.sources
        ],
    }


@router.get("/summaries")
async def list_summaries(
    domain_id: UUID,
    topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    limit, offset = _clamp_pagination(limit, offset)
    base = select(Summary).where(Summary.domain_id == domain_id)
    if topic:
        base = base.where(Summary.topic == topic)
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0
    q = base.options(selectinload(Summary.sources)).order_by(Summary.created_at.desc()).limit(limit).offset(offset)
    result = await session.execute(q)
    summaries = result.scalars().all()
    return {
        "items": [
            {
                "id": s.id,
                "topic": s.topic,
                "title": s.title,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "source_slugs": [src.slug for src in s.sources],
            }
            for s in summaries
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/summaries/{summary_id}")
async def get_summary(domain_id: UUID, summary_id: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Summary)
        .options(selectinload(Summary.sources))
        .where(Summary.domain_id == domain_id, Summary.id == summary_id)
    )
    summary = result.scalar_one_or_none()
    if not summary:
        return {"error": "Summary not found"}
    return {
        "id": summary.id,
        "topic": summary.topic,
        "title": summary.title,
        "content": summary.content,
        "created_at": summary.created_at.isoformat(),
        "sources": [
            {"slug": s.slug, "url": s.url, "word_count": s.word_count}
            for s in summary.sources
        ],
    }


@router.get("/beliefs")
async def list_beliefs(
    domain_id: UUID,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: UserInfo = Depends(verify_auth_or_public),
):
    limit, offset = _clamp_pagination(limit, offset)
    result = await asyncio.to_thread(
        rms_api.list_nodes, domain_id, status=status, visible_to=user.visible_tags
    )
    nodes = result.get("nodes", [])
    total = len(nodes)
    page = nodes[offset:offset + limit]
    return {
        "items": page,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/beliefs/status")
async def beliefs_status(domain_id: UUID, user: UserInfo = Depends(verify_auth_or_public)):
    result = await asyncio.to_thread(rms_api.get_status, domain_id, visible_to=user.visible_tags)
    return result


@router.get("/issues")
async def find_issues(domain_id: UUID, user: UserInfo = Depends(verify_auth_or_public)):
    """Find issues in the belief network: gated beliefs and negative candidates."""
    vt = user.visible_tags
    gated = await asyncio.to_thread(rms_api.list_gated, domain_id, visible_to=vt)
    negative = await asyncio.to_thread(rms_api.list_negative_candidates, domain_id, visible_to=vt)
    return {"gated": gated, "negative": negative}


# --- Proposal endpoints (must be before /beliefs/{node_id} to avoid path capture) ---


async def _validate_tags(
    tags: list[str],
    domain_id: UUID,
    user: UserInfo,
    session: AsyncSession,
) -> None:
    """Validate proposed tags against domain allowlist and user writable_tags."""
    if not tags:
        return
    result = await session.execute(select(Domain.allowed_tags).where(Domain.id == domain_id))
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Domain not found")
    allowed = row.allowed_tags or []
    if allowed:
        invalid = set(tags) - set(allowed)
        if invalid:
            raise HTTPException(status_code=400, detail=f"Tags not in domain allowlist: {sorted(invalid)}")
    if user.role != Role.ADMIN and user.writable_tags is not None:
        forbidden = set(tags) - set(user.writable_tags)
        if forbidden:
            raise HTTPException(status_code=403, detail=f"You lack writable_tags for: {sorted(forbidden)}")


class ProposalCreate(BaseModel):
    proposal_type: str
    target_node_id: str | None = None
    proposed_text: str | None = None
    proposed_tags: list[str] | None = None
    rationale: str | None = None


class ProposalReview(BaseModel):
    status: str
    review_notes: str | None = None


@router.post(
    "/beliefs/propose",
    dependencies=[Depends(verify_auth), Depends(require_action(Action.PROPOSE_BELIEFS))],
)
async def propose_belief(
    domain_id: UUID,
    data: ProposalCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Create a belief change proposal."""
    if data.proposal_type not in ("add", "retract", "nogood", "modify"):
        raise HTTPException(status_code=400, detail=f"Invalid proposal_type: {data.proposal_type}")
    if data.proposal_type == "add" and not data.proposed_text:
        raise HTTPException(status_code=400, detail="proposed_text is required for 'add' proposals")
    if data.proposal_type in ("retract", "modify") and not data.target_node_id:
        raise HTTPException(status_code=400, detail="target_node_id is required for 'retract'/'modify' proposals")
    if data.proposal_type == "modify" and not data.proposed_text:
        raise HTTPException(status_code=400, detail="proposed_text is required for 'modify' proposals")

    user = request.state.user
    tags = sorted(set(data.proposed_tags)) if data.proposed_tags else []
    if tags:
        await _validate_tags(tags, domain_id, user, session)
    proposal = Proposal(
        domain_id=domain_id,
        proposal_type=data.proposal_type,
        target_node_id=data.target_node_id,
        proposed_text=data.proposed_text,
        proposed_tags=tags,
        rationale=data.rationale,
        proposed_by=user.identity,
    )
    session.add(proposal)
    await session.commit()
    await session.refresh(proposal)
    return {
        "id": str(proposal.id),
        "proposal_type": proposal.proposal_type,
        "status": proposal.status,
        "proposed_by": proposal.proposed_by,
        "created_at": proposal.created_at.isoformat(),
    }


@router.get("/beliefs/proposed")
async def list_proposals(
    domain_id: UUID,
    status: str | None = "pending",
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List belief change proposals."""
    limit, offset = _clamp_pagination(limit, offset)
    base = select(Proposal).where(Proposal.domain_id == domain_id)
    if status:
        base = base.where(Proposal.status == status)
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0
    result = await session.execute(base.order_by(Proposal.created_at.desc()).limit(limit).offset(offset))
    return {
        "items": [
            {
                "id": str(p.id),
                "proposal_type": p.proposal_type,
                "target_node_id": p.target_node_id,
                "proposed_text": p.proposed_text,
                "proposed_tags": p.proposed_tags or [],
                "rationale": p.rationale,
                "proposed_by": p.proposed_by,
                "status": p.status,
                "review_notes": p.review_notes,
                "reviewed_by": p.reviewed_by,
                "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
                "created_at": p.created_at.isoformat(),
            }
            for p in result.scalars().all()
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.put(
    "/beliefs/proposed/{proposal_id}",
    dependencies=[Depends(verify_auth), Depends(require_action(Action.REVIEW_PROPOSALS))],
)
async def review_proposal(
    domain_id: UUID,
    proposal_id: UUID,
    data: ProposalReview,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Accept or reject a proposal (reviewer role only)."""
    if data.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}. Must be 'approved' or 'rejected'.")

    result = await session.execute(
        select(Proposal).where(Proposal.id == proposal_id, Proposal.domain_id == domain_id)
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal already {proposal.status}")

    user = request.state.user
    proposal.status = data.status
    proposal.review_notes = data.review_notes
    proposal.reviewed_by = user.identity
    proposal.reviewed_at = datetime.now(timezone.utc)
    await session.commit()
    return {
        "id": str(proposal.id),
        "status": proposal.status,
        "review_notes": proposal.review_notes,
        "reviewed_by": proposal.reviewed_by,
        "reviewed_at": proposal.reviewed_at.isoformat(),
    }


@router.get("/beliefs/{node_id}")
async def get_belief(domain_id: UUID, node_id: str, user: UserInfo = Depends(verify_auth_or_public)):
    try:
        result = await asyncio.to_thread(rms_api.show_node, domain_id, node_id, visible_to=user.visible_tags)
    except KeyError:
        return {"error": "Belief not found", "id": node_id}
    except PermissionError:
        return {"error": "Access denied", "id": node_id}
    return result


@router.get("/beliefs/{node_id}/explain")
async def explain_belief(domain_id: UUID, node_id: str, user: UserInfo = Depends(verify_auth_or_public)):
    try:
        result = await asyncio.to_thread(rms_api.explain_node, domain_id, node_id, visible_to=user.visible_tags)
    except KeyError:
        return {"error": "Belief not found", "id": node_id}
    except PermissionError:
        return {"error": "Access denied", "id": node_id}
    return result


@router.get("/beliefs/{node_id}/what-if")
async def what_if_belief(domain_id: UUID, node_id: str, action: str = "retract"):
    if action == "assert":
        result = await asyncio.to_thread(rms_api.what_if_assert, domain_id, node_id)
    else:
        result = await asyncio.to_thread(rms_api.what_if_retract, domain_id, node_id)
    return result


@router.get("/search")
async def search(
    domain_id: UUID,
    q: str = Query(..., min_length=1),
    user: UserInfo = Depends(verify_auth_or_public),
    session: AsyncSession = Depends(get_session),
):
    """Full-text search across entries, beliefs, and source chunks.

    Uses OR-based tsquery with ts_rank_cd ranking on PostgreSQL,
    LIKE-based OR search on SQLite.
    """
    # Search entries
    entry_text = "coalesce(title, '') || ' ' || content"
    ew, eo, ep = fts_clause(entry_text, q)
    ep["pid"] = str(domain_id)
    order_clause = f"ORDER BY {eo}" if eo else ""
    entry_results = await session.execute(
        text(
            f"SELECT id, title, topic FROM entries "
            f"WHERE domain_id = :pid AND {ew} "
            f"{order_clause} LIMIT 20"
        ),
        ep,
    )

    # Search RMS beliefs (routed through rms_api for SQLite compatibility)
    belief_rows = await asyncio.to_thread(rms_api.search_beliefs_fts, domain_id, q, 20, visible_to=user.visible_tags)

    # Search source chunks
    cw, co, cp = fts_clause("c.text", q)
    cp["pid"] = str(domain_id)
    chunk_order = f"ORDER BY {co}" if co else ""
    # Use substr() instead of left() for SQLite compatibility
    snippet_expr = "substr(c.text, 1, 500)" if settings.db_backend == "sqlite" else "left(c.text, 500)"
    chunk_results = await session.execute(
        text(
            f"SELECT c.id, c.section, s.slug AS source_slug, s.url AS source_url, "
            f"  {snippet_expr} AS snippet "
            f"FROM source_chunks c "
            f"JOIN sources s ON s.id = c.source_id "
            f"WHERE c.domain_id = :pid AND {cw} "
            f"{chunk_order} LIMIT 20"
        ),
        cp,
    )

    return {
        "entries": [dict(r._mapping) for r in entry_results.all()],
        "beliefs": [{"id": b["id"], "text": b["text"], "truth_value": b.get("truth_value", "IN")} for b in belief_rows],
        "sources": [dict(r._mapping) for r in chunk_results.all()],
    }


@router.get("/deep-search")
async def deep_search(
    domain_id: UUID,
    q: str = Query(..., min_length=1),
):
    """Dual-path retrieval with IDF ranking — no LLM, just structured context.

    Runs the same retrieval strategy as the LLM-powered /ask endpoint:
    1. TMS belief search with IDF re-ranking (20 results)
    2. Source chunk FTS with IDF re-ranking (10 results)

    Returns pre-ranked, pre-formatted results ready for client-side synthesis.
    """
    from reasons_service.db.search import quick_belief_search, search_source_chunks

    (belief_ctx, belief_sources), (chunk_ctx, chunk_sources) = await asyncio.gather(
        asyncio.to_thread(quick_belief_search, domain_id, q, 20),
        asyncio.to_thread(search_source_chunks, domain_id, q, 10),
    )

    return {
        "query": q,
        "belief_context": belief_ctx,
        "chunk_context": chunk_ctx,
        "beliefs": [
            {"cite_key": s.cite_key, "label": s.label, "slug": s.slug,
             "url": s.url, "category": s.category}
            for s in belief_sources
        ],
        "sources": [
            {"cite_key": s.cite_key, "label": s.label, "slug": s.slug,
             "url": s.url, "category": s.category}
            for s in chunk_sources
        ],
        "belief_count": len(belief_sources),
        "source_count": len(chunk_sources),
    }


# --- Import endpoints ---


class SourceImport(BaseModel):
    slug: str
    url: str | None = None
    content: str
    word_count: int | None = None


class SourcesImportRequest(BaseModel):
    sources: list[SourceImport]


class EntryImport(BaseModel):
    id: str
    topic: str
    title: str | None = None
    content: str
    path: str | None = None


class EntriesImportRequest(BaseModel):
    entries: list[EntryImport]


class SummaryImport(BaseModel):
    id: str
    topic: str
    title: str | None = None
    content: str
    path: str | None = None


class SummariesImportRequest(BaseModel):
    summaries: list[SummaryImport]


class ClaimImport(BaseModel):
    id: str
    text: str
    status: str = "IN"
    source: str | None = None
    source_hash: str | None = None


class ClaimsImportRequest(BaseModel):
    claims: list[ClaimImport]


@router.post("/import/sources", dependencies=[Depends(verify_auth)])
async def import_sources(
    domain_id: UUID,
    data: SourcesImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Bulk import sources from a file-based expert repo."""
    imported = 0
    skipped = 0

    for s in data.sources:
        existing = await session.execute(
            select(Source.id).where(Source.domain_id == domain_id, Source.slug == s.slug)
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        source = Source(
            domain_id=domain_id,
            slug=s.slug,
            url=s.url,
            content=s.content,
            word_count=s.word_count,
        )
        session.add(source)
        await session.flush()

        for c in chunk_markdown(s.content):
            session.add(SourceChunk(
                domain_id=domain_id,
                source_id=source.id,
                chunk_index=c["chunk_index"],
                section=c["section"],
                text=c["text"],
            ))
        imported += 1

    await session.commit()
    return {"imported": imported, "skipped": skipped}


@router.post("/import/entries", dependencies=[Depends(verify_auth)])
async def import_entries(
    domain_id: UUID,
    data: EntriesImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Bulk import entries from a file-based expert repo."""
    imported = 0
    skipped = 0
    linked = 0

    # Pre-load source slug→id map for auto-matching
    source_result = await session.execute(
        select(Source.slug, Source.id).where(Source.domain_id == domain_id)
    )
    source_map = {row.slug: row.id for row in source_result.all()}

    for e in data.entries:
        # Check if already exists
        existing = await session.execute(
            select(Entry.id).where(Entry.domain_id == domain_id, Entry.id == e.id)
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        entry = Entry(
            id=e.id,
            domain_id=domain_id,
            topic=e.topic,
            title=e.title,
            content=e.content,
            metadata_={"imported_from": e.path} if e.path else None,
        )
        session.add(entry)
        imported += 1

        # Auto-match entry to source by topic == slug
        if e.topic in source_map:
            await session.flush()
            await session.execute(
                insert(entry_sources).values(
                    entry_id=e.id,
                    entry_domain_id=domain_id,
                    source_id=source_map[e.topic],
                )
            )
            linked += 1

    await session.commit()
    return {"imported": imported, "skipped": skipped, "linked": linked}


@router.post("/import/summaries", dependencies=[Depends(verify_auth)])
async def import_summaries(
    domain_id: UUID,
    data: SummariesImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Bulk import summaries from a file-based expert repo."""
    imported = 0
    skipped = 0
    linked = 0

    source_result = await session.execute(
        select(Source.slug, Source.id).where(Source.domain_id == domain_id)
    )
    source_map = {row.slug: row.id for row in source_result.all()}

    for s in data.summaries:
        existing = await session.execute(
            select(Summary.id).where(Summary.domain_id == domain_id, Summary.id == s.id)
        )
        if existing.scalar_one_or_none() is not None:
            skipped += 1
            continue

        summary = Summary(
            id=s.id,
            domain_id=domain_id,
            topic=s.topic,
            title=s.title,
            content=s.content,
            metadata_={"imported_from": s.path} if s.path else None,
        )
        session.add(summary)
        imported += 1

        if s.topic in source_map:
            await session.flush()
            await session.execute(
                insert(summary_sources).values(
                    summary_id=s.id,
                    summary_domain_id=domain_id,
                    source_id=source_map[s.topic],
                )
            )
            linked += 1

    await session.commit()
    return {"imported": imported, "skipped": skipped, "linked": linked}


@router.post("/import/beliefs", dependencies=[Depends(verify_auth)])
async def import_beliefs(
    domain_id: UUID,
    data: ClaimsImportRequest,
):
    """Bulk import beliefs into RMS from a file-based expert repo."""

    def _do_import():
        imported = 0
        skipped = 0

        # Check existing nodes
        existing_status = rms_api.get_status(domain_id)
        existing_ids = {n["id"] for n in existing_status["nodes"]}

        for c in data.claims:
            if c.id in existing_ids:
                skipped += 1
                continue

            rms_api.add_node(
                domain_id,
                node_id=c.id,
                text=c.text,
                source=c.source or "",
            )

            # Match original status
            if c.status == "OUT":
                rms_api.retract_node(domain_id, c.id)

            imported += 1

        return {"imported": imported, "skipped": skipped}

    return await asyncio.to_thread(_do_import)


@router.post("/link-entries-sources", dependencies=[Depends(verify_auth)])
async def link_entries_sources(
    domain_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Backfill entry-source links by matching entry.topic to source.slug.

    Also migrates any existing source_id FK values into the join table.
    """
    linked = 0
    already_linked = 0
    migrated = 0

    # 1. Migrate existing source_id FK values into join table
    entries_with_fk = await session.execute(
        select(Entry.id, Entry.domain_id, Entry.source_id)
        .where(Entry.domain_id == domain_id, Entry.source_id.isnot(None))
    )
    for row in entries_with_fk.all():
        existing = await session.execute(
            select(entry_sources.c.source_id).where(
                entry_sources.c.entry_id == row.id,
                entry_sources.c.entry_domain_id == row.domain_id,
                entry_sources.c.source_id == row.source_id,
            )
        )
        if existing.scalar_one_or_none() is None:
            await session.execute(
                insert(entry_sources).values(
                    entry_id=row.id,
                    entry_domain_id=row.domain_id,
                    source_id=row.source_id,
                )
            )
            migrated += 1

    # 2. Auto-match unlinked entries by topic == slug
    source_result = await session.execute(
        select(Source.slug, Source.id).where(Source.domain_id == domain_id)
    )
    source_map = {row.slug: row.id for row in source_result.all()}

    all_entries = await session.execute(
        select(Entry.id, Entry.domain_id, Entry.topic)
        .where(Entry.domain_id == domain_id)
    )
    for row in all_entries.all():
        if row.topic not in source_map:
            continue
        # Check if link already exists
        existing = await session.execute(
            select(entry_sources.c.source_id).where(
                entry_sources.c.entry_id == row.id,
                entry_sources.c.entry_domain_id == row.domain_id,
                entry_sources.c.source_id == source_map[row.topic],
            )
        )
        if existing.scalar_one_or_none() is not None:
            already_linked += 1
            continue
        await session.execute(
            insert(entry_sources).values(
                entry_id=row.id,
                entry_domain_id=row.domain_id,
                source_id=source_map[row.topic],
            )
        )
        linked += 1

    await session.commit()
    return {"linked": linked, "migrated": migrated, "already_linked": already_linked}


@router.post("/chunk-sources", dependencies=[Depends(verify_auth)])
async def chunk_sources(
    domain_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Backfill source_chunks for all sources that haven't been chunked yet."""
    sources = await session.execute(
        select(Source).where(Source.domain_id == domain_id)
    )
    chunked = 0
    total_chunks = 0
    for source in sources.scalars().all():
        existing = await session.execute(
            select(SourceChunk).where(SourceChunk.source_id == source.id).limit(1)
        )
        if existing.scalar_one_or_none():
            continue
        chunks = chunk_markdown(source.content)
        for c in chunks:
            session.add(SourceChunk(
                domain_id=domain_id,
                source_id=source.id,
                chunk_index=c["chunk_index"],
                section=c["section"],
                text=c["text"],
            ))
        chunked += 1
        total_chunks += len(chunks)
    await session.commit()
    return {"sources_chunked": chunked, "total_chunks": total_chunks}


# --- Topic endpoints ---


@router.get("/topics")
async def list_topics(
    domain_id: UUID,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    """List stored topics for a domain."""
    limit, offset = _clamp_pagination(limit, offset)
    base = select(Topic).where(Topic.domain_id == domain_id)
    total_result = await session.execute(select(func.count()).select_from(base.subquery()))
    total = total_result.scalar() or 0
    result = await session.execute(
        base.order_by(Topic.belief_count.desc()).limit(limit).offset(offset)
    )
    return {
        "items": [
            {
                "name": t.name,
                "label": t.label,
                "description": t.description,
                "belief_count": t.belief_count,
                "curated": t.curated,
            }
            for t in result.scalars().all()
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/topics/generate", dependencies=[Depends(verify_auth)])
async def generate_topics(
    domain_id: UUID,
    session: AsyncSession = Depends(get_session),
):
    """Generate topics from belief node IDs (word frequency) and store them.

    Replaces non-curated topics; keeps any manually curated ones.
    """
    raw = await asyncio.to_thread(rms_api.topics, domain_id, 50)

    existing = await session.execute(
        select(Topic).where(Topic.domain_id == domain_id)
    )
    existing_map = {t.name: t for t in existing.scalars().all()}

    generated = 0
    kept_curated = 0
    for item in raw.get("topics", []):
        name = item["topic"]
        count = item["count"]
        if name in existing_map:
            t = existing_map[name]
            if t.curated:
                t.belief_count = count
                kept_curated += 1
            else:
                t.belief_count = count
                generated += 1
        else:
            session.add(Topic(
                domain_id=domain_id,
                name=name,
                belief_count=count,
            ))
            generated += 1

    # Remove stale non-curated topics not in the new set
    new_names = {item["topic"] for item in raw.get("topics", [])}
    for name, t in existing_map.items():
        if name not in new_names and not t.curated:
            await session.delete(t)

    await session.commit()
    return {"generated": generated, "kept_curated": kept_curated, "total_nodes": raw.get("total_nodes", 0)}


class TopicImport(BaseModel):
    name: str
    label: str | None = None
    description: str | None = None
    belief_count: int = 0


class TopicsImportRequest(BaseModel):
    topics: list[TopicImport]


@router.post("/import/topics", dependencies=[Depends(verify_auth)])
async def import_topics(
    domain_id: UUID,
    data: TopicsImportRequest,
    session: AsyncSession = Depends(get_session),
):
    """Bulk import pre-curated topics."""
    imported = 0
    updated = 0

    existing = await session.execute(
        select(Topic).where(Topic.domain_id == domain_id)
    )
    existing_map = {t.name: t for t in existing.scalars().all()}

    for item in data.topics:
        if item.name in existing_map:
            t = existing_map[item.name]
            t.label = item.label
            t.description = item.description
            t.belief_count = item.belief_count
            t.curated = True
            updated += 1
        else:
            session.add(Topic(
                domain_id=domain_id,
                name=item.name,
                label=item.label,
                description=item.description,
                belief_count=item.belief_count,
                curated=True,
            ))
            imported += 1

    await session.commit()
    return {"imported": imported, "updated": updated}



# --- Access tag management ---

tag_router = APIRouter(prefix="/api", tags=["access-control"])


@tag_router.get("/users/{email}/tags", dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))])
async def get_user_tags(email: str, session: AsyncSession = Depends(get_session)):
    """View a user's visible_tags and writable_tags."""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "email": user.email,
        "visible_tags": user.visible_tags or [],
        "writable_tags": user.writable_tags or [],
    }


class SetTagsRequest(BaseModel):
    visible_tags: list[str]


class SetWritableTagsRequest(BaseModel):
    writable_tags: list[str]


@tag_router.put("/users/{email}/tags", dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))])
async def set_user_tags(email: str, data: SetTagsRequest, session: AsyncSession = Depends(get_session)):
    """Set a user's visible_tags (admin only)."""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.visible_tags = sorted(set(data.visible_tags))
    await session.commit()
    return {"email": user.email, "visible_tags": user.visible_tags}


@tag_router.put("/users/{email}/writable-tags", dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))])
async def set_user_writable_tags(email: str, data: SetWritableTagsRequest, session: AsyncSession = Depends(get_session)):
    """Set a user's writable_tags (admin only)."""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.writable_tags = sorted(set(data.writable_tags))
    await session.commit()
    return {"email": user.email, "writable_tags": user.writable_tags}


# --- Domain allowed-tags management ---


class SetAllowedTagsRequest(BaseModel):
    allowed_tags: list[str]


@tag_router.get(
    "/domains/{domain_id}/allowed-tags",
    dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))],
)
async def get_allowed_tags(domain_id: UUID, session: AsyncSession = Depends(get_session)):
    """List valid tags for a domain."""
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    return {"domain_id": str(domain_id), "allowed_tags": domain.allowed_tags or []}


@tag_router.put(
    "/domains/{domain_id}/allowed-tags",
    dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))],
)
async def set_allowed_tags(domain_id: UUID, data: SetAllowedTagsRequest, session: AsyncSession = Depends(get_session)):
    """Set the tag allowlist for a domain (admin only)."""
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")
    domain.allowed_tags = sorted(set(data.allowed_tags))
    await session.commit()
    return {"domain_id": str(domain_id), "allowed_tags": domain.allowed_tags}


@tag_router.get(
    "/domains/{domain_id}/tags/audit",
    dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))],
)
async def audit_tags(domain_id: UUID, session: AsyncSession = Depends(get_session)):
    """Audit tag usage: find orphans, mismatches, and misconfigured users."""
    result = await session.execute(select(Domain).where(Domain.id == domain_id))
    domain = result.scalar_one_or_none()
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    allowed = set(domain.allowed_tags or [])

    # Tags on beliefs
    all_nodes = await asyncio.to_thread(rms_api.list_nodes, domain_id)
    belief_tags: set[str] = set()
    for node in all_nodes.get("nodes", []):
        belief_tags.update(node.get("metadata", {}).get("access_tags", []))

    # Tags on users
    users_result = await session.execute(select(User))
    all_users = users_result.scalars().all()
    user_visible_tags: set[str] = set()
    user_writable_tags: set[str] = set()
    writable_exceeds_visible = []
    for u in all_users:
        vt = set(u.visible_tags or [])
        wt = set(u.writable_tags or [])
        user_visible_tags.update(vt)
        user_writable_tags.update(wt)
        excess = wt - vt
        if excess:
            writable_exceeds_visible.append({"email": u.email, "excess_tags": sorted(excess)})

    return {
        "domain_id": str(domain_id),
        "allowed_tags": sorted(allowed),
        "belief_tags_not_in_allowlist": sorted(belief_tags - allowed) if allowed else [],
        "user_visible_tags_not_in_allowlist": sorted(user_visible_tags - allowed) if allowed else [],
        "user_writable_tags_not_in_allowlist": sorted(user_writable_tags - allowed) if allowed else [],
        "allowed_tags_unused": sorted(allowed - belief_tags - user_visible_tags - user_writable_tags),
        "users_writable_exceeds_visible": writable_exceeds_visible,
        "belief_tags_in_use": sorted(belief_tags),
        "user_visible_tags_in_use": sorted(user_visible_tags),
        "user_writable_tags_in_use": sorted(user_writable_tags),
    }


class SetBeliefTagsRequest(BaseModel):
    access_tags: list[str]


@router.put("/beliefs/{node_id}/tags", dependencies=[Depends(verify_auth), Depends(require_action(Action.ADMIN))])
async def set_belief_tags(
    domain_id: UUID,
    node_id: str,
    data: SetBeliefTagsRequest,
    user: UserInfo = Depends(verify_auth),
    session: AsyncSession = Depends(get_session),
):
    """Set access_tags on a belief (admin only). Validates against domain allowlist."""
    tags = sorted(set(data.access_tags))
    await _validate_tags(tags, domain_id, user, session)
    try:
        result = await asyncio.to_thread(rms_api.set_access_tags, domain_id, node_id, tags)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Belief not found: {node_id}")
    return result


@router.get("/beliefs/{node_id}/tags")
async def get_belief_tags(domain_id: UUID, node_id: str, user: UserInfo = Depends(verify_auth_or_public)):
    """Get access_tags for a belief, including inherited tags from dependencies."""
    try:
        result = await asyncio.to_thread(rms_api.trace_access_tags, domain_id, node_id, visible_to=user.visible_tags)
    except KeyError:
        return {"error": "Belief not found", "id": node_id}
    except PermissionError:
        return {"error": "Access denied", "id": node_id}
    return result
