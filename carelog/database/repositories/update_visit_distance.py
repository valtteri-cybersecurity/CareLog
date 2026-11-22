from decimal import Decimal

from pymysql.cursors import Cursor


def update_visit_distance(
    cursor: Cursor,
    visit_id: int,
    distance_km: Decimal | None
) -> None:

    # Changes only the total distance of the visit
    sql = """
        UPDATE visits
        SET distance_km = %s
        WHERE id = %s
    """

    cursor.execute(sql, (distance_km, visit_id))
