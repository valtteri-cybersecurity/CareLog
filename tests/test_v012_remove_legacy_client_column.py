from carelog.database.migrations import v012_remove_legacy_client_column
from tests.migration_helpers import get_columns, insert_client


def test_upgrade_leaves_fresh_clients_table_unchanged(cursor_with_clients):
    cursor = cursor_with_clients
    columns = get_columns(cursor, "clients")

    v012_remove_legacy_client_column.upgrade(cursor)

    assert get_columns(cursor, "clients") == columns


def test_upgrade_removes_only_the_legacy_column(cursor_with_clients):
    cursor = cursor_with_clients
    columns = get_columns(cursor, "clients")
    cursor.execute("ALTER TABLE clients ADD COLUMN personal_identity_code VARCHAR(11) NULL")
    client_id = insert_client(cursor)
    cursor.execute(
        "UPDATE clients SET personal_identity_code = %s WHERE id = %s",
        ("test-value", client_id),
    )

    v012_remove_legacy_client_column.upgrade(cursor)

    assert get_columns(cursor, "clients") == columns
    cursor.execute("SELECT first_name, last_name FROM clients WHERE id = %s", (client_id,))
    assert cursor.fetchone() == ("Test", "Client")


def test_upgrade_can_be_retried(cursor_with_clients):
    cursor = cursor_with_clients
    columns = get_columns(cursor, "clients")
    cursor.execute("ALTER TABLE clients ADD COLUMN personal_identity_code VARCHAR(11) NULL")
    v012_remove_legacy_client_column.upgrade(cursor)

    v012_remove_legacy_client_column.upgrade(cursor)

    assert get_columns(cursor, "clients") == columns
