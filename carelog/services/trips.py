from decimal import Decimal

from carelog.database.connection import get_connection
from carelog.database.repositories.delete_trip import delete_trip_record
from carelog.database.repositories.insert_trip import insert_trip
from carelog.database.repositories.select_trip import select_trip
from carelog.database.repositories.select_trips import select_trips
from carelog.database.repositories.update_trip import (
    ALLOWED_FIELDS,
    update_trip_record,
)


def validate_distance_km(
    distance_km: Decimal | int | float | None
) -> Decimal | None:

    if distance_km is None:
        return None

    if isinstance(distance_km, bool):
        raise ValueError("Distance must be a number")

    if not isinstance(distance_km, (int, float, Decimal)):
        raise ValueError("Distance must be a number")

    distance_km = Decimal(str(distance_km))

    if not distance_km.is_finite():
        raise ValueError("Distance must be finite")

    if distance_km < 0:
        raise ValueError("Distance cannot be negative")

    if distance_km > Decimal("99999999.99"):
        raise ValueError("Distance exceeds database limit")

    if distance_km != distance_km.quantize(Decimal("0.01")):
        raise ValueError("Distance cannot exceed two decimal places")

    return distance_km


def add_trip(
    client_id: int,
    start_location: str,
    destination: str,
    distance_km: Decimal | int | float | None = None
) -> int:

    # Client ID validation
    # The foreign key in the database checks that the client exists.

    if type(client_id) is not int:
        raise ValueError("Client ID must be an integer")

    if client_id <= 0:
        raise ValueError("Client ID must be positive")

    # Start location validation

    if not isinstance(start_location, str):
        raise ValueError("Start location must be a string")

    start_location = start_location.strip()

    if not start_location:
        raise ValueError("Start location cannot be empty")

    if len(start_location) > 255:
        raise ValueError("Start location cannot exceed 255 characters")

    # Destination validation

    if not isinstance(destination, str):
        raise ValueError("Destination must be a string")

    destination = destination.strip()

    if not destination:
        raise ValueError("Destination cannot be empty")

    if len(destination) > 255:
        raise ValueError("Destination cannot exceed 255 characters")

    # Distance validation

    distance_km = validate_distance_km(distance_km)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        trip_id = insert_trip(
            cursor,
            client_id,
            start_location,
            destination,
            distance_km
        )

        connection.commit()

        return trip_id

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_trip(trip_id: int) -> dict | None:

    # Trip ID validation

    if type(trip_id) is not int:
        raise ValueError("Trip ID must be an integer")

    if trip_id <= 0:
        raise ValueError("Trip ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        trip = select_trip(cursor, trip_id)

        return trip

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_trips(client_id: int) -> list[dict]:

    # Client ID validation

    if type(client_id) is not int:
        raise ValueError("Client ID must be an integer")

    if client_id <= 0:
        raise ValueError("Client ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        trips = select_trips(cursor, client_id)

        return trips

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def update_trip(trip_id: int, changes: dict) -> bool:

    # Trip ID validation

    if type(trip_id) is not int:
        raise ValueError("Trip ID must be an integer")

    if trip_id <= 0:
        raise ValueError("Trip ID must be positive")

    # Changes validation

    if not isinstance(changes, dict):
        raise ValueError("Changes must be a dictionary")

    if not changes:
        raise ValueError("No fields to update")

    validated_changes = {}

    for field, value in changes.items():

        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid trip field")

        # Start location and destination validation

        if field == "start_location" or field == "destination":

            if not isinstance(value, str):
                raise ValueError("Location must be a string")

            value = value.strip()

            if not value:
                raise ValueError("Location cannot be empty")

            if len(value) > 255:
                raise ValueError("Location cannot exceed 255 characters")

            validated_changes[field] = value
            continue

        # Distance validation

        if field == "distance_km":
            validated_changes[field] = validate_distance_km(value)
            continue

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        updated = update_trip_record(
            cursor,
            trip_id,
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


def delete_trip(trip_id: int) -> bool:

    # Trip ID validation

    if type(trip_id) is not int:
        raise ValueError("Trip ID must be an integer")

    if trip_id <= 0:
        raise ValueError("Trip ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        deleted = delete_trip_record(
            cursor,
            trip_id
        )

        connection.commit()

        return deleted

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
