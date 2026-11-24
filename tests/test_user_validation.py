import pytest

from carelog.services import user_validation
from carelog.services.user_validation import (
    check_worker_access,
    get_active_user,
    get_owner_filter,
    is_admin,
    validate_user_id,
)
from tests.postgres_helpers import insert_client


ADMIN = {"id": 1, "role": "admin", "is_active": True}
WORKER = {"id": 2, "role": "worker", "is_active": True}


@pytest.mark.parametrize("user_id", [None, True, False, "1", 1.0, 0, -1])
def test_validate_user_id_rejects_invalid_id(user_id):
    with pytest.raises(ValueError):
        validate_user_id(user_id)


def test_get_active_user_validates_id_before_database():
    # The cursor is never used for an invalid ID
    with pytest.raises(ValueError):
        get_active_user(None, True)


def test_get_active_user_rejects_unknown_role(monkeypatch):
    # The database allows only admin and worker. The service checks the
    # role too, in case the CHECK constraint is ever changed.
    def fake_select_user(cursor, user_id):
        return {"id": user_id, "role": "guest", "is_active": True}

    monkeypatch.setattr(user_validation, "select_user", fake_select_user)

    with pytest.raises(PermissionError):
        get_active_user(None, 5)


def test_is_admin():
    assert is_admin(ADMIN) is True
    assert is_admin(WORKER) is False


def test_worker_can_handle_own_record():
    check_worker_access(WORKER, 2)


def test_worker_cannot_handle_other_workers_record():
    with pytest.raises(PermissionError):
        check_worker_access(WORKER, 3)


def test_admin_can_handle_other_workers_record():
    check_worker_access(ADMIN, 2)


def test_check_worker_access_rejects_invalid_owner_id():
    # True == 1 in Python, so a bool must not pass as the actor's own ID
    with pytest.raises(ValueError):
        check_worker_access(ADMIN, True)


def test_get_owner_filter():
    # No user_id: an admin gets every worker (None), a worker their own ID
    assert get_owner_filter(ADMIN, None) is None
    assert get_owner_filter(WORKER, None) == 2

    # An admin may choose any worker, a worker only themselves
    assert get_owner_filter(ADMIN, 2) == 2
    assert get_owner_filter(WORKER, 2) == 2

    with pytest.raises(PermissionError):
        get_owner_filter(WORKER, 3)


def test_get_active_user_returns_user_from_database(migrated_cursor, user_ids):
    admin_id = user_ids["admin"]
    worker_id = user_ids["worker"]

    admin = get_active_user(migrated_cursor, admin_id)
    worker = get_active_user(migrated_cursor, worker_id)

    assert admin == {"id": admin_id, "role": "admin", "is_active": True}
    assert worker == {"id": worker_id, "role": "worker", "is_active": True}
    assert is_admin(admin) is True
    assert is_admin(worker) is False


def test_get_active_user_rejects_missing_user(migrated_cursor):
    with pytest.raises(ValueError, match="User not found"):
        get_active_user(migrated_cursor, 999)


def test_get_active_user_rejects_inactive_user(migrated_cursor, user_ids):
    with pytest.raises(PermissionError, match="not active"):
        get_active_user(migrated_cursor, user_ids["inactive"])


def test_failed_check_saves_nothing_in_write_transaction(migrated_cursor, user_ids):
    cursor = migrated_cursor
    active_id = user_ids["worker"]
    inactive_id = user_ids["inactive"]

    # A row written before the failed check is rolled back with the
    # whole transaction.
    with pytest.raises(PermissionError):
        with cursor.connection.transaction():
            insert_client(cursor, active_id)
            get_active_user(cursor, inactive_id)

    cursor.execute("SELECT COUNT(*) FROM clients")

    assert cursor.fetchone()[0] == 0
