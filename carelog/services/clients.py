from carelog.database.connection import get_connection
from carelog.database.repositories.insert_client import insert_client

def add_client(first_name: str, last_name: str) -> int:
    if not isinstance(first_name, str) or not isinstance(last_name, str):
        raise ValueError("Names must be strings")

    first_name = first_name.strip()
    last_name = last_name.strip()

    if not first_name or not last_name:
        raise ValueError("Names cannot be empty")

    if len(first_name) > 100 or len(last_name) > 100:
        raise ValueError("Names cannot exceed 100 characters")

    connection = None
    cursor = None
    try:
        connection = get_connection()
        cursor = connection.cursor()

        client_id = insert_client(cursor, first_name, last_name)
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