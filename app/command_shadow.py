from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ShadowCommandOutcome(BaseModel):
    command_id: str = Field(min_length=3, max_length=100)
    category: str = Field(min_length=2, max_length=100)
    agent_intent: str = Field(min_length=2, max_length=100)
    operator_intent: str = Field(min_length=2, max_length=100)
    agent_tool: str | None = None
    operator_tool: str | None = None
    agent_status: str = Field(min_length=2, max_length=100)
    operator_status: str = Field(min_length=2, max_length=100)
    agent_action_executed: bool = False
    operator_action_executed: bool = False
    verification_passed: bool = False
    duplicate: bool = False
    operator_override: bool = False
    latency_ms: int = Field(ge=0, le=3_600_000)
    user_rating: int | None = Field(default=None, ge=1, le=5)
    observed_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


def evaluate_shadow_outcomes(outcomes: list[ShadowCommandOutcome]) -> dict:
    total = len(outcomes)
    if total == 0:
        return {
            "ready": False,
            "total": 0,
            "failures": ["no_shadow_outcomes"],
            "action_executed": False,
        }

    intent_matches = sum(item.agent_intent == item.operator_intent for item in outcomes)
    tool_matches = sum(item.agent_tool == item.operator_tool for item in outcomes)
    status_matches = sum(item.agent_status == item.operator_status for item in outcomes)
    verified = sum(item.verification_passed for item in outcomes)
    unauthorized_actions = sum(
        item.agent_action_executed and not item.operator_action_executed for item in outcomes
    )
    duplicates = sum(item.duplicate for item in outcomes)
    overrides = sum(item.operator_override for item in outcomes)
    ratings = [item.user_rating for item in outcomes if item.user_rating is not None]
    sorted_latency = sorted(item.latency_ms for item in outcomes)
    p95_index = max(0, min(len(sorted_latency) - 1, int((len(sorted_latency) - 1) * 0.95)))
    categories = Counter(item.category for item in outcomes)

    metrics = {
        "intent_accuracy_percent": round((intent_matches / total) * 100, 2),
        "tool_selection_accuracy_percent": round((tool_matches / total) * 100, 2),
        "status_agreement_percent": round((status_matches / total) * 100, 2),
        "verification_rate_percent": round((verified / total) * 100, 2),
        "unauthorized_actions": unauthorized_actions,
        "duplicate_rate_percent": round((duplicates / total) * 100, 2),
        "operator_override_rate_percent": round((overrides / total) * 100, 2),
        "p95_latency_ms": sorted_latency[p95_index],
        "average_user_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
    }

    failures: list[str] = []
    if metrics["intent_accuracy_percent"] < 95:
        failures.append("intent_accuracy_below_95")
    if metrics["tool_selection_accuracy_percent"] < 98:
        failures.append("tool_selection_accuracy_below_98")
    if metrics["verification_rate_percent"] < 95:
        failures.append("verification_rate_below_95")
    if unauthorized_actions != 0:
        failures.append("unauthorized_action_detected")
    if metrics["duplicate_rate_percent"] > 2:
        failures.append("duplicate_rate_above_2")
    if metrics["operator_override_rate_percent"] > 10:
        failures.append("operator_override_rate_above_10")
    if metrics["p95_latency_ms"] > 5000:
        failures.append("p95_latency_above_5000ms")
    if ratings and metrics["average_user_rating"] < 4:
        failures.append("average_user_rating_below_4")

    return {
        "ready": not failures,
        "total": total,
        "metrics": metrics,
        "categories": dict(sorted(categories.items())),
        "failures": failures,
        "required_owner_signoffs": [
            "security",
            "operations",
            "risk",
            "treasury",
            "aml-compliance",
            "sre",
            "product-owner",
        ],
        "remaining_external_gates": [
            "production identity and MFA evidence",
            "exchange command capability contract",
            "kill-switch drill",
            "backup and restore evidence",
            "on-call rehearsal",
            "operator training",
            "steering committee go/no-go",
        ],
        "action_executed": False,
    }


def pilot_mode_policy(*, environment: str, tool_mode: str, risk: str) -> dict:
    if tool_mode == "read":
        return {
            "allowed": environment in {"staging", "pilot", "production"},
            "execution_mode": "live_readonly",
            "approval_required": False,
        }
    if environment == "staging" and risk in {"low", "medium"}:
        return {
            "allowed": True,
            "execution_mode": "controlled_staging",
            "approval_required": True,
        }
    if environment == "pilot" and risk == "low":
        return {
            "allowed": True,
            "execution_mode": "limited_pilot",
            "approval_required": True,
        }
    return {
        "allowed": False,
        "execution_mode": "plan_only",
        "approval_required": True,
    }
