from fastapi import Header, HTTPException

from .services.compiler import ROLES


def get_role(x_role: str | None = Header(default=None)) -> str:
    """Demo identity: the role is taken from the X-Role header (admin | analyst | viewer).

    Replace with real authentication before exposing the service; authorization itself is
    enforced by the execution layer from this role on every request."""
    role = (x_role or "analyst").lower()
    if role not in ROLES:
        raise HTTPException(400, f"unknown role '{role}', expected one of {ROLES}")
    return role


def require_reviewer(role: str) -> None:
    if role not in ("admin", "analyst"):
        raise HTTPException(403, "metadata review requires the analyst or admin role")


def require_admin(role: str) -> None:
    if role != "admin":
        raise HTTPException(403, "this action requires the admin role")
