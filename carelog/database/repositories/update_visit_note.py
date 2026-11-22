from pymysql.cursors import Cursor


def update_visit_note_record(
    cursor: Cursor,
    note_id: int,
    content: str
) -> bool:

    # Check if note exists and lock it until the transaction ends.
    # The rowcount of the UPDATE is not used, because it is 0 when the
    # new content is the same as the old one.

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
