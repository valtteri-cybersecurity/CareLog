from pymysql.constants import ER

from carelog.database.migrations import v003_services
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    insert_service,
    table_exists,
)


def test_upgrade_creates_table(cursor):
    assert not table_exists(cursor, "services")
    v003_services.upgrade(cursor)
    assert table_exists(cursor, "services")


def test_table_structure(cursor):
    v003_services.upgrade(cursor)

    assert get_columns(cursor, "services") == (
        ("id", "int", "NO", None),
        ("name", "varchar(150)", "NO", None),
    )


def test_table_constraints(cursor):
    v003_services.upgrade(cursor)
    assert get_primary_key(cursor, "services") == ["id"]

    service_id = insert_service(cursor)
    assert service_id > 0

    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO services (id, name) VALUES (%s, 'Other service')",
        (service_id,),
    )
    assert_mysql_error(
        cursor, ER.BAD_NULL_ERROR,
        "INSERT INTO services (name) VALUES (NULL)",
    )
