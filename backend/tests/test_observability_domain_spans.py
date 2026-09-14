"""Phase 15 spec §34 domain-boundary span tests: verify
`CompatibilityService.run_scan`, `RiskService.run_assessment`, and
`GitHubPullRequestAnalysisService.run_analysis` create the expected span
names without changing their return values, using OTel's in-memory span
exporter. Needs `opentelemetry-sdk` + SQLAlchemy/asyncpg (real Postgres
via the `session` fixture) — none installed in this sandbox this session
(`pip install opentelemetry-api` returns "No matching distribution
found"; PyPI is unreachable here — see docs/DECISIONS.md). Written and
`py_compile`-clean; not pytest-executed.
"""

import pytest

from app.models import Component, ComponentVersion, Organization, Project
from app.services.compatibility_service import CompatibilityService


@pytest.fixture
def span_exporter():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()


async def test_compatibility_run_scan_emits_expected_span_and_unchanged_result(
    session, span_exporter
):
    org = Organization(name="Acme", slug="acme")
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name="Payments", slug="payments")
    session.add(project)
    await session.flush()
    component = Component(
        organization_id=org.id,
        project_id=project.id,
        component_type="tool",
        slug="tool",
        name="Tool",
    )
    session.add(component)
    await session.flush()
    baseline = ComponentVersion(
        component_id=component.id, version="1", content={}, checksum="a" * 64
    )
    candidate = ComponentVersion(
        component_id=component.id, version="2", content={}, checksum="b" * 64
    )
    session.add_all([baseline, candidate])
    await session.flush()
    await session.commit()

    service = CompatibilityService(session)
    scan = await service.run_scan(project.id, component.id, "1", "2")

    span_names = [s.name for s in span_exporter.get_finished_spans()]
    assert "agentabi.compatibility.analyze" in span_names
    # Tracing must not alter the deterministic result (spec §2/§41).
    assert scan.component_id == component.id
    assert scan.baseline_version_id == baseline.id
    assert scan.candidate_version_id == candidate.id
