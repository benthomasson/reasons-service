"""Admin CLI for reasons-service."""

import click
from sqlalchemy import create_engine, text

from reasons_service.config import settings


def _engine():
    return create_engine(settings.database_url_sync, echo=False)


@click.group()
def cli():
    """Reasons Service admin commands."""


# --- Users ---


@cli.group()
def user():
    """Manage users."""


@user.command("list")
def user_list():
    """List all users."""
    with _engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT email, role, display_name, tenant_id, created_at FROM users ORDER BY email"
        )).all()
    if not rows:
        click.echo("No users.")
        return
    for r in rows:
        tenant = f" (tenant: {r.tenant_id})" if r.tenant_id else ""
        name = f" [{r.display_name}]" if r.display_name else ""
        click.echo(f"  {r.email}  {r.role}{name}{tenant}")


@user.command("add")
@click.argument("email")
@click.option("--role", default="reader", type=click.Choice(["admin", "reviewer", "editor", "reader"]))
@click.option("--name", "display_name", default=None, help="Display name")
def user_add(email, role, display_name):
    """Add a user."""
    with _engine().connect() as conn:
        conn.execute(text(
            "INSERT INTO users (email, role, display_name) VALUES (:email, :role, :name)"
        ), {"email": email.strip().lower(), "role": role, "name": display_name or email})
        conn.commit()
    click.echo(f"Added {email} as {role}")


@user.command("set-role")
@click.argument("email")
@click.argument("role", type=click.Choice(["admin", "reviewer", "editor", "reader"]))
def user_set_role(email, role):
    """Change a user's role."""
    with _engine().connect() as conn:
        result = conn.execute(text(
            "UPDATE users SET role = :role, updated_at = now() WHERE email = :email"
        ), {"email": email.strip().lower(), "role": role})
        conn.commit()
    if result.rowcount:
        click.echo(f"Set {email} → {role}")
    else:
        click.echo(f"User {email} not found", err=True)


@user.command("remove")
@click.argument("email")
@click.confirmation_option(prompt="Are you sure?")
def user_remove(email):
    """Remove a user."""
    with _engine().connect() as conn:
        result = conn.execute(text("DELETE FROM users WHERE email = :email"), {"email": email.strip().lower()})
        conn.commit()
    if result.rowcount:
        click.echo(f"Removed {email}")
    else:
        click.echo(f"User {email} not found", err=True)


# --- Domains ---


@cli.group()
def domain():
    """Manage domains."""


@domain.command("list")
def domain_list():
    """List all domains."""
    with _engine().connect() as conn:
        rows = conn.execute(text(
            "SELECT id, name, public, members_only, tenant_id FROM domains ORDER BY name"
        )).all()
    if not rows:
        click.echo("No domains.")
        return
    for r in rows:
        flags = []
        if r.public:
            flags.append("public")
        if r.members_only:
            flags.append("members-only")
        tenant = f" (tenant: {r.tenant_id})" if r.tenant_id else ""
        click.echo(f"  {r.id}  {r.name}  {' '.join(flags)}{tenant}")


if __name__ == "__main__":
    cli()
