def upgrade(cursor):
    cursor.execute("""
        CREATE TABLE expenses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            visit_id INT NULL,
            expense_date DATE NOT NULL,
            amount DECIMAL(10, 2) NOT NULL,
            category VARCHAR(20) NOT NULL,
            description VARCHAR(255) NULL,

            FOREIGN KEY (visit_id)
                REFERENCES visits(id)
        ) ENGINE=InnoDB
    """)
