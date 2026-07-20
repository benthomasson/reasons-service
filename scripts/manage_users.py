#!/usr/bin/env python3
"""Manage users in reasons-service.

Usage:
    python scripts/manage_users.py add <email> [--role admin|editor|reader] [--name "Display Name"]
    python scripts/manage_users.py list
    python scripts/manage_users.py remove <email>
"""

import sys

import psycopg


CONNINFO = "postgresql://ben@localhost:5432/reasons_service"


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    pg = psycopg.connect(CONNINFO)

    if command == "add":
        if len(sys.argv) < 3:
            print("Usage: manage_users.py add <email> [--role admin|editor|reader] [--name 'Name']")
            sys.exit(1)
        email = sys.argv[2].strip().lower()
        role = "reader"
        display_name = None
        if "--role" in sys.argv:
            idx = sys.argv.index("--role")
            if idx + 1 < len(sys.argv):
                role = sys.argv[idx + 1]
        if "--name" in sys.argv:
            idx = sys.argv.index("--name")
            if idx + 1 < len(sys.argv):
                display_name = sys.argv[idx + 1]

        with pg.cursor() as cur:
            cur.execute(
                "INSERT INTO users (email, role, display_name) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role, "
                "display_name = COALESCE(EXCLUDED.display_name, users.display_name), "
                "updated_at = now()",
                (email, role, display_name),
            )
        pg.commit()
        print(f"Added user: {email} (role={role})")

    elif command == "list":
        with pg.cursor() as cur:
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
        if len(sys.argv) < 3:
            print("Usage: manage_users.py remove <email>")
            sys.exit(1)
        email = sys.argv[2].strip().lower()
        with pg.cursor() as cur:
            cur.execute("DELETE FROM users WHERE email = %s", (email,))
            if cur.rowcount == 0:
                print(f"User not found: {email}")
            else:
                print(f"Removed user: {email}")
        pg.commit()

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)

    pg.close()


if __name__ == "__main__":
    main()
