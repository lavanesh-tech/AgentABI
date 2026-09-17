"""Regression test for the exact class of bug that caused the onboarding
runtime failure: `app.audit.actions.AuditAction` (the application-layer
source of truth) gaining a member with no corresponding Postgres
`audit_action` enum value, so `AuditService.record()` for that action
fails at commit with `InvalidTextRepresentationError`.

Unlike every other `tests/test_*_api.py` file in this suite, this test
needs neither SQLAlchemy nor a live Postgres connection — it statically
parses the Alembic migration source files that declare `audit_action`'s
values (rather than importing them, which would require `alembic`/
`sqlalchemy` to be installed) and compares that set against
`AuditAction`'s members. Both `app.audit.actions` (stdlib `enum` only)
and this file itself are importable with nothing but the standard
library, so this test actually runs in environments where the rest of
`tests/test_*_api.py` cannot (see every other test file's module
docstring for that sandbox constraint) — it can be run directly with
`python3 -m unittest tests.test_audit_action_enum_sync` as well as via
pytest.

If this test starts failing, it means a value was added to `AuditAction`
without a migration adding it to the database enum (or vice versa) —
exactly what happened with `ORGANIZATION_CREATED` before migration 0011.
The fix is always a new additive migration (see 0011's docstring for why
downgrading this enum is refused rather than attempted automatically),
never editing 0007 or 0011 in place.
"""

import ast
import re
import unittest
from pathlib import Path

from app.audit.actions import AuditAction

_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def _assignment_targets(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Assign):
        return [t.id for t in node.targets if isinstance(t, ast.Name)]
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return [node.target.id]
    return []


def _string_constants_from_value(value: ast.AST) -> set[str]:
    """Positional-only for a `Call` (so `postgresql.ENUM("a", "b",
    name="audit_action", create_type=False)`'s `name=`/other keyword
    strings are never mistaken for enum member values); every element
    for a `Tuple`/`List` literal (e.g. `_MISSING_VALUES = ("a", "b")`)."""

    if isinstance(value, ast.Call):
        source_nodes: list[ast.AST] = list(value.args)
    elif isinstance(value, ast.Tuple | ast.List):
        source_nodes = list(value.elts)
    else:
        source_nodes = [value]

    values: set[str] = set()
    for node in source_nodes:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                values.add(sub.value)
    return values


def _extract_string_list_literal(source: str, *, variable_pattern: str) -> set[str]:
    """Parse `source` with `ast` and return every string literal declared
    as an enum member value in the assignment whose target matches
    `variable_pattern`. Works for both the `postgresql.ENUM("a", "b",
    ...)` call form (0007) and the `_MISSING_VALUES: tuple[str, ...] =
    ("a", "b", ...)` annotated-tuple form (0011)."""

    tree = ast.parse(source)
    values: set[str] = set()
    for node in ast.walk(tree):
        targets = _assignment_targets(node)
        if not targets or not any(re.fullmatch(variable_pattern, t) for t in targets):
            continue
        value_node = node.value  # type: ignore[union-attr]
        values |= _string_constants_from_value(value_node)
    return values


def _migrated_audit_action_values() -> set[str]:
    """Every value the `audit_action` Postgres enum has ever been told to
    contain, across every migration that touches it (currently 0007's
    initial `CREATE TYPE` and 0011's additive `ALTER TYPE ... ADD
    VALUE`s). Extend this list's file/variable pairs, never rewrite an
    already-applied migration, when a future migration adds more."""

    sources: list[tuple[str, str]] = [
        ("0007_security_audit_and_github_webhooks.py", r"_audit_action"),
        ("0011_audit_action_missing_values.py", r"_MISSING_VALUES"),
    ]
    values: set[str] = set()
    for filename, variable_pattern in sources:
        path = _VERSIONS_DIR / filename
        values |= _extract_string_list_literal(path.read_text(), variable_pattern=variable_pattern)
    return values


class AuditActionEnumSyncTest(unittest.TestCase):
    def test_every_application_audit_action_is_migrated(self) -> None:
        application_values = {member.value for member in AuditAction}
        migrated_values = _migrated_audit_action_values()

        missing_from_database = application_values - migrated_values
        self.assertEqual(
            missing_from_database,
            set(),
            "AuditAction has value(s) with no corresponding audit_action "
            "Postgres enum migration — recording that action will fail at "
            "commit with InvalidTextRepresentationError, exactly like "
            "ORGANIZATION_CREATED did before migration 0011. Add a new "
            "additive migration (never edit an applied one).",
        )

    def test_migrations_do_not_declare_unknown_values(self) -> None:
        """Catches the opposite drift too: a value the database enum
        knows about that `AuditAction` no longer has (e.g. a typo fixed
        in the application enum without a corresponding migration note).
        Not a runtime failure by itself, but worth keeping in sync."""

        application_values = {member.value for member in AuditAction}
        migrated_values = _migrated_audit_action_values()

        unknown_to_application = migrated_values - application_values
        self.assertEqual(
            unknown_to_application,
            set(),
            "audit_action Postgres enum has value(s) that AuditAction no "
            "longer declares — confirm this is intentional (Postgres enum "
            "values cannot be safely removed; see 0011's downgrade()).",
        )


if __name__ == "__main__":
    unittest.main()
