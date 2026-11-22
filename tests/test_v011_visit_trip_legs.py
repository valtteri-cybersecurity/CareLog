from pymysql.constants import ER

from carelog.database.migrations import v011_visit_trip_legs
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    insert_visit,
    table_exists,
)


def test_upgrade_creates_table(cursor_with_visit_scheduling):
    cursor = cursor_with_visit_scheduling
    assert not table_exists(cursor, "visit_trip_legs")
    v011_visit_trip_legs.upgrade(cursor)
    assert table_exists(cursor, "visit_trip_legs")


def test_table_structure(cursor_with_visit_scheduling):
    cursor = cursor_with_visit_scheduling
    v011_visit_trip_legs.upgrade(cursor)

    assert get_columns(cursor, "visit_trip_legs") == (
        ("id", "int", "NO", None),
        ("visit_id", "int", "NO", None),
        ("position", "int", "NO", None),
        ("start_location", "varchar(255)", "NO", None),
        ("destination", "varchar(255)", "NO", None),
        ("distance_km", "decimal(10,2)", "YES", None),
    )

    assert get_primary_key(cursor, "visit_trip_legs") == ["id"]


def test_table_constraints(cursor_with_visit_scheduling):
    cursor = cursor_with_visit_scheduling
    v011_visit_trip_legs.upgrade(cursor)

    visit_id = insert_visit(cursor)

    insert_sql = (
        "INSERT INTO visit_trip_legs "
        "(visit_id, position, start_location, destination, distance_km) "
        "VALUES (%s, %s, 'Koti', 'Kauppa', %s)"
    )

    # Valid values: a known distance, an unknown distance and the
    # largest DECIMAL(10,2) value
    cursor.execute(insert_sql, (visit_id, 1, "3.20"))
    cursor.execute(insert_sql, (visit_id, 2, None))
    cursor.execute(insert_sql, (visit_id, 3, "99999999.99"))

    cursor.execute(
        "SELECT distance_km FROM visit_trip_legs "
        "WHERE visit_id = %s ORDER BY position",
        (visit_id,)
    )

    rows = cursor.fetchall()

    assert str(rows[0][0]) == "3.20"
    assert rows[1][0] is None
    assert str(rows[2][0]) == "99999999.99"

    # The visit must exist
    assert_mysql_error(
        cursor, ER.NO_REFERENCED_ROW_2,
        insert_sql, (visit_id + 1, 1, "1.00"),
    )

    # Two legs of the same visit cannot share a position
    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        insert_sql, (visit_id, 1, "1.00"),
    )

    # CHECK constraints: position > 0 and distance_km >= 0
    assert_mysql_error(cursor, 3819, insert_sql, (visit_id, 0, "1.00"))
    assert_mysql_error(cursor, 3819, insert_sql, (visit_id, 4, "-1.00"))

    # Too large for DECIMAL(10,2) in strict mode
    assert_mysql_error(
        cursor, ER.WARN_DATA_OUT_OF_RANGE,
        insert_sql, (visit_id, 4, "100000000.00"),
    )

    # The history is protected: a visit with legs cannot be deleted
    assert_mysql_error(
        cursor, ER.ROW_IS_REFERENCED_2,
        "DELETE FROM visits WHERE id = %s",
        (visit_id,),
    )
