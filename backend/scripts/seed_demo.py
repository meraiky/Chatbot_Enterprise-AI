"""
Seed the database with demo users, topic-guard patterns, and a sample QA-cache entry.

Usage (from project root, after `alembic upgrade head`):
    python -m scripts.seed_demo

Environment: reads DATABASE_URL from .env or environment.
"""

import os
import secrets
import sys
from pathlib import Path

# Allow running from backend/ root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2  # type: ignore[import-untyped]
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from app.core.auth import get_password_hash

DATABASE_URL = os.environ["DATABASE_URL"]
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()
ALLOW_DEMO_SEED = os.environ.get("ALLOW_DEMO_SEED", "").lower() in {"1", "true", "yes"}


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def _pwd(env_var: str) -> str:
    """Return env override if set, otherwise generate a secure random password."""
    return os.environ.get(env_var) or secrets.token_urlsafe(16)


DEMO_USERS = [
    {"username": "admin",    "password": _pwd("SEED_ADMIN_PASSWORD"),    "role": "admin"},
    {"username": "alice",    "password": _pwd("SEED_ALICE_PASSWORD"),    "role": "user"},
    {"username": "readonly", "password": _pwd("SEED_READONLY_PASSWORD"), "role": "user"},
]

TOPIC_GUARD_PATTERNS = [
    {"pattern": "ignore previous instructions", "reason": "prompt injection", "is_regex": False},
    {"pattern": "you are now (?:DAN|jailbreak)", "reason": "jailbreak attempt", "is_regex": True},
    {"pattern": "forget all rules",              "reason": "prompt injection", "is_regex": False},
    {"pattern": "act as an unrestricted AI",     "reason": "jailbreak attempt", "is_regex": False},
]


def seed_users(conn):
    with conn.cursor() as cur:
        for u in DEMO_USERS:
            cur.execute(
                "SELECT id FROM users WHERE username = %s",
                (u["username"],),
            )
            if cur.fetchone():
                print(f"  user '{u['username']}' already exists, skipping")
                continue
            cur.execute(
                "INSERT INTO users (username, hashed_password, role, is_active) VALUES (%s, %s, %s, TRUE)",
                (u["username"], get_password_hash(u["password"]), u["role"]),
            )
            print(f"  created user '{u['username']}' ({u['role']})")
    conn.commit()


def seed_topic_guard(conn):
    with conn.cursor() as cur:
        for p in TOPIC_GUARD_PATTERNS:
            cur.execute(
                "SELECT id FROM topic_guard WHERE pattern = %s",
                (p["pattern"],),
            )
            if cur.fetchone():
                pattern = str(p["pattern"])
                print(f"  topic_guard pattern already exists: {pattern[:40]!r}")
                continue
            cur.execute(
                "INSERT INTO topic_guard (pattern, reason, is_regex, is_active) VALUES (%s, %s, %s, TRUE)",
                (p["pattern"], p["reason"], p["is_regex"]),
            )
            pattern = str(p["pattern"])
            print(f"  added topic_guard: {pattern[:40]!r}")
    conn.commit()


def print_summary():
    sep = "-" * 56
    print(f"\n{sep}")
    print("  Demo credentials (CHANGE BEFORE EXPOSING TO ANY NETWORK)")
    print(sep)
    for u in DEMO_USERS:
        print(f"  username: {u['username']:<12}  password: {u['password']:<14}  role: {u['role']}")
    print(sep)
    print("  API:      http://localhost:8000/docs")
    print("  Frontend: http://localhost:3000")
    print(sep)
    print()
    print("  *** SECURITY WARNING ***")
    print("  These are demo passwords for local development only.")
    print("  Change all passwords via the Admin UI before any network")
    print("  exposure, staging deploy, or production use.")
    print(f"{sep}\n")


def main():
    if ENVIRONMENT in {"staging", "production"} and not ALLOW_DEMO_SEED:
        raise RuntimeError(
            "Refusing to seed demo credentials in staging/production. "
            "Set ALLOW_DEMO_SEED=true only for a deliberate isolated demo."
        )

    print("\nSeeding demo data ...")
    conn = get_conn()
    try:
        print("\n[users]")
        seed_users(conn)
        print("\n[topic_guard]")
        seed_topic_guard(conn)
    finally:
        conn.close()

    print_summary()
    print("Done.")


if __name__ == "__main__":
    main()
