from datetime import UTC, datetime

from app.evidence import evidence_trends, latest_evidence_payload, verify_chain
from app.investigations import withdrawal_investigation


BRIEF_VERSION = "1.0.0"


def daily_executive_brief(
    path: str,
    *,
    trend_limit: int,
    freshness_warning_seconds: int,
) -> dict:
    latest = latest_evidence_payload(path)
    if not latest:
        return {
            "status": "insufficient_evidence",
            "brief_version": BRIEF_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "action_executed": False,
        }

    report = withdrawal_investigation(
        path,
        trend_limit=trend_limit,
        freshness_warning_seconds=freshness_warning_seconds,
    )
    trend = evidence_trends(path, trend_limit, freshness_warning_seconds)
    audit = verify_chain(path)
    payload = latest["payload"]
    risk = payload["market_risk"]
    priorities = []
    if report["severity"] in {"warning", "critical"}:
        priorities.append(
            {
                "severity": report["severity"],
                "title": "Review withdrawal backlog",
                "reason": report["conclusion"],
            }
        )
    priorities.extend(
        {
            "severity": alert["severity"],
            "title": "Resolve evidence freshness warning",
            "reason": alert["code"],
        }
        for alert in trend.get("alerts", [])
    )
    if risk["severity"] == "unknown":
        priorities.append(
            {
                "severity": "notice",
                "title": "Market OHLC evidence is insufficient",
                "reason": ", ".join(
                    risk["data_quality"]["missing_or_invalid_fields"]
                ),
            }
        )

    return {
        "status": "ready",
        "brief_version": BRIEF_VERSION,
        "brief_id": f"daily-{latest['id']}-{latest['record_hash'][:12]}",
        "generated_at": datetime.now(UTC).isoformat(),
        "headline": report["conclusion"],
        "overall_severity": report["severity"],
        "priorities": priorities,
        "operations": {
            "pending_withdrawals": report["supporting_evidence"][
                "pending_withdrawals"
            ],
            "pending_change": report["supporting_evidence"]["pending_change"],
            "freshness_seconds": report["supporting_evidence"][
                "freshness_seconds"
            ],
        },
        "market": {
            "symbol": risk["market"],
            "risk_severity": risk["severity"],
            "range_percent": risk["metrics"]["range_percent"],
            "confidence": risk["confidence"],
        },
        "evidence": {
            "record_id": latest["id"],
            "record_hash": latest["record_hash"],
            "audit_chain_valid": audit["valid"],
            "sources": [
                "GET /api/bot/operations",
                "GET /api/bot/market/{market}/summary",
            ],
        },
        "limitations": report["limitations"] + risk["limitations"],
        "recommended_investigation": report["recommended_investigation"],
        "statement": "No action executed by bitAgent.",
        "action_executed": False,
    }
