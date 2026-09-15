"""Regression test for the Alembic-in-Docker packaging bug: the API
image's Dockerfile copied `pyproject.toml` and `app/` but never
`alembic.ini` or `alembic/`, so `docker compose exec api alembic upgrade
head` failed with `FAILED: No config file 'alembic.ini' found, or file
has no '[alembic]' section` even though `alembic` itself (a pyproject.toml
dependency) was installed in the image — the CLI had nothing to read.

Two checks, both pure text/AST inspection of files already on disk — no
`alembic`/`sqlalchemy`/`pydantic` import needed, so unlike most of this
project's tests this one has zero third-party dependencies and actually
executes in this sandbox:

1. The Dockerfile actually COPYs both `alembic.ini` and the `alembic`
   directory into the image, so this specific omission can't silently
   come back.
2. The migration chain itself (0001 through the current head) is a
   single unbroken line with no gaps, branches, or duplicate revision
   ids — the thing `alembic upgrade head` needs to be true regardless of
   how it's invoked.
"""

from __future__ import annotations

import re
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
_DOCKERFILE = _BACKEND_DIR / "Dockerfile"
_VERSIONS_DIR = _BACKEND_DIR / "alembic" / "versions"

_REVISION_RE = re.compile(r'^revision:\s*str\s*=\s*"([^"]+)"', re.MULTILINE)
_DOWN_REVISION_RE = re.compile(r"^down_revision:\s*str\s*\|\s*None\s*=\s*(.+)$", re.MULTILINE)


def _dockerfile_copy_lines() -> list[str]:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip().startswith("COPY ")]


def test_dockerfile_copies_alembic_config_and_versions():
    copy_lines = _dockerfile_copy_lines()

    copies_ini = any("alembic.ini" in line for line in copy_lines)
    copies_dir = any(
        re.search(r"\balembic\b", line) and "alembic.ini" not in line for line in copy_lines
    )

    assert copies_ini, (
        f"Dockerfile has no COPY line for alembic.ini — `alembic upgrade head` "
        f"will fail inside the container with 'No config file' again. COPY lines: {copy_lines}"
    )
    assert copies_dir, (
        f"Dockerfile has no COPY line for the alembic/ directory — the migration "
        f"chain won't exist inside the container. COPY lines: {copy_lines}"
    )


def _parse_revision(path: Path) -> tuple[str, str | None]:
    text = path.read_text(encoding="utf-8")
    revision_match = _REVISION_RE.search(text)
    down_match = _DOWN_REVISION_RE.search(text)
    assert revision_match, f"{path} has no `revision: str = ...` line"
    assert down_match, f"{path} has no `down_revision: str | None = ...` line"
    revision = revision_match.group(1)
    down_raw = down_match.group(1).strip()
    down_revision = None if down_raw == "None" else down_raw.strip('"')
    return revision, down_revision


def test_alembic_revision_chain_is_linear_and_unbroken():
    version_files = sorted(_VERSIONS_DIR.glob("*.py"))
    assert version_files, "no migration files found under alembic/versions/"

    revisions: dict[str, str | None] = {}
    for path in version_files:
        revision, down_revision = _parse_revision(path)
        assert revision not in revisions, f"duplicate revision id {revision!r} ({path})"
        revisions[revision] = down_revision

    roots = [rev for rev, down in revisions.items() if down is None]
    assert len(roots) == 1, f"expected exactly one root revision (down_revision=None), got {roots}"

    down_revisions = list(revisions.values())
    heads = [rev for rev in revisions if rev not in down_revisions]
    assert len(heads) == 1, f"expected exactly one head revision, got {heads}"

    # Walk root -> head following down_revision links; every revision
    # must be visited exactly once (no branches, no orphans, no cycles).
    by_down_revision = {down: rev for rev, down in revisions.items()}
    visited: list[str] = []
    current: str | None = None
    while True:
        next_rev = by_down_revision.get(current)
        if next_rev is None:
            break
        assert next_rev not in visited, f"cycle detected at revision {next_rev!r}"
        visited.append(next_rev)
        current = next_rev

    assert set(visited) == set(revisions), (
        f"migration chain is broken: reachable from root {sorted(visited)}, "
        f"declared {sorted(revisions)}"
    )
    assert visited[-1] == heads[0]
