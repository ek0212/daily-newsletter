"""YouTube Shorts script and graphics generator for the daily newsletter."""

import argparse
import json
import os
import re
import textwrap
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

from constants import (
    GEMINI_MODEL,
    SHORTS_WIDTH, SHORTS_HEIGHT, SHORTS_DIR,
    SHORTS_HOOK_BG, SHORTS_BODY_BG, SHORTS_CTA_BG,
    SHORTS_ACCENT, SHORTS_TEXT_LIGHT, SHORTS_TEXT_DARK,
    SHORTS_FONT_HOOK, SHORTS_FONT_BODY, SHORTS_FONT_STAT,
    SHORTS_FONT_CTA, SHORTS_FONT_SMALL, SHORTS_MARGIN,
)


# ── Font loading ──────────────────────────────────────────────────────

def _load_font(size):
    for path in [
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Times.ttc",
        "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


# ── Data loading ──────────────────────────────────────────────────────

def _load_items(date_str=None, from_likes=False):
    """Load newsletter items from archive JSON or likes."""
    if from_likes:
        likes_path = Path("site/likes.json")
        if not likes_path.exists():
            print("No site/likes.json found.")
            return []
        return json.loads(likes_path.read_text())

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    archive = Path(f"site/posts/{date_str}.json")
    if not archive.exists():
        print(f"No archive found for {date_str}")
        return []

    data = json.loads(archive.read_text())
    items = []
    for section in ("news", "youtube", "ai_security"):
        for item in data.get(section, []):
            item["_section"] = section
            items.append(item)
    return items


# ── Saliency scoring ─────────────────────────────────────────────────

def _score_item(item):
    score = 0
    summary = item.get("summary", "")
    emoji_re = re.compile(r"[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U00002702-\U000027B0]")
    if len(emoji_re.findall(summary)) >= 3:
        score += 3
    section = item.get("_section", "")
    if section == "ai_security":
        score += 2
    elif section == "news":
        score += 1
    if len(summary) > 200:
        score += 1
    if len(item.get("raw_text", "")) > 500:
        score += 1
    return score


def _select_items(items, count):
    scored = sorted(items, key=_score_item, reverse=True)
    return scored[:count]


# ── Gemini script generation ─────────────────────────────────────────

def _generate_script(item):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("WARNING: GEMINI_API_KEY not set, skipping script generation.")
        return None

    from google import genai

    title = item.get("title", "Untitled")
    summary = item.get("summary", "")
    raw_text = item.get("raw_text", "")[:1000]
    source_content = f"{summary}\n{raw_text}".strip()

    prompt = f"""Write a YouTube Shorts script (under 60 seconds when spoken aloud) about this topic.

Structure it as:
HOOK (first 3 seconds): A surprising question, bold claim, or "Did you know..." that stops the scroll. Must create curiosity gap.
BODY (45 seconds): The key insight explained simply. Include ONE concrete number, name, or example. Break complex ideas into "imagine if..." analogies.
CTA (5 seconds): End with "Follow for your daily AI briefing" or similar.

Topic: {title}
Source content: {source_content}

Output EXACTLY in this format (no other text):
HOOK: [your hook text]
BODY: [your body text]
CTA: [your CTA text]
KEY_STAT: [the single most striking number/fact for the graphic overlay]"""

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
    return _parse_script(response.text)


def _parse_script(text):
    sections = {}
    for key in ("HOOK", "BODY", "CTA", "KEY_STAT"):
        match = re.search(rf"^{key}:\s*(.+?)(?=\n[A-Z_]+:|$)", text, re.MULTILINE | re.DOTALL)
        sections[key] = match.group(1).strip() if match else ""
    return sections


# ── Graphics generation ──────────────────────────────────────────────

def _wrap_text(text, font, max_width, draw):
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_centered_text(draw, lines, font, color, y_start, width):
    """Draw lines of text centered horizontally."""
    y = y_start
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        x = (width - lw) // 2
        draw.text((x, y), line, fill=color, font=font)
        y += lh + 10
    return y


def _generate_hook_slide(script, output_path):
    img = Image.new("RGB", (SHORTS_WIDTH, SHORTS_HEIGHT), SHORTS_HOOK_BG)
    draw = ImageDraw.Draw(img)
    font = _load_font(SHORTS_FONT_HOOK)
    max_w = SHORTS_WIDTH - 2 * SHORTS_MARGIN
    lines = _wrap_text(script["HOOK"], font, max_w, draw)

    # Center in bottom 60% (y range: 40%-90% of height)
    line_h = draw.textbbox((0, 0), "Ag", font=font)[3] + 10
    block_h = len(lines) * line_h
    y_start = int(SHORTS_HEIGHT * 0.4) + (int(SHORTS_HEIGHT * 0.5) - block_h) // 2
    _draw_centered_text(draw, lines, font, SHORTS_TEXT_LIGHT, y_start, SHORTS_WIDTH)

    # Red accent line at bottom
    line_y = int(SHORTS_HEIGHT * 0.9)
    line_w = int(SHORTS_WIDTH * 0.6)
    x0 = (SHORTS_WIDTH - line_w) // 2
    draw.line([(x0, line_y), (x0 + line_w, line_y)], fill=SHORTS_ACCENT, width=3)

    img.save(output_path)


def _generate_body_slide(script, source_name, output_path):
    img = Image.new("RGB", (SHORTS_WIDTH, SHORTS_HEIGHT), SHORTS_BODY_BG)
    draw = ImageDraw.Draw(img)

    # KEY_STAT in top area (15-35%)
    stat_font = _load_font(SHORTS_FONT_STAT)
    max_w = SHORTS_WIDTH - 2 * SHORTS_MARGIN
    stat_lines = _wrap_text(script["KEY_STAT"], stat_font, max_w, draw)
    stat_y = int(SHORTS_HEIGHT * 0.15)
    y = _draw_centered_text(draw, stat_lines, stat_font, SHORTS_ACCENT, stat_y, SHORTS_WIDTH)

    # Body text below
    body_font = _load_font(SHORTS_FONT_BODY)
    body_lines = _wrap_text(script["BODY"], body_font, max_w, draw)
    body_y = max(y + 40, int(SHORTS_HEIGHT * 0.35))
    for line in body_lines:
        bbox = draw.textbbox((0, 0), line, font=body_font)
        lh = bbox[3] - bbox[1]
        draw.text((SHORTS_MARGIN, body_y), line, fill=SHORTS_TEXT_DARK, font=body_font)
        body_y += lh + 10

    # Source attribution at bottom
    small_font = _load_font(SHORTS_FONT_SMALL)
    src_text = f"Source: {source_name}"
    bbox = draw.textbbox((0, 0), src_text, font=small_font)
    sx = (SHORTS_WIDTH - (bbox[2] - bbox[0])) // 2
    draw.text((sx, int(SHORTS_HEIGHT * 0.9)), src_text, fill="#888888", font=small_font)

    img.save(output_path)


def _generate_cta_slide(script, output_path):
    img = Image.new("RGB", (SHORTS_WIDTH, SHORTS_HEIGHT), SHORTS_CTA_BG)
    draw = ImageDraw.Draw(img)

    cta_font = _load_font(SHORTS_FONT_CTA)
    max_w = SHORTS_WIDTH - 2 * SHORTS_MARGIN
    lines = _wrap_text(script["CTA"], cta_font, max_w, draw)

    line_h = draw.textbbox((0, 0), "Ag", font=cta_font)[3] + 10
    block_h = len(lines) * line_h
    y_start = (SHORTS_HEIGHT - block_h) // 2 - 40
    y = _draw_centered_text(draw, lines, cta_font, SHORTS_TEXT_LIGHT, y_start, SHORTS_WIDTH)

    # Down arrow
    arrow_font = _load_font(SHORTS_FONT_STAT)
    arrow = "v"
    bbox = draw.textbbox((0, 0), arrow, font=arrow_font)
    ax = (SHORTS_WIDTH - (bbox[2] - bbox[0])) // 2
    draw.text((ax, y + 30), arrow, fill=SHORTS_TEXT_LIGHT, font=arrow_font)

    # Branding at bottom
    small_font = _load_font(SHORTS_FONT_SMALL)
    brand = "Daily Briefing"
    bbox = draw.textbbox((0, 0), brand, font=small_font)
    bx = (SHORTS_WIDTH - (bbox[2] - bbox[0])) // 2
    draw.text((bx, int(SHORTS_HEIGHT * 0.85)), brand, fill="#888888", font=small_font)

    img.save(output_path)


def _generate_graphics(script, item, date_str, index, shorts_dir):
    if not HAS_PILLOW:
        print("WARNING: Pillow not installed. Skipping graphics. Install with: pip install Pillow")
        return

    source_name = item.get("channel") or item.get("source") or item.get("_section", "")
    prefix = f"{date_str}-{index}"

    hook_path = shorts_dir / f"{prefix}-hook.png"
    body_path = shorts_dir / f"{prefix}-body.png"
    cta_path = shorts_dir / f"{prefix}-cta.png"

    _generate_hook_slide(script, hook_path)
    _generate_body_slide(script, source_name, body_path)
    _generate_cta_slide(script, cta_path)

    for p in (hook_path, body_path, cta_path):
        print(f"  Generated: {p}")


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate YouTube Shorts scripts and graphics")
    parser.add_argument("--from-likes", action="store_true", help="Use liked items from site/likes.json")
    parser.add_argument("--date", type=str, default=None, help="Date to load (YYYY-MM-DD)")
    parser.add_argument("--count", type=int, default=1, help="Number of shorts to generate")
    parser.add_argument("--no-graphics", action="store_true", help="Script only, skip PNG generation")
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    items = _load_items(date_str=date_str, from_likes=args.from_likes)
    if not items:
        print("No items found. Exiting.")
        return

    selected = _select_items(items, args.count)
    shorts_dir = Path(SHORTS_DIR)
    shorts_dir.mkdir(parents=True, exist_ok=True)

    for i, item in enumerate(selected, 1):
        title = item.get("title", "Untitled")
        print(f"\n{'='*60}")
        print(f"Short #{i}: {title}")
        print(f"{'='*60}")

        script = _generate_script(item)
        if not script:
            continue

        # Save script text
        script_path = shorts_dir / f"{date_str}-{i}.txt"
        with open(script_path, "w") as f:
            for key in ("HOOK", "BODY", "CTA", "KEY_STAT"):
                f.write(f"{key}: {script[key]}\n\n")
        print(f"  Script saved: {script_path}")

        # Print script
        for key in ("HOOK", "BODY", "CTA", "KEY_STAT"):
            print(f"  {key}: {script[key]}")

        # Generate graphics
        if not args.no_graphics:
            _generate_graphics(script, item, date_str, i, shorts_dir)


if __name__ == "__main__":
    main()
