from carelog.database.connection import get_connection
from carelog.database.repositories.insert_visit_note import insert_visit_note
from carelog.database.repositories.select_visit_notes import select_visit_notes
from carelog.database.repositories.update_visit_note import update_visit_note_record


def validate_note_content(content: str) -> str:

    # Error messages never contain the note itself, because notes can
    # hold sensitive information about the client.

    if not isinstance(content, str):
        raise ValueError("Note content must be a string")

    # strip() removes spaces, tabs and line breaks only from the edges.
    # Line breaks inside the text are kept.
    content = content.strip()

    if not content:
        raise ValueError("Note content cannot be empty")

    if len(content.encode("utf-8")) > 65535:
        raise ValueError("Note content exceeds database limit")

    return content


def add_visit_note(visit_id: int, content: str) -> int:

    # Visit ID validation
    # The foreign key in the database checks that the visit exists.
    # A note can be added to a visit in any status.

    if type(visit_id) is not int:
        raise ValueError("Visit ID must be an integer")

    if visit_id <= 0:
        raise ValueError("Visit ID must be positive")

    # Content validation

    content = validate_note_content(content)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        note_id = insert_visit_note(
            cursor,
            visit_id,
            content
        )

        connection.commit()

        return note_id

    except Exception:
        if connection is not None:
            connection.rollback()
        raise

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_visit_notes(visit_id: int) -> list[dict]:

    # Visit ID validation
    # A visit that does not exist simply has no notes, so the result is
    # an empty list. Notes are returned for visits in any status.

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

        notes = select_visit_notes(cursor, visit_id)

        return notes

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def update_visit_note(note_id: int, content: str) -> bool:

    # Note ID validation
    # A note can be corrected for a visit in any status.

    if type(note_id) is not int:
        raise ValueError("Note ID must be an integer")

    if note_id <= 0:
        raise ValueError("Note ID must be positive")

    # Content validation

    content = validate_note_content(content)

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = connection.cursor()

        updated = update_visit_note_record(
            cursor,
            note_id,
            content
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
