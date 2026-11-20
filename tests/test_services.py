from decimal import Decimal

import pytest

from carelog.services.services import add_service, get_service, get_services


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



# GET SERVICE TESTS


def test_get_service_rejects_invalid_id_type():
    with pytest.raises(ValueError):
        get_service("123")


def test_get_service_rejects_none_id():
    with pytest.raises(ValueError):
        get_service(None)


def test_get_service_rejects_boolean_id():
    with pytest.raises(ValueError):
        get_service(True)


def test_get_service_rejects_zero_id():
    with pytest.raises(ValueError):
        get_service(0)


def test_get_service_rejects_negative_id():
    with pytest.raises(ValueError):
        get_service(-1)


def test_get_service_returns_service(
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

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate
        )
        VALUES (%s, %s, %s)
        """,
        ("Kaupassa käynti", "Asiointiapu", Decimal("35.50"))
    )

    service_id = cursor.lastrowid

    service = get_service(service_id)

    assert isinstance(service, dict)
    assert service["id"] == service_id
    assert service["name"] == "Kaupassa käynti"
    assert service["description"] == "Asiointiapu"
    assert service["default_hourly_rate"] == Decimal("35.50")


def test_get_service_returns_none_if_not_found(
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

    service = get_service(999999)

    assert service is None


def test_get_service_closes_connection_on_error(monkeypatch):

    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False

        def cursor(self):
            return self.test_cursor

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def select_then_fail(cursor, service_id):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.services.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.services.select_service",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_service(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True



# GET SERVICES TESTS


def test_get_services_returns_empty_list(
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

    services = get_services()

    assert services == []


def test_get_services_returns_sorted_services(
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

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate
        )
        VALUES (%s, %s, %s)
        """,
        ("Ulkoilu", None, None)
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate
        )
        VALUES (%s, %s, %s)
        """,
        ("Apteekkiasiointi", "Lääkkeiden nouto", Decimal("35.00"))
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate
        )
        VALUES (%s, %s, %s)
        """,
        ("Kaupassa käynti", "Asiointiapu", Decimal("40.00"))
    )

    services = get_services()

    assert len(services) == 3

    assert services[0]["name"] == "Apteekkiasiointi"
    assert services[1]["name"] == "Kaupassa käynti"
    assert services[2]["name"] == "Ulkoilu"

    assert isinstance(services[0]["id"], int)
    assert services[0]["description"] == "Lääkkeiden nouto"
    assert services[0]["default_hourly_rate"] == Decimal("35.00")

    assert services[2]["description"] is None
    assert services[2]["default_hourly_rate"] is None


def test_get_services_closes_connection_on_error(monkeypatch):

    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False

        def cursor(self):
            return self.test_cursor

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def select_then_fail(cursor):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.services.get_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.services.select_services",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_services()

    assert connection.test_cursor.closed is True
    assert connection.closed is True
