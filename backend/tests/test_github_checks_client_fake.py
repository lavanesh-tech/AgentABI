"""Tests for `FakeGitHubChecksClient` / `failing_checks_client` (Phase 12
spec §9/§35/§41: "no real network in normal tests"). Exercises the same
request/response shapes `GitHubPullRequestAnalysisService` sends, without
any `httpx`/SQLAlchemy import — runs for real via `pytest --noconftest`.

The real `HttpxGitHubChecksClient` (in `app/github/checks_client.py`) is
written and `py_compile`-clean but cannot be exercised here: `httpx` is
not installable in this sandbox (same limitation documented for every
prior phase's network-dependent code). Its retry/timeout/auth-failure
branches are NOT covered by an executed test.
"""

import pytest

from app.domain.exceptions import GitHubAPIUnavailable
from app.github.check_mapping import CHECK_NAME, build_completed_output, decision_to_conclusion
from app.github.checks_fake import FakeGitHubChecksClient, failing_checks_client
from app.github.checks_models import CheckRunOutput, CheckRunRequest, CheckStatus
from app.risk.models import RiskDecision


def _request(
    *, head_sha="abc123", status=CheckStatus.COMPLETED, conclusion=None
) -> CheckRunRequest:
    return CheckRunRequest(
        repository_full_name="acme-corp/payments-service",
        head_sha=head_sha,
        name=CHECK_NAME,
        status=status,
        output=CheckRunOutput(title="t", summary="s"),
        conclusion=conclusion,
        external_id="analysis-1",
    )


@pytest.mark.asyncio
async def test_create_check_run_records_repository_sha_and_check_name():
    client = FakeGitHubChecksClient()
    result = await client.create_check_run(_request(head_sha="deadbeef"))

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call.operation == "create"
    assert call.repository_full_name == "acme-corp/payments-service"
    assert call.head_sha == "deadbeef"
    assert result.id == call.check_run_id


@pytest.mark.asyncio
async def test_update_check_run_targets_the_same_check_run_id():
    client = FakeGitHubChecksClient()
    created = await client.create_check_run(_request(head_sha="deadbeef"))
    updated = await client.update_check_run(
        repository_full_name="acme-corp/payments-service",
        check_run_id=created.id,
        request=_request(head_sha="deadbeef", conclusion=None),
    )
    assert updated.id == created.id
    assert client.calls[1].check_run_id == created.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision,expected_conclusion_value",
    [
        (RiskDecision.PASS, "success"),
        (RiskDecision.WARN, "neutral"),
        (RiskDecision.BLOCK, "failure"),
    ],
)
async def test_pass_warn_block_map_to_expected_conclusions_end_to_end(
    decision, expected_conclusion_value
):
    conclusion = decision_to_conclusion(decision)
    output = build_completed_output(
        decision=decision,
        score=50,
        risk_engine_version="1",
        hard_block=False,
        top_rules=[("SOME_RULE", 10)],
    )
    client = FakeGitHubChecksClient()
    request = CheckRunRequest(
        repository_full_name="acme-corp/payments-service",
        head_sha="abc123",
        name=CHECK_NAME,
        status=CheckStatus.COMPLETED,
        output=output,
        conclusion=conclusion,
    )
    result = await client.create_check_run(request)

    assert result.conclusion.value == expected_conclusion_value
    assert "SOME_RULE" in output.summary
    assert "50/100" in output.summary


@pytest.mark.asyncio
async def test_failing_checks_client_raises_sanitized_provider_error():
    client = failing_checks_client("simulated outage")
    with pytest.raises(GitHubAPIUnavailable):
        await client.create_check_run(_request())
    # No token/secret material anywhere in the recorded state or the call.
    assert client.calls == []


@pytest.mark.asyncio
async def test_fake_client_failure_clears_after_raising_once():
    client = failing_checks_client()
    with pytest.raises(GitHubAPIUnavailable):
        await client.create_check_run(_request())

    # The next call succeeds — a single simulated failure doesn't wedge
    # every subsequent call.
    result = await client.create_check_run(_request())
    assert result.id is not None
    assert len(client.calls) == 1
