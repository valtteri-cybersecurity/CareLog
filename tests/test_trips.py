from decimal import Decimal

import pymysql
import pytest

from carelog.services.trips import (
    add_trip,
    delete_trip,
    get_trip,
    get_trips,
    update_trip,
)


# ADD TRIP TESTS


def test_add_trip_rejects_invalid_client_id():
    for client_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            add_trip(client_id, "Koti", "Kauppa")


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
            add_trip(1, start_location, destination)


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
            add_trip(1, "Koti", "Kauppa", distance_km)


def test_add_trip_saves_to_database(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    trip_id = add_trip(
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
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    trip_without_distance = add_trip(client_id, "Koti", "Apteekki")
    trip_with_zero_distance = add_trip(client_id, "Koti", "Naapuri", 0)

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
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    # The foreign key must reject a client that does not exist
    with pytest.raises(pymysql.err.IntegrityError):
        add_trip(999999, "Koti", "Kauppa")

    cursor.execute("SELECT COUNT(*) FROM trips")

    assert cursor.fetchone()[0] == 0


def test_add_trip_rolls_back_on_error(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    def insert_then_fail(
        cursor,
        client_id,
        start_location,
        destination,
        distance_km
    ):
        cursor.execute(
            """
            INSERT INTO trips (client_id, start_location, destination)
            VALUES (%s, %s, %s)
            """,
            (client_id, start_location, destination)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.insert_trip",
        insert_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_trip(client_id, "Koti", "Kauppa")

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

    def insert_then_fail(
        cursor,
        client_id,
        start_location,
        destination,
        distance_km
    ):
        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.insert_trip",
        insert_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_trip(1, "Koti", "Kauppa")

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
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, distance_km)
        VALUES (%s, %s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa", Decimal("12.50"))
    )

    trip_id = cursor.lastrowid

    trip = get_trip(trip_id)

    assert trip == {
        "id": trip_id,
        "client_id": client_id,
        "start_location": "Koti",
        "destination": "Kauppa",
        "distance_km": Decimal("12.50"),
    }


def test_get_trip_returns_none_if_not_found(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
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
        "carelog.services.trips.get_connection",
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
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    trips = get_trips(client_id)

    assert trips == []


def test_get_trips_returns_sorted_trips(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    trip_rows = (
        ("Koti", "Kauppa", Decimal("12.50")),
        ("Asiakas", "Apteekki", None),
        ("Koti", "Apteekki", Decimal("8.00")),
    )

    for start_location, destination, distance_km in trip_rows:
        cursor.execute(
            """
            INSERT INTO trips (client_id, start_location, destination, distance_km)
            VALUES (%s, %s, %s, %s)
            """,
            (client_id, start_location, destination, distance_km)
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
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Toinen", "Asiakas")
    )

    other_client_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination)
        VALUES (%s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa")
    )

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination)
        VALUES (%s, %s, %s)
        """,
        (other_client_id, "Koti", "Kirjasto")
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
        "carelog.services.trips.get_connection",
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
            update_trip(trip_id, {"destination": "Kauppa"})


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
            update_trip(1, changes)


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
            update_trip(1, changes)


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
            update_trip(1, {"distance_km": distance_km})


def test_update_trip_changes_locations(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination, distance_km)
        VALUES (%s, %s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa", Decimal("12.50"))
    )

    trip_id = cursor.lastrowid

    updated = update_trip(
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
    assert update_trip(trip_id, {"destination": "Apteekki"}) is True


def test_update_trip_changes_and_clears_distance(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination)
        VALUES (%s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa")
    )

    trip_id = cursor.lastrowid

    assert update_trip(trip_id, {"distance_km": 7.25}) is True

    cursor.execute(
        "SELECT distance_km FROM trips WHERE id = %s",
        (trip_id,)
    )

    assert cursor.fetchone()[0] == Decimal("7.25")

    assert update_trip(trip_id, {"distance_km": None}) is True

    cursor.execute(
        "SELECT distance_km FROM trips WHERE id = %s",
        (trip_id,)
    )

    assert cursor.fetchone()[0] is None


def test_update_trip_returns_false_if_not_found(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    updated = update_trip(
        999999,
        {"destination": "Kauppa"}
    )

    assert updated is False


def test_update_trip_rolls_back_on_error(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    def update_then_fail(cursor, trip_id, changes):
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
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.update_trip_record",
        update_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination)
        VALUES (%s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa")
    )

    trip_id = cursor.lastrowid

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_trip(trip_id, {"destination": "Apteekki"})

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

    def update_then_fail(cursor, trip_id, changes):
        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.update_trip_record",
        update_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_trip(1, {"destination": "Kauppa"})

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# DELETE TRIP TESTS


def test_delete_trip_rejects_invalid_id():
    for trip_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            delete_trip(trip_id)


def test_delete_trip_removes_only_given_trip(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination)
        VALUES (%s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa")
    )

    trip_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination)
        VALUES (%s, %s, %s)
        """,
        (client_id, "Koti", "Apteekki")
    )

    other_trip_id = cursor.lastrowid

    deleted = delete_trip(trip_id)

    assert deleted is True

    cursor.execute("SELECT id FROM trips")

    # Only the other trip is left
    assert cursor.fetchall() == ((other_trip_id,),)

    cursor.execute(
        "SELECT COUNT(*) FROM clients WHERE id = %s",
        (client_id,)
    )

    # Deleting a trip must not delete the client
    assert cursor.fetchone()[0] == 1


def test_delete_trip_returns_false_if_not_found(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    deleted = delete_trip(999999)

    assert deleted is False


def test_delete_trip_rolls_back_on_error(
    cursor_with_trips,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_trips

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    def delete_then_fail(cursor, trip_id):
        cursor.execute(
            "DELETE FROM trips WHERE id = %s",
            (trip_id,)
        )

        raise RuntimeError("Simulated delete failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.delete_trip_record",
        delete_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Testi", "Asiakas")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        """
        INSERT INTO trips (client_id, start_location, destination)
        VALUES (%s, %s, %s)
        """,
        (client_id, "Koti", "Kauppa")
    )

    trip_id = cursor.lastrowid

    with pytest.raises(RuntimeError, match="Simulated delete failure"):
        delete_trip(trip_id)

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

    def delete_then_fail(cursor, trip_id):
        raise RuntimeError("Simulated delete failure")

    monkeypatch.setattr(
        "carelog.services.trips.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.trips.delete_trip_record",
        delete_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated delete failure"):
        delete_trip(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True
