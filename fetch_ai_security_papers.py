#!/usr/bin/env python3
"""Fetch trending AI security papers from arxiv and optionally enrich with Semantic Scholar data."""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timedelta
from typing import Optional

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1"
HF_DAILY_API = "https://huggingface.co/api/daily_papers"

AI_SECURITY_KEYWORDS = [
    "prompt injection",
    "jailbreak LLM",
    "red teaming language model",
    "adversarial attack LLM",
    "AI agent security",
    "guardrail bypass",
    "AI alignment",
    "LLM security",
    "autonomous agent safety",
    "declarative agent LLM",
    "agentic AI safety",
    "multi-agent LLM security",
]

ARXIV_CATEGORIES = ["cs.CR", "cs.AI", "cs.CL", "cs.LG"]


def fetch_arxiv_papers(days_back: int = 7, max_results: int = 30) -> list[dict]:
    """Query arxiv API for recent AI security papers."""
    now = datetime.utcnow()
    start = now - timedelta(days=days_back)
    date_range = f"[{start.strftime('%Y%m%d')}0000+TO+{now.strftime('%Y%m%d')}2359]"

    # Build query: (keyword1 OR keyword2 ...) AND (cat1 OR cat2 ...) AND date
    kw_parts = [f'all:"{kw}"' for kw in AI_SECURITY_KEYWORDS]
    kw_query = "+OR+".join(kw_parts)

    cat_parts = [f"cat:{c}" for c in ARXIV_CATEGORIES]
    cat_query = "+OR+".join(cat_parts)

    query = f"({kw_query})+AND+({cat_query})+AND+submittedDate:{date_range}"

    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    url = f"{ARXIV_API}?{urllib.parse.urlencode(params, safe='+():[]:')}"
    # The urlencode may double-encode; build manually instead
    url = f"{ARXIV_API}?search_query={query}&start=0&max_results={max_results}&sortBy=submittedDate&sortOrder=descending"

    req = urllib.request.Request(url, headers={"User-Agent": "DailyNewsletter/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_data = resp.read()

    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_data)
    papers = []

    for entry in root.findall("atom:entry", ns):
        title = entry.find("atom:title", ns)
        if title is None:
            continue
        title_text = " ".join(title.text.strip().split())

        abstract = entry.find("atom:summary", ns)
        abstract_text = " ".join(abstract.text.strip().split()) if abstract is not None else ""

        authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns)]

        link = ""
        for l in entry.findall("atom:link", ns):
            if l.get("title") == "pdf":
                link = l.get("href", "")
                break
        if not link:
            id_el = entry.find("atom:id", ns)
            link = id_el.text if id_el is not None else ""

        published = entry.find("atom:published", ns)
        pub_date = published.text[:10] if published is not None else ""

        categories = [c.get("term") for c in entry.findall("atom:category", ns)]

        # Extract arxiv ID for Semantic Scholar lookup
        id_el = entry.find("atom:id", ns)
        arxiv_id = ""
        if id_el is not None and id_el.text:
            arxiv_id = id_el.text.split("/abs/")[-1]

        papers.append({
            "title": title_text,
            "authors": authors[:5],  # first 5 authors
            "abstract": abstract_text[:500],
            "link": link,
            "published": pub_date,
            "categories": categories,
            "arxiv_id": arxiv_id,
            "citation_count": None,
        })

    return papers


def enrich_with_semantic_scholar(papers: list[dict]) -> list[dict]:
    """Add citation counts from Semantic Scholar (best-effort, no API key required)."""
    for paper in papers:
        if not paper.get("arxiv_id"):
            continue
        try:
            url = f"{S2_API}/paper/ARXIV:{paper['arxiv_id']}?fields=citationCount,influentialCitationCount"
            req = urllib.request.Request(url, headers={"User-Agent": "DailyNewsletter/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            paper["citation_count"] = data.get("citationCount", 0)
            paper["influential_citations"] = data.get("influentialCitationCount", 0)
        except Exception:
            pass  # S2 may not have the paper yet
    return papers


def fetch_hf_daily_papers(limit: int = 50) -> list[dict]:
    """Fetch HuggingFace Daily Papers and filter for AI security topics."""
    try:
        url = f"{HF_DAILY_API}?limit={limit}"
        req = urllib.request.Request(url, headers={"User-Agent": "DailyNewsletter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    security_keywords = [
        "llm security", "ai safety", "ai alignment", "jailbreak",
        "prompt injection", "red team", "adversarial", "guardrail",
        "autonomous agent", "declarative agent", "agentic ai",
        "ai agent", "multi-agent", "agent safety", "ai vulnerability",
    ]
    results = []
    for item in data:
        paper = item.get("paper", item)
        title = paper.get("title", "")
        summary = paper.get("summary", paper.get("abstract", ""))
        text = (title + " " + summary).lower()
        if any(kw in text for kw in security_keywords):
            results.append({
                "title": title,
                "authors": [a.get("name", a.get("user", "")) for a in paper.get("authors", [])][:5],
                "abstract": summary[:500] if summary else "",
                "link": f"https://huggingface.co/papers/{paper.get('id', '')}",
                "published": paper.get("publishedAt", "")[:10],
                "source": "huggingface_daily",
            })
    return results


def rank_papers(papers: list[dict], top_n: int = 5) -> list[dict]:
    """Rank papers by relevance. Prioritize those with more keyword matches and citations."""
    priority_terms = [
        "prompt injection", "jailbreak", "red team", "adversarial",
        "guardrail", "attack", "safety", "alignment", "security",
    ]

    def score(p):
        text = (p["title"] + " " + p["abstract"]).lower()
        keyword_score = sum(2 for t in priority_terms if t in text)
        cite_score = min((p.get("citation_count") or 0), 20)
        return keyword_score + cite_score

    papers.sort(key=score, reverse=True)
    return papers[:top_n]


def format_paper(i: int, p: dict) -> str:
    authors_str = ", ".join(p["authors"][:3])
    if len(p["authors"]) > 3:
        authors_str += " et al."
    lines = [
        f"{i}. **{p['title']}**",
        f"   Authors: {authors_str}",
        f"   Published: {p['published']}",
        f"   Link: {p['link']}",
    ]
    if p.get("citation_count") is not None:
        lines.append(f"   Citations: {p['citation_count']}")
    lines.append(f"   Abstract: {p['abstract'][:300]}...")
    return "\n".join(lines)


def get_top_ai_security_papers(days_back: int = 7, top_n: int = 5, use_semantic_scholar: bool = True) -> str:
    """Main entry point: fetch, enrich, rank, and format top AI security papers."""
    print(f"Fetching arxiv papers from the last {days_back} days...")
    papers = fetch_arxiv_papers(days_back=days_back)
    print(f"  Found {len(papers)} arxiv papers")

    print("Checking HuggingFace Daily Papers...")
    hf_papers = fetch_hf_daily_papers()
    print(f"  Found {len(hf_papers)} relevant HF daily papers")

    # Merge, dedup by title similarity
    seen_titles = {p["title"].lower()[:60] for p in papers}
    for hp in hf_papers:
        if hp["title"].lower()[:60] not in seen_titles:
            papers.append(hp)
            seen_titles.add(hp["title"].lower()[:60])

    if use_semantic_scholar and papers:
        print("Enriching with Semantic Scholar citation data...")
        papers = enrich_with_semantic_scholar(papers)

    top = rank_papers(papers, top_n=top_n)

    if not top:
        return "No AI security papers found for the given time period."

    header = f"## Top {len(top)} AI Security Papers (last {days_back} days)\n"
    body = "\n\n".join(format_paper(i + 1, p) for i, p in enumerate(top))
    return header + "\n" + body


if __name__ == "__main__":
    result = get_top_ai_security_papers()
    print("\n" + result)
