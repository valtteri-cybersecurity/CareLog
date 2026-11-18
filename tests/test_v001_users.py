from pymysql.constants import ER

from carelog.database.migrations import v001_users
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    table_exists,
)


def test_upgrade_creates_table(cursor):
    assert not table_exists(cursor, "users")
    v001_users.upgrade(cursor)
    assert table_exists(cursor, "users")


def test_table_structure(cursor):
    v001_users.upgrade(cursor)

    assert get_columns(cursor, "users") == (
        ("id", "int", "NO", None),
        ("email", "varchar(254)", "NO", None),
        ("display_name", "varchar(150)", "NO", None),
        ("password_hash", "varchar(255)", "NO", None),
        ("role", "enum('admin','worker')", "NO", "worker"),
        ("is_active", "tinyint(1)", "NO", "1"),
        ("created_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
        ("updated_at", "timestamp", "NO", "CURRENT_TIMESTAMP"),
    )


def test_table_constraints(cursor):
    v001_users.upgrade(cursor)
    assert get_primary_key(cursor, "users") == ["id"]

    cursor.execute(
        "INSERT INTO users (email, display_name, password_hash) "
        "VALUES ('worker@example.com', 'Worker', 'test-hash')"
    )
    user_id = cursor.lastrowid
    assert user_id > 0

    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO users (id, email, display_name, password_hash) "
        "VALUES (%s, 'other@example.com', 'Other', 'test-hash')",
        (user_id,),
    )
    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO users (email, display_name, password_hash) "
        "VALUES ('worker@example.com', 'Other', 'test-hash')",
    )
    assert_mysql_error(
        cursor, ER.WARN_DATA_TRUNCATED,
        "INSERT INTO users (email, display_name, password_hash, role) "
        "VALUES ('other@example.com', 'Other', 'test-hash', 'unknown')",
    )
