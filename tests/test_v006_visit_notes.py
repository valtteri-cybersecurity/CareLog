from pymysql.constants import ER

from carelog.database.migrations import v006_visit_notes
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    insert_visit,
    table_exists,
)


def test_upgrade_creates_table(cursor_with_visits):
    cursor = cursor_with_visits
    assert not table_exists(cursor, "visit_notes")
    v006_visit_notes.upgrade(cursor)
    assert table_exists(cursor, "visit_notes")


def test_table_structure(cursor_with_visits):
    cursor = cursor_with_visits
    v006_visit_notes.upgrade(cursor)

    assert get_columns(cursor, "visit_notes") == (
        ("id", "int", "NO", None),
        ("visit_id", "int", "NO", None),
        ("content", "text", "NO", None),
        ("created_at", "datetime", "NO", "CURRENT_TIMESTAMP"),
    )


def test_table_constraints(cursor_with_visits):
    cursor = cursor_with_visits
    v006_visit_notes.upgrade(cursor)
    assert get_primary_key(cursor, "visit_notes") == ["id"]

    visit_id = insert_visit(cursor)
    insert_sql = "INSERT INTO visit_notes (visit_id, content) VALUES (%s, 'Test note')"
    cursor.execute(insert_sql, (visit_id,))
    note_id = cursor.lastrowid
    assert note_id > 0

    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO visit_notes (id, visit_id, content) VALUES (%s, %s, 'Other note')",
        (note_id, visit_id),
    )
    assert_mysql_error(cursor, ER.NO_REFERENCED_ROW_2, insert_sql, (visit_id + 1,))
    assert_mysql_error(
        cursor, ER.ROW_IS_REFERENCED_2,
        "DELETE FROM visits WHERE id = %s",
        (visit_id,),
    )
