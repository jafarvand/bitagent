from typing import Literal


Role = Literal["anonymous", "viewer", "operator", "auditor", "admin"]

ROLE_CAPABILITIES = {
    "anonymous": set(),
    "viewer": {"view_aggregate", "view_brief", "view_features"},
    "operator": {
        "view_aggregate",
        "view_brief",
        "view_features",
        "view_user_investigation",
        "submit_feedback",
        "use_readonly_chat",
        "create_marketing_plan",
        "view_marketing",
    },
    "auditor": {
        "view_aggregate",
        "view_brief",
        "view_features",
        "view_user_investigation",
        "view_audit",
        "view_chat_audit",
        "view_marketing",
        "view_marketing_audit",
    },
    "admin": {
        "view_aggregate",
        "view_brief",
        "view_features",
        "view_user_investigation",
        "submit_feedback",
        "view_audit",
        "use_readonly_chat",
        "view_chat_audit",
        "create_marketing_plan",
        "view_marketing",
        "view_marketing_audit",
    },
}

PROHIBITED_CAPABILITIES = {
    "place_order",
    "cancel_order",
    "transfer_funds",
    "approve_withdrawal",
    "change_balance",
    "modify_user",
    "modify_exchange_configuration",
    "restart_service",
}


def evaluate_policy(role: str | None, capability: str, *, enforced: bool) -> dict:
    normalized_role = role if role in ROLE_CAPABILITIES else "anonymous"
    if capability in PROHIBITED_CAPABILITIES:
        allowed = False
        reason = "prohibited_by_read_only_boundary"
    elif capability not in set().union(*ROLE_CAPABILITIES.values()):
        allowed = False
        reason = "unknown_capability"
    elif capability in ROLE_CAPABILITIES[normalized_role]:
        allowed = True
        reason = "role_capability_allowed"
    else:
        allowed = False
        reason = "role_capability_denied"
    return {
        "role": normalized_role,
        "capability": capability,
        "allowed": allowed,
        "enforced": enforced,
        "reason": reason,
        "action_executed": False,
    }
