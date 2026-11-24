from datetime import date, datetime

import pytest

from carelog.services.visit_notes import (
    add_visit_note,
    get_visit_note_history,
    get_visit_notes,
    update_visit_note,
    validate_note_content,
)
from tests.postgres_helpers import (
    fake_active_user,
    insert_visit,
    set_actor,
    start_in_thread,
    wait_until_waiting_for_lock,
)


@pytest.fixture(autouse=True)
def block_real_database(monkeypatch):

    # A test that does not replace the connection with the test database
    # must never reach the real database.

    def connection_not_allowed():
        raise RuntimeError("Unexpected database connection in a test")

    monkeypatch.setattr("carelog.services.visit_notes.get_postgres_connection", connection_not_allowed)


def fake_select_visit(cursor, visit_id, for_update=False, owner_user_id=None):
    return {"id": visit_id}


# VALIDATE NOTE CONTENT TESTS


def test_validate_note_content_strips_edges_and_keeps_lines():
    assert validate_note_content(" Kaupassa käyty ") == "Kaupassa käyty"

    content = "\n  Käytiin kaupassa.\nHaettiin lääkkeet apteekista.  \n"

    assert validate_note_content(content) == (
        "Käytiin kaupassa.\nHaettiin lääkkeet apteekista."
    )

    # Exactly CareLog's upper limit of 65535 bytes is allowed
    assert validate_note_content("a" * 65535) == "a" * 65535


# ADD VISIT NOTE TESTS


def test_add_visit_note_rejects_invalid_visit_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            add_visit_note(1, visit_id, "Kaupassa käyty")


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
            add_visit_note(1, 1, content)

    # The note itself must not appear in the error message
    with pytest.raises(ValueError) as error:
        add_visit_note(1, 1, "Salainen tieto " * 5000)

    assert "Salainen" not in str(error.value)


def test_add_visit_note_saves_note(
    postgres_cursor_with_visit_notes,
    user_ids,
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    note_id = add_visit_note(
        user_ids["worker"],
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
    user_ids,
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    visit_ids = []

    for status in ("planned", "completed", "cancelled"):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, status, planned_week, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (client_id, service_id, status, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
        )

        visit_id = cursor.fetchone()[0]
        visit_ids.append(visit_id)

        add_visit_note(user_ids["worker"], visit_id, "Ensimmäinen muistiinpano")

    # A visit can have many notes, for example the reason for cancelling
    add_visit_note(user_ids["worker"], visit_ids[2], "Asiakas perui käynnin")

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
    user_ids,
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

    # A visit that does not exist is rejected before the insert
    with pytest.raises(ValueError, match="Visit not found"):
        add_visit_note(user_ids["worker"], 999999, "Kaupassa käyty")

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_add_visit_note_rolls_back_on_error(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def insert_then_fail(cursor, created_by_user_id, visit_id, content):
        cursor.execute(
            "INSERT INTO visit_notes (visit_id, content, created_by_user_id) VALUES (%s, %s, %s)",
            (visit_id, content, created_by_user_id)
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated insert failure"):
        add_visit_note(user_ids["worker"], visit_id, "Kaupassa käyty")

    cursor.execute("SELECT COUNT(*) FROM visit_notes")

    assert cursor.fetchone()[0] == 0


def test_add_visit_note_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run SQL, so the checks are replaced
    monkeypatch.setattr("carelog.services.visit_notes.get_active_user", fake_active_user)
    monkeypatch.setattr("carelog.services.visit_notes.select_visit", fake_select_visit)


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

    def insert_then_fail(cursor, created_by_user_id, visit_id, content):
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
        add_visit_note(1, 1, "Kaupassa käyty")

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# GET VISIT NOTES TESTS


def test_get_visit_notes_rejects_invalid_visit_id():
    for visit_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            get_visit_notes(1, visit_id)


def test_get_visit_notes_returns_empty_list(
    postgres_cursor_with_visit_notes,
    user_ids,
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    # A visit without notes, and a visit that does not exist
    assert get_visit_notes(user_ids["worker"], visit_id) == []
    assert get_visit_notes(user_ids["worker"], 999999) == []


def test_get_visit_notes_returns_notes_oldest_first(
    postgres_cursor_with_visit_notes,
    user_ids,
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Kauppa-asiointi", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    visit_ids = []

    for week in (date(2026, 11, 16), date(2026, 11, 23)):
        cursor.execute(
            """
            INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (client_id, service_id, week, user_ids["worker"], user_ids["worker"])
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
            INSERT INTO visit_notes (visit_id, content, created_at, created_by_user_id)
            VALUES (%s, %s, %s, %s)
            """,
            (note_visit_id, content, created_at, user_ids["worker"])
        )

    # A note added through the service gets the current time, so it is last
    add_visit_note(user_ids["worker"], visit_id, "Neljäs")

    notes = get_visit_notes(user_ids["worker"], visit_id)

    contents = []

    for note in notes:
        contents.append(note["content"])

    # The other visit's note is not included
    assert contents == ["Ensimmäinen", "Toinen", "Kolmas", "Neljäs"]

    assert set(notes[0]) == {
        "id",
        "visit_id",
        "content",
        "created_at",
        "updated_at",
        "created_by_user_id",
        "updated_by_user_id",
    }
    assert notes[0]["visit_id"] == visit_id

    # The creator of each note is saved, also for a note added through
    # the service. A note that was never edited has no editor yet.
    assert notes[0]["created_by_user_id"] == user_ids["worker"]
    assert notes[3]["created_by_user_id"] == user_ids["worker"]
    assert notes[0]["updated_by_user_id"] is None
    assert notes[0]["created_at"] == datetime(2026, 11, 18, 9, 0)
    assert notes[0]["id"] < notes[1]["id"]


def test_get_visit_notes_returns_notes_of_cancelled_visit_of_archived_client(
    postgres_cursor_with_visit_notes,
    user_ids,
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    add_visit_note(user_ids["worker"], visit_id, "Asiakas perui käynnin")

    # The client is archived later
    cursor.execute(
        "UPDATE clients SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = %s",
        (client_id,)
    )

    notes = get_visit_notes(user_ids["worker"], visit_id)

    assert len(notes) == 1
    assert notes[0]["content"] == "Asiakas perui käynnin"


def test_get_visit_notes_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run SQL, so the checks are replaced
    monkeypatch.setattr("carelog.services.visit_notes.get_active_user", fake_active_user)
    monkeypatch.setattr("carelog.services.visit_notes.select_visit", fake_select_visit)


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

    def select_then_fail(cursor, visit_id, owner_user_id=None):
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
        get_visit_notes(1, 1)

    assert connection.test_cursor.closed is True
    assert connection.closed is True


# UPDATE VISIT NOTE TESTS


def test_update_visit_note_rejects_invalid_note_id():
    for note_id in ("1", None, True, 0, -1):
        with pytest.raises(ValueError):
            update_visit_note(1, note_id, "Korjattu muistiinpano")


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
            update_visit_note(1, 1, content)


def test_update_visit_note_changes_only_content(
    postgres_cursor_with_visit_notes,
    user_ids,
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    # A cancelled visit of a client who is archived later
    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, status, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, "cancelled", date(2026, 11, 16), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visit_notes (visit_id, content, created_at, created_by_user_id)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (visit_id, "Asiakas peru käynnin", datetime(2026, 11, 18, 9, 0), user_ids["worker"])
    )

    note_id = cursor.fetchone()[0]

    cursor.execute(
        "UPDATE clients SET archived_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = %s",
        (client_id,)
    )

    updated = update_visit_note(
        user_ids["worker"],
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
        user_ids["worker"],
        note_id,
        "Asiakas perui käynnin.\nUusi aika sovitaan myöhemmin."
    ) is True


def test_update_visit_note_returns_false_if_not_found(
    postgres_cursor_with_visit_notes,
    user_ids,
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

    updated = update_visit_note(user_ids["worker"], 999999, "Korjattu muistiinpano")

    assert updated is False


def test_update_visit_note_rolls_back_on_error(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    def update_then_fail(cursor, updated_by_user_id, note_id, content, owner_user_id=None):
        set_actor(cursor, updated_by_user_id)
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
        "INSERT INTO clients (first_name, last_name, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        ("Hilma", "Testi", user_ids["worker"])
    )

    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES (%s, %s) RETURNING id",
        ("Ulkoilu", user_ids["worker"])
    )

    service_id = cursor.fetchone()[0]

    cursor.execute(
        """
        INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (client_id, service_id, date(2026, 11, 23), user_ids["worker"], user_ids["worker"])
    )

    visit_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO visit_notes (visit_id, content, created_by_user_id) VALUES (%s, %s, %s) RETURNING id",
        (visit_id, "Alkuperäinen", user_ids["worker"])
    )

    note_id = cursor.fetchone()[0]

    with pytest.raises(RuntimeError, match="Simulated update failure"):
        update_visit_note(user_ids["worker"], note_id, "Korjattu")

    cursor.execute(
        "SELECT content, updated_by_user_id FROM visit_notes WHERE id = %s",
        (note_id,)
    )

    assert cursor.fetchone() == ("Alkuperäinen", None)

    # The history row of the trigger was rolled back with the change
    cursor.execute("SELECT COUNT(*) FROM visit_note_history")

    assert cursor.fetchone()[0] == 0


def test_update_visit_note_closes_connection_on_error(monkeypatch):
    # The fake cursor cannot run SQL, so the checks are replaced
    monkeypatch.setattr("carelog.services.visit_notes.get_active_user", fake_active_user)
    monkeypatch.setattr("carelog.services.visit_notes.select_visit", fake_select_visit)


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

    def update_then_fail(cursor, updated_by_user_id, note_id, content, owner_user_id=None):
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
        update_visit_note(1, 1, "Korjattu")

    assert connection.rolled_back is True
    assert connection.test_cursor.closed is True
    assert connection.closed is True


# NOTE HISTORY TESTS
# The trigger trg_visit_notes_history saves the old and the new content
# whenever the content of a note changes.


@pytest.fixture
def history_database(
    postgres_cursor_with_visit_notes,
    user_ids,
    connect_to_test_postgres,
    monkeypatch
):
    cursor = postgres_cursor_with_visit_notes

    cursor.execute("SELECT current_database()")
    database = cursor.fetchone()[0]

    # Only a temporary test database is ever used
    assert database.startswith("carelog_test_")

    def get_test_connection():
        return connect_to_test_postgres(database=database)

    monkeypatch.setattr(
        "carelog.services.visit_notes.get_postgres_connection",
        get_test_connection
    )

    cursor.execute(
        "INSERT INTO clients (first_name, last_name, created_by_user_id) "
        "VALUES ('Hilma', 'Testi', %s) RETURNING id",
        (user_ids["admin"],)
    )
    client_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO services (name, created_by_user_id) VALUES ('Ulkoilu', %s) RETURNING id",
        (user_ids["admin"],)
    )
    service_id = cursor.fetchone()[0]

    cursor.execute(
        "INSERT INTO visits (client_id, service_id, planned_week, user_id, created_by_user_id) "
        "VALUES (%s, %s, '2026-11-16', %s, %s) RETURNING id",
        (client_id, service_id, user_ids["worker"], user_ids["worker"])
    )
    visit_id = cursor.fetchone()[0]

    note_id = add_visit_note(user_ids["worker"], visit_id, "Alkuperäinen")

    # The note was written last week. The content stays the same, so the
    # trigger writes no history row for this UPDATE.
    cursor.execute(
        "UPDATE visit_notes SET created_at = '2026-11-18 09:00', "
        "updated_at = '2026-11-18 09:00' WHERE id = %s",
        (note_id,)
    )

    return cursor, visit_id, note_id, get_test_connection


def get_note_times(cursor, note_id):
    cursor.execute("SELECT created_at, updated_at FROM visit_notes WHERE id = %s", (note_id,))
    return cursor.fetchone()


def get_history_contents(actor_user_id, note_id):
    contents = []

    for change in get_visit_note_history(actor_user_id, note_id):
        contents.append((change["old_content"], change["new_content"]))

    return contents


def test_get_visit_note_history_rejects_invalid_note_id():
    for note_id in ("1", None, True, 0, -1, 1.0):
        with pytest.raises(ValueError):
            get_visit_note_history(1, note_id)


def test_new_note_has_no_history(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database

    assert get_visit_note_history(user_ids["worker"], note_id) == []

    # A note that does not exist has no history either
    assert get_visit_note_history(user_ids["worker"], 999999) == []

    cursor.execute("SELECT COUNT(*) FROM visit_note_history")
    assert cursor.fetchone()[0] == 0


def test_edits_are_saved_to_history_oldest_first(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database

    # An edit of another note is not part of this note's history
    other_note_id = add_visit_note(user_ids["worker"], visit_id, "Toinen muistiinpano")
    assert update_visit_note(user_ids["worker"], other_note_id, "Toinen muistiinpano korjattu") is True

    assert update_visit_note(user_ids["worker"], note_id, "Ensimmäinen korjaus") is True
    assert update_visit_note(user_ids["worker"], note_id, "Toinen korjaus") is True

    assert get_history_contents(user_ids["worker"], note_id) == [
        ("Alkuperäinen", "Ensimmäinen korjaus"),
        ("Ensimmäinen korjaus", "Toinen korjaus"),
    ]

    history = get_visit_note_history(user_ids["worker"], note_id)

    assert set(history[0]) == {
        "id", "note_id", "old_content", "new_content", "edited_at", "edited_by_user_id"
    }
    assert history[0]["id"] < history[1]["id"]
    assert history[0]["note_id"] == note_id

    # The editor that the service gave is saved for each change
    assert history[0]["edited_by_user_id"] == user_ids["worker"]
    assert history[1]["edited_by_user_id"] == user_ids["worker"]

    # created_at is kept. updated_at is the time of the last edit.
    created_at, updated_at = get_note_times(cursor, note_id)

    assert created_at == datetime(2026, 11, 18, 9, 0)
    assert updated_at > created_at
    assert updated_at == history[1]["edited_at"]

    notes = get_visit_notes(user_ids["worker"], visit_id)

    assert notes[0]["content"] == "Toinen korjaus"
    assert notes[0]["updated_at"] == updated_at


def test_same_content_saves_no_history(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database

    # The service strips the edges, so the text is the same as before
    assert update_visit_note(user_ids["worker"], note_id, "  Alkuperäinen  ") is True

    assert get_visit_note_history(user_ids["worker"], note_id) == []

    # Nothing changed, so updated_at is not changed either
    assert get_note_times(cursor, note_id) == (
        datetime(2026, 11, 18, 9, 0),
        datetime(2026, 11, 18, 9, 0),
    )


def test_direct_sql_update_saves_history(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database

    # The trigger works for every UPDATE, not only for the service. The
    # editor is given in the same transaction, as the service does.
    with cursor.connection.transaction():
        set_actor(cursor, user_ids["admin"])
        cursor.execute(
            "UPDATE visit_notes SET content = 'Korjattu suoraan' WHERE id = %s",
            (note_id,)
        )

    assert get_history_contents(user_ids["worker"], note_id) == [("Alkuperäinen", "Korjattu suoraan")]

    history = get_visit_note_history(user_ids["admin"], note_id)
    assert history[0]["edited_by_user_id"] == user_ids["admin"]


def test_concurrent_edits_are_saved_one_at_a_time(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database

    # The other connection edits the note but does not commit yet, so it
    # keeps the note row locked.
    other_connection = get_test_connection()

    try:
        other_connection.execute(
            "SELECT set_config('carelog.actor_user_id', %s, true)",
            (str(user_ids["admin"]),)
        )
        other_connection.execute(
            "UPDATE visit_notes SET content = 'Ensimmäinen korjaus' WHERE id = %s",
            (note_id,)
        )

        thread, done, outcome = start_in_thread(update_visit_note, user_ids["worker"], note_id, "Toinen korjaus")

        wait_until_waiting_for_lock(cursor)
        assert not done.is_set()

        other_connection.commit()

        assert done.wait(timeout=10)
        thread.join(timeout=10)

    finally:
        # Releases the lock also when the test fails
        other_connection.close()

    assert outcome == {"result": True}

    # The second edit starts from the text of the first one, so no edit
    # is lost from the history.
    assert get_history_contents(user_ids["worker"], note_id) == [
        ("Alkuperäinen", "Ensimmäinen korjaus"),
        ("Ensimmäinen korjaus", "Toinen korjaus"),
    ]

    cursor.execute("SELECT content FROM visit_notes WHERE id = %s", (note_id,))
    assert cursor.fetchone()[0] == "Toinen korjaus"


# OWNERSHIP TESTS
# Access to a note follows the worker of its visit (visits.user_id), not
# the creator of the note. history_database gives a visit of the worker
# and a note written by the worker.


def test_note_functions_reject_invalid_actor_id():
    # The user check itself is tested in test_user_validation.py
    for actor_user_id in (None, True, "1", 0):
        with pytest.raises(ValueError):
            add_visit_note(actor_user_id, 1, "Kaupassa käyty")

        with pytest.raises(ValueError):
            get_visit_notes(actor_user_id, 1)

        with pytest.raises(ValueError):
            get_visit_note_history(actor_user_id, 1)

        with pytest.raises(ValueError):
            update_visit_note(actor_user_id, 1, "Korjattu")


def test_note_access_follows_the_worker_of_the_visit(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database
    worker_id = user_ids["worker"]
    other_worker_id = user_ids["other_worker"]
    admin_id = user_ids["admin"]

    other_visit_id = insert_visit(cursor, other_worker_id)

    # A worker cannot add a note to another worker's visit. The error is
    # the same as for a missing visit.
    with pytest.raises(ValueError, match="Visit not found"):
        add_visit_note(worker_id, other_visit_id, "Väärä käynti")

    # An admin can, and is the creator
    other_note_id = add_visit_note(admin_id, other_visit_id, "Adminin muistiinpano")

    cursor.execute(
        "SELECT created_by_user_id, updated_by_user_id FROM visit_notes WHERE id = %s",
        (other_note_id,)
    )
    assert cursor.fetchone() == (admin_id, None)

    # The worker of the visit may edit the admin's note: the creator is
    # not the owner
    assert update_visit_note(other_worker_id, other_note_id, "Korjattu") is True

    # Another worker gets nothing: no notes, no history and no edit
    assert get_visit_notes(worker_id, other_visit_id) == []
    assert get_visit_note_history(worker_id, other_note_id) == []
    assert update_visit_note(worker_id, other_note_id, "Väärä korjaus") is False

    # The admin and the worker of the visit see the note and its history
    notes = get_visit_notes(admin_id, other_visit_id)
    assert len(notes) == 1
    assert notes[0]["content"] == "Korjattu"
    assert notes[0]["created_by_user_id"] == admin_id
    assert notes[0]["updated_by_user_id"] == other_worker_id

    history = get_visit_note_history(other_worker_id, other_note_id)
    assert len(history) == 1
    assert history[0]["edited_by_user_id"] == other_worker_id

    # The other worker cannot see the first worker's notes either
    assert get_visit_notes(other_worker_id, visit_id) == []

    cursor.execute("SELECT COUNT(*) FROM visit_notes")
    assert cursor.fetchone()[0] == 2


def test_history_saves_the_editor_of_each_change(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database
    worker_id = user_ids["worker"]
    admin_id = user_ids["admin"]

    # The same user twice in a row, then another user, then the first
    # user again. Every change gives its own editor.
    edits = [
        (worker_id, "Ensimmäinen"),
        (worker_id, "Toinen"),
        (admin_id, "Kolmas"),
        (worker_id, "Neljäs"),
    ]

    for editor_id, content in edits:
        assert update_visit_note(editor_id, note_id, content) is True

    editors = []

    for change in get_visit_note_history(admin_id, note_id):
        editors.append(change["edited_by_user_id"])

    assert editors == [worker_id, worker_id, admin_id, worker_id]

    cursor.execute(
        "SELECT created_by_user_id, updated_by_user_id FROM visit_notes WHERE id = %s",
        (note_id,)
    )
    assert cursor.fetchone() == (worker_id, worker_id)


def test_note_edit_waits_for_worker_change(history_database, user_ids):
    cursor, visit_id, note_id, get_test_connection = history_database

    # The other connection gives the visit to another worker but does not
    # commit yet, so it keeps the visit row locked.
    other_connection = get_test_connection()

    try:
        other_connection.execute(
            "UPDATE visits SET user_id = %s WHERE id = %s",
            (user_ids["other_worker"], visit_id)
        )

        thread, done, outcome = start_in_thread(
            update_visit_note, user_ids["worker"], note_id, "Korjattu"
        )

        wait_until_waiting_for_lock(cursor)
        assert not done.is_set()

        other_connection.commit()

        assert done.wait(timeout=10)
        thread.join(timeout=10)

    finally:
        other_connection.close()

    # The visit is no longer the worker's, so the note is not changed
    assert outcome == {"result": False}

    cursor.execute("SELECT content FROM visit_notes WHERE id = %s", (note_id,))
    assert cursor.fetchone()[0] == "Alkuperäinen"

    cursor.execute("SELECT COUNT(*) FROM visit_note_history")
    assert cursor.fetchone()[0] == 0
