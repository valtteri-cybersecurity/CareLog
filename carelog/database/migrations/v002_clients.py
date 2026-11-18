def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE clients (
            id INT AUTO_INCREMENT PRIMARY KEY,
            first_name VARCHAR(100) NOT NULL,
            last_name VARCHAR(100) NOT NULL,
            phone VARCHAR(50) NULL,
            email VARCHAR(255) NULL,
            street_address VARCHAR(255) NULL,
            postal_code VARCHAR(20) NULL,
            city VARCHAR(100) NULL,
            distance_from_home_km DECIMAL(10, 2) NULL,
            archived_at DATETIME NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    """)
