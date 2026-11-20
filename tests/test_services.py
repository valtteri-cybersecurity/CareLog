
from decimal import Decimal

import pytest

from carelog.services.services import add_service


def test_add_service_rejects_empty_name():
    with pytest.raises(ValueError):
        add_service("")


def test_add_service_rejects_spaces_name():
    with pytest.raises(ValueError):
        add_service("   ")


def test_add_service_rejects_invalid_name_type():
    with pytest.raises(ValueError):
        add_service(123)


def test_add_service_rejects_long_name():
    with pytest.raises(ValueError):
        add_service("A" * 151)


def test_add_service_rejects_invalid_description():
    with pytest.raises(ValueError):
        add_service("Kaupassa käynti", description=123)


def test_add_service_rejects_negative_rate():
    with pytest.raises(ValueError):
        add_service("Kaupassa käynti", default_hourly_rate=-10)


def test_add_service_rejects_boolean_rate():
    with pytest.raises(ValueError):
        add_service("Kaupassa käynti", default_hourly_rate=True)


def test_add_service_rejects_infinite_rate():
    with pytest.raises(ValueError):
        add_service("Kaupassa käynti", default_hourly_rate=float("inf"))


def test_add_service_rejects_nan_rate():
    with pytest.raises(ValueError):
        add_service("Kaupassa käynti", default_hourly_rate=float("nan"))


def test_add_service_rejects_too_many_decimals():
    with pytest.raises(ValueError):
        add_service(
            "Kaupassa käynti",
            default_hourly_rate=Decimal("35.555")
        )


def test_add_service_rejects_rate_over_limit():
    with pytest.raises(ValueError):
        add_service(
            "Kaupassa käynti",
            default_hourly_rate=Decimal("100000000.00")
        )


def test_add_service_saves_to_database(
    cursor_with_clients_and_services,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients_and_services

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_connection",
        get_test_connection
    )

    service_id = add_service(
        "  Kaupassa käynti  ",
        "  Asiointiapu  ",
        Decimal("35.50")
    )

    cursor.execute(
        """
        SELECT name, description, default_hourly_rate
        FROM services
        WHERE id = %s
        """,
        (service_id,)
    )

    result = cursor.fetchone()

    assert result == (
        "Kaupassa käynti",
        "Asiointiapu",
        Decimal("35.50")
    )


def test_add_service_saves_null_values(
    cursor_with_clients_and_services,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients_and_services

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_connection",
        get_test_connection
    )

    service_id = add_service("Ulkoilu")

    cursor.execute(
        """
        SELECT description, default_hourly_rate
        FROM services
        WHERE id = %s
        """,
        (service_id,)
    )

    assert cursor.fetchone() == (None, None)


def test_add_service_rolls_back_on_error(
    cursor_with_clients_and_services,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients_and_services

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    def insert_then_fail(
        cursor,
        name,
        description,
        default_hourly_rate
    ):
        cursor.execute(
            "INSERT INTO services (name) VALUES (%s)",
            (name,)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.services.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.services.insert_service",
        insert_then_fail
    )

    with pytest.raises(RuntimeError):
        add_service("Ulkoilu")

    cursor.execute(
        "SELECT COUNT(*) FROM services WHERE name = %s",
        ("Ulkoilu",)
    )

    assert cursor.fetchone()[0] == 0
