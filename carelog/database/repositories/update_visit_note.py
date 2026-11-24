from psycopg import Cursor


def update_visit_note_record(
    cursor: Cursor,
    updated_by_user_id: int,
    note_id: int,
    content: str,
    owner_user_id: int | None = None
) -> bool:

    # Check if note exists and lock it until the transaction ends.
    # The existence is checked here, so the result does not depend on
    # the rowcount of the UPDATE.
    #
    # The visit row is locked too. A change of the visit's worker waits
    # for this transaction, and with owner_user_id a visit that was given
    # to another worker meanwhile is not found.

    sql = """
        SELECT n.id
        FROM visit_notes AS n
        JOIN visits AS v
          ON v.id = n.visit_id
        WHERE n.id = %s
    """

    values = [note_id]

    if owner_user_id is not None:
        sql += " AND v.user_id = %s"
        values.append(owner_user_id)

    sql += " FOR UPDATE"

    cursor.execute(sql, tuple(values))

    if cursor.fetchone() is None:
        return False

    # The editor of this change. The history trigger of v014 reads it,
    # saves it to updated_by_user_id and to the history row, and clears
    # it, so it is used only for this UPDATE. true: the value disappears
    # when the transaction ends. updated_by_user_id is not set in the
    # UPDATE below, because the trigger decides it.

    cursor.execute(
        "SELECT set_config('carelog.actor_user_id', %s, true)",
        (str(updated_by_user_id),)
    )

    # Only the content changes. visit_id and created_at stay the same.

    sql = """
        UPDATE visit_notes
        SET content = %s
        WHERE id = %s
    """

    cursor.execute(sql, (content, note_id))

    return True
