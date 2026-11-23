from datetime import date, datetime

import psycopg
import pytest

from carelog.services.visit_notes import (
    add_visit_note,
    get_visit_notes,
    update_visit_note,
    validate_note_content,
)


# VALIDATE NOTE CONTENT TESTS


def test_validate_note_content_strips_edges_and_keeps_lines():
    assert validate_note_content(" Kaupassa käyty ") == "Kaupassa käyty"

    content = "\n  Käytiin kaupassa.\nHaettiin lääkkeet apteekista.  \n"

    assert validate_note_content(content) == (
        "Käytiin kaupassa.\nHaettiin lääkkeet apteekista."
    )

    # Exactly the size of a TEXT column is allowed
    assert validate_note_content("a" * 65535) == "a" * 65535


# ADD VISIT NOTE TESTS


def test_add_visit_note_rejects_invalid_visit_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            add_visit_note(visit_id, "Kaupassa käyty")


def test_add_visit_note_rejects_invalid_content():
    invalid_contents = (
        None,
        "",
        "   ",
        "\n\t",
        123,
        # 32 768 characters, but 65 536 bytes in UTF-8
        "ä" * 32768,
    )

    for content in invalid_contents:
        with pytest.raises(ValueError):
            add_visit_note(1, content)

    # The note itself must not appear in the error message
    with pytest.raises(ValueError) as error:
        add_visit_note(1, "Salainen tieto " * 5000)

    assert "Salainen" not in str(error.value)


def test_add_visit_note_saves_note(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Kauppa-asiointi",)
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23))
    )

    visit_id = cursor.fetchone()[0]

    note_id = add_visit_note(
        visit_id,
        "  Käytiin kaupassa.\nHaettiin lääkkeet apteekista.\n"
    )

    cursor.execute(
        "SELECT visit_id, content, created_at FROM visit_notes WHERE id = %s",
        (note_id,)
    )

    saved_visit_id, content, created_at = cursor.fetchone()

    # The edges are stripped and the line break inside is kept
    assert saved_visit_id == visit_id
    assert content == "Käytiin kaupassa.\nHaettiin lääkkeet apteekista."
    assert isinstance(created_at, datetime)


def test_add_visit_note_works_for_every_visit_status(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Ulkoilu",)
    )

    service_id = cursor.fetchone()[0]

    visit_ids = []

    for status in ("planned", "completed", "cancelled"):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, status, planned_week)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (client_id, service_id, status, date(2026, 11, 23))
        )

        visit_id = cursor.fetchone()[0]
        visit_ids.append(visit_id)

        add_visit_note(visit_id, "Ensimmäinen muistiinpano")

    # A visit can have many notes, for example the reason for cancelling
    add_visit_note(visit_ids[2], "Asiakas perui käynnin")

    cursor.execute(
        """
        SELECT visit_id, COUNT(*)
        FROM visit_notes
        GROUP BY visit_id
        ORDER BY visit_id
        """
    )

    assert cursor.fetchall() == [
        (visit_ids[0], 1),
        (visit_ids[1], 1),
        (visit_ids[2], 2),
    ]

    cursor.execute("SELECT status FROM visits ORDER BY id")

    # The visits themselves are not changed
    assert cursor.fetchall() == [("planned",), ("completed",), ("cancelled",)]


def test_add_visit_note_rejects_missing_visit(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    # The foreign key must reject a visit that does not exist
    with pytest.raises(psycopg.IntegrityError):
        add_visit_note(999999, "Kaupassa käyty")

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_add_visit_note_rolls_back_on_error(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(cursor, visit_id, content):
        cursor.execute(
            "INSERT INTO visit_notes (visit_id, content) VALUES (%s, %s)",
            (visit_id, content)
        )

        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visit_notes.insert_visit_note",
        insert_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Ulkoilu",)
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23))
    )

    visit_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_visit_note(visit_id, "Kaupassa käyty")

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_add_visit_note_closes_connection_on_error(monkeypatch):

    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False
            self.rolled_back = False

        def cursor(self):
            return self.test_cursor

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def insert_then_fail(cursor, visit_id, content):
        raise RuntimeError("Simulated insert failure")

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visit_notes.insert_visit_note",
        insert_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_visit_note(1, "Kaupassa käyty")

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET VISIT NOTES TESTS


def test_get_visit_notes_rejects_invalid_visit_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            get_visit_notes(visit_id)


def test_get_visit_notes_returns_empty_list(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Ulkoilu",)
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23))
    )

    visit_id = cursor.fetchone()[0]

    # A visit without notes, and a visit that does not exist
    assert get_visit_notes(visit_id) == []
    assert get_visit_notes(999999) == []


def test_get_visit_notes_returns_notes_oldest_first(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Kauppa-asiointi",)
    )

    service_id = cursor.fetchone()[0]

    visit_ids = []

    for week in (date(2026, 11, 16), date(2026, 11, 23)):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, planned_week)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (client_id, service_id, week)
        )

        visit_ids.append(cursor.fetchone()[0])

    visit_id = visit_ids[0]
    other_visit_id = visit_ids[1]

    # Inserted in mixed order. Two notes have the same created_at,
    # so their order comes from the id.
    note_rows = (
        (visit_id, "Kolmas", datetime(2026, 11, 18, 12, 0)),
        (visit_id, "Ensimmäinen", datetime(2026, 11, 18, 9, 0)),
        (visit_id, "Toinen", datetime(2026, 11, 18, 9, 0)),
        (other_visit_id, "Toisen käynnin muistiinpano", datetime(2026, 11, 18, 8, 0)),
    )

    for note_visit_id, content, created_at in note_rows:
        cursor.execute(
            """
            INSERT INTO visit_notes (visit_id, content, created_at)
            VALUES (%s, %s, %s)
            """,
            (note_visit_id, content, created_at)
        )

    # A note added through the service gets the current time, so it is last
    add_visit_note(visit_id, "Neljäs")

    notes = get_visit_notes(visit_id)

    contents = []

    for note in notes:
        contents.append(note["content"])

    # The other visit's note is not included
    assert contents == ["Ensimmäinen", "Toinen", "Kolmas", "Neljäs"]

    assert set(notes[0]) == {"id", "visit_id", "content", "created_at"}
    assert notes[0]["visit_id"] == visit_id
    assert notes[0]["created_at"] == datetime(2026, 11, 18, 9, 0)
    assert notes[0]["id"] < notes[1]["id"]


def test_get_visit_notes_returns_notes_of_cancelled_visit_of_archived_client(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Ulkoilu",)
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16))
    )

    visit_id = cursor.fetchone()[0]

    add_visit_note(visit_id, "Asiakas perui käynnin")

    # The client is archived later
    cursor.execute(
        "UPDATE clients SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = %s",
        (client_id,)
    )

    notes = get_visit_notes(visit_id)

    assert len(notes) == 1
    assert notes[0]["content"] == "Asiakas perui käynnin"


def test_get_visit_notes_closes_connection_on_error(monkeypatch):

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

    def select_then_fail(cursor, visit_id):
        raise RuntimeError("Simulated select failure")

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visit_notes.select_visit_notes",
        select_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated select failure"):
        get_visit_notes(1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# UPDATE VISIT NOTE TESTS


def test_update_visit_note_rejects_invalid_note_id():
    for note_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            update_visit_note(note_id, "Korjattu muistiinpano")


def test_update_visit_note_rejects_invalid_content():
    invalid_contents = (
        None,
        "",
        "  \n ",
        123,
        "ä" * 32768,
    )

    for content in invalid_contents:
        with pytest.raises(ValueError):
            update_visit_note(1, content)


def test_update_visit_note_changes_only_content(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Ulkoilu",)
    )

    service_id = cursor.fetchone()[0]

    # A cancelled visit of a client who is archived later
    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16))
    )

    visit_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visit_notes (visit_id, content, created_at)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (visit_id, "Asiakas peru käynnin", datetime(2026, 11, 18, 9, 0))
    )

    note_id = cursor.fetchone()[0]

    cursor.execute(
        "UPDATE clients SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = %s",
        (client_id,)
    )

    updated = update_visit_note(
        note_id,
        "  Asiakas perui käynnin.\nUusi aika sovitaan myöhemmin.  "
    )

    assert updated is True

    sql = "SELECT visit_id, content, created_at FROM visit_notes WHERE id = %s"

    cursor.execute(sql, (note_id,))

    # The edges are stripped, the line break is kept, and the note stays
    # with the same visit and creation time
    assert cursor.fetchone() == (
        visit_id,
        "Asiakas perui käynnin.\nUusi aika sovitaan myöhemmin.",
        datetime(2026, 11, 18, 9, 0),
    )

    # Saving the same content again is still a successful update
    assert update_visit_note(
        note_id,
        "Asiakas perui käynnin.\nUusi aika sovitaan myöhemmin."
    ) is True


def test_update_visit_note_returns_false_if_not_found(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    updated = update_visit_note(999999, "Korjattu muistiinpano")

    assert updated is False


def test_update_visit_note_rolls_back_on_error(
    postgres_cursor_with_visit_notes,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def update_then_fail(cursor, note_id, content):
        cursor.execute(
            "UPDATE visit_notes SET content = %s WHERE id = %s",
            (content, note_id)
        )

        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visit_notes.update_visit_note_record",
        update_then_fail
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name) VALUES (%s, %s) RETURNING id",
        ("Hilma", "Testi")
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name) VALUES (%s) RETURNING id",
        ("Ulkoilu",)
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week)
        VALUES (%s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23))
    )

    visit_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content) VALUES (%s, %s) RETURNING id",
        (visit_id, "Alkuperäinen")
    )

    note_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_visit_note(note_id, "Korjattu")

    cursor.execute("SELECT content FROM visit_notes WHERE id = %s", (note_id,))

    assert cursor.fetchone()[0] == "Alkuperäinen"


def test_update_visit_note_closes_connection_on_error(monkeypatch):

    class FakeCursor:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    class FakeConnection:
        def __init__(self):
            self.test_cursor = FakeCursor()
            self.closed = False
            self.rolled_back = False

        def cursor(self):
            return self.test_cursor

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    connection = FakeConnection()

    def get_test_connection():
        return connection

    def update_then_fail(cursor, note_id, content):
        raise RuntimeError("Simulated update failure")

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    monkeypatch.setattr(
        "carelog.services.visit_notes.update_visit_note_record",
        update_then_fail
    )

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_visit_note(1, "Korjattu")

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True
