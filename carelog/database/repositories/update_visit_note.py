from psycopg import Cursor


def update_visit_note_record(
    cursor: Cursor,
    note_id: int,
    content: str
) -> bool:

    # Check if note exists and lock it until the transaction ends.
    # The existence is checked here, so the result does not depend on
    # the rowcount of the UPDATE.

    cursor.execute(
        """
        SELECT id
        FROM visit_notes
        WHERE id = %s
        FOR UPDATE
        """,
        (note_id,)
    )

    if cursor.fetchone() is None:
        return False

    # Only the content changes. visit_id and created_at stay the same.

    sql = """
        UPDATE visit_notes
        SET content = %s
        WHERE id = %s
    """

    cursor.execute(sql, (content, note_id))

    return True
