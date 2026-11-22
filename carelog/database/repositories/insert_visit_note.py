from pymysql.cursors import Cursor


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
    """

    cursor.execute(
        sql,
        (visit_id, content)
    )

    return cursor.lastrowid
