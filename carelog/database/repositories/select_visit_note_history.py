from psycopg import Cursor


def select_visit_note_history(
    cursor: Cursor,
    note_id: int,
    owner_user_id: int | None = None
) -> list[dict]:

    # With owner_user_id only the history of a note of that worker's visit
    # is returned.
    sql = """
        SELECT h.id, h.note_id, h.old_content, h.new_content, h.edited_at,
               h.edited_by_user_id
        FROM visit_note_history AS h
        JOIN visit_notes AS n
          ON n.id = h.note_id
        JOIN visits AS v
          ON v.id = n.visit_id
        WHERE h.note_id = %s
    """

    values = [note_id]

    if owner_user_id is not None:
        sql += " AND v.user_id = %s"
        values.append(owner_user_id)

    # Oldest change first. Changes saved at the same time are ordered by
    # id, which grows in the order the rows were added.
    sql += " ORDER BY h.edited_at ASC, h.id ASC"

    cursor.execute(sql, tuple(values))

    results = cursor.fetchall()
    history = []

    for result in results:
        change = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            change[column_name] = result[index]

        history.append(change)

    return history
