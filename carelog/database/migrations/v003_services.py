def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE services (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(150) NOT NULL,
            description TEXT NULL,
            default_hourly_rate DECIMAL(10, 2) NULL
        ) ENGINE=InnoDB
    """)
