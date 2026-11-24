from carelog.database.postgres_connection import get_postgres_connection
from carelog.database.repositories.insert_visit_note import insert_visit_note
from carelog.database.repositories.select_visit import select_visit
from carelog.database.repositories.select_visit_notes import select_visit_notes
from carelog.database.repositories.select_visit_note_history import select_visit_note_history
from carelog.database.repositories.update_visit_note import update_visit_note_record
from carelog.services.user_validation import (
    get_active_user,
    get_owner_filter,
    validate_user_id,
)


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

    # CareLog's own upper limit, 65535 bytes. A PostgreSQL TEXT column
    # itself has no practical size limit.
    if len(content.encode("utf-8")) > 65535:
        raise ValueError("Note content is too long")

    return content


def add_visit_note(actor_user_id: int, visit_id: int, content: str) -> int:

    # A worker may add notes only to their own visits, an admin to the
    # visits of every worker.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Visit ID validation
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
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        # The visit row is locked, so its worker cannot change before the
        # note is saved. A missing visit and another worker's visit give
        # the same error, so the other visit's existence is not revealed.
        visit = select_visit(
            cursor,
            visit_id,
            for_update=True,
            owner_user_id=owner_user_id
        )

        if visit is None:
            raise ValueError("Visit not found")

        note_id = insert_visit_note(
            cursor,
            actor["id"],
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


def get_visit_notes(actor_user_id: int, visit_id: int) -> list[dict]:

    # A worker gets the notes of their own visits only. Another worker's
    # visit gives an empty list, as a missing visit does.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

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
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        notes = select_visit_notes(cursor, visit_id, owner_user_id)

        return notes

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def get_visit_note_history(actor_user_id: int, note_id: int) -> list[dict]:

    # A worker gets only the history of notes of their own visits. A note
    # of another worker's visit gives an empty history, as a missing note
    # does.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

    # Note ID validation
    # The history is saved by a trigger in the database whenever the
    # content of a note changes. A note that was never edited, or does
    # not exist, has an empty history. edited_by_user_id is the user that
    # the application gave for the change.

    if type(note_id) is not int:
        raise ValueError("Note ID must be an integer")

    if note_id <= 0:
        raise ValueError("Note ID must be positive")

    # Database operation

    connection = None
    cursor = None

    try:
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        history = select_visit_note_history(cursor, note_id, owner_user_id)

        return history

    finally:
        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


def update_visit_note(actor_user_id: int, note_id: int, content: str) -> bool:

    # A worker may edit notes of their own visits only. A note of another
    # worker's visit gives False, as a missing note does. The creator of
    # the note does not change.

    # Actor validation. The user is checked in the database below, in the
    # same transaction as the rest of the operation.

    validate_user_id(actor_user_id)

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
        connection = get_postgres_connection()
        cursor = connection.cursor()

        actor = get_active_user(cursor, actor_user_id)
        owner_user_id = get_owner_filter(actor, None)

        # The history row is written by the trigger in this transaction,
        # so the note and its history are saved or rolled back together.
        updated = update_visit_note_record(
            cursor,
            actor["id"],
            note_id,
            content,
            owner_user_id
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
