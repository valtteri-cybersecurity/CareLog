from pymysql.constants import ER

from carelog.database.migrations import v004_trips
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    insert_client,
    table_exists,
)


def test_upgrade_creates_table(cursor_with_clients):
    cursor = cursor_with_clients
    assert not table_exists(cursor, "trips")
    v004_trips.upgrade(cursor)
    assert table_exists(cursor, "trips")


def test_table_structure(cursor_with_clients):
    cursor = cursor_with_clients
    v004_trips.upgrade(cursor)

    assert get_columns(cursor, "trips") == (
        ("id", "int", "NO", None),
        ("client_id", "int", "NO", None),
        ("start_location", "varchar(255)", "NO", None),
        ("destination", "varchar(255)", "NO", None),
        ("distance_km", "decimal(10,2)", "YES", None),
    )


def test_table_constraints(cursor_with_clients):
    cursor = cursor_with_clients
    v004_trips.upgrade(cursor)
    assert get_primary_key(cursor, "trips") == ["id"]

    client_id = insert_client(cursor)

    cursor.execute(
        "INSERT INTO trips (client_id, start_location, destination) "
        "VALUES (%s, 'Home', 'Shop')",
        (client_id,),
    )

    trip_id = cursor.lastrowid
    assert trip_id > 0

    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO trips (id, client_id, start_location, destination) "
        "VALUES (%s, %s, 'Home', 'Pharmacy')",
        (trip_id, client_id),
    )

    assert_mysql_error(
        cursor, ER.NO_REFERENCED_ROW_2,
        "INSERT INTO trips (client_id, start_location, destination) "
        "VALUES (%s, 'Home', 'Shop')",
        (client_id + 1,),
    )

    cursor.execute(
        "DELETE FROM clients WHERE id = %s",
        (client_id,),
    )

    cursor.execute(
        "SELECT id FROM trips WHERE id = %s",
        (trip_id,),
    )

    assert cursor.fetchone() is None

