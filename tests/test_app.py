import hashlib
import hmac
import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.exchange import ExchangeClient
from app.evidence import record_dashboard
from app.main import app
from app.market_risk import analyze_market_range


client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_mode(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "bitagent_mode", "mock")
    monkeypatch.setattr(settings, "evidence_db_path", str(tmp_path / "evidence.db"))
    monkeypatch.setattr(
        settings,
        "upstream_security_report_path",
        str(tmp_path / "upstream-security-report.json"),
    )
    monkeypatch.setattr(settings, "bitagent_access_control_mode", "observe")


def test_health_is_read_only_version_zero_line():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == "0.9.1"


def test_dashboard_mock_contract():
    response = client.get("/api/v0/dashboard?market=BTC_USDT&days=30")
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "mock"
    assert body["operations"]["data"]["pending_withdrawals"] == 42
    assert body["market"]["data"]["market"] == "BTC_USDT"
    incident = body["incident"]
    assert incident["severity"] == "warning"
    assert incident["observed"]["pending_count"] == 42
    assert incident["rule"] == {
        "id": "withdrawal-pending-count",
        "version": "1.0.0",
    }
    assert incident["action_executed"] is False
    assert incident["confidence"] == "limited"
    market_risk = body["market_risk"]
    assert market_risk["severity"] == "healthy"
    assert market_risk["metrics"]["range_percent"] == "2.74"
    assert market_risk["metrics"]["last_position_percent"] == "60.86"
    assert market_risk["action_executed"] is False
    assert market_risk["data_quality"] == {
        "valid": True,
        "missing_or_invalid_fields": [],
    }
    assert body["evidence_record"]["id"] == 1


def test_evidence_ledger_is_append_only_and_verifiable():
    client.get("/api/v0/dashboard?market=BTC_USDT&days=30")
    client.get("/api/v0/dashboard?market=BTC_USDT&days=7")

    recent = client.get("/api/v0/evidence/recent?limit=10").json()
    verification = client.get("/api/v0/audit/verify").json()

    assert [item["id"] for item in recent["items"]] == [2, 1]
    assert all("payload_json" not in item for item in recent["items"])
    assert verification["valid"] is True
    assert verification["records"] == 2


def test_historical_trends_compare_retained_evidence():
    first = client.get("/api/v0/dashboard?market=BTC_USDT&days=30").json()
    changed = deepcopy(first)
    changed.pop("evidence_record")
    changed["operations"]["data"]["pending_withdrawals"] = 50
    changed["operations"]["data"]["orders"] = 271
    changed["market"]["data"]["last"] = "64475.21850000"
    record_dashboard(settings.evidence_db_path, changed)

    trend = client.get("/api/v0/trends?limit=30").json()

    assert trend["status"] == "ready"
    assert trend["records"] == 2
    assert trend["deltas"]["pending_withdrawals"] == 8
    assert trend["deltas"]["orders"] == 10
    assert trend["market"]["last_price_change_percent"] == "1.00"
    assert trend["action_executed"] is False


def test_investigation_brief_fulfills_runbook_response_contract():
    client.get("/api/v0/dashboard?market=BTC_USDT&days=30")

    report = client.get("/api/v0/investigations/withdrawal-slowdown").json()

    assert report["status"] == "ready"
    assert report["severity"] == "warning"
    assert "42 withdrawals are pending" in report["conclusion"]
    assert report["supporting_evidence"]["source"] == "GET /api/bot/operations"
    assert report["supporting_evidence"]["source_timestamp"]
    assert report["supporting_evidence"]["rule"]["version"] == "1.0.0"
    assert report["confidence"] == "limited"
    assert report["limitations"]
    assert report["runbook"]["path"] == "docs/runbooks/master-runbook.md"
    assert report["runbook"]["section"].startswith("19.")
    assert report["statement"] == "No action executed by bitAgent."
    assert report["action_executed"] is False


def test_daily_brief_is_deterministic_and_evidence_backed():
    client.get("/api/v0/dashboard?market=BTC_USDT&days=30")

    brief = client.get("/api/v0/briefs/daily").json()

    assert brief["status"] == "ready"
    assert brief["brief_version"] == "1.0.0"
    assert "42 withdrawals are pending" in brief["headline"]
    assert brief["priorities"]
    assert brief["evidence"]["audit_chain_valid"] is True
    assert brief["evidence"]["sources"]
    assert brief["limitations"]
    assert brief["statement"] == "No action executed by bitAgent."
    assert brief["action_executed"] is False


def test_feedback_is_local_append_only_and_never_writes_exchange():
    response = client.post(
        "/api/v0/feedback",
        json={
            "report_id": "daily-1-test",
            "rating": "needs_correction",
            "comment": "Threshold needs owner review.",
        },
    )
    summary = client.get("/api/v0/feedback/summary").json()

    assert response.status_code == 201
    body = response.json()
    assert body["feedback"]["local_only"] is True
    assert body["exchange_write_performed"] is False
    assert "Threshold needs owner review." not in str(body)
    assert summary == {
        "version": "0.9.1",
        "total": 1,
        "counts": {"needs_correction": 1},
    }


def test_prohibited_actions_are_refused_even_for_admin():
    response = client.post(
        "/api/v0/policy/evaluate",
        headers={"X-BitAgent-Role": "admin"},
        json={"capability": "transfer_funds"},
    )

    assert response.status_code == 200
    decision = response.json()["decision"]
    assert decision["allowed"] is False
    assert decision["reason"] == "prohibited_by_read_only_boundary"
    assert decision["action_executed"] is False
    assert decision["audit"]["decision_hash"]


def test_enforced_rbac_denies_anonymous_and_allows_viewer(monkeypatch):
    monkeypatch.setattr(settings, "bitagent_access_control_mode", "enforced")

    denied = client.get("/api/v0/dashboard?market=BTC_USDT&days=30")
    allowed = client.get(
        "/api/v0/dashboard?market=BTC_USDT&days=30",
        headers={"X-BitAgent-Role": "viewer"},
    )

    assert denied.status_code == 403
    assert denied.json()["detail"]["reason"] == "role_capability_denied"
    assert allowed.status_code == 200


def test_access_decisions_are_audited(monkeypatch):
    monkeypatch.setattr(settings, "bitagent_access_control_mode", "enforced")
    client.get("/api/v0/dashboard?market=BTC_USDT&days=30")

    audit = client.get(
        "/api/v0/audit/access/recent",
        headers={"X-BitAgent-Role": "auditor"},
    ).json()

    assert len(audit["items"]) >= 2
    assert any(item["allowed"] is False for item in audit["items"])
    assert all(item["decision_hash"] for item in audit["items"])


def test_replay_suite_validates_six_severity_cases():
    replay = client.get(
        "/api/v0/evaluations/replay",
        headers={"X-BitAgent-Role": "auditor"},
    ).json()

    assert replay["total"] == 6
    assert replay["passed"] == 6
    assert replay["accuracy_percent"] == 100
    assert replay["all_passed"] is True
    assert all(case["action_executed"] is False for case in replay["cases"])
    assert replay["fixture_classification"] == "sanitized_synthetic"


def test_readiness_report_is_evidence_based_and_not_false_go_live():
    report = client.get(
        "/api/v0/readiness",
        headers={"X-BitAgent-Role": "auditor"},
    ).json()

    assert report["version"] == "0.9.1"
    assert report["security"]["all_passed"] is True
    assert report["security"]["refusal_percent"] == 100
    assert report["uat"]["decision"] == "not_ready_for_1_0_pilot"
    gates = {gate["id"]: gate for gate in report["uat"]["gates"]}
    assert gates["automated-replay"]["status"] == "pass"
    assert gates["owner-historical-incidents"]["status"] == "pending"
    assert gates["upstream-negative-security"]["status"] == "pending"
    assert report["uat"]["action_executed"] is False


def test_readiness_loads_credential_free_upstream_probe():
    probe = {
        "generated_at": "2026-07-29T00:00:00+00:00",
        "checks": [{"id": "request-id-replay", "passed": True}],
        "passed": 4,
        "total": 4,
        "all_passed": True,
        "contains_credentials": False,
    }
    with open(settings.upstream_security_report_path, "w", encoding="utf-8") as stream:
        json.dump(probe, stream)

    report = client.get(
        "/api/v0/readiness",
        headers={"X-BitAgent-Role": "auditor"},
    ).json()
    gates = {gate["id"]: gate for gate in report["uat"]["gates"]}

    assert report["upstream_security"]["contains_credentials"] is False
    assert gates["upstream-negative-security"]["status"] == "partial"
    assert "IP/scope/rotation/revocation remain" in gates[
        "upstream-negative-security"
    ]["evidence"]


def test_feature_gaps_are_explicit():
    response = client.get("/api/v0/features")
    assert response.status_code == 200
    body = response.json()
    assert body["counts"]["available"] >= 6
    assert body["counts"]["missing"] >= 1
    assert any(item["id"] == "auth-v02" for item in body["items"])


def test_invalid_market_is_rejected():
    response = client.get("/api/v0/dashboard?market=bad-market")
    assert response.status_code == 422


def test_market_risk_fails_closed_for_zero_ohlc():
    result = analyze_market_range(
        {"data": {"market": "BTC_USDT", "low": "0", "high": "0", "last": "1"}},
        warning_percent=settings.market_range_warning_percent,
        critical_percent=settings.market_range_critical_percent,
    )

    assert result["severity"] == "unknown"
    assert result["confidence"] == "insufficient"
    assert result["data_quality"]["missing_or_invalid_fields"] == ["low", "high"]


def test_v02_signature_covers_sorted_query_and_empty_body_hash(monkeypatch):
    monkeypatch.setattr(settings, "exchange_bot_key_id", "pilot-key")
    monkeypatch.setattr(settings, "exchange_bot_secret", "test-secret")
    exchange = ExchangeClient()
    query = exchange._query_string(
        {"z": "last value", "asset": ["USDT", "BTC"]}
    )

    headers = exchange._headers(
        "get",
        "/api/bot/transactions/../operations",
        query,
        timestamp="1785350000",
        request_id="AAAAAAAA-BBBB-4CCC-8DDD-EEEEEEEEEEEE",
    )

    assert query == "asset=USDT&asset=BTC&z=last%20value"
    canonical = "\n".join(
        [
            "GET",
            "/api/bot/operations",
            query,
            "1785350000",
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
            hashlib.sha256(b"").hexdigest(),
        ]
    )
    expected = hmac.new(
        b"test-secret", canonical.encode(), hashlib.sha256
    ).hexdigest()
    assert headers["X-Bot-Key-ID"] == "pilot-key"
    assert "X-Exchange-Bot-Authorization" not in headers
    assert headers["X-Request-Signature"] == expected


def test_status_reports_v02_credentials_without_exposing_values(monkeypatch):
    monkeypatch.setattr(settings, "exchange_bot_key_id", "pilot-key")
    monkeypatch.setattr(settings, "exchange_bot_secret", "test-secret")

    body = client.get("/api/v0/status").json()

    assert body["key_id_configured"] is True
    assert body["secret_configured"] is True
    assert "pilot-key" not in str(body)
    assert "test-secret" not in str(body)


def test_combined_service_keys_are_supported(monkeypatch):
    monkeypatch.setattr(settings, "exchange_bot_key_id", "")
    monkeypatch.setattr(settings, "exchange_bot_secret", "")
    monkeypatch.setattr(
        settings,
        "exchange_bot_service_keys",
        "pilot-key:test-secret,rotation-key:rotation-secret",
    )

    assert settings.exchange_credentials() == ("pilot-key", "test-secret")
    body = client.get("/api/v0/status").json()
    assert body["key_id_configured"] is True
    assert body["secret_configured"] is True
    assert "test-secret" not in str(body)
