"""Fetch documentation from URLs and convert to markdown.

Ported from expert_build/fetch.py — replaces filesystem writes with DB inserts.
"""

import re
import time
from datetime import date
from fnmatch import fnmatch
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag


def html_to_markdown(element: Tag) -> str:
    """Convert an HTML element to markdown."""
    parts: list[str] = []
    _convert(element, parts)
    text = "".join(parts)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _convert(element, parts):
    """Recursively convert HTML elements to markdown."""
    if isinstance(element, NavigableString):
        text = str(element)
        if text.strip():
            parts.append(text)
        elif text:
            parts.append(" ")
        return

    if not isinstance(element, Tag):
        return

    tag = element.name

    if tag in ("script", "style", "nav", "footer", "header"):
        return

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        parts.append(f"\n\n{'#' * level} ")
        for child in element.children:
            _convert(child, parts)
        parts.append("\n\n")

    elif tag == "p":
        parts.append("\n\n")
        for child in element.children:
            _convert(child, parts)
        parts.append("\n\n")

    elif tag in ("ul", "ol"):
        parts.append("\n")
        for i, li in enumerate(element.find_all("li", recursive=False)):
            prefix = f"{i + 1}. " if tag == "ol" else "- "
            parts.append(prefix)
            for child in li.children:
                _convert(child, parts)
            parts.append("\n")
        parts.append("\n")

    elif tag == "pre":
        code = element.find("code")
        lang = ""
        if code and code.get("class"):
            for cls in code["class"]:
                if cls.startswith("language-"):
                    lang = cls[len("language-"):]
                    break
        text = element.get_text()
        parts.append(f"\n```{lang}\n{text}\n```\n")

    elif tag == "code":
        if element.parent and element.parent.name != "pre":
            parts.append(f"`{element.get_text()}`")
        else:
            parts.append(element.get_text())

    elif tag in ("strong", "b"):
        parts.append("**")
        for child in element.children:
            _convert(child, parts)
        parts.append("**")

    elif tag in ("em", "i"):
        parts.append("*")
        for child in element.children:
            _convert(child, parts)
        parts.append("*")

    elif tag == "a":
        href = element.get("href", "")
        parts.append("[")
        for child in element.children:
            _convert(child, parts)
        parts.append(f"]({href})")

    elif tag == "table":
        _convert_table(element, parts)

    elif tag == "br":
        parts.append("\n")

    elif tag in ("div", "section", "article", "main", "span", "dd", "dt", "dl",
                 "blockquote", "figure", "figcaption", "details", "summary"):
        for child in element.children:
            _convert(child, parts)

    elif tag == "img":
        alt = element.get("alt", "")
        src = element.get("src", "")
        parts.append(f"![{alt}]({src})")

    else:
        for child in element.children:
            _convert(child, parts)


def _convert_table(table: Tag, parts):
    """Convert an HTML table to markdown."""
    rows = table.find_all("tr")
    if not rows:
        return

    parts.append("\n")
    for i, row in enumerate(rows):
        cells = row.find_all(["th", "td"])
        cell_texts = [cell.get_text(strip=True) for cell in cells]
        parts.append("| " + " | ".join(cell_texts) + " |\n")
        if i == 0:
            parts.append("| " + " | ".join(["---"] * len(cell_texts)) + " |\n")
    parts.append("\n")


def slugify_url(url: str) -> str:
    """Convert URL path to a filename-safe slug."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "-") or "index"
    slug = re.sub(r"[^\w-]", "", path)
    return slug[:80]


def matches_patterns(url: str, include: str | None, exclude: str | None) -> bool:
    """Check if URL matches include/exclude patterns."""
    if include and not fnmatch(url, include):
        return False
    if exclude and fnmatch(url, exclude):
        return False
    return True


def fetch_sitemap(url: str, client: httpx.Client) -> list[str]:
    """Fetch URLs from a sitemap.xml."""
    resp = client.get(url, follow_redirects=True)
    resp.raise_for_status()
    root = ElementTree.fromstring(resp.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    for loc in root.findall(".//sm:loc", ns):
        if loc.text:
            urls.append(loc.text)
    if not urls:
        for loc in root.findall(".//loc"):
            if loc.text:
                urls.append(loc.text)
    return urls


def fetch_docs(
    url: str,
    depth: int = 2,
    delay: float = 1.0,
    selector: str = "main,article,.content,body",
    include: str | None = None,
    exclude: str | None = None,
    use_sitemap: bool = False,
    on_progress: callable = None,
) -> list[dict]:
    """Fetch documentation from URLs and return as list of dicts.

    Returns list of {url, slug, content, word_count} dicts.
    Calls on_progress(url, status, count) if provided.
    """
    base_domain = urlparse(url).netloc
    headers = {"User-Agent": "reasons-service/0.1 (documentation fetcher)"}
    results = []

    with httpx.Client(timeout=30, headers=headers, follow_redirects=True) as client:
        if use_sitemap:
            urls = fetch_sitemap(url, client)
            urls = [u for u in urls if matches_patterns(u, include, exclude)]
            queue = [(u, 0) for u in urls]
        else:
            queue = [(url, 0)]

        visited = set()

        while queue:
            page_url, page_depth = queue.pop(0)
            if page_url in visited or page_depth > depth:
                continue

            visited.add(page_url)

            try:
                resp = client.get(page_url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                if on_progress:
                    on_progress(page_url, "error", len(results))
                continue

            content_type = resp.headers.get("content-type", "")
            if "html" not in content_type:
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            content_element = None
            for sel in selector.split(","):
                sel = sel.strip()
                content_element = soup.select_one(sel)
                if content_element:
                    break
            if not content_element:
                content_element = soup.body or soup

            md = html_to_markdown(content_element)
            if not md.strip():
                continue

            slug = slugify_url(page_url)
            word_count = len(md.split())

            results.append({
                "url": page_url,
                "slug": slug,
                "content": md,
                "word_count": word_count,
            })

            if on_progress:
                on_progress(page_url, "done", len(results))

            # Discover links for crawling
            if not use_sitemap and page_depth < depth:
                for a in soup.find_all("a", href=True):
                    href = urljoin(page_url, a["href"]).split("#")[0]
                    if urlparse(href).netloc == base_domain:
                        if href not in visited and matches_patterns(href, include, exclude):
                            queue.append((href, page_depth + 1))

            if delay > 0:
                time.sleep(delay)

    return results
