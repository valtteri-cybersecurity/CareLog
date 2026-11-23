from datetime import date
from decimal import Decimal

import psycopg
import pytest

from carelog.services.visit_trips import get_visit_trip, save_visit_trip
from carelog.services.visits import (
    add_completed_visit,
    add_planned_visit,
    complete_visit,
)


THREE_LEGS = [
    {"start_location": "Hilman koti", "destination": "Ruokakauppa", "distance_km": Decimal("3.20")},
    {"start_location": "Ruokakauppa", "destination": "Apteekki", "distance_km": Decimal("1.50")},
    {"start_location": "Apteekki", "destination": "Hilman koti", "distance_km": Decimal("4.10")},
]


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # Nothing may reach the real database. Tests that need PostgreSQL use the
    # trips_database fixture, which connects to an isolated test database.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a test")

    monkeypatch.setattr(
        "carelog.services.visit_trips.get_postgres_connection",
        connection_not_allowed
    )

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        connection_not_allowed
    )


@pytest.fixture
def trips_database(postgres_cursor_with_visit_trips, connect_to_test_postgres, monkeypatch):
    cursor = postgres_cursor_with_visit_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Kauppa-asiointi",)
    )

    service_id = cursor.fetchone()[0]

    return cursor, client_id, service_id


def get_saved_legs(cursor, visit_id):
    cursor.execute(
        """
        SELECT position, start_location, destination, distance_km
        FROM visit_trip_legs
        WHERE visit_id = %s
        ORDER BY position
        """,
        (visit_id,)
    )

    return cursor.fetchall()


def get_visit_distance(cursor, visit_id):
    cursor.execute(
        "SELECT distance_km FROM visits WHERE id = %s",
        (visit_id,)
    )

    return cursor.fetchone()[0]


# VALIDATION TESTS


def test_save_and_get_reject_invalid_visit_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            save_visit_trip(visit_id, THREE_LEGS)

        with pytest.raises(ValueError):
            get_visit_trip(visit_id)


def test_save_visit_trip_rejects_invalid_legs_before_database():
    invalid_lists = (
        None,
        [],
        THREE_LEGS[0],
        [{"start_location": "Koti", "destination": "", "distance_km": 1}],
        [THREE_LEGS[0], {"start_location": "A", "destination": "B", "distance_km": -1}],
    )

    # The database guard would raise RuntimeError, so ValueError proves
    # that nothing was touched before validation
    for legs in invalid_lists:
        with pytest.raises(ValueError):
            save_visit_trip(1, legs)


# SAVE VISIT TRIP TESTS


def test_save_visit_trip_returns_false_for_missing_visit(trips_database):
    assert save_visit_trip(999999, THREE_LEGS) is False


def test_save_visit_trip_rejects_cancelled_visit(trips_database):
    cursor, client_id, service_id = trips_database

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week, distance_km)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16), Decimal("5.00"))
    )

    visit_id = cursor.fetchone()[0]

    with pytest.raises(ValueError, match="cancelled"):
        save_visit_trip(visit_id, THREE_LEGS)

    assert get_saved_legs(cursor, visit_id) == []
    assert get_visit_distance(cursor, visit_id) == Decimal("5.00")


def test_save_visit_trip_for_planned_and_completed_visit(trips_database):
    cursor, client_id, service_id = trips_database

    planned_visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_date=date(2026, 11, 18)
    )

    completed_visit_id = add_completed_visit(
        client_id,
        service_id,
        completed_date=date(2026, 11, 18)
    )

    assert save_visit_trip(planned_visit_id, THREE_LEGS) is True

    one_leg = [{"start_location": " Koti ", "destination": " Pankki ", "distance_km": 5}]

    assert save_visit_trip(completed_visit_id, one_leg) is True

    # Positions start from 1 in the order given by the user
    assert get_saved_legs(cursor, planned_visit_id) == [
        (1, "Hilman koti", "Ruokakauppa", Decimal("3.20")),
        (2, "Ruokakauppa", "Apteekki", Decimal("1.50")),
        (3, "Apteekki", "Hilman koti", Decimal("4.10")),
    ]

    assert get_saved_legs(cursor, completed_visit_id) == [
        (1, "Koti", "Pankki", Decimal("5.00")),
    ]

    # The total distance is saved on the visit
    assert get_visit_distance(cursor, planned_visit_id) == Decimal("8.80")
    assert get_visit_distance(cursor, completed_visit_id) == Decimal("5.00")

    # The status is not changed
    cursor.execute(
        "SELECT status FROM visits WHERE id IN (%s, %s) ORDER BY id",
        (planned_visit_id, completed_visit_id)
    )

    assert cursor.fetchall() == [("planned",), ("completed",)]


def test_save_visit_trip_with_unknown_and_zero_distance(trips_database):
    cursor, client_id, service_id = trips_database

    unknown_visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 11, 18)
    )
    zero_visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 11, 19)
    )

    unknown_legs = [
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.20")},
        {"start_location": "Kauppa", "destination": "Apteekki", "distance_km": None},
    ]

    zero_legs = [
        {"start_location": "Koti", "destination": "Naapuri", "distance_km": Decimal("0.00")},
    ]

    save_visit_trip(unknown_visit_id, unknown_legs)
    save_visit_trip(zero_visit_id, zero_legs)

    # The legs are saved, but the total is unknown, not 3.20
    assert len(get_saved_legs(cursor, unknown_visit_id)) == 2
    assert get_visit_distance(cursor, unknown_visit_id) is None

    # 0 is a known distance
    assert get_visit_distance(cursor, zero_visit_id) == Decimal("0.00")


def test_save_visit_trip_replaces_old_legs(trips_database):
    cursor, client_id, service_id = trips_database

    visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 11, 18)
    )
    other_visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 11, 19)
    )

    save_visit_trip(other_visit_id, THREE_LEGS)

    save_visit_trip(
        visit_id,
        [
            {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.00")},
            {"start_location": "Kauppa", "destination": "Koti", "distance_km": Decimal("3.00")},
        ]
    )

    new_legs = [
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.00")},
        {"start_location": "Kauppa", "destination": "Apteekki", "distance_km": Decimal("1.50")},
        {"start_location": "Apteekki", "destination": "Pankki", "distance_km": Decimal("0.80")},
        {"start_location": "Pankki", "destination": "Koti", "distance_km": Decimal("3.70")},
    ]

    save_visit_trip(visit_id, new_legs)

    # Only the new list is left, numbered from 1 again
    saved = get_saved_legs(cursor, visit_id)

    assert len(saved) == 4
    assert saved[0][0] == 1
    assert saved[3] == (4, "Pankki", "Koti", Decimal("3.70"))
    assert get_visit_distance(cursor, visit_id) == Decimal("9.00")

    # The other visit is not touched
    assert len(get_saved_legs(cursor, other_visit_id)) == 3
    assert get_visit_distance(cursor, other_visit_id) == Decimal("8.80")


def test_manual_distance_and_completion_keep_kilometres(trips_database):
    cursor, client_id, service_id = trips_database

    # A total distance entered without legs is not changed by anything
    manual_visit_id = add_completed_visit(
        client_id,
        service_id,
        completed_date=date(2026, 11, 18),
        distance_km=Decimal("12.50")
    )

    # Kilometres saved before completion stay after completion
    planned_visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_date=date(2026, 11, 18),
        planned_duration_minutes=60
    )

    save_visit_trip(planned_visit_id, THREE_LEGS)
    complete_visit(planned_visit_id)

    assert get_visit_distance(cursor, manual_visit_id) == Decimal("12.50")
    assert get_saved_legs(cursor, manual_visit_id) == []

    assert get_visit_distance(cursor, planned_visit_id) == Decimal("8.80")
    assert len(get_saved_legs(cursor, planned_visit_id)) == 3


def test_save_visit_trip_rolls_back_after_deleting_old_legs(
    trips_database,
    monkeypatch
):
    cursor, client_id, service_id = trips_database

    visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 11, 18)
    )

    save_visit_trip(visit_id, THREE_LEGS)

    legs_before = get_saved_legs(cursor, visit_id)
    distance_before = get_visit_distance(cursor, visit_id)

    assert distance_before == Decimal("8.80")

    # A real database error after the old legs were deleted and the
    # first new leg was inserted: position 0 breaks the CHECK constraint.
    calls = []

    def insert_then_fail(cursor, visit_id, position, start, destination, km):
        calls.append(position)

        if position == 2:
            position = 0

        cursor.execute(
            """
            INSERT INTO visit_trip_legs (
                visit_id, position, start_location, destination, distance_km
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (visit_id, position, start, destination, km)
        )

    monkeypatch.setattr(
        "carelog.services.visit_trips.insert_visit_trip_leg",
        insert_then_fail
    )

    new_legs = [
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("1.00")},
        {"start_location": "Kauppa", "destination": "Koti", "distance_km": Decimal("1.00")},
    ]

    with pytest.raises(psycopg.Error):
        save_visit_trip(visit_id, new_legs)

    # The failure happened inside the transaction
    assert calls == [1, 2]

    # The old legs and the old total are exactly as before
    assert get_saved_legs(cursor, visit_id) == legs_before
    assert get_visit_distance(cursor, visit_id) == distance_before


def test_save_visit_trip_closes_connection_on_error(monkeypatch):

    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False
            self.rolled_back = False

        def cursor(self):
            return self.test_cursor

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def lock_then_fail(cursor, visit_id):
        raise RuntimeError("Simulated lock failure")

    monkeypatch.setattr(
        "carelog.services.visit_trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visit_trips.select_visit_status_for_update",
        lock_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated lock failure"):
        save_visit_trip(1, THREE_LEGS)

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET VISIT TRIP TESTS


def test_get_visit_trip_returns_legs_in_order(trips_database):
    cursor, client_id, service_id = trips_database

    visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 11, 18)
    )
    empty_visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 11, 19)
    )

    save_visit_trip(visit_id, THREE_LEGS)

    legs = get_visit_trip(visit_id)

    assert len(legs) == 3
    assert set(legs[0]) == {
        "id", "visit_id", "position", "start_location", "destination", "distance_km"
    }

    positions = []

    for leg in legs:
        positions.append(leg["position"])

    assert positions == [1, 2, 3]
    assert legs[0]["visit_id"] == visit_id
    assert legs[2]["destination"] == "Hilman koti"
    assert legs[1]["distance_km"] == Decimal("1.50")

    # A visit without legs and a visit that does not exist
    assert get_visit_trip(empty_visit_id) == []
    assert get_visit_trip(999999) == []


def test_get_visit_trip_closes_connection_on_error(monkeypatch):

    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False

        def cursor(self):
            return self.test_cursor

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def select_then_fail(cursor, visit_id):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visit_trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visit_trips.select_visit_trip_legs",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_visit_trip(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True
