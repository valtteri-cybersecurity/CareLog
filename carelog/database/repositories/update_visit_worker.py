from psycopg import Cursor


def update_visit_worker_record(
    cursor: Cursor,
    updated_by_user_id: int,
    visit_id: int,
    user_id: int
) -> bool:

    # Changes the worker of a planned visit. The service has already
    # locked the row and checked the status and the users in the same
    # transaction. AND status = 'planned' makes sure that a completed or
    # cancelled visit never gets another worker here.
    #
    # created_by_user_id is not changed. The expenses of the visit keep
    # their own user_id.

    cursor.execute(
        """
        UPDATE visits
        SET user_id = %s,
            updated_by_user_id = %s
        WHERE id = %s
        AND status = 'planned'
        """,
        (user_id, updated_by_user_id, visit_id)
    )

    if cursor.rowcount == 0:
        return False

    return True
