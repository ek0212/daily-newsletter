"""Fetch trending AI security papers from arxiv + HuggingFace Daily Papers."""

import logging
import time
import urllib.error
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import json
from datetime import datetime, timedelta

from src.constants import (
    ARXIV_API_URL,
    CITATION_SCORE_CAP,
    HF_DAILY_LIMIT,
    HF_DAILY_PAPERS_API_URL,
    HTTP_TIMEOUT_DEFAULT,
    HTTP_TIMEOUT_MEDIUM,
    MAX_AUTHORS_DISPLAY,
    MAX_PAPERS_ENRICH,
    RELEVANCE_TERM_SCORE,
    SEMANTIC_SCHOLAR_API_URL,
    USER_AGENT,
)

logger = logging.getLogger(__name__)

ARXIV_API = ARXIV_API_URL
S2_API = SEMANTIC_SCHOLAR_API_URL
HF_DAILY_API = HF_DAILY_PAPERS_API_URL

# Focused search terms — AI/LLM security, agents, and AI safety
ARXIV_QUERIES = [
    "prompt+injection+jailbreak+LLM",
    "red+teaming+language+model",
    "adversarial+attack+large+language+model",
    "LLM+guardrail+bypass",
    "LLM+safety+alignment",
    "AI+model+extraction+attack",
    "agentic+AI+safety+autonomous",
    "declarative+agent+LLM",
    "multi+agent+LLM+security",
    "AI+agent+tool+use+safety",
    "LLM+hallucination+detection",
    "AI+bias+fairness+language+model",
    "machine+learning+adversarial+robustness",
    "LLM+watermarking+detection",
    "AI+deepfake+detection",
]

# High-relevance terms (must match at least one to be included)
# These correspond to the badge keywords in the newsletter template
REQUIRED_TERMS = [
    "prompt injection", "jailbreak", "red team", "blue team", "purple team",
    "adversarial", "guardrail", "model extraction", "distillation attack",
    "phishing", "social engineering", "malware", "obfuscat",
    "agentic", "autonomous agent", "llm-as-a-judge", "agent-as-a-judge",
    "sycophancy", "sabotage", "behavioral evaluation",
    "privacy", "red teaming", "safety", "alignment",
    "nist", "taxonomy",
]

# Bonus scoring terms
RELEVANCE_TERMS = [
    "prompt injection", "jailbreak", "red team", "adversarial",
    "guardrail", "llm security", "ai safety", "ai alignment",
    "model extraction", "ai vulnerability", "llm attack",
    "ai threat", "ai robustness", "ai agent", "agentic",
]


def _parse_arxiv_xml(xml_data: bytes) -> list[dict]:
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(xml_data)
    papers = []
    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        if title_el is None or not title_el.text:
            continue
        title = " ".join(title_el.text.strip().split())
        abstract_el = entry.find("atom:summary", ns)
        abstract = " ".join(abstract_el.text.strip().split()) if abstract_el is not None else ""
        authors = []
        affiliations = []
        for a in entry.findall("atom:author", ns):
            name_el = a.find("atom:name", ns)
            if name_el is None:
                continue
            authors.append(name_el.text)
            affs = [aff.text for aff in a.findall("arxiv:affiliation", ns) if aff.text]
            affiliations.append(", ".join(affs) if affs else "")

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
            "title": title, "authors": authors[:MAX_AUTHORS_DISPLAY], "abstract": abstract,
            "link": link, "published": pub_date, "arxiv_id": arxiv_id, "citation_count": None,
            "affiliations": affiliations[:MAX_AUTHORS_DISPLAY],
            "influential_citations": None,
        })
    return papers


def fetch_arxiv_papers(max_per_query: int = 5) -> list[dict]:
    """Run several focused arxiv queries and merge results."""
    logger.info("Searching arxiv for AI security papers...")
    seen_ids = set()
    all_papers = []

    for kw in ARXIV_QUERIES:
        try:
            url = f"{ARXIV_API}?search_query=all:{kw}&start=0&max_results={max_per_query}&sortBy=submittedDate&sortOrder=descending"
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_MEDIUM) as resp:
                xml_data = resp.read()
            new_papers = _parse_arxiv_xml(xml_data)
            count_new = 0
            for p in new_papers:
                if p["arxiv_id"] not in seen_ids:
                    seen_ids.add(p["arxiv_id"])
                    all_papers.append(p)
                    count_new += 1
            logger.debug("Query: %s -> %d results", kw, count_new)
        except Exception:
            continue

    logger.info("Total arxiv papers found: %d", len(all_papers))
    return all_papers


def enrich_citations(papers: list[dict]) -> list[dict]:
    """Enrich papers with citation counts and author affiliations from Semantic Scholar batch API."""
    candidates = [p for p in papers[:MAX_PAPERS_ENRICH] if p.get("arxiv_id")]
    if not candidates:
        return papers
    logger.info("Enriching %d papers from Semantic Scholar (batch API)...", len(candidates))

    # Strip version suffix (e.g., "2603.04390v1" -> "2603.04390") — S2 rejects versioned IDs
    ids = [f"ARXIV:{p['arxiv_id'].split('v')[0]}" for p in candidates]
    fields = "citationCount,influentialCitationCount,authors.name,authors.affiliations"
    url = f"{S2_API}/paper/batch?fields={fields}"
    payload = json.dumps({"ids": ids}).encode()

    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=payload,
                headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_MEDIUM) as resp:
                results = json.loads(resp.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 10 * (attempt + 1)
                logger.warning("S2 batch rate limited, waiting %ds (attempt %d/3)...", wait, attempt + 1)
                time.sleep(wait)
            else:
                logger.warning("S2 batch error %d", e.code)
                return papers
        except Exception as e:
            logger.warning("S2 batch request failed: %s", str(e)[:80])
            return papers
    else:
        logger.warning("S2 batch failed after 3 attempts")
        return papers

    enriched = 0
    for paper, s2_data in zip(candidates, results):
        if not s2_data:
            continue
        paper["citation_count"] = s2_data.get("citationCount", 0)
        paper["influential_citations"] = s2_data.get("influentialCitationCount", 0)
        # Backfill affiliations from S2 if arXiv didn't provide real ones
        # (arXiv sometimes returns garbage like single words in affiliation tags)
        s2_authors = s2_data.get("authors", [])
        current_affs = paper.get("affiliations", [])
        has_real_affs = any(a for a in current_affs if a and len(a) > 5)
        if s2_authors and not has_real_affs:
            s2_affs = [
                ", ".join(s2a.get("affiliations") or []) or ""
                for s2a in s2_authors[:MAX_AUTHORS_DISPLAY]
            ]
            # Only use S2 affiliations if they actually have content
            if any(a for a in s2_affs if a):
                paper["affiliations"] = s2_affs
        enriched += 1
        logger.debug("Paper '%s': %d citations (%d influential), affiliations: %s",
                     paper["title"][:60], paper["citation_count"],
                     paper.get("influential_citations", 0),
                     [a for a in paper.get("affiliations", []) if a])

    logger.info("S2 enrichment complete: %d/%d papers enriched", enriched, len(candidates))
    return papers


def fetch_hf_daily_papers() -> list[dict]:
    logger.debug("Checking HuggingFace Daily Papers...")
    try:
        url = f"{HF_DAILY_API}?limit={HF_DAILY_LIMIT}"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_MEDIUM) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []

    keywords = ["llm security", "ai safety", "ai alignment", "jailbreak",
                 "prompt injection", "red team", "adversarial", "guardrail",
                 "autonomous agent", "declarative agent", "agentic ai",
                 "ai agent", "multi-agent", "agent safety", "model extraction",
                 "language model", "ai vulnerability", "ai robustness",
                 "ai threat", "ai governance", "llm attack", "hallucination",
                 "deepfake", "ai bias", "watermark", "foundation model"]
    results = []
    for item in data:
        paper = item.get("paper", item)
        title = paper.get("title", "")
        summary = paper.get("summary", paper.get("abstract", ""))
        if any(kw in (title + " " + summary).lower() for kw in keywords):
            hf_authors = [a.get("name", "") for a in paper.get("authors", [])][:MAX_AUTHORS_DISPLAY]
            paper_id = paper.get("id", "")
            results.append({
                "title": title, "authors": hf_authors,
                "abstract": summary or "",
                "link": f"https://huggingface.co/papers/{paper_id}",
                "published": paper.get("publishedAt", "")[:10],
                "arxiv_id": paper_id, "citation_count": None,
                "affiliations": [""] * len(hf_authors),
                "influential_citations": None,
            })
    logger.info("HF papers found: %d relevant", len(results))
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
    papers = [p for p in papers if p.get("published", "") >= cutoff]

    # Only keep papers matching at least one required AI security term
    def has_required_term(p):
        text = (p["title"] + " " + p["abstract"]).lower()
        return any(t in text for t in REQUIRED_TERMS)

    papers = [p for p in papers if has_required_term(p)]
    logger.info("Papers after AI security filter: %d", len(papers))

    papers = enrich_citations(papers)

    # Rank
    def score(p):
        text = (p["title"] + " " + p["abstract"]).lower()
        return sum(RELEVANCE_TERM_SCORE for t in RELEVANCE_TERMS if t in text) + min((p.get("citation_count") or 0), CITATION_SCORE_CAP)

    papers.sort(key=score, reverse=True)
    top_papers = papers[:top_n]
    top_papers.sort(key=lambda p: p.get("published", ""), reverse=True)
    for p in top_papers:
        p["quick_summary"] = ""
        p["raw_text"] = p.get("abstract", "")
    logger.info("Papers complete: top %d selected", len(top_papers))
    return top_papers
