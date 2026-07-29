from app.evidence import evidence_trends, latest_evidence_payload


REPORT_VERSION = "1.0.0"
RUNBOOK_PATH = "docs/runbooks/master-runbook.md"


def withdrawal_investigation(
    path: str,
    *,
    trend_limit: int,
    freshness_warning_seconds: int,
) -> dict:
    latest = latest_evidence_payload(path)
    if not latest:
        return {
            "status": "insufficient_evidence",
            "report_version": REPORT_VERSION,
            "conclusion": "No retained exchange evidence is available yet.",
            "confidence": "insufficient",
            "action_executed": False,
        }

    payload = latest["payload"]
    incident = payload["incident"]
    operations = payload["operations"]
    trend = evidence_trends(path, trend_limit, freshness_warning_seconds)
    pending = incident["observed"]["pending_count"]
    delta = trend.get("deltas", {}).get("pending_withdrawals")
    delta_text = (
        f" The retained-window change is {delta:+d}."
        if delta is not None and trend["status"] == "ready"
        else " Historical direction is not yet established."
    )
    conclusion = (
        f"{incident['severity'].capitalize()} withdrawal backlog signal: "
        f"{pending} withdrawals are pending.{delta_text} "
        "The available evidence does not establish a root cause."
    )

    return {
        "status": "ready",
        "report_version": REPORT_VERSION,
        "incident_id": incident["incident_id"],
        "severity": incident["severity"],
        "conclusion": conclusion,
        "supporting_evidence": {
            "latest_record_id": latest["id"],
            "latest_record_hash": latest["record_hash"],
            "pending_withdrawals": pending,
            "pending_change": delta,
            "source": "GET /api/bot/operations",
            "source_timestamp": operations.get("meta", {}).get("generated_at"),
            "freshness_seconds": operations.get("meta", {}).get(
                "data_freshness_seconds"
            ),
            "rule": incident["rule"],
        },
        "timeline": incident["timeline"],
        "confidence": incident["confidence"],
        "limitations": incident["limitations"] + trend.get("limitations", []),
        "recommended_investigation": incident["recommended_investigation"],
        "runbook": {
            "path": RUNBOOK_PATH,
            "section": "19. Incident runbook: deposit/withdrawal slowdown",
            "triage_steps": [
                "Confirm the alert uses fresh data.",
                "Group affected transactions by asset, network, status and age band.",
                "Check queue depth, workers, wallet service, node and network status.",
                "Escalate to the named owner according to severity.",
            ],
        },
        "missing_sources": [
            "/api/bot/withdrawals/pending",
            "/api/bot/networks/status",
            "/api/bot/queues/status",
            "/api/bot/workers/status",
        ],
        "statement": "No action executed by bitAgent.",
        "action_executed": False,
    }
