from psycopg import Cursor


def select_user(cursor: Cursor, user_id: int) -> dict | None:

    # Returns only the columns needed to check a user: never password_hash
    # or other personal data. Returns None if the user does not exist.
    #
    # The row is not locked: the application account has no UPDATE on
    # users, and SELECT ... FOR SHARE would need it.

    cursor.execute(
        """
        SELECT id, role, is_active
        FROM users
        WHERE id = %s
        """,
        (user_id,)
    )

    result = cursor.fetchone()

    if result is None:
        return None

    return {
        "id": result[0],
        "role": result[1],
        "is_active": result[2],
    }
