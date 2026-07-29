from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5


RULE_ID = "withdrawal-pending-count"
RULE_VERSION = "1.0.0"


def detect_withdrawal_slowdown(
    operations: dict,
    *,
    warning_threshold: int,
    critical_threshold: int,
) -> dict:
    """Build a deterministic incident assessment from aggregate evidence."""
    data = operations.get("data", {})
    meta = operations.get("meta", {})
    pending = int(data.get("pending_withdrawals", 0))
    withdrawals = int(data.get("withdrawals", 0))
    generated_at = meta.get("generated_at") or datetime.now(UTC).isoformat()
    request_id = str(meta.get("request_id", "unknown"))

    if pending >= critical_threshold:
        severity, state = "critical", "open"
    elif pending >= warning_threshold:
        severity, state = "warning", "open"
    elif pending:
        severity, state = "notice", "observing"
    else:
        severity, state = "healthy", "clear"

    incident_id = str(
        uuid5(NAMESPACE_URL, f"bitagent:{RULE_ID}:{request_id}:{generated_at}")
    )
    ratio = round((pending / withdrawals) * 100, 2) if withdrawals else None
    return {
        "incident_id": incident_id,
        "rule": {"id": RULE_ID, "version": RULE_VERSION},
        "title": "Withdrawal backlog signal",
        "severity": severity,
        "state": state,
        "observed": {"pending_count": pending, "pending_ratio_percent": ratio},
        "thresholds": {
            "warning_pending_count": warning_threshold,
            "critical_pending_count": critical_threshold,
        },
        "evidence": [
            {
                "source": "GET /api/bot/operations",
                "request_id": request_id,
                "generated_at": generated_at,
                "data_freshness_seconds": meta.get("data_freshness_seconds"),
            }
        ],
        "timeline": [
            {
                "at": generated_at,
                "event": "Aggregate withdrawal evidence observed",
            },
            {
                "at": datetime.now(UTC).isoformat(),
                "event": f"Rule {RULE_ID}@{RULE_VERSION} evaluated as {severity}",
            },
        ],
        "confidence": "limited",
        "limitations": [
            "Pending age distribution is unavailable.",
            "Queue depth, worker health and network status are unavailable.",
            "The aggregate count alone cannot establish root cause.",
        ],
        "recommended_investigation": (
            "Review pending withdrawals by asset/network and check wallet, queue, "
            "worker and node health in approved operational systems."
        ),
        "action_executed": False,
    }
