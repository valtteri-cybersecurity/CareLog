from pymysql.constants import ER

from carelog.database.migrations import v005_visits
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    insert_client,
    insert_service,
    table_exists,
)


def test_upgrade_creates_table(cursor_with_clients_and_services):
    cursor = cursor_with_clients_and_services
    assert not table_exists(cursor, "visits")
    v005_visits.upgrade(cursor)
    assert table_exists(cursor, "visits")


def test_table_structure(cursor_with_clients_and_services):
    cursor = cursor_with_clients_and_services
    v005_visits.upgrade(cursor)

    assert get_columns(cursor, "visits") == (
        ("id", "int", "NO", None),
        ("client_id", "int", "NO", None),
        ("service_id", "int", "NO", None),
        ("status", "varchar(20)", "NO", "planned"),
        ("priority", "tinyint", "NO", "2"),
        ("planned_week", "date", "YES", None),
        ("planned_at", "datetime", "YES", None),
        ("started_at", "datetime", "YES", None),
        ("ended_at", "datetime", "YES", None),
        ("description", "text", "YES", None),
        ("distance_km", "decimal(10,2)", "YES", None),
        ("price", "decimal(10,2)", "YES", None),
        ("created_at", "datetime", "NO", "CURRENT_TIMESTAMP"),
        ("updated_at", "datetime", "NO", "CURRENT_TIMESTAMP"),
    )


def test_table_constraints(cursor_with_clients_and_services):
    cursor = cursor_with_clients_and_services
    v005_visits.upgrade(cursor)
    assert get_primary_key(cursor, "visits") == ["id"]

    client_id = insert_client(cursor)
    service_id = insert_service(cursor)
    insert_sql = "INSERT INTO visits (client_id, service_id) VALUES (%s, %s)"
    cursor.execute(insert_sql, (client_id, service_id))
    visit_id = cursor.lastrowid
    assert visit_id > 0

    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO visits (id, client_id, service_id) VALUES (%s, %s, %s)",
        (visit_id, client_id, service_id),
    )
    assert_mysql_error(
        cursor, ER.NO_REFERENCED_ROW_2, insert_sql, (client_id + 1, service_id),
    )
    assert_mysql_error(
        cursor, ER.NO_REFERENCED_ROW_2, insert_sql, (client_id, service_id + 1),
    )
    assert_mysql_error(
        cursor, ER.ROW_IS_REFERENCED_2,
        "DELETE FROM clients WHERE id = %s",
        (client_id,),
    )
    assert_mysql_error(
        cursor, ER.ROW_IS_REFERENCED_2,
        "DELETE FROM services WHERE id = %s",
        (service_id,),
    )
