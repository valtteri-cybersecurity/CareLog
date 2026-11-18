def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE trips (
            id INT AUTO_INCREMENT PRIMARY KEY,
            client_id INT NOT NULL,
            start_location VARCHAR(255) NOT NULL,
            destination VARCHAR(255) NOT NULL,
            distance_km DECIMAL(10, 2) NULL,

            FOREIGN KEY (client_id)
                REFERENCES clients(id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB
    """)
