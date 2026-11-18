from decimal import Decimal

from carelog.database.migrations import v007_expenses, v011_add_expense_description
from tests.migration_helpers import get_columns


def test_table_structure(cursor_with_visits):
    cursor = cursor_with_visits
    v007_expenses.upgrade(cursor)
    v011_add_expense_description.upgrade(cursor)

    assert ("description", "varchar(255)", "YES", None) in get_columns(cursor, "expenses")


def test_upgrade_preserves_existing_row(cursor_with_visits):
    cursor = cursor_with_visits
    v007_expenses.upgrade(cursor)
    cursor.execute(
        "INSERT INTO expenses (expense_date, amount, category) "
        "VALUES ('2026-01-01', 12.50, 'company')"
    )
    expense_id = cursor.lastrowid

    v011_add_expense_description.upgrade(cursor)

    cursor.execute("SELECT amount, description FROM expenses WHERE id = %s", (expense_id,))
    assert cursor.fetchone() == (Decimal("12.50"), None)


def test_description_can_be_stored(cursor_with_visits):
    cursor = cursor_with_visits
    v007_expenses.upgrade(cursor)
    v011_add_expense_description.upgrade(cursor)
    description = "Test purchase"
    cursor.execute(
        "INSERT INTO expenses (expense_date, amount, category, description) "
        "VALUES ('2026-01-01', 12.50, 'company', %s)",
        (description,),
    )
    expense_id = cursor.lastrowid

    v011_add_expense_description.upgrade(cursor)

    cursor.execute("SELECT description FROM expenses WHERE id = %s", (expense_id,))
    assert cursor.fetchone() == (description,)
