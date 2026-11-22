from carelog.database.connection import get_connection
from carelog.database.repositories.delete_visit_trip_legs import delete_visit_trip_legs
from carelog.database.repositories.insert_visit_trip_leg import insert_visit_trip_leg
from carelog.database.repositories.select_visit_status_for_update import (
    select_visit_status_for_update,
)
from carelog.database.repositories.select_visit_trip_legs import select_visit_trip_legs
from carelog.database.repositories.update_visit_distance import update_visit_distance
from carelog.services.trips import calculate_trip_distance, validate_trip_leg


def save_visit_trip(visit_id: int, legs: list[dict]) -> bool:

    # Saves the legs of the trip driven for a visit and the total distance
    # of the visit in one transaction. A new list replaces the old legs.
    # visits.distance_km stays the only source of kilometres for reports.

    # Visit ID validation

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Legs validation, before the database is touched.
    # calculate_trip_distance() checks the list and every leg, and returns
    # None if any distance is unknown.

    total_km = calculate_trip_distance(legs)

    # The cleaned copies of the legs are the ones that are saved
    validated_legs = []

    for leg in legs:
        validated_legs.append(validate_trip_leg(leg))

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        # The visit is locked, so two saves for the same visit cannot mix.
        status = select_visit_status_for_update(cursor, visit_id)

        if status is None:
            return False

        if status != "planned" and status != "completed":
            raise ValueError("Trip legs cannot be saved for a cancelled visit")

        delete_visit_trip_legs(cursor, visit_id)

        # Positions start from 1 in the order the user gave
        position = 1

        for leg in validated_legs:
            insert_visit_trip_leg(
                cursor,
                visit_id,
                position,
                leg["start_location"],
                leg["destination"],
                leg["distance_km"]
            )

            position += 1

        update_visit_distance(cursor, visit_id, total_km)

        connection.commit()

        return True

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_visit_trip(visit_id: int) -> list[dict]:

    # Visit ID validation
    # A visit without legs, or a visit that does not exist, gives [].

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        legs = select_visit_trip_legs(cursor, visit_id)

        return legs

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
