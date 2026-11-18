from carelog.database.migrations import v008_rename_street_address
from tests.migration_helpers import get_columns, insert_client


def test_upgrade_preserves_existing_address(cursor_with_clients):
    cursor = cursor_with_clients
    client_id = insert_client(cursor)
    cursor.execute(
        "UPDATE clients SET street_adress = %s WHERE id = %s",
        ("Test Street 1", client_id),
    )

    v008_rename_street_address.upgrade(cursor)

    cursor.execute("SELECT street_address FROM clients WHERE id = %s", (client_id,))
    assert cursor.fetchone() == ("Test Street 1",)


def test_table_structure(cursor_with_clients):
    cursor = cursor_with_clients
    v008_rename_street_address.upgrade(cursor)

    columns = get_columns(cursor, "clients")
    assert ("street_address", "varchar(255)", "YES", None) in columns
    assert "street_adress" not in [column[0] for column in columns]


def test_upgrade_can_be_retried(cursor_with_clients):
    cursor = cursor_with_clients
    v008_rename_street_address.upgrade(cursor)

    v008_rename_street_address.upgrade(cursor)

    columns = get_columns(cursor, "clients")
    assert ("street_address", "varchar(255)", "YES", None) in columns
