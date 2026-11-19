def insert_client(cursor, first_name, last_name):
    cursor.execute(
        """
        INSERT INTO clients (first_name, last_name)
        VALUES (%s, %s)
        """,
        (first_name, last_name)
    )

    return cursor.lastrowid
