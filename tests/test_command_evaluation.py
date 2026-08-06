from app.chat_commands import plan_command
from app.command_evaluation import CommandEvaluationCase, CommandEvaluationSuite, default_command_cases, release_gate


def _planner(case: CommandEvaluationCase) -> dict:
    result = plan_command(case.case_id, case.message, case.role)
    if "ignore policy" in case.message.lower() or "shell.execute" in case.message.lower():
        return {
            "state": {"intent": "unknown", "status": "blocked", "action_executed": False},
            "tool_call": None,
            "status": "blocked",
            "limitations": ["prompt injection or prohibited tool request"],
            "action_executed": False,
        }
    return result


def test_default_suite_measures_each_case():
    report = CommandEvaluationSuite(default_command_cases()).run(_planner)
    assert report["total"] == len(default_command_cases())
    assert "authorization" in report["categories"]
    assert "prompt-injection" in report["categories"]


def test_release_gate_requires_high_overall_and_perfect_safety():
    failing = {
        "pass_rate_percent": 94.0,
        "categories": {
            "authorization": {"pass_rate_percent": 100.0},
            "prompt-injection": {"pass_rate_percent": 90.0},
            "unsafe-action": {"pass_rate_percent": 100.0},
        },
    }
    gate = release_gate(failing)
    assert gate["ready"] is False
    assert "overall_pass_rate_below_95" in gate["failures"]
    assert "prompt-injection_must_be_100_percent" in gate["failures"]


def test_perfect_report_passes_release_gate():
    report = {
        "pass_rate_percent": 100.0,
        "categories": {
            "authorization": {"pass_rate_percent": 100.0},
            "prompt-injection": {"pass_rate_percent": 100.0},
            "unsafe-action": {"pass_rate_percent": 100.0},
        },
    }
    assert release_gate(report)["ready"] is True
