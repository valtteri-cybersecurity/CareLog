from psycopg import Cursor


def select_visit_note_history(cursor: Cursor, note_id: int) -> list[dict]:

    # Oldest change first. Changes saved at the same time are ordered by
    # id, which grows in the order the rows were added.
    sql = """
        SELECT id, note_id, old_content, new_content, edited_at, edited_by_user_id
        FROM visit_note_history
        WHERE note_id = %s
        ORDER BY edited_at ASC, id ASC
    """

    cursor.execute(sql, (note_id,))

    results = cursor.fetchall()
    history = []

    for result in results:
        change = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            change[column_name] = result[index]

        history.append(change)

    return history
