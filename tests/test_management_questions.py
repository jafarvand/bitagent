from app.management_questions import MANAGEMENT_QUESTIONS, question_catalog, readiness_summary


def test_catalog_contains_twenty_unique_management_questions():
    assert len(MANAGEMENT_QUESTIONS) == 20
    assert len({row["id"] for row in MANAGEMENT_QUESTIONS}) == 20
    assert all(row["question"] for row in MANAGEMENT_QUESTIONS)


def test_every_question_has_agents_use_cases_and_safe_coverage():
    allowed = {"supported", "partial", "blocked"}
    for row in MANAGEMENT_QUESTIONS:
        assert row["coverage"] in allowed
        assert row["agents"]
        assert row["use_cases"]
        assert isinstance(row["missing_sources"], list)


def test_filters_are_deterministic():
    treasury = question_catalog(domain="treasury")
    assert {row["id"] for row in treasury} == {13, 14, 15, 16}
    assert all(row["domain"] == "treasury" for row in treasury)
    assert all(row["coverage"] == "supported" for row in question_catalog(coverage="supported"))


def test_readiness_summary_is_fail_honest_and_non_executing():
    result = readiness_summary()
    assert result["version"] == "3.0.0-rc.5"
    assert result["total_questions"] == 20
    assert result["supported"] + result["partial"] + result["blocked"] == 20
    assert 0 <= result["weighted_readiness_percent"] <= 100
    assert result["action_executed"] is False
    assert "/api/bot/queues/status" in result["required_exchange_endpoints"]
    assert "/api/bot/networks/status" in result["required_exchange_endpoints"]
