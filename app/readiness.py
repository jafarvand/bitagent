from datetime import UTC, datetime
import json
from pathlib import Path

from app.incidents import detect_withdrawal_slowdown
from app.policy import PROHIBITED_CAPABILITIES, evaluate_policy


REPLAY_FIXTURES = (
    ("healthy-empty", 0, 120, "healthy"),
    ("notice-small", 8, 120, "notice"),
    ("warning-boundary", 25, 120, "warning"),
    ("warning-backlog", 42, 205, "warning"),
    ("critical-boundary", 100, 205, "critical"),
    ("critical-surge", 240, 300, "critical"),
)


def historical_replay(warning_threshold: int, critical_threshold: int) -> dict:
    """Replay sanitized golden cases through the production incident rule."""
    cases = []
    for name, pending, withdrawals, expected in REPLAY_FIXTURES:
        operations = {
            "data": {
                "pending_withdrawals": pending,
                "withdrawals": withdrawals,
            },
            "meta": {
                "request_id": f"replay-{name}",
                "generated_at": "2026-07-29T00:00:00+00:00",
                "data_freshness_seconds": 0,
            },
        }
        result = detect_withdrawal_slowdown(
            operations,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
        )
        cases.append(
            {
                "fixture": name,
                "expected": expected,
                "actual": result["severity"],
                "passed": result["severity"] == expected,
                "action_executed": result["action_executed"],
            }
        )
    passed = sum(case["passed"] for case in cases)
    return {
        "suite": "withdrawal-pending-golden-cases",
        "fixture_classification": "sanitized_synthetic",
        "cases": cases,
        "passed": passed,
        "total": len(cases),
        "accuracy_percent": round(passed / len(cases) * 100, 2),
        "all_passed": passed == len(cases),
        "limitations": [
            "These are synthetic golden cases, not owner-supplied historical incidents.",
            "Aggregate counts cannot validate age, queue, worker, network, or root cause analysis.",
        ],
    }


def security_self_test(audit_verification: dict) -> dict:
    refusal_results = [
        evaluate_policy("admin", capability, enforced=True)
        for capability in sorted(PROHIBITED_CAPABILITIES)
    ]
    refused = sum(not result["allowed"] for result in refusal_results)
    checks = [
        {
            "id": "prohibited-action-refusal",
            "passed": refused == len(refusal_results),
            "evidence": f"{refused}/{len(refusal_results)} prohibited capabilities denied",
        },
        {
            "id": "no-action-execution",
            "passed": all(not result["action_executed"] for result in refusal_results),
            "evidence": "Every policy result records action_executed=false",
        },
        {
            "id": "evidence-chain-integrity",
            "passed": bool(audit_verification.get("valid")),
            "evidence": f"{audit_verification.get('records', 0)} evidence records verified",
        },
    ]
    return {
        "suite": "local-security-self-test",
        "checks": checks,
        "passed": sum(check["passed"] for check in checks),
        "total": len(checks),
        "all_passed": all(check["passed"] for check in checks),
        "refusal_percent": round(refused / len(refusal_results) * 100, 2),
        "limitations": [
            "Upstream replay, expired timestamp, wrong IP, wrong scope, rotation, and revocation require server-side staging tests.",
            "Pilot role headers are not production identity proof; SSO/JWT and MFA remain required.",
        ],
    }


def load_upstream_security_report(path: str) -> dict | None:
    report_path = Path(path)
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    required = {"generated_at", "checks", "all_passed", "contains_credentials"}
    if not required.issubset(report) or report["contains_credentials"] is not False:
        return None
    return report


def uat_readiness(
    replay: dict,
    security: dict,
    *,
    live_mode: bool,
    upstream_security: dict | None = None,
    release_inputs: dict | None = None,
) -> dict:
    upstream_passed = bool(upstream_security and upstream_security.get("all_passed"))
    release_inputs = release_inputs or {}
    owner_incidents = release_inputs.get("owner_incidents", {})
    external_security = release_inputs.get("external_security", {})
    identity = release_inputs.get("production_identity", {})
    approval = release_inputs.get("uat_approval", {})
    gates = [
        {"id": "automated-replay", "status": "pass" if replay["all_passed"] else "fail", "evidence": f"{replay['passed']}/{replay['total']} sanitized cases"},
        {"id": "local-security", "status": "pass" if security["all_passed"] else "fail", "evidence": f"{security['passed']}/{security['total']} local checks"},
        {"id": "prohibited-action-refusal", "status": "pass" if security["refusal_percent"] == 100 else "fail", "evidence": f"{security['refusal_percent']}% refused"},
        {"id": "live-read-smoke", "status": "pass" if live_mode else "pending", "evidence": "live mode configured" if live_mode else "run against staging read-only credentials"},
        {
            "id": "owner-historical-incidents",
            "status": "pass" if owner_incidents.get("passed") else "pending",
            "evidence": f"{len(owner_incidents.get('cases', []))} owner-approved incidents replayed" if owner_incidents.get("passed") else "5-20 owner-approved incidents required",
        },
        {
            "id": "upstream-negative-security",
            "status": "pass" if upstream_passed and external_security.get("passed") else ("partial" if upstream_passed else "pending"),
            "evidence": (
                f"{upstream_security['passed']}/{upstream_security['total']} safe probes plus owner security evidence"
                if upstream_passed and external_security.get("passed")
                else f"{upstream_security['passed']}/{upstream_security['total']} safe authentication probes passed; IP/scope/rotation/revocation remain"
                if upstream_passed
                else "replay/timestamp/tamper/IP/scope/rotation/revocation evidence required"
            ),
        },
        {"id": "production-identity", "status": "pass" if identity.get("passed") else "pending", "evidence": "validated owner identity evidence" if identity.get("passed") else "SSO/JWT, MFA and access review required"},
        {"id": "owner-uat-approval", "status": "pass" if approval.get("passed") else "pending", "evidence": "operations and risk approvals validated" if approval.get("passed") else "operations and risk owner sign-off required"},
    ]
    passed = sum(gate["status"] == "pass" for gate in gates)
    return {
        "report": "0.9 pilot readiness",
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "ready_for_controlled_uat" if passed == len(gates) else "not_ready_for_1_0_pilot",
        "passed": passed,
        "total": len(gates),
        "gates": gates,
        "action_executed": False,
    }
