import pytest

from carelog.services.clients import add_client


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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

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
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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


def test_add_client_rejects_zero_distance():
    with pytest.raises(ValueError):
        add_client("Hilma", "Virtanen", distance_from_home_km=0.0)


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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT street_address FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_street_address_as_null(
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", postal_code=" 00100 ")

    cursor.execute(
        "SELECT postal_code FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] == "00100"


def test_add_client_saves_null_postal_code(
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT postal_code FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_postal_code_as_null(
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen", city=" Tampere ")

    cursor.execute(
        "SELECT city FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] == "Tampere"


def test_add_client_saves_null_city(
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT city FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None


def test_add_client_saves_empty_city_as_null(
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
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


def test_add_client_saves_null_distance(
    cursor_with_clients,
    connect_to_test_mysql,
    monkeypatch
):
    cursor = cursor_with_clients

    cursor.execute("SELECT DATABASE()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_mysql(database=database)

    monkeypatch.setattr(
        "carelog.services.clients.get_connection",
        get_test_connection
    )

    client_id = add_client("Hilma", "Virtanen")

    cursor.execute(
        "SELECT distance_from_home_km FROM clients WHERE id = %s",
        (client_id,)
    )

    assert cursor.fetchone()[0] is None

