from math import isfinite

from carelog.database.repositories.update_client import (
    ALLOWED_FIELDS,
    update_client_record,
)
from carelog.database.connection import get_connection
from carelog.database.repositories.insert_client import insert_client
from carelog.database.repositories.select_client import select_client
from carelog.database.repositories.select_clients import select_clients
from carelog.database.repositories.archive_client import archive_client_record


def add_client(
        first_name: str,
        last_name: str,
        phone: str | None = None,
        email: str | None = None,
        street_address: str | None = None,
        postal_code: str | None = None,
        city: str | None = None,
        distance_from_home_km: float | int | None = None
    ) -> int:
    

    # Name validation

    if not isinstance(first_name, str) or not isinstance(last_name, str):
        raise ValueError("Names must be strings")

    first_name = first_name.strip()
    last_name = last_name.strip()

    if not first_name or not last_name:
        raise ValueError("Names cannot be empty")

    if len(first_name) > 100 or len(last_name) > 100:
        raise ValueError("Names cannot exceed 100 characters")


    # Phone number validation

    if not isinstance(phone, str) and phone is not None:
        raise ValueError("Phone number must be strings")
    
    if not phone:
        phone = None
    
    else:
        phone = phone.strip()
        if phone == "":
            raise ValueError("Phone number cannot be spaces")
        if len(phone) > 50:
            raise ValueError("Phone number cannot exceed 50 characters")


    # Email validation

    if not isinstance(email, str) and email is not None:
        raise ValueError("Email must be strings")

    if not email:
        email = None

    else:
        email = email.strip()

        if email == "":
            raise ValueError("Email cannot be spaces")

        if len(email) > 255:
            raise ValueError("Email cannot exceed 255 characters")

        if email.count("@") != 1:
            raise ValueError("Email must contain exactly one '@'")

        local, domain = email.split("@")

        if not local or not domain:
            raise ValueError("Email must contain a local part and domain")

        for character in email:
            if character.isspace():
                raise ValueError("Email cannot contain whitespace")


    # Street address validation:

    if not isinstance(street_address, str) and street_address is not None:
        raise ValueError("Street address must be strings")

    if not street_address:
        street_address = None

    else:
        street_address = street_address.strip()

        if street_address == "":
            raise ValueError("Street address cannot be spaces")

        if len(street_address) > 255:
            raise ValueError("Street address cannot exceed 255 characters")

    
    # Postal code validation

    if not isinstance(postal_code, str) and postal_code is not None:
        raise ValueError("Postal code must be a string")

    if not postal_code:
        postal_code = None

    else:
        postal_code = postal_code.strip()

        if not postal_code:
            raise ValueError("Postal code cannot be spaces")

        if len(postal_code) > 20:
            raise ValueError("Postal code cannot exceed 20 characters")

        if not postal_code.isascii() or not postal_code.isdigit():
            raise ValueError("Postal code must contain only digits")


    # City validation

    if not isinstance(city, str) and city is not None:
        raise ValueError("City must be a string")

    if not city:
        city = None

    else:
        city = city.strip()

        if not city:
            raise ValueError("City cannot be spaces")

        if len(city) > 100:
            raise ValueError("City cannot exceed 100 characters")


    # Distance from home validation

    if distance_from_home_km is not None:
        if isinstance(distance_from_home_km, bool):
            raise ValueError("Distance must be a number")

        if not isinstance(distance_from_home_km, (int, float)):
            raise ValueError("Distance must be a number")

        if not isfinite(distance_from_home_km):
            raise ValueError("Distance must be finite")

        if distance_from_home_km <= 0:
            raise ValueError("Distance must be positive")

        if distance_from_home_km > 99999999.99:
            raise ValueError("Distance exceeds database limit")


    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        client_id = insert_client(cursor, first_name, last_name, phone, email, street_address, postal_code, city, distance_from_home_km)
        connection.commit()
        return client_id

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()
        if connection is not None:
            connection.close()



from pymysql.cursors import Cursor



def get_client(client_id: int) -> dict | None:

    # Client ID validation

    if type(client_id) is not int:
        raise ValueError("Client ID must be an integer")

    if client_id <= 0:
        raise ValueError("Client ID must be positive")

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        client = select_client(cursor, client_id)

        return client

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_clients() -> list[dict]:
    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        clients = select_clients(cursor)

        return clients

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()



def update_client(client_id: int, changes: dict) -> bool:

    # Client ID validation

    if type(client_id) is not int:
        raise ValueError("Client ID must be an integer")

    if client_id <= 0:
        raise ValueError("Client ID must be positive")

    # Changes validation

    if not isinstance(changes, dict):
        raise ValueError("Changes must be a dictionary")

    if not changes:
        raise ValueError("No fields to update")

    validated_changes = {}

    for field, value in changes.items():

        if field not in ALLOWED_FIELDS:
            raise ValueError("Invalid client field")

        # Distance validation

        if field == "distance_from_home_km":

            if value is not None:
                if isinstance(value, bool):
                    raise ValueError("Invalid distance type")

                if not isinstance(value, (int, float)):
                    raise ValueError("Invalid distance type")

                if not isfinite(value):
                    raise ValueError("Distance must be finite")

                if value <= 0:
                    raise ValueError("Distance must be positive")

                if value > 99999999.99:
                    raise ValueError("Distance exceeds limit")

            validated_changes[field] = value
            continue

        # Required fields

        if field == "first_name" or field == "last_name":

            if not isinstance(value, str):
                raise ValueError("Name must be a string")

            value = value.strip()

            if not value:
                raise ValueError("Name cannot be empty")

        # Optional fields

        else:
            if value is None or value == "":
                validated_changes[field] = None
                continue

            if not isinstance(value, str):
                raise ValueError("Field must be a string")

            value = value.strip()

            if not value:
                raise ValueError("Field cannot be spaces")

        # Length validation

        if len(value) > ALLOWED_FIELDS[field]:
            raise ValueError("Field exceeds maximum length")

        # Email validation

        if field == "email":

            if value.count("@") != 1:
                raise ValueError("Invalid email address")

            local, domain = value.split("@")

            if not local or not domain:
                raise ValueError("Invalid email address")

            for character in value:
                if character.isspace():
                    raise ValueError("Email cannot contain whitespace")

        validated_changes[field] = value

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        updated = update_client_record(
            cursor,
            client_id,
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



def archive_client(client_id: int) -> bool:

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

        archived = archive_client_record(
            cursor,
            client_id
        )

        connection.commit()

        return archived

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()
