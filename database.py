import sqlite3

DATABASE = "dbsystem.db"

def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn

def create_tables():
    with get_db_connection() as conn:

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                date_of_birth TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                address TEXT NOT NULL,
                password TEXT NOT NULL,
                user_status TEXT DEFAULT 'pending',
                role TEXT CHECK(role IN ('student','warden','admin')) NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Students (
                student_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                programme TEXT NOT NULL,
                year_of_study TEXT NOT NULL,
                gender TEXT NOT NULL,
                emergency_contact TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Admin (
                admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Warden (
                warden_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                FOREIGN KEY (user_id) REFERENCES Users(user_id) ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Announcements (
                announcement_id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                details TEXT NOT NULL,
                date TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES Users(user_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Notifications (
                notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                student_id INTEGER NOT NULL,
                category TEXT NOT NULL DEFAULT 'info',
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (student_id) REFERENCES Students(student_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Rooms (
                room_id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_number TEXT NOT NULL,
                bed_capacity INTEGER NOT NULL,
                available_beds INTEGER NOT NULL,
                price_per_month REAL NOT NULL,
                room_details TEXT NOT NULL,
                gender TEXT,
                room_type TEXT NOT NULL,
                room_status TEXT DEFAULT 'Available'
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Bookings (
                booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                admin_id INTEGER,
                student_name TEXT NOT NULL,
                rent_per_month REAL NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                total_payment REAL NOT NULL,
                booking_status TEXT,
                payment_status TEXT,
                receipt_url TEXT,
                FOREIGN KEY (room_id) REFERENCES Rooms(room_id) ON DELETE RESTRICT,
                FOREIGN KEY (student_id) REFERENCES Students(student_id),
                FOREIGN KEY (admin_id) REFERENCES Admin(admin_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Fine (
                fine_id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount REAL NOT NULL,
                reason TEXT NOT NULL,
                fine_status TEXT DEFAULT 'pending',
                fine_type TEXT NOT NULL,
                issued_date TEXT NOT NULL,
                student_id INTEGER NOT NULL,
                FOREIGN KEY (student_id) REFERENCES Students(student_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS Payment (
                payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_method TEXT NOT NULL,
                outstanding REAL,
                payment_date TEXT NOT NULL,
                amount REAL NOT NULL,
                card_holder_name TEXT,
                card_number TEXT,
                payment_status TEXT NOT NULL,
                booking_id INTEGER,
                fine_id INTEGER,
                FOREIGN KEY (booking_id) REFERENCES Bookings(booking_id),
                FOREIGN KEY (fine_id) REFERENCES Fine(fine_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS MaintenanceRequests (
                request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                room_id INTEGER NOT NULL,
                description TEXT,
                category TEXT,
                priority TEXT,
                maintenance_status TEXT DEFAULT 'pending',
                request_date TEXT,
                warden_id INTEGER,
                FOREIGN KEY (room_id) REFERENCES Rooms(room_id) ON DELETE RESTRICT,
                FOREIGN KEY (student_id) REFERENCES Students(student_id),
                FOREIGN KEY (warden_id) REFERENCES Warden(warden_id)
            )
        """)

        conn.commit()


if __name__ == "__main__":
    create_tables()
    print("Database and tables created successfully!")





