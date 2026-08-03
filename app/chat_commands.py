from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field


Intent = Literal[
    "search", "view", "calculate", "generate_report", "approve", "reject",
    "pause", "resume", "cancel", "set", "investigate", "unknown",
]
Risk = Literal["none", "low", "medium", "high", "prohibited"]


class ToolDefinition(BaseModel):
    name: str
    intent: Intent
    description: str
    required_fields: list[str] = Field(default_factory=list)
    required_roles: list[str] = Field(default_factory=list)
    risk: Risk = "none"
    approval_policy: Literal["none", "explicit_confirmation", "single_approval", "maker_checker", "prohibited"] = "none"
    reversible: bool = False
    exchange_write_required: bool = False


class CommandState(BaseModel):
    session_id: str
    intent: Intent = "unknown"
    tool_name: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    status: Literal["collecting", "ready", "blocked", "completed"] = "collecting"
    risk: Risk = "none"
    approval_policy: str = "none"
    action_executed: bool = False


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "management.search": ToolDefinition(
        name="management.search", intent="search",
        description="Search retained, authorized exchange evidence.",
        required_fields=["query"], required_roles=["operator", "manager", "admin"],
    ),
    "management.calculate_report": ToolDefinition(
        name="management.calculate_report", intent="calculate",
        description="Calculate a deterministic report from available evidence.",
        required_fields=["report_type", "period"], required_roles=["manager", "admin"],
    ),
    "management.generate_report": ToolDefinition(
        name="management.generate_report", intent="generate_report",
        description="Generate an evidence-backed management report.",
        required_fields=["report_type", "period"], required_roles=["manager", "admin"],
    ),
    "workflow.approve": ToolDefinition(
        name="workflow.approve", intent="approve",
        description="Approve an existing governed workflow request.",
        required_fields=["request_id", "reason"], required_roles=["approver", "manager", "admin"],
        risk="medium", approval_policy="single_approval", reversible=True,
        exchange_write_required=True,
    ),
    "workflow.reject": ToolDefinition(
        name="workflow.reject", intent="reject",
        description="Reject an existing governed workflow request.",
        required_fields=["request_id", "reason"], required_roles=["approver", "manager", "admin"],
        risk="medium", approval_policy="single_approval", reversible=False,
        exchange_write_required=True,
    ),
    "process.pause": ToolDefinition(
        name="process.pause", intent="pause",
        description="Pause an allowlisted process after policy checks.",
        required_fields=["process_id", "reason"], required_roles=["operator", "manager", "admin"],
        risk="high", approval_policy="maker_checker", reversible=True,
        exchange_write_required=True,
    ),
    "settings.propose": ToolDefinition(
        name="settings.propose", intent="set",
        description="Create a governed proposal to change an exchange setting.",
        required_fields=["setting_name", "new_value", "reason"], required_roles=["manager", "admin"],
        risk="high", approval_policy="maker_checker", reversible=True,
        exchange_write_required=True,
    ),
}


_KEYWORDS: list[tuple[Intent, tuple[str, ...]]] = [
    ("approve", ("approve", "authorize", "accept")),
    ("reject", ("reject", "deny", "decline")),
    ("pause", ("pause", "stop", "hold")),
    ("resume", ("resume", "continue", "unpause")),
    ("cancel", ("cancel", "abort")),
    ("set", ("set", "change", "update setting", "configure")),
    ("generate_report", ("generate report", "create report", "prepare report")),
    ("calculate", ("calculate", "compute", "compare", "coverage")),
    ("investigate", ("investigate", "diagnose", "why")),
    ("search", ("search", "find", "look up")),
    ("view", ("show", "view", "list")),
]


_INTENT_TOOL = {
    "search": "management.search",
    "view": "management.search",
    "calculate": "management.calculate_report",
    "generate_report": "management.generate_report",
    "approve": "workflow.approve",
    "reject": "workflow.reject",
    "pause": "process.pause",
    "set": "settings.propose",
}


def detect_intent(message: str) -> Intent:
    normalized = " ".join(message.lower().split())
    for intent, words in _KEYWORDS:
        if any(word in normalized for word in words):
            return intent
    return "unknown"


def _extract_fields(message: str, intent: Intent) -> dict[str, str]:
    text = " ".join(message.strip().split())
    fields: dict[str, str] = {}
    if intent in {"search", "view", "investigate"}:
        fields["query"] = text
    if intent in {"calculate", "generate_report"}:
        fields["report_type"] = text
        for period in ("today", "yesterday", "last week", "this week", "last month", "30 days"):
            if period in text.lower():
                fields["period"] = period
                break
    tokens = text.replace("#", " ").split()
    for token in tokens:
        cleaned = token.strip(".,:;()[]")
        if cleaned.upper().startswith(("REQ-", "APR-", "CASE-")):
            fields["request_id"] = cleaned
        if cleaned.upper().startswith(("PROC-", "JOB-", "CMP-")):
            fields["process_id"] = cleaned
    return fields


def plan_command(session_id: str, message: str, role: str, existing: CommandState | None = None) -> dict:
    state = existing.model_copy(deep=True) if existing else CommandState(session_id=session_id)
    intent = state.intent if state.intent != "unknown" else detect_intent(message)
    state.intent = intent
    state.fields.update(_extract_fields(message, intent))

    tool_name = state.tool_name or _INTENT_TOOL.get(intent)
    if not tool_name:
        state.status = "blocked"
        return {"state": state.model_dump(), "reply": "I could not identify an allowed command. Please state the task and target.", "tool_call": None}

    tool = TOOL_REGISTRY[tool_name]
    state.tool_name = tool_name
    state.risk = tool.risk
    state.approval_policy = tool.approval_policy

    if role not in tool.required_roles:
        state.status = "blocked"
        return {"state": state.model_dump(), "reply": f"Your role is not authorized for {tool.name}.", "tool_call": None}

    state.missing_fields = [field for field in tool.required_fields if not state.fields.get(field)]
    if state.missing_fields:
        state.status = "collecting"
        needed = ", ".join(state.missing_fields)
        return {"state": state.model_dump(), "reply": f"I need the following information: {needed}.", "tool_call": None}

    if tool.exchange_write_required:
        state.status = "ready"
        return {
            "state": state.model_dump(),
            "reply": "The command is ready for policy and approval processing. No exchange change has been executed.",
            "tool_call": {
                "tool": tool.name,
                "arguments": state.fields,
                "risk": tool.risk,
                "approval_policy": tool.approval_policy,
                "exchange_write_required": True,
            },
        }

    state.status = "ready"
    return {
        "state": state.model_dump(),
        "reply": "The command is ready for read-only execution.",
        "tool_call": {
            "tool": tool.name,
            "arguments": state.fields,
            "risk": tool.risk,
            "approval_policy": tool.approval_policy,
            "exchange_write_required": False,
        },
    }
