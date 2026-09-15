"""Regression test for the PostgreSQL enum double-CREATE bug: migration
0001 (and, on inspection, 0002/0003/0004/0005/0007) declared a
`postgresql.ENUM(...)` and explicitly created it with `<enum>.create(bind,
checkfirst=True)`, then used that same enum object as a column type in
`op.create_table(...)`. `postgresql.ENUM` defaults to `create_type=True`,
which registers its own `before_create` event on any table that uses it
— so `op.create_table(...)` (which Alembic runs with `checkfirst=False`)
tried to `CREATE TYPE` a *second* time for the same name, raising
`asyncpg.exceptions.DuplicateObjectError: type "organization_role"
already exists` even on a completely fresh database, on the very first
`alembic upgrade head`.

Fixed by passing `create_type=False` to every such `postgresql.ENUM(...)`
declaration, making the explicit `.create()`/`.drop()` calls the sole
place each type is created or dropped.

Pure AST inspection of the migration files on disk — no `alembic`/
`sqlalchemy` import needed, so unlike most of this project's tests this
one has zero third-party dependencies and actually executes in this
sandbox. Migration chain linearity (0001 -> ... -> current head) is
already covered by
`test_docker_alembic_packaging.py::test_alembic_revision_chain_is_linear_and_unbroken`
— not duplicated here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _module_level_enum_assignments(tree: ast.Module) -> dict[str, ast.Call]:
    """Every `NAME = postgresql.ENUM(...)` (or `sa.Enum(...)`) assignment
    at module level, keyed by the assigned variable name."""

    result: dict[str, ast.Call] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func_name = getattr(call.func, "attr", None) or getattr(call.func, "id", None)
        if func_name in ("ENUM", "Enum"):
            result[target.id] = call
    return result


def _has_create_type_false(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg == "create_type" and isinstance(kw.value, ast.Constant):
            return kw.value.value is False
    return False


def test_every_explicitly_created_enum_disables_the_automatic_table_create():
    """For every migration that explicitly calls `<enum>.create(bind,
    ...)` on a module-level `postgresql.ENUM`, that enum must also be
    declared with `create_type=False` — otherwise using it as a column
    type in `op.create_table(...)` triggers a second, automatic
    `CREATE TYPE` for the same name and the migration fails against a
    completely fresh database."""

    checked_any = False
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        enums = _module_level_enum_assignments(tree)
        if not enums:
            continue

        for var_name, call in enums.items():
            explicitly_created = re.search(rf"\b{re.escape(var_name)}\.create\(", source)
            if not explicitly_created:
                # This project's convention (so far) is always to create
                # enums explicitly; a migration relying purely on the
                # automatic table-triggered create is a different,
                # equally valid pattern this test doesn't need to police.
                continue
            checked_any = True
            assert _has_create_type_false(call), (
                f"{path.name}: {var_name} is explicitly .create()'d but declared "
                f"without create_type=False — op.create_table() will try to CREATE "
                f"TYPE it a second time and fail with DuplicateObjectError"
            )

    assert checked_any, "expected at least one explicitly-created enum to check"


def test_0001_organization_role_specifically_disables_automatic_create():
    """The exact reported failure: `organization_role` in
    `0001_initial_schema.py`."""

    path = _VERSIONS_DIR / "0001_initial_schema.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    enums = _module_level_enum_assignments(tree)
    assert "_organization_role" in enums
    assert _has_create_type_false(enums["_organization_role"])
