
import pytest

from carelog.database.migrations import (
    v004_trips,
    v006_visit_notes,
    v007_expenses,
    v008_business_constraints,
)
from tests.migration_helpers import (
    assert_mysql_error,
    insert_client,
    insert_service,
)


@pytest.fixture
def cursor_with_all_tables(cursor_with_visits):
    cursor = cursor_with_visits

    v004_trips.upgrade(cursor)
    v006_visit_notes.upgrade(cursor)
    v007_expenses.upgrade(cursor)

    return cursor


def test_upgrade_creates_constraints(cursor_with_all_tables):
    cursor = cursor_with_all_tables
    v008_business_constraints.upgrade(cursor)

    cursor.execute("""
        SELECT TABLE_NAME, CONSTRAINT_NAME
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND CONSTRAINT_TYPE = 'CHECK'
    """)

    constraints = set(cursor.fetchall())

    expected = {
        ("clients", "chk_clients_distance"),
        ("services", "chk_services_rate"),
        ("trips", "chk_trips_distance"),
        ("visits", "chk_visits_distance"),
        ("visits", "chk_visits_price"),
        ("visits", "chk_visits_time"),
        ("visit_notes", "chk_notes_content"),
        ("expenses", "chk_expenses_amount"),
    }

    assert constraints == expected


def test_upgrade_can_run_twice(cursor_with_all_tables):
    cursor = cursor_with_all_tables

    v008_business_constraints.upgrade(cursor)
    v008_business_constraints.upgrade(cursor)

    cursor.execute("""
        SELECT COUNT(*)
        FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS
        WHERE CONSTRAINT_SCHEMA = DATABASE()
          AND CONSTRAINT_TYPE = 'CHECK'
    """)

    assert cursor.fetchone()[0] == 8


def test_constraints_reject_invalid_values(cursor_with_all_tables):
    cursor = cursor_with_all_tables
    v008_business_constraints.upgrade(cursor)

    client_id = insert_client(cursor)
    service_id = insert_service(cursor)

    cursor.execute(
        "INSERT INTO visits (client_id, service_id) VALUES (%s, %s)",
        (client_id, service_id),
    )

    visit_id = cursor.lastrowid

    invalid_values = [
        (
            "UPDATE clients SET distance_from_home_km = -1 WHERE id = %s",
            (client_id,),
        ),
        (
            "UPDATE services SET default_hourly_rate = -1 WHERE id = %s",
            (service_id,),
        ),
        (
            "INSERT INTO trips "
            "(client_id, start_location, destination, distance_km) "
            "VALUES (%s, 'Home', 'Shop', -1)",
            (client_id,),
        ),
        (
            "UPDATE visits SET distance_km = -1 WHERE id = %s",
            (visit_id,),
        ),
        (
            "UPDATE visits SET price = -1 WHERE id = %s",
            (visit_id,),
        ),
        (
            "UPDATE visits "
            "SET started_at = '2026-01-02 12:00:00', "
            "ended_at = '2026-01-01 12:00:00' "
            "WHERE id = %s",
            (visit_id,),
        ),
        (
            "INSERT INTO visit_notes (visit_id, content) "
            "VALUES (%s, '   ')",
            (visit_id,),
        ),
        (
            "INSERT INTO expenses (expense_date, amount, category) "
            "VALUES ('2026-01-01', 0, 'company')",
            (),
        ),
        (
            "INSERT INTO expenses (expense_date, amount, category) "
            "VALUES ('2026-01-01', -10, 'company')",
            (),
        ),
    ]

    for sql, values in invalid_values:
        assert_mysql_error(cursor, 3819, sql, values)


def test_constraints_accept_valid_values(cursor_with_all_tables):
    cursor = cursor_with_all_tables
    v008_business_constraints.upgrade(cursor)

    client_id = insert_client(cursor)
    service_id = insert_service(cursor)

    cursor.execute(
        "INSERT INTO visits (client_id, service_id) VALUES (%s, %s)",
        (client_id, service_id),
    )

    visit_id = cursor.lastrowid

    cursor.execute(
        "UPDATE clients SET distance_from_home_km = 0 WHERE id = %s",
        (client_id,),
    )

    cursor.execute(
        "UPDATE services SET default_hourly_rate = 0 WHERE id = %s",
        (service_id,),
    )

    cursor.execute(
        "INSERT INTO trips "
        "(client_id, start_location, destination, distance_km) "
        "VALUES (%s, 'Home', 'Shop', 0)",
        (client_id,),
    )

    cursor.execute(
        "UPDATE visits "
        "SET distance_km = 0, price = 0, "
        "started_at = '2026-01-01 12:00:00', "
        "ended_at = '2026-01-01 12:00:00' "
        "WHERE id = %s",
        (visit_id,),
    )

    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content) "
        "VALUES (%s, 'Test note')",
        (visit_id,),
    )

    cursor.execute(
        "INSERT INTO expenses (expense_date, amount, category) "
        "VALUES ('2026-01-01', 0.01, 'company')"
    )
