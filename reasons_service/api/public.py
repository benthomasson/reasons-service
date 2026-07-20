"""Public HTML/markdown/JSON beliefs views for public domains.

No authentication required — access is gated by domain.public flag.
Designed for Cloudflare caching: plain HTML, Cache-Control headers.
"""

from __future__ import annotations

import asyncio
import html as html_mod
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Depends
from reasons_service.db.connection import get_session
from reasons_service.db.models import Entry, Domain, Source
from reasons_service.rms import api as rms_api

router = APIRouter(prefix="/public/{domain_name}", tags=["public"])
landing_router = APIRouter(prefix="/public", tags=["public"])

_templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))

_CACHE_MAX_AGE = 300  # 5 minutes


async def _resolve_public_domain(domain_name: str, session: AsyncSession) -> Domain:
    result = await session.execute(
        select(Domain).where(Domain.name == domain_name)
    )
    domain_obj = result.scalar_one_or_none()
    if not domain_obj or not domain_obj.public:
        raise HTTPException(status_code=404, detail="Domain not found")
    return domain_obj


# --- Markdown to HTML renderer (ported from agentic-mind-service) ---

def _inline(s: str) -> str:
    s = html_mod.escape(s)
    s = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', s)
    s = re.sub(r'`(.+?)`', r'<code>\1</code>', s)
    s = re.sub(r'_(.+?)_', r'<em>\1</em>', s)
    return s


def _with_links(s: str) -> str:
    parts = re.split(r'(\[.+?\]\(.+?\))', s)
    result = []
    for part in parts:
        m = re.match(r'\[(.+?)\]\((.+?)\)', part)
        if m:
            result.append(f'<a href="{html_mod.escape(m.group(2))}">{_inline(m.group(1))}</a>')
        else:
            result.append(_inline(part))
    return ''.join(result)


def _md_to_html(md: str) -> str:
    lines = md.splitlines()
    out: list[str] = []
    in_code_block = False
    in_list = False
    in_frontmatter = False
    fm_count = 0

    for line in lines:
        if line.strip() == "---":
            fm_count += 1
            if fm_count <= 2:
                in_frontmatter = not in_frontmatter
                continue
        if in_frontmatter:
            continue
        if line.startswith("```"):
            if in_list:
                out.append("</ul>")
                in_list = False
            if in_code_block:
                out.append("</code></pre>")
                in_code_block = False
            else:
                out.append("<pre><code>")
                in_code_block = True
            continue
        if in_code_block:
            out.append(html_mod.escape(line))
            continue

        stripped = line.strip()
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("")
            continue
        if stripped.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_with_links(stripped[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if stripped.startswith("### "):
            out.append(f"<h3>{_with_links(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            out.append(f"<h2>{_with_links(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            out.append(f"<h1>{_with_links(stripped[2:])}</h1>")
        elif stripped.startswith("<!--") and stripped.endswith("-->"):
            continue
        else:
            out.append(f"<p>{_with_links(stripped)}</p>")

    if in_list:
        out.append("</ul>")
    if in_code_block:
        out.append("</code></pre>")
    return "\n".join(out)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{description}">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; max-width: 48rem; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; line-height: 1.6; }}
  h1 {{ border-bottom: 1px solid #e5e5e5; padding-bottom: 0.3em; }}
  h2 {{ margin-top: 1.5em; border-bottom: 1px solid #eee; padding-bottom: 0.2em; }}
  h3 {{ margin-top: 1.2em; }}
  pre {{ background: #f6f8fa; padding: 1em; border-radius: 6px; overflow-x: auto; }}
  code {{ background: #f0f0f0; padding: 0.15em 0.3em; border-radius: 3px; font-size: 0.9em; }}
  pre code {{ background: none; padding: 0; }}
  ul {{ padding-left: 1.5em; }}
  li {{ margin: 0.3em 0; }}
  p {{ margin: 0.5em 0; }}
  nav {{ margin-bottom: 1.5em; font-size: 0.9em; }}
  nav a {{ margin-right: 1em; }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

_STOP_WORDS = {
    "a", "an", "the", "is", "are", "was", "were", "in", "on", "at", "to",
    "for", "of", "and", "or", "not", "as", "by", "via", "can", "with",
    "from", "than", "that", "this", "be", "has", "have", "it", "its",
    "no", "do", "if", "so", "up", "out", "all", "but", "get", "set",
    "only", "per", "use", "may", "one", "two", "new", "any", "each",
    "must", "when", "how", "also", "into", "over", "more", "both",
    "same", "own", "used", "using", "based", "does", "then",
}


def _inject_belief_links(body: str, prefix: str) -> str:
    def _add_link(match):
        node_id = match.group(1)
        rest = match.group(2)
        return f"### [{node_id}]({prefix}/belief/{node_id}){rest}"
    body = re.sub(r'^### ([a-z0-9][a-z0-9._:-]*)(.*)', _add_link, body, flags=re.MULTILINE)
    return _append_topic_links(body, prefix)


def _extract_topics(node_ids: list[str], limit: int = 20) -> list[dict]:
    """Extract topics from node IDs by word frequency. Returns [{topic, count}]."""
    word_counts: dict[str, int] = {}
    for nid in node_ids:
        for word in re.split(r'[-._:]', nid):
            if word and len(word) > 2 and word not in _STOP_WORDS:
                word_counts[word] = word_counts.get(word, 0) + 1
    topics = sorted(word_counts, key=lambda w: (-word_counts[w], w))[:limit]
    return [{"topic": t, "count": word_counts[t]} for t in topics]


def _append_topic_links(body: str, prefix: str) -> str:
    node_ids = re.findall(r'^### \[([a-z0-9][a-z0-9._:-]*)\]', body, flags=re.MULTILINE)
    if not node_ids:
        node_ids = re.findall(r'^### ([a-z0-9][a-z0-9._:-]*)', body, flags=re.MULTILINE)
    topics = _extract_topics(node_ids)
    if not topics:
        return body
    lines = ["", "## Topics", ""]
    for t in topics:
        lines.append(f"- [{t['topic']}]({prefix}/search?q={t['topic']}) ({t['count']})")
    lines.append("")
    return body + "\n".join(lines)


# --- Endpoints ---

@router.get("/beliefs", response_class=HTMLResponse)
async def beliefs_html(domain_name: str, session: AsyncSession = Depends(get_session)):
    domain_obj = await _resolve_public_domain(domain_name, session)
    md = await asyncio.to_thread(rms_api.export_markdown, domain_obj.id)
    prefix = f"/public/{domain_name}"
    md = _inject_belief_links(md, prefix)
    body = _md_to_html(md)
    nav = (
        f'<nav>'
        f'<a href="{prefix}/beliefs">All</a>'
        f'<a href="{prefix}/beliefs-in">IN only</a>'
        f'<a href="{prefix}/beliefs.md">Markdown</a>'
        f'<a href="{prefix}/beliefs.json">JSON</a>'
        f'</nav>'
    )
    html = _HTML_TEMPLATE.format(
        title=f"{domain_obj.name} — Beliefs",
        description=f"Belief registry for {domain_obj.name} — {domain_obj.description or 'knowledge base'}",
        body=nav + body,
    )
    return HTMLResponse(
        html,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/beliefs-in", response_class=HTMLResponse)
async def beliefs_in_html(domain_name: str, session: AsyncSession = Depends(get_session)):
    domain_obj = await _resolve_public_domain(domain_name, session)
    md = await asyncio.to_thread(rms_api.export_markdown, domain_obj.id, status="IN")
    prefix = f"/public/{domain_name}"
    md = _inject_belief_links(md, prefix)
    body = _md_to_html(md)
    nav = (
        f'<nav>'
        f'<a href="{prefix}/beliefs">All</a>'
        f'<a href="{prefix}/beliefs-in">IN only</a>'
        f'<a href="{prefix}/beliefs-in.md">Markdown</a>'
        f'<a href="{prefix}/beliefs-in.json">JSON</a>'
        f'</nav>'
    )
    html = _HTML_TEMPLATE.format(
        title=f"{domain_obj.name} — Beliefs (IN)",
        description=f"Active beliefs for {domain_obj.name} — {domain_obj.description or 'knowledge base'}",
        body=nav + body,
    )
    return HTMLResponse(
        html,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/beliefs-in.md", response_class=PlainTextResponse)
async def beliefs_in_markdown(domain_name: str, session: AsyncSession = Depends(get_session)):
    domain_obj = await _resolve_public_domain(domain_name, session)
    md = await asyncio.to_thread(rms_api.export_markdown, domain_obj.id, status="IN")
    return PlainTextResponse(
        md,
        media_type="text/markdown",
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/beliefs-in.json")
async def beliefs_in_json(domain_name: str, session: AsyncSession = Depends(get_session)):
    domain_obj = await _resolve_public_domain(domain_name, session)
    result = await asyncio.to_thread(rms_api.list_nodes, domain_obj.id, status="IN")
    prefix = f"/public/{domain_name}"
    for n in result.get("nodes", []):
        n["url"] = f"{prefix}/belief/{n['id']}.json"
    return JSONResponse(
        result,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/beliefs.md", response_class=PlainTextResponse)
async def beliefs_markdown(domain_name: str, session: AsyncSession = Depends(get_session)):
    domain_obj = await _resolve_public_domain(domain_name, session)
    md = await asyncio.to_thread(rms_api.export_markdown, domain_obj.id)
    return PlainTextResponse(
        md,
        media_type="text/markdown",
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/beliefs.json")
async def beliefs_json(domain_name: str, session: AsyncSession = Depends(get_session)):
    domain_obj = await _resolve_public_domain(domain_name, session)
    result = await asyncio.to_thread(rms_api.list_nodes, domain_obj.id)
    prefix = f"/public/{domain_name}"
    for n in result.get("nodes", []):
        n["url"] = f"{prefix}/belief/{n['id']}.json"
    return JSONResponse(
        result,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


def _belief_to_html(node_id: str, detail: dict, explanation: dict, prefix: str) -> str:
    status = detail.get("truth_value", "?")
    text = html_mod.escape(detail.get("text", ""))
    source = detail.get("source", "")
    source_url = detail.get("source_url", "")

    parts = [
        f'<nav><a href="{prefix}/beliefs">&larr; All beliefs</a></nav>',
        f'<h1>{html_mod.escape(node_id)}</h1>',
        f'<p><strong>Status:</strong> {html_mod.escape(status)}</p>',
        f'<p>{text}</p>',
    ]

    if source:
        if source_url:
            parts.append(f'<p><strong>Source:</strong> <a href="{html_mod.escape(source_url)}">{html_mod.escape(source)}</a></p>')
        elif source.startswith("entries/") and source.endswith(".md"):
            slug = source.rsplit("/", 1)[-1].removesuffix(".md")
            parts.append(f'<p><strong>Source:</strong> <a href="{prefix}/entry/{html_mod.escape(slug)}">{html_mod.escape(source)}</a></p>')
        else:
            parts.append(f'<p><strong>Source:</strong> {html_mod.escape(source)}</p>')

    # Example from metadata
    metadata = detail.get("metadata") or {}
    example = metadata.get("example", "")
    if example:
        parts.append('<h2>Example</h2>')
        parts.append(f'<pre><code>{html_mod.escape(example)}</code></pre>')

    # Dependencies
    justifications = detail.get("justifications", [])
    if justifications:
        parts.append('<h2>Justifications</h2>')
        for j in justifications:
            jtype = j.get("type", "SL")
            label = j.get("label", "")
            antecedents = j.get("antecedents", [])
            outlist = j.get("outlist", [])
            parts.append(f'<div style="margin-bottom:1em;">')
            if label:
                parts.append(f'<p><em>{html_mod.escape(label)}</em></p>')
            if antecedents:
                links = ", ".join(
                    f'<a href="{prefix}/belief/{html_mod.escape(a)}">{html_mod.escape(a)}</a>'
                    for a in antecedents
                )
                parts.append(f'<p><strong>Depends on ({jtype}):</strong> {links}</p>')
            if outlist:
                links = ", ".join(
                    f'<a href="{prefix}/belief/{html_mod.escape(o)}">{html_mod.escape(o)}</a>'
                    for o in outlist
                )
                parts.append(f'<p><strong>Unless:</strong> {links}</p>')
            parts.append('</div>')

    # Dependents
    dependents = detail.get("dependents", [])
    if dependents:
        parts.append('<h2>Depended on by</h2>')
        parts.append('<ul>')
        for d in dependents:
            parts.append(f'<li><a href="{prefix}/belief/{html_mod.escape(d)}">{html_mod.escape(d)}</a></li>')
        parts.append('</ul>')

    # Explanation chain
    exp_text = explanation.get("explanation", "")
    if exp_text:
        parts.append('<h2>Explanation</h2>')
        parts.append(f'<pre><code>{html_mod.escape(exp_text)}</code></pre>')

    parts.append(f'<p style="margin-top:2em;font-size:0.85em;"><a href="{prefix}/belief/{html_mod.escape(node_id)}?format=json">JSON</a></p>')

    return "\n".join(parts)


@router.get("/belief/{node_id}.json")
async def get_belief_json(
    domain_name: str,
    node_id: str,
    session: AsyncSession = Depends(get_session),
):
    domain_obj = await _resolve_public_domain(domain_name, session)
    try:
        detail = await asyncio.to_thread(rms_api.show_node, domain_obj.id, node_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Belief not found")
    explanation = await asyncio.to_thread(rms_api.explain_node, domain_obj.id, node_id)
    detail["explanation"] = explanation
    return JSONResponse(
        detail,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/belief/{node_id}", response_class=HTMLResponse)
async def get_belief(
    domain_name: str,
    node_id: str,
    format: str = "html",
    session: AsyncSession = Depends(get_session),
):
    domain_obj = await _resolve_public_domain(domain_name, session)
    try:
        detail = await asyncio.to_thread(rms_api.show_node, domain_obj.id, node_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Belief not found")
    explanation = await asyncio.to_thread(rms_api.explain_node, domain_obj.id, node_id)

    if format == "json":
        detail["explanation"] = explanation
        return JSONResponse(
            detail,
            headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
        )

    prefix = f"/public/{domain_name}"
    body = _belief_to_html(node_id, detail, explanation, prefix)
    belief_text = detail.get("text", "")[:160]
    html = _HTML_TEMPLATE.format(
        title=f"{node_id} — {domain_obj.name}",
        description=belief_text,
        body=body,
    )
    return HTMLResponse(
        html,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/intro.json")
async def intro_json(
    domain_name: str,
    session: AsyncSession = Depends(get_session),
):
    domain_obj = await _resolve_public_domain(domain_name, session)
    belief_count = await asyncio.to_thread(rms_api.count_beliefs, domain_obj.id, "IN")
    nodes_result = await asyncio.to_thread(rms_api.list_nodes, domain_obj.id, status="IN")
    node_ids = [n["id"] for n in nodes_result.get("nodes", [])]
    prefix = f"/public/{domain_name}"
    topics = _extract_topics(node_ids, limit=30)
    for t in topics:
        t["search_url"] = f"{prefix}/search?q={t['topic']}"
    return JSONResponse(
        {
            "name": domain_obj.name,
            "description": domain_obj.description,
            "belief_count": belief_count,
            "topics": topics,
            "endpoints": {
                "beliefs": f"{prefix}/beliefs.json",
                "beliefs_in": f"{prefix}/beliefs-in.json",
                "search": f"{prefix}/search?q={{query}}",
                "belief": f"{prefix}/belief/{{node_id}}.json",
                "intro": f"{prefix}/intro.json",
            },
        },
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/entry/{entry_id}", response_class=HTMLResponse)
async def get_entry(
    domain_name: str,
    entry_id: str,
    session: AsyncSession = Depends(get_session),
):
    domain_obj = await _resolve_public_domain(domain_name, session)
    from sqlalchemy.orm import selectinload
    result = await session.execute(
        select(Entry).options(selectinload(Entry.sources))
        .where(Entry.domain_id == domain_obj.id, Entry.id == entry_id)
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    prefix = f"/public/{domain_name}"
    nav = f'<nav><a href="{prefix}/beliefs">&larr; All beliefs</a></nav>'
    source_links = ""
    if entry.sources:
        links = " &middot; ".join(
            f'<a href="{prefix}/source/{html_mod.escape(s.slug)}">{html_mod.escape(s.slug)}</a>'
            for s in entry.sources
        )
        source_links = f'<p><strong>Original source:</strong> {links}</p><hr>'
    body = _md_to_html(entry.content)
    html = _HTML_TEMPLATE.format(
        title=f"{entry_id} — {domain_obj.name}",
        description=f"{entry.title or entry_id} — analysis entry for {domain_obj.name}",
        body=nav + source_links + body,
    )
    return HTMLResponse(
        html,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/source/{slug}")
async def get_source(
    domain_name: str,
    slug: str,
    session: AsyncSession = Depends(get_session),
):
    domain_obj = await _resolve_public_domain(domain_name, session)
    result = await session.execute(
        select(Source).where(Source.domain_id == domain_obj.id, Source.slug == slug)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    prefix = f"/public/{domain_name}"
    nav = f'<nav><a href="{prefix}/beliefs">&larr; All beliefs</a></nav>'
    title_html = f"<h1>{html_mod.escape(source.slug)}</h1>"
    body = _md_to_html(source.content)
    html = _HTML_TEMPLATE.format(
        title=f"{slug} — {domain_obj.name}",
        description=f"Source document: {slug} — {domain_obj.name}",
        body=nav + title_html + body,
    )
    return HTMLResponse(
        html,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/search")
async def search_beliefs(
    domain_name: str,
    q: str,
    limit: int = 20,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    domain_obj = await _resolve_public_domain(domain_name, session)
    result = await asyncio.to_thread(rms_api.search, domain_obj.id, q, limit=limit, offset=offset)
    return JSONResponse(
        result,
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


@router.get("/deep-search")
async def deep_search(
    domain_name: str,
    q: str,
    session: AsyncSession = Depends(get_session),
):
    from reasons_service.db.search import quick_belief_search, search_source_chunks

    domain_obj = await _resolve_public_domain(domain_name, session)
    (belief_ctx, belief_sources), (chunk_ctx, chunk_sources) = await asyncio.gather(
        asyncio.to_thread(quick_belief_search, domain_obj.id, q, 20),
        asyncio.to_thread(search_source_chunks, domain_obj.id, q, 10),
    )
    return JSONResponse(
        {
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
        },
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )


# --- Landing page ---

@landing_router.get("/", response_class=HTMLResponse)
async def public_landing(request: Request, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Domain).where(Domain.public == True).order_by(Domain.name)
    )
    domain_list = result.scalars().all()
    public_domains = []
    for p in domain_list:
        belief_count = await asyncio.to_thread(rms_api.count_beliefs, p.id, "IN")
        public_domains.append({
            "name": p.name,
            "description": p.description,
            "belief_count": belief_count,
        })
    return _templates.TemplateResponse(
        request, "public/index.html",
        {"public_domains": public_domains},
        headers={"Cache-Control": f"public, max-age={_CACHE_MAX_AGE}"},
    )
