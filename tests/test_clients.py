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


def test_add_client_rejects_over_lenght_first_name():
    test_name = "A" * 101
    with pytest.raises(ValueError):
        add_client(test_name, "Virtanen")


def test_add_client_rejects_over_lenght_last_name():
    test_name = "A" * 101
    with pytest.raises(ValueError):
        add_client("Arvo", test_name)


def test_add_client_rejets_invalid_type_first_name():
    with pytest.raises(ValueError):
        add_client(69, "Mauno")


def test_add_client_rejets_invalid_type_last_name():
    with pytest.raises(ValueError):
        add_client("Rauno", 88)



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
