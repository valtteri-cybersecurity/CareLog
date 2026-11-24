from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from carelog.services.expenses import (
    add_expense,
    get_expense,
    get_expenses,
    get_visit_expenses,
    update_expense,
    validate_amount,
)
from carelog.services.visits import get_visit
from tests.postgres_helpers import (
    fake_active_user,
    insert_visit,
    start_in_thread,
    wait_until_waiting_for_lock,
)


HELSINKI = ZoneInfo("Europe/Helsinki")


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # Unit tests must never reach a real database. If validation breaks
    # and the code tries to connect, the test fails clearly. Tests that
    # need PostgreSQL replace get_postgres_connection with the isolated test database.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a unit test")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        connection_not_allowed
    )


# VALIDATE AMOUNT TESTS


def test_validate_amount_accepts_valid_amounts():
    assert validate_amount(35.80) == Decimal("35.80")
    assert validate_amount(Decimal("35.80")) == Decimal("35.80")
    assert validate_amount(12) == Decimal("12")
    assert validate_amount(Decimal("0.01")) == Decimal("0.01")
    assert validate_amount(Decimal("99999999.99")) == Decimal("99999999.99")


# ADD EXPENSE TESTS


def test_add_expense_rejects_invalid_amount():
    invalid_amounts = (
        None,
        0,
        Decimal("0.00"),
        -10,
        True,
        "35.80",
        float("nan"),
        float("inf"),
        Decimal("NaN"),
        Decimal("35.805"),
        Decimal("100000000.00"),
    )

    for amount in invalid_amounts:
        with pytest.raises(ValueError):
            add_expense(1, date(2026, 11, 18), amount, "company")


def test_add_expense_rejects_invalid_date():
    tomorrow = datetime.now(HELSINKI).date() + timedelta(days=1)

    invalid_dates = (
        None,
        datetime(2026, 11, 18, 10, 0),
        "2026-11-18",
        20261118,
        tomorrow,
    )

    for expense_date in invalid_dates:
        with pytest.raises(ValueError):
            add_expense(1, expense_date, Decimal("35.80"), "company")


def test_add_expense_rejects_invalid_category_and_description():
    invalid_values = (
        {"category": None},
        {"category": ""},
        {"category": "   "},
        {"category": 123},
        {"category": "Customer"},
        {"category": "groceries"},
        {"category": "company", "description": 123},
        {"category": "company", "description": "a" * 256},
    )

    for values in invalid_values:
        with pytest.raises(ValueError):
            add_expense(1, date(2026, 11, 18), Decimal("35.80"), **values)


def test_add_expense_rejects_invalid_visit_id():
    for visit_id in ("1", True, 0, -1, 1.0):
        with pytest.raises(ValueError):
            add_expense(
                1,
                date(2026, 11, 18),
                Decimal("35.80"),
                "company",
                visit_id=visit_id
            )

    # A customer expense is linked to the client only through a visit
    with pytest.raises(ValueError, match="requires a visit"):
        add_expense(1, date(2026, 11, 18), Decimal("35.80"), "customer")


def test_add_expense_saves_customer_expense(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, completed_date, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "completed", date(2026, 11, 18), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    expense_id = add_expense(
        user_ids["worker"],
        date(2026, 11, 18),
        35.80,
        "  customer  ",
        visit_id=visit_id,
        description="  Ruokaostokset, Lähikauppa  "
    )

    cursor.execute(
        """
        SELECT visit_id, expense_date, amount, category, description
        FROM expenses
        WHERE id = %s
        """,
        (expense_id,)
    )

    assert cursor.fetchone() == (
        visit_id,
        date(2026, 11, 18),
        Decimal("35.80"),
        "customer",
        "Ruokaostokset, Lähikauppa",
    )


def test_add_expense_saves_company_expenses(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    # Expenses can be added to a visit in any status, here a cancelled one
    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    # A general business cost without a visit and an empty description
    general_id = add_expense(
        user_ids["worker"],
        date(2026, 11, 17),
        Decimal("12.50"),
        "company",
        description="   "
    )

    # Two costs for the same visit
    first_id = add_expense(
        user_ids["worker"],
        date(2026, 11, 18),
        Decimal("3.00"),
        "company",
        visit_id=visit_id,
        description="Pysäköinti"
    )

    second_id = add_expense(
        user_ids["worker"],
        date(2026, 11, 18),
        Decimal("3.00"),
        "company",
        visit_id=visit_id,
        description="Pysäköinti"
    )

    cursor.execute(
        """
        SELECT id, visit_id, amount, category, description
        FROM expenses
        ORDER BY id
        """
    )

    assert cursor.fetchall() == [
        (general_id, None, Decimal("12.50"), "company", None),
        (first_id, visit_id, Decimal("3.00"), "company", "Pysäköinti"),
        (second_id, visit_id, Decimal("3.00"), "company", "Pysäköinti"),
    ]

    cursor.execute("SELECT status FROM visits WHERE id = %s", (visit_id,))

    # The visit itself is not changed
    assert cursor.fetchone()[0] == "cancelled"


def test_add_expense_rejects_missing_visit(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    # A visit that does not exist is rejected before the insert
    with pytest.raises(ValueError, match="Visit not found"):
        add_expense(
            user_ids["worker"],
            date(2026, 11, 18),
            Decimal("35.80"),
            "customer",
            visit_id=999999
        )

    cursor.execute("SELECT COUNT(*) FROM expenses")

    assert cursor.fetchone()[0] == 0


def test_add_expense_rolls_back_on_error(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(
        cursor,
        user_id,
        created_by_user_id,
        expense_date,
        amount,
        category,
        visit_id,
        description
    ):
        cursor.execute(
            """
            INSERT INTO expenses (expense_date, amount, category, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (expense_date, amount, category, user_id, created_by_user_id)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.expenses.insert_expense",
        insert_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_expense(user_ids["worker"], date(2026, 11, 18), Decimal("12.50"), "company")

    cursor.execute("SELECT COUNT(*) FROM expenses")

    assert cursor.fetchone()[0] == 0


def test_add_expense_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.expenses.get_active_user", fake_active_user)


    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False
            self.rolled_back = False

        def cursor(self):
            return self.test_cursor

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def insert_then_fail(
        cursor,
        user_id,
        created_by_user_id,
        expense_date,
        amount,
        category,
        visit_id,
        description
    ):
        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.expenses.insert_expense",
        insert_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_expense(1, date(2026, 11, 18), Decimal("12.50"), "company")

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET EXPENSE TESTS


def test_get_expense_rejects_invalid_id():
    for expense_id in ("1", None, True, 0, -1, 1.0):
        with pytest.raises(ValueError):
            get_expense(1, expense_id)


def test_get_expense_returns_visit_expense(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, completed_date, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "completed", date(2026, 11, 18), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    expense_id = add_expense(
        user_ids["worker"],
        date(2026, 11, 18),
        Decimal("35.80"),
        "customer",
        visit_id=visit_id,
        description="Ruokaostokset"
    )

    expense = get_expense(user_ids["worker"], expense_id)

    # updated_at is set by the database
    assert expense.pop("updated_at") is not None

    # All columns are returned with their original types
    assert expense == {
        "id": expense_id,
        "visit_id": visit_id,
        "expense_date": date(2026, 11, 18),
        "amount": Decimal("35.80"),
        "category": "customer",
        "description": "Ruokaostokset",
        "user_id": user_ids["worker"],
        "created_by_user_id": user_ids["worker"],
        "updated_by_user_id": None,
    }

    assert type(expense["expense_date"]) is date
    assert isinstance(expense["amount"], Decimal)


def test_get_expense_returns_expense_without_visit(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    expense_id = add_expense(user_ids["worker"], date(2026, 11, 17), Decimal("12.50"), "company")

    expense = get_expense(user_ids["worker"], expense_id)

    assert expense["visit_id"] is None
    assert expense["description"] is None
    assert expense["amount"] == Decimal("12.50")
    assert expense["category"] == "company"


def test_get_expense_returns_none_if_not_found(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    expense = get_expense(user_ids["worker"], 999999)

    assert expense is None


def test_get_expense_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.expenses.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, expense_id, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.expenses.select_expense",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_expense(1, 1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET VISIT EXPENSES TESTS


def test_get_visit_expenses_rejects_invalid_visit_id():
    for visit_id in ("1", None, True, 0, -1, 1.0):
        with pytest.raises(ValueError):
            get_visit_expenses(1, visit_id)


def test_get_visit_expenses_returns_empty_list(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    # A general expense without a visit is not a visit expense
    add_expense(user_ids["worker"], date(2026, 11, 17), Decimal("12.50"), "company")

    # A visit without expenses, and a visit that does not exist
    assert get_visit_expenses(user_ids["worker"], visit_id) == []
    assert get_visit_expenses(user_ids["worker"], 999999) == []


def test_get_visit_expenses_returns_only_this_visit_in_order(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, completed_date, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "completed", date(2026, 11, 18), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16), user_ids["worker"], user_ids["worker"])
    )

    cancelled_visit_id = cursor.fetchone()[0]

    # Inserted in mixed order. Two expenses are on the same day,
    # so their order comes from the id.
    expense_rows = (
        (visit_id, date(2026, 11, 18), Decimal("4.20"), "customer", "Apteekki"),
        (visit_id, date(2026, 11, 17), Decimal("35.80"), "customer", "Ruokaostokset"),
        (visit_id, date(2026, 11, 18), Decimal("3.00"), "company", None),
        (cancelled_visit_id, date(2026, 11, 16), Decimal("9.90"), "customer", "Peruttu"),
        (None, date(2026, 11, 18), Decimal("12.50"), "company", "Yleinen"),
    )

    for expense_visit_id, expense_date, amount, category, description in expense_rows:
        cursor.execute(
            """
            INSERT INTO expenses (
                visit_id, expense_date, amount, category, description, user_id, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (expense_visit_id, expense_date, amount, category, description, user_ids["worker"], user_ids["worker"])
        )

    # The client is archived later; the history stays available
    cursor.execute(
        "UPDATE clients SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = %s",
        (client_id,)
    )

    expenses = get_visit_expenses(user_ids["worker"], visit_id)

    descriptions = []

    for expense in expenses:
        descriptions.append(expense["description"])

    # Only this visit's expenses, oldest first, then by id
    assert descriptions == ["Ruokaostokset", "Apteekki", None]

    assert expenses[0].pop("updated_at") is not None
    assert expenses[0] == {
        "id": expenses[0]["id"],
        "visit_id": visit_id,
        "expense_date": date(2026, 11, 17),
        "amount": Decimal("35.80"),
        "category": "customer",
        "description": "Ruokaostokset",
        "user_id": user_ids["worker"],
        "created_by_user_id": user_ids["worker"],
        "updated_by_user_id": None,
    }

    assert isinstance(expenses[2]["amount"], Decimal)
    assert expenses[1]["id"] < expenses[2]["id"]

    # A cancelled visit's expenses can be read too
    cancelled_expenses = get_visit_expenses(user_ids["worker"], cancelled_visit_id)

    assert len(cancelled_expenses) == 1
    assert cancelled_expenses[0]["amount"] == Decimal("9.90")


def test_get_visit_expenses_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.expenses.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, visit_id, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.expenses.select_visit_expenses",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_visit_expenses(1, 1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET EXPENSES TESTS


def test_get_expenses_rejects_invalid_filters():
    invalid_filters = (
        {"start_date": datetime(2026, 11, 1, 0, 0)},
        {"start_date": "2026-11-01"},
        {"end_date": 20261130},
        {"end_date": datetime(2026, 11, 30, 0, 0)},
        # The start is after the end
        {"start_date": date(2026, 12, 1), "end_date": date(2026, 11, 30)},
        {"category": ""},
        {"category": "groceries"},
        {"category": 123},
        {"client_id": True},
        {"client_id": 0},
        {"client_id": -1},
        {"client_id": "1"},
    )

    for filters in invalid_filters:
        with pytest.raises(ValueError):
            get_expenses(1, **filters)


def test_get_expenses_returns_empty_list(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    assert get_expenses(user_ids["worker"]) == []


def test_get_expenses_filters_by_date(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    # Inserted in mixed order. The description is used as a label.
    expense_rows = (
        (date(2026, 11, 30), "30.11."),
        (date(2026, 10, 31), "31.10."),
        (date(2026, 11, 15), "15.11. a"),
        (date(2026, 12, 1), "1.12."),
        (date(2026, 11, 1), "1.11."),
        (date(2026, 11, 15), "15.11. b"),
    )

    for expense_date, label in expense_rows:
        cursor.execute(
            """
            INSERT INTO expenses (expense_date, amount, category, description, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (expense_date, Decimal("10.00"), "company", label, user_ids["worker"], user_ids["worker"])
        )

    def labels_of(expenses):
        labels = []

        for expense in expenses:
            labels.append(expense["description"])

        return labels

    # Without filters: all expenses, oldest first, same day by id
    assert labels_of(get_expenses(user_ids["worker"])) == [
        "31.10.", "1.11.", "15.11. a", "15.11. b", "30.11.", "1.12."
    ]

    assert labels_of(get_expenses(user_ids["worker"], start_date=date(2026, 11, 1))) == [
        "1.11.", "15.11. a", "15.11. b", "30.11.", "1.12."
    ]

    assert labels_of(get_expenses(user_ids["worker"], end_date=date(2026, 11, 30))) == [
        "31.10.", "1.11.", "15.11. a", "15.11. b", "30.11."
    ]

    # Both limit days are included
    november = get_expenses(
        user_ids["worker"],
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30)
    )

    assert labels_of(november) == ["1.11.", "15.11. a", "15.11. b", "30.11."]

    one_day = get_expenses(
        user_ids["worker"],
        start_date=date(2026, 11, 15),
        end_date=date(2026, 11, 15)
    )

    assert labels_of(one_day) == ["15.11. a", "15.11. b"]

    assert set(november[0]) == {
        "id", "visit_id", "expense_date", "amount", "category", "description",
        "user_id", "created_by_user_id", "updated_by_user_id", "updated_at",
    }
    assert november[0]["amount"] == Decimal("10.00")


def test_get_expenses_filters_by_category_and_client(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    client_ids = []

    for first_name in ("Hilma", "Aino", "Kalle"):
        cursor.execute(
            "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
            (first_name, "Testi", user_ids["worker"])
        )

        client_ids.append(cursor.fetchone()[0])

    hilma_id = client_ids[0]
    aino_id = client_ids[1]
    client_without_expenses_id = client_ids[2]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    visit_ids = []

    for visit_client_id in (hilma_id, hilma_id, aino_id):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, status, completed_date, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (visit_client_id, service_id, "completed", date(2026, 11, 5), user_ids["worker"], user_ids["worker"])
        )

        visit_ids.append(cursor.fetchone()[0])

    expense_rows = (
        (visit_ids[0], date(2026, 11, 5), "customer", "Hilma ostokset"),
        (visit_ids[1], date(2026, 11, 10), "company", "Hilma pysäköinti"),
        (visit_ids[1], date(2026, 12, 2), "customer", "Hilma joulukuu"),
        (visit_ids[2], date(2026, 11, 6), "customer", "Aino ostokset"),
        (None, date(2026, 11, 7), "company", "Yleinen"),
    )

    for visit_id, expense_date, category, label in expense_rows:
        cursor.execute(
            """
            INSERT INTO expenses (
                visit_id, expense_date, amount, category, description, user_id, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (visit_id, expense_date, Decimal("10.00"), category, label, user_ids["worker"], user_ids["worker"])
        )

    def labels_of(expenses):
        labels = []

        for expense in expenses:
            labels.append(expense["description"])

        return labels

    assert labels_of(get_expenses(user_ids["worker"], category="customer")) == [
        "Hilma ostokset", "Aino ostokset", "Hilma joulukuu"
    ]

    assert labels_of(get_expenses(user_ids["worker"], category=" company ")) == [
        "Yleinen", "Hilma pysäköinti"
    ]

    # Only the client's own visits; general expenses and other clients
    # are left out
    assert labels_of(get_expenses(user_ids["worker"], client_id=hilma_id)) == [
        "Hilma ostokset", "Hilma pysäköinti", "Hilma joulukuu"
    ]

    # All given filters must match
    hilma_november_purchases = get_expenses(
        user_ids["worker"],
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        category="customer",
        client_id=hilma_id
    )

    assert labels_of(hilma_november_purchases) == ["Hilma ostokset"]

    assert get_expenses(user_ids["worker"], client_id=client_without_expenses_id) == []


def test_get_expenses_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.expenses.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, start_date, end_date, category, client_id, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.expenses.select_expenses",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_expenses(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# UPDATE EXPENSE TESTS


def test_update_expense_rejects_invalid_id():
    for expense_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            update_expense(1, expense_id, {"amount": Decimal("10.00")})


def test_update_expense_rejects_invalid_changes():
    tomorrow = datetime.now(HELSINKI).date() + timedelta(days=1)

    invalid_changes = (
        None,
        [],
        {},
        # Fields that cannot be changed
        {"id": 5},
        {"client_id": 2},
        # Invalid values follow the same rules as in add_expense()
        {"amount": 0},
        {"amount": True},
        {"amount": Decimal("10.005")},
        {"amount": float("nan")},
        {"expense_date": datetime(2026, 11, 18, 10, 0)},
        {"expense_date": tomorrow},
        {"category": "groceries"},
        {"description": "a" * 256},
        {"visit_id": True},
        {"visit_id": 0},
    )

    for changes in invalid_changes:
        with pytest.raises(ValueError):
            update_expense(1, 1, changes)


def test_update_expense_changes_values(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, completed_date, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "completed", date(2026, 11, 18), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    expense_id = add_expense(
        user_ids["worker"],
        date(2026, 11, 18),
        Decimal("3.00"),
        "company",
        visit_id=visit_id,
        description="Pysäköinti"
    )

    updated = update_expense(
        user_ids["worker"],
        expense_id,
        {
            "amount": 35.80,
            "expense_date": date(2026, 11, 17),
            "category": "customer",
            "description": "  Ruokaostokset  "
        }
    )

    assert updated is True

    sql = """
        SELECT visit_id, expense_date, amount, category, description
        FROM expenses
        WHERE id = %s
    """

    cursor.execute(sql, (expense_id,))

    # The visit was not given, so it stays the same
    assert cursor.fetchone() == (
        visit_id,
        date(2026, 11, 17),
        Decimal("35.80"),
        "customer",
        "Ruokaostokset",
    )

    # Saving the same value again is still a successful update
    assert update_expense(user_ids["worker"], expense_id, {"amount": Decimal("35.80")}) is True

    # An empty description is stored as NULL
    update_expense(user_ids["worker"], expense_id, {"description": "   "})

    cursor.execute(
        "SELECT description FROM expenses WHERE id = %s",
        (expense_id,)
    )

    assert cursor.fetchone()[0] is None


def test_update_expense_changes_visit(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    visit_ids = []

    for completed_date in (date(2026, 11, 17), date(2026, 11, 18)):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, status, completed_date, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (client_id, service_id, "completed", completed_date, user_ids["worker"], user_ids["worker"])
        )

        visit_ids.append(cursor.fetchone()[0])

    expense_id = add_expense(
        user_ids["worker"],
        date(2026, 11, 17),
        Decimal("35.80"),
        "customer",
        visit_id=visit_ids[0],
        description="Ruokaostokset"
    )

    sql = """
        SELECT visit_id, expense_date, amount, category, description
        FROM expenses
        WHERE id = %s
    """

    # Moved to the right visit; the other values stay the same
    assert update_expense(user_ids["worker"], expense_id, {"visit_id": visit_ids[1]}) is True

    cursor.execute(sql, (expense_id,))

    assert cursor.fetchone() == (
        visit_ids[1],
        date(2026, 11, 17),
        Decimal("35.80"),
        "customer",
        "Ruokaostokset",
    )

    # A customer expense cannot lose its visit
    with pytest.raises(ValueError, match="requires a visit"):
        update_expense(user_ids["worker"], expense_id, {"visit_id": None})

    # A visit that does not exist is rejected before the update
    with pytest.raises(ValueError, match="Visit not found"):
        update_expense(user_ids["worker"], expense_id, {"visit_id": 999999})

    cursor.execute(sql, (expense_id,))

    # The failed updates did not change the expense
    assert cursor.fetchone()[0] == visit_ids[1]

    # As a company expense it can become a general expense
    update_expense(user_ids["worker"], expense_id, {"category": "company", "visit_id": None})

    cursor.execute(sql, (expense_id,))

    assert cursor.fetchone()[:4] == (
        None,
        date(2026, 11, 17),
        Decimal("35.80"),
        "company",
    )

    # A general expense cannot become a customer expense without a visit
    with pytest.raises(ValueError, match="requires a visit"):
        update_expense(user_ids["worker"], expense_id, {"category": "customer"})

    cursor.execute("SELECT COUNT(*) FROM expenses")

    # The expense was updated, never copied
    assert cursor.fetchone()[0] == 1


def test_update_expense_returns_false_if_not_found(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    updated = update_expense(user_ids["worker"], 999999, {"amount": Decimal("10.00")})

    assert updated is False


def test_update_expense_rolls_back_on_error(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def update_then_fail(cursor, updated_by_user_id, expense_id, changes):
        cursor.execute(
            "UPDATE expenses SET amount = %s WHERE id = %s",
            (Decimal("99.00"), expense_id)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    expense_id = add_expense(user_ids["worker"], date(2026, 11, 17), Decimal("12.50"), "company")

    monkeypatch.setattr(
        "carelog.services.expenses.update_expense_record",
        update_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_expense(user_ids["worker"], expense_id, {"amount": Decimal("99.00")})

    cursor.execute("SELECT amount FROM expenses WHERE id = %s", (expense_id,))

    # The original amount is kept after the rollback
    assert cursor.fetchone()[0] == Decimal("12.50")


def test_update_expense_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.expenses.get_active_user", fake_active_user)


    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False
            self.rolled_back = False

        def cursor(self):
            return self.test_cursor

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def select_then_fail(cursor, expense_id, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.expenses.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.expenses.select_expense_for_update",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        update_expense(1, 1, {"amount": Decimal("10.00")})

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# OWNERSHIP TESTS
# expenses.user_id is the worker the expense belongs to. It is chosen on
# its own and can differ from the worker of the visit.


def test_expense_functions_reject_invalid_user_ids():
    # The user check itself is tested in test_user_validation.py
    for user_id in (None, True, "1", 0):
        with pytest.raises(ValueError):
            add_expense(user_id, date(2026, 11, 18), Decimal("10.00"), "company")

        with pytest.raises(ValueError):
            get_expense(user_id, 1)

        with pytest.raises(ValueError):
            get_visit_expenses(user_id, 1)

        with pytest.raises(ValueError):
            update_expense(user_id, 1, {"amount": Decimal("11.00")})

    # user_id=None means the actor, so only the other values are invalid
    for user_id in (True, "1", 0):
        with pytest.raises(ValueError):
            add_expense(1, date(2026, 11, 18), Decimal("10.00"), "company", user_id=user_id)

        with pytest.raises(ValueError):
            get_expenses(1, user_id=user_id)


@pytest.fixture
def ownership_database(
    postgres_cursor_with_expenses,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    # A visit of the worker and a visit of the other worker
    cursor = postgres_cursor_with_expenses

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    for module in ("carelog.services.expenses", "carelog.services.visits"):
        monkeypatch.setattr(f"{module}.get_postgres_connection", get_test_connection)

    visit_id = insert_visit(cursor, user_ids["worker"])
    other_visit_id = insert_visit(cursor, user_ids["other_worker"])

    return cursor, visit_id, other_visit_id, get_test_connection


def get_expense_users(cursor, expense_id):
    cursor.execute(
        "SELECT user_id, created_by_user_id, updated_by_user_id FROM expenses WHERE id = %s",
        (expense_id,)
    )
    return cursor.fetchone()


def test_worker_and_admin_choose_the_expense_owner(ownership_database, user_ids):
    cursor, visit_id, other_visit_id, get_test_connection = ownership_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]
    day = date(2026, 11, 18)

    # Without user_id the actor owns the expense
    own_id = add_expense(worker_id, day, Decimal("10.00"), "company")
    assert get_expense_users(cursor, own_id) == (worker_id, worker_id, None)

    # A worker cannot add an expense for another worker
    with pytest.raises(PermissionError):
        add_expense(worker_id, day, Decimal("10.00"), "company", user_id=other_worker_id)

    # An admin can, and is the creator
    admin_added_id = add_expense(admin_id, day, Decimal("12.00"), "company", user_id=other_worker_id)
    assert get_expense_users(cursor, admin_added_id) == (other_worker_id, admin_id, None)

    # The owner must be an active user
    with pytest.raises(PermissionError):
        add_expense(admin_id, day, Decimal("10.00"), "company", user_id=user_ids["inactive"])

    cursor.execute("SELECT COUNT(*) FROM expenses")
    assert cursor.fetchone()[0] == 2


def test_expense_visit_link_does_not_give_visit_access(ownership_database, user_ids):
    cursor, visit_id, other_visit_id, get_test_connection = ownership_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]
    day = date(2026, 11, 18)

    # A worker cannot link an expense to another worker's visit. The
    # error is the same as for a missing visit.
    with pytest.raises(ValueError, match="Visit not found"):
        add_expense(worker_id, day, Decimal("10.00"), "customer", visit_id=other_visit_id)

    own_id = add_expense(worker_id, day, Decimal("10.00"), "customer", visit_id=visit_id)

    with pytest.raises(ValueError, match="Visit not found"):
        update_expense(worker_id, own_id, {"visit_id": other_visit_id})

    # An admin can link the worker's expense to the other worker's visit.
    # The owners of the expense and the visit then differ.
    linked_id = add_expense(
        admin_id, day, Decimal("20.00"), "customer", visit_id=other_visit_id, user_id=worker_id
    )
    other_id = add_expense(other_worker_id, day, Decimal("30.00"), "customer", visit_id=other_visit_id)

    # The worker sees their own expense, but not the visit or the other
    # worker's expense of the same visit
    assert get_expense(worker_id, linked_id)["visit_id"] == other_visit_id
    assert get_visit(worker_id, other_visit_id) is None

    def ids_of(expenses):
        ids = []

        for expense in expenses:
            ids.append(expense["id"])

        return ids

    assert ids_of(get_visit_expenses(worker_id, other_visit_id)) == [linked_id]
    assert ids_of(get_visit_expenses(other_worker_id, other_visit_id)) == [other_id]
    assert ids_of(get_visit_expenses(admin_id, other_visit_id)) == [linked_id, other_id]

    cursor.execute("SELECT visit_id FROM expenses WHERE id = %s", (own_id,))
    assert cursor.fetchone()[0] == visit_id


def test_expense_reads_and_updates_are_limited_to_own(ownership_database, user_ids):
    cursor, visit_id, other_visit_id, get_test_connection = ownership_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]
    day = date(2026, 11, 18)

    own_id = add_expense(worker_id, day, Decimal("10.00"), "company")
    other_id = add_expense(other_worker_id, day, Decimal("20.00"), "company")

    def ids_of(expenses):
        ids = []

        for expense in expenses:
            ids.append(expense["id"])

        return ids

    # Another worker's expense looks like a missing expense
    assert get_expense(worker_id, other_id) is None
    assert update_expense(worker_id, other_id, {"amount": Decimal("1.00")}) is False
    assert get_expense(admin_id, other_id)["amount"] == Decimal("20.00")

    # Lists: own expenses for a worker, every worker's or one worker's
    # for an admin
    assert ids_of(get_expenses(worker_id)) == [own_id]
    assert ids_of(get_expenses(admin_id)) == [own_id, other_id]
    assert ids_of(get_expenses(admin_id, user_id=other_worker_id)) == [other_id]

    with pytest.raises(PermissionError):
        get_expenses(worker_id, user_id=other_worker_id)

    # The owner and the creator never change in an update
    with pytest.raises(ValueError, match="Invalid expense field"):
        update_expense(admin_id, own_id, {"user_id": other_worker_id})

    assert update_expense(admin_id, own_id, {"amount": Decimal("11.00")}) is True
    assert get_expense_users(cursor, own_id) == (worker_id, worker_id, admin_id)

    assert update_expense(worker_id, own_id, {"description": "Parkkimaksu"}) is True
    assert get_expense_users(cursor, own_id) == (worker_id, worker_id, worker_id)


def test_expense_on_visit_waits_for_worker_change(ownership_database, user_ids):
    cursor, visit_id, other_visit_id, get_test_connection = ownership_database

    # The other connection gives the worker's visit to the other worker
    # but does not commit yet, so it keeps the visit row locked.
    other_connection = get_test_connection()

    try:
        other_connection.execute(
            "UPDATE visits SET user_id = %s WHERE id = %s",
            (user_ids["other_worker"], visit_id)
        )

        thread, done, outcome = start_in_thread(
            add_expense, user_ids["worker"], date(2026, 11, 18), Decimal("10.00"),
            "customer", visit_id=visit_id
        )

        wait_until_waiting_for_lock(cursor)
        assert not done.is_set()

        other_connection.commit()

        assert done.wait(timeout=10)
        thread.join(timeout=10)

    finally:
        other_connection.close()

    # The visit is no longer the worker's, so the expense is not saved
    assert isinstance(outcome.get("error"), ValueError)

    cursor.execute("SELECT COUNT(*) FROM expenses")
    assert cursor.fetchone()[0] == 0
