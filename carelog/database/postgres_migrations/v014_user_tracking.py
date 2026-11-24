# Every table that gets a NOT NULL user column in this migration. A row
# that already exists in one of them has no known creator or worker, so
# the migration cannot fill in the new column safely.
TABLES_WITH_REQUIRED_USER = (
    "clients",
    "services",
    "trips",
    "visits",
    "visit_notes",
    "expenses",
    "visit_trip_legs",
    "visit_note_history",
)

# Tables whose created_by_user_id cannot be changed after the row has
# been created. Each one gets the trigger trg_<table>_created_by.
CREATED_BY_TABLES = (
    "clients",
    "services",
    "trips",
    "visits",
    "visit_notes",
    "expenses",
    "visit_trip_legs",
)

# Tables that get updated_at in this migration. Each one gets the
# trigger trg_<table>_updated_at, like users, clients and visits.
NEW_UPDATED_AT_TABLES = ("services", "trips", "expenses")


def check_no_existing_rows(cursor):
    # The tables are locked first, so no other connection can add a row
    # between this check and the changes below. The locks are released
    # when the migration transaction ends.
    #
    # The table names are fixed values from the list above.
    cursor.execute(
        "LOCK TABLE "
        + ", ".join(TABLES_WITH_REQUIRED_USER)
        + " IN ACCESS EXCLUSIVE MODE"
    )

    tables_with_rows = []

    for table in TABLES_WITH_REQUIRED_USER:
        cursor.execute(f"SELECT EXISTS (SELECT 1 FROM {table})")

        if cursor.fetchone()[0]:
            tables_with_rows.append(table)

    # Old rows are never deleted, linked to an invented user or to the
    # user with id 1. The administrator decides what to do with them.
    if tables_with_rows:
        raise RuntimeError(
            "Migration 14 was not applied: these tables contain records "
            "whose creator is unknown: "
            + ", ".join(tables_with_rows)
            + ". Remove the development data by hand or create a new, "
            "empty database, and run the installation again."
        )


def upgrade(cursor):
    # 1. Stop before any change if old rows exist. The migration runner
    #    rolls back the whole migration when an error is raised.
    check_no_existing_rows(cursor)

    # 2. A trigger function that keeps created_by_user_id unchanged.
    #    IS DISTINCT FROM also works with NULL values. An UPDATE that
    #    keeps the same value is allowed, so a normal update of other
    #    columns is never blocked. The function only reads the row, so it
    #    runs with the rights of the caller, like set_updated_at().
    cursor.execute("""
        CREATE FUNCTION prevent_created_by_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id THEN
                RAISE EXCEPTION 'created_by_user_id cannot be changed'
                    USING ERRCODE = 'restrict_violation';
            END IF;

            RETURN NEW;
        END;
        $$
    """)

    # 3. The user columns. users.id is INT, so the references are INT.
    #    user_id         = the worker the visit or expense belongs to
    #    created_by_user_id = the user who created the row
    #    updated_by_user_id = the user who changed the row last; NULL
    #                         until the first change
    #    ON DELETE RESTRICT: a user with records cannot be deleted. Users
    #    are deactivated with is_active instead.
    #
    #    The columns are added to empty tables (checked above), so NOT
    #    NULL needs no default value.
    cursor.execute("""
        ALTER TABLE clients
            ADD COLUMN created_by_user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_by_user_id INT NULL
                REFERENCES users(id) ON DELETE RESTRICT
    """)

    # services and trips also get updated_at, with the same UTC default
    # as the other tables.
    cursor.execute("""
        ALTER TABLE services
            ADD COLUMN created_by_user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_by_user_id INT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_at TIMESTAMP NOT NULL
                DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
    """)

    cursor.execute("""
        ALTER TABLE trips
            ADD COLUMN created_by_user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_by_user_id INT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_at TIMESTAMP NOT NULL
                DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
    """)

    # A planned visit always has a worker, so user_id is NOT NULL for
    # every visit.
    cursor.execute("""
        ALTER TABLE visits
            ADD COLUMN user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN created_by_user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_by_user_id INT NULL
                REFERENCES users(id) ON DELETE RESTRICT
    """)

    # updated_by_user_id of a note is set by the history trigger below,
    # never directly.
    cursor.execute("""
        ALTER TABLE visit_notes
            ADD COLUMN created_by_user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_by_user_id INT NULL
                REFERENCES users(id) ON DELETE RESTRICT
    """)

    cursor.execute("""
        ALTER TABLE expenses
            ADD COLUMN user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN created_by_user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_by_user_id INT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            ADD COLUMN updated_at TIMESTAMP NOT NULL
                DEFAULT (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')
    """)

    # Trip legs are never updated: a new list replaces the old legs, so
    # created_by_user_id tells who saved the current legs.
    cursor.execute("""
        ALTER TABLE visit_trip_legs
            ADD COLUMN created_by_user_id INT NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT
    """)

    # The existing column of v013 keeps its name. From now on every
    # history row must tell who made the change.
    cursor.execute("""
        ALTER TABLE visit_note_history
            ALTER COLUMN edited_by_user_id SET NOT NULL
    """)

    # 4. Indexes for the columns used in searches: the visits, kilometres
    #    and expenses of one worker. The other user columns are not used
    #    in searches, and users are never deleted, so they get no index.
    cursor.execute("CREATE INDEX idx_visits_user_id ON visits (user_id)")
    cursor.execute("CREATE INDEX idx_expenses_user_id ON expenses (user_id)")

    # 5. updated_at triggers. set_updated_at() is created in v001_users.
    #    The table names are fixed values from the list above.
    for table in NEW_UPDATED_AT_TABLES:
        cursor.execute(
            f"CREATE TRIGGER trg_{table}_updated_at "
            f"BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )

    # 6. created_by_user_id triggers. The table names are fixed values
    #    from the list above.
    for table in CREATED_BY_TABLES:
        cursor.execute(
            f"CREATE TRIGGER trg_{table}_created_by "
            f"BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION prevent_created_by_change()"
        )

    # 7. The note history function of v013 now saves the editor.
    #
    #    Who is the editor? The application connects with one shared
    #    database account, so the database cannot know the person. The
    #    application gives the editor explicitly before every UPDATE of a
    #    note's content, in the same transaction:
    #
    #        SELECT set_config('carelog.actor_user_id', '5', true);
    #        UPDATE visit_notes SET content = ... WHERE id = ...;
    #
    #    true means that the value disappears when the transaction ends.
    #    The function also clears the value after using it, so every
    #    change of content needs its own set_config(). An UPDATE without
    #    an editor fails, so the editor of an earlier change is never
    #    used by mistake. The same user can still make many changes in a
    #    row: each one gives the editor again.
    #
    #    This only records the editor that the application gives. It does
    #    not prove who the person is; authentication is done by the
    #    application later.
    #
    #    updated_by_user_id of the note changes only together with the
    #    content, so the latest editor cannot be changed alone.
    #
    #    CREATE OR REPLACE keeps the owner and the privileges of the
    #    function (REVOKE ... FROM PUBLIC of v013). SECURITY DEFINER and
    #    the fixed search_path are written again, as in v013, because
    #    CREATE OR REPLACE replaces all function settings.
    cursor.execute("""
        CREATE OR REPLACE FUNCTION public.save_visit_note_history()
        RETURNS trigger
        LANGUAGE plpgsql
        SECURITY DEFINER
        SET search_path = pg_catalog, pg_temp
        AS $$
        DECLARE
            actor_user_id INT;
        BEGIN
            IF NEW.content IS DISTINCT FROM OLD.content THEN
                actor_user_id := NULLIF(
                    current_setting('carelog.actor_user_id', true),
                    ''
                )::INT;

                IF actor_user_id IS NULL THEN
                    RAISE EXCEPTION
                        'The editor of a visit note must be given in carelog.actor_user_id'
                        USING ERRCODE = 'not_null_violation';
                END IF;

                -- Used once: the next change needs the editor again
                PERFORM set_config('carelog.actor_user_id', '', true);

                NEW.updated_at := CURRENT_TIMESTAMP AT TIME ZONE 'UTC';
                NEW.updated_by_user_id := actor_user_id;

                INSERT INTO public.visit_note_history
                    (note_id, old_content, new_content, edited_at, edited_by_user_id)
                VALUES
                    (OLD.id, OLD.content, NEW.content, NEW.updated_at, actor_user_id);
            ELSE
                -- Without a change of content the latest editor stays
                NEW.updated_by_user_id := OLD.updated_by_user_id;
            END IF;

            RETURN NEW;
        END;
        $$
    """)
