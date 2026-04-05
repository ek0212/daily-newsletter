#!/usr/bin/env python3
"""Generate learnings digest from liked newsletter items."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

GEMINI_MODEL = "gemini-3-flash-preview"  # standalone tool, not part of newsletter pipeline

PROJECT_ROOT = Path(__file__).parent.parent
SITE_DIR = PROJECT_ROOT / "site"

load_dotenv(PROJECT_ROOT / ".env")


def main():
    parser = argparse.ArgumentParser(description="Generate learnings digest from liked items.")
    parser.add_argument("--likes", type=Path, default=SITE_DIR / "likes.json", help="Path to likes.json")
    parser.add_argument("--since", type=str, help="Only process likes after this date (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, default=SITE_DIR / "learnings.json", help="Output path")
    parser.add_argument("--force", action="store_true", help="Skip minimum 3 new likes check")
    args = parser.parse_args()

    # 1. Read likes
    if not args.likes.exists():
        print(f"Likes file not found: {args.likes}")
        sys.exit(1)

    likes_data = json.loads(args.likes.read_text())
    items = likes_data.get("items", [])

    if args.since:
        items = [i for i in items if i.get("date_liked", i.get("saved_at", "")) >= args.since]

    # 2. Load audit state
    state_path = SITE_DIR / "audit_state.json"
    state = {}
    if state_path.exists():
        state = json.loads(state_path.read_text())

    last_ids = set(state.get("last_item_ids", []))

    # 3. Filter to new items
    if not args.force:
        items = [i for i in items if i.get("id") not in last_ids]

    # 4. Minimum check
    if len(items) < 3 and not args.force:
        print(f"Not enough new likes ({len(items)}). Use --force to override.")
        sys.exit(0)

    if not items:
        print("No items to process.")
        sys.exit(0)

    # 5. Group by section
    grouped = {}
    for item in items:
        section = item.get("section", "other")
        grouped.setdefault(section, []).append(item)

    # 6. Build prompt
    prompt_lines = [
        "You are a casual, friendly colleague sharing learnings from items I've been saving.",
        "Based on these bookmarked items from my daily newsletter, write a brief digest:",
        "- What topics am I gravitating toward?",
        "- Key insights across the items",
        "- Any emerging themes or patterns?",
        "",
        "Keep it conversational, like a Slack message to a teammate. Use 3-5 bullet points with emoji.",
        "Format as HTML (use <br> between bullets, emoji at start of each).",
        "",
        "Items:",
    ]
    for section, section_items in grouped.items():
        for item in section_items:
            title = item.get("title", "Untitled")
            summary = item.get("summary", "")
            # Strip HTML tags for prompt
            import re
            clean_summary = re.sub(r"<[^>]+>", " ", summary).strip()[:200]
            prompt_lines.append(f'[{section}] "{title}" - {clean_summary}')

    prompt = "\n".join(prompt_lines)

    # 7. Call Gemini
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not set")
        sys.exit(1)

    from google import genai

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )
    content_html = response.text.strip()

    # Strip markdown code fences if present
    if content_html.startswith("```"):
        content_html = content_html.split("\n", 1)[1] if "\n" in content_html else content_html[3:]
        if content_html.endswith("```"):
            content_html = content_html[:-3]
        content_html = content_html.strip()

    # 8. Save learnings.json
    item_ids = [i.get("id") for i in items if i.get("id")]
    output_data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "based_on_count": len(items),
        "content_html": content_html,
        "items_used": item_ids,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output_data, indent=2))
    print(f"Saved learnings to {args.output}")

    # 9. Update audit state
    state_path.write_text(json.dumps({
        "last_audit_date": datetime.now().isoformat(timespec="seconds"),
        "last_item_ids": item_ids,
    }, indent=2))

    # 10. Print content
    print("\n--- Generated Learnings ---")
    print(content_html)


if __name__ == "__main__":
    main()
