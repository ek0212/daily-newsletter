#!/usr/bin/env python3
"""Flask backend for newsletter: login, per-bullet likes, and script generation."""

import hashlib
import json
import logging
import os
import sqlite3
import textwrap
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, session

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="../site", static_url_path="")
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-change-me")

DB_PATH = Path(__file__).parent.parent / "data" / "newsletter.db"


def get_db():
    if "db" not in g:
        DB_PATH.parent.mkdir(exist_ok=True)
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    db_path = DB_PATH
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS likes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            bullet_text TEXT NOT NULL,
            article_title TEXT DEFAULT '',
            section TEXT DEFAULT '',
            newsletter_date TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_likes_user ON likes(user_id);
    """)
    conn.close()


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# --- Auth endpoints ---

@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, _hash_password(password)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already taken"}), 409
    user = db.execute("SELECT id, username FROM users WHERE username = ?", (username,)).fetchone()
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"username": user["username"]})


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json()
    username = (data.get("username") or "").strip()
    password = (data.get("password") or "").strip()
    db = get_db()
    user = db.execute(
        "SELECT id, username FROM users WHERE username = ? AND password_hash = ?",
        (username, _hash_password(password)),
    ).fetchone()
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401
    session["user_id"] = user["id"]
    session["username"] = user["username"]
    return jsonify({"username": user["username"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    if "user_id" not in session:
        return jsonify({"user": None})
    return jsonify({"user": {"username": session["username"]}})


# --- Likes endpoints ---

@app.route("/api/likes", methods=["GET"])
def get_likes():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    db = get_db()
    rows = db.execute(
        "SELECT id, bullet_text, article_title, section, newsletter_date, created_at "
        "FROM likes WHERE user_id = ? ORDER BY created_at DESC",
        (session["user_id"],),
    ).fetchall()
    return jsonify({"likes": [dict(r) for r in rows]})


@app.route("/api/likes", methods=["POST"])
def add_like():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    bullet_text = (data.get("bullet_text") or "").strip()
    if not bullet_text:
        return jsonify({"error": "bullet_text required"}), 400
    db = get_db()
    # Prevent duplicates
    existing = db.execute(
        "SELECT id FROM likes WHERE user_id = ? AND bullet_text = ?",
        (session["user_id"], bullet_text),
    ).fetchone()
    if existing:
        return jsonify({"ok": True, "id": existing["id"]})
    cur = db.execute(
        "INSERT INTO likes (user_id, bullet_text, article_title, section, newsletter_date) VALUES (?, ?, ?, ?, ?)",
        (
            session["user_id"],
            bullet_text,
            data.get("article_title", ""),
            data.get("section", ""),
            data.get("newsletter_date", ""),
        ),
    )
    db.commit()
    return jsonify({"ok": True, "id": cur.lastrowid})


@app.route("/api/likes/<int:like_id>", methods=["DELETE"])
def remove_like(like_id):
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    db = get_db()
    db.execute("DELETE FROM likes WHERE id = ? AND user_id = ?", (like_id, session["user_id"]))
    db.commit()
    return jsonify({"ok": True})


# --- Script generation ---

@app.route("/api/generate-script", methods=["POST"])
def generate_script():
    if "user_id" not in session:
        return jsonify({"error": "Not logged in"}), 401
    data = request.get_json()
    bullet_texts = data.get("bullets", [])
    if not bullet_texts:
        return jsonify({"error": "No bullets selected"}), 400

    # Build prompt
    bullets_block = "\n".join(f"- {b}" for b in bullet_texts)
    prompt = textwrap.dedent(f"""\
        You are an educational content writer. The user liked these bullet points from a daily newsletter:

        {bullets_block}

        Your task:
        1. Use your knowledge and search to research each topic in more depth.
        2. Write a 2-3 minute spoken script (roughly 350-500 words) that explains these topics in an educational, engaging way.
        3. The script should be conversational but informative — imagine explaining these topics to a smart friend over coffee.
        4. Add context, background, and "why it matters" for each topic.
        5. Weave the topics together naturally if they're related, otherwise use clear transitions.
        6. Start with a brief hook, end with a takeaway.

        Return ONLY the script text, ready to be read aloud. No stage directions, no markdown formatting.
    """)

    # Use Gemini
    api_keys = []
    for var in ["GEMINI_API_KEY", "GEMINI_API_KEY_2"]:
        k = os.getenv(var)
        if k:
            api_keys.append(k)
    if not api_keys:
        return jsonify({"error": "No Gemini API keys configured"}), 500

    from google import genai
    from google.genai import types

    last_err = None
    for key in api_keys:
        try:
            client = genai.Client(api_key=key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            return jsonify({"script": response.text})
        except Exception as e:
            last_err = str(e)
            continue

    return jsonify({"error": f"All Gemini keys failed: {last_err}"}), 500


# --- Serve static site ---

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/<path:path>")
def static_files(path):
    return app.send_static_file(path)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5001, threaded=True)
