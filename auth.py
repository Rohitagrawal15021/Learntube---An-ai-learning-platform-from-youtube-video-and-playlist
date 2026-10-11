"""Minimal account + history store for LearnTube.

Deliberately dependency-free: standard-library ``sqlite3`` for storage,
Werkzeug (already installed) for password hashing, and Flask's signed-cookie
``session`` for login state. No Flask-Login / SQLAlchemy needed.
"""

import os
import sqlite3
from datetime import datetime, timezone
from functools import wraps

from flask import session, redirect, url_for, request, g
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join("data", "learntube.db")


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_db():
    """One sqlite connection per request (safe across Flask's worker threads)."""
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables on first run. Called once at startup."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at    TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL,
            kind        TEXT NOT NULL,          -- 'playlist' | 'video'
            ref_id      TEXT NOT NULL,          -- playlist_id or video_id
            title       TEXT,
            last_opened TEXT NOT NULL,
            UNIQUE(user_id, kind, ref_id)
        );
        """
    )
    con.commit()
    con.close()


# ---- users -----------------------------------------------------------------

def create_user(email, password):
    """Return (user_row, None) on success or (None, error_message)."""
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return None, "Please enter a valid email address."
    if not password or len(password) < 6:
        return None, "Password must be at least 6 characters."

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), _now()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        return None, "An account with that email already exists."

    return get_user_by_email(email), None


def get_user_by_email(email):
    row = get_db().execute(
        "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),)
    ).fetchone()
    return row


def get_user(user_id):
    if not user_id:
        return None
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def verify_user(email, password):
    """Return (user_row, None) if credentials match, else (None, message)."""
    user = get_user_by_email(email)
    if user and check_password_hash(user["password_hash"], password or ""):
        return user, None
    return None, "Email or password is incorrect."


# ---- session helpers -------------------------------------------------------

def login_session(user):
    session["uid"] = user["id"]
    session["email"] = user["email"]


def logout_session():
    session.pop("uid", None)
    session.pop("email", None)


def current_user():
    """The logged-in user row, or None."""
    return get_user(session.get("uid"))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("uid"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


# ---- history ---------------------------------------------------------------

def add_history(user_id, kind, ref_id, title):
    if not user_id or not ref_id:
        return
    db = get_db()
    db.execute(
        """INSERT INTO history (user_id, kind, ref_id, title, last_opened)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(user_id, kind, ref_id)
           DO UPDATE SET last_opened = excluded.last_opened, title = excluded.title""",
        (user_id, kind, ref_id, title or ref_id, _now()),
    )
    db.commit()


def list_history(user_id, limit=12):
    if not user_id:
        return []
    rows = get_db().execute(
        "SELECT * FROM history WHERE user_id = ? ORDER BY last_opened DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]
