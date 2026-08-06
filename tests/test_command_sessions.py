from app.chat_commands import CommandState
from app.command_sessions import cancel_session, create_session, load_session, save_state


def test_session_is_tenant_and_user_scoped(tmp_path):
    path = str(tmp_path / "commands.sqlite3")
    created = create_session(path, tenant_id="tenant-a", user_id="manager-1", role="manager")
    assert load_session(
        path,
        session_id=created["session_id"],
        tenant_id="tenant-a",
        user_id="manager-1",
    ) is not None
    assert load_session(
        path,
        session_id=created["session_id"],
        tenant_id="tenant-b",
        user_id="manager-1",
    ) is None


def test_state_update_requires_exact_hash(tmp_path):
    path = str(tmp_path / "commands.sqlite3")
    created = create_session(path, tenant_id="tenant-a", user_id="manager-1", role="manager")
    state = CommandState.model_validate(created["state"])
    state.intent = "calculate"
    state.status = "ready"
    updated = save_state(
        path,
        tenant_id="tenant-a",
        user_id="manager-1",
        state=state,
        expected_state_hash=created["state_hash"],
    )
    assert updated["state_hash"] != created["state_hash"]

    try:
        save_state(
            path,
            tenant_id="tenant-a",
            user_id="manager-1",
            state=state,
            expected_state_hash=created["state_hash"],
        )
        assert False, "stale state hash must be rejected"
    except ValueError as exc:
        assert str(exc) == "session_state_conflict"


def test_session_cancel_is_idempotent(tmp_path):
    path = str(tmp_path / "commands.sqlite3")
    created = create_session(path, tenant_id="tenant-a", user_id="manager-1", role="manager")
    first = cancel_session(
        path,
        session_id=created["session_id"],
        tenant_id="tenant-a",
        user_id="manager-1",
        expected_state_hash=created["state_hash"],
    )
    assert first["status"] == "cancelled"
    second = cancel_session(
        path,
        session_id=created["session_id"],
        tenant_id="tenant-a",
        user_id="manager-1",
        expected_state_hash=first["state_hash"],
    )
    assert second["replayed"] is True
