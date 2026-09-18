"""`RiskService` integration tests (real Postgres via the `session`
fixture, spec §37). Written and `py_compile`-clean; needs SQLAlchemy/
asyncpg, unavailable in this sandbox — see docs/DECISIONS.md.
"""

import uuid

import pytest

from app.compatibility.models import Classification, Severity
from app.domain.exceptions import (
    CompatibilityScanNotFound,
    DifferentialReportNotFound,
    RiskAssessmentInputRequired,
    RiskAssessmentNotFound,
)
from app.models import CompatibilityScan, Component, Organization, Project, ScanChange
from app.services.risk_service import RiskService


async def _setup(session, org_slug="acme", project_slug="payments"):
    org = Organization(name=org_slug.title(), slug=org_slug)
    session.add(org)
    await session.flush()
    project = Project(organization_id=org.id, name=project_slug.title(), slug=project_slug)
    session.add(project)
    await session.flush()
    component = Component(
        organization_id=org.id,
        project_id=project.id,
        component_type="tool",
        slug="authorize-payment-tool",
        name="AuthorizePaymentTool",
    )
    session.add(component)
    await session.flush()
    return org, project, component


async def _scan(session, org, project, component, *, status, changes=()):
    from app.models import ComponentVersion

    v1 = ComponentVersion(component_id=component.id, version="1", content={}, checksum="a" * 64)
    v2 = ComponentVersion(component_id=component.id, version="2", content={}, checksum="b" * 64)
    session.add_all([v1, v2])
    await session.flush()

    scan = CompatibilityScan(
        project_id=project.id,
        component_id=component.id,
        baseline_version_id=v1.id,
        candidate_version_id=v2.id,
        status=status,
        total_changes=len(changes),
        compatible_count=0,
        potentially_breaking_count=0,
        breaking_count=sum(1 for c in changes if c.get("classification") == "breaking"),
        severity_info_count=0,
        severity_low_count=0,
        severity_medium_count=0,
        severity_high_count=0,
        severity_critical_count=sum(1 for c in changes if c.get("severity") == "critical"),
    )
    session.add(scan)
    await session.flush()
    for index, change in enumerate(changes):
        session.add(
            ScanChange(
                scan_id=scan.id,
                order_index=index,
                change_type=change.get("change_type", "field_removed"),
                path=change.get("path", "$.field"),
                classification=Classification(change.get("classification", "breaking")),
                severity=Severity(change.get("severity", "high")),
                message=change.get("message", "field removed"),
            )
        )
    await session.flush()
    await session.commit()
    await session.refresh(scan, attribute_names=["changes"])
    return scan


async def test_no_evidence_scan_yields_pass(session):
    org, project, component = await _setup(session)
    scan = await _scan(session, org, project, component, status="compatible")

    service = RiskService(session)
    record = await service.run_assessment(project.id, compatibility_scan_id=scan.id)

    assert record.decision == "PASS"
    assert record.score == 0
    assert record.hard_block is False


async def test_critical_change_hard_blocks(session):
    org, project, component = await _setup(session)
    scan = await _scan(
        session,
        org,
        project,
        component,
        status="breaking",
        changes=[{"classification": "breaking", "severity": "critical"}],
    )

    service = RiskService(session)
    record = await service.run_assessment(project.id, compatibility_scan_id=scan.id)

    assert record.hard_block is True
    assert record.decision == "BLOCK"


async def test_no_input_rejected(session):
    org, project, component = await _setup(session)
    service = RiskService(session)
    with pytest.raises(RiskAssessmentInputRequired):
        await service.run_assessment(project.id)


async def test_cross_project_scan_id_rejected(session):
    org, project, component = await _setup(session)
    scan = await _scan(session, org, project, component, status="compatible")
    other_project_id = uuid.uuid4()

    service = RiskService(session)
    with pytest.raises(CompatibilityScanNotFound):
        await service.run_assessment(other_project_id, compatibility_scan_id=scan.id)


async def test_missing_differential_report_rejected(session):
    org, project, component = await _setup(session)
    service = RiskService(session)
    with pytest.raises(DifferentialReportNotFound):
        await service.run_assessment(project.id, differential_report_id=uuid.uuid4())


async def test_idempotent_retry_returns_same_assessment(session):
    org, project, component = await _setup(session)
    scan = await _scan(session, org, project, component, status="compatible")

    service = RiskService(session)
    first = await service.run_assessment(project.id, compatibility_scan_id=scan.id)
    second = await service.run_assessment(project.id, compatibility_scan_id=scan.id)
    assert first.id == second.id


async def test_get_assessment_not_found_raises(session):
    org, project, component = await _setup(session)
    service = RiskService(session)
    with pytest.raises(RiskAssessmentNotFound):
        await service.get_assessment(project.id, uuid.uuid4())


async def test_deterministic_evidence_unchanged_after_assessment(session):
    org, project, component = await _setup(session)
    scan = await _scan(
        session,
        org,
        project,
        component,
        status="breaking",
        changes=[{"classification": "breaking", "severity": "high"}],
    )
    service = RiskService(session)

    before = (scan.status, scan.breaking_count, [c.severity for c in scan.changes])
    await service.run_assessment(project.id, compatibility_scan_id=scan.id)
    after = (scan.status, scan.breaking_count, [c.severity for c in scan.changes])
    assert before == after
