def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            email VARCHAR(254) NOT NULL UNIQUE,
            display_name VARCHAR(150) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role ENUM('admin', 'worker')
                NOT NULL DEFAULT 'worker',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMP NOT NULL
                DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL
                DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB
    """)