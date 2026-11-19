from carelog.database.connection import get_connection
from carelog.database.repositories.insert_client import insert_client

def add_client(
        first_name: str,
        last_name: str,
        phone: str | None = None,
        email: str | None = None,
        street_address: str | None = None
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


    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        client_id = insert_client(cursor, first_name, last_name, phone, email, street_address)
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