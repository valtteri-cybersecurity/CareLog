from datetime import date
from decimal import Decimal

import psycopg
import pytest

from carelog.services.trips import (
    add_trip,
    delete_trip,
    get_trip,
    leg_from_trip,
    update_trip,
)
from carelog.services.visit_trips import get_visit_trip, save_visit_trip
from carelog.services.visits import (
    add_completed_visit,
    add_planned_visit,
    cancel_visit,
    complete_visit,
    get_visit,
)
from tests.postgres_helpers import get_columns


# The service modules used together in these tests. All of them must
# use the same isolated test database.
SERVICE_MODULES = (
    "carelog.services.trips",
    "carelog.services.visits",
    "carelog.services.visit_trips",
)

THREE_LEGS = [
    {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.20")},
    {"start_location": "Kauppa", "destination": "Apteekki", "distance_km": Decimal("1.50")},
    {"start_location": "Apteekki", "destination": "Koti", "distance_km": Decimal("4.10")},
]


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # Nothing may reach the real database. The integration_database
    # fixture replaces this with the isolated test database.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a test")

    for module in SERVICE_MODULES:
        monkeypatch.setattr(f"{module}.get_postgres_connection", connection_not_allowed)


@pytest.fixture
def integration_database(postgres_cursor_with_visit_trips, user_ids, connect_to_test_postgres, monkeypatch):
    cursor = postgres_cursor_with_visit_trips

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    for module in SERVICE_MODULES:
        monkeypatch.setattr(f"{module}.get_postgres_connection", get_test_connection)

    return cursor


def create_client(cursor, user_id, first_name):
    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) "
        "VALUES (%s, %s, %s) RETURNING id",
        (first_name, "Testi", user_id)
    )

    return cursor.fetchone()[0]


def create_service(cursor, user_id):
    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_id)
    )

    return cursor.fetchone()[0]


def get_saved_legs(cursor, visit_id):
    cursor.execute(
        """
        SELECT position, start_location, destination, distance_km
        FROM visit_trip_legs
        WHERE visit_id = %s
        ORDER BY position
        """,
        (visit_id,)
    )

    return cursor.fetchall()


def test_default_route_is_copied_into_visit(integration_database, user_ids):
    cursor = integration_database
    actor_id = user_ids["worker"]
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    trip_id = add_trip(actor_id, client_id, "Hilman koti", "Ruokakauppa", Decimal("3.20"))
    trip = get_trip(trip_id)

    leg = leg_from_trip(trip)

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 25)
    )

    assert save_visit_trip(user_ids["worker"], visit_id, [leg]) is True

    legs = get_visit_trip(user_ids["worker"], visit_id)

    assert len(legs) == 1
    assert legs[0]["visit_id"] == visit_id
    assert legs[0]["start_location"] == "Hilman koti"
    assert legs[0]["destination"] == "Ruokakauppa"
    assert legs[0]["distance_km"] == Decimal("3.20")
    assert isinstance(legs[0]["distance_km"], Decimal)

    assert get_visit(user_ids["worker"], visit_id)["distance_km"] == Decimal("3.20")

    # The saved trip itself is not changed
    assert get_trip(trip_id) == trip

    # The legs table has no link to the trips table
    column_names = []

    for column in get_columns(cursor, "visit_trip_legs"):
        column_names.append(column[0])

    assert "trip_id" not in column_names
    assert "client_id" not in column_names


def test_changing_or_deleting_default_route_keeps_history(integration_database, user_ids):
    cursor = integration_database
    actor_id = user_ids["worker"]
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    trip_id = add_trip(actor_id, client_id, "Hilman koti", "Ruokakauppa", Decimal("3.20"))

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 25)
    )

    save_visit_trip(user_ids["worker"], visit_id, [leg_from_trip(get_trip(trip_id))])

    # The saved route gets longer later
    update_trip(actor_id, trip_id, {"distance_km": Decimal("4.50")})

    assert get_trip(trip_id)["distance_km"] == Decimal("4.50")
    assert get_visit_trip(user_ids["worker"], visit_id)[0]["distance_km"] == Decimal("3.20")
    assert get_visit(user_ids["worker"], visit_id)["distance_km"] == Decimal("3.20")

    # The saved route is deleted; the visit's history stays
    assert delete_trip(actor_id, trip_id) is True

    assert get_trip(trip_id) is None
    assert get_saved_legs(cursor, visit_id) == [
        (1, "Hilman koti", "Ruokakauppa", Decimal("3.20")),
    ]
    assert get_visit(user_ids["worker"], visit_id)["distance_km"] == Decimal("3.20")


def test_multi_stop_trip_on_planned_visit(integration_database, user_ids):
    cursor = integration_database
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 25),
        planned_duration_minutes=90,
        priority=1,
        description="Ruokaostokset"
    )

    visit_before = get_visit(user_ids["worker"], visit_id)

    assert save_visit_trip(user_ids["worker"], visit_id, THREE_LEGS) is True

    legs = get_visit_trip(user_ids["worker"], visit_id)

    positions = []

    for leg in legs:
        positions.append(leg["position"])

    assert positions == [1, 2, 3]
    assert legs[0]["destination"] == "Kauppa"
    assert legs[1]["distance_km"] == Decimal("1.50")
    assert legs[2]["destination"] == "Koti"

    visit_after = get_visit(user_ids["worker"], visit_id)

    assert visit_after["distance_km"] == Decimal("8.80")

    # The legs and the visit's total agree in the database
    cursor.execute(
        "SELECT SUM(distance_km) FROM visit_trip_legs WHERE visit_id = %s",
        (visit_id,)
    )

    assert cursor.fetchone()[0] == visit_after["distance_km"]

    # The plan is not changed by saving the trip
    for field in (
        "status",
        "planned_week",
        "planned_date",
        "planned_at",
        "planned_duration_minutes",
        "priority",
        "description",
    ):
        assert visit_after[field] == visit_before[field]


def test_completing_visit_keeps_trip(integration_database, user_ids):
    cursor = integration_database
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    # A past day, so the completion date is allowed
    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 18),
        planned_duration_minutes=60
    )

    save_visit_trip(user_ids["worker"], visit_id, THREE_LEGS)

    assert get_visit(user_ids["worker"], visit_id)["distance_km"] == Decimal("8.80")

    assert complete_visit(user_ids["worker"], visit_id) is True

    visit = get_visit(user_ids["worker"], visit_id)

    assert visit["status"] == "completed"
    assert visit["completed_date"] == date(2026, 11, 18)

    # complete_visit() does not clear the kilometres or the legs
    assert visit["distance_km"] == Decimal("8.80")
    assert len(get_visit_trip(user_ids["worker"], visit_id)) == 3

    # The planned duration is used as the actual one, as before
    assert visit["planned_duration_minutes"] == 60
    assert visit["duration_minutes"] == 60


def test_trip_added_after_completion(integration_database, user_ids):
    cursor = integration_database
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    # The kilometres are added at the end of the day
    visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        completed_date=date(2026, 11, 18),
        duration_minutes=90
    )

    assert get_visit(user_ids["worker"], visit_id)["distance_km"] is None

    assert save_visit_trip(user_ids["worker"], visit_id, THREE_LEGS) is True

    visit = get_visit(user_ids["worker"], visit_id)

    assert visit["status"] == "completed"
    assert visit["completed_date"] == date(2026, 11, 18)
    assert visit["duration_minutes"] == 90
    assert visit["distance_km"] == Decimal("8.80")
    assert len(get_visit_trip(user_ids["worker"], visit_id)) == 3


def test_replacing_trip_does_not_touch_other_clients(integration_database, user_ids):
    cursor = integration_database
    hilma_id = create_client(cursor, user_ids["admin"], "Hilma")
    aino_id = create_client(cursor, user_ids["admin"], "Aino")
    service_id = create_service(cursor, user_ids["admin"])

    hilma_visit_id = add_planned_visit(
        user_ids["worker"],
        hilma_id, service_id, planned_date=date(2026, 11, 25)
    )
    aino_visit_id = add_planned_visit(
        user_ids["worker"],
        aino_id, service_id, planned_date=date(2026, 11, 25)
    )

    save_visit_trip(
        user_ids["worker"],
        hilma_visit_id,
        [
            {"start_location": "Koti", "destination": "Kauppa", "distance_km": 3},
            {"start_location": "Kauppa", "destination": "Koti", "distance_km": 3},
        ]
    )

    save_visit_trip(
        user_ids["worker"],
        aino_visit_id,
        [{"start_location": "Ainon koti", "destination": "Pankki", "distance_km": 5}]
    )

    assert get_visit(user_ids["worker"], hilma_visit_id)["distance_km"] == Decimal("6")

    # Hilma's trip is replaced with a longer one
    save_visit_trip(
        user_ids["worker"],
        hilma_visit_id,
        [
            {"start_location": "Koti", "destination": "Kauppa", "distance_km": 3},
            {"start_location": "Kauppa", "destination": "Apteekki", "distance_km": 2},
            {"start_location": "Apteekki", "destination": "Koti", "distance_km": 4},
        ]
    )

    # Exactly the new legs, numbered from 1 again
    assert get_saved_legs(cursor, hilma_visit_id) == [
        (1, "Koti", "Kauppa", Decimal("3.00")),
        (2, "Kauppa", "Apteekki", Decimal("2.00")),
        (3, "Apteekki", "Koti", Decimal("4.00")),
    ]
    assert get_visit(user_ids["worker"], hilma_visit_id)["distance_km"] == Decimal("9")

    # Aino's visit is not touched
    aino_legs = get_visit_trip(user_ids["worker"], aino_visit_id)

    assert len(aino_legs) == 1
    assert aino_legs[0]["start_location"] == "Ainon koti"
    assert get_visit(user_ids["worker"], aino_visit_id)["distance_km"] == Decimal("5")


def test_unknown_distance_is_completed_later(integration_database, user_ids):
    cursor = integration_database
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 25)
    )

    legs_with_gap = [
        {"start_location": "Koti", "destination": "Kauppa", "distance_km": Decimal("3.20")},
        {"start_location": "Kauppa", "destination": "Apteekki", "distance_km": None},
        {"start_location": "Apteekki", "destination": "Koti", "distance_km": Decimal("4.10")},
    ]

    save_visit_trip(user_ids["worker"], visit_id, legs_with_gap)

    # All legs are saved, the gap stays NULL and no partial total is saved
    assert get_saved_legs(cursor, visit_id) == [
        (1, "Koti", "Kauppa", Decimal("3.20")),
        (2, "Kauppa", "Apteekki", None),
        (3, "Apteekki", "Koti", Decimal("4.10")),
    ]
    assert get_visit(user_ids["worker"], visit_id)["distance_km"] is None

    # The missing distance is filled in later
    save_visit_trip(user_ids["worker"], visit_id, THREE_LEGS)

    assert get_visit(user_ids["worker"], visit_id)["distance_km"] == Decimal("8.80")

    # A known zero is not the same as an unknown distance
    zero_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 26)
    )

    save_visit_trip(
        user_ids["worker"],
        zero_visit_id,
        [{"start_location": "Koti", "destination": "Naapuri", "distance_km": Decimal("0.00")}]
    )

    assert get_visit(user_ids["worker"], zero_visit_id)["distance_km"] == Decimal("0.00")


def test_manual_distance_is_kept_without_legs(integration_database, user_ids):
    cursor = integration_database
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    manual_visit_id = add_completed_visit(
        user_ids["worker"],
        client_id,
        service_id,
        completed_date=date(2026, 11, 18),
        distance_km=Decimal("12.50")
    )

    # Another visit gets a trip; the manual one must not change
    other_visit_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 25)
    )

    save_visit_trip(user_ids["worker"], other_visit_id, THREE_LEGS)

    assert get_visit_trip(user_ids["worker"], manual_visit_id) == []
    assert get_visit(user_ids["worker"], manual_visit_id)["distance_km"] == Decimal("12.50")


def test_cancelled_visit_keeps_trip_history(integration_database, user_ids):
    cursor = integration_database
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id, service_id, planned_date=date(2026, 11, 25)
    )

    save_visit_trip(user_ids["worker"], visit_id, THREE_LEGS)
    legs_before = get_visit_trip(user_ids["worker"], visit_id)

    cancel_visit(user_ids["worker"], visit_id)

    visit = get_visit(user_ids["worker"], visit_id)

    # The history stays after cancelling
    assert visit["status"] == "cancelled"
    assert visit["distance_km"] == Decimal("8.80")
    assert get_visit_trip(user_ids["worker"], visit_id) == legs_before

    # A cancelled visit cannot get a new trip
    with pytest.raises(ValueError, match="cancelled"):
        save_visit_trip(
            user_ids["worker"],
            visit_id,
            [{"start_location": "Koti", "destination": "Kauppa", "distance_km": 1}]
        )

    assert get_visit_trip(user_ids["worker"], visit_id) == legs_before
    assert get_visit(user_ids["worker"], visit_id)["distance_km"] == Decimal("8.80")


def test_failure_after_all_legs_rolls_back_everything(
    integration_database,
    user_ids,
    monkeypatch
):
    cursor = integration_database
    client_id = create_client(cursor, user_ids["admin"], "Hilma")
    service_id = create_service(cursor, user_ids["admin"])

    visit_id = add_planned_visit(
        user_ids["worker"],
        client_id,
        service_id,
        planned_date=date(2026, 11, 25),
        planned_duration_minutes=60
    )

    save_visit_trip(user_ids["worker"], visit_id, THREE_LEGS)

    legs_before = get_saved_legs(cursor, visit_id)
    visit_before = get_visit(user_ids["worker"], visit_id)

    # A real database error at the very last step: the old legs are already
    # deleted and all new legs inserted when the total is updated.
    # (tests/test_visit_trips.py covers a failure in the middle of the
    # inserts.)
    def update_then_fail(cursor, updated_by_user_id, visit_id, distance_km):
        cursor.execute(
            "UPDATE visits SET no_such_column = %s WHERE id = %s",
            (distance_km, visit_id)
        )

    monkeypatch.setattr(
        "carelog.services.visit_trips.update_visit_distance",
        update_then_fail
    )

    new_legs = [
        {"start_location": "Koti", "destination": "Pankki", "distance_km": Decimal("5.00")},
        {"start_location": "Pankki", "destination": "Posti", "distance_km": Decimal("1.00")},
        {"start_location": "Posti", "destination": "Koti", "distance_km": Decimal("5.50")},
        {"start_location": "Koti", "destination": "Naapuri", "distance_km": Decimal("0.20")},
    ]

    with pytest.raises(psycopg.Error):
        save_visit_trip(user_ids["worker"], visit_id, new_legs)

    # The old legs, the old total and the rest of the visit are as before,
    # and no new legs were left behind
    assert get_saved_legs(cursor, visit_id) == legs_before
    assert get_visit(user_ids["worker"], visit_id) == visit_before

    cursor.execute(
        "SELECT COUNT(*) FROM visit_trip_legs WHERE visit_id = %s",
        (visit_id,)
    )

    assert cursor.fetchone()[0] == 3
