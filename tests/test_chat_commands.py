from app.chat_commands import CommandState, detect_intent, plan_command


def test_detects_management_intents():
    assert detect_intent("Calculate treasury coverage for today") == "calculate"
    assert detect_intent("Approve REQ-104 with the required controls") == "approve"
    assert detect_intent("Pause PROC-WITHDRAWAL because of an incident") == "pause"


def test_readonly_command_becomes_tool_ready():
    result = plan_command("s1", "Calculate treasury coverage for today", "manager")
    assert result["state"]["status"] == "ready"
    assert result["tool_call"]["tool"] == "management.calculate_report"
    assert result["tool_call"]["exchange_write_required"] is False
    assert result["state"]["action_executed"] is False


def test_approval_collects_missing_reason():
    result = plan_command("s2", "Approve REQ-104", "manager")
    assert result["state"]["status"] == "collecting"
    assert "reason" in result["state"]["missing_fields"]
    assert result["tool_call"] is None


def test_multiturn_state_preserves_request_and_collects_reason():
    first = plan_command("s3", "Approve REQ-104", "manager")
    state = CommandState.model_validate(first["state"])
    state.fields["reason"] = "Evidence reviewed and policy conditions satisfied"
    second = plan_command("s3", "Proceed", "manager", state)
    assert second["state"]["status"] == "ready"
    assert second["tool_call"]["approval_policy"] == "single_approval"
    assert second["tool_call"]["exchange_write_required"] is True
    assert second["state"]["action_executed"] is False


def test_unauthorized_role_is_blocked():
    result = plan_command("s4", "Approve REQ-104", "viewer")
    assert result["state"]["status"] == "blocked"
    assert result["tool_call"] is None


def test_high_risk_setting_change_requires_maker_checker():
    state = CommandState(
        session_id="s5", intent="set", tool_name="settings.propose",
        fields={"setting_name": "btc_manual_review_threshold", "new_value": "5 BTC", "reason": "Risk policy update"},
    )
    result = plan_command("s5", "Proceed", "manager", state)
    assert result["tool_call"]["risk"] == "high"
    assert result["tool_call"]["approval_policy"] == "maker_checker"
    assert result["state"]["action_executed"] is False
