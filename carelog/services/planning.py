from datetime import date, datetime, timedelta, timezone

from carelog.services.visits import (
    LOCAL_TIMEZONE,
    get_planned_visits,
    get_week_visits,
)


def get_visit_day(visit: dict) -> date | None:

    # Returns the local calendar day of a visit, or None if the visit
    # has no day yet. TIMESTAMP values come from the database in UTC
    # without a time zone, so UTC is attached before converting.

    if visit["status"] == "completed":

        # A completed visit is shown on the day it was done, never on
        # the planned day.
        if visit["completed_date"] is not None:
            return visit["completed_date"]

        if visit["started_at"] is not None:
            started_at = visit["started_at"].replace(tzinfo=timezone.utc)
            return started_at.astimezone(LOCAL_TIMEZONE).date()

        return None

    # A planned visit
    if visit["planned_date"] is not None:
        return visit["planned_date"]

    if visit["planned_at"] is not None:
        planned_at = visit["planned_at"].replace(tzinfo=timezone.utc)
        return planned_at.astimezone(LOCAL_TIMEZONE).date()

    return None


def get_week_plan(week_start: date) -> dict:

    # Week start validation
    # A datetime is also a date in Python, so type() is used to reject it.

    if type(week_start) is not date:
        raise ValueError("Week start must be a date")

    if week_start.weekday() != 0:
        raise ValueError("Week start must be a Monday")

    week_end = week_start + timedelta(days=6)

    # Seven days from Monday to Sunday, also the empty ones

    days = []

    for day_number in range(7):
        day = week_start + timedelta(days=day_number)
        days.append({"date": day, "visits": []})

    unscheduled = []

    # The visits come already in order, and the order is kept inside
    # each day. The original dictionaries are added as they are.

    visits = get_week_visits(week_start)

    for visit in visits:
        visit_day = get_visit_day(visit)

        if visit_day is None:
            # Planned for the week, but no day chosen yet
            unscheduled.append(visit)

        elif visit_day < week_start or visit_day > week_end:
            # An old or inconsistent row whose day is outside this week.
            # It is not dropped, so the user can still see and fix it.
            unscheduled.append(visit)

        else:
            day_index = (visit_day - week_start).days
            days[day_index]["visits"].append(visit)

    return {
        "week_start": week_start,
        "week_end": week_end,
        "days": days,
        "unscheduled": unscheduled,
    }


def get_week_summary(week_start: date) -> dict:

    # Week start validation, the same rule as in get_week_plan()

    if type(week_start) is not date:
        raise ValueError("Week start must be a date")

    if week_start.weekday() != 0:
        raise ValueError("Week start must be a Monday")

    week_end = week_start + timedelta(days=6)

    # get_week_visits() already puts planned visits in their planned
    # week and completed visits in the week they were done, and leaves
    # cancelled visits out. Each visit comes only once.

    planned_count = 0
    completed_count = 0

    planned_minutes = 0
    completed_minutes = 0

    planned_unknown_duration_count = 0
    completed_unknown_duration_count = 0

    urgent_planned_count = 0

    visits = get_week_visits(week_start)

    for visit in visits:

        if visit["status"] == "planned":
            planned_count += 1

            # Remaining work: only known planned durations are added.
            # A missing duration is counted, not treated as 0 minutes.
            if visit["planned_duration_minutes"] is None:
                planned_unknown_duration_count += 1
            else:
                planned_minutes += visit["planned_duration_minutes"]

            # 1 = urgent
            if visit["priority"] == 1:
                urgent_planned_count += 1

        elif visit["status"] == "completed":
            completed_count += 1

            # Actual work: the planned duration is never used instead.
            if visit["duration_minutes"] is None:
                completed_unknown_duration_count += 1
            else:
                completed_minutes += visit["duration_minutes"]

    return {
        "week_start": week_start,
        "week_end": week_end,
        "planned_count": planned_count,
        "completed_count": completed_count,
        "total_count": planned_count + completed_count,
        "planned_minutes": planned_minutes,
        "completed_minutes": completed_minutes,
        "planned_unknown_duration_count": planned_unknown_duration_count,
        "completed_unknown_duration_count": completed_unknown_duration_count,
        "urgent_planned_count": urgent_planned_count,
    }


def get_overdue_planned_visits(reference_date: date | None = None) -> list[dict]:

    # Returns the planned visits whose day or week has already passed.
    # This only reads data; the user decides later what to do with them.

    # Reference date validation
    # Without a date, today in Helsinki is used, not the UTC date.

    if reference_date is None:
        reference_date = datetime.now(LOCAL_TIMEZONE).date()

    elif type(reference_date) is not date:
        raise ValueError("Reference date must be a date")

    overdue_visits = []

    visits = get_planned_visits()

    for visit in visits:

        # An exact day comes first. get_visit_day() also turns an old
        # planned_at value into the local day.
        visit_day = get_visit_day(visit)

        if visit_day is not None:

            # The day has passed. A visit planned for today is not late,
            # because times of day are not compared.
            if visit_day < reference_date:
                overdue_visits.append(visit)

        elif visit["planned_week"] is not None:

            # Planned only for a week: late once the whole week has ended.
            week_end = visit["planned_week"] + timedelta(days=6)

            if week_end < reference_date:
                overdue_visits.append(visit)

    return overdue_visits
