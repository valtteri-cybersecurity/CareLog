from pymysql.cursors import Cursor


def select_visit_notes(cursor: Cursor, visit_id: int) -> list[dict]:

    # Oldest first. Notes added in the same second are ordered by id.
    sql = """
        SELECT id, visit_id, content, created_at
        FROM visit_notes
        WHERE visit_id = %s
        ORDER BY created_at ASC, id ASC
    """

    cursor.execute(sql, (visit_id,))

    results = cursor.fetchall()
    notes = []

    for result in results:
        note = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            note[column_name] = result[index]

        notes.append(note)

    return notes
