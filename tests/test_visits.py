import threading
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import psycopg
import pytest

from carelog.database.repositories.archive_client import archive_client_record
from carelog.database.repositories.insert_visit import insert_visit
from carelog.services.clients import archive_client, get_client
from carelog.services.visits import (
    add_completed_visit,
    add_planned_visit,
    cancel_visit,
    change_visit_worker,
    complete_visit,
    get_client_visits,
    get_planned_visits,
    get_visit,
    get_week_visits,
    update_visit,
)
from tests.postgres_helpers import (
    fake_active_user,
    start_in_thread,
    wait_until_waiting_for_lock,
)


HELSINKI = ZoneInfo("Europe/Helsinki")


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # A test that does not replace the connection with the test database
    # must never reach the real database.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a test")

    monkeypatch.setattr("carelog.services.visits.get_postgres_connection", connection_not_allowed)


# ADD PLANNED VISIT TESTS


def test_add_planned_visit_rejects_invalid_ids():
    invalid_ids = (
        ("1", 1),
        (None, 1),
        (True, 1),
        (0, 1),
        (1, -1),
        (1, True),
    )

    for client_id, service_id in invalid_ids:
        with pytest.raises(ValueError):
            add_planned_visit(
                1,
                client_id,
                service_id,
                planned_week=date(2026, 11, 23)
            )


def test_add_planned_visit_rejects_invalid_priority(monkeypatch):
    # The priority is checked before any database connection is opened
    def connection_not_allowed():
        raise AssertionError("The database must not be used")

    monkeypatch.setattr("carelog.services.visits.get_postgres_connection", connection_not_allowed)

    # bool is a subclass of int in Python, so True and False are tested too
    for priority in (0, 4, -1, True, False, None, "2"):
        with pytest.raises(ValueError):
            add_planned_visit(
                1,
                1,
                1,
                planned_week=date(2026, 11, 23),
                priority=priority
            )


def test_add_planned_visit_rejects_invalid_duration():
    for duration in (0, -30, True, 1.5, "60"):
        with pytest.raises(ValueError):
            add_planned_visit(
                1,
                1,
                1,
                planned_week=date(2026, 11, 23),
                planned_duration_minutes=duration
            )


def test_add_planned_visit_rejects_invalid_schedule():
    invalid_schedules = (
        # No week, date or time
        {},
        # 24.11.2026 is a Tuesday, not a Monday
        {"planned_week": date(2026, 11, 24)},
        {"planned_week": datetime(2026, 11, 23, 10, 0, tzinfo=HELSINKI)},
        {"planned_date": "2026-11-25"},
        # A time without a time zone
        {"planned_at": datetime(2026, 11, 25, 10, 0)},
        # The date is in the following week
        {
            "planned_week": date(2026, 11, 23),
            "planned_date": date(2026, 11, 30),
        },
        # The time is on another day than the date
        {
            "planned_date": date(2026, 11, 26),
            "planned_at": datetime(2026, 11, 25, 10, 0, tzinfo=HELSINKI),
        },
    )

    for schedule in invalid_schedules:
        with pytest.raises(ValueError):
            add_planned_visit(1, 1, 1, **schedule)


def test_add_planned_visit_saves_week_only(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_week=date(2026, 11, 23),
        planned_duration_minutes=60,
        description="  Ruokaostokset  "
    )

    cursor.execute(
        """
        SELECT client_id, service_id, status, priority,
               planned_week, planned_date, planned_at,
               planned_duration_minutes, description
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    assert cursor.fetchone() == (
        client_id,
        service_id,
        "planned",
        2,
        date(2026, 11, 23),
        None,
        None,
        60,
        "Ruokaostokset",
    )

    cursor.execute(
        """
        SELECT duration_minutes, completed_date, started_at, ended_at,
               distance_km, price
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # Nothing about the completed visit is filled in yet
    assert cursor.fetchone() == (None, None, None, None, None, None)


def test_add_planned_visit_saves_date_without_time(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 25),
        planned_duration_minutes=90,
        priority=1
    )

    cursor.execute(
        """
        SELECT planned_week, planned_date, planned_at,
               planned_duration_minutes, priority
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # The week is the Monday of the date, and no time is invented
    assert cursor.fetchone() == (
        date(2026, 11, 23),
        date(2026, 11, 25),
        None,
        90,
        1,
    )


def test_add_planned_visit_saves_exact_time_in_utc(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # 25.11.2026 at 10.00 in Helsinki is 08.00 UTC
    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 25, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120
    )

    # Monday 30.11.2026 at 00.30 in Helsinki is still Sunday in UTC.
    # The week and date must follow the local day.
    early_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 30, 0, 30, tzinfo=HELSINKI)
    )

    sql = """
        SELECT planned_week, planned_date, planned_at,
               planned_duration_minutes
        FROM visits
        WHERE id = %s
    """

    cursor.execute(sql, (visit_id,))

    assert cursor.fetchone() == (
        date(2026, 11, 23),
        date(2026, 11, 25),
        datetime(2026, 11, 25, 8, 0),
        120,
    )

    cursor.execute(sql, (early_visit_id,))

    assert cursor.fetchone() == (
        date(2026, 11, 30),
        date(2026, 11, 30),
        datetime(2026, 11, 29, 22, 30),
        None,
    )


def test_add_planned_visit_saves_null_duration(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_week=date(2026, 11, 23),
        description="   "
    )

    cursor.execute(
        """
        SELECT planned_duration_minutes, duration_minutes, description
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # No default duration is invented
    assert cursor.fetchone() == (None, None, None)


def test_add_planned_visit_rejects_missing_or_archived_client(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, archived_at, created_by_user_id)
        VALUES (%s, %s, CURRENT_TIMESTAMP AT TIME ZONE 'UTC', %s)
        RETURNING id
        """,
        ("Arkistoitu", "Asiakas", user_ids["worker"])
    )

    archived_client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    with pytest.raises(ValueError, match="archived"):
        add_planned_visit(
            user_ids["worker"],
            archived_client_id,
            service_id,
            planned_week=date(2026, 11, 23)
        )

    with pytest.raises(ValueError, match="not found"):
        add_planned_visit(
            user_ids["worker"],
            999999,
            service_id,
            planned_week=date(2026, 11, 23)
        )

    cursor.execute("SELECT COUNT(*) FROM visits")

    assert cursor.fetchone()[0] == 0


def test_add_planned_visit_rolls_back_on_error(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(
        cursor,
        user_id,
        created_by_user_id,
        client_id,
        service_id,
        status,
        priority,
        planned_week,
        planned_date,
        planned_at,
        planned_duration_minutes,
        description,
        price=None
    ):
        cursor.execute(
            "INSERT INTO visits (client_id, service_id, user_id, created_by_user_id) VALUES (%s, %s, %s, %s)",
            (client_id, service_id, user_id, created_by_user_id)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.insert_visit",
        insert_then_fail
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

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_planned_visit(
            user_ids["worker"],
            client_id,
            service_id,
            planned_week=date(2026, 11, 23)
        )

    cursor.execute("SELECT COUNT(*) FROM visits")

    assert cursor.fetchone()[0] == 0


def test_add_planned_visit_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, client_id, for_update=False):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_client",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        add_planned_visit(1, 1, 1, planned_week=date(2026, 11, 23))

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True



# ADD COMPLETED VISIT TESTS


def test_add_completed_visit_rejects_invalid_ids():
    invalid_ids = (
        ("1", 1),
        (None, 1),
        (True, 1),
        (0, 1),
        (1, -1),
        (1, True),
    )

    for client_id, service_id in invalid_ids:
        with pytest.raises(ValueError):
            add_completed_visit(
                1,
                client_id,
                service_id,
                completed_date=date(2026, 11, 18)
            )


def test_add_completed_visit_rejects_invalid_dates_and_times():
    tomorrow = datetime.now(HELSINKI) + timedelta(days=1)

    invalid_values = (
        # No date or start time
        {},
        {"completed_date": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI)},
        {"completed_date": "2026-11-18"},
        # A time without a time zone
        {"started_at": datetime(2026, 11, 18, 10, 0)},
        # An end time without a start time
        {
            "completed_date": date(2026, 11, 18),
            "ended_at": datetime(2026, 11, 18, 11, 0, tzinfo=HELSINKI),
        },
        # The end is before the start, or at the same minute
        {
            "started_at": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
            "ended_at": datetime(2026, 11, 18, 9, 0, tzinfo=HELSINKI),
        },
        {
            "started_at": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
            "ended_at": datetime(2026, 11, 18, 10, 0, 30, tzinfo=HELSINKI),
        },
        # The date does not match the local day of the start time
        {
            "completed_date": date(2026, 11, 19),
            "started_at": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
        },
        # A completed visit cannot be in the future
        {"completed_date": tomorrow.date()},
        {"started_at": tomorrow},
    )

    for values in invalid_values:
        with pytest.raises(ValueError):
            add_completed_visit(1, 1, 1, **values)


def test_add_completed_visit_rejects_invalid_or_conflicting_duration():
    for duration in (0, -30, True, 1.5, "90"):
        with pytest.raises(ValueError):
            add_completed_visit(
                1,
                1,
                1,
                completed_date=date(2026, 11, 18),
                duration_minutes=duration
            )

    # 10.00–11.30 is 90 minutes, not 60
    with pytest.raises(ValueError, match="Duration does not match"):
        add_completed_visit(
            1,
            1,
            1,
            started_at=datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
            ended_at=datetime(2026, 11, 18, 11, 30, tzinfo=HELSINKI),
            duration_minutes=60
        )

    # Clocks move forward at 03.00 on 29.3.2026, so 02.30–04.30 on the
    # wall clock is only 60 minutes of real time.
    with pytest.raises(ValueError, match="Duration does not match"):
        add_completed_visit(
            1,
            1,
            1,
            started_at=datetime(2026, 3, 29, 2, 30, tzinfo=HELSINKI),
            ended_at=datetime(2026, 3, 29, 4, 30, tzinfo=HELSINKI),
            duration_minutes=120
        )


def test_add_completed_visit_rejects_invalid_distance_and_price():
    invalid_values = (
        {"distance_km": -1},
        {"distance_km": True},
        {"distance_km": float("nan")},
        {"distance_km": Decimal("8.555")},
        {"price": -1},
        {"price": True},
        {"price": float("inf")},
        {"price": "35"},
        {"price": Decimal("35.555")},
        {"price": Decimal("100000000.00")},
    )

    for values in invalid_values:
        with pytest.raises(ValueError):
            add_completed_visit(
                1,
                1,
                1,
                completed_date=date(2026, 11, 18),
                **values
            )


def test_add_completed_visit_saves_date_only(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        completed_date=date(2026, 11, 18)
    )

    cursor.execute(
        """
        SELECT client_id, service_id, status, completed_date,
               duration_minutes, started_at, ended_at,
               description, distance_km, price
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    assert cursor.fetchone() == (
        client_id,
        service_id,
        "completed",
        date(2026, 11, 18),
        None,
        None,
        None,
        None,
        None,
        None,
    )

    cursor.execute(
        """
        SELECT planned_week, planned_date, planned_at,
               planned_duration_minutes
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # A visit logged directly has no plan
    assert cursor.fetchone() == (None, None, None, None)


def test_add_completed_visit_saves_date_and_duration(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        completed_date=date(2026, 11, 18),
        duration_minutes=90,
        description="  Kaupassa käynti  ",
        distance_km=8.5,
        price=0
    )

    cursor.execute(
        """
        SELECT completed_date, duration_minutes, started_at, ended_at,
               description, distance_km, price
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # No start or end time is invented from the duration
    assert cursor.fetchone() == (
        date(2026, 11, 18),
        90,
        None,
        None,
        "Kaupassa käynti",
        Decimal("8.50"),
        Decimal("0.00"),
    )


def test_add_completed_visit_saves_exact_times_in_utc(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Seconds are dropped, so 10.00–11.30 is exactly 90 minutes
    visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        started_at=datetime(2026, 11, 18, 10, 0, 45, tzinfo=HELSINKI),
        ended_at=datetime(2026, 11, 18, 11, 30, 10, tzinfo=HELSINKI)
    )

    cursor.execute(
        """
        SELECT status, completed_date, started_at, ended_at,
               duration_minutes, planned_week, planned_at
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # 10.00 in Helsinki is 08.00 UTC
    assert cursor.fetchone() == (
        "completed",
        date(2026, 11, 18),
        datetime(2026, 11, 18, 8, 0),
        datetime(2026, 11, 18, 9, 30),
        90,
        None,
        None,
    )


def test_add_completed_visit_rejects_archived_client(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, archived_at, created_by_user_id)
        VALUES (%s, %s, CURRENT_TIMESTAMP AT TIME ZONE 'UTC', %s)
        RETURNING id
        """,
        ("Arkistoitu", "Asiakas", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    with pytest.raises(ValueError, match="archived"):
        add_completed_visit(
            user_ids["worker"],
            client_id,
            service_id,
            completed_date=date(2026, 11, 18)
        )

    cursor.execute("SELECT COUNT(*) FROM visits")

    assert cursor.fetchone()[0] == 0


def test_add_completed_visit_rolls_back_on_error(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(
        cursor,
        user_id,
        created_by_user_id,
        client_id,
        service_id,
        status,
        priority,
        description=None,
        completed_date=None,
        started_at=None,
        ended_at=None,
        duration_minutes=None,
        distance_km=None,
        price=None
    ):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, status, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (client_id, service_id, status, user_id, created_by_user_id)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.insert_visit",
        insert_then_fail
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

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_completed_visit(
            user_ids["worker"],
            client_id,
            service_id,
            completed_date=date(2026, 11, 18)
        )

    cursor.execute("SELECT COUNT(*) FROM visits")

    assert cursor.fetchone()[0] == 0


def test_add_completed_visit_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, client_id, for_update=False):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_client",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        add_completed_visit(1, 1, 1, completed_date=date(2026, 11, 18))

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET VISIT TESTS


def test_get_visit_rejects_invalid_id():
    for visit_id in ("1", None, 0, -1, 1.0):
        with pytest.raises(ValueError):
            get_visit(1, visit_id)


def test_get_visit_rejects_boolean_id():
    with pytest.raises(ValueError):
        get_visit(1, True)


def test_get_visit_returns_planned_visit(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 25, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120,
        priority=1,
        description="Ruokaostokset"
    )

    visit = get_visit(user_ids["worker"], visit_id)

    # All columns are returned, including the ones added by v009 and the
    # user columns of v014
    assert set(visit) == {
        "id",
        "client_id",
        "service_id",
        "status",
        "priority",
        "planned_week",
        "planned_date",
        "planned_at",
        "planned_duration_minutes",
        "completed_date",
        "duration_minutes",
        "started_at",
        "ended_at",
        "description",
        "distance_km",
        "price",
        "created_at",
        "updated_at",
        "user_id",
        "created_by_user_id",
        "updated_by_user_id",
    }

    assert visit["id"] == visit_id
    assert visit["client_id"] == client_id
    assert visit["service_id"] == service_id
    assert visit["status"] == "planned"
    assert visit["priority"] == 1
    assert visit["planned_week"] == date(2026, 11, 23)
    assert visit["planned_date"] == date(2026, 11, 25)

    # Returned in UTC, as stored
    assert visit["planned_at"] == datetime(2026, 11, 25, 8, 0)
    assert visit["planned_duration_minutes"] == 120
    assert visit["description"] == "Ruokaostokset"

    # The completed fields are still empty
    assert visit["completed_date"] is None
    assert visit["duration_minutes"] is None
    assert visit["started_at"] is None
    assert visit["ended_at"] is None

    assert isinstance(visit["created_at"], datetime)
    assert isinstance(visit["updated_at"], datetime)


def test_get_visit_returns_completed_visit(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        started_at=datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
        ended_at=datetime(2026, 11, 18, 11, 30, tzinfo=HELSINKI),
        distance_km=Decimal("8.50"),
        price=Decimal("48.00")
    )

    visit = get_visit(user_ids["worker"], visit_id)

    assert visit["status"] == "completed"
    assert visit["completed_date"] == date(2026, 11, 18)
    assert visit["started_at"] == datetime(2026, 11, 18, 8, 0)
    assert visit["ended_at"] == datetime(2026, 11, 18, 9, 30)
    assert visit["duration_minutes"] == 90
    assert visit["distance_km"] == Decimal("8.50")
    assert visit["price"] == Decimal("48.00")

    # A visit logged directly has no plan
    assert visit["planned_week"] is None
    assert visit["planned_date"] is None
    assert visit["planned_at"] is None
    assert visit["planned_duration_minutes"] is None


def test_get_visit_returns_none_if_not_found(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    visit = get_visit(user_ids["worker"], 999999)

    assert visit is None


def test_get_visit_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_visit",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_visit(1, 1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET CLIENT VISITS TESTS


def test_get_client_visits_rejects_invalid_client_id():
    for client_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            get_client_visits(1, client_id)


def test_get_client_visits_returns_empty_list(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    visits = get_client_visits(user_ids["worker"], client_id)

    assert visits == []


def test_get_client_visits_returns_all_statuses_newest_first(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Inserted in mixed order: status, planned week, planned date,
    # completed date and planned duration
    visit_rows = (
        ("completed", None, None, date(2026, 11, 18), None),
        ("cancelled", date(2026, 11, 9), None, None, 60),
        ("planned", date(2026, 11, 30), None, None, 90),
        ("planned", date(2026, 11, 23), date(2026, 11, 25), None, 120),
    )

    for status, week, planned_date, completed_date, duration in visit_rows:
        cursor.execute(
            """
            INSERT INTO visits (
                client_id, service_id, status, planned_week,
                planned_date, completed_date, planned_duration_minutes, user_id, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                client_id,
                service_id,
                status,
                week,
                planned_date,
                completed_date,
                duration, user_ids["worker"], user_ids["worker"]
            )
        )

    visits = get_client_visits(user_ids["worker"], client_id)

    assert len(visits) == 4

    # Newest first: week 30.11, day 25.11, completed 18.11, week 9.11
    assert visits[0]["status"] == "planned"
    assert visits[0]["planned_week"] == date(2026, 11, 30)
    assert visits[1]["planned_date"] == date(2026, 11, 25)
    assert visits[2]["status"] == "completed"
    assert visits[2]["completed_date"] == date(2026, 11, 18)
    assert visits[3]["status"] == "cancelled"

    # Each visit has the same fields as get_visit() returns
    assert len(visits[0]) == 18
    assert visits[1]["planned_duration_minutes"] == 120
    assert visits[1]["duration_minutes"] is None


def test_get_client_visits_excludes_other_clients_visits(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Toinen", "Asiakas", user_ids["worker"])
    )

    other_client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    for visit_client_id in (client_id, other_client_id, other_client_id):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (visit_client_id, service_id, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
        )

    visits = get_client_visits(user_ids["worker"], client_id)

    assert len(visits) == 1
    assert visits[0]["client_id"] == client_id


def test_get_client_visits_returns_archived_client_visits(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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
        INSERT INTO visits (client_id, service_id, status, completed_date, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "completed", date(2026, 11, 18), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    # The client is archived after the visit
    cursor.execute(
        "UPDATE clients SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = %s",
        (client_id,)
    )

    visits = get_client_visits(user_ids["worker"], client_id)

    assert len(visits) == 1
    assert visits[0]["id"] == visit_id


def test_get_client_visits_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, client_id, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_client_visits",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_client_visits(1, 1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET PLANNED VISITS TESTS


def test_get_planned_visits_returns_empty_list(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    visits = get_planned_visits(user_ids["worker"])

    assert visits == []


def test_get_planned_visits_returns_only_planned_in_order(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # The description is used as a label. Times are in UTC.
    visit_rows = (
        ("A", "planned", date(2026, 11, 30), None, None, 2),
        ("B", "planned", date(2026, 11, 23), date(2026, 11, 25), datetime(2026, 11, 25, 12, 0), 2),
        ("C", "planned", date(2026, 11, 23), date(2026, 11, 25), None, 3),
        ("D", "planned", date(2026, 11, 23), date(2026, 11, 25), None, 1),
        ("E", "planned", date(2026, 11, 23), date(2026, 11, 25), datetime(2026, 11, 25, 8, 0), 3),
        ("F", "planned", date(2026, 11, 23), None, None, 2),
        # A planned visit left in a past week is still shown
        ("G", "planned", date(2026, 11, 2), None, None, 2),
        ("H", "completed", date(2026, 11, 23), None, None, 2),
        ("I", "cancelled", date(2026, 11, 23), None, None, 2),
    )

    for label, status, week, planned_date, planned_at, priority in visit_rows:
        cursor.execute(
            """
            INSERT INTO visits (
                client_id, service_id, status, planned_week,
                planned_date, planned_at, priority, description, user_id, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                client_id,
                service_id,
                status,
                week,
                planned_date,
                planned_at,
                priority,
                label, user_ids["worker"], user_ids["worker"]
            )
        )

    visits = get_planned_visits(user_ids["worker"])

    labels = []

    for visit in visits:
        labels.append(visit["description"])

    # By week, then day (week-only visits first), then time (day-only
    # visits first), then priority. Completed and cancelled are left out.
    assert labels == ["G", "F", "D", "C", "E", "B", "A"]


def test_get_planned_visits_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_planned_visits",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_planned_visits(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET WEEK VISITS TESTS


def test_get_week_visits_rejects_invalid_week_start():
    invalid_values = (
        # 24.11.2026 is a Tuesday
        date(2026, 11, 24),
        datetime(2026, 11, 23, 0, 0),
        "2026-11-23",
        None,
    )

    for week_start in invalid_values:
        with pytest.raises(ValueError):
            get_week_visits(1, week_start)


def test_get_week_visits_uses_local_week_limits(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


    class FakeConnection:
        def cursor(self):
            return self

        def close(self):
            pass

    calls = []

    def select_and_remember(
        cursor,
        week_start,
        next_week_start,
        week_start_utc,
        next_week_start_utc,
        owner_user_id=None
    ):
        calls.append(
            (week_start, next_week_start, week_start_utc, next_week_start_utc)
        )
        return []

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        FakeConnection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_week_visits",
        select_and_remember
    )

    get_week_visits(1, date(2026, 11, 23))

    # Clocks move forward on Sunday 29.3.2026
    get_week_visits(1, date(2026, 3, 23))

    # Helsinki is UTC+2 in winter, so the week starts at 22.00 UTC
    assert calls[0] == (
        date(2026, 11, 23),
        date(2026, 11, 30),
        datetime(2026, 11, 22, 22, 0),
        datetime(2026, 11, 29, 22, 0),
    )

    # The week ends in summer time (UTC+3), so it is only 167 hours long
    assert calls[1] == (
        date(2026, 3, 23),
        date(2026, 3, 30),
        datetime(2026, 3, 22, 22, 0),
        datetime(2026, 3, 29, 21, 0),
    )


def test_get_week_visits_returns_visits_of_week(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Label, status, planned week, planned day, completed day,
    # planned duration and actual duration
    visit_rows = (
        ("week only", "planned", date(2026, 11, 23), None, None, 60, None),
        ("planned day", "planned", date(2026, 11, 23), date(2026, 11, 25), None, 90, None),
        ("sunday done", "completed", None, None, date(2026, 11, 29), None, 75),
        ("next monday done", "completed", None, None, date(2026, 11, 30), None, 60),
        ("previous sunday done", "completed", None, None, date(2026, 11, 22), None, 60),
        ("next week", "planned", date(2026, 11, 30), None, None, None, None),
        ("cancelled", "cancelled", date(2026, 11, 23), date(2026, 11, 24), None, None, None),
    )

    for row in visit_rows:
        label, status, week, planned_date, completed_date, planned_minutes, minutes = row

        cursor.execute(
            """
            INSERT INTO visits (
                client_id, service_id, status, planned_week, planned_date,
                completed_date, planned_duration_minutes, duration_minutes,
                description, user_id, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                client_id,
                service_id,
                status,
                week,
                planned_date,
                completed_date,
                planned_minutes,
                minutes,
                label, user_ids["worker"], user_ids["worker"]
            )
        )

    visits = get_week_visits(user_ids["worker"], date(2026, 11, 23))

    labels = []

    for visit in visits:
        labels.append(visit["description"])

    # Monday to Sunday only, no cancelled visits, the week-only visit first
    assert labels == ["week only", "planned day", "sunday done"]

    # Planned and actual durations stay separate and unchanged
    assert visits[1]["planned_duration_minutes"] == 90
    assert visits[1]["duration_minutes"] is None
    assert visits[2]["planned_duration_minutes"] is None
    assert visits[2]["duration_minutes"] == 75


def test_get_week_visits_uses_local_time_for_old_completed_visits(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Old completed visits without completed_date. Times are in UTC.
    # The week of 23.3.2026 ends in summer time.
    visit_rows = (
        # Sunday 22.3 at 23.30 in Helsinki: previous week
        ("before", datetime(2026, 3, 22, 21, 30)),
        # Monday 23.3 at 00.30 in Helsinki
        ("monday", datetime(2026, 3, 22, 22, 30)),
        # Sunday 29.3 at 23.30 in Helsinki (summer time)
        ("sunday", datetime(2026, 3, 29, 20, 30)),
        # Monday 30.3 at 00.30 in Helsinki (summer time): next week
        ("after", datetime(2026, 3, 29, 21, 30)),
    )

    for label, started_at in visit_rows:
        cursor.execute(
            """
            INSERT INTO visits (
                client_id, service_id, status, started_at, description, user_id, created_by_user_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (client_id, service_id, "completed", started_at, label, user_ids["worker"], user_ids["worker"])
        )

    visits = get_week_visits(user_ids["worker"], date(2026, 3, 23))

    labels = []

    for visit in visits:
        labels.append(visit["description"])

    assert labels == ["monday", "sunday"]


def test_get_week_visits_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def select_then_fail(
        cursor,
        week_start,
        next_week_start,
        week_start_utc,
        next_week_start_utc,
        owner_user_id=None
    ):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_week_visits",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_week_visits(1, date(2026, 11, 23))

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# UPDATE VISIT TESTS


def test_update_visit_rejects_invalid_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            update_visit(1, visit_id, {"priority": 1})


def test_update_visit_rejects_invalid_changes(monkeypatch):
    # The changes are checked before any database connection is opened
    def connection_not_allowed():
        raise AssertionError("The database must not be used")

    monkeypatch.setattr("carelog.services.visits.get_postgres_connection", connection_not_allowed)

    invalid_changes = (
        None,
        [],
        {},
        # Fields that cannot be changed here
        {"client_id": 2},
        {"status": "completed"},
        {"duration_minutes": 60},
        {"price": 10},
        # Invalid values
        {"service_id": True},
        {"priority": 0},
        {"priority": 4},
        {"priority": -1},
        {"priority": True},
        {"priority": False},
        {"priority": None},
        {"priority": "1"},
        {"planned_duration_minutes": 0},
        {"description": 123},
        {"planned_week": date(2026, 11, 24)},
        {"planned_date": "2026-11-25"},
        {"planned_at": datetime(2026, 11, 25, 10, 0)},
    )

    for changes in invalid_changes:
        with pytest.raises(ValueError):
            update_visit(1, 1, changes)


def test_update_visit_changes_service_priority_and_duration(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Apteekkiasiointi", user_ids["worker"])
    )

    new_service_id = cursor.fetchone()[0]

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 25),
        planned_duration_minutes=60
    )

    updated = update_visit(
        user_ids["worker"],
        visit_id,
        {
            "service_id": new_service_id,
            "priority": 1,
            "planned_duration_minutes": 90,
            "description": "  Reseptilääkkeet  "
        }
    )

    assert updated is True

    cursor.execute(
        """
        SELECT service_id, priority, planned_duration_minutes, description,
               planned_week, planned_date, status
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # The schedule was not given, so it stays the same
    assert cursor.fetchone() == (
        new_service_id,
        1,
        90,
        "Reseptilääkkeet",
        date(2026, 11, 23),
        date(2026, 11, 25),
        "planned",
    )

    # Saving the same value again is still a successful update
    assert update_visit(user_ids["worker"], visit_id, {"priority": 1}) is True


def test_update_visit_moves_visit_to_another_time(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Wednesday at 10.00, 120 minutes
    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 25, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120
    )

    sql = """
        SELECT planned_week, planned_date, planned_at,
               planned_duration_minutes
        FROM visits
        WHERE id = %s
    """

    # Moved to Thursday at 12.00
    update_visit(
        user_ids["worker"],
        visit_id,
        {"planned_at": datetime(2026, 11, 26, 12, 0, tzinfo=HELSINKI)}
    )

    cursor.execute(sql, (visit_id,))

    assert cursor.fetchone() == (
        date(2026, 11, 23),
        date(2026, 11, 26),
        datetime(2026, 11, 26, 10, 0),
        120,
    )

    # Moved to the next week: the week follows the time
    update_visit(
        user_ids["worker"],
        visit_id,
        {"planned_at": datetime(2026, 12, 1, 9, 0, tzinfo=HELSINKI)}
    )

    cursor.execute(sql, (visit_id,))

    assert cursor.fetchone() == (
        date(2026, 11, 30),
        date(2026, 12, 1),
        datetime(2026, 12, 1, 7, 0),
        120,
    )


def test_update_visit_clears_time_and_moves_day(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 25, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120
    )

    sql = """
        SELECT planned_week, planned_date, planned_at,
               planned_duration_minutes
        FROM visits
        WHERE id = %s
    """

    # From an exact time to the day level: the day and week stay
    update_visit(user_ids["worker"], visit_id, {"planned_at": None})

    cursor.execute(sql, (visit_id,))

    assert cursor.fetchone() == (
        date(2026, 11, 23),
        date(2026, 11, 25),
        None,
        120,
    )

    # To another day in the next week
    update_visit(user_ids["worker"], visit_id, {"planned_date": date(2026, 12, 2)})

    cursor.execute(sql, (visit_id,))

    assert cursor.fetchone() == (date(2026, 11, 30), date(2026, 12, 2), None, 120)

    # From the day level to the week level: only the week stays
    update_visit(user_ids["worker"], visit_id, {"planned_date": None})

    cursor.execute(sql, (visit_id,))

    assert cursor.fetchone() == (date(2026, 11, 30), None, None, 120)


def test_update_visit_rejects_conflicting_schedule(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Wednesday 25.11.2026 at 10.00
    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 25, 10, 0, tzinfo=HELSINKI)
    )

    conflicting_changes = (
        # A new day while the old time would stay on the old day
        {"planned_date": date(2026, 11, 26)},
        # A week that does not contain the planned day
        {"planned_week": date(2026, 11, 30)},
        # Clearing the day but keeping the time
        {"planned_date": None},
        # A new time on another day than the given date
        {
            "planned_at": datetime(2026, 11, 26, 12, 0, tzinfo=HELSINKI),
            "planned_date": date(2026, 11, 25),
        },
        # A planned visit must keep at least its week
        {"planned_at": None, "planned_date": None, "planned_week": None},
    )

    for changes in conflicting_changes:
        with pytest.raises(ValueError):
            update_visit(user_ids["worker"], visit_id, changes)

    cursor.execute(
        "SELECT planned_week, planned_date, planned_at FROM visits WHERE id = %s",
        (visit_id,)
    )

    assert cursor.fetchone() == (
        date(2026, 11, 23),
        date(2026, 11, 25),
        datetime(2026, 11, 25, 8, 0),
    )


def test_update_visit_returns_false_if_not_found(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    updated = update_visit(user_ids["worker"], 999999, {"priority": 1})

    assert updated is False


def test_update_visit_rejects_completed_and_cancelled_visits(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    for status in ("completed", "cancelled"):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, status, planned_week, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (client_id, service_id, status, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
        )

        visit_id = cursor.fetchone()[0]

        with pytest.raises(ValueError, match="Only planned visits"):
            update_visit(user_ids["worker"], visit_id, {"priority": 1})

        cursor.execute(
            "SELECT status, priority FROM visits WHERE id = %s",
            (visit_id,)
        )

        assert cursor.fetchone() == (status, 2)


def test_update_visit_rolls_back_on_error(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def update_then_fail(cursor, updated_by_user_id, visit_id, changes):
        cursor.execute(
            "UPDATE visits SET priority = %s WHERE id = %s",
            (1, visit_id)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.update_visit_record",
        update_then_fail
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_week=date(2026, 11, 23)
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_visit(user_ids["worker"], visit_id, {"priority": 1})

    cursor.execute(
        "SELECT priority FROM visits WHERE id = %s",
        (visit_id,)
    )

    assert cursor.fetchone()[0] == 2


def test_update_visit_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, visit_id, for_update=False, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_visit",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        update_visit(1, 1, {"priority": 1})

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# COMPLETE VISIT TESTS


def test_complete_visit_rejects_invalid_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            complete_visit(1, visit_id)


def test_complete_visit_rejects_invalid_times_and_duration():
    tomorrow = datetime.now(HELSINKI) + timedelta(days=1)

    invalid_values = (
        {"duration_minutes": 0},
        {"duration_minutes": True},
        {"duration_minutes": "90"},
        {"completed_date": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI)},
        {"completed_date": tomorrow.date()},
        {"started_at": datetime(2026, 11, 18, 10, 0)},
        {"started_at": tomorrow},
        {"ended_at": datetime(2026, 11, 18, 11, 0, tzinfo=HELSINKI)},
        {
            "started_at": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
            "ended_at": datetime(2026, 11, 18, 9, 0, tzinfo=HELSINKI),
        },
        {
            "started_at": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
            "ended_at": datetime(2026, 11, 18, 11, 30, tzinfo=HELSINKI),
            "duration_minutes": 60,
        },
        {
            "completed_date": date(2026, 11, 19),
            "started_at": datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
        },
    )

    for values in invalid_values:
        with pytest.raises(ValueError):
            complete_visit(1, 1, **values)


def test_complete_visit_with_one_click_uses_plan(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # 18.11.2026 at 10.00, 120 minutes
    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120,
        priority=1,
        description="Ruokaostokset"
    )

    completed = complete_visit(user_ids["worker"], visit_id)

    assert completed is True

    cursor.execute(
        """
        SELECT status, completed_date, duration_minutes, started_at, ended_at
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # The planned day, time and duration are accepted as the actual ones.
    # 10.00–12.00 in Helsinki is 08.00–10.00 UTC.
    assert cursor.fetchone() == (
        "completed",
        date(2026, 11, 18),
        120,
        datetime(2026, 11, 18, 8, 0),
        datetime(2026, 11, 18, 10, 0),
    )

    cursor.execute(
        """
        SELECT client_id, service_id, planned_week, planned_date, planned_at,
               planned_duration_minutes, priority, description
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # The plan itself is not changed
    assert cursor.fetchone() == (
        client_id,
        service_id,
        date(2026, 11, 16),
        date(2026, 11, 18),
        datetime(2026, 11, 18, 8, 0),
        120,
        1,
        "Ruokaostokset",
    )


def test_complete_visit_with_changed_duration(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120
    )

    complete_visit(user_ids["worker"], visit_id, duration_minutes=90)

    cursor.execute(
        """
        SELECT planned_duration_minutes, duration_minutes, started_at, ended_at
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # The start stays, the end follows the new duration, and the
    # planned duration is kept as it was
    assert cursor.fetchone() == (
        120,
        90,
        datetime(2026, 11, 18, 8, 0),
        datetime(2026, 11, 18, 9, 30),
    )


def test_complete_visit_with_own_day_or_times(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    other_day_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120
    )

    own_times_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 18, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120
    )

    # Done on another day: the old day's time is not copied
    complete_visit(user_ids["worker"], other_day_visit_id, completed_date=date(2026, 11, 19))

    # Done at other times: the user's times are used
    complete_visit(
        user_ids["worker"],
        own_times_visit_id,
        started_at=datetime(2026, 11, 18, 13, 0, tzinfo=HELSINKI),
        ended_at=datetime(2026, 11, 18, 14, 15, tzinfo=HELSINKI)
    )

    sql = """
        SELECT completed_date, duration_minutes, started_at, ended_at
        FROM visits
        WHERE id = %s
    """

    cursor.execute(sql, (other_day_visit_id,))

    assert cursor.fetchone() == (date(2026, 11, 19), 120, None, None)

    cursor.execute(sql, (own_times_visit_id,))

    assert cursor.fetchone() == (
        date(2026, 11, 18),
        75,
        datetime(2026, 11, 18, 11, 0),
        datetime(2026, 11, 18, 12, 15),
    )


def test_complete_visit_before_planned_end_time(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Started 30 minutes ago and planned for 120 minutes, so the planned
    # end time has not come yet
    planned_at = datetime.now(HELSINKI) - timedelta(minutes=30)

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=planned_at,
        planned_duration_minutes=120
    )

    completed = complete_visit(user_ids["worker"], visit_id)

    assert completed is True

    cursor.execute(
        """
        SELECT status, completed_date, duration_minutes, started_at, ended_at
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    # The planned times are not saved as actual times, because the end
    # would be in the future. The day and the duration are kept.
    assert cursor.fetchone() == (
        "completed",
        planned_at.date(),
        120,
        None,
        None,
    )


def test_complete_visit_without_exact_times(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Planned for a day without a time or a duration
    day_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 18)
    )

    # Planned only for a week, with a duration
    week_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_week=date(2026, 11, 16),
        planned_duration_minutes=60
    )

    complete_visit(user_ids["worker"], day_visit_id)

    # A week-only visit gets today's date. The date is read before and
    # after the call, so the test also works around midnight.
    today_before = datetime.now(HELSINKI).date()
    complete_visit(user_ids["worker"], week_visit_id)
    today_after = datetime.now(HELSINKI).date()

    sql = """
        SELECT completed_date, duration_minutes, started_at, ended_at
        FROM visits
        WHERE id = %s
    """

    cursor.execute(sql, (day_visit_id,))

    # No times are invented and the missing duration stays NULL
    assert cursor.fetchone() == (date(2026, 11, 18), None, None, None)

    cursor.execute(sql, (week_visit_id,))

    completed_date, duration, started_at, ended_at = cursor.fetchone()

    assert completed_date in (today_before, today_after)
    assert duration == 60
    assert started_at is None
    assert ended_at is None


def test_complete_visit_returns_false_if_not_found(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    completed = complete_visit(user_ids["worker"], 999999)

    assert completed is False


def test_complete_visit_rejects_completed_and_cancelled_visits(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 18),
        planned_duration_minutes=60
    )

    complete_visit(user_ids["worker"], visit_id)

    # A second completion is not allowed
    with pytest.raises(ValueError, match="Only planned visits"):
        complete_visit(user_ids["worker"], visit_id, duration_minutes=90)

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16), user_ids["worker"], user_ids["worker"])
    )

    cancelled_visit_id = cursor.fetchone()[0]

    with pytest.raises(ValueError, match="Only planned visits"):
        complete_visit(user_ids["worker"], cancelled_visit_id)

    cursor.execute(
        "SELECT duration_minutes FROM visits WHERE id = %s",
        (visit_id,)
    )

    assert cursor.fetchone()[0] == 60

    cursor.execute(
        "SELECT status, completed_date FROM visits WHERE id = %s",
        (cancelled_visit_id,)
    )

    assert cursor.fetchone() == ("cancelled", None)


def test_complete_visit_rolls_back_on_error(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def complete_then_fail(
        cursor,
        updated_by_user_id,
        visit_id,
        completed_date,
        duration_minutes,
        started_at,
        ended_at
    ):
        cursor.execute(
            "UPDATE visits SET status = 'completed' WHERE id = %s",
            (visit_id,)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.complete_visit_record",
        complete_then_fail
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 18)
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        complete_visit(user_ids["worker"], visit_id)

    cursor.execute(
        "SELECT status, completed_date FROM visits WHERE id = %s",
        (visit_id,)
    )

    assert cursor.fetchone() == ("planned", None)


def test_complete_visit_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def select_then_fail(cursor, visit_id, for_update=False, owner_user_id=None):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_visit",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        complete_visit(1, 1)

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# CANCEL VISIT TESTS


def test_cancel_visit_rejects_invalid_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            cancel_visit(1, visit_id)


def test_cancel_visit_changes_only_status(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_at=datetime(2026, 11, 25, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=120,
        priority=1,
        description="Ruokaostokset"
    )

    sql = """
        SELECT client_id, service_id, priority, planned_week, planned_date,
               planned_at, planned_duration_minutes, description, price,
               distance_km, completed_date, duration_minutes, started_at,
               ended_at, created_at
        FROM visits
        WHERE id = %s
    """

    cursor.execute(sql, (visit_id,))
    values_before = cursor.fetchone()

    cancelled = cancel_visit(user_ids["worker"], visit_id)

    assert cancelled is True

    cursor.execute("SELECT status FROM visits WHERE id = %s", (visit_id,))

    assert cursor.fetchone()[0] == "cancelled"

    # Everything else, including the plan and created_at, is kept
    cursor.execute(sql, (visit_id,))

    assert cursor.fetchone() == values_before


def test_cancelled_visit_stays_in_history_only(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 18),
        planned_duration_minutes=60
    )

    cancel_visit(user_ids["worker"], visit_id)

    # Shown in the visit itself and in the client's history
    assert get_visit(user_ids["worker"], visit_id)["status"] == "cancelled"

    history = get_client_visits(user_ids["worker"], client_id)

    assert len(history) == 1
    assert history[0]["id"] == visit_id

    # Left out of the planning views
    assert get_planned_visits(user_ids["worker"]) == []
    assert get_week_visits(user_ids["worker"], date(2026, 11, 16)) == []

    # Cannot be changed or completed any more
    with pytest.raises(ValueError, match="Only planned visits"):
        update_visit(user_ids["worker"], visit_id, {"priority": 1})

    with pytest.raises(ValueError, match="Only planned visits"):
        complete_visit(user_ids["worker"], visit_id)


def test_cancel_visit_returns_false_if_not_found(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    cancelled = cancel_visit(user_ids["worker"], 999999)

    assert cancelled is False


def test_cancel_visit_rejects_completed_and_cancelled_visits(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    completed_visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        completed_date=date(2026, 11, 18),
        duration_minutes=60
    )

    planned_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_week=date(2026, 11, 23)
    )

    cancel_visit(user_ids["worker"], planned_visit_id)

    # A completed visit is part of the work history
    with pytest.raises(ValueError, match="Only planned visits"):
        cancel_visit(user_ids["worker"], completed_visit_id)

    # A visit cannot be cancelled twice
    with pytest.raises(ValueError, match="Only planned visits"):
        cancel_visit(user_ids["worker"], planned_visit_id)

    cursor.execute(
        "SELECT status FROM visits WHERE id = %s",
        (completed_visit_id,)
    )

    assert cursor.fetchone()[0] == "completed"


def test_cancel_visit_rolls_back_on_error(
    postgres_cursor_with_visit_scheduling,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_scheduling

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def cancel_then_fail(cursor, updated_by_user_id, visit_id, owner_user_id=None):
        cursor.execute(
            "UPDATE visits SET status = 'cancelled' WHERE id = %s",
            (visit_id,)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.cancel_visit_record",
        cancel_then_fail
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_week=date(2026, 11, 23)
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        cancel_visit(user_ids["worker"], visit_id)

    cursor.execute("SELECT status FROM visits WHERE id = %s", (visit_id,))

    assert cursor.fetchone()[0] == "planned"


def test_cancel_visit_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


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

    def cancel_then_fail(cursor, updated_by_user_id, visit_id, owner_user_id=None):
        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.cancel_visit_record",
        cancel_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        cancel_visit(1, 1)

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# VISIT NOTE INTEGRATION TESTS


def test_visit_functions_reject_invalid_note():
    for note in (123, ["Kaupassa"], "ä" * 32768):
        with pytest.raises(ValueError):
            add_planned_visit(1, 1, 1, planned_week=date(2026, 11, 23), note=note)

        with pytest.raises(ValueError):
            add_completed_visit(1, 1, 1, completed_date=date(2026, 11, 18), note=note)

        with pytest.raises(ValueError):
            complete_visit(1, 1, note=note)


def test_visit_functions_save_note_with_visit(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    planned_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_week=date(2026, 11, 23),
        note="  Muista ostoslista  "
    )

    completed_visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        completed_date=date(2026, 11, 18),
        note="Käytiin kaupassa.\nHaettiin lääkkeet."
    )

    visit_to_complete_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 18),
        planned_duration_minutes=60
    )

    # The admin completes the worker's visit and writes the note
    assert complete_visit(user_ids["admin"], visit_to_complete_id, note="Kaikki hyvin") is True

    cursor.execute(
        "SELECT visit_id, content, created_by_user_id, updated_by_user_id "
        "FROM visit_notes ORDER BY id"
    )

    # Each note belongs to its own visit, stripped and with line breaks
    # kept. The creator of a note is the user who saved it.
    assert cursor.fetchall() == [
        (planned_visit_id, "Muista ostoslista", user_ids["worker"], None),
        (completed_visit_id, "Käytiin kaupassa.\nHaettiin lääkkeet.", user_ids["worker"], None),
        (visit_to_complete_id, "Kaikki hyvin", user_ids["admin"], None),
    ]

    cursor.execute(
        "SELECT status, duration_minutes FROM visits WHERE id = %s",
        (visit_to_complete_id,)
    )

    # The completion itself still uses the planned duration
    assert cursor.fetchone() == ("completed", 60)


def test_visit_functions_skip_empty_notes(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    # Without a note, and with empty or blank notes
    add_planned_visit(user_ids["worker"], client_id, service_id, planned_week=date(2026, 11, 23))
    add_planned_visit(user_ids["worker"], client_id, service_id, planned_week=date(2026, 11, 23), note="")
    add_completed_visit(user_ids["worker"], client_id, service_id, completed_date=date(2026, 11, 18), note="   ")

    visit_id = add_planned_visit(user_ids["worker"], client_id, service_id, planned_date=date(2026, 11, 18))

    assert complete_visit(user_ids["worker"], visit_id, note="\n\t") is True

    cursor.execute("SELECT COUNT(*) FROM visits")

    assert cursor.fetchone()[0] == 4

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_complete_visit_does_not_add_note_without_completion(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    completed_visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        completed_date=date(2026, 11, 18)
    )

    # A missing visit
    assert complete_visit(user_ids["worker"], 999999, note="Ei tallenneta") is False

    # A visit that is already completed
    with pytest.raises(ValueError, match="Only planned visits"):
        complete_visit(user_ids["worker"], completed_visit_id, note="Ei tallenneta")

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_add_visit_rolls_back_when_note_insert_fails(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    # A real database error: the note points to a visit that does not
    # exist, so the foreign key rejects it after the visit was inserted.
    def insert_note_with_wrong_visit(cursor, created_by_user_id, visit_id, content):
        cursor.execute(
            "INSERT INTO visit_notes (visit_id, content, created_by_user_id) VALUES (%s, %s, %s)",
            (visit_id + 1000000, content, created_by_user_id)
        )

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.insert_visit_note",
        insert_note_with_wrong_visit
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

    with pytest.raises(psycopg.IntegrityError):
        add_planned_visit(
            user_ids["worker"],
            client_id,
            service_id,
            planned_week=date(2026, 11, 23),
            note="Muistiinpano"
        )

    with pytest.raises(psycopg.IntegrityError):
        add_completed_visit(
            user_ids["worker"],
            client_id,
            service_id,
            completed_date=date(2026, 11, 18),
            note="Muistiinpano"
        )

    # Neither visit was left in the database
    cursor.execute("SELECT COUNT(*) FROM visits")

    assert cursor.fetchone()[0] == 0

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_complete_visit_rolls_back_when_note_insert_fails(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_note_with_wrong_visit(cursor, created_by_user_id, visit_id, content):
        cursor.execute(
            "INSERT INTO visit_notes (visit_id, content, created_by_user_id) VALUES (%s, %s, %s)",
            (visit_id + 1000000, content, created_by_user_id)
        )

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
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

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 18),
        planned_duration_minutes=60
    )

    monkeypatch.setattr(
        "carelog.services.visits.insert_visit_note",
        insert_note_with_wrong_visit
    )

    with pytest.raises(psycopg.IntegrityError):
        complete_visit(user_ids["worker"], visit_id, note="Muistiinpano")

    # The status change was rolled back together with the note
    cursor.execute(
        """
        SELECT status, completed_date, duration_minutes
        FROM visits
        WHERE id = %s
        """,
        (visit_id,)
    )

    assert cursor.fetchone() == ("planned", None, None)

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_complete_visit_with_note_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.visits.get_active_user", fake_active_user)


    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False
            self.committed = False
            self.rolled_back = False

        def cursor(self):
            return self.test_cursor

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def select_planned_visit(cursor, visit_id, for_update=False, owner_user_id=None):
        return {
            "status": "planned",
            "planned_date": date(2026, 11, 18),
            "planned_at": None,
            "planned_duration_minutes": 60,
        }

    def complete_record(
        cursor,
        updated_by_user_id,
        visit_id,
        completed_date,
        duration_minutes,
        started_at,
        ended_at
    ):
        return True

    def insert_note_then_fail(cursor, created_by_user_id, visit_id, content):
        raise RuntimeError("Simulated note failure")

    monkeypatch.setattr(
        "carelog.services.visits.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visits.select_visit",
        select_planned_visit
    )

    monkeypatch.setattr(
        "carelog.services.visits.complete_visit_record",
        complete_record
    )

    monkeypatch.setattr(
        "carelog.services.visits.insert_visit_note",
        insert_note_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated note failure"):
        complete_visit(1, 1, note="Muistiinpano")

    assert connection.committed is False
    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# LOCKING TESTS
# A second, real PostgreSQL connection changes the visit and keeps the row
# locked. The service call runs in a thread and must wait for that lock,
# and then use the committed, current values.


@pytest.fixture
def lock_database(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr("carelog.services.visits.get_postgres_connection", get_test_connection)

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) "
        "VALUES ('Hilma', 'Testi', %s) RETURNING id",
        (user_ids["admin"],)
    )
    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES ('Kauppa-asiointi', %s) RETURNING id",
        (user_ids["admin"],)
    )
    service_id = cursor.fetchone()[0]

    # A planned visit on Wednesday 25.11.2026 at 10.00 Helsinki time
    # (08.00 UTC), planned for 60 minutes
    cursor.execute(
        """
        INSERT INTO visits (
            client_id, service_id, planned_week, planned_date, planned_at,
            planned_duration_minutes, user_id, created_by_user_id
        )
        VALUES (%s, %s, '2026-11-23', '2026-11-25', '2026-11-25 08:00', 60, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, user_ids["worker"], user_ids["worker"])
    )
    visit_id = cursor.fetchone()[0]

    other_connection = get_test_connection()

    try:
        yield cursor, visit_id, other_connection
    finally:
        other_connection.close()


def test_update_visit_uses_current_locked_schedule(lock_database, user_ids):
    cursor, visit_id, other_connection = lock_database

    # The other connection moves the visit to the next week but does not
    # commit yet, so it keeps the row locked.
    other_connection.execute(
        """
        UPDATE visits
        SET planned_week = '2026-11-30', planned_date = '2026-12-02', planned_at = NULL
        WHERE id = %s
        """,
        (visit_id,)
    )

    # Clearing the time keeps the stored day and week. They must be the
    # new ones, not the ones before the other change.
    thread, done, outcome = start_in_thread(update_visit, user_ids["worker"], visit_id, {"planned_at": None})

    wait_until_waiting_for_lock(cursor)
    assert not done.is_set()

    other_connection.commit()

    assert done.wait(timeout=10)
    thread.join(timeout=10)
    assert outcome == {"result": True}

    cursor.execute(
        "SELECT planned_week, planned_date, planned_at FROM visits WHERE id = %s",
        (visit_id,)
    )

    assert cursor.fetchone() == (date(2026, 11, 30), date(2026, 12, 2), None)


def test_complete_visit_uses_current_planned_duration(lock_database, user_ids):
    cursor, visit_id, other_connection = lock_database

    # A visit planned in the past, without an exact time, for 60 minutes
    cursor.execute(
        """
        UPDATE visits
        SET planned_week = '2026-11-16', planned_date = '2026-11-20', planned_at = NULL
        WHERE id = %s
        """,
        (visit_id,)
    )

    # The other connection changes the planned duration to 90 minutes
    other_connection.execute(
        "UPDATE visits SET planned_duration_minutes = 90 WHERE id = %s",
        (visit_id,)
    )

    thread, done, outcome = start_in_thread(complete_visit, user_ids["worker"], visit_id)

    wait_until_waiting_for_lock(cursor)
    assert not done.is_set()

    other_connection.commit()

    assert done.wait(timeout=10)
    thread.join(timeout=10)
    assert outcome == {"result": True}

    cursor.execute(
        "SELECT status, completed_date, duration_minutes, planned_duration_minutes "
        "FROM visits WHERE id = %s",
        (visit_id,)
    )

    # The default duration comes from the current plan, and the plan
    # itself is not changed.
    assert cursor.fetchone() == ("completed", date(2026, 11, 20), 90, 90)


@pytest.mark.parametrize(
    ("new_status", "function", "arguments", "message"),
    [
        ("cancelled", update_visit, ({"priority": 1},), "Only planned visits can be updated"),
        ("completed", update_visit, ({"priority": 1},), "Only planned visits can be updated"),
        ("cancelled", complete_visit, (), "Only planned visits can be completed"),
    ],
)
def test_concurrent_status_change_is_respected(
    lock_database,
    user_ids,
    new_status,
    function,
    arguments,
    message
):
    cursor, visit_id, other_connection = lock_database

    # The other connection cancels or completes the visit
    other_connection.execute(
        "UPDATE visits SET status = %s WHERE id = %s",
        (new_status, visit_id)
    )

    thread, done, outcome = start_in_thread(function, user_ids["worker"], visit_id, *arguments)

    wait_until_waiting_for_lock(cursor)
    assert not done.is_set()

    other_connection.commit()

    assert done.wait(timeout=10)
    thread.join(timeout=10)

    assert isinstance(outcome.get("error"), ValueError)
    assert str(outcome["error"]) == message

    cursor.execute(
        "SELECT status, priority, completed_date FROM visits WHERE id = %s",
        (visit_id,)
    )

    assert cursor.fetchone() == (new_status, 2, None)


def test_error_after_lock_rolls_back_and_releases_the_row(lock_database, user_ids, monkeypatch):
    cursor, visit_id, other_connection = lock_database

    cursor.execute(
        "UPDATE visits SET planned_date = '2026-11-20', planned_week = '2026-11-16', "
        "planned_at = NULL WHERE id = %s",
        (visit_id,)
    )

    def lock_then_fail(
        cursor, updated_by_user_id, visit_id, completed_date, duration_minutes, started_at, ended_at
    ):
        # The service has already locked the row. The status is changed
        # and then the operation fails.
        cursor.execute("UPDATE visits SET status = 'completed' WHERE id = %s", (visit_id,))
        raise RuntimeError("Simulated failure after the lock")

    monkeypatch.setattr("carelog.services.visits.complete_visit_record", lock_then_fail)

    with pytest.raises(RuntimeError, match="Simulated failure"):
        complete_visit(user_ids["worker"], visit_id, note="Ei saa tallentua")

    cursor.execute(
        "SELECT status, completed_date, duration_minutes FROM visits WHERE id = %s",
        (visit_id,)
    )
    assert cursor.fetchone() == ("planned", None, None)

    cursor.execute("SELECT COUNT(*) FROM visit_notes WHERE visit_id = %s", (visit_id,))
    assert cursor.fetchone()[0] == 0

    # The lock was released: another connection can lock the row at once
    other_connection.execute(
        "SELECT id FROM visits WHERE id = %s FOR UPDATE NOWAIT",
        (visit_id,)
    )
    other_connection.rollback()


def test_update_and_complete_still_work_normally(lock_database, user_ids):
    cursor, visit_id, other_connection = lock_database

    assert update_visit(user_ids["worker"], visit_id, {"planned_duration_minutes": 45, "priority": 1}) is True
    assert update_visit(user_ids["worker"], visit_id, {"planned_date": date(2026, 11, 20), "planned_at": None}) is True
    assert complete_visit(user_ids["worker"], visit_id, note="Kaikki hyvin") is True

    visit = get_visit(user_ids["worker"], visit_id)

    assert visit["status"] == "completed"
    assert visit["completed_date"] == date(2026, 11, 20)
    assert visit["duration_minutes"] == 45
    assert visit["priority"] == 1

    cursor.execute("SELECT content FROM visit_notes WHERE visit_id = %s", (visit_id,))
    assert cursor.fetchall() == [("Kaikki hyvin",)]

    # A missing visit still returns False
    assert update_visit(user_ids["worker"], visit_id + 1000, {"priority": 1}) is False
    assert complete_visit(user_ids["worker"], visit_id + 1000) is False


# CLIENT LOCKING TESTS
# A new visit locks the client row with FOR UPDATE. The client cannot be
# archived between the archived_at check and the commit of the visit.


@pytest.fixture
def client_lock_database(lock_database, connect_to_test_postgres, monkeypatch):
    cursor, visit_id, other_connection = lock_database

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    # archive_client() and get_client() use the same test database
    monkeypatch.setattr("carelog.services.clients.get_postgres_connection", get_test_connection)

    # The active client and the service of the fixture visit
    cursor.execute("SELECT client_id, service_id FROM visits WHERE id = %s", (visit_id,))
    client_id, service_id = cursor.fetchone()

    return cursor, client_id, service_id, other_connection


NEW_VISITS = [
    (add_planned_visit, {"planned_date": date(2026, 11, 20)}),
    (add_completed_visit, {"completed_date": date(2026, 11, 20)}),
]


@pytest.mark.parametrize(("add_visit", "arguments"), NEW_VISITS, ids=["planned", "completed"])
def test_add_visit_waits_for_archiving_and_rejects_archived_client(
    client_lock_database,
    user_ids,
    add_visit,
    arguments
):
    cursor, client_id, service_id, other_connection = client_lock_database

    # The other connection archives the client but does not commit yet,
    # so it keeps the client row locked.
    with other_connection.cursor() as other_cursor:
        assert archive_client_record(other_cursor, user_ids["admin"], client_id) is True

    thread, done, outcome = start_in_thread(add_visit, user_ids["worker"], client_id, service_id, **arguments)

    wait_until_waiting_for_lock(cursor)
    assert not done.is_set()

    other_connection.commit()

    assert done.wait(timeout=10)
    thread.join(timeout=10)

    assert isinstance(outcome.get("error"), ValueError)
    assert str(outcome["error"]) == "Cannot add a visit for an archived client"

    # Only the visit of the fixture exists
    cursor.execute("SELECT COUNT(*) FROM visits WHERE client_id = %s", (client_id,))
    assert cursor.fetchone()[0] == 1


@pytest.mark.parametrize(("add_visit", "arguments"), NEW_VISITS, ids=["planned", "completed"])
def test_archiving_waits_for_visit_that_locked_the_client_first(
    client_lock_database,
    user_ids,
    monkeypatch,
    add_visit,
    arguments
):
    cursor, client_id, service_id, other_connection = client_lock_database

    client_locked = threading.Event()
    may_commit = threading.Event()

    # The visit is inserted while the client row is locked. The service
    # then waits before its commit until the test allows it.
    def insert_then_wait(*args, **kwargs):
        visit_id = insert_visit(*args, **kwargs)
        client_locked.set()

        if not may_commit.wait(timeout=10):
            raise RuntimeError("The test did not allow the commit")

        return visit_id

    monkeypatch.setattr("carelog.services.visits.insert_visit", insert_then_wait)

    add_thread, add_done, add_outcome = start_in_thread(
        add_visit, user_ids["worker"], client_id, service_id, **arguments
    )
    archive_thread = None

    try:
        assert client_locked.wait(timeout=10)

        archive_thread, archive_done, archive_outcome = start_in_thread(
            archive_client, user_ids["admin"], client_id
        )

        # Archiving must wait for the lock of the visit transaction
        wait_until_waiting_for_lock(cursor)
        assert not archive_done.is_set()

        may_commit.set()

        assert add_done.wait(timeout=10)
        assert archive_done.wait(timeout=10)

    finally:
        # The threads can finish even if the test failed
        may_commit.set()
        add_thread.join(timeout=10)

        if archive_thread is not None:
            archive_thread.join(timeout=10)

    assert "error" not in add_outcome
    assert archive_outcome == {"result": True}

    # The visit was saved, and the client was archived only after it
    cursor.execute(
        """
        SELECT v.created_at, c.archived_at
        FROM visits AS v
        JOIN clients AS c
          ON c.id = v.client_id
        WHERE v.id = %s
        """,
        (add_outcome["result"],)
    )
    created_at, archived_at = cursor.fetchone()

    assert archived_at is not None
    assert created_at <= archived_at


def test_get_client_does_not_wait_for_client_lock(client_lock_database, user_ids):
    cursor, client_id, service_id, other_connection = client_lock_database

    # The other connection keeps the client row locked
    with other_connection.cursor() as other_cursor:
        archive_client_record(other_cursor, user_ids["admin"], client_id)

    thread, done, outcome = start_in_thread(get_client, client_id)

    # get_client() does not lock, so it returns at once with the last
    # committed values.
    assert done.wait(timeout=5)
    thread.join(timeout=5)
    assert outcome["result"]["archived_at"] is None

    other_connection.rollback()


def test_error_after_client_lock_rolls_back_and_releases_the_client(
    client_lock_database,
    user_ids,
    monkeypatch
):
    cursor, client_id, service_id, other_connection = client_lock_database

    def insert_then_fail(*args, **kwargs):
        insert_visit(*args, **kwargs)
        raise RuntimeError("Simulated failure after the lock")

    monkeypatch.setattr("carelog.services.visits.insert_visit", insert_then_fail)

    with pytest.raises(RuntimeError, match="Simulated failure"):
        add_planned_visit(user_ids["worker"], client_id, service_id, planned_date=date(2026, 11, 20))

    # The inserted visit was rolled back
    cursor.execute("SELECT COUNT(*) FROM visits WHERE client_id = %s", (client_id,))
    assert cursor.fetchone()[0] == 1

    # The lock was released: another connection can lock the row at once
    other_connection.execute(
        "SELECT id FROM clients WHERE id = %s FOR UPDATE NOWAIT",
        (client_id,)
    )
    other_connection.rollback()


# HOURLY RATE TESTS
# visits.price is the hourly rate of the visit.


def test_add_planned_visit_rejects_invalid_price():
    invalid_prices = (-1, Decimal("-0.01"), True, "35", float("inf"), Decimal("35.555"))

    for price in invalid_prices:
        with pytest.raises(ValueError):
            add_planned_visit(
                1,
                1,
                1,
                planned_week=date(2026, 11, 23),
                price=price
            )


@pytest.fixture
def rate_database(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    # A client and a service with the default hourly rate 35.00 €
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr("carelog.services.visits.get_postgres_connection", get_test_connection)

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )
    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, default_hourly_rate, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Siivous", Decimal("35.00"), user_ids["worker"])
    )
    service_id = cursor.fetchone()[0]

    return cursor, client_id, service_id


def get_saved_price(cursor, visit_id):
    cursor.execute("SELECT price FROM visits WHERE id = %s", (visit_id,))
    return cursor.fetchone()[0]


def test_add_planned_visit_saves_service_default_rate(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    visit_id = add_planned_visit(user_ids["worker"], client_id, service_id, planned_date=date(2026, 11, 20))

    assert get_saved_price(cursor, visit_id) == Decimal("35.00")
    assert get_visit(user_ids["worker"], visit_id)["price"] == Decimal("35.00")


def test_given_rate_overrides_service_default_rate(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    planned_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 20), price=Decimal("40.00")
    )
    completed_id = add_completed_visit(
        user_ids["worker"],
        client_id, service_id, completed_date=date(2026, 11, 20), price=40
    )

    assert get_saved_price(cursor, planned_id) == Decimal("40.00")
    assert get_saved_price(cursor, completed_id) == Decimal("40.00")


def test_add_completed_visit_saves_service_default_rate(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    visit_id = add_completed_visit(user_ids["worker"], client_id, service_id, completed_date=date(2026, 11, 20))

    assert get_saved_price(cursor, visit_id) == Decimal("35.00")


def test_service_rate_change_does_not_change_saved_visits(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    visit_a = add_planned_visit(user_ids["worker"], client_id, service_id, planned_date=date(2026, 11, 20))
    visit_b = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 20), price=Decimal("40.00")
    )

    # The service gets a new default rate later
    cursor.execute(
        "UPDATE services SET default_hourly_rate = %s WHERE id = %s",
        (Decimal("45.00"), service_id)
    )

    assert get_saved_price(cursor, visit_a) == Decimal("35.00")
    assert get_saved_price(cursor, visit_b) == Decimal("40.00")

    # A new visit gets the new default rate
    visit_c = add_planned_visit(user_ids["worker"], client_id, service_id, planned_date=date(2026, 11, 20))

    assert get_saved_price(cursor, visit_c) == Decimal("45.00")


def test_complete_visit_keeps_hourly_rate(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    default_rate_id = add_planned_visit(user_ids["worker"], client_id, service_id, planned_date=date(2026, 11, 20))
    own_rate_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 20), price=Decimal("40.00")
    )

    # The service rate changes before the visits are completed
    cursor.execute("UPDATE services SET default_hourly_rate = 45 WHERE id = %s", (service_id,))

    assert complete_visit(user_ids["worker"], default_rate_id, duration_minutes=120) is True
    assert complete_visit(user_ids["worker"], own_rate_id, duration_minutes=180) is True

    assert get_saved_price(cursor, default_rate_id) == Decimal("35.00")
    assert get_saved_price(cursor, own_rate_id) == Decimal("40.00")


def test_missing_default_rate_saves_no_price(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )
    service_without_rate = cursor.fetchone()[0]

    planned_id = add_planned_visit(user_ids["worker"], client_id, service_without_rate, planned_date=date(2026, 11, 20))
    completed_id = add_completed_visit(
        user_ids["worker"],
        client_id, service_without_rate, completed_date=date(2026, 11, 20)
    )

    # A missing rate stays missing; it is not saved as 0
    assert get_saved_price(cursor, planned_id) is None
    assert get_saved_price(cursor, completed_id) is None


def test_zero_rate_is_not_a_missing_rate(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    # A given rate of 0 is kept and the default 35.00 is not used
    visit_id = add_planned_visit(user_ids["worker"], client_id, service_id, planned_date=date(2026, 11, 20), price=0)

    assert get_saved_price(cursor, visit_id) == Decimal("0.00")

    # A default rate of 0 is copied as 0, not as a missing rate
    cursor.execute(
        "INSERT INTO services (name, default_hourly_rate, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Vapaaehtoinen apu", Decimal("0.00"), user_ids["worker"])
    )
    free_service_id = cursor.fetchone()[0]

    free_visit_id = add_completed_visit(
        user_ids["worker"],
        client_id, free_service_id, completed_date=date(2026, 11, 20)
    )

    assert get_saved_price(cursor, free_visit_id) == Decimal("0.00")


# PRIORITY TESTS
# 1 = urgent, 2 = normal, 3 = low


def test_add_and_update_visit_accept_every_priority(rate_database, user_ids):
    cursor, client_id, service_id = rate_database

    for priority in (1, 2, 3):
        visit_id = add_planned_visit(
            user_ids["worker"],
            client_id, service_id, planned_date=date(2026, 11, 27), priority=priority
        )
        assert get_visit(user_ids["worker"], visit_id)["priority"] == priority

    for priority in (3, 1, 2):
        assert update_visit(user_ids["worker"], visit_id, {"priority": priority}) is True
        assert get_visit(user_ids["worker"], visit_id)["priority"] == priority


# OWNERSHIP TESTS
# visits.user_id is the worker of the visit. A worker handles only their
# own visits, an admin the visits of every worker. rate_database gives a
# client and a service.


def get_visit_users(cursor, visit_id):
    cursor.execute(
        "SELECT user_id, created_by_user_id, updated_by_user_id FROM visits WHERE id = %s",
        (visit_id,)
    )
    return cursor.fetchone()


def test_visit_functions_reject_invalid_user_ids(monkeypatch):
    # The user check itself is tested in test_user_validation.py. Invalid
    # IDs are rejected before any database connection.
    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection")

    monkeypatch.setattr("carelog.services.visits.get_postgres_connection", connection_not_allowed)

    for user_id in (None, True, "1", 0):
        with pytest.raises(ValueError):
            add_planned_visit(user_id, 1, 1, planned_week=date(2026, 11, 23))

        with pytest.raises(ValueError):
            get_visit(user_id, 1)

        with pytest.raises(ValueError):
            update_visit(user_id, 1, {"priority": 1})

        with pytest.raises(ValueError):
            cancel_visit(user_id, 1)

        with pytest.raises(ValueError):
            change_visit_worker(1, 1, user_id)

    # user_id=None means the actor, so only the other values are invalid
    for user_id in (True, "1", 0):
        with pytest.raises(ValueError):
            add_completed_visit(1, 1, 1, completed_date=date(2026, 11, 18), user_id=user_id)

        with pytest.raises(ValueError):
            get_week_visits(1, date(2026, 11, 23), user_id=user_id)


def test_worker_and_admin_choose_the_worker_of_new_visits(rate_database, user_ids):
    cursor, client_id, service_id = rate_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]

    # Without user_id the actor is the worker
    own_visit_id = add_planned_visit(worker_id, client_id, service_id, planned_date=date(2026, 11, 25))
    assert get_visit_users(cursor, own_visit_id) == (worker_id, worker_id, None)

    # A worker cannot add a visit for another worker
    with pytest.raises(PermissionError):
        add_planned_visit(
            worker_id, client_id, service_id, planned_date=date(2026, 11, 25), user_id=other_worker_id
        )

    # An admin can, and the creator is the admin
    planned_id = add_planned_visit(
        admin_id, client_id, service_id, planned_date=date(2026, 11, 25), user_id=other_worker_id
    )
    completed_id = add_completed_visit(
        admin_id, client_id, service_id, completed_date=date(2026, 11, 18), user_id=worker_id
    )

    assert get_visit_users(cursor, planned_id) == (other_worker_id, admin_id, None)
    assert get_visit_users(cursor, completed_id) == (worker_id, admin_id, None)

    # The worker must be an active, existing user
    with pytest.raises(PermissionError):
        add_completed_visit(
            admin_id, client_id, service_id, completed_date=date(2026, 11, 18),
            user_id=user_ids["inactive"]
        )

    with pytest.raises(ValueError, match="User not found"):
        add_planned_visit(
            admin_id, client_id, service_id, planned_date=date(2026, 11, 25),
            user_id=admin_id + worker_id + 1000
        )

    # The rejected visits were not saved
    cursor.execute("SELECT COUNT(*) FROM visits")
    assert cursor.fetchone()[0] == 3


def test_visit_searches_are_limited_to_own_visits(rate_database, user_ids):
    cursor, client_id, service_id = rate_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]
    week = date(2026, 11, 23)

    own_id = add_planned_visit(worker_id, client_id, service_id, planned_date=date(2026, 11, 25))
    other_id = add_planned_visit(other_worker_id, client_id, service_id, planned_date=date(2026, 11, 26))

    def ids_of(visits):
        ids = []

        for visit in visits:
            ids.append(visit["id"])

        return ids

    # One visit: another worker's visit looks like a missing visit
    assert get_visit(worker_id, own_id)["user_id"] == worker_id
    assert get_visit(worker_id, other_id) is None
    assert get_visit(admin_id, other_id)["user_id"] == other_worker_id

    # Lists: a worker gets only their own visits, an admin every visit or
    # the visits of one worker
    assert ids_of(get_client_visits(worker_id, client_id)) == [own_id]
    assert ids_of(get_planned_visits(worker_id)) == [own_id]
    assert ids_of(get_week_visits(worker_id, week)) == [own_id]

    assert ids_of(get_planned_visits(admin_id)) == [own_id, other_id]
    assert ids_of(get_week_visits(admin_id, week)) == [own_id, other_id]
    assert ids_of(get_client_visits(admin_id, client_id, user_id=other_worker_id)) == [other_id]
    assert ids_of(get_week_visits(worker_id, week, user_id=worker_id)) == [own_id]

    # A worker cannot get another worker's visits by giving their ID
    with pytest.raises(PermissionError):
        get_client_visits(worker_id, client_id, user_id=other_worker_id)

    with pytest.raises(PermissionError):
        get_planned_visits(worker_id, user_id=other_worker_id)

    with pytest.raises(PermissionError):
        get_week_visits(worker_id, week, user_id=other_worker_id)


def test_worker_cannot_change_another_workers_visit(rate_database, user_ids):
    cursor, client_id, service_id = rate_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]

    # The admin plans one visit for each worker
    own_id = add_planned_visit(
        admin_id, client_id, service_id, planned_date=date(2026, 11, 25), user_id=worker_id
    )
    other_id = add_planned_visit(
        admin_id, client_id, service_id, planned_date=date(2026, 11, 26), user_id=other_worker_id
    )

    # Another worker's visit is treated as a missing visit
    assert update_visit(worker_id, other_id, {"priority": 1}) is False
    assert complete_visit(worker_id, other_id, completed_date=date(2026, 11, 18)) is False
    assert cancel_visit(worker_id, other_id) is False

    cursor.execute("SELECT status, priority FROM visits WHERE id = %s", (other_id,))
    assert cursor.fetchone() == ("planned", 2)
    assert get_visit_users(cursor, other_id) == (other_worker_id, admin_id, None)

    # The worker updates their own visit: the creator stays the admin
    assert update_visit(worker_id, own_id, {"priority": 1}) is True
    assert get_visit_users(cursor, own_id) == (worker_id, admin_id, worker_id)

    # The admin completes and cancels visits of the workers. The worker
    # of a visit does not change.
    assert complete_visit(admin_id, own_id, completed_date=date(2026, 11, 18)) is True
    assert cancel_visit(admin_id, other_id) is True

    assert get_visit_users(cursor, own_id) == (worker_id, admin_id, admin_id)
    assert get_visit_users(cursor, other_id) == (other_worker_id, admin_id, admin_id)


def test_admin_changes_the_worker_of_a_planned_visit(rate_database, user_ids):
    cursor, client_id, service_id = rate_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]

    visit_id = add_planned_visit(worker_id, client_id, service_id, planned_date=date(2026, 11, 25))

    # The expense of the visit has its own worker
    cursor.execute(
        "INSERT INTO expenses (visit_id, expense_date, amount, category, "
        "user_id, created_by_user_id) "
        "VALUES (%s, '2026-11-25', 10, 'customer', %s, %s) RETURNING id",
        (visit_id, worker_id, worker_id)
    )
    expense_id = cursor.fetchone()[0]

    # Only an admin may change the worker
    with pytest.raises(PermissionError):
        change_visit_worker(worker_id, visit_id, other_worker_id)

    # The new worker must be an active, existing user
    with pytest.raises(PermissionError):
        change_visit_worker(admin_id, visit_id, user_ids["inactive"])

    with pytest.raises(ValueError, match="User not found"):
        change_visit_worker(admin_id, visit_id, admin_id + worker_id + 1000)

    assert get_visit_users(cursor, visit_id) == (worker_id, worker_id, None)

    assert change_visit_worker(admin_id, visit_id, other_worker_id) is True
    assert get_visit_users(cursor, visit_id) == (other_worker_id, worker_id, admin_id)

    cursor.execute("SELECT user_id FROM expenses WHERE id = %s", (expense_id,))
    assert cursor.fetchone()[0] == worker_id

    # The visit now belongs to the other worker
    assert get_visit(worker_id, visit_id) is None

    assert change_visit_worker(admin_id, visit_id + 1000, worker_id) is False


def test_worker_of_completed_or_cancelled_visit_cannot_change(rate_database, user_ids):
    cursor, client_id, service_id = rate_database
    worker_id = user_ids["worker"]
    admin_id = user_ids["admin"]

    completed_id = add_completed_visit(worker_id, client_id, service_id, completed_date=date(2026, 11, 18))
    cancelled_id = add_planned_visit(worker_id, client_id, service_id, planned_date=date(2026, 11, 25))
    assert cancel_visit(worker_id, cancelled_id) is True

    for visit_id in (completed_id, cancelled_id):
        with pytest.raises(ValueError, match="Only the worker of a planned visit"):
            change_visit_worker(admin_id, visit_id, user_ids["other_worker"])

        assert get_visit_users(cursor, visit_id)[0] == worker_id


def test_deactivated_worker_keeps_visit_history(rate_database, user_ids):
    cursor, client_id, service_id = rate_database
    worker_id = user_ids["worker"]

    visit_id = add_completed_visit(worker_id, client_id, service_id, completed_date=date(2026, 11, 18))

    cursor.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (worker_id,))

    # The visit stays, but the deactivated user cannot use the services
    assert get_visit(user_ids["admin"], visit_id)["user_id"] == worker_id

    with pytest.raises(PermissionError):
        get_visit(worker_id, visit_id)


def test_worker_change_waits_for_completion(lock_database, user_ids):
    cursor, visit_id, other_connection = lock_database

    # The other connection completes the visit but does not commit yet
    other_connection.execute(
        "UPDATE visits SET status = 'completed' WHERE id = %s",
        (visit_id,)
    )

    thread, done, outcome = start_in_thread(
        change_visit_worker, user_ids["admin"], visit_id, user_ids["other_worker"]
    )

    wait_until_waiting_for_lock(cursor)
    assert not done.is_set()

    other_connection.commit()

    assert done.wait(timeout=10)
    thread.join(timeout=10)

    # The status of the locked row decides: the completed visit keeps
    # its worker
    assert isinstance(outcome.get("error"), ValueError)
    assert get_visit_users(cursor, visit_id)[0] == user_ids["worker"]


def test_completion_waits_for_worker_change(lock_database, user_ids):
    cursor, visit_id, other_connection = lock_database

    # The other connection gives the visit to another worker but does not
    # commit yet
    other_connection.execute(
        "UPDATE visits SET user_id = %s WHERE id = %s",
        (user_ids["other_worker"], visit_id)
    )

    thread, done, outcome = start_in_thread(complete_visit, user_ids["worker"], visit_id)

    wait_until_waiting_for_lock(cursor)
    assert not done.is_set()

    other_connection.commit()

    assert done.wait(timeout=10)
    thread.join(timeout=10)

    # The locked row is checked again: it is no longer the worker's visit
    assert outcome == {"result": False}

    cursor.execute("SELECT status FROM visits WHERE id = %s", (visit_id,))
    assert cursor.fetchone()[0] == "planned"
