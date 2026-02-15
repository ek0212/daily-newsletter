"""Fetch trending AI security papers from arxiv + HuggingFace Daily Papers."""

import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timedelta

ARXIV_API = "http://export.arxiv.org/api/query"
S2_API = "https://api.semanticscholar.org/graph/v1"
HF_DAILY_API = "https://huggingface.co/api/daily_papers"

# Focused search terms (URL-safe, no spaces)
ARXIV_QUERIES = [
    "prompt+injection",
    "jailbreak+LLM",
    "red+teaming+language+model",
    "adversarial+attack+LLM",
    "LLM+security",
    "AI+safety+alignment",
]

RELEVANCE_TERMS = [
    "prompt injection", "jailbreak", "red team", "adversarial",
    "guardrail", "attack", "safety", "alignment", "security",
]


def _parse_arxiv_xml(xml_data: bytes) -> list[dict]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)
    papers = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        if title_el is None or not title_el.text:
            continue
        title = " ".join(title_el.text.strip().split())
        abstract_el = entry.find("atom:summary", ns)
        abstract = " ".join(abstract_el.text.strip().split()) if abstract_el is not None else ""
        authors = [a.find("atom:name", ns).text for a in entry.findall("atom:author", ns) if a.find("atom:name", ns) is not None]

        link = ""
        for l in entry.findall("atom:link", ns):
            if l.get("title") == "pdf":
                link = l.get("href", "")
                break
        if not link:
            id_el = entry.find("atom:id", ns)
            link = id_el.text if id_el is not None else ""

        pub_el = entry.find("atom:published", ns)
        pub_date = pub_el.text[:10] if pub_el is not None else ""

        id_el = entry.find("atom:id", ns)
        arxiv_id = id_el.text.split("/abs/")[-1] if id_el is not None and id_el.text else ""

        papers.append({
            "title": title, "authors": authors[:5], "abstract": abstract[:500],
            "link": link, "published": pub_date, "arxiv_id": arxiv_id, "citation_count": None,
        })
    return papers


def fetch_arxiv_papers(max_per_query: int = 5) -> list[dict]:
    """Run several focused arxiv queries and merge results."""
    seen_ids = set()
    all_papers = []

    for kw in ARXIV_QUERIES:
        try:
            url = f"{ARXIV_API}?search_query=all:{kw}&start=0&max_results={max_per_query}&sortBy=submittedDate&sortOrder=descending"
            req = urllib.request.Request(url, headers={"User-Agent": "DailyNewsletter/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                xml_data = resp.read()
            for p in _parse_arxiv_xml(xml_data):
                if p["arxiv_id"] not in seen_ids:
                    seen_ids.add(p["arxiv_id"])
                    all_papers.append(p)
        except Exception:
            continue

    return all_papers


def enrich_citations(papers: list[dict]) -> list[dict]:
    for paper in papers[:10]:
        if not paper.get("arxiv_id"):
            continue
        try:
            url = f"{S2_API}/paper/ARXIV:{paper['arxiv_id']}?fields=citationCount"
            req = urllib.request.Request(url, headers={"User-Agent": "DailyNewsletter/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            paper["citation_count"] = data.get("citationCount", 0)
        except Exception:
            pass
    return papers


def fetch_hf_daily_papers() -> list[dict]:
    try:
        url = f"{HF_DAILY_API}?limit=50"
        req = urllib.request.Request(url, headers={"User-Agent": "DailyNewsletter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    keywords = ["security", "safety", "adversarial", "jailbreak", "red team",
                 "alignment", "guardrail", "injection", "attack", "robustness"]
    results = []
    for item in data:
        paper = item.get("paper", item)
        title = paper.get("title", "")
        summary = paper.get("summary", paper.get("abstract", ""))
        if any(kw in (title + " " + summary).lower() for kw in keywords):
            results.append({
                "title": title, "authors": [a.get("name", "") for a in paper.get("authors", [])][:5],
                "abstract": (summary or "")[:500],
                "link": f"https://huggingface.co/papers/{paper.get('id', '')}",
                "published": paper.get("publishedAt", "")[:10],
                "arxiv_id": "", "citation_count": None,
            })
    return results


def get_ai_security_papers(days_back: int = 7, top_n: int = 5) -> list[dict]:
    """Main entry: fetch, enrich, rank, return top AI security papers with raw text."""
    papers = fetch_arxiv_papers()
    hf_papers = fetch_hf_daily_papers()

    # Merge, dedup
    seen = {p["title"].lower()[:60] for p in papers}
    for hp in hf_papers:
        if hp["title"].lower()[:60] not in seen:
            papers.append(hp)
            seen.add(hp["title"].lower()[:60])

    # Filter to recent papers only
    cutoff = (datetime.utcnow() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    papers = [p for p in papers if p.get("published", "9999") >= cutoff] or papers

    papers = enrich_citations(papers)

    # Rank
    def score(p):
        text = (p["title"] + " " + p["abstract"]).lower()
        return sum(2 for t in RELEVANCE_TERMS if t in text) + min((p.get("citation_count") or 0), 20)

    papers.sort(key=score, reverse=True)
    top_papers = papers[:top_n]
    for p in top_papers:
        p["quick_summary"] = ""
        p["raw_text"] = p.get("abstract", "")
    return top_papers
