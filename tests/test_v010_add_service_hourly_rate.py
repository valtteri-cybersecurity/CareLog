from decimal import Decimal

from carelog.database.migrations import v003_services, v010_add_service_hourly_rate
from tests.migration_helpers import get_columns, insert_service


def test_table_structure(cursor):
    v003_services.upgrade(cursor)
    v010_add_service_hourly_rate.upgrade(cursor)

    assert ("default_hourly_rate", "decimal(10,2)", "YES", None) in get_columns(
        cursor, "services"
    )


def test_upgrade_preserves_existing_row(cursor):
    v003_services.upgrade(cursor)
    service_id = insert_service(cursor)

    v010_add_service_hourly_rate.upgrade(cursor)

    cursor.execute(
        "SELECT name, default_hourly_rate FROM services WHERE id = %s",
        (service_id,),
    )
    assert cursor.fetchone() == ("Test service", None)


def test_hourly_rate_can_be_stored(cursor):
    v003_services.upgrade(cursor)
    v010_add_service_hourly_rate.upgrade(cursor)
    rate = Decimal("42.50")
    cursor.execute(
        "INSERT INTO services (name, default_hourly_rate) VALUES (%s, %s)",
        ("Test service", rate),
    )
    service_id = cursor.lastrowid

    v010_add_service_hourly_rate.upgrade(cursor)

    cursor.execute("SELECT default_hourly_rate FROM services WHERE id = %s", (service_id,))
    assert cursor.fetchone() == (rate,)
