from datetime import date, datetime

import pytest

from carelog.services.planning import (
    get_overdue_planned_visits,
    get_visit_day,
    get_week_plan,
    get_week_summary,
)


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # These are pure unit tests. If the code tries to open a database
    # connection through the Visits service, the test fails clearly.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a unit test")

    monkeypatch.setattr(
        "carelog.services.visits.get_connection",
        connection_not_allowed
    )


def make_visit(
    visit_id,
    status="planned",
    planned_week=None,
    planned_date=None,
    planned_at=None,
    completed_date=None,
    started_at=None,
    priority=2,
    planned_duration_minutes=None,
    duration_minutes=None
):
    # Only the fields that the planning functions read
    return {
        "id": visit_id,
        "status": status,
        "priority": priority,
        "planned_week": planned_week,
        "planned_date": planned_date,
        "planned_at": planned_at,
        "planned_duration_minutes": planned_duration_minutes,
        "completed_date": completed_date,
        "started_at": started_at,
        "duration_minutes": duration_minutes,
    }


def use_week_visits(monkeypatch, visits):

    # Replaces get_week_visits() and remembers how it was called
    calls = []

    def fake_get_week_visits(week_start):
        calls.append(week_start)
        return visits

    monkeypatch.setattr(
        "carelog.services.planning.get_week_visits",
        fake_get_week_visits
    )

    return calls


# GET VISIT DAY TESTS


def test_get_visit_day_uses_local_day():
    # A planned day is used as it is
    planned_day = make_visit(1, planned_date=date(2026, 11, 25))

    assert get_visit_day(planned_day) == date(2026, 11, 25)

    # Sunday 22.30 UTC is already Monday in Helsinki
    planned_time = make_visit(2, planned_at=datetime(2026, 11, 29, 22, 30))

    assert get_visit_day(planned_time) == date(2026, 11, 30)

    # A week-only visit has no day
    week_only = make_visit(3, planned_week=date(2026, 11, 23))

    assert get_visit_day(week_only) is None

    # A completed visit uses its completed day, not the planned day
    completed = make_visit(
        4,
        status="completed",
        planned_date=date(2026, 11, 24),
        completed_date=date(2026, 11, 26)
    )

    assert get_visit_day(completed) == date(2026, 11, 26)

    # An old completed visit without completed_date uses started_at.
    # In summer time 21.30 UTC is 00.30 the next day in Helsinki.
    old_completed = make_visit(
        5,
        status="completed",
        started_at=datetime(2026, 6, 14, 21, 30)
    )

    assert get_visit_day(old_completed) == date(2026, 6, 15)

    # The visit dictionary itself is not changed
    assert old_completed["started_at"] == datetime(2026, 6, 14, 21, 30)


# GET WEEK PLAN TESTS


def test_get_week_plan_rejects_invalid_week_start(monkeypatch):
    calls = use_week_visits(monkeypatch, [])

    invalid_values = (
        # 24.11.2026 is a Tuesday
        date(2026, 11, 24),
        datetime(2026, 11, 23, 0, 0),
        "2026-11-23",
        None,
    )

    for week_start in invalid_values:
        with pytest.raises(ValueError):
            get_week_plan(week_start)

    # The visits are not fetched when the week start is invalid
    assert calls == []


def test_get_week_plan_returns_seven_days_for_empty_week(monkeypatch):
    calls = use_week_visits(monkeypatch, [])

    plan = get_week_plan(date(2026, 11, 23))

    expected_days = [
        {"date": date(2026, 11, 23), "visits": []},
        {"date": date(2026, 11, 24), "visits": []},
        {"date": date(2026, 11, 25), "visits": []},
        {"date": date(2026, 11, 26), "visits": []},
        {"date": date(2026, 11, 27), "visits": []},
        {"date": date(2026, 11, 28), "visits": []},
        {"date": date(2026, 11, 29), "visits": []},
    ]

    assert plan == {
        "week_start": date(2026, 11, 23),
        "week_end": date(2026, 11, 29),
        "days": expected_days,
        "unscheduled": [],
    }

    # The visits are fetched exactly once
    assert calls == [date(2026, 11, 23)]


def test_get_week_plan_places_planned_visits(monkeypatch):
    week_only = make_visit(1, planned_week=date(2026, 11, 23))

    day_level = make_visit(
        2,
        planned_week=date(2026, 11, 23),
        planned_date=date(2026, 11, 25)
    )

    # An old row with only planned_at: Wednesday 08.00 UTC is
    # Wednesday 10.00 in Helsinki
    time_only = make_visit(
        3,
        planned_week=date(2026, 11, 23),
        planned_at=datetime(2026, 11, 25, 8, 0)
    )

    use_week_visits(monkeypatch, [week_only, day_level, time_only])

    plan = get_week_plan(date(2026, 11, 23))

    assert plan["unscheduled"] == [week_only]
    assert plan["days"][2]["date"] == date(2026, 11, 25)
    assert plan["days"][2]["visits"] == [day_level, time_only]

    # The other days stay empty
    for day_index in (0, 1, 3, 4, 5, 6):
        assert plan["days"][day_index]["visits"] == []


def test_get_week_plan_places_completed_visits_on_actual_day(monkeypatch):
    # Planned for Tuesday but done on Thursday
    completed = make_visit(
        1,
        status="completed",
        planned_week=date(2026, 11, 23),
        planned_date=date(2026, 11, 24),
        completed_date=date(2026, 11, 26)
    )

    # An old completed row without completed_date:
    # Sunday 22.30 UTC is Monday 00.30 in Helsinki
    old_completed = make_visit(
        2,
        status="completed",
        started_at=datetime(2026, 11, 22, 22, 30)
    )

    use_week_visits(monkeypatch, [old_completed, completed])

    plan = get_week_plan(date(2026, 11, 23))

    assert plan["days"][0]["visits"] == [old_completed]
    assert plan["days"][1]["visits"] == []
    assert plan["days"][3]["visits"] == [completed]
    assert plan["unscheduled"] == []


def test_get_week_plan_keeps_order_and_original_dictionaries(monkeypatch):
    first = make_visit(1, planned_date=date(2026, 11, 25))
    second = make_visit(2, planned_date=date(2026, 11, 25))
    third = make_visit(3, planned_date=date(2026, 11, 25))

    use_week_visits(monkeypatch, [first, second, third])

    plan = get_week_plan(date(2026, 11, 23))

    wednesday_visits = plan["days"][2]["visits"]

    assert wednesday_visits == [first, second, third]

    # The same dictionaries, not copies
    assert wednesday_visits[0] is first
    assert wednesday_visits[2] is third


def test_get_week_plan_keeps_visit_with_day_outside_week(monkeypatch):
    # An inconsistent old row: the planned week is this week, but the
    # planned day is in the next week. It is not dropped; it is shown
    # among the unscheduled visits so the user can fix it.
    inconsistent = make_visit(
        1,
        planned_week=date(2026, 11, 23),
        planned_date=date(2026, 12, 2)
    )

    use_week_visits(monkeypatch, [inconsistent])

    plan = get_week_plan(date(2026, 11, 23))

    assert plan["unscheduled"] == [inconsistent]

    for day in plan["days"]:
        assert day["visits"] == []


# GET WEEK SUMMARY TESTS


def test_get_week_summary_rejects_invalid_week_start(monkeypatch):
    calls = use_week_visits(monkeypatch, [])

    invalid_values = (
        date(2026, 11, 24),
        datetime(2026, 11, 23, 0, 0),
        "2026-11-23",
        None,
    )

    for week_start in invalid_values:
        with pytest.raises(ValueError):
            get_week_summary(week_start)

    assert calls == []


def test_get_week_summary_returns_zeros_for_empty_week(monkeypatch):
    calls = use_week_visits(monkeypatch, [])

    summary = get_week_summary(date(2026, 11, 23))

    assert summary == {
        "week_start": date(2026, 11, 23),
        "week_end": date(2026, 11, 29),
        "planned_count": 0,
        "completed_count": 0,
        "total_count": 0,
        "planned_minutes": 0,
        "completed_minutes": 0,
        "planned_unknown_duration_count": 0,
        "completed_unknown_duration_count": 0,
        "urgent_planned_count": 0,
    }

    assert calls == [date(2026, 11, 23)]


def test_get_week_summary_counts_visits_and_minutes(monkeypatch):
    visits = [
        # Planned: 60 + 90 known minutes, one unknown, one urgent
        make_visit(1, planned_duration_minutes=60, priority=1),
        make_visit(2, planned_duration_minutes=90),
        make_visit(3, planned_duration_minutes=None, priority=3),
        # Completed: 75 known minutes and one unknown. The planned
        # duration of a completed visit is never used.
        make_visit(
            4,
            status="completed",
            planned_duration_minutes=120,
            duration_minutes=75
        ),
        make_visit(
            5,
            status="completed",
            planned_duration_minutes=60,
            duration_minutes=None,
            priority=1
        ),
    ]

    calls = use_week_visits(monkeypatch, visits)

    summary = get_week_summary(date(2026, 11, 23))

    assert summary["planned_count"] == 3
    assert summary["completed_count"] == 2
    assert summary["total_count"] == 5

    # Only known minutes are added; unknown durations are counted apart
    assert summary["planned_minutes"] == 150
    assert summary["planned_unknown_duration_count"] == 1
    assert summary["completed_minutes"] == 75
    assert summary["completed_unknown_duration_count"] == 1

    # A completed urgent visit is not counted as urgent work
    assert summary["urgent_planned_count"] == 1

    # The visits are fetched only once and not changed
    assert calls == [date(2026, 11, 23)]
    assert visits[2]["planned_duration_minutes"] is None
    assert visits[4]["duration_minutes"] is None


def test_get_week_summary_with_only_unknown_durations(monkeypatch):
    visits = [
        make_visit(1),
        make_visit(2, status="completed"),
    ]

    use_week_visits(monkeypatch, visits)

    summary = get_week_summary(date(2026, 11, 23))

    # 0 minutes here means "no known minutes", which the counters show
    assert summary["planned_minutes"] == 0
    assert summary["completed_minutes"] == 0
    assert summary["planned_unknown_duration_count"] == 1
    assert summary["completed_unknown_duration_count"] == 1


def test_get_week_summary_counts_moved_visit_in_completed_week(monkeypatch):
    # Planned for the week of 16.11. but done on 24.11. The Visits
    # service returns it only for the week in which it was done.
    moved_visit = make_visit(
        1,
        status="completed",
        planned_week=date(2026, 11, 16),
        planned_date=date(2026, 11, 18),
        planned_duration_minutes=60,
        completed_date=date(2026, 11, 24),
        duration_minutes=45
    )

    visits_by_week = {
        date(2026, 11, 16): [],
        date(2026, 11, 23): [moved_visit],
    }

    def fake_get_week_visits(week_start):
        return visits_by_week[week_start]

    monkeypatch.setattr(
        "carelog.services.planning.get_week_visits",
        fake_get_week_visits
    )

    planned_week_summary = get_week_summary(date(2026, 11, 16))
    completed_week_summary = get_week_summary(date(2026, 11, 23))

    assert planned_week_summary["planned_count"] == 0
    assert planned_week_summary["total_count"] == 0

    assert completed_week_summary["completed_count"] == 1
    assert completed_week_summary["completed_minutes"] == 45
    assert completed_week_summary["planned_minutes"] == 0


# GET OVERDUE PLANNED VISITS TESTS


def use_planned_visits(monkeypatch, visits):

    # Replaces get_planned_visits() and remembers how many times it was called
    calls = []

    def fake_get_planned_visits():
        calls.append(True)
        return visits

    monkeypatch.setattr(
        "carelog.services.planning.get_planned_visits",
        fake_get_planned_visits
    )

    return calls


def test_get_overdue_planned_visits_rejects_invalid_reference_date(monkeypatch):
    calls = use_planned_visits(monkeypatch, [])

    for reference_date in (datetime(2026, 11, 25, 12, 0), "2026-11-25", 20261125):
        with pytest.raises(ValueError):
            get_overdue_planned_visits(reference_date)

    # The visits are not fetched when the date is invalid
    assert calls == []


def test_get_overdue_planned_visits_returns_empty_list(monkeypatch):
    calls = use_planned_visits(monkeypatch, [])

    assert get_overdue_planned_visits(date(2026, 11, 25)) == []
    assert calls == [True]


def test_get_overdue_planned_visits_compares_days(monkeypatch):
    yesterday = make_visit(1, planned_date=date(2026, 11, 24))
    today = make_visit(2, planned_date=date(2026, 11, 25))
    tomorrow = make_visit(3, planned_date=date(2026, 11, 26))

    # An old row with only planned_at: Tuesday 22.30 UTC is already
    # Wednesday 00.30 in Helsinki, so it is planned for today
    old_today = make_visit(4, planned_at=datetime(2026, 11, 24, 22, 30))

    # Tuesday 21.30 UTC is still Tuesday 23.30 in Helsinki, so it is late
    old_yesterday = make_visit(5, planned_at=datetime(2026, 11, 24, 21, 30))

    use_planned_visits(
        monkeypatch,
        [yesterday, today, tomorrow, old_today, old_yesterday]
    )

    overdue = get_overdue_planned_visits(date(2026, 11, 25))

    assert overdue == [yesterday, old_yesterday]


def test_get_overdue_planned_visits_handles_week_only_visits(monkeypatch):
    # The week 16.–22.11. has ended on 23.11.
    last_week = make_visit(1, planned_week=date(2026, 11, 16))

    # The week 23.–29.11. is still going on, even on its last day
    this_week = make_visit(2, planned_week=date(2026, 11, 23))

    use_planned_visits(monkeypatch, [last_week, this_week])

    assert get_overdue_planned_visits(date(2026, 11, 23)) == [last_week]
    assert get_overdue_planned_visits(date(2026, 11, 29)) == [last_week]

    # On the Monday after, this week's visit is late too
    assert get_overdue_planned_visits(date(2026, 11, 30)) == [
        last_week,
        this_week,
    ]


def test_get_overdue_planned_visits_prefers_exact_day(monkeypatch):
    # Inconsistent old row: the week has ended, but the exact day is
    # still in the future. The exact day decides, so it is not late.
    future_day_in_old_week = make_visit(
        1,
        planned_week=date(2026, 11, 16),
        planned_date=date(2026, 11, 27)
    )

    # The other way round: the week is still going on, but the exact
    # day has passed. It is late.
    past_day_in_current_week = make_visit(
        2,
        planned_week=date(2026, 11, 23),
        planned_date=date(2026, 11, 24)
    )

    visits = [future_day_in_old_week, past_day_in_current_week]

    use_planned_visits(monkeypatch, visits)

    overdue = get_overdue_planned_visits(date(2026, 11, 25))

    assert overdue == [past_day_in_current_week]

    # The original dictionaries are returned as they are and not changed
    assert overdue[0] is past_day_in_current_week
    assert future_day_in_old_week["planned_week"] == date(2026, 11, 16)
    assert future_day_in_old_week["planned_date"] == date(2026, 11, 27)


def test_get_overdue_planned_visits_keeps_order(monkeypatch):
    first = make_visit(1, planned_week=date(2026, 11, 2))
    not_late = make_visit(2, planned_date=date(2026, 12, 1))
    second = make_visit(3, planned_date=date(2026, 11, 10))
    third = make_visit(4, planned_at=datetime(2026, 11, 20, 8, 0))

    use_planned_visits(monkeypatch, [first, not_late, second, third])

    assert get_overdue_planned_visits(date(2026, 11, 25)) == [
        first,
        second,
        third,
    ]


def test_get_overdue_planned_visits_uses_today_in_helsinki(monkeypatch):
    # Far in the past and far in the future, so the result is the same
    # whatever day the test is run on.
    long_ago = make_visit(1, planned_date=date(2020, 1, 1))
    far_future = make_visit(2, planned_date=date(2099, 1, 1))

    use_planned_visits(monkeypatch, [long_ago, far_future])

    assert get_overdue_planned_visits() == [long_ago]
