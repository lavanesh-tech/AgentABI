"""Regression test for the Grafana bind-mount bug: `docker compose up`
failed with `error mounting ".../observability/grafana/dashboards" to
"/etc/grafana/provisioning/dashboards/files": create mountpoint ...
read-only file system`. The `grafana` service mounted
`./observability/grafana/provisioning` read-only at
`/etc/grafana/provisioning`, and separately mounted
`./observability/grafana/dashboards` at
`/etc/grafana/provisioning/dashboards/files` — a path *nested inside*
the first, already read-only, mount. Docker has to create that nested
path as a mountpoint before attaching the second bind mount, and can't
do that inside a filesystem it already mounted read-only.

Fixed by moving the dashboards mount to a sibling path,
`/etc/grafana/dashboards` (not nested under `/etc/grafana/provisioning`),
and updating `observability/grafana/provisioning/dashboards/provider.yml`'s
`path:` to match.

Two checks, both pure text inspection — the general one (no bind-mount
target anywhere in the file is nested inside another read-only bind
mount's target, for any service) and one specific to this bug (the
dashboard provider's `path:` matches its compose bind-mount target).
No PyYAML import (not a project dependency), so this actually executes
in this sandbox like this project's other dependency-free regression
tests.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"
_DASHBOARD_PROVIDER_FILE = (
    _REPO_ROOT / "observability" / "grafana" / "provisioning" / "dashboards" / "provider.yml"
)

# Matches a compose bind-mount volume line, e.g.:
#   - ./observability/grafana/provisioning:/etc/grafana/provisioning:ro
# Captures (host_path, container_path, options_or_None).
_BIND_MOUNT_RE = re.compile(
    r"^\s*-\s*(\.\/\S+?):(\/[^:\s]+)(?::(\S+))?\s*$",
)


def _parse_bind_mounts(compose_text: str) -> list[tuple[str, str, bool]]:
    """Returns (host_path, container_path, read_only) for every bind
    mount (host-path-prefixed `./...` source) in the whole compose file,
    across all services — a named-volume mount (no leading `./`) is
    excluded since it can't collide with a host bind mount this way."""

    mounts = []
    for line in compose_text.splitlines():
        match = _BIND_MOUNT_RE.match(line)
        if not match:
            continue
        host_path, container_path, options = match.groups()
        read_only = options == "ro"
        mounts.append((host_path, container_path, read_only))
    return mounts


def _is_nested_under(inner: str, outer: str) -> bool:
    """True if `inner` is a strict subdirectory of `outer` (both
    absolute container paths)."""

    outer_norm = outer.rstrip("/")
    return inner != outer_norm and inner.startswith(outer_norm + "/")


def test_no_bind_mount_target_is_nested_inside_a_read_only_bind_mount():
    compose_text = _COMPOSE_FILE.read_text(encoding="utf-8")
    mounts = _parse_bind_mounts(compose_text)
    assert mounts, "expected at least one bind mount in docker-compose.yml"

    read_only_targets = [target for _, target, ro in mounts if ro]
    for _, target, _ro in mounts:
        for ro_target in read_only_targets:
            if target == ro_target:
                continue
            assert not _is_nested_under(target, ro_target), (
                f"bind mount target {target!r} is nested inside read-only bind mount "
                f"target {ro_target!r} — Docker cannot create a mountpoint inside an "
                f"already-mounted read-only filesystem (this is the exact Grafana bug: "
                f"'error mounting ... create mountpoint ... read-only file system')"
            )


def test_grafana_dashboard_provider_path_matches_its_compose_mount():
    compose_text = _COMPOSE_FILE.read_text(encoding="utf-8")
    mounts = _parse_bind_mounts(compose_text)

    dashboards_mounts = [
        target for host, target, _ro in mounts if host == "./observability/grafana/dashboards"
    ]
    assert len(dashboards_mounts) == 1, (
        f"expected exactly one bind mount for ./observability/grafana/dashboards, "
        f"found {dashboards_mounts}"
    )
    compose_target = dashboards_mounts[0]

    provider_text = _DASHBOARD_PROVIDER_FILE.read_text(encoding="utf-8")
    path_match = re.search(r"^\s*path:\s*(\S+)\s*$", provider_text, re.MULTILINE)
    assert path_match, "provider.yml has no `path:` line"
    provider_path = path_match.group(1)

    assert provider_path == compose_target, (
        f"provider.yml's dashboard path ({provider_path!r}) doesn't match the "
        f"docker-compose.yml bind-mount target ({compose_target!r}) — Grafana would "
        f"look for dashboard JSON files somewhere nothing is actually mounted"
    )
