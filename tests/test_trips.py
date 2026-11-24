from decimal import Decimal

import psycopg
import pytest

from carelog.services.trips import (
    add_trip,
    calculate_trip_distance,
    delete_trip,
    get_trip,
    get_trips,
    leg_from_trip,
    update_trip,
    validate_trip_leg,
)
from tests.postgres_helpers import fake_active_user


# ADD TRIP TESTS


def test_add_trip_rejects_invalid_client_id():
    for client_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            add_trip(1, client_id, "Koti", "Kauppa")


def test_add_trip_rejects_invalid_locations():
    invalid_locations = (
        ("", "Kauppa"),
        ("Koti", "   "),
        (123, "Kauppa"),
        ("Koti", None),
        ("A" * 256, "Kauppa"),
        ("Koti", "A" * 256),
    )

    for start_location, destination in invalid_locations:
        with pytest.raises(ValueError):
            add_trip(1, 1, start_location, destination)


def test_add_trip_rejects_invalid_distance():
    invalid_distances = (
        -1,
        True,
        "5",
        float("nan"),
        float("inf"),
        Decimal("12.555"),
        Decimal("100000000.00"),
    )

    for distance_km in invalid_distances:
        with pytest.raises(ValueError):
            add_trip(1, 1, "Koti", "Kauppa", distance_km)


def test_add_trip_saves_to_database(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    trip_id = add_trip(
        user_ids["worker"],
        client_id,
        "  Koti  ",
        "  Kauppa  ",
        12.5
    )

    cursor.execute(
        """
        SELECT client_id, start_location, destination, distance_km
        FROM trips
        WHERE id = %s
        """,
        (trip_id,)
    )

    assert cursor.fetchone() == (
        client_id,
        "Koti",
        "Kauppa",
        Decimal("12.50")
    )


def test_add_trip_saves_null_and_zero_distance(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    trip_without_distance = add_trip(user_ids["worker"], client_id, "Koti", "Apteekki")
    trip_with_zero_distance = add_trip(user_ids["worker"], client_id, "Koti", "Naapuri", 0)

    cursor.execute(
        "SELECT distance_km FROM trips WHERE id = %s",
        (trip_without_distance,)
    )

    assert cursor.fetchone()[0] is None

    cursor.execute(
        "SELECT distance_km FROM trips WHERE id = %s",
        (trip_with_zero_distance,)
    )

    assert cursor.fetchone()[0] == Decimal("0.00")


def test_add_trip_rejects_missing_client(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    # The foreign key must reject a client that does not exist
    with pytest.raises(psycopg.IntegrityError):
        add_trip(user_ids["worker"], 999999, "Koti", "Kauppa")

    cursor.execute("SELECT COUNT(*) FROM trips")

    assert cursor.fetchone()[0] == 0


def test_add_trip_rolls_back_on_error(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(
        cursor,
        created_by_user_id,
        client_id,
        start_location,
        destination,
        distance_km
    ):
        cursor.execute(
            """
            INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
            VALUES (%s, %s, %s, %s)
            """,
            (client_id, start_location, destination, created_by_user_id)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.insert_trip",
        insert_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_trip(user_ids["worker"], client_id, "Koti", "Kauppa")

    cursor.execute("SELECT COUNT(*) FROM trips")

    assert cursor.fetchone()[0] == 0


def test_add_trip_closes_connection_on_error(monkeypatch):

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

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.trips.get_active_user", fake_active_user)

    def insert_then_fail(
        cursor,
        created_by_user_id,
        client_id,
        start_location,
        destination,
        distance_km
    ):
        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.insert_trip",
        insert_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_trip(1, 1, "Koti", "Kauppa")

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET TRIP TESTS


def test_get_trip_rejects_invalid_id():
    for trip_id in ("1", None, 0, -1):
        with pytest.raises(ValueError):
            get_trip(trip_id)


def test_get_trip_rejects_boolean_id():
    with pytest.raises(ValueError):
        get_trip(True)


def test_get_trip_returns_trip(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, distance_km, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, "Koti", "Kauppa", Decimal("12.50"), user_ids["worker"])
    )

    trip_id = cursor.fetchone()[0]

    trip = get_trip(trip_id)

    # updated_at is set by the database
    assert trip.pop("updated_at") is not None

    assert trip == {
        "id": trip_id,
        "client_id": client_id,
        "start_location": "Koti",
        "destination": "Kauppa",
        "distance_km": Decimal("12.50"),
        "created_by_user_id": user_ids["worker"],
        "updated_by_user_id": None,
    }


def test_get_trip_returns_none_if_not_found(
    postgres_cursor_with_trips,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    trip = get_trip(999999)

    assert trip is None


def test_get_trip_closes_connection_on_error(monkeypatch):

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

    def select_then_fail(cursor, trip_id):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.select_trip",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_trip(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET TRIPS TESTS


def test_get_trips_rejects_invalid_client_id():
    for client_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            get_trips(client_id)


def test_get_trips_returns_empty_list(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    trips = get_trips(client_id)

    assert trips == []


def test_get_trips_returns_sorted_trips(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    trip_rows = (
        ("Koti", "Kauppa", Decimal("12.50")),
        ("Asiakas", "Apteekki", None),
        ("Koti", "Apteekki", Decimal("8.00")),
    )

    for start_location, destination, distance_km in trip_rows:
        cursor.execute(
            """
            INSERT INTO trips (client_id, start_location, destination, distance_km, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (client_id, start_location, destination, distance_km, user_ids["worker"])
        )

    trips = get_trips(client_id)

    assert len(trips) == 3

    # Sorted by start location, then destination
    assert trips[0]["start_location"] == "Asiakas"
    assert trips[0]["destination"] == "Apteekki"
    assert trips[1]["start_location"] == "Koti"
    assert trips[1]["destination"] == "Apteekki"
    assert trips[2]["start_location"] == "Koti"
    assert trips[2]["destination"] == "Kauppa"

    assert isinstance(trips[0]["id"], int)
    assert trips[0]["client_id"] == client_id
    assert trips[0]["distance_km"] is None
    assert trips[2]["distance_km"] == Decimal("12.50")


def test_get_trips_excludes_other_clients_trips(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Toinen", "Asiakas", user_ids["worker"])
    )

    other_client_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa", user_ids["worker"])
    )

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        """,
        (other_client_id, "Koti", "Kirjasto", user_ids["worker"])
    )

    trips = get_trips(client_id)

    assert len(trips) == 1
    assert trips[0]["client_id"] == client_id
    assert trips[0]["destination"] == "Kauppa"


def test_get_trips_closes_connection_on_error(monkeypatch):

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

    def select_then_fail(cursor, client_id):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.select_trips",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_trips(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# UPDATE TRIP TESTS


def test_update_trip_rejects_invalid_id():
    for trip_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            update_trip(1, trip_id, {"destination": "Kauppa"})


def test_update_trip_rejects_invalid_changes():
    invalid_changes = (
        None,
        [],
        {},
        {"id": 5},
        {"client_id": 2},
        {"unknown": "Kauppa"},
    )

    for changes in invalid_changes:
        with pytest.raises(ValueError):
            update_trip(1, 1, changes)


def test_update_trip_rejects_invalid_locations():
    invalid_changes = (
        {"start_location": "   "},
        {"destination": ""},
        {"destination": None},
        {"start_location": 123},
        {"destination": "A" * 256},
    )

    for changes in invalid_changes:
        with pytest.raises(ValueError):
            update_trip(1, 1, changes)


def test_update_trip_rejects_invalid_distance():
    invalid_distances = (
        -1,
        True,
        "5",
        float("nan"),
        float("inf"),
        Decimal("12.555"),
        Decimal("100000000.00"),
    )

    for distance_km in invalid_distances:
        with pytest.raises(ValueError):
            update_trip(1, 1, {"distance_km": distance_km})


def test_update_trip_changes_locations(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, distance_km, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, "Koti", "Kauppa", Decimal("12.50"), user_ids["worker"])
    )

    trip_id = cursor.fetchone()[0]

    updated = update_trip(
        user_ids["worker"],
        trip_id,
        {
            "start_location": "  Asiakkaan koti  ",
            "destination": "  Apteekki  "
        }
    )

    assert updated is True

    cursor.execute(
        """
        SELECT client_id, start_location, destination, distance_km
        FROM trips
        WHERE id = %s
        """,
        (trip_id,)
    )

    # The distance was not given, so it must stay the same
    assert cursor.fetchone() == (
        client_id,
        "Asiakkaan koti",
        "Apteekki",
        Decimal("12.50")
    )

    # Saving the same value again is still a successful update
    assert update_trip(user_ids["worker"], trip_id, {"destination": "Apteekki"}) is True


def test_update_trip_changes_and_clears_distance(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, "Koti", "Kauppa", user_ids["worker"])
    )

    trip_id = cursor.fetchone()[0]

    assert update_trip(user_ids["worker"], trip_id, {"distance_km": 7.25}) is True

    cursor.execute(
        "SELECT distance_km FROM trips WHERE id = %s",
        (trip_id,)
    )

    assert cursor.fetchone()[0] == Decimal("7.25")

    assert update_trip(user_ids["worker"], trip_id, {"distance_km": None}) is True

    cursor.execute(
        "SELECT distance_km FROM trips WHERE id = %s",
        (trip_id,)
    )

    assert cursor.fetchone()[0] is None


def test_update_trip_returns_false_if_not_found(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    updated = update_trip(
        user_ids["worker"],
        999999,
        {"destination": "Kauppa"}
    )

    assert updated is False


def test_update_trip_rolls_back_on_error(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def update_then_fail(cursor, updated_by_user_id, trip_id, changes):
        cursor.execute(
            """
            UPDATE trips
            SET destination = %s
            WHERE id = %s
            """,
            ("Apteekki", trip_id)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.update_trip_record",
        update_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, "Koti", "Kauppa", user_ids["worker"])
    )

    trip_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_trip(user_ids["worker"], trip_id, {"destination": "Apteekki"})

    cursor.execute(
        "SELECT destination FROM trips WHERE id = %s",
        (trip_id,)
    )

    assert cursor.fetchone()[0] == "Kauppa"


def test_update_trip_closes_connection_on_error(monkeypatch):

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

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.trips.get_active_user", fake_active_user)

    def update_then_fail(cursor, updated_by_user_id, trip_id, changes):
        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.update_trip_record",
        update_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_trip(1, 1, {"destination": "Kauppa"})

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# DELETE TRIP TESTS


def test_delete_trip_rejects_invalid_id():
    for trip_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            delete_trip(1, trip_id)


def test_delete_trip_removes_only_given_trip(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, "Koti", "Kauppa", user_ids["worker"])
    )

    trip_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, "Koti", "Apteekki", user_ids["worker"])
    )

    other_trip_id = cursor.fetchone()[0]

    deleted = delete_trip(user_ids["worker"], trip_id)

    assert deleted is True

    cursor.execute("SELECT id FROM trips")

    # Only the other trip is left
    assert cursor.fetchall() == [(other_trip_id,)]

    cursor.execute(
        "SELECT COUNT(*) FROM clients WHERE id = %s",
        (client_id,)
    )

    # Deleting a trip must not delete the client
    assert cursor.fetchone()[0] == 1


def test_delete_trip_returns_false_if_not_found(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    deleted = delete_trip(user_ids["worker"], 999999)

    assert deleted is False


def test_delete_trip_rolls_back_on_error(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def delete_then_fail(cursor, trip_id):
        cursor.execute(
            "DELETE FROM trips WHERE id = %s",
            (trip_id,)
        )

        raise RuntimeError("Simulated delete failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.delete_trip_record",
        delete_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, "Koti", "Kauppa", user_ids["worker"])
    )

    trip_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated delete failure"):
        delete_trip(user_ids["worker"], trip_id)

    cursor.execute(
        "SELECT COUNT(*) FROM trips WHERE id = %s",
        (trip_id,)
    )

    assert cursor.fetchone()[0] == 1


def test_delete_trip_closes_connection_on_error(monkeypatch):

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

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.trips.get_active_user", fake_active_user)

    def delete_then_fail(cursor, trip_id):
        raise RuntimeError("Simulated delete failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.delete_trip_record",
        delete_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated delete failure"):
        delete_trip(1, 1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# TRIP LEG TESTS


@pytest.fixture
def block_real_database(monkeypatch):

    # The trip leg functions are pure Python. If they ever try to open
    # a database connection, the test fails clearly.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a unit test")

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        connection_not_allowed
    )


def test_validate_trip_leg_returns_clean_copy(block_real_database):
    leg = {
        "start_location": " Hilman koti ",
        "destination": " Ruokakauppa ",
        "distance_km": Decimal("3.20"),
    }

    validated = validate_trip_leg(leg)

    assert validated == {
        "start_location": "Hilman koti",
        "destination": "Ruokakauppa",
        "distance_km": Decimal("3.20"),
    }

    # A new dictionary; the original is not changed
    assert validated is not leg
    assert leg["start_location"] == " Hilman koti "

    # int and float are accepted like in add_trip()
    assert validate_trip_leg(
        {"start_location": "A", "destination": "B", "distance_km": 3.2}
    )["distance_km"] == Decimal("3.2")


def test_validate_trip_leg_accepts_unknown_and_zero_distance(block_real_database):
    unknown = validate_trip_leg(
        {"start_location": "Koti", "destination": "Apteekki", "distance_km": None}
    )

    zero = validate_trip_leg(
        {"start_location": "Koti", "destination": "Naapuri", "distance_km": 0}
    )

    # Unknown stays unknown; it is never turned into 0
    assert unknown["distance_km"] is None
    assert zero["distance_km"] == Decimal("0")


def test_validate_trip_leg_rejects_invalid_structure(block_real_database):
    invalid_legs = (
        None,
        [],
        "Koti - Kauppa",
        # Missing fields
        {"start_location": "Koti", "destination": "Kauppa"},
        {"destination": "Kauppa", "distance_km": 3},
        # Unknown field
        {
            "start_location": "Koti",
            "destination": "Kauppa",
            "distance_km": 3,
            "visit_id": 1,
        },
    )

    for leg in invalid_legs:
        with pytest.raises(ValueError):
            validate_trip_leg(leg)


def test_validate_trip_leg_rejects_invalid_values(block_real_database):
    invalid_values = (
        {"start_location": ""},
        {"start_location": "   "},
        {"destination": None},
        {"destination": 123},
        {"start_location": "A" * 256},
        {"distance_km": -1},
        {"distance_km": True},
        {"distance_km": "3.2"},
        {"distance_km": float("nan")},
        {"distance_km": float("inf")},
        {"distance_km": Decimal("3.205")},
        {"distance_km": Decimal("100000000.00")},
    )

    for values in invalid_values:
        leg = {
            "start_location": "Koti",
            "destination": "Kauppa",
            "distance_km": Decimal("3.20"),
        }

        leg.update(values)

        with pytest.raises(ValueError):
            validate_trip_leg(leg)


def test_leg_from_trip_copies_only_the_route(block_real_database):
    trip = {
        "id": 12,
        "client_id": 5,
        "start_location": "Hilman koti",
        "destination": "Ruokakauppa",
        "distance_km": Decimal("3.20"),
    }

    leg = leg_from_trip(trip)

    # No id or client_id, so the leg has no link to the saved trip
    assert leg == {
        "start_location": "Hilman koti",
        "destination": "Ruokakauppa",
        "distance_km": Decimal("3.20"),
    }

    # Changing the leg later does not change the saved trip
    leg["distance_km"] = Decimal("4.00")

    assert trip["distance_km"] == Decimal("3.20")
    assert trip["id"] == 12


def test_leg_from_trip_rejects_invalid_trip(block_real_database):
    invalid_trips = (
        None,
        [],
        {"id": 1, "start_location": "Koti", "destination": "Kauppa"},
        {
            "id": 1,
            "client_id": 5,
            "start_location": "  ",
            "destination": "Kauppa",
            "distance_km": None,
        },
    )

    for trip in invalid_trips:
        with pytest.raises(ValueError):
            leg_from_trip(trip)


# CALCULATE TRIP DISTANCE TESTS


def test_calculate_trip_distance_adds_legs(block_real_database):
    one_leg = [
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.20")},
    ]

    assert calculate_trip_distance(one_leg) == Decimal("3.20")

    three_legs = [
        {"start_location": "Hilman koti", "destination": "Ruokakauppa", "distance_km": Decimal("3.20")},
        {"start_location": "Ruokakauppa", "destination": "Apteekki", "distance_km": Decimal("1.50")},
        {"start_location": "Apteekki", "destination": "Hilman koti", "distance_km": Decimal("4.10")},
    ]

    total = calculate_trip_distance(three_legs)

    assert total == Decimal("8.80")
    assert isinstance(total, Decimal)

    # 0.1 + 0.2 would be 0.30000000000000004 with floats
    precise_legs = [
        {"start_location": "A", "destination": "B", "distance_km": 0.1},
        {"start_location": "B", "destination": "C", "distance_km": 0.2},
    ]

    assert calculate_trip_distance(precise_legs) == Decimal("0.30")


def test_calculate_trip_distance_rejects_invalid_list(block_real_database):
    leg = {"start_location": "Koti", "destination": "Kauppa", "distance_km": 3}

    for legs in (None, "Koti - Kauppa", leg, (leg,), []):
        with pytest.raises(ValueError):
            calculate_trip_distance(legs)


def test_calculate_trip_distance_rejects_invalid_leg(block_real_database):
    invalid_legs = (
        {"start_location": "", "destination": "Kauppa", "distance_km": 3},
        {"start_location": "Koti", "destination": "Kauppa"},
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": -1},
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": True},
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": float("nan")},
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": float("inf")},
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("1.005")},
        "Koti - Kauppa",
    )

    valid_leg = {"start_location": "Koti", "destination": "Kauppa", "distance_km": 3}

    for invalid_leg in invalid_legs:
        with pytest.raises(ValueError):
            calculate_trip_distance([valid_leg, invalid_leg])


def test_calculate_trip_distance_returns_none_for_unknown_distance(block_real_database):
    legs = [
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.20")},
        {"start_location": "Kauppa", "destination": "Apteekki", "distance_km": None},
    ]

    # The total is unknown, not 3.20 and not 0
    assert calculate_trip_distance(legs) is None

    # A None does not hide an invalid leg later in the list
    legs_with_error = [
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": None},
        {"start_location": "Kauppa", "destination": "Apteekki", "distance_km": -1},
    ]

    with pytest.raises(ValueError):
        calculate_trip_distance(legs_with_error)


def test_calculate_trip_distance_accepts_zero(block_real_database):
    legs = [
        {"start_location": "Koti", "destination": "Naapuri", "distance_km": Decimal("0.00")},
    ]

    # 0 is a known distance, different from None
    total = calculate_trip_distance(legs)

    assert total == Decimal("0.00")
    assert total is not None


def test_calculate_trip_distance_checks_total_limit(block_real_database):
    legs = [
        {"start_location": "A", "destination": "B", "distance_km": Decimal("99999999.00")},
        {"start_location": "B", "destination": "C", "distance_km": Decimal("0.99")},
    ]

    assert calculate_trip_distance(legs) == Decimal("99999999.99")

    legs.append(
        {"start_location": "C", "destination": "D", "distance_km": Decimal("0.01")}
    )

    with pytest.raises(ValueError, match="Total distance"):
        calculate_trip_distance(legs)

    # Too long even if another leg is unknown
    legs.append({"start_location": "D", "destination": "E", "distance_km": None})

    with pytest.raises(ValueError, match="Total distance"):
        calculate_trip_distance(legs)


def test_calculate_trip_distance_does_not_change_input(block_real_database):
    legs = [
        {"start_location": " Koti ", "destination": " Kauppa ", "distance_km": 3.2},
        {"start_location": "Kauppa", "destination": "Koti", "distance_km": None},
    ]

    calculate_trip_distance(legs)

    assert legs == [
        {"start_location": " Koti ", "destination": " Kauppa ", "distance_km": 3.2},
        {"start_location": "Kauppa", "destination": "Koti", "distance_km": None},
    ]


# USER TRACKING TESTS


def test_trip_writes_reject_invalid_actor_id():
    # The user check itself is tested in test_user_validation.py
    for actor_user_id in (None, True, "1", 0):
        with pytest.raises(ValueError):
            add_trip(actor_user_id, 1, "Koti", "Kauppa")

        with pytest.raises(ValueError):
            update_trip(actor_user_id, 1, {"destination": "Apteekki"})

        with pytest.raises(ValueError):
            delete_trip(actor_user_id, 1)


def test_trip_saves_creator_and_latest_editor(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) "
        "VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["admin"])
    )
    client_id = cursor.fetchone()[0]

    trip_id = add_trip(worker_id, client_id, "Koti", "Kauppa")

    trip = get_trip(trip_id)
    assert trip["created_by_user_id"] == worker_id
    assert trip["updated_by_user_id"] is None

    # Saved trips are shared: another worker may change the trip
    assert update_trip(other_worker_id, trip_id, {"distance_km": Decimal("4.50")})

    trips = get_trips(client_id)
    assert len(trips) == 1
    assert trips[0]["created_by_user_id"] == worker_id
    assert trips[0]["updated_by_user_id"] == other_worker_id

    assert delete_trip(other_worker_id, trip_id) is True
    assert get_trip(trip_id) is None


def test_trip_writes_reject_missing_and_inactive_users(
    postgres_cursor_with_trips,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) "
        "VALUES (%s, %s, %s) RETURNING id",
        ("Testi", "Asiakas", user_ids["admin"])
    )
    client_id = cursor.fetchone()[0]

    trip_id = add_trip(user_ids["worker"], client_id, "Koti", "Kauppa")
    inactive_id = user_ids["inactive"]
    missing_id = user_ids["admin"] + user_ids["worker"] + 1000

    with pytest.raises(PermissionError):
        add_trip(inactive_id, client_id, "Koti", "Apteekki")

    with pytest.raises(ValueError, match="User not found"):
        update_trip(missing_id, trip_id, {"destination": "Apteekki"})

    with pytest.raises(PermissionError):
        delete_trip(inactive_id, trip_id)

    # Nothing was saved, and the trip was not deleted
    cursor.execute("SELECT id, destination, updated_by_user_id FROM trips")

    assert cursor.fetchall() == [(trip_id, "Kauppa", None)]
