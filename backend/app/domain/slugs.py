"""Slug generation — pure stdlib, no DB access, so it's independently
`pytest --noconftest`-runnable like `app/compatibility/`/`app/trajectory/`.

Used by `OrganizationService` to derive `Organization.slug` (required,
unique) from a user-supplied `name` when the onboarding request
deliberately accepts nothing but `{"name": "..."}"` (task §1 — no client-
supplied slug/id is accepted for a security-sensitive create)."""

import re
import uuid

_NON_SLUG_CHARS = re.compile(r"[^a-z0-9]+")


def slugify(name: str, *, max_base_length: int = 80) -> str:
    """Lowercase, hyphenate, and strip a human-supplied name into a slug
    base. Always suffixed with a short random token by
    `generate_unique_slug` below — this alone is not guaranteed unique."""

    base = _NON_SLUG_CHARS.sub("-", name.strip().lower()).strip("-")
    if not base:
        base = "organization"
    return base[:max_base_length].strip("-") or "organization"


def generate_unique_slug(name: str) -> str:
    """Derive a slug for a brand-new `Organization` row. Appends a short
    random suffix (rather than relying on a retry-on-collision loop) so
    a single insert attempt is, in practice, collision-free — the
    service still handles the theoretical collision the same way
    `ProjectService.create_project` handles any unique-constraint
    violation: `IntegrityError` -> rollback -> a specific domain error."""

    suffix = uuid.uuid4().hex[:8]
    return f"{slugify(name)}-{suffix}"
