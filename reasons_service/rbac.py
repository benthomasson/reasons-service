"""Role-based access control definitions and permission checks."""

from dataclasses import dataclass
from enum import StrEnum

from fastapi import HTTPException, Request


class Action(StrEnum):
    READ = "read"
    CHAT = "chat"
    EDIT_BELIEFS = "edit_beliefs"
    MANAGE_SOURCES = "manage_sources"
    MANAGE_PROJECTS = "manage_projects"
    ADMIN = "admin"


class Role(StrEnum):
    ADMIN = "admin"
    EDITOR = "editor"
    READER = "reader"


@dataclass(frozen=True, slots=True)
class UserInfo:
    identity: str
    role: str
    display_name: str | None = None
    visible_tags: list[str] | None = None


ROLE_ACTIONS: dict[Role, frozenset[Action]] = {
    Role.EDITOR: frozenset({
        Action.READ, Action.CHAT, Action.EDIT_BELIEFS, Action.MANAGE_SOURCES,
    }),
    Role.READER: frozenset({
        Action.READ, Action.CHAT,
    }),
}


def has_permission(role: str, action: Action) -> bool:
    if role == Role.ADMIN:
        return True
    return action in ROLE_ACTIONS.get(role, frozenset())


def require_action(action: Action):
    async def _check(request: Request):
        user = request.state.user
        if not has_permission(user.role, action):
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user.role}' lacks '{action}' permission",
            )
    return _check
