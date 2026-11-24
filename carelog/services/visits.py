from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from carelog.database.postgres_connection import get_postgres_connection
from carelog.database.repositories.cancel_visit import cancel_visit_record
from carelog.database.repositories.complete_visit import complete_visit_record
from carelog.database.repositories.insert_visit import insert_visit
from carelog.database.repositories.insert_visit_note import insert_visit_note
from carelog.database.repositories.select_client import select_client
from carelog.database.repositories.select_client_visits import select_client_visits
from carelog.database.repositories.select_planned_visits import select_planned_visits
from carelog.database.repositories.select_service import select_service
from carelog.database.repositories.select_visit import select_visit
from carelog.database.repositories.select_week_visits import select_week_visits
from carelog.database.repositories.update_visit_worker import update_visit_worker_record
from carelog.database.repositories.update_visit import (
    ALLOWED_FIELDS,
    update_visit_record,
)
from carelog.services.trips import validate_distance_km
from carelog.services.user_validation import (
    get_active_user,
    get_owner_filter,
    is_admin,
    resolve_owner_id,
    validate_user_id,
)
from carelog.services.visit_notes import validate_note_content


# DATE columns hold the user's local calendar day.
# TIMESTAMP columns are stored in UTC.
LOCAL_TIMEZONE = ZoneInfo("Europe/Helsinki")

# Largest value of an INT column.
MAX_INT_VALUE = 2147483647


def validate_duration_minutes(duration_minutes: int | None) -> int | None:

    if duration_minutes is None:
        return None

    if type(duration_minutes) is not int:
        raise ValueError("Duration must be an integer")

    if duration_minutes <= 0:
        raise ValueError("Duration must be positive")

    if duration_minutes > MAX_INT_VALUE:
        raise ValueError("Duration exceeds database limit")

    return duration_minutes


def validate_description(description: str | None) -> str | None:

    if description is None:
        return None

    if not isinstance(description, str):
        raise ValueError("Description must be a string")

    description = description.strip()

    if not description:
        return None

    # CareLog's own upper limit, 65535 bytes. A PostgreSQL TEXT column
    # itself has no practical size limit.
    if len(description.encode("utf-8")) > 65535:
        raise ValueError("Description is too long")

    return description


def validate_price(price: Decimal | int | float | None) -> Decimal | None:

    if price is None:
        return None

    if isinstance(price, bool):
        raise ValueError("Price must be a number")

    if not isinstance(price, (int, float, Decimal)):
        raise ValueError("Price must be a number")

    price = Decimal(str(price))

    if not price.is_finite():
        raise ValueError("Price must be finite")

    if price < 0:
        raise ValueError("Price cannot be negative")

    if price > Decimal("99999999.99"):
        raise ValueError("Price exceeds database limit")

    if price != price.quantize(Decimal("0.01")):
        raise ValueError("Price cannot exceed two decimal places")

    return price


def validate_optional_note(note: str | None) -> str | None:

    # The note field of a visit is optional: None or text with only
    # spaces or line breaks means that no note is saved. Real text
    # follows the same rules as add_visit_note().

    if note is None:
        return None

    if not isinstance(note, str):
        raise ValueError("Note must be a string")

    if not note.strip():
        return None

    return validate_note_content(note)


def validate_completed_times(
    completed_date: date | None,
    duration_minutes: int | None,
    started_at: datetime | None,
    ended_at: datetime | None
) -> tuple:

    # Validates the actual day, duration and times of a completed visit.
    # Times are compared in UTC, so daylight saving time changes do not
    # affect the order or the duration. If a start time is given, the
    # day is taken from it. If both times are given, the duration is
    # calculated from them.
    # Returns (completed_date, duration_minutes, started_at, ended_at)
    # with the times in UTC without time zone.

    if completed_date is not None:

        if type(completed_date) is not date:
            raise ValueError("Completed date must be a date")

    if ended_at is not None and started_at is None:
        raise ValueError("End time requires a start time")

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    if started_at is not None:

        if not isinstance(started_at, datetime):
            raise ValueError("Start time must be a datetime")

        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("Start time must include a time zone")

        # The local calendar day of the start time
        local_date = started_at.astimezone(LOCAL_TIMEZONE).date()

        if completed_date is not None and completed_date != local_date:
            raise ValueError("Completed date does not match start time")

        completed_date = local_date

        # Store in UTC with minute precision, so the times and the
        # duration always match.
        started_at = started_at.astimezone(timezone.utc)
        started_at = started_at.replace(tzinfo=None, second=0, microsecond=0)

        if started_at > now:
            raise ValueError("Start time cannot be in the future")

    if ended_at is not None:

        if not isinstance(ended_at, datetime):
            raise ValueError("End time must be a datetime")

        if ended_at.tzinfo is None or ended_at.utcoffset() is None:
            raise ValueError("End time must include a time zone")

        ended_at = ended_at.astimezone(timezone.utc)
        ended_at = ended_at.replace(tzinfo=None, second=0, microsecond=0)

        if ended_at <= started_at:
            raise ValueError("End time must be after start time")

        if ended_at > now:
            raise ValueError("End time cannot be in the future")

    today = datetime.now(LOCAL_TIMEZONE).date()

    if completed_date is not None and completed_date > today:
        raise ValueError("Completed date cannot be in the future")

    duration_minutes = validate_duration_minutes(duration_minutes)

    if ended_at is not None:

        # Both times are whole minutes, so this is a whole number.
        time_difference = ended_at - started_at
        calculated_minutes = int(time_difference.total_seconds() // 60)

        if duration_minutes is not None and duration_minutes != calculated_minutes:
            raise ValueError("Duration does not match start and end time")

        duration_minutes = calculated_minutes

    return completed_date, duration_minutes, started_at, ended_at


def add_planned_visit(
    actor_user_id: int,
    client_id: int,
    service_id: int,
    planned_week: date | None = None,
    planned_date: date | None = None,
    planned_at: datetime | None = None,
    planned_duration_minutes: int | None = None,
    priority: int = 2,
    description: str | None = None,
    note: str | None = None,
    price: Decimal | int | float | None = None,
    user_id: int | None = None
) -> int:

    # Actor and worker validation. The worker is the actor unless an
    # admin gives user_id. The users are checked in the database below.

    validate_user_id(actor_user_id)

    if user_id is not None:
        validate_user_id(user_id)

    # Client and service ID validation
    # The service foreign key checks that the service exists.

    if type(client_id) is not int:
        raise ValueError("Client ID must be an integer")

    if client_id <= 0:
        raise ValueError("Client ID must be positive")

    if type(service_id) is not int:
        raise ValueError("Service ID must be an integer")

    if service_id <= 0:
        raise ValueError("Service ID must be positive")

    # Schedule validation
    # A datetime is also a date in Python, so type() is used to reject it.

    if planned_week is None and planned_date is None and planned_at is None:
        raise ValueError("Planned week, date or time is required")

    if planned_week is not None:

        if type(planned_week) is not date:
            raise ValueError("Planned week must be a date")

        if planned_week.weekday() != 0:
            raise ValueError("Planned week must be a Monday")

    if planned_date is not None:

        if type(planned_date) is not date:
            raise ValueError("Planned date must be a date")

    if planned_at is not None:

        if not isinstance(planned_at, datetime):
            raise ValueError("Planned time must be a datetime")

        if planned_at.tzinfo is None or planned_at.utcoffset() is None:
            raise ValueError("Planned time must include a time zone")

        # The local calendar day of the planned time
        local_date = planned_at.astimezone(LOCAL_TIMEZONE).date()

        if planned_date is not None and planned_date != local_date:
            raise ValueError("Planned date does not match planned time")

        planned_date = local_date

        # Store in UTC without time zone and seconds fractions.
        # A planned time does not need fractions of a second.
        planned_at = planned_at.astimezone(timezone.utc)
        planned_at = planned_at.replace(tzinfo=None, microsecond=0)

    if planned_date is not None:

        # Monday of the planned date's week
        week_start = planned_date - timedelta(days=planned_date.weekday())

        if planned_week is not None and planned_week != week_start:
            raise ValueError("Planned week does not match planned date")

        planned_week = week_start

    # Planned duration validation

    planned_duration_minutes = validate_duration_minutes(
        planned_duration_minutes
    )

    # Priority validation: 1 = urgent, 2 = normal, 3 = low

    if type(priority) is not int:
        raise ValueError("Priority must be an integer")

    if priority < 1 or priority > 3:
        raise ValueError("Priority must be between 1 and 3")

    # Description, hourly rate and note validation

    description = validate_description(description)
    price = validate_price(price)
    note = validate_optional_note(note)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        # The users are checked first, then the client row is locked, in
        # the same order in every visit function.
        actor = get_active_user(cursor, actor_user_id)
        worker_id = resolve_owner_id(cursor, actor, user_id)

        # New visits are not allowed for missing or archived clients.
        # The client row is locked until commit or rollback, so the client
        # cannot be archived between this check and the insert below.
        client = select_client(cursor, client_id, for_update=True)

        if client is None:
            raise ValueError("Client not found")

        if client["archived_at"] is not None:
            raise ValueError("Cannot add a visit for an archived client")

        # visits.price is the hourly rate of this visit. Without a given
        # rate, the current default rate of the service is copied, so a
        # later change of the service does not change this visit. A
        # missing service is rejected by the foreign key below.
        if price is None:
            service = select_service(cursor, service_id)

            if service is not None:
                price = service["default_hourly_rate"]

        visit_id = insert_visit(
            cursor,
            worker_id,
            actor["id"],
            client_id,
            service_id,
            "planned",
            priority,
            planned_week,
            planned_date,
            planned_at,
            planned_duration_minutes,
            description,
            price=price
        )

        # The note is saved in the same transaction, so the visit and
        # the note are either both saved or both rolled back.
        if note is not None:
            insert_visit_note(cursor, actor["id"], visit_id, note)

        connection.commit()

        return visit_id

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def add_completed_visit(
    actor_user_id: int,
    client_id: int,
    service_id: int,
    completed_date: date | None = None,
    duration_minutes: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    description: str | None = None,
    distance_km: Decimal | int | float | None = None,
    price: Decimal | int | float | None = None,
    note: str | None = None,
    user_id: int | None = None
) -> int:

    # Actor and worker validation, as in add_planned_visit()

    validate_user_id(actor_user_id)

    if user_id is not None:
        validate_user_id(user_id)

    # Client and service ID validation
    # The service foreign key checks that the service exists.

    if type(client_id) is not int:
        raise ValueError("Client ID must be an integer")

    if client_id <= 0:
        raise ValueError("Client ID must be positive")

    if type(service_id) is not int:
        raise ValueError("Service ID must be an integer")

    if service_id <= 0:
        raise ValueError("Service ID must be positive")

    # Date, time and duration validation

    if completed_date is None and started_at is None:
        raise ValueError("Completed date or start time is required")

    completed_date, duration_minutes, started_at, ended_at = validate_completed_times(
        completed_date,
        duration_minutes,
        started_at,
        ended_at
    )

    # Description, distance, price and note validation

    description = validate_description(description)
    distance_km = validate_distance_km(distance_km)
    price = validate_price(price)
    note = validate_optional_note(note)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        worker_id = resolve_owner_id(cursor, actor, user_id)

        # New visits are not allowed for missing or archived clients.
        # The client row is locked until commit or rollback, so the client
        # cannot be archived between this check and the insert below.
        client = select_client(cursor, client_id, for_update=True)

        if client is None:
            raise ValueError("Client not found")

        if client["archived_at"] is not None:
            raise ValueError("Cannot add a visit for an archived client")

        # Without a given hourly rate, the current default rate of the
        # service is copied to the visit, as in add_planned_visit().
        if price is None:
            service = select_service(cursor, service_id)

            if service is not None:
                price = service["default_hourly_rate"]

        # Planning fields stay NULL. Priority only matters for planning,
        # so the normal priority is stored.
        visit_id = insert_visit(
            cursor,
            worker_id,
            actor["id"],
            client_id,
            service_id,
            "completed",
            2,
            description=description,
            completed_date=completed_date,
            started_at=started_at,
            ended_at=ended_at,
            duration_minutes=duration_minutes,
            distance_km=distance_km,
            price=price
        )

        # The note is saved in the same transaction as the visit.
        if note is not None:
            insert_visit_note(cursor, actor["id"], visit_id, note)

        connection.commit()

        return visit_id

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_visit(actor_user_id: int, visit_id: int) -> dict | None:

    # A worker gets only their own visits. Another worker's visit gives
    # None, as a missing visit does, so its existence is not revealed.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Visit ID validation

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Database operation
    # TIMESTAMP values are returned in UTC as they are stored.

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        visit = select_visit(cursor, visit_id, owner_user_id=owner_user_id)

        return visit

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_client_visits(
    actor_user_id: int,
    client_id: int,
    user_id: int | None = None
) -> list[dict]:

    # A worker gets only their own visits of the client. An admin gets
    # the visits of every worker, or of the worker user_id.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    if user_id is not None:
        validate_user_id(user_id)

    # Client ID validation
    # Visits of archived clients are returned too, so history is kept.

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

        visits = select_client_visits(cursor, client_id, owner_user_id)

        return visits

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_planned_visits(actor_user_id: int, user_id: int | None = None) -> list[dict]:

    # All planned visits, also the ones left in past weeks, so that
    # they can be noticed later. A worker gets only their own visits, an
    # admin the visits of every worker, or of the worker user_id.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    if user_id is not None:
        validate_user_id(user_id)

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, user_id)

        visits = select_planned_visits(cursor, owner_user_id)

        return visits

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_week_visits(
    actor_user_id: int,
    week_start: date,
    user_id: int | None = None
) -> list[dict]:

    # A worker gets only their own visits, an admin the visits of every
    # worker, or of the worker user_id.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    if user_id is not None:
        validate_user_id(user_id)

    # Week start validation
    # A datetime is also a date in Python, so type() is used to reject it.

    if type(week_start) is not date:
        raise ValueError("Week start must be a date")

    if week_start.weekday() != 0:
        raise ValueError("Week start must be a Monday")

    next_week_start = week_start + timedelta(days=7)

    # Limits of the local week in UTC. The week starts on Monday at
    # 00.00 in Helsinki. A week with a daylight saving time change is
    # not exactly 168 hours long, so both limits are converted separately.
    local_week_start = datetime(
        week_start.year,
        week_start.month,
        week_start.day,
        tzinfo=LOCAL_TIMEZONE
    )

    local_next_week_start = datetime(
        next_week_start.year,
        next_week_start.month,
        next_week_start.day,
        tzinfo=LOCAL_TIMEZONE
    )

    week_start_utc = local_week_start.astimezone(timezone.utc)
    week_start_utc = week_start_utc.replace(tzinfo=None)

    next_week_start_utc = local_next_week_start.astimezone(timezone.utc)
    next_week_start_utc = next_week_start_utc.replace(tzinfo=None)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, user_id)

        visits = select_week_visits(
            cursor,
            week_start,
            next_week_start,
            week_start_utc,
            next_week_start_utc,
            owner_user_id
        )

        return visits

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def resolve_planned_schedule(visit: dict, changes: dict) -> tuple:

    # Starts from the stored schedule and applies the changes. The exact
    # time decides the day, and the day decides the week. Nothing is
    # changed silently: conflicting values raise ValueError.
    # Returns (planned_week, planned_date, planned_at).

    planned_week = visit["planned_week"]
    planned_date = visit["planned_date"]
    planned_at = visit["planned_at"]

    if "planned_at" in changes and changes["planned_at"] is not None:

        # A new exact time: the day and the week follow it.
        new_time = changes["planned_at"]
        local_date = new_time.astimezone(LOCAL_TIMEZONE).date()

        if "planned_date" in changes and changes["planned_date"] != local_date:
            raise ValueError("Planned date does not match planned time")

        planned_at = new_time.astimezone(timezone.utc)
        planned_at = planned_at.replace(tzinfo=None, microsecond=0)
        planned_date = local_date

        week_start = planned_date - timedelta(days=planned_date.weekday())

        if "planned_week" in changes and changes["planned_week"] != week_start:
            raise ValueError("Planned week does not match planned time")

        planned_week = week_start

    elif "planned_date" in changes and changes["planned_date"] is not None:

        # A new day: the old exact time would be on another day,
        # so it must be changed or cleared in the same update.
        new_date = changes["planned_date"]

        if "planned_at" in changes:
            planned_at = None

        if planned_at is not None and new_date != planned_date:
            raise ValueError("Change or clear the planned time with the date")

        planned_date = new_date

        week_start = planned_date - timedelta(days=planned_date.weekday())

        if "planned_week" in changes and changes["planned_week"] != week_start:
            raise ValueError("Planned week does not match planned date")

        planned_week = week_start

    else:

        # Only clearing the time or the day, or changing the week.
        if "planned_at" in changes:
            planned_at = None

        if "planned_date" in changes:

            if planned_at is not None:
                raise ValueError("Clear the planned time with the date")

            planned_date = None

        if "planned_week" in changes:
            planned_week = changes["planned_week"]

            if planned_date is not None:
                week_start = planned_date - timedelta(days=planned_date.weekday())

                if planned_week != week_start:
                    raise ValueError("Planned week does not match planned date")

    if planned_week is None:
        raise ValueError("Planned week, date or time is required")

    return planned_week, planned_date, planned_at


def update_visit(actor_user_id: int, visit_id: int, changes: dict) -> bool:

    # A worker may update only their own visits. The worker of a visit is
    # not one of ALLOWED_FIELDS: change_visit_worker() changes it.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Visit ID validation

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Changes validation
    # Client, status and completed fields cannot be changed here.

    if not isinstance(changes, dict):
        raise ValueError("Changes must be a dictionary")

    if not changes:
        raise ValueError("No fields to update")

    for field in changes:
        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid visit field")

    validated_changes = {}

    # Service ID validation
    # The service foreign key checks that the service exists.

    if "service_id" in changes:
        service_id = changes["service_id"]

        if type(service_id) is not int:
            raise ValueError("Service ID must be an integer")

        if service_id <= 0:
            raise ValueError("Service ID must be positive")

        validated_changes["service_id"] = service_id

    # Priority validation: 1 = urgent, 2 = normal, 3 = low

    if "priority" in changes:
        priority = changes["priority"]

        if type(priority) is not int:
            raise ValueError("Priority must be an integer")

        if priority < 1 or priority > 3:
            raise ValueError("Priority must be between 1 and 3")

        validated_changes["priority"] = priority

    # Planned duration and description validation

    if "planned_duration_minutes" in changes:
        validated_changes["planned_duration_minutes"] = validate_duration_minutes(
            changes["planned_duration_minutes"]
        )

    if "description" in changes:
        validated_changes["description"] = validate_description(
            changes["description"]
        )

    # Schedule value validation
    # None clears a value. How the values fit together is checked
    # against the stored visit below.

    if "planned_week" in changes:
        planned_week = changes["planned_week"]

        if planned_week is not None:

            if type(planned_week) is not date:
                raise ValueError("Planned week must be a date")

            if planned_week.weekday() != 0:
                raise ValueError("Planned week must be a Monday")

    if "planned_date" in changes:
        planned_date = changes["planned_date"]

        if planned_date is not None and type(planned_date) is not date:
            raise ValueError("Planned date must be a date")

    if "planned_at" in changes:
        planned_at = changes["planned_at"]

        if planned_at is not None:

            if not isinstance(planned_at, datetime):
                raise ValueError("Planned time must be a datetime")

            if planned_at.tzinfo is None or planned_at.utcoffset() is None:
                raise ValueError("Planned time must include a time zone")

    schedule_changed = False

    if "planned_week" in changes or "planned_date" in changes:
        schedule_changed = True

    if "planned_at" in changes:
        schedule_changed = True

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        # The visit is read and locked before anything is calculated from
        # it, so the schedule is based on the current values and no other
        # update can change the row before this transaction ends. Another
        # worker's visit is not found.
        visit = select_visit(
            cursor,
            visit_id,
            for_update=True,
            owner_user_id=owner_user_id
        )

        if visit is None:
            return False

        if visit["status"] != "planned":
            raise ValueError("Only planned visits can be updated")

        # All three schedule fields are saved together, so they never
        # disagree with each other.
        if schedule_changed:
            planned_week, planned_date, planned_at = resolve_planned_schedule(
                visit,
                changes
            )

            validated_changes["planned_week"] = planned_week
            validated_changes["planned_date"] = planned_date
            validated_changes["planned_at"] = planned_at

        # The record function checks the status again. The row is already
        # locked by this transaction, so locking it again does not wait.
        updated = update_visit_record(
            cursor,
            actor["id"],
            visit_id,
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


def complete_visit(
    actor_user_id: int,
    visit_id: int,
    completed_date: date | None = None,
    duration_minutes: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    note: str | None = None
) -> bool:

    # Marks a planned visit as completed. Values that are not given are
    # taken from the plan, so complete_visit(visit_id) is enough when the
    # plan is detailed enough. The plan and the worker are never changed.
    # A worker may complete only their own visits.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Visit ID validation

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Values given by the user follow the same rules as in
    # add_completed_visit(). Times are returned in UTC.

    completed_date, duration_minutes, started_at, ended_at = validate_completed_times(
        completed_date,
        duration_minutes,
        started_at,
        ended_at
    )

    note = validate_optional_note(note)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        # The visit is read and locked before the default values are
        # taken from the plan, so they come from the current plan.
        # Another worker's visit is not found.
        visit = select_visit(
            cursor,
            visit_id,
            for_update=True,
            owner_user_id=owner_user_id
        )

        if visit is None:
            return False

        if visit["status"] != "planned":
            raise ValueError("Only planned visits can be completed")

        planned_at = visit["planned_at"]
        planned_local_date = None

        if planned_at is not None:
            # planned_at is stored in UTC without time zone
            planned_local_date = planned_at.replace(tzinfo=timezone.utc)
            planned_local_date = planned_local_date.astimezone(LOCAL_TIMEZONE).date()

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        today = datetime.now(LOCAL_TIMEZONE).date()

        # Default day: the planned day, then the day of the planned time,
        # and for a visit planned only for a week, today.

        if completed_date is None:

            if visit["planned_date"] is not None:
                completed_date = visit["planned_date"]
            elif planned_local_date is not None:
                completed_date = planned_local_date
            else:
                completed_date = today

            if completed_date > today:
                raise ValueError("Completed date cannot be in the future")

        # Default duration: the planned duration, unless the user gave
        # both times, because then the duration comes from them.

        if duration_minutes is None and ended_at is None:
            duration_minutes = visit["planned_duration_minutes"]

        # Default start time: the planned time, but only if it is on the
        # completed day and has already passed. A planned time is never
        # moved to another day. A planned time that has not come yet is
        # not used, because the visit was done earlier than planned.

        start_from_plan = False

        if started_at is None and planned_at is not None:

            if planned_local_date == completed_date and planned_at <= now:
                started_at = planned_at
                start_from_plan = True

        # End time from the start time and the accepted duration, so the
        # times and the duration always match.

        if started_at is not None and ended_at is None:

            if duration_minutes is not None:
                ended_at = started_at + timedelta(minutes=duration_minutes)

                if ended_at > now:

                    if start_from_plan:
                        # The visit ended before the planned end time, so
                        # the planned times are not the actual ones. Only
                        # the day and the duration are saved.
                        started_at = None
                        ended_at = None

                    else:
                        raise ValueError("End time cannot be in the future")

        completed = complete_visit_record(
            cursor,
            actor["id"],
            visit_id,
            completed_date,
            duration_minutes,
            started_at,
            ended_at
        )

        # The note is added only after a successful completion, in the
        # same transaction as the status change.
        if completed and note is not None:
            insert_visit_note(cursor, actor["id"], visit_id, note)

        connection.commit()

        return completed

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def cancel_visit(actor_user_id: int, visit_id: int) -> bool:

    # A cancelled visit is not deleted. Only its status changes, so it
    # stays in the client's history. A worker may cancel only their own
    # visits.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Visit ID validation

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Database operation
    # The record function locks the row, checks the worker and that the
    # visit is planned, and changes the status in the same transaction.

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        cancelled = cancel_visit_record(
            cursor,
            actor["id"],
            visit_id,
            owner_user_id
        )

        connection.commit()

        return cancelled

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def change_visit_worker(actor_user_id: int, visit_id: int, user_id: int) -> bool:

    # Gives a planned visit to another worker. Only an admin may do this,
    # and only while the visit is planned: the worker of a completed or
    # cancelled visit never changes. The role is read from the database.
    # The database itself cannot check the role, because the application
    # uses one shared database account.
    #
    # The creator of the visit and the user_id of its expenses do not
    # change. Returns False if the visit does not exist.

    # Actor, visit and worker ID validation

    validate_user_id(actor_user_id)

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    validate_user_id(user_id)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        # The users are checked first, then the visit row is locked, as
        # in the other visit functions.
        actor = get_active_user(cursor, actor_user_id)

        if not is_admin(actor):
            raise PermissionError("Only an admin can change the worker of a visit")

        worker_id = resolve_owner_id(cursor, actor, user_id)

        # The status is checked from the locked row. A completion that
        # started earlier has to finish first, and a completion that
        # starts later waits until this transaction ends.
        visit = select_visit(cursor, visit_id, for_update=True)

        if visit is None:
            return False

        if visit["status"] != "planned":
            raise ValueError("Only the worker of a planned visit can be changed")

        changed = update_visit_worker_record(
            cursor,
            actor["id"],
            visit_id,
            worker_id
        )

        connection.commit()

        return changed

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
