#!/usr/bin/env python3
"""Manage users in reasons-service.

Works with both SQLite and PostgreSQL. Detects backend from DATABASE_URL
env var, or pass --db path/to/reasons.db for direct SQLite access.

Usage:
    python scripts/manage_users.py add <email> [--role admin|editor|reader] [--name "Display Name"]
    python scripts/manage_users.py list
    python scripts/manage_users.py remove <email>

Examples:
    # SQLite (direct path)
    python scripts/manage_users.py --db /home/reasons/data/reasons.db add user@example.com --role admin

    # SQLite (via DATABASE_URL)
    DATABASE_URL=sqlite+aiosqlite:///data/reasons.db python scripts/manage_users.py list

    # PostgreSQL (via DATABASE_URL)
    DATABASE_URL=postgresql://ben@localhost:5432/reasons_service python scripts/manage_users.py list
"""

import os
import sys


def parse_args():
    email = None
    role = "reader"
    display_name = None
    db_path = None
    command = None

    args = sys.argv[1:]
    i = 0
    positional = []
    while i < len(args):
        if args[i] == "--db":
            i += 1
            db_path = args[i]
        elif args[i] == "--role":
            i += 1
            role = args[i]
        elif args[i] == "--name":
            i += 1
            display_name = args[i]
        else:
            positional.append(args[i])
        i += 1

    if positional:
        command = positional[0]
    if len(positional) > 1:
        email = positional[1].strip().lower()

    return command, email, role, display_name, db_path


def get_sqlite_conn(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def get_pg_conn(url):
    import psycopg
    conninfo = url
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if conninfo.startswith(prefix):
            conninfo = "postgresql://" + conninfo[len(prefix):]
    return psycopg.connect(conninfo)


def detect_backend(db_path):
    if db_path:
        return "sqlite", db_path

    url = os.getenv("DATABASE_URL", "")
    if url.startswith("sqlite"):
        for prefix in ("sqlite+aiosqlite:///", "sqlite:///"):
            if url.startswith(prefix):
                return "sqlite", url[len(prefix):]
        return "sqlite", url.replace("sqlite+aiosqlite://", "").replace("sqlite://", "")

    if url:
        return "postgresql", url

    return "postgresql", "postgresql://ben@localhost:5432/reasons_service"


def main():
    command, email, role, display_name, db_path = parse_args()

    if not command:
        print(__doc__)
        sys.exit(1)

    backend, conn_target = detect_backend(db_path)

    if backend == "sqlite":
        conn = get_sqlite_conn(conn_target)
        placeholder = "?"
        now_expr = "datetime('now')"
        upsert_sql = (
            f"INSERT INTO users (email, role, display_name, created_at, updated_at) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}, {now_expr}, {now_expr}) "
            f"ON CONFLICT (email) DO UPDATE SET role = excluded.role, "
            f"display_name = COALESCE(excluded.display_name, users.display_name), "
            f"updated_at = {now_expr}"
        )
    else:
        conn = get_pg_conn(conn_target)
        placeholder = "%s"
        upsert_sql = (
            f"INSERT INTO users (email, role, display_name) "
            f"VALUES ({placeholder}, {placeholder}, {placeholder}) "
            f"ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role, "
            f"display_name = COALESCE(EXCLUDED.display_name, users.display_name), "
            f"updated_at = now()"
        )

    cur = conn.cursor()

    if command == "add":
        if not email:
            print("Usage: manage_users.py add <email> [--role admin|editor|reader] [--name 'Name']")
            sys.exit(1)
        cur.execute(upsert_sql, (email, role, display_name))
        conn.commit()
        print(f"Added user: {email} (role={role})")

    elif command == "list":
        cur.execute("SELECT email, role, display_name, created_at FROM users ORDER BY created_at")
        rows = cur.fetchall()
        if not rows:
            print("No users.")
        else:
            print(f"{'Email':<40} {'Role':<10} {'Name':<30}")
            print("-" * 80)
            for email, role, name, created_at in rows:
                print(f"{email:<40} {role:<10} {name or '':<30}")

    elif command == "remove":
        if not email:
            print("Usage: manage_users.py remove <email>")
            sys.exit(1)
        cur.execute(f"DELETE FROM users WHERE email = {placeholder}", (email,))
        if cur.rowcount == 0:
            print(f"User not found: {email}")
        else:
            print(f"Removed user: {email}")
        conn.commit()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
