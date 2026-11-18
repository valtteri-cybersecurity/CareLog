def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE visit_notes (
            id INT AUTO_INCREMENT PRIMARY KEY,
            visit_id INT NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (visit_id)
                REFERENCES visits(id)
        ) ENGINE=InnoDB
        """)