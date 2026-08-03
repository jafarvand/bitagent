from __future__ import annotations

from collections import Counter
from typing import Literal

Coverage = Literal["supported", "partial", "blocked"]

MANAGEMENT_QUESTIONS = [
    {"id": 1, "domain": "executive", "question": "Give me a concise executive summary of the exchange's current status.", "coverage": "supported", "use_cases": ["daily-executive-brief", "exchange-health", "priority-summary"], "agents": ["executive", "operations", "market-risk", "treasury", "security"], "missing_sources": []},
    {"id": 2, "domain": "executive", "question": "What are the three most important risks requiring management attention today?", "coverage": "supported", "use_cases": ["cross-domain-prioritization", "risk-limit-breach", "incident-priority"], "agents": ["executive", "operations", "market-risk", "treasury", "security", "aml-fraud"], "missing_sources": []},
    {"id": 3, "domain": "business", "question": "How did revenue, trading volume, active users, and fees change compared with yesterday and last week?", "coverage": "supported", "use_cases": ["business-performance", "period-comparison", "daily-executive-brief"], "agents": ["executive", "marketing"], "missing_sources": []},
    {"id": 4, "domain": "business", "question": "Which products, markets, or customer segments generated the most revenue and growth?", "coverage": "partial", "use_cases": ["segment-performance", "market-revenue", "product-growth"], "agents": ["executive", "marketing"], "missing_sources": ["customer-segment profitability view", "product revenue attribution"]},
    {"id": 5, "domain": "operations", "question": "Which services currently have abnormal latency, errors, or resource usage?", "coverage": "supported", "use_cases": ["service-health", "operations-anomaly", "capacity-report"], "agents": ["operations"], "missing_sources": []},
    {"id": 6, "domain": "operations", "question": "Why are deposits or withdrawals for a specific asset delayed?", "coverage": "partial", "use_cases": ["transaction-delay-investigation", "withdrawal-slowdown", "node-health"], "agents": ["operations", "treasury", "support"], "missing_sources": ["/api/bot/queues/status", "/api/bot/workers/status", "/api/bot/networks/status"]},
    {"id": 7, "domain": "operations", "question": "What incidents occurred during the last 24 hours, and what caused them?", "coverage": "partial", "use_cases": ["incident-summary", "root-cause-hypothesis", "deployment-correlation"], "agents": ["operations"], "missing_sources": ["/api/bot/services/dependencies", "/api/bot/queues/status", "/api/bot/workers/status", "/api/bot/networks/status"]},
    {"id": 8, "domain": "operations", "question": "Which infrastructure problems are most likely to affect customers in the next few hours?", "coverage": "partial", "use_cases": ["predictive-infrastructure-risk", "capacity-forecast"], "agents": ["operations"], "missing_sources": ["historical infrastructure metrics", "capacity forecast inputs"]},
    {"id": 9, "domain": "market-risk", "question": "What is our current net exposure for each asset, and which exposures exceed approved limits?", "coverage": "supported", "use_cases": ["asset-exposure", "risk-limit-breach", "daily-risk-report"], "agents": ["market-risk"], "missing_sources": []},
    {"id": 10, "domain": "market-risk", "question": "How did the market maker perform during the last 24 hours in terms of profit, spread, volume, and inventory risk?", "coverage": "partial", "use_cases": ["market-maker-performance", "inventory-risk", "spread-analysis"], "agents": ["market-risk", "executive"], "missing_sources": ["order-book depth", "market-maker PnL attribution"]},
    {"id": 11, "domain": "market-risk", "question": "Which markets currently have insufficient liquidity, excessive spread, or abnormal slippage?", "coverage": "partial", "use_cases": ["market-quality", "liquidity-risk", "slippage-anomaly"], "agents": ["market-risk"], "missing_sources": ["order-book depth API"]},
    {"id": 12, "domain": "market-risk", "question": "What would happen to our exposure and liquidity if BTC or another major asset moved by 10%?", "coverage": "partial", "use_cases": ["market-stress-testing", "liquidity-stress", "scenario-analysis"], "agents": ["market-risk"], "missing_sources": ["deterministic scenario service", "current portfolio scenario inputs"]},
    {"id": 13, "domain": "treasury", "question": "Are hot-wallet balances sufficient for expected withdrawals during the next six hours?", "coverage": "partial", "use_cases": ["wallet-sufficiency", "withdrawal-demand-forecast"], "agents": ["treasury"], "missing_sources": ["network status", "withdrawal demand forecast inputs"]},
    {"id": 14, "domain": "treasury", "question": "Which assets require wallet rebalancing, and how much should be transferred?", "coverage": "partial", "use_cases": ["wallet-rebalancing-proposal", "treasury-approval"], "agents": ["treasury"], "missing_sources": ["network status", "approved wallet thresholds"]},
    {"id": 15, "domain": "treasury", "question": "Are there discrepancies between blockchain balances, wallet records, and the internal ledger?", "coverage": "supported", "use_cases": ["treasury-reconciliation", "financial-integrity-alert"], "agents": ["treasury", "market-risk", "operations"], "missing_sources": []},
    {"id": 16, "domain": "treasury", "question": "Which pending blockchain transactions are stuck, delayed, underfunded, or at risk of failure?", "coverage": "partial", "use_cases": ["pending-transaction-monitoring", "fee-analysis", "confirmation-monitoring"], "agents": ["treasury"], "missing_sources": ["/api/bot/networks/status", "transaction fee and nonce telemetry"]},
    {"id": 17, "domain": "aml-fraud", "question": "Which users or transactions currently have the highest AML or fraud risk, and why?", "coverage": "supported", "use_cases": ["aml-priority", "user-risk-timeline", "case-recommendation"], "agents": ["aml-fraud"], "missing_sources": []},
    {"id": 18, "domain": "aml-fraud", "question": "Are there signs of account takeover, coordinated abuse, wash trading, spoofing, or withdrawal fraud?", "coverage": "partial", "use_cases": ["account-takeover", "market-manipulation", "coordinated-abuse"], "agents": ["aml-fraud", "security", "market-risk"], "missing_sources": ["relationship graph", "full order-event telemetry"]},
    {"id": 19, "domain": "security", "question": "What are the most serious security alerts, suspicious logins, API-key activities, or administrative changes today?", "coverage": "supported", "use_cases": ["security-daily-brief", "authentication-anomaly", "privileged-activity"], "agents": ["security"], "missing_sources": []},
    {"id": 20, "domain": "marketing", "question": "Which customer segments are growing or declining, why are users becoming inactive, and what campaigns or retention actions should we prioritize?", "coverage": "partial", "use_cases": ["growth-segmentation", "churn-retention", "campaign-planning"], "agents": ["marketing", "executive"], "missing_sources": ["customer cohort analytics", "live churn features", "campaign attribution"]},
]


def question_catalog(domain: str | None = None, coverage: Coverage | None = None) -> list[dict]:
    rows = MANAGEMENT_QUESTIONS
    if domain:
        rows = [row for row in rows if row["domain"] == domain]
    if coverage:
        rows = [row for row in rows if row["coverage"] == coverage]
    return rows


def readiness_summary() -> dict:
    counts = Counter(row["coverage"] for row in MANAGEMENT_QUESTIONS)
    total = len(MANAGEMENT_QUESTIONS)
    weighted = counts["supported"] + (counts["partial"] * 0.5)
    return {
        "version": "2.16.0",
        "total_questions": total,
        "supported": counts["supported"],
        "partial": counts["partial"],
        "blocked": counts["blocked"],
        "weighted_readiness_percent": round((weighted / total) * 100, 1),
        "required_exchange_endpoints": sorted({
            source
            for row in MANAGEMENT_QUESTIONS
            for source in row["missing_sources"]
            if source.startswith("/api/")
        }),
        "action_executed": False,
    }
