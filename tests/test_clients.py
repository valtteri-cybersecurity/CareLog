from decimal import Decimal

import pytest

from carelog.services.clients import add_client, get_client, get_clients, update_client, archive_client


def test_add_client_rejects_empty_first_name():
    with pytest.raises(ValueError):
        add_client("", "Virtanen")


def test_add_client_rejects_empty_last_name():
    with pytest.raises(ValueError):
        add_client("Hilma", "")


def test_add_client_rejects_spaces_first_name():
    with pytest.raises(ValueError):
        add_client("    ", "Virtanen")


def test_add_client_rejects_spaces_last_name():
    with pytest.raises(ValueError):
        add_client("Pena", "    ")


def test_add_client_rejects_over_length_first_name():
    test_name = "A" * 101

    with pytest.raises(ValueError):
        add_client(test_name, "Virtanen")


def test_add_client_rejects_over_length_last_name():
    test_name = "A" * 101

    with pytest.raises(ValueError):
        add_client("Arvo", test_name)


def test_add_client_rejects_invalid_type_first_name():
    with pytest.raises(ValueError):
        add_client(69, "Mauno")


def test_add_client_rejects_invalid_type_last_name():
    with pytest.raises(ValueError):
        add_client("Rauno", 88)


def test_add_client_rejects_invalid_phone_type():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", 123456)


def test_add_client_rejects_over_length_phone():
    test_phone = "1" * 51

    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", test_phone)


def test_add_client_rejects_spaces_phone():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", "   ")


def test_add_client_saves_to_database(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    assert isinstance(client_id, int)
    assert client_id > 0

    cursor.execute(
        """
        SELECT first_name, last_name
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone() == ("Hilma", "Virtanen")


def test_add_client_rolls_back_on_insert_error(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(
        cursor,
        first_name,
        last_name,
        phone,
        email,
        street_address,
        postal_code,
        city,
        distance_from_home_km
    ):
        cursor.execute(
            """
            INSERT INTO clients (
                first_name, last_name, phone, email, street_address,
                postal_code, city, distance_from_home_km
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                first_name, last_name, phone, email, street_address,
                postal_code, city, distance_from_home_km
            )
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.clients.insert_client",
        insert_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_client("Hilma", "Virtanen")

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM clients
        WHERE first_name = %s AND last_name = %s
        """,
        ("Hilma", "Virtanen")
    )

    assert cursor.fetchone()[0] == 0


def test_add_client_strips_whitespace(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("  Hilma  ", "  Virtanen  ")

    cursor.execute(
        """
        SELECT first_name, last_name
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone() == ("Hilma", "Virtanen")


def test_add_client_saves_phone(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client(
        "Hilma",
        "Virtanen",
        " 0401234567 "
    )

    cursor.execute(
        """
        SELECT phone
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] == "0401234567"


def test_add_client_saves_null_phone(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        """
        SELECT phone
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_phone_as_null(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", "")

    cursor.execute(
        """
        SELECT phone
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] is None



def test_add_client_rejects_invalid_email_type():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email=123456)


def test_add_client_rejects_over_length_email():
    test_email = "A" * 256

    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email=test_email)


def test_add_client_rejects_spaces_email():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email="   ")


def test_add_client_saves_email(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client(
        "Hilma",
        "Virtanen",
        email=" hilma@example.com "
    )

    cursor.execute(
        """
        SELECT email
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] == "hilma@example.com"


def test_add_client_saves_null_email(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        """
        SELECT email
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_email_as_null(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client(
        "Hilma",
        "Virtanen",
        email=""
    )

    cursor.execute(
        """
        SELECT email
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_rejects_email_without_at():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email="hilma.example.com")


def test_add_client_rejects_email_multiple_at():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email="hilma@@example.com")


def test_add_client_rejects_email_without_local():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email="@example.com")


def test_add_client_rejects_email_without_domain():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email="hilma@")


def test_add_client_rejects_email_with_whitespace():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", email="hilma@\texample.com")


def test_add_client_rejects_invalid_street_address_type():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", street_address=12345)


def test_add_client_rejects_over_length_street_address():
    test_address = "A" * 256

    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", street_address=test_address)


def test_add_client_rejects_spaces_street_address():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", street_address="   ")


def test_add_client_saves_street_address(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client(
        "Hilma",
        "Virtanen",
        street_address="  Kauppakatu 12  "
    )

    cursor.execute(
        """
        SELECT street_address
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] == "Kauppakatu 12"


def test_add_client_rejects_invalid_postal_code_type():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", postal_code=12345)


def test_add_client_rejects_over_length_postal_code():
    test_postal_code = "1" * 21

    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", postal_code=test_postal_code)


def test_add_client_rejects_spaces_postal_code():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", postal_code="   ")


def test_add_client_rejects_invalid_city_type():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", city=12345)


def test_add_client_rejects_over_length_city():
    test_city = "A" * 101

    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", city=test_city)


def test_add_client_rejects_spaces_city():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", city="   ")


def test_add_client_rejects_invalid_distance_type():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", distance_from_home_km="3.5")


def test_add_client_rejects_too_many_decimals_in_distance():
    # DECIMAL(10,2) would round 4.567 to 4.57 without an error
    with pytest.raises(ValueError, match="two decimal places"):
        add_client("Hilma", "Virtanen", distance_from_home_km=4.567)


def test_add_client_rejects_negative_distance():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", distance_from_home_km=-3.5)


def test_add_client_rejects_infinite_distance():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", distance_from_home_km=float("inf"))


def test_add_client_rejects_over_limit_distance():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", distance_from_home_km=100000000.0)

# Street address: optional values


def test_add_client_saves_null_street_address(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT street_address FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_street_address_as_null(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", street_address="")

    cursor.execute(
        "SELECT street_address FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


# Postal code: SQL storage and leading zeroes


def test_add_client_saves_postal_code(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", postal_code=" 00100 ")

    cursor.execute(
        "SELECT postal_code FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] == "00100"


def test_add_client_saves_null_postal_code(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT postal_code FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_postal_code_as_null(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", postal_code="")

    cursor.execute(
        "SELECT postal_code FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


# City: SQL storage and optional values


def test_add_client_saves_city(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", city=" Tampere ")

    cursor.execute(
        "SELECT city FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] == "Tampere"


def test_add_client_saves_null_city(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT city FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_city_as_null(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", city="")

    cursor.execute(
        "SELECT city FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


# Distance from home: DECIMAL(10,2) storage and optional value


def test_add_client_saves_distance(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client(
        "Hilma", "Virtanen", distance_from_home_km=3.5
    )

    cursor.execute(
        "SELECT distance_from_home_km FROM clients WHERE id = %s",
        (client_id,)
    )

    assert str(cursor.fetchone()[0]) == "3.50"


def test_client_distance_can_be_zero(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    # 0 km is allowed, as in the database CHECK constraint
    client_id = add_client("Hilma", "Virtanen", distance_from_home_km=0)

    cursor.execute(
        "SELECT distance_from_home_km FROM clients WHERE id = %s",
        (client_id,)
    )
    assert str(cursor.fetchone()[0]) == "0.00"

    assert update_client(client_id, {"distance_from_home_km": Decimal("4.57")}) is True

    cursor.execute(
        "SELECT distance_from_home_km FROM clients WHERE id = %s",
        (client_id,)
    )
    assert cursor.fetchone()[0] == Decimal("4.57")

    assert update_client(client_id, {"distance_from_home_km": 0.0}) is True

    cursor.execute(
        "SELECT distance_from_home_km FROM clients WHERE id = %s",
        (client_id,)
    )
    assert str(cursor.fetchone()[0]) == "0.00"


def test_add_client_saves_null_distance(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT distance_from_home_km FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


# GET CLIENT TESTS


def test_get_client_rejects_invalid_id_type():
    with pytest.raises(ValueError):
        get_client("123")


def test_get_client_rejects_none_id():
    with pytest.raises(ValueError):
        get_client(None)


def test_get_client_rejects_boolean_id():
    with pytest.raises(ValueError):
        get_client(True)


def test_get_client_rejects_zero_id():
    with pytest.raises(ValueError):
        get_client(0)


def test_get_client_rejects_negative_id():
    with pytest.raises(ValueError):
        get_client(-1)


def test_get_client_returns_client(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, city)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        ("Hilma", "Virtanen", "Tampere")
    )

    client_id = cursor.fetchone()[0]

    client = get_client(client_id)

    assert isinstance(client, dict)
    assert client["id"] == client_id
    assert client["first_name"] == "Hilma"
    assert client["last_name"] == "Virtanen"
    assert client["city"] == "Tampere"


def test_get_client_returns_none_if_not_found(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    client = get_client(999999)

    assert client is None


def test_get_client_closes_connection_on_error(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    connections = []

    def get_test_connection():
        connection = connect_to_test_postgres(database=database)
        connections.append(connection)
        return connection

    def select_then_fail(cursor, client_id):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.clients.select_client",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_client(1)

    assert connections[0].closed is True


def test_get_clients_returns_empty_list(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    clients = get_clients()

    assert clients == []


def test_get_clients_returns_clients_in_name_order(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name)
        VALUES (%s, %s), (%s, %s)
        """,
        ("Hilma", "Virtanen", "Aino", "Aalto")
    )

    clients = get_clients()

    assert isinstance(clients, list)
    assert len(clients) == 2
    assert isinstance(clients[0], dict)
    assert clients[0]["first_name"] == "Aino"
    assert clients[0]["last_name"] == "Aalto"
    assert clients[1]["first_name"] == "Hilma"
    assert clients[1]["last_name"] == "Virtanen"


def test_get_clients_excludes_archived_clients(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name)
        VALUES (%s, %s)
        """,
        ("Hilma", "Virtanen")
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, archived_at)
        VALUES (%s, %s, NOW())
        """,
        ("Aino", "Aalto")
    )

    clients = get_clients()

    assert len(clients) == 1
    assert clients[0]["first_name"] == "Hilma"


def test_get_clients_closes_connection_on_error(monkeypatch):
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
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.clients.select_clients",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_clients()

    assert connection.test_cursor.closed is True
    assert connection.closed is True



# UPDATE CLIENT TESTS


def test_update_client_rejects_invalid_id():
    with pytest.raises(ValueError):
        update_client("123", {"city": "Tampere"})


def test_update_client_rejects_zero_id():
    with pytest.raises(ValueError):
        update_client(0, {"city": "Tampere"})


def test_update_client_rejects_boolean_id():
    with pytest.raises(ValueError):
        update_client(True, {"city": "Tampere"})


def test_update_client_rejects_empty_changes():
    with pytest.raises(ValueError):
        update_client(1, {})


def test_update_client_rejects_invalid_field():
    with pytest.raises(ValueError):
        update_client(1, {"password_hash": "test"})


def test_update_client_rejects_empty_name():
    with pytest.raises(ValueError):
        update_client(1, {"first_name": "   "})


def test_update_client_rejects_invalid_distance():
    for distance in (-5, 4.567, "3.5", True, float("inf"), 100000000):
        with pytest.raises(ValueError):
            update_client(1, {"distance_from_home_km": distance})


def test_update_client_changes_city(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, city)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        ("Hilma", "Virtanen", "Tampere")
    )

    client_id = cursor.fetchone()[0]

    updated = update_client(
        client_id,
        {"city": "  Helsinki  "}
    )

    assert updated is True

    cursor.execute(
        """
        SELECT first_name, last_name, city
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone() == (
        "Hilma",
        "Virtanen",
        "Helsinki"
    )


def test_update_client_clears_phone(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, phone)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        ("Hilma", "Virtanen", "0401234567")
    )

    client_id = cursor.fetchone()[0]

    updated = update_client(
        client_id,
        {"phone": None}
    )

    assert updated is True

    cursor.execute(
        """
        SELECT phone
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_update_client_returns_false_if_not_found(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    updated = update_client(
        999999,
        {"city": "Tampere"}
    )

    assert updated is False


def test_update_client_rejects_archived_client(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (
            first_name,
            last_name,
            archived_at
        )
        VALUES (%s, %s, NOW())
        RETURNING id
        """,
        ("Hilma", "Virtanen")
    )

    client_id = cursor.fetchone()[0]

    updated = update_client(
        client_id,
        {"city": "Tampere"}
    )

    assert updated is False


def test_update_client_rolls_back_on_error(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def update_then_fail(cursor, client_id, changes):
        cursor.execute(
            """
            UPDATE clients
            SET city = %s
            WHERE id = %s
            """,
            ("Helsinki", client_id)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.clients.update_client_record",
        update_then_fail
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name, city)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        ("Hilma", "Virtanen", "Tampere")
    )

    client_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_client(client_id, {"city": "Helsinki"})

    cursor.execute(
        """
        SELECT city
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] == "Tampere"


# ARCHIVE CLIENT TESTS


def test_archive_client_rejects_invalid_id_type():
    with pytest.raises(ValueError):
        archive_client("123")


def test_archive_client_rejects_none_id():
    with pytest.raises(ValueError):
        archive_client(None)


def test_archive_client_rejects_boolean_id():
    with pytest.raises(ValueError):
        archive_client(True)


def test_archive_client_rejects_zero_id():
    with pytest.raises(ValueError):
        archive_client(0)


def test_archive_client_rejects_negative_id():
    with pytest.raises(ValueError):
        archive_client(-1)


def test_archive_client_sets_archived_at(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        ("Hilma", "Virtanen")
    )

    client_id = cursor.fetchone()[0]

    archived = archive_client(client_id)

    assert archived is True

    cursor.execute(
        """
        SELECT first_name, last_name, archived_at
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    result = cursor.fetchone()

    assert result[0] == "Hilma"
    assert result[1] == "Virtanen"
    assert result[2] is not None


def test_archive_client_returns_false_if_not_found(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    archived = archive_client(999999)

    assert archived is False


def test_archive_client_returns_false_if_already_archived(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        ("Hilma", "Virtanen")
    )

    client_id = cursor.fetchone()[0]

    first_result = archive_client(client_id)

    cursor.execute(
        """
        SELECT archived_at
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    original_time = cursor.fetchone()[0]

    second_result = archive_client(client_id)

    cursor.execute(
        """
        SELECT archived_at
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    final_time = cursor.fetchone()[0]

    assert first_result is True
    assert second_result is False
    assert final_time == original_time


def test_archive_client_rolls_back_on_error(
    postgres_cursor_with_clients,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_clients

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def archive_then_fail(cursor, client_id):
        cursor.execute(
            """
            UPDATE clients
            SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
            WHERE id = %s
            """,
            (client_id,)
        )

        raise RuntimeError("Simulated archive failure")

    monkeypatch.setattr(
        "carelog.services.clients.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.clients.archive_client_record",
        archive_then_fail
    )

    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        ("Hilma", "Virtanen")
    )

    client_id = cursor.fetchone()[0]

    with pytest.raises(
        RuntimeError,
        match="Simulated archive failure"
    ):
        archive_client(client_id)

    cursor.execute(
        """
        SELECT archived_at
        FROM clients
        WHERE id = %s
        """,
        (client_id,)
    )

    assert cursor.fetchone()[0] is None



def test_add_client_rejects_invalid_postal_code():
    with pytest.raises(
        ValueError,
        match="Postal code must contain only digits"
    ):
        add_client("Hilma", "Virtanen", postal_code="ABC")


def test_update_client_rejects_invalid_postal_code():
    with pytest.raises(
        ValueError,
        match="Postal code must contain only digits"
    ):
        update_client(1, {"postal_code": "ABC"})


def test_update_client_rejects_unicode_postal_code():
    with pytest.raises(
        ValueError,
        match="Postal code must contain only digits"
    ):
        update_client(1, {"postal_code": "１２３４５"})


def test_update_client_rejects_spaces_postal_code():
    with pytest.raises(
        ValueError,
        match="Postal code cannot be spaces"
    ):
        update_client(1, {"postal_code": "   "})
