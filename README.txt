=====================================================================
                 HOSTEL MANAGEMENT SYSTEM - README
=====================================================================

A web-based hostel management system built with Flask and SQLite.
It manages student registration, room booking, payments, fines,
maintenance requests, announcements, and reporting for three user
roles: Admin, Warden, and Student.


---------------------------------------------------------------------
1. TECH STACK
---------------------------------------------------------------------
- Python 3.13
- Flask (web framework)
- SQLite (database: dbsystem.db)
- Flask-Mail (Gmail SMTP - password reset emails)
- itsdangerous (secure password reset tokens)
- Werkzeug (password hashing)
- ReportLab (PDF generation - reports and receipts)
- Matplotlib (room occupancy graphs)
- Groq API (AI chatbot for students, llama-3.3-70b-versatile)
- Bootstrap 5 (frontend styling)


---------------------------------------------------------------------
2. PROJECT STRUCTURE
---------------------------------------------------------------------
project/
|-- app.py              Main Flask application (all routes)
|-- database.py         Database connection + table creation
|-- dbsystem.db         SQLite database (auto-created on first run)
|-- .env                Environment variables (see section 4)
|-- templates/          HTML templates (Jinja2)
|-- static/
    |-- css/            Stylesheets


---------------------------------------------------------------------
3. INSTALLATION
---------------------------------------------------------------------
1. Install Python 3.10 or newer.

2. Install dependencies:

   pip install flask flask-mail itsdangerous reportlab matplotlib
   pip install python-dateutil python-dotenv groq werkzeug

3. Create a .env file (see section 4).

4. Run the app:

   python app.py

5. Open in browser:

   http://127.0.0.1:5002


---------------------------------------------------------------------
4. ENVIRONMENT VARIABLES (.env)
---------------------------------------------------------------------
Create a file named ".env" in the project folder:

   SECRET_KEY=your-random-secret-key-here
   MAIL_PASSWORD=your-gmail-app-password
   GROQ_API_KEY=your-groq-api-key

Notes:
- MAIL_PASSWORD is a Gmail App Password (not the normal account
  password). Required for the forgot-password email feature.
- GROQ_API_KEY is required for the student AI chatbot.
- Never commit the .env file or share these keys.


---------------------------------------------------------------------
5. USER ROLES AND FEATURES
---------------------------------------------------------------------

ADMIN (default login: admin@gmail.com / admin123)
- Dashboard with totals (students, rooms, bookings, pending approvals)
- Approve / reject student registrations
- Register and view wardens (with detail pages)
- Add / edit / delete rooms
- Manage bookings (approve, reject, delete)
- Manage payments (mark paid, mark fines paid, generate receipts)
- Reports: bed occupancy, payment reports, downloadable PDFs,
  room occupancy graph

WARDEN
- Dashboard
- View students and student details
- Post and manage announcements
- Manage maintenance requests (mark done, prioritised by category)
- Issue fines to students
- View payment fines and overdue payments
- Edit own profile

STUDENT
- Register (pending admin approval before login works)
- Dashboard with notifications
- Browse and book rooms (with filters: type, gender, price)
- One active booking at a time; overlap and capacity checks
- Pay for bookings (Card / E-Wallet / Online Banking)
- Pay fines
- Download PDF receipts and view payment history
- Submit maintenance requests (requires a paid, approved booking)
- View announcements and hostel policy
- AI chatbot for hostel-related questions
- Edit own profile, forgot/reset password by email


---------------------------------------------------------------------
6. KEY BUSINESS RULES
---------------------------------------------------------------------
- New students must be approved by admin before they can log in.
- A student can hold only one Pending/Approved booking at a time.
- Approving a booking takes one bed from the room; rejecting or
  deleting an approved booking gives the bed back.
- Rooms become "Occupied" when available beds reach 0.
- Booking cost = monthly rent x number of months (partial months
  are rounded up).
- Maintenance requests are only allowed after the room payment
  is completed.
- Maintenance priority is auto-assigned by category
  (e.g. Gas Leak = High, Furniture = Low).
- Fines use status values: "pending" and "paid".
- When a booking expires, the room is released and the student is
  reminded of any outstanding payments or fines.


---------------------------------------------------------------------
7. SECURITY NOTES
---------------------------------------------------------------------
- Passwords are stored hashed (Werkzeug generate_password_hash).
- Password reset uses expiring signed tokens sent by email.
- All admin/warden/student pages check the session role.
- Payment routes verify the booking/fine belongs to the logged-in
  student.
- Only the last 4 digits of card/account numbers are stored.
- Secrets (secret key, mail password, API key) are read from .env.
- The default admin account (admin@gmail.com / admin123) is
  hardcoded for development - change or remove it before any
  real deployment.


---------------------------------------------------------------------
8. DATABASE TABLES (overview)
---------------------------------------------------------------------
- Users                 All accounts (name, email, password hash,
                        role, user_status)
- Students              Student details (programme, year, gender,
                        emergency contact)
- Warden                Warden details
- Rooms                 Room info (number, type, gender, capacity,
                        available beds, price, status)
- Bookings              Room bookings (dates, total payment,
                        booking status, payment status)
- Payment               Payment records (method, amount, date,
                        masked card number)
- Fine                  Fines (amount, reason, fine_status,
                        issued date)
- MaintenanceRequests   Maintenance requests (category, priority,
                        status)
- Announcements         Announcements posted by admin/warden
- Notifications         Student notifications

The database and tables are created automatically on first run
(create_tables() in database.py).


---------------------------------------------------------------------
9. TROUBLESHOOTING
---------------------------------------------------------------------
- "BuildError: Could not build url for endpoint ..."
  A template links to a route that does not exist. Check that the
  function name in app.py matches the name used in url_for().

- "no such column ..."
  The SQL uses a column name that does not match the table schema.
  Check the column names in database.py.

- Emails not sending
  Make sure MAIL_PASSWORD is set in .env and is a valid Gmail
  App Password.

- Chatbot not replying
  Make sure GROQ_API_KEY is set in .env.

- Login fails for a registered student
  The account may still be "pending" - approve it from the admin
  dashboard first.
