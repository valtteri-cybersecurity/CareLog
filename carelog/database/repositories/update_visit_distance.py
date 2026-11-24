from decimal import Decimal

from psycopg import Cursor


def update_visit_distance(
    cursor: Cursor,
    updated_by_user_id: int,
    visit_id: int,
    distance_km: Decimal | None
) -> None:

    # Changes only the total distance and the latest editor of the visit
    sql = """
        UPDATE visits
        SET distance_km = %s,
            updated_by_user_id = %s
        WHERE id = %s
    """

    cursor.execute(sql, (distance_km, updated_by_user_id, visit_id))
