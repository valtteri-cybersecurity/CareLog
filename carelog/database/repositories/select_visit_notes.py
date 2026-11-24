from psycopg import Cursor


def select_visit_notes(
    cursor: Cursor,
    visit_id: int,
    owner_user_id: int | None = None
) -> list[dict]:

    # With owner_user_id only the notes of that worker's visit are
    # returned. Access follows visits.user_id, not the note's creator.
    sql = """
        SELECT n.id, n.visit_id, n.content, n.created_at, n.updated_at,
               n.created_by_user_id, n.updated_by_user_id
        FROM visit_notes AS n
        JOIN visits AS v
          ON v.id = n.visit_id
        WHERE n.visit_id = %s
    """

    values = [visit_id]

    if owner_user_id is not None:
        sql += " AND v.user_id = %s"
        values.append(owner_user_id)

    # Oldest first. Notes added in the same second are ordered by id.
    sql += " ORDER BY n.created_at ASC, n.id ASC"

    cursor.execute(sql, tuple(values))

    results = cursor.fetchall()
    notes = []

    for result in results:
        note = {}

        for index, column in enumerate(cursor.description):
            column_name = column[0]
            note[column_name] = result[index]

        notes.append(note)

    return notes
