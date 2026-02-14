#!/usr/bin/env python3
"""Main newsletter generator: fetches all data, renders HTML, sends email."""

import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.weather import get_nyc_weather
from src.news import get_top_news
from src.podcasts import get_recent_episodes
from src.papers import get_ai_security_papers
from src.site_generator import update_site


def fetch_all_data() -> dict:
    """Fetch all newsletter sections in sequence."""
    print("Fetching NYC weather...")
    weather = get_nyc_weather()

    print("Fetching top news...")
    news = get_top_news(count=3)

    print("Fetching podcast episodes...")
    podcasts = get_recent_episodes(days=7)

    print("Fetching AI security papers...")
    papers = get_ai_security_papers(days_back=7, top_n=5)

    return {
        "date": datetime.now().strftime("%A, %B %d, %Y"),
        "weather": weather,
        "news": news,
        "podcasts": podcasts,
        "papers": papers,
    }


def render_html(data: dict) -> str:
    """Render the newsletter HTML template with data."""
    template_dir = PROJECT_ROOT / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("newsletter.html")
    return template.render(**data)


def send_email(html: str, to_email: str):
    """Send the newsletter via SMTP."""
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    from_email = os.getenv("EMAIL_ADDRESS")
    password = os.getenv("EMAIL_PASSWORD")

    if not from_email or not password:
        print("ERROR: EMAIL_ADDRESS and EMAIL_PASSWORD must be set in .env")
        print("Saving newsletter to output.html instead...")
        output_path = PROJECT_ROOT / "output.html"
        output_path.write_text(html)
        print(f"Saved to {output_path}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your Daily Briefing - {datetime.now().strftime('%B %d, %Y')}"
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(from_email, password)
        server.sendmail(from_email, to_email, msg.as_string())

    print(f"Newsletter sent to {to_email}")


def main():
    load_dotenv(PROJECT_ROOT / ".env")

    data = fetch_all_data()
    html = render_html(data)

    # Generate static site files (archive, index, RSS)
    update_site(data, html)

    to_email = os.getenv("RECIPIENT_EMAIL", os.getenv("EMAIL_ADDRESS", ""))
    if to_email:
        send_email(html, to_email)
    else:
        output_path = PROJECT_ROOT / "output.html"
        output_path.write_text(html)
        print(f"No email configured. Newsletter saved to {output_path}")


if __name__ == "__main__":
    main()
