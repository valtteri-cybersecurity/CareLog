from decimal import Decimal

import pytest

from carelog.services.services import (
    add_service,
    get_service,
    get_services,
    update_service,
)
from tests.postgres_helpers import fake_active_user


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # A test that does not replace the connection with the test database
    # must never reach the real database.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a test")

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        connection_not_allowed
    )


def test_add_service_rejects_empty_name():
    with pytest.raises(ValueError):
        add_service(1, "")


def test_add_service_rejects_spaces_name():
    with pytest.raises(ValueError):
        add_service(1, "   ")


def test_add_service_rejects_invalid_name_type():
    with pytest.raises(ValueError):
        add_service(1, 123)


def test_add_service_rejects_long_name():
    with pytest.raises(ValueError):
        add_service(1, "A" * 151)


def test_add_service_rejects_invalid_description():
    with pytest.raises(ValueError):
        add_service(1, "Kaupassa käynti", description=123)


def test_add_service_rejects_negative_rate():
    with pytest.raises(ValueError):
        add_service(1, "Kaupassa käynti", default_hourly_rate=-10)


def test_add_service_rejects_boolean_rate():
    with pytest.raises(ValueError):
        add_service(1, "Kaupassa käynti", default_hourly_rate=True)


def test_add_service_rejects_infinite_rate():
    with pytest.raises(ValueError):
        add_service(1, "Kaupassa käynti", default_hourly_rate=float("inf"))


def test_add_service_rejects_nan_rate():
    with pytest.raises(ValueError):
        add_service(1, "Kaupassa käynti", default_hourly_rate=float("nan"))


def test_add_service_rejects_too_many_decimals():
    with pytest.raises(ValueError):
        add_service(
            1,
            "Kaupassa käynti",
            default_hourly_rate=Decimal("35.555")
        )


def test_add_service_rejects_rate_over_limit():
    with pytest.raises(ValueError):
        add_service(
            1,
            "Kaupassa käynti",
            default_hourly_rate=Decimal("100000000.00")
        )


def test_add_service_saves_to_database(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    service_id = add_service(
        user_ids["worker"],
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
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    service_id = add_service(user_ids["worker"], "Ulkoilu")

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
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(
        cursor,
        created_by_user_id,
        name,
        description,
        default_hourly_rate
    ):
        cursor.execute(
            "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s)",
            (name, created_by_user_id)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.services.insert_service",
        insert_then_fail
    )

    with pytest.raises(RuntimeError):
        add_service(user_ids["worker"], "Ulkoilu")

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
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate, created_by_user_id
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        ("Kaupassa käynti", "Asiointiapu", Decimal("35.50"), user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    service = get_service(service_id)

    assert isinstance(service, dict)
    assert service["id"] == service_id
    assert service["name"] == "Kaupassa käynti"
    assert service["description"] == "Asiointiapu"
    assert service["default_hourly_rate"] == Decimal("35.50")


def test_get_service_returns_none_if_not_found(
    postgres_cursor_with_clients_and_services,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
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
        "carelog.services.services.get_postgres_connection",
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
    postgres_cursor_with_clients_and_services,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    services = get_services()

    assert services == []


def test_get_services_returns_sorted_services(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate, created_by_user_id
        )
        VALUES (%s, %s, %s, %s)
        """,
        ("Ulkoilu", None, None, user_ids["worker"])
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate, created_by_user_id
        )
        VALUES (%s, %s, %s, %s)
        """,
        ("Apteekkiasiointi", "Lääkkeiden nouto", Decimal("35.00"), user_ids["worker"])
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate, created_by_user_id
        )
        VALUES (%s, %s, %s, %s)
        """,
        ("Kaupassa käynti", "Asiointiapu", Decimal("40.00"), user_ids["worker"])
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
        "carelog.services.services.get_postgres_connection",
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



# UPDATE SERVICE TESTS


def test_update_service_rejects_invalid_id():
    with pytest.raises(ValueError):
        update_service(1, "123", {"name": "Ulkoilu"})


def test_update_service_rejects_boolean_id():
    with pytest.raises(ValueError):
        update_service(1, True, {"name": "Ulkoilu"})


def test_update_service_rejects_empty_changes():
    with pytest.raises(ValueError):
        update_service(1, 1, {})


def test_update_service_rejects_invalid_field():
    with pytest.raises(ValueError):
        update_service(1, 1, {"id": 5})


def test_update_service_rejects_empty_name():
    with pytest.raises(ValueError):
        update_service(1, 1, {"name": "   "})


def test_update_service_rejects_invalid_description():
    with pytest.raises(ValueError):
        update_service(1, 1, {"description": 123})


def test_update_service_rejects_negative_rate():
    with pytest.raises(ValueError):
        update_service(1, 1, {"default_hourly_rate": -10})


def test_update_service_changes_name_and_rate(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate, created_by_user_id
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        ("Kaupassa käynti", "Asiointiapu", Decimal("35.50"), user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    updated = update_service(
        user_ids["worker"],
        service_id,
        {
            "name": "  Apteekkiasiointi  ",
            "default_hourly_rate": Decimal("40.25")
        }
    )

    assert updated is True

    cursor.execute(
        """
        SELECT name, description, default_hourly_rate
        FROM services
        WHERE id = %s
        """,
        (service_id,)
    )

    # The description was not given, so it must stay the same
    assert cursor.fetchone() == (
        "Apteekkiasiointi",
        "Asiointiapu",
        Decimal("40.25")
    )


def test_update_service_clears_description_and_rate(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO services (
            name,
            description,
            default_hourly_rate, created_by_user_id
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        ("Kaupassa käynti", "Asiointiapu", Decimal("35.50"), user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    updated = update_service(
        user_ids["worker"],
        service_id,
        {
            "description": None,
            "default_hourly_rate": None
        }
    )

    assert updated is True

    cursor.execute(
        """
        SELECT name, description, default_hourly_rate
        FROM services
        WHERE id = %s
        """,
        (service_id,)
    )

    assert cursor.fetchone() == ("Kaupassa käynti", None, None)


def test_update_service_returns_false_if_not_found(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    updated = update_service(
        user_ids["worker"],
        999999,
        {"name": "Ulkoilu"}
    )

    assert updated is False


def test_update_service_rolls_back_on_error(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def update_then_fail(cursor, updated_by_user_id, service_id, changes):
        cursor.execute(
            """
            UPDATE services
            SET name = %s
            WHERE id = %s
            """,
            ("Ulkoilu", service_id)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.services.update_service_record",
        update_then_fail
    )

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kaupassa käynti", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_service(user_ids["worker"], service_id, {"name": "Ulkoilu"})

    cursor.execute(
        "SELECT name FROM services WHERE id = %s",
        (service_id,)
    )

    assert cursor.fetchone()[0] == "Kaupassa käynti"


def test_update_service_closes_connection_on_error(monkeypatch):

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

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    # The fake cursor cannot run the user check, so it is replaced
    monkeypatch.setattr("carelog.services.services.get_active_user", fake_active_user)

    def update_then_fail(cursor, updated_by_user_id, service_id, changes):
        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.services.update_service_record",
        update_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_service(1, 1, {"name": "Ulkoilu"})

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# USER TRACKING TESTS


def test_service_writes_reject_invalid_actor_id():
    # The user check itself is tested in test_user_validation.py
    for actor_user_id in (None, True, "1", 0):
        with pytest.raises(ValueError):
            add_service(actor_user_id, "Ulkoilu")

        with pytest.raises(ValueError):
            update_service(actor_user_id, 1, {"name": "Ulkoilu"})


def test_service_saves_creator_and_latest_editor(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    worker_id = user_ids["worker"]
    admin_id = user_ids["admin"]

    service_id = add_service(worker_id, "Ulkoilu")

    service = get_service(service_id)
    assert service["created_by_user_id"] == worker_id
    assert service["updated_by_user_id"] is None
    created_updated_at = service["updated_at"]

    assert update_service(admin_id, service_id, {"default_hourly_rate": Decimal("32.00")})

    # get_services() returns the same user columns as get_service()
    service = get_services()[0]
    assert service["created_by_user_id"] == worker_id
    assert service["updated_by_user_id"] == admin_id
    assert service["updated_at"] >= created_updated_at


def test_service_writes_reject_missing_and_inactive_users(
    postgres_cursor_with_clients_and_services,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients_and_services

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.services.get_postgres_connection",
        get_test_connection
    )

    service_id = add_service(user_ids["worker"], "Ulkoilu")
    missing_id = user_ids["admin"] + user_ids["worker"] + 1000

    with pytest.raises(ValueError, match="User not found"):
        add_service(missing_id, "Kauppa-asiointi")

    with pytest.raises(PermissionError):
        update_service(user_ids["inactive"], service_id, {"name": "Kauppa-asiointi"})

    # Nothing was saved
    cursor.execute("SELECT id, name, updated_by_user_id FROM services")

    assert cursor.fetchall() == [(service_id, "Ulkoilu", None)]
