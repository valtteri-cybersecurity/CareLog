from decimal import Decimal

from carelog.database.postgres_connection import get_postgres_connection
from carelog.database.repositories.insert_service import insert_service
from carelog.database.repositories.select_service import select_service
from carelog.database.repositories.select_services import select_services
from carelog.database.repositories.update_service import (
    ALLOWED_FIELDS,
    update_service_record,
)


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

        # CareLog's own upper limit, 65535 bytes. A PostgreSQL TEXT
        # column itself has no practical size limit.
        elif len(description.encode("utf-8")) > 65535:
            raise ValueError("Description is too long")

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
        connection = get_postgres_connection()
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
        connection = get_postgres_connection()
        cursor = connection.cursor()

        service = select_service(cursor, service_id)

        return service

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()



def get_services() -> list[dict]:

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        services = select_services(cursor)

        return services

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()



def update_service(service_id: int, changes: dict) -> bool:

    # Service ID validation

    if type(service_id) is not int:
        raise ValueError("Service ID must be an integer")

    if service_id <= 0:
        raise ValueError("Service ID must be positive")

    # Changes validation

    if not isinstance(changes, dict):
        raise ValueError("Changes must be a dictionary")

    if not changes:
        raise ValueError("No fields to update")

    validated_changes = {}

    for field, value in changes.items():

        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid service field")

        # Name validation

        if field == "name":

            if not isinstance(value, str):
                raise ValueError("Service name must be a string")

            value = value.strip()

            if not value:
                raise ValueError("Service name cannot be empty")

            if len(value) > 150:
                raise ValueError("Service name cannot exceed 150 characters")

            validated_changes[field] = value
            continue

        # Description validation

        if field == "description":

            if value is not None:

                if not isinstance(value, str):
                    raise ValueError("Description must be a string")

                value = value.strip()

                if not value:
                    value = None

                # CareLog's own upper limit, as in add_service()
                elif len(value.encode("utf-8")) > 65535:
                    raise ValueError("Description is too long")

            validated_changes[field] = value
            continue

        # Hourly rate validation

        if field == "default_hourly_rate":

            if value is not None:

                if isinstance(value, bool):
                    raise ValueError("Hourly rate must be a number")

                if not isinstance(value, (int, float, Decimal)):
                    raise ValueError("Hourly rate must be a number")

                value = Decimal(str(value))

                if not value.is_finite():
                    raise ValueError("Hourly rate must be finite")

                if value < 0:
                    raise ValueError("Hourly rate cannot be negative")

                if value > Decimal("99999999.99"):
                    raise ValueError("Hourly rate exceeds database limit")

                if value != value.quantize(Decimal("0.01")):
                    raise ValueError("Hourly rate cannot exceed two decimal places")

            validated_changes[field] = value
            continue

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        updated = update_service_record(
            cursor,
            service_id,
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
