from decimal import Decimal

from carelog.database.connection import get_connection
from carelog.database.repositories.insert_service import insert_service
from carelog.database.repositories.select_service import select_service


def add_service(
    name: str,
    description: str | None = None,
    default_hourly_rate: Decimal | int | float | None = None
) -> int:

    # Name validation

    if not isinstance(name, str):
        raise ValueError("Service name must be a string")

    name = name.strip()

    if not name:
        raise ValueError("Service name cannot be empty")

    if len(name) > 150:
        raise ValueError("Service name cannot exceed 150 characters")

    # Description validation

    if description is not None:

        if not isinstance(description, str):
            raise ValueError("Description must be a string")

        description = description.strip()

        if not description:
            description = None

        elif len(description.encode("utf-8")) > 65535:
            raise ValueError("Description exceeds database limit")

    # Hourly rate validation

    if default_hourly_rate is not None:

        if isinstance(default_hourly_rate, bool):
            raise ValueError("Hourly rate must be a number")

        if not isinstance(default_hourly_rate, (int, float, Decimal)):
            raise ValueError("Hourly rate must be a number")

        default_hourly_rate = Decimal(str(default_hourly_rate))

        if not default_hourly_rate.is_finite():
            raise ValueError("Hourly rate must be finite")

        if default_hourly_rate < 0:
            raise ValueError("Hourly rate cannot be negative")

        if default_hourly_rate > Decimal("99999999.99"):
            raise ValueError("Hourly rate exceeds database limit")

        if default_hourly_rate != default_hourly_rate.quantize(Decimal("0.01")):
            raise ValueError("Hourly rate cannot exceed two decimal places")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        service_id = insert_service(
            cursor,
            name,
            description,
            default_hourly_rate
        )

        connection.commit()

        return service_id

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_service(service_id: int) -> dict | None:

    # Service ID validation

    if type(service_id) is not int:
        raise ValueError("Service ID must be an integer")

    if service_id <= 0:
        raise ValueError("Service ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        service = select_service(cursor, service_id)

        return service

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
