from datetime import date
from decimal import Decimal

from carelog.database.migrations import v009_visit_scheduling
from tests.migration_helpers import get_columns, insert_visit


def test_upgrade_adds_columns(cursor_with_visits):
    cursor = cursor_with_visits
    v009_visit_scheduling.upgrade(cursor)

    columns = get_columns(cursor, "visits")

    # The 14 original columns stay, and the new ones are added last.
    assert len(columns) == 18
    assert columns[0][0] == "id"
    assert columns[13][0] == "updated_at"
    assert columns[14:] == (
        ("planned_date", "date", "YES", None),
        ("completed_date", "date", "YES", None),
        ("planned_duration_minutes", "int", "YES", None),
        ("duration_minutes", "int", "YES", None),
    )


def test_upgrade_keeps_existing_visits(cursor_with_visits):
    cursor = cursor_with_visits
    visit_id = insert_visit(cursor)

    cursor.execute(
        "UPDATE visits "
        "SET priority = 1, planned_week = '2026-11-23', price = 35.50 "
        "WHERE id = %s",
        (visit_id,),
    )

    v009_visit_scheduling.upgrade(cursor)

    cursor.execute(
        "SELECT status, priority, planned_week, price, "
        "planned_date, completed_date, "
        "planned_duration_minutes, duration_minutes "
        "FROM visits WHERE id = %s",
        (visit_id,),
    )

    # Old values are unchanged and the new columns are empty.
    assert cursor.fetchone() == (
        "planned",
        1,
        date(2026, 11, 23),
        Decimal("35.50"),
        None,
        None,
        None,
        None,
    )

    cursor.execute(
        "UPDATE visits "
        "SET planned_date = '2026-11-24', completed_date = '2026-11-24', "
        "planned_duration_minutes = 120, duration_minutes = 90 "
        "WHERE id = %s",
        (visit_id,),
    )

    assert cursor.rowcount == 1


def test_upgrade_can_run_twice(cursor_with_visits):
    cursor = cursor_with_visits

    v009_visit_scheduling.upgrade(cursor)
    v009_visit_scheduling.upgrade(cursor)

    assert len(get_columns(cursor, "visits")) == 18
