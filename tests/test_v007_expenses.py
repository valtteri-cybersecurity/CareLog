from pymysql.constants import ER

from carelog.database.migrations import v007_expenses
from tests.migration_helpers import (
    assert_mysql_error,
    get_columns,
    get_primary_key,
    insert_visit,
    table_exists,
)


def test_upgrade_creates_table(cursor_with_visits):
    cursor = cursor_with_visits
    assert not table_exists(cursor, "expenses")
    v007_expenses.upgrade(cursor)
    assert table_exists(cursor, "expenses")


def test_table_structure(cursor_with_visits):
    cursor = cursor_with_visits
    v007_expenses.upgrade(cursor)

    assert get_columns(cursor, "expenses") == (
        ("id", "int", "NO", None),
        ("visit_id", "int", "YES", None),
        ("expense_date", "date", "NO", None),
        ("amount", "decimal(10,2)", "NO", None),
        ("category", "varchar(20)", "NO", None),
        ("description", "varchar(255)", "YES", None),
    )


def test_table_constraints(cursor_with_visits):
    cursor = cursor_with_visits
    v007_expenses.upgrade(cursor)
    assert get_primary_key(cursor, "expenses") == ["id"]

    visit_id = insert_visit(cursor)

    insert_sql = (
        "INSERT INTO expenses (visit_id, expense_date, amount, category) "
        "VALUES (%s, '2026-01-01', 12.50, 'customer')"
    )

    cursor.execute(insert_sql, (visit_id,))
    expense_id = cursor.lastrowid
    assert expense_id > 0

    assert_mysql_error(
        cursor, ER.DUP_ENTRY,
        "INSERT INTO expenses (id, visit_id, expense_date, amount, category) "
        "VALUES (%s, %s, '2026-01-01', 12.50, 'customer')",
        (expense_id, visit_id),
    )

    assert_mysql_error(
        cursor, ER.NO_REFERENCED_ROW_2,
        insert_sql,
        (visit_id + 1,),
    )

    assert_mysql_error(
        cursor, ER.ROW_IS_REFERENCED_2,
        "DELETE FROM visits WHERE id = %s",
        (visit_id,),
    )

    cursor.execute(
        "INSERT INTO expenses (expense_date, amount, category) "
        "VALUES ('2026-01-01', 12.50, 'company')"
    )

    cursor.execute(
        "SELECT visit_id FROM expenses WHERE id = %s",
        (cursor.lastrowid,),
    )

    assert cursor.fetchone() == (None,)

