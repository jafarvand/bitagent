from app.command_shadow import ShadowCommandOutcome, evaluate_shadow_outcomes, pilot_mode_policy


def _outcome(index: int) -> ShadowCommandOutcome:
    return ShadowCommandOutcome(
        command_id=f"CMD-{index}",
        category="read-only",
        agent_intent="calculate",
        operator_intent="calculate",
        agent_tool="management.calculate_report",
        operator_tool="management.calculate_report",
        agent_status="succeeded",
        operator_status="succeeded",
        agent_action_executed=False,
        operator_action_executed=False,
        verification_passed=True,
        duplicate=False,
        operator_override=False,
        latency_ms=900,
        user_rating=5,
    )


def test_high_quality_shadow_outcomes_pass_readiness():
    report = evaluate_shadow_outcomes([_outcome(index) for index in range(1, 21)])
    assert report["ready"] is True
    assert report["metrics"]["unauthorized_actions"] == 0


def test_unauthorized_action_blocks_readiness():
    outcomes = [_outcome(index) for index in range(1, 20)]
    unsafe = _outcome(20)
    unsafe.agent_action_executed = True
    outcomes.append(unsafe)
    report = evaluate_shadow_outcomes(outcomes)
    assert report["ready"] is False
    assert "unauthorized_action_detected" in report["failures"]


def test_pilot_policy_keeps_high_risk_actions_plan_only():
    result = pilot_mode_policy(environment="pilot", tool_mode="controlled_write", risk="high")
    assert result["allowed"] is False
    assert result["execution_mode"] == "plan_only"


def test_readonly_tools_can_run_live_in_pilot():
    result = pilot_mode_policy(environment="pilot", tool_mode="read", risk="none")
    assert result["allowed"] is True
    assert result["execution_mode"] == "live_readonly"
