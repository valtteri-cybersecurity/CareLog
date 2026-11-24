from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from carelog.database.postgres_connection import get_postgres_connection
from carelog.database.repositories.insert_expense import insert_expense
from carelog.database.repositories.select_expense import select_expense
from carelog.database.repositories.select_expenses import select_expenses
from carelog.database.repositories.select_visit import select_visit
from carelog.database.repositories.select_visit_expenses import select_visit_expenses
from carelog.database.repositories.update_expense import (
    ALLOWED_FIELDS,
    select_expense_for_update,
    update_expense_record,
)
from carelog.services.user_validation import (
    get_active_user,
    get_owner_filter,
    resolve_owner_id,
    validate_user_id,
)


# expense_date is the user's local calendar day.
LOCAL_TIMEZONE = ZoneInfo("Europe/Helsinki")

# customer = bought on behalf of a client and charged from the client
# company  = the business's own cost
# The category does not decide whether a cost is tax deductible.
ALLOWED_CATEGORIES = ("customer", "company")


def validate_amount(amount: Decimal | int | float) -> Decimal:

    # Money is handled as Decimal, never rounded silently.

    if isinstance(amount, bool):
        raise ValueError("Amount must be a number")

    if not isinstance(amount, (int, float, Decimal)):
        raise ValueError("Amount must be a number")

    # str() keeps the value as written, for example 35.8 -> "35.8"
    amount = Decimal(str(amount))

    if not amount.is_finite():
        raise ValueError("Amount must be finite")

    if amount <= 0:
        raise ValueError("Amount must be positive")

    if amount > Decimal("99999999.99"):
        raise ValueError("Amount exceeds database limit")

    if amount != amount.quantize(Decimal("0.01")):
        raise ValueError("Amount cannot exceed two decimal places")

    return amount


def validate_category(category: str) -> str:

    if not isinstance(category, str):
        raise ValueError("Category must be a string")

    category = category.strip()

    if category not in ALLOWED_CATEGORIES:
        raise ValueError("Category must be customer or company")

    return category


def validate_expense_date(expense_date: date) -> date:

    # A datetime is also a date in Python, so type() is used to reject it.

    if type(expense_date) is not date:
        raise ValueError("Expense date must be a date")

    today = datetime.now(LOCAL_TIMEZONE).date()

    if expense_date > today:
        raise ValueError("Expense date cannot be in the future")

    return expense_date


def validate_visit_id(visit_id: int | None) -> int | None:

    # None means a general expense without a visit.
    # check_visit_link() checks that the visit exists and may be used.

    if visit_id is None:
        return None

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    return visit_id


def validate_expense_description(description: str | None) -> str | None:

    if description is None:
        return None

    if not isinstance(description, str):
        raise ValueError("Description must be a string")

    description = description.strip()

    if not description:
        return None

    if len(description) > 255:
        raise ValueError("Description cannot exceed 255 characters")

    return description


def check_visit_link(cursor, actor: dict, visit_id: int) -> None:

    # A worker may link an expense only to their own visit, an admin to
    # the visit of any worker. A missing visit and another worker's visit
    # give the same error, so the other visit's existence is not revealed.
    # The visit row is locked, so its worker cannot change before commit.
    #
    # The link does not give the owner of the expense any access to the
    # visit itself.

    owner_user_id = get_owner_filter(actor, None)

    visit = select_visit(
        cursor,
        visit_id,
        for_update=True,
        owner_user_id=owner_user_id
    )

    if visit is None:
        raise ValueError("Visit not found")


def add_expense(
    actor_user_id: int,
    expense_date: date,
    amount: Decimal | int | float,
    category: str,
    visit_id: int | None = None,
    description: str | None = None,
    user_id: int | None = None
) -> int:

    # The owner of the expense (user_id) is the actor unless an admin
    # chooses another active worker. It is not taken from the visit: the
    # owner of an expense can differ from the worker of its visit.

    validate_user_id(actor_user_id)

    if user_id is not None:
        validate_user_id(user_id)

    # Expense date validation

    expense_date = validate_expense_date(expense_date)

    # Amount validation

    amount = validate_amount(amount)

    # Category validation

    category = validate_category(category)

    # Visit ID validation

    visit_id = validate_visit_id(visit_id)

    # A customer expense is linked to the client through the visit.
    if category == "customer" and visit_id is None:
        raise ValueError("A customer expense requires a visit")

    # Description validation

    description = validate_expense_description(description)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        # Users first, then the visit row, as in the visit functions
        actor = get_active_user(cursor, actor_user_id)
        owner_id = resolve_owner_id(cursor, actor, user_id)

        if visit_id is not None:
            check_visit_link(cursor, actor, visit_id)

        expense_id = insert_expense(
            cursor,
            owner_id,
            actor["id"],
            expense_date,
            amount,
            category,
            visit_id,
            description
        )

        connection.commit()

        return expense_id

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_expense(actor_user_id: int, expense_id: int) -> dict | None:

    # A worker gets only their own expenses. Another worker's expense
    # gives None, as a missing expense does. Only the expense row is
    # returned, never data of the visit.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Expense ID validation

    if type(expense_id) is not int:
        raise ValueError("Expense ID must be an integer")

    if expense_id <= 0:
        raise ValueError("Expense ID must be positive")

    # Database operation
    # The amount is returned as Decimal and the date as date,
    # exactly as they are stored.

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        expense = select_expense(cursor, expense_id, owner_user_id)

        return expense

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_visit_expenses(actor_user_id: int, visit_id: int) -> list[dict]:

    # A worker gets only their own expenses of the visit, also when the
    # visit belongs to another worker. Only expense rows are returned, so
    # nothing else about the visit is revealed.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Visit ID validation
    # A visit that does not exist simply has no expenses, so the result
    # is an empty list. Expenses are returned for visits in any status.

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        expenses = select_visit_expenses(cursor, visit_id, owner_user_id)

        return expenses

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_expenses(
    actor_user_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = None,
    client_id: int | None = None,
    user_id: int | None = None
) -> list[dict]:

    # All filters are optional. Without filters every expense the actor
    # may see is returned: a worker's own expenses, or for an admin the
    # expenses of every worker, or of the worker user_id. The filters
    # that are given must all match.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    if user_id is not None:
        validate_user_id(user_id)

    # Date validation
    # A datetime is also a date in Python, so type() is used to reject it.

    if start_date is not None and type(start_date) is not date:
        raise ValueError("Start date must be a date")

    if end_date is not None and type(end_date) is not date:
        raise ValueError("End date must be a date")

    if start_date is not None and end_date is not None:

        if start_date > end_date:
            raise ValueError("Start date cannot be after end date")

    # Category validation

    if category is not None:
        category = validate_category(category)

    # Client ID validation

    if client_id is not None:

        if type(client_id) is not int:
            raise ValueError("Client ID must be an integer")

        if client_id <= 0:
            raise ValueError("Client ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, user_id)

        expenses = select_expenses(
            cursor,
            start_date,
            end_date,
            category,
            client_id,
            owner_user_id
        )

        return expenses

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def update_expense(actor_user_id: int, expense_id: int, changes: dict) -> bool:

    # A worker may update only their own expenses. The owner (user_id)
    # is not one of ALLOWED_FIELDS, so it never changes here.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Expense ID validation

    if type(expense_id) is not int:
        raise ValueError("Expense ID must be an integer")

    if expense_id <= 0:
        raise ValueError("Expense ID must be positive")

    # Changes validation
    # The same rules as in add_expense() are used for every field.

    if not isinstance(changes, dict):
        raise ValueError("Changes must be a dictionary")

    if not changes:
        raise ValueError("No fields to update")

    validated_changes = {}

    for field, value in changes.items():

        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid expense field")

        if field == "expense_date":
            validated_changes[field] = validate_expense_date(value)

        elif field == "amount":
            validated_changes[field] = validate_amount(value)

        elif field == "category":
            validated_changes[field] = validate_category(value)

        elif field == "description":
            validated_changes[field] = validate_expense_description(value)

        elif field == "visit_id":
            validated_changes[field] = validate_visit_id(value)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        # The row is locked, so the check below uses current data.
        # Another worker's expense is not found.
        expense = select_expense_for_update(cursor, expense_id, owner_user_id)

        if expense is None:
            return False

        # The category and the visit must fit together after the update.
        category = expense["category"]
        visit_id = expense["visit_id"]

        if "category" in validated_changes:
            category = validated_changes["category"]

        if "visit_id" in validated_changes:
            visit_id = validated_changes["visit_id"]

        if category == "customer" and visit_id is None:
            raise ValueError("A customer expense requires a visit")

        # A new visit link follows the same rule as in add_expense(). The
        # expense row is locked first, then the visit row.
        if "visit_id" in validated_changes and validated_changes["visit_id"] is not None:
            check_visit_link(cursor, actor, validated_changes["visit_id"])

        updated = update_expense_record(
            cursor,
            actor["id"],
            expense_id,
            validated_changes
        )

        connection.commit()

        return updated

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
