from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from carelog.services.planning import (
    get_overdue_planned_visits,
    get_week_plan,
    get_week_summary,
)
from carelog.services.visits import (
    add_completed_visit,
    add_planned_visit,
    cancel_visit,
    complete_visit,
    get_visit,
    update_visit,
)


HELSINKI = ZoneInfo("Europe/Helsinki")

# Fixed weeks in the past, so completed dates are never in the future.
# The week of 23.3.2026 has the change to summer time on Sunday 29.3.
WEEK_1 = date(2026, 3, 16)
WEEK_2 = date(2026, 3, 23)


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # Nothing may reach the real database. The planning_database
    # fixture below replaces this with the isolated test database.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a test")

    monkeypatch.setattr(
        "carelog.services.visits.get_connection",
        connection_not_allowed
    )


@pytest.fixture
def planning_database(
    cursor_with_visit_scheduling,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_visit_scheduling

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    # The planning functions use the Visits service, which looks up
    # get_connection in its own module.
    monkeypatch.setattr(
        "carelog.services.visits.get_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s)",
        ("Hilma", "Testi")
    )

    client_id = cursor.lastrowid

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s)",
        ("Kauppa-asiointi",)
    )

    service_id = cursor.lastrowid

    return client_id, service_id


def visit_ids_of(visits):
    ids = []

    for visit in visits:
        ids.append(visit["id"])

    return ids


def test_week_only_visit_is_unscheduled(planning_database):
    client_id, service_id = planning_database

    visit_id = add_planned_visit(client_id, service_id, planned_week=WEEK_1)

    plan = get_week_plan(WEEK_1)

    assert visit_ids_of(plan["unscheduled"]) == [visit_id]

    for day in plan["days"]:
        assert day["visits"] == []

    summary = get_week_summary(WEEK_1)

    assert summary["planned_count"] == 1
    assert summary["planned_unknown_duration_count"] == 1


def test_day_visit_is_placed_on_its_day(planning_database):
    client_id, service_id = planning_database

    visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_date=date(2026, 3, 18),
        planned_duration_minutes=90,
        priority=1
    )

    plan = get_week_plan(WEEK_1)

    # Wednesday is the third day of the week
    assert plan["days"][2]["date"] == date(2026, 3, 18)
    assert visit_ids_of(plan["days"][2]["visits"]) == [visit_id]
    assert plan["unscheduled"] == []

    summary = get_week_summary(WEEK_1)

    assert summary["planned_minutes"] == 90
    assert summary["urgent_planned_count"] == 1


def test_moving_visit_to_another_day_and_week(planning_database):
    client_id, service_id = planning_database

    # Tuesday 17.3. at 10.00
    visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_at=datetime(2026, 3, 17, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=60
    )

    assert visit_ids_of(get_week_plan(WEEK_1)["days"][1]["visits"]) == [visit_id]

    # To Thursday 19.3. at 12.00 in the same week
    update_visit(
        visit_id,
        {"planned_at": datetime(2026, 3, 19, 12, 0, tzinfo=HELSINKI)}
    )

    plan = get_week_plan(WEEK_1)

    assert plan["days"][1]["visits"] == []
    assert visit_ids_of(plan["days"][3]["visits"]) == [visit_id]

    summary = get_week_summary(WEEK_1)

    assert summary["planned_count"] == 1
    assert summary["planned_minutes"] == 60

    # To Wednesday 25.3. in the next week. The visit has a time, so the
    # time is cleared in the same update, as the Visits rules require.
    update_visit(
        visit_id,
        {"planned_date": date(2026, 3, 25), "planned_at": None}
    )

    old_week_plan = get_week_plan(WEEK_1)
    new_week_plan = get_week_plan(WEEK_2)

    for day in old_week_plan["days"]:
        assert day["visits"] == []

    assert visit_ids_of(new_week_plan["days"][2]["visits"]) == [visit_id]

    assert get_week_summary(WEEK_1)["planned_count"] == 0
    assert get_week_summary(WEEK_2)["planned_count"] == 1

    # The Visits service set the week to the new day's Monday
    visit = get_visit(visit_id)

    assert visit["planned_week"] == WEEK_2
    assert visit["planned_duration_minutes"] == 60


def test_completing_visit_moves_it_from_planned_to_completed(planning_database):
    client_id, service_id = planning_database

    visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_date=date(2026, 3, 18),
        planned_duration_minutes=120
    )

    before = get_week_summary(WEEK_1)

    assert before["planned_count"] == 1
    assert before["planned_minutes"] == 120

    assert complete_visit(visit_id) is True

    plan = get_week_plan(WEEK_1)
    completed_visits = plan["days"][2]["visits"]

    assert visit_ids_of(completed_visits) == [visit_id]
    assert completed_visits[0]["status"] == "completed"

    after = get_week_summary(WEEK_1)

    assert after["planned_count"] == 0
    assert after["completed_count"] == 1
    assert after["total_count"] == 1
    assert after["planned_minutes"] == 0
    assert after["completed_minutes"] == 120

    # The planned duration stays in its own column
    visit = get_visit(visit_id)

    assert visit["planned_duration_minutes"] == 120
    assert visit["duration_minutes"] == 120


def test_visit_completed_in_another_week(planning_database):
    client_id, service_id = planning_database

    # Planned for Wednesday 18.3. but done on Tuesday 24.3.
    visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_date=date(2026, 3, 18),
        planned_duration_minutes=60
    )

    complete_visit(
        visit_id,
        completed_date=date(2026, 3, 24),
        duration_minutes=45
    )

    planned_week_plan = get_week_plan(WEEK_1)
    completed_week_plan = get_week_plan(WEEK_2)

    for day in planned_week_plan["days"]:
        assert day["visits"] == []

    assert planned_week_plan["unscheduled"] == []
    assert visit_ids_of(completed_week_plan["days"][1]["visits"]) == [visit_id]

    planned_week_summary = get_week_summary(WEEK_1)
    completed_week_summary = get_week_summary(WEEK_2)

    # Counted once, only in the week it was done
    assert planned_week_summary["total_count"] == 0
    assert completed_week_summary["completed_count"] == 1
    assert completed_week_summary["total_count"] == 1
    assert completed_week_summary["completed_minutes"] == 45


def test_cancelled_visit_is_left_out(planning_database):
    client_id, service_id = planning_database

    visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_date=date(2026, 3, 18),
        planned_duration_minutes=60
    )

    cancel_visit(visit_id)

    plan = get_week_plan(WEEK_1)

    for day in plan["days"]:
        assert day["visits"] == []

    assert plan["unscheduled"] == []

    summary = get_week_summary(WEEK_1)

    assert summary["planned_count"] == 0
    assert summary["total_count"] == 0
    assert summary["planned_minutes"] == 0

    assert get_overdue_planned_visits(date(2026, 3, 25)) == []

    # The visit is kept in the database as cancelled
    visit = get_visit(visit_id)

    assert visit["status"] == "cancelled"
    assert visit["planned_date"] == date(2026, 3, 18)


def test_overdue_planned_visits(planning_database):
    client_id, service_id = planning_database

    reference_date = date(2026, 3, 18)

    past_day_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 3, 17)
    )
    today_id = add_planned_visit(
        client_id, service_id, planned_date=reference_date
    )
    add_planned_visit(client_id, service_id, planned_date=date(2026, 3, 19))

    # The week 9.–15.3. has ended; the week 16.–22.3. has not
    past_week_id = add_planned_visit(
        client_id, service_id, planned_week=date(2026, 3, 9)
    )
    add_planned_visit(client_id, service_id, planned_week=WEEK_1)

    overdue = get_overdue_planned_visits(reference_date)

    # Ordered as get_planned_visits() returns them: by week, then day
    assert visit_ids_of(overdue) == [past_week_id, past_day_id]
    assert today_id not in visit_ids_of(overdue)

    # Finding late visits does not change them
    assert get_visit(past_day_id)["status"] == "planned"
    assert get_visit(past_week_id)["planned_week"] == date(2026, 3, 9)


def test_changed_planned_duration(planning_database):
    client_id, service_id = planning_database

    visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_date=date(2026, 3, 18),
        planned_duration_minutes=60
    )

    update_visit(visit_id, {"planned_duration_minutes": 90})

    summary = get_week_summary(WEEK_1)

    assert summary["planned_count"] == 1
    assert summary["planned_minutes"] == 90


def test_local_day_differs_from_utc_day(planning_database):
    client_id, service_id = planning_database

    # Monday 23.3. at 00.30 in Helsinki is still Sunday 22.3. in UTC
    planned_visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_at=datetime(2026, 3, 23, 0, 30, tzinfo=HELSINKI)
    )

    # Sunday 29.3. at 23.30 in Helsinki (summer time) is 20.30 UTC
    completed_visit_id = add_completed_visit(
        client_id,
        service_id,
        started_at=datetime(2026, 3, 29, 23, 30, tzinfo=HELSINKI)
    )

    previous_week_plan = get_week_plan(WEEK_1)

    for day in previous_week_plan["days"]:
        assert day["visits"] == []

    plan = get_week_plan(WEEK_2)

    # Monday and Sunday of the local week, not the UTC days
    assert visit_ids_of(plan["days"][0]["visits"]) == [planned_visit_id]
    assert visit_ids_of(plan["days"][6]["visits"]) == [completed_visit_id]

    assert get_visit(planned_visit_id)["planned_at"] == datetime(2026, 3, 22, 22, 30)


def test_rejected_changes_do_not_change_week_plan(planning_database):
    client_id, service_id = planning_database

    timed_visit_id = add_planned_visit(
        client_id,
        service_id,
        planned_at=datetime(2026, 3, 17, 10, 0, tzinfo=HELSINKI),
        planned_duration_minutes=60
    )

    completed_visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 3, 18)
    )
    complete_visit(completed_visit_id)

    cancelled_visit_id = add_planned_visit(
        client_id, service_id, planned_date=date(2026, 3, 19)
    )
    cancel_visit(cancelled_visit_id)

    plan_before = get_week_plan(WEEK_1)
    summary_before = get_week_summary(WEEK_1)

    with pytest.raises(ValueError):
        update_visit("1", {"priority": 1})

    # A new day while the old time would stay on the old day
    with pytest.raises(ValueError):
        update_visit(timed_visit_id, {"planned_date": date(2026, 3, 20)})

    # A completed visit cannot be changed, and status is not editable
    with pytest.raises(ValueError):
        update_visit(completed_visit_id, {"status": "planned"})

    with pytest.raises(ValueError):
        update_visit(completed_visit_id, {"priority": 1})

    # A cancelled visit cannot be completed
    with pytest.raises(ValueError):
        complete_visit(cancelled_visit_id)

    # Nothing was partly changed
    assert get_week_plan(WEEK_1) == plan_before
    assert get_week_summary(WEEK_1) == summary_before

    assert get_visit(timed_visit_id)["planned_date"] == date(2026, 3, 17)
    assert get_visit(completed_visit_id)["status"] == "completed"
    assert get_visit(cancelled_visit_id)["status"] == "cancelled"
