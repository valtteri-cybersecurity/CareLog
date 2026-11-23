from psycopg import Cursor


def insert_visit_note(
    cursor: Cursor,
    visit_id: int,
    content: str
) -> int:

    # The database fills in created_at.
    # No commit here, so the same function can be used inside another
    # transaction, for example when a visit and its note are saved together.

    sql = """
        INSERT INTO visit_notes (
            visit_id,
            content
        )
        VALUES (%s, %s)
        RETURNING id
    """

    cursor.execute(
        sql,
        (visit_id, content)
    )

    # RETURNING id gives the id that PostgreSQL created for the row.
    return cursor.fetchone()[0]
