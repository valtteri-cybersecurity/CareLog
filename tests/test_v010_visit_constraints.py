import pytest

from carelog.database.migrations import (
    v009_visit_scheduling,
    v010_visit_constraints,
)
from tests.migration_helpers import assert_mysql_error, insert_visit


@pytest.fixture
def cursor_with_v009(cursor_with_visits):
    cursor = cursor_with_visits
    v009_visit_scheduling.upgrade(cursor)
    return cursor


def get_visit_checks(cursor):
    cursor.execute("""
        SELECT CONSTRAINT_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND TABLE_NAME = 'visits'
          AND CONSTRAINT_TYPE = 'CHECK'
    """)

    names = set()

    for row in cursor.fetchall():
        names.add(row[0])

    return names


def test_upgrade_creates_constraints(cursor_with_v009):
    cursor = cursor_with_v009
    v010_visit_constraints.upgrade(cursor)

    assert get_visit_checks(cursor) == {
        "chk_visits_planned_duration",
        "chk_visits_duration",
        "chk_visits_priority",
        "chk_visits_status",
    }


def test_upgrade_can_run_twice(cursor_with_v009):
    cursor = cursor_with_v009

    v010_visit_constraints.upgrade(cursor)
    v010_visit_constraints.upgrade(cursor)

    assert len(get_visit_checks(cursor)) == 4


def test_constraints_reject_invalid_values(cursor_with_v009):
    cursor = cursor_with_v009
    v010_visit_constraints.upgrade(cursor)

    visit_id = insert_visit(cursor)

    invalid_changes = [
        "planned_duration_minutes = 0",
        "planned_duration_minutes = -30",
        "duration_minutes = 0",
        "duration_minutes = -30",
        "priority = 0",
        "priority = 4",
        "status = 'done'",
        "status = ''",
    ]

    for change in invalid_changes:
        assert_mysql_error(
            cursor, 3819,
            f"UPDATE visits SET {change} WHERE id = %s",
            (visit_id,),
        )


def test_constraints_accept_valid_values(cursor_with_v009):
    cursor = cursor_with_v009
    v010_visit_constraints.upgrade(cursor)

    # The defaults (status planned, priority 2) and NULL durations are valid.
    visit_id = insert_visit(cursor)

    valid_changes = [
        "planned_duration_minutes = 1, duration_minutes = 1",
        "planned_duration_minutes = 120, duration_minutes = 90",
        "planned_duration_minutes = NULL, duration_minutes = NULL",
        "priority = 1",
        "priority = 3",
        "status = 'completed'",
        "status = 'cancelled'",
        "status = 'planned'",
    ]

    for change in valid_changes:
        cursor.execute(
            f"UPDATE visits SET {change} WHERE id = %s",
            (visit_id,),
        )
