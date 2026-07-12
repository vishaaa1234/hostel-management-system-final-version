from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
from flask import send_file
from flask_mail import Mail, Message
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
import io
import sqlite3
import io
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.units import inch
from reportlab.platypus import Image
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, TableStyle, Table, Image
from werkzeug.security import generate_password_hash,  check_password_hash
from dateutil.relativedelta import relativedelta
from database import get_db_connection, create_tables

import os
from dotenv import load_dotenv
load_dotenv()
from groq import Groq

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
   # reject uploads over 5 MB


app = Flask(__name__)
app.secret_key = "secret456"

import os
from werkzeug.utils import secure_filename

MAINT_UPLOAD_FOLDER = os.path.join('static', 'uploads', 'maintenance')
ALLOWED_IMAGE_EXT = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
os.makedirs(MAINT_UPLOAD_FOLDER, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024

reset_serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

DATABASE = "dbsystem.db"

# one-time migration: soft-delete column for Rooms
try:
    _mconn = sqlite3.connect('dbsystem.db')
    _mconn.execute("ALTER TABLE Rooms ADD COLUMN is_deleted INTEGER DEFAULT 0")
    _mconn.commit()
    _mconn.close()
except sqlite3.OperationalError:
    pass  # column already exists


#--- Email(GmailSMTP) config - --
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'hostelsystem25@gmail.com'
app.config['MAIL_PASSWORD'] = 'gisyhwbnatiaolsw'
app.config['MAIL_DEFAULT_SENDER'] = 'Hostel Management', 'hostelsystem25@gmail.com'
app.config['APP_BASE_URL'] = 'http://127.0.0.1:5002'

mail = Mail(app)

# Category mapping on
CATEGORY_PRIORITY = {
    "Fire Safety / Smoke Detector": "High",
    "Gas Leak": "High",
    "Elevator/Lift Issues": "High",
    "Safety and Security": "High",
    "Doors, Windows, and Locks": "High",
    "Building Infrastructure": "High",
    "Plumbing Issues": "Medium",
    "Electrical Issues": "High",
    "HVAC and Ventilation": "Medium",
    "Internet and Communication": "Medium",
    "Cleanliness and Hygiene": "Medium",
    "Furniture": "Low",
    "Laundry Facilities": "Low",
    "Kitchen and Pantry Areas": "Low",
    "Room-specific Comfort": "Low",
}


with app.app_context():
    create_tables()

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# ================= HOME =================
@app.route('/')
def home():
    return render_template('homepage.html')

# ================= LOGIN =================
@app.route('/login', methods=['GET', 'POST'])
def login():
    message = ""

    if request.method == 'POST':
        email = request.form['email'].strip()
        password = request.form['password'].strip()

        # ADMIN LOGIN (hardcoded)
        if email == "admin@gmail.com" and password == "admin123":
            session.clear()
            session['user_id'] = None
            session['name'] = "Administrator"
            session['role'] = "admin"
            return redirect(url_for('admin_dashboard'))

        # NORMAL USERS (DB)
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM Users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()

        if not user or not check_password_hash(user['password'], password):
            message = "Invalid email or password!"
            return render_template('homepage.html', message=message)

        if user['user_status'] == 'pending':
            message = "Your account is pending admin approval."
            return render_template('homepage.html', message=message)

        if user['user_status'] == 'rejected':
            message = "Your account has been rejected."
            return render_template('homepage.html', message=message)

        # VALID USER LOGIN
        session.clear()
        session['user_id'] = user['user_id']
        session['name'] = user['name']
        session['role'] = user['role']

        if user['role'] == 'warden':
            return redirect(url_for('warden_dashboard'))
        elif user['role'] == 'student':
            return redirect(url_for('student_dashboard'))

    return render_template('homepage.html', message=message)

# ================= FORGOT PASSWORD =================
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    message = ""

    if request.method == 'POST':
        email = request.form.get('email', '').strip()

        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM Users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()

        if user:
            token = reset_serializer.dumps(email, salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)

            html_body = render_template(
                'reset_password_email.html',
                name=user['name'],
                reset_url=reset_url
            )
            msg = Message(
                subject="Reset Your Hostel Account Password",
                recipients=[email],
                html=html_body
            )
            try:
                mail.send(msg)
            except Exception as e:
                print("Password reset email error:", e)


        message = "If an account with that email exists, we've sent a password reset link to it."

    return render_template('forgot_password.html', message=message)


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = reset_serializer.loads(token, salt='password-reset-salt', max_age=3600)
    except SignatureExpired:
        flash("This password reset link has expired. Please request a new one.", "danger")
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash("This password reset link is invalid. Please request a new one.", "danger")
        return redirect(url_for('forgot_password'))

    message = ""

    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()

        if not password or not confirm_password:
            message = "Both fields are required."
        elif password != confirm_password:
            message = "Passwords do not match."
        else:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()
            cursor.execute("UPDATE Users SET password = ? WHERE email = ?", (generate_password_hash(password), email))
            conn.commit()
            conn.close()

            flash("Your password has been reset. Please log in with your new password.", "success")
            return redirect(url_for('login'))

    return render_template('reset_password.html', token=token, message=message)



# ================= ADMIN =================
@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()

    # Count only APPROVED students (user_status = 'approved')
    total_students = conn.execute("""
            SELECT COUNT(*) 
            FROM Students s 
            JOIN Users u ON s.user_id = u.user_id 
            WHERE u.user_status = 'approved'
        """).fetchone()[0]

    # Total rooms
    total_rooms = conn.execute("SELECT COUNT(*) FROM Rooms").fetchone()[0]

    # Total bookings
    total_bookings = conn.execute("SELECT COUNT(*) FROM Bookings").fetchone()[0]

    # Pending approvals (students waiting for approval)
    pending_approvals = conn.execute("""
            SELECT COUNT(*) 
            FROM Users 
            WHERE user_status = 'pending' AND role = 'student'
        """).fetchone()[0]

    conn.close()

    return render_template('admin_dashboard.html',
                           total_students=total_students,
                           total_rooms=total_rooms,
                           total_bookings=total_bookings,
                           pending_approvals=pending_approvals)


# ================= STUDENT REGISTER (by student) =================
import re

@app.route('/student_register', methods=['GET', 'POST'])
def student_register():
    message = ""
    success = False
    form_data = {}

    if request.method == 'POST':
        form_data = request.form

        name = request.form['name'].strip()
        email = request.form['email'].strip()
        phone_number = request.form['phone_number'].strip()
        date_of_birth = request.form.get('date_of_birth', '').strip()
        programme = request.form.get('programme', '').strip()
        year_of_study = request.form.get('year_of_study', '').strip()
        emergency_contact = request.form.get('emergency_contact', '').strip()
        gender = request.form.get('gender', '').strip()

        address_parts = [
            request.form.get('address', '').strip(),
            request.form.get('address2', '').strip(),
            request.form.get('postcode', '').strip(),
            request.form.get('city', '').strip(),
            request.form.get('country', '').strip()
        ]
        address = ', '.join(part for part in address_parts if part)

        password = request.form['password'].strip()
        confirm_password = request.form['confirm_password'].strip()

        # 1. Required fields
        if (
                not name or
                not email or
                not phone_number or
                not date_of_birth or
                not programme or
                not gender or
                not year_of_study or
                not emergency_contact or
                not password or
                not confirm_password
        ):
            message = "All fields are required!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        # 2. Name checks
        if len(name) < 2 or len(name) > 100:
            message = "Please enter a valid name!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        if any(char.isdigit() for char in name):
            message = "Name cannot contain numbers!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        # 3. Email checks
        email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not re.match(email_pattern, email):
            message = "Please enter a valid email address!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        # 4. Programme checks
        if any(char.isdigit() for char in programme):
            message = "Programme cannot contain numbers!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        # 7. Phone number checks
        if not phone_number.isdigit():
            message = "Contact number must be numeric!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        if not (9 <= len(phone_number) <= 11):
            message = "Contact number must be between 9 and 11 digits!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        # 8. Emergency contact checks
        if not emergency_contact.isdigit():
            message = "Emergency contact must be numeric!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        if not (9 <= len(emergency_contact) <= 11):
            message = "Emergency contact must be between 9 and 11 digits!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        # 9. Date of birth checks
        try:
            dob = datetime.strptime(date_of_birth, '%Y-%m-%d')
        except ValueError:
            message = "Invalid date of birth format!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        if dob > datetime.now():
            message = "Date of birth cannot be in the future!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        age = (datetime.now() - dob).days // 365
        if age < 1 or age > 100:
            message = "Please enter a valid date of birth!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        # 10. Password checks: min 8 characters, at least one uppercase letter
        if len(password) < 6:
            message = "Password must be at least 6 characters long!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        if not any(char.isdigit() for char in password):
            message = "Password must contain at least one numeric digit!"
            return render_template(
                'student_register.html',
                message=message,
                success=False,
                form_data=form_data
            )

        if password != confirm_password:
            message = "Passwords do not match!"
            return render_template('student_register.html', message=message, success=False, form_data=form_data)

        hashed_password = generate_password_hash(password)

        conn = None
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()

            # 11. Check for duplicate email before inserting
            cursor.execute("SELECT user_id FROM Users WHERE email = ?", (email,))
            if cursor.fetchone():
                conn.close()
                message = "Email is already registered!"
                return render_template('student_register.html', message=message, success=False, form_data=form_data)

            cursor.execute("""
                        INSERT INTO Users (name, email, phone_number, date_of_birth, address, password, role, user_status)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (name, email, phone_number, date_of_birth, address, hashed_password, 'student', 'pending'))
            user_id = cursor.lastrowid

            cursor.execute("""
                        INSERT INTO Students (user_id, programme, year_of_study, gender, emergency_contact)
                        VALUES (?, ?, ?, ?, ?)
                    """, (user_id, programme, year_of_study, gender, emergency_contact))

            conn.commit()
            message = "Registration submitted! Please wait for admin approval."
            success = True
            form_data = {}

        except sqlite3.IntegrityError as e:
            if conn: conn.rollback()
            message = f"IntegrityError: {str(e)}"
            success = False
        except Exception as e:
            if conn: conn.rollback()
            message = f"Error: {str(e)}"
            success = False
        finally:
            if conn: conn.close()

    return render_template('student_register.html', message=message, success=success, form_data=form_data)



# ================= VIEW STUDENTS =================
@app.route('/view_students')
def view_students():
    if session.get('role') not in ['admin']:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    search = request.args.get('q', '').strip()

    query = """
        SELECT users.*,
               students.student_id,
               students.rowid AS student_num,
               students.programme,
               students.year_of_study,
               students.emergency_contact,
               students.gender,
               r.room_number AS room_number
        FROM users
        LEFT JOIN students 
               ON users.user_id = students.user_id
        LEFT JOIN bookings b 
               ON b.student_id = students.student_id 
              AND b.booking_status = 'Approved'
        LEFT JOIN rooms r 
               ON b.room_id = r.room_id
        WHERE users.role = 'student'
    """

    params = []

    if search:
        query += " AND (users.name LIKE ? OR r.room_number LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])

    query += " ORDER BY users.name"

    cursor.execute(query, params)
    students = [dict(row) for row in cursor.fetchall()]

    for s in students:
        s['display_id'] = f"S{s['student_num']:03d}" if s['student_num'] else "—"

    conn.close()

    return render_template('view_students.html', students=students, search=search)

@app.route('/view_students_detail/<int:user_id>')
def view_students_detail(user_id):
    if session.get('role') not in ['admin']:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    student = cursor.execute("""
        SELECT u.*,s.rowid AS student_num, s.programme, s.year_of_study, s.emergency_contact, s.gender
        FROM Users u
        LEFT JOIN Students s ON u.user_id = s.user_id
        WHERE u.user_id = ?
    """, (user_id,)).fetchone()

    student = dict(student) if student else None

    if student:
        student['display_id'] = f"S{student['student_num']:03d}" if student['student_num'] else "—"

    conn.close()

    return render_template('view_students_detail.html', student=student)

@app.route('/warden_view_student_details/<int:user_id>')
def warden_view_student_details(user_id):
    if session.get('role') not in ['warden']:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    student = cursor.execute("""
        SELECT u.*, s.rowid AS student_num, s.programme, s.year_of_study, s.emergency_contact, s.gender
        FROM Users u
        LEFT JOIN Students s ON u.user_id = s.user_id
        WHERE u.user_id = ?
    """, (user_id,)).fetchone()

    student = dict(student) if student else None

    if student:
        student['display_id'] = f"S{student['student_num']:03d}" if student['student_num'] else "—"

    conn.close()

    return render_template('warden_view_student_details.html', student=student)


# =============warden view students ============= #
@app.route('/warden_view_students')
def warden_view_students():
    if session.get('role') not in ['warden']:
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    search = request.args.get('q', '').strip()

    query = """
        SELECT Users.*, Students.rowid AS student_num, Students.programme, Students.year_of_study,
               Students.emergency_contact, Students.gender,
               r.room_number AS room_number
        FROM Users
        LEFT JOIN Students ON Users.user_id = Students.user_id
        LEFT JOIN Bookings b ON b.student_id = Students.student_id AND b.booking_status = 'Approved'
        LEFT JOIN Rooms r ON b.room_id = r.room_id
        WHERE Users.role = 'student'
    """
    params = []

    if search:
        query += " AND (Users.name LIKE ? OR r.room_number LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])

    query += " ORDER BY Users.name"

    cursor.execute(query, params)
    cursor.execute(query, params)

    students = [dict(row) for row in cursor.fetchall()]
    for s in students:
        s['display_id'] = f"S{s['student_num']:03d}" if s.get('student_num') else "—"
    conn.close()


    return render_template('warden_view_students.html', students=students, search=search)


# ================= APPROVE / REJECT =================
@app.route('/approve_user/<int:user_id>')
def approve_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("SELECT email, name FROM Users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    cursor.execute("UPDATE Users SET user_status = 'approved' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    if user:
        user_email, user_name = user
        try:
            send_registration_email(user_email, user_name, approved=True)
        except Exception as e:
            print(f"Email failed to send: {e}")

    return redirect(url_for('view_students'))

@app.route('/reject_user/<int:user_id>')
def reject_user(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()

    cursor.execute("SELECT email, name FROM Users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()

    cursor.execute("UPDATE Users SET user_status = 'rejected' WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    if user:
        user_email, user_name = user
        try:
            send_registration_email(user_email, user_name, approved=False)
        except Exception as e:
            print(f"Email failed to send: {e}")

    return redirect(url_for('view_students'))

@app.route('/admin/register')
def admin_registration():
    return render_template('admin_registration.html')

# ================= WARDEN =================
@app.route('/warden_registration', methods=['GET', 'POST'])
def warden_registration():
    message = ""
    success = False
    form_data = {}

    if request.method == 'POST':
        form_data = request.form

        name = request.form['name'].strip()
        email = request.form['email'].strip()
        phone_number = request.form['phone_number'].strip()
        date_of_birth = request.form.get('date_of_birth', '').strip()

        address_parts = [
            request.form.get('address', '').strip(),
            request.form.get('address2', '').strip(),
            request.form.get('postcode', '').strip(),
            request.form.get('city', '').strip(),
            request.form.get('country', '').strip()
        ]
        address = ', '.join(part for part in address_parts if part)

        password = request.form['password'].strip()
        confirm_password = request.form['confirm_password'].strip()

        # Required fields
        if not name or not email or not phone_number or not password or not confirm_password:
            message = "All fields are required!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        # Password match
        if password != confirm_password:
            message = "Passwords do not match!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        # Phone number check
        if not phone_number.isdigit():
            message = "Contact number must be numeric!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        # DOB checks
        try:
            dob = datetime.strptime(date_of_birth, '%Y-%m-%d')
        except ValueError:
            message = "Invalid date of birth format!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        if dob > datetime.now():
            message = "Date of birth cannot be in the future!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        age = (datetime.now() - dob).days // 365
        if age < 1 or age > 100:
            message = "Please enter a valid age!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        # Password rules
        if len(password) < 6:
            message = "Password must be at least 6 characters long!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        if not any(char.isdigit() for char in password):
            message = "Password must contain at least one numeric digit!"
            return render_template('warden_registration.html', message=message, success=False, form_data=form_data)

        hashed_password = generate_password_hash(password)

        conn = None
        try:
            conn = sqlite3.connect(DATABASE)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO Users (name, email, phone_number, date_of_birth, address, password, role, user_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (name, email, phone_number, date_of_birth, address, hashed_password, 'warden', 'approved'))

            user_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO Warden (user_id)
                VALUES (?)
            """, (user_id,))

            conn.commit()

            message = "Registration Successful!"
            success = True
            form_data = {}


        except sqlite3.IntegrityError as e:

            if conn: conn.rollback()

            if 'Users.email' in str(e):

                message = "This email is already registered. Please use a different email or log in."

            else:

                message = "A database error occurred. Please try again."

        except Exception as e:

            if conn: conn.rollback()

            message = "An unexpected error occurred. Please try again."
        finally:
            if conn: conn.close()

    return render_template('warden_registration.html', message=message, success=success, form_data=form_data)


@app.route('/view_wardens')
def view_wardens():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    search = request.args.get('q', '').strip()

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT Users.*, Warden.rowid AS warden_num
        FROM Users
        LEFT JOIN Warden ON Users.user_id = Warden.user_id
        WHERE Users.role = 'warden'
    """
    params = []

    if search:
        query += " AND Users.name LIKE ?"
        params.append(f"%{search}%")

    cursor.execute(query, params)
    wardens = [dict(row) for row in cursor.fetchall()]

    for w in wardens:
        w['display_id'] = f"W{w['warden_num']:03d}" if w['warden_num'] else "—"

    conn.close()

    return render_template('view_wardens.html', wardens=wardens, search=search)

@app.route('/view_warden_detail/<int:user_id>')
def view_warden_detail(user_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    warden = cursor.execute("""
        SELECT Users.*
        FROM Users
        JOIN Warden ON Users.user_id = Warden.user_id
        WHERE Users.user_id = ?
    """, (user_id,)).fetchone()

    conn.close()

    if warden is None:
        return redirect(url_for('view_wardens'))

    return render_template('view_warden_detail.html', warden=warden)


@app.route('/edit-warden-profile', methods=['GET', 'POST'])
def warden_edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    def get_warden(cursor):
        cursor.execute("""
            SELECT u.*
            FROM Users u
            JOIN Warden w ON u.user_id = w.user_id
            WHERE u.user_id = ?
        """, (user_id,))
        return cursor.fetchone()

    if request.method == 'GET':
        conn = sqlite3.connect(DATABASE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        warden = get_warden(cursor)
        conn.close()
        return render_template('warden_edit_profile.html', warden=warden)

    # ── POST ──
    name              = request.form.get('name', '').strip()
    email             = request.form.get('email', '').strip()
    phone_number      = request.form.get('phone_number', '').strip()
    date_of_birth     = request.form.get('date_of_birth', '').strip()
    address           = request.form.get('address', '').strip()
    current_password  = request.form.get('current_password', '')
    new_password      = request.form.get('new_password', '')
    confirm_password  = request.form.get('confirm_password', '')

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    warden = get_warden(cursor)

    def error(message):
        current_warden = get_warden(cursor)
        conn.close()
        return render_template('warden_edit_profile.html', warden=current_warden,
                               message=message, success=False)

    # Required fields
    if not name or not email or not phone_number or not date_of_birth:
        return error("Name, email, phone number, and date of birth are required.")

    # Phone number check
    if not phone_number.isdigit():
        return error("Contact number must be numeric!")

    # DOB checks
    try:
        dob = datetime.strptime(date_of_birth, '%Y-%m-%d')
    except ValueError:
        return error("Invalid date of birth format!")

    if dob > datetime.now():
        return error("Date of birth cannot be in the future!")

    age = (datetime.now() - dob).days // 365
    if age < 1 or age > 100:
        return error("Please enter a valid age!")

    # Email uniqueness check
    existing = cursor.execute(
        "SELECT * FROM Users WHERE email = ? AND user_id != ?", (email, user_id)
    ).fetchone()
    if existing:
        return error("Email already in use by another account.")

    # Optional password change — must verify current password first
    if new_password or confirm_password:
        if not current_password:
            return error("Please enter your current password to set a new one.")

        if not check_password_hash(warden['password'], current_password):
            return error("Current password is incorrect.")

        if new_password != confirm_password:
            return error("Passwords do not match.")

        # Password rules
        if len(new_password) < 6:
            return error("Password must be at least 6 characters long!")

        if not any(char.isdigit() for char in new_password):
            return error("Password must contain at least one numeric digit!")

        hashed = generate_password_hash(new_password)
        cursor.execute("UPDATE Users SET password = ? WHERE user_id = ?",
                       (hashed, user_id))

    cursor.execute("""
        UPDATE Users SET name = ?, email = ?, phone_number = ?, date_of_birth = ?, address = ?
        WHERE user_id = ?
    """, (name, email, phone_number, date_of_birth, address, user_id))

    conn.commit()
    session['name'] = name

    warden = get_warden(cursor)
    conn.close()
    return render_template('warden_edit_profile.html', warden=warden,
                           message="Profile updated successfully!", success=True)

# ================= DASHBOARDS =================


def get_checkout_message(conn, student_id, today):
    """
    Check the student's most recent booking. If it was Approved and its
    end date has passed, mark the room Available again and build a
    'thank you for your stay' message (including any outstanding
    payment/fines). Returns the message string, or None if not applicable.
    Shared by /student_dashboard and /room_booking so the two stay in sync.
    """

    my_booking = conn.execute("""
        SELECT b.booking_id, b.booking_status, b.payment_status, b.end_date,
               b.room_id, r.room_number
        FROM Bookings b
        LEFT JOIN Rooms r ON b.room_id = r.room_id
        WHERE b.student_id = ?
        ORDER BY b.booking_id DESC
        LIMIT 1
    """, (student_id,)).fetchone()

    from datetime import datetime

    if not (my_booking and my_booking['booking_status'] == 'Approved'):
        return None

    end_date = datetime.strptime(my_booking['end_date'], "%Y-%m-%d").date()
    today_date = datetime.now().date()

    if not (end_date < today_date):
        return None

    # Mark room as Available again
    conn.execute("""
            UPDATE Rooms
            SET room_status='Available'
            WHERE room_id=?
        """, (my_booking["room_id"],))

    conn.execute("""
            UPDATE Bookings
            SET booking_status='Completed'
            WHERE booking_id=?
        """, (my_booking["booking_id"],))

    conn.commit()

    outstanding_booking = my_booking["payment_status"] != "Paid"

    fine = conn.execute("""
            SELECT COALESCE(SUM(amount),0) AS total
            FROM Fine
            WHERE student_id=?
            AND fine_status='pending'
        """, (student_id,)).fetchone()

    outstanding_fines = fine["total"]

    message = (
        f"Thank you for staying in Room {my_booking['room_number']}! "
        "We hope you enjoyed your stay."
    )

    if outstanding_booking or outstanding_fines > 0:
        message += " Please remember to settle your outstanding payments."

    return message
print(get_checkout_message)


@app.route('/student_dashboard')
def student_dashboard():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    user_id = session['user_id']
    today = datetime.now().strftime('%Y-%m-%d')

    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    # If no student record exists
    if student is None:
        conn.close()
        return redirect(url_for('login'))

    notifications = ()
    checkout_message = None
    if student:
        notifications = conn.execute("""
            SELECT notification_id, message, category, created_at
            FROM Notifications
            WHERE student_id=? AND is_read=0
            ORDER BY notification_id DESC
            LIMIT 3
        """, (student['student_id'],)).fetchall()

        checkout_message = get_checkout_message(conn, student['student_id'], today)

        booking = conn.execute("""
                SELECT b.booking_status, b.payment_status, r.room_number, b.start_date, b.end_date, b.total_payment
                FROM Bookings b
                LEFT JOIN Rooms r ON b.room_id = r.room_id
                WHERE b.student_id=?
                ORDER BY b.booking_id DESC LIMIT 1
            """, (student['student_id'],)).fetchone()

        outstanding = conn.execute("""
                SELECT COALESCE(SUM(total_payment), 0) AS total
                FROM Bookings
                WHERE student_id=? AND payment_status='Unpaid'
            """, (student['student_id'],)).fetchone()['total']

        announcements = conn.execute("""
                    SELECT title, details, date
                    FROM Announcements
                    ORDER BY date DESC
                    LIMIT 3
                """).fetchall()

        conn.close()

    return render_template('student_dashboard.html', notifications=notifications,
                           booking=booking, outstanding=outstanding,checkout_message=checkout_message,announcements=announcements)


@app.route('/post_announcement', methods=['GET', 'POST'])
def post_announcement():

    if session.get('role') != 'warden':
        return redirect(url_for('login'))

    if request.method == 'POST':

        title = request.form['title']
        details = request.form['details']
        date = datetime.now().strftime('%Y-%m-%d')

        conn = get_db_connection()
        warden_row = conn.execute(
            "SELECT warden_id FROM Warden WHERE user_id=?", (session['user_id'],)
        ).fetchone()
        warden_id = warden_row['warden_id'] if warden_row else None

        conn.execute("""
            INSERT INTO Announcements
            (title, details, date, user_id)
            VALUES (?, ?, ?, ?)
        """, (title, details, date, session['user_id']))

        conn.commit()
        conn.close()

        flash("Announcement posted successfully!", "success")

        return redirect(url_for('warden_dashboard'))

    return render_template('post_announcement.html')


@app.route('/warden_dashboard')
def warden_dashboard():
    if session.get('role') != 'warden':
        return redirect(url_for('login'))

    conn = get_db_connection()

    total_students = conn.execute("SELECT COUNT(*) FROM Students").fetchone()[0]


    bed_stats = conn.execute("""
            SELECT COALESCE(SUM(bed_capacity), 0) AS total_beds,
                   COALESCE(SUM(available_beds), 0) AS available_beds
            FROM Rooms 
            
            
        """).fetchone()

    pending_maintenance = conn.execute("""
            SELECT COUNT(*) FROM MaintenanceRequests
            WHERE maintenance_status = 'Pending'
        """).fetchone()[0]

    conn.close()

    total_beds = bed_stats["total_beds"]
    available_beds = bed_stats["available_beds"]
    occupied_beds = total_beds - available_beds

    return render_template('warden_dashboard.html',
                           total_students=total_students,
                           total_beds=total_beds,
                           available_beds=available_beds,
                           occupied_beds=occupied_beds,
                           pending_maintenance=pending_maintenance
                           )






# ==========================
# ROOM PREVIEW  (public — no login needed)
# ==========================
@app.route('/room-preview')
def room_preview():
    conn = get_db_connection()
    cur  = conn.cursor()

    query  = "SELECT * FROM Rooms WHERE available_beds > 0 AND is_deleted=0"
    params = []

    room_type = request.args.get('type')
    gender    = request.args.get('gender')
    price     = request.args.get('price')

    if room_type:
        query += " AND room_type = ?"
        params.append(room_type)
    if gender:
        query += " AND gender = ?"
        params.append(gender)
    if price:
        query += " AND price_per_month <= ?"
        params.append(price)



    cur.execute(query, params)
    rooms = cur.fetchall()
    conn.close()

    today = datetime.now().strftime('%B %d, %Y')
    return render_template('room_preview.html', rooms=rooms, today=today)



# ==========================
# ROOM BOOKING FLOW (student)
# ==========================

from datetime import datetime

from flask import send_file


@app.route('/room_booking')
def room_booking():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    user_id = session['user_id']
    today = datetime.now().strftime('%Y-%m-%d')

    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    rooms = conn.execute(
        "SELECT * FROM Rooms WHERE room_status='Available' AND is_deleted=0 "
    ).fetchall()

    # ── Apply filters ──
    query = "SELECT * FROM Rooms WHERE (room_status='Available')"
    params = []

    room_type = request.args.get('type')
    gender = request.args.get('gender')
    price = request.args.get('price')
    room_id = request.args.get('room_id')

    if room_type:
        query += " AND room_type = ?"
        params.append(room_type)
    if gender:
        query += " AND gender = ?"
        params.append(gender)
    if price:
        query += " AND price_per_month <= ?"
        params.append(price)

    rooms = conn.execute(query, params).fetchall()

    my_booking = None
    selected_room = None

    checkout_message = None





    if student:
        student_id = student['student_id']

        my_booking = conn.execute("""
            SELECT
                b.booking_id      AS id,
                b.room_id         AS room_id,
                r.room_number     AS room_number,
                b.rent_per_month   AS rent_per_month,
                b.start_date      AS start_date,
                b.end_date        AS end_date,
                b.total_payment   AS total_payment,
                b.booking_status AS status,
                b.payment_status AS payment_status,
                b.receipt_url    AS receipt_url
            FROM Bookings b
            JOIN Rooms r ON b.room_id = r.room_id
            WHERE b.student_id=?
            ORDER BY b.booking_id DESC LIMIT 1
        """, (student_id,)).fetchone()




        if my_booking and my_booking['status'] == 'Approved' and my_booking['end_date'] < today:
            # Mark room as Available again
            conn.execute(
                "UPDATE Rooms SET room_status='Available' WHERE room_id=?",
                (my_booking['room_id'],)
            )
            conn.commit()

            # Check for unpaid booking payment
            unpaid_booking = my_booking['payment_status'] != 'Paid'

            # Check for unpaid fines
            unpaid_fines = conn.execute("""
                        SELECT COALESCE(SUM(amount), 0) AS total
                        FROM Fine
                        WHERE student_id=? AND status='pending'
                    """, (student_id,)).fetchone()['total']

            if unpaid_booking or unpaid_fines > 0:
                parts = []
                if unpaid_booking:
                    parts.append(f"RM {my_booking['total_payment']:.2f} room payment")
                if unpaid_fines > 0:
                    parts.append(f"RM {unpaid_fines:.2f} in outstanding fines")
                outstanding_summary = ' and '.join(parts)
                checkout_message = (
                    f"Thank you for your delightful stay in Room {my_booking['room_number']}! "
                    f"Please complete your remaining payment of {outstanding_summary} "
                    f"to keep your account in good standing."
                )

            # Don't show the expired booking card as active
            my_booking = None

        elif my_booking and (
                my_booking['status'] == 'Pending'
                or (my_booking['status'] == 'Approved' and my_booking['end_date'] >= today)
        ):
            has_active_booking = True

        # If a room was picked from the grid, show the booking panel
        room_id = request.args.get('room_id')
        if room_id:
            selected_room = conn.execute(
                "SELECT * FROM Rooms WHERE room_id=?", (room_id,)
            ).fetchone()

    conn.close()

    return render_template('room_booking.html',
                           rooms=rooms,
                           my_booking=my_booking,
                           selected_room=selected_room,
                           checkout_message=checkout_message)


@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    user_id      = session['user_id']
    student_name = session['name']
    room_id      = request.form['room_id']
    start_date   = request.form['start_date']
    end_date     = request.form['end_date']

    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    room = conn.execute(
        "SELECT * FROM Rooms WHERE room_id=?", (room_id,)
    ).fetchone()

    if not student or not room:
        flash('Unable to process booking. Please try again.', 'danger')
        conn.close()
        return redirect(url_for('room_booking'))

    student_id = student['student_id']
    today = datetime.now().strftime('%Y-%m-%d')

    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    today = datetime.now().date()
    if end <= start:
        flash("End date must be after the start date.", "danger")
        conn.close()
        return redirect(url_for("room_booking"))

    diff = relativedelta(end, start)

    total_months = diff.years * 12 + diff.months

    if start.date() < today:
        flash("Start date cannot be in the past.", "danger")
        conn.close()
        return redirect(url_for("room_booking", room_id=room_id))

    # If there are extra days, count as another month
    if diff.days > 0:
        total_months += 1

    rent_per_month = room['price_per_month']

    total_payment = rent_per_month * total_months

    overlap = conn.execute("""
    SELECT COUNT(*) AS total
    FROM Bookings
    WHERE room_id=?
    AND booking_status IN ('Pending','Approved')
    AND NOT (
        end_date < ?
        OR start_date > ?
    )
    """, (room_id, start_date, end_date)).fetchone()

    if overlap["total"] >= room["bed_capacity"]:
        flash("This room is fully booked for the selected dates.", "danger")
        conn.close()
        return redirect(url_for("room_booking", room_id=room_id))

    existing_booking = conn.execute("""
            SELECT booking_id, booking_status, end_date FROM Bookings
            WHERE student_id=?
              AND (
                    booking_status='Pending'
                    OR (booking_status='Approved' AND end_date >= ?)
                  )
            ORDER BY booking_id DESC LIMIT 1
        """, (student_id, today)).fetchone()

    print("existing_booking:", existing_booking)

    if existing_booking:
        conn.close()
        if existing_booking['booking_status'] == 'Pending':
            flash('You already have a booking request pending approval. '
                  'You cannot book another room until it is approved or rejected.', 'warning')
        else:
            flash(f"You already have an active room booking until {existing_booking['end_date']}. "
                  f"You cannot book another room until it expires.", 'warning')
        return redirect(url_for('room_booking'))


    conn.execute("""
        INSERT INTO Bookings
        (room_id, student_id, student_name, rent_per_month, start_date, end_date,
         total_payment, booking_status, payment_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', 'Unpaid')
    """, (room['room_id'], student['student_id'], student_name,
          rent_per_month, start_date, end_date, total_payment))

    conn.commit()
    conn.close()



    flash('Booking request submitted! Waiting for admin approval.', 'success')
    return redirect(url_for('room_booking', room_id=room_id))

@app.route('/student_delete_booking/<int:booking_id>', methods=['POST'])
def student_delete_booking(booking_id):
    if session.get('role') != 'student':
        return redirect('/room_booking')

    user_id = session['user_id']
    conn = get_db_connection()

    student =conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    booking = conn.execute(
        "SELECT * FROM Bookings WHERE booking_id=?", (booking_id,)
    ).fetchone()

    if booking['payment_status'] == 'Paid':
        conn.close()
        flash('Paid bookings cannot be deleted. Please contact admin.', 'warning')
        return redirect(url_for('room_booking'))

    if booking['payment_status'] == 'Unpaid':
        conn.close()
        flash('Unpaid Bookings or bookings with outstanding payment cannot be deleted. Please contact admin.', 'warning')
        return redirect(url_for('room_booking'))


    if not booking:
        conn.close()
        flash('Booking not found.', 'danger')
        return redirect(url_for('room_booking'))

    conn.execute("DELETE FROM Payment WHERE booking_id=?", (booking_id,))
    conn.execute("DELETE FROM Bookings WHERE booking_id=?", (booking_id,))
    conn.commit()

    conn.commit()
    conn.close()

    flash('Your booking has been deleted.', 'success')
    return redirect(url_for('room_booking'))




@app.route('/admin_reports')
def admin_reports():

    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()

    # Total collected payments
    total_paid = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM Payment
        WHERE payment_status = 'Paid'
    """).fetchone()[0]

    # Outstanding payments
    outstanding = conn.execute("""
        SELECT COALESCE(SUM(total_payment), 0)
        FROM Bookings
        WHERE payment_status = 'Unpaid'
    """).fetchone()[0]

    # Total fines (pending/unpaid only)
    total_fines = conn.execute("""
            SELECT COALESCE(SUM(amount), 0)
            FROM Fine
            WHERE fine_status = 'pending'
        """).fetchone()[0]

    # Bed statistics
    bed_stats = conn.execute("""
        SELECT
            COALESCE(SUM(bed_capacity), 0) AS total_beds,
            COALESCE(SUM(available_beds), 0) AS available_beds
        FROM Rooms
    """).fetchone()

    total_beds = bed_stats["total_beds"]
    available_beds = bed_stats["available_beds"]
    occupied_beds = total_beds - available_beds

    occupancy_rate = round(
        (occupied_beds / total_beds) * 100, 1
    ) if total_beds else 0

    # Monthly payment collection
    payment_rows = conn.execute("""
        SELECT
            strftime('%m', payment_date) AS month,
            SUM(amount) AS total
        FROM Payment
        WHERE payment_status = 'Paid'
        GROUP BY strftime('%m', payment_date)
        ORDER BY month
    """).fetchall()

    conn.close()

    month_map = {
        '01': 'Jan',
        '02': 'Feb',
        '03': 'Mar',
        '04': 'Apr',
        '05': 'May',
        '06': 'Jun',
        '07': 'Jul',
        '08': 'Aug',
        '09': 'Sep',
        '10': 'Oct',
        '11': 'Nov',
        '12': 'Dec'
    }

    months = []
    payment_amounts = []

    for row in payment_rows:
        months.append(month_map.get(row["month"]))
        payment_amounts.append(row["total"])

    return render_template(
        'admin_reports.html',
        total_paid=round(total_paid, 2),
        outstanding=round(outstanding, 2),
        total_fines=round(total_fines, 2),

        # Bed occupancy data
        total_beds=total_beds,
        occupied_beds=occupied_beds,
        available_beds=available_beds,
        occupancy_rate=occupancy_rate,

        # Payment chart
        months=months,
        payment_amounts=payment_amounts)





# ==========================
# MANAGE BOOKINGS  (admin)
# ==========================
@app.route('/manage_booking')
def manage_booking():
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()
    bookings = conn.execute("""
    SELECT a.booking_id, a.student_name, a.start_date, a.end_date, c.gender,
    b.room_number, a.booking_status, a.payment_status, b.room_id, b.room_type, b.bed_capacity, b.available_beds,
    b.price_per_month, b.room_details, b.room_status, b.gender AS room_gender
    FROM Bookings a
    JOIN Rooms b ON a.room_id= b.room_id
    JOIN Students c ON a.student_id= c.student_id
    ORDER BY booking_id DESC;
        """).fetchall()
    conn.close()

    return render_template('manage_booking.html', bookings=bookings)


@app.route('/approve_booking/<int:booking_id>', methods=['POST'])
def approve_booking(booking_id):
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()

    booking = conn.execute(
        "SELECT room_id, student_id FROM Bookings WHERE booking_id=?", (booking_id,)
    ).fetchone()

    if booking:
        room_id = booking['room_id']

        conn.execute(
            "UPDATE Bookings SET booking_status='Approved' WHERE booking_id=?", (booking_id,)
        )

        add_notification(
            conn, booking['student_id'],
            "Your booking has been approved.",
            'success'
        )

        room = conn.execute(
            "SELECT bed_capacity, available_beds FROM Rooms WHERE room_id=?", (room_id,)
        ).fetchone()

        new_available = max(0, room['available_beds'] - 1)
        conn.execute(
            "UPDATE Rooms SET available_beds=? WHERE room_id=?", (new_available, room_id)
        )


        if new_available == 0:
            conn.execute("UPDATE Rooms SET room_status='Occupied' WHERE room_id=?", (room_id,))
        else:
            conn.execute("UPDATE Rooms SET room_status='Available' WHERE room_id=?", (room_id,))


        conn.commit()

    conn.close()
    return redirect(url_for('manage_booking'))


@app.route('/reject_booking/<int:booking_id>', methods=['POST'])
def reject_booking(booking_id):
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()
    booking = conn.execute(
        "SELECT student_id FROM Bookings WHERE booking_id=?", (booking_id,)
    ).fetchone()

    conn.execute(
        "UPDATE Bookings SET booking_status='Rejected' WHERE booking_id=?", (booking_id,)
    )

    if booking:
        add_notification(
            conn, booking['student_id'],
            "Your room booking request has been rejected.",
            'danger'
        )
    conn.commit()
    conn.close()
    return redirect(url_for('manage_booking'))

@app.route('/delete_booking/<int:booking_id>', methods=['POST'])
def delete_booking(booking_id):
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()

    booking = conn.execute("""
        SELECT room_id, booking_status, payment_status, end_date
        FROM Bookings WHERE booking_id=?
    """, (booking_id,)).fetchone()

    if not booking:
        conn.close()
        flash('Booking not found.', 'danger')
        return redirect(url_for('manage_booking'))

    today = datetime.now().strftime('%Y-%m-%d')

    # Rule 1: rejected bookings can always be deleted (they're dead records)
    if booking['booking_status'] != 'Rejected':

        # Rule 2: unpaid bookings cannot be deleted
        if booking['payment_status'] != 'Paid':
            conn.close()
            flash('Cannot delete this booking — payment is still unpaid. Resolve payment first.', 'danger')
            return redirect(url_for('manage_booking'))

        # Rule 3: paid bookings can only be deleted after they expire
        if booking['end_date'] >= today:
            conn.close()
            flash(f"Cannot delete this booking — it is still active until {booking['end_date']}.", 'danger')
            return redirect(url_for('manage_booking'))

    conn.execute("DELETE FROM Payment WHERE booking_id=?", (booking_id,))
    conn.execute("DELETE FROM Bookings WHERE booking_id=?", (booking_id,))
    conn.execute(
        "UPDATE Rooms SET room_status='Available' WHERE room_id=?", (booking['room_id'],)
    )

    conn.commit()
    conn.close()

    flash('Booking deleted successfully.', 'success')
    return redirect(url_for('manage_booking'))

@app.route('/download_report')
def download_report():
    # This route now only handles bed occupancy reports.
    # Payment reports are handled by /download_payment_pdf
    conn = sqlite3.connect("dbsystem.db")
    cursor = conn.cursor()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    styles = getSampleStyleSheet()
    elements = []

    cursor.execute("SELECT * FROM Rooms")
    rows = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM Rooms WHERE available_beds > 0")
    vacant_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM Rooms WHERE available_beds = 0")
    occupied_count = cursor.fetchone()[0]

    conn.close()

    report_title = "Bed Occupancy Report"
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Title'],
        fontSize=20,
        leading=20,
        alignment=TA_CENTER,
        spaceAfter=2,
        textColor=colors.black,
    )
    elements.append(Paragraph(report_title, title_style))
    elements.append(Spacer(width=1, height=40))

    total_beds = sum(room[2] for room in rows)      # Capacity
    available_beds = sum(room[3] for room in rows)  # Available beds
    occupied_beds = total_beds - available_beds

    summary_data = [
        ["Total Beds", "Occupied Beds", "Available Beds"],
        [total_beds, occupied_beds, available_beds]
    ]
    summary_table = Table(summary_data)
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.darkblue),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(width=1, height=40))

    elements.append(Paragraph("Bed Occupancy Details", styles['Heading2']))
    elements.append(Spacer(width=1, height=10))

    data = [["Room ID", "Room Number", "Capacity", "Available Beds", "Price", "Status"]]
    for room in rows:
        if room[3] == 0:
            status = "Fully Occupied"
        elif room[3] == room[2]:
            status = "Fully Available"
        else:
            status = "Partially Occupied"
        data.append([room[0], room[1], room[2], room[3], room[4], status])

    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    filename = report_title.replace(" ", "_") + ".pdf"
    return send_file(buffer, as_attachment=True, download_name=filename, mimetype='application/pdf')

# ==========================
# PAYMENT FLOW (student)
# ==========================

@app.route('/make_payment/<int:booking_id>')
def make_payment(booking_id):
    if session.get('role') != 'student':
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    booking = conn.execute("""
        SELECT
            b.booking_id    AS id,
            r.room_number   AS room_number,
            b.rent_per_month AS rent_per_month,
            b.start_date    AS start_date,
            b.end_date      AS end_date,
            b.total_payment AS total_payment,
            b.payment_status AS payment_status
        FROM Bookings b
        JOIN Rooms r ON b.room_id = r.room_id
        WHERE b.booking_id=? AND b.student_id=?
    """, (booking_id, student['student_id'] if student else None)).fetchone()

    conn.close()

    if not booking:
        flash('Booking not found.', 'danger')
        return redirect(url_for('room_booking'))

    if booking['payment_status'] == 'Paid':
        flash('This booking has already been paid.', 'success')
        return redirect(url_for('room_booking'))

    return render_template('make_payment.html', booking=booking)


@app.route('/process_payment', methods=['POST'])
def process_payment():
    if session.get('role') != 'student':
        return redirect('/login')

    booking_id     = request.form['booking_id']
    payment_method = request.form['payment_method']


    if payment_method == 'Card':
        holder_name = request.form.get('cardholder_name')
        ref_number  = request.form.get('card_number')

    elif payment_method == 'E-Wallet':
        provider    = request.form.get('ewallet_provider')
        holder_name = request.form.get('ewallet_name')
        ref_number  = request.form.get('ewallet_phone')
        payment_method = f"E-Wallet ({provider})"

    elif payment_method == 'Online Banking':
        bank        = request.form.get('bank_name')
        holder_name = request.form.get('bank_account_name')
        ref_number  = request.form.get('bank_account_number')
        payment_method = f"Online Banking ({bank})"

    else:
        flash('Invalid payment method.', 'danger')
        return redirect(url_for('room_booking'))

    conn = get_db_connection()

    booking = conn.execute("""
        SELECT b.*, r.room_number
        FROM Bookings b
        JOIN Rooms r ON b.room_id = r.room_id
        WHERE b.booking_id=?
    """, (booking_id,)).fetchone()

    if not booking:
        conn.close()
        flash('Booking not found.', 'danger')
        return redirect(url_for('room_booking'))

    room_number = booking['room_number']

    payment_date = datetime.now().strftime('%Y-%m-%d')


    conn.execute("""
        INSERT INTO Payment
        (payment_method, outstanding, payment_date, amount,
         card_holder_name, card_number, payment_status, booking_id)
        VALUES (?, 0, ?, ?, ?, ?, 'Paid', ?)
    """, (payment_method, payment_date, booking['total_payment'],
          holder_name, ref_number, booking_id))


    conn.execute("""
        UPDATE Bookings SET payment_status='Paid' WHERE booking_id=?
    """, (booking_id,))



    add_notification(
        conn,
        booking['student_id'],
        f"Payment of RM {booking['total_payment']:.2f} for Room {room_number} was successful.",
        'success'
    )

    conn.commit()
    conn.close()

    flash('Payment successful! You can download your receipt from Payment History.', 'success')
    return redirect(url_for('payment_history'))


# ==========================
# PDF RECEIPT GENERATION
# ==========================

@app.route('/download_receipt/<int:booking_id>')
def download_receipt(booking_id):
    if session.get('role') != 'student':
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    booking = conn.execute("""
        SELECT
            b.booking_id    AS id,
            r.room_number   AS room_number,
            b.rent_per_month AS rent_per_month,
            b.start_date    AS start_date,
            b.end_date      AS end_date,
            b.total_payment AS total_payment,
            b.student_name AS student_name
        FROM Bookings b
        JOIN Rooms r ON b.room_id = r.room_id
        WHERE b.booking_id=? AND b.student_id=?
    """, (booking_id, student['student_id'] if student else None)).fetchone()

    payment = conn.execute("""
        SELECT * FROM Payment WHERE booking_id=? ORDER BY payment_id DESC LIMIT 1
    """, (booking_id,)).fetchone()

    conn.close()

    if not booking or not payment:
        flash('Receipt not found.', 'danger')
        return redirect(url_for('payment_history'))

    pdf_path = generate_receipt_pdf(booking, payment)

    return send_file(pdf_path, as_attachment=True,
                     download_name=f"receipt_booking_{booking_id}.pdf")


def generate_receipt_pdf(booking, payment):

    import os
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.pdfgen import canvas

    os.makedirs('receipts', exist_ok=True)
    file_path = f"receipts/receipt_booking_{booking['id']}.pdf"

    c = canvas.Canvas(file_path, pagesize=A4)
    width, height = A4

    # Header
    c.setFillColor(colors.HexColor('#4f46e5'))
    c.rect(0, height - 30*mm, width, 30*mm, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 20)
    c.drawString(20*mm, height - 18*mm, "Hostel Management System")
    c.setFont('Helvetica', 11)
    c.drawString(20*mm, height - 25*mm, "Official Payment Receipt")

    y = height - 45*mm
    c.setFillColor(colors.black)

    c.setFont('Helvetica-Bold', 12)
    c.drawString(20*mm, y, f"Receipt No: RCP-{booking['id']:05d}")
    c.drawRightString(width - 20*mm, y, f"Date: {payment['payment_date']}")

    y -= 12*mm
    c.setStrokeColor(colors.HexColor('#e5e7eb'))
    c.line(20*mm, y, width - 20*mm, y)

    y -= 10*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawString(20*mm, y, "Booking Details")

    details = [
        ("Booking ID", f"#{booking['id']}"),
        ("Student Name", booking['student_name']),
        ("Room Number", str(booking['room_number'])),
        ("Rent per Month", f"RM {booking['rent_per_month']:.2f}"),
        ("Start Date", booking['start_date']),
        ("End Date", booking['end_date']),
    ]

    y -= 8*mm
    c.setFont('Helvetica', 10)
    for label, value in details:
        c.setFillColor(colors.HexColor('#6b7280'))
        c.drawString(20*mm, y, label)
        c.setFillColor(colors.black)
        c.drawRightString(width - 20*mm, y, str(value))
        y -= 7*mm

    y -= 5*mm
    c.setStrokeColor(colors.HexColor('#e5e7eb'))
    c.line(20*mm, y, width - 20*mm, y)

    y -= 10*mm
    c.setFont('Helvetica-Bold', 11)
    c.drawString(20*mm, y, "Payment Details")

    payment_details = [
        ("Payment Method", payment['payment_method']),
        ("Cardholder / Account Name", payment['card_holder_name'] or '-'),
        ("Payment Status", payment['payment_status']),
    ]

    y -= 8*mm
    c.setFont('Helvetica', 10)
    for label, value in payment_details:
        c.setFillColor(colors.HexColor('#6b7280'))
        c.drawString(20*mm, y, label)
        c.setFillColor(colors.black)
        c.drawRightString(width - 20*mm, y, str(value))
        y -= 7*mm

    y -= 8*mm
    c.setFillColor(colors.HexColor('#f5f3ff'))
    c.rect(20*mm, y - 5*mm, width - 40*mm, 15*mm, fill=True, stroke=False)
    c.setFillColor(colors.HexColor('#4f46e5'))
    c.setFont('Helvetica-Bold', 13)
    c.drawString(25*mm, y + 2*mm, "Total Amount Paid")
    c.drawRightString(width - 25*mm, y + 2*mm, f"RM {payment['amount']:.2f}")

    # Footer
    c.setFillColor(colors.HexColor('#9ca3af'))
    c.setFont('Helvetica', 8)
    c.drawCentredString(width / 2, 15*mm, "This is a computer-generated receipt and does not require a signature.")

    c.save()
    return file_path


@app.route('/room_graph')
def room_graph():
    import io
    import sqlite3
    import matplotlib
    matplotlib.use('Agg')

    import matplotlib.pyplot as plt
    from flask import send_file

    conn = sqlite3.connect("dbsystem.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT room_number, available_beds
        FROM Rooms
        ORDER BY room_id
    """)

    data = cursor.fetchall()
    conn.close()

    room_numbers = []
    available_beds = []

    for row in data:
        room_numbers.append(row[0])
        available_beds.append(row[1])

    plt.figure(figsize=(8, 5))

    bars = plt.bar(
        room_numbers,
        available_beds
    )

    plt.title("Room Availability Report")
    plt.xlabel("Room Number")
    plt.ylabel("Available Beds")

    for bar in bars:
        height = bar.get_height()

        plt.text(
            bar.get_x() + bar.get_width() / 2,
            height,  # NOTE: rest of args were cut off in image;
            str(int(height)),  # completed with standard bar-label pattern
            ha='center', va='bottom'
        )

    plt.grid(axis='y', linestyle='--')

    img = io.BytesIO()
    plt.savefig(
        img,
        format='png',
        bbox_inches='tight'
    )
    img.seek(0)
    plt.close()

    return send_file(
        img,
        mimetype='image/png'
    )


# Manage Announcements ─────────────────────────────────────

from datetime import datetime

@app.route('/manage_announcements')
def manage_announcements():
    if session.get('role') not in ['admin', 'warden']:
        return redirect(url_for('login'))

    conn = get_db_connection()

    announcements = conn.execute("""
        SELECT a.user_id, a.announcement_id, a.title, a.details, 
        a.date, u.name AS poster_name
        FROM Announcements a
        LEFT JOIN Users u ON a.user_id = u.user_id
        ORDER BY a.announcement_id DESC
    """).fetchall()

    conn.close()

    formatted = []

    for row in announcements:
        try:
            time_only = datetime.strptime(
                row["date"], "%Y-%m-%d %H:%M:%S"
            ).strftime("%d %b %Y, %H:%M")
        except:
            time_only = row["date"]

        formatted.append({
            "announcement_id": row["announcement_id"],
            "title": row["title"],
            "details": row["details"],
            "date": row["date"],
            "time_only": time_only,
            "poster_name": row["poster_name"]
        })

    return render_template(
        'manage_announcements.html',
        announcements=formatted
    )


# Add Announcement ────────────────────────────────────────

@app.route('/add_announcement', methods=['POST'])
def add_announcement():
    if session.get('role') != 'warden':
        return redirect(url_for('login'))

    title = request.form['title']
    details = request.form['message']
    date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()

    conn.execute("""
        INSERT INTO Announcements
        (title, details, date, user_id)
        VALUES (?, ?, ?, ?)
    """, (title, details, date, session.get('user_id')))

    conn.commit()
    conn.close()

    flash("Announcement posted successfully!", category="success")
    return redirect(url_for('manage_announcements'))


# Delete Announcement ─────────────────────────────────────────────

@app.route('/delete_announcement/<int:announcement_id>')
def delete_announcement(announcement_id):
    if session.get('role') not in ['admin', 'warden']:
        return redirect('/login')

    conn = get_db_connection()

    conn.execute("""
        DELETE FROM Announcements
        WHERE announcement_id = ?
    """, (announcement_id,))

    conn.commit()
    conn.close()

    flash("Announcement deleted successfully!", category="danger")

    return redirect('/manage_announcements')


# Student Announcements ───────────────────────────────────────────

@app.route('/student_announcements')
def student_announcements():
    if session.get('role') != 'student':
        return redirect('/login')

    conn = get_db_connection()

    announcements = conn.execute("""
        SELECT *
        FROM Announcements
        ORDER BY announcement_id DESC
        
    """).fetchall()

    conn.close()

    return render_template(
        'student_announcements.html',
        announcements=announcements
    )



# Reports ─────────────────────────────────────────────────────────

@app.route('/reports')
def reports():
    conn = sqlite3.connect("dbsystem.db")
    cursor = conn.cursor()

    report_type = request.args.get("filter", "all")

    if report_type == "vacant":
        cursor.execute("""
            SELECT * FROM Rooms
            WHERE available_beds > 0
        """)

    elif report_type == "occupied":
        cursor.execute("""
            SELECT * FROM Rooms
            WHERE available_beds = 0
        """)

    else:
        cursor.execute("""
            SELECT * FROM Rooms
        """)

    rooms = cursor.fetchall()

    cursor.execute("""
        SELECT COUNT(*)
        FROM Rooms
        WHERE available_beds > 0
    """)
    vacant_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*)
        FROM Rooms
        WHERE available_beds = 0
    """)
    occupied_count = cursor.fetchone()[0]

    conn.close()

    return render_template(
        'reports.html',
        rooms=rooms,
        vacant_count=vacant_count,
        occupied_count=occupied_count
    )

#Download Report ──────────────────────────────────────────────



# Payment Report ────────────────────────────────────────────────

@app.route('/payment_report')
def payment_report():

    conn = sqlite3.connect("dbsystem.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Payment Received
    cursor.execute("""
        SELECT
            payment_id,
            booking_id,
            payment_date,
            amount,
            card_holder_name
        FROM Payment
        WHERE payment_status='Paid'
    """)

    paid_payments = cursor.fetchall()

    # Get Booking payment information
    cursor.execute("""
        SELECT
            b.booking_id,
            b.student_name,
            r.room_number,
            b.total_payment,

            IFNULL(
                (
                    SELECT SUM(p.amount)
                    FROM Payment p
                    WHERE p.booking_id = b.booking_id
                ),
                0
            ) AS PaidAmount

        FROM Bookings b
        LEFT JOIN Rooms r ON b.room_id = r.room_id
    """)

    payment_records = cursor.fetchall()

    # Outstanding Payments
    outstanding_payments = []

    for record in payment_records:

        booking_id = record[0]
        student_name = record[1]
        room_number = record[2]
        total_payment = record[3]
        paid_amount = record[4]

        balance = total_payment - paid_amount

        if balance > 0:

            outstanding_payments.append(
                (
                    booking_id,
                    student_name,
                    room_number,
                    total_payment,
                    paid_amount,
                    balance
                )
            )

    # Total Received
    cursor.execute("""
        SELECT IFNULL(SUM(amount), 0)
        FROM Payment
        WHERE payment_status='Paid'
    """)

    total_received = cursor.fetchone()[0]

    # Total Outstanding
    total_outstanding = 0

    for payment in outstanding_payments:
        total_outstanding += payment[5]

    conn.close()

    return render_template(
        'payment_report.html',
        paid_payments=paid_payments,
        outstanding_payments=outstanding_payments,
        total_received=total_received,
        total_outstanding=total_outstanding
    )




# ==========================
# ROOM MANAGEMENT  (admin)
# ==========================

@app.route('/admin_rooms')
def admin_rooms():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()
    rooms = conn.execute("SELECT * FROM Rooms WHERE is_deleted=0 ORDER BY room_id DESC").fetchall()
    conn.close()

    return render_template('admin_rooms.html', rooms=rooms)


@app.route('/add_room', methods=['GET', 'POST'])
def add_room():
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()


    if request.method == 'POST':
       # room_id = request.form['room_id']
        room_number    = request.form['room_number'].strip()
        room_type      = request.form['room_type']
        gender         = request.form['gender']
        bed_capacity   = int(request.form['bed_capacity'])
        available_beds = int(request.form['available_beds'])
        price          = float(request.form['price_per_month'])
        room_details   = request.form['room_details'].strip()
        status         = request.form['room_status']

        if available_beds > bed_capacity:
            flash("Available beds cannot be greater than bed capacity.", "danger")
            conn.close()
            return redirect(url_for('add_room'))

        existing = conn.execute("""
                SELECT room_id
                FROM Rooms
                WHERE room_number=? 
            """, (room_number,)).fetchone()

        if existing:
            flash("Room number already exists.", "danger")
            conn.close()
            return redirect(url_for('add_room'))

        conn = get_db_connection()
        conn.execute("""
            INSERT INTO Rooms
            (room_number, bed_capacity, available_beds, price_per_month, room_details, gender, room_type, room_status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (room_number, bed_capacity, available_beds, price, room_details, gender, room_type, status))
        conn.commit()
        conn.close()

        flash('Room added successfully!', 'success')
        return redirect(url_for('admin_rooms'))


    return render_template('room_form.html', room=None)


@app.route('/edit_room/<int:room_id>', methods=['GET', 'POST'])
def edit_room(room_id):
    if session.get('role') != 'admin':
        return redirect(url_for('login'))

    conn = get_db_connection()

    if request.method == 'POST':
        room_number    = request.form['room_number'].strip()
        room_type      = request.form['room_type']
        gender         = request.form['gender']
        bed_capacity   = int(request.form['bed_capacity'])
        available_beds = int(request.form['available_beds'])
        price          = float(request.form['price_per_month'])

        room_details   = request.form['room_details'].strip()
        status         = request.form['room_status']

        if available_beds > bed_capacity:
            flash("Available beds cannot be greater than bed capacity.", "danger")
            conn.close()
            return redirect(url_for('edit_room', room_id=room_id))

        existing = conn.execute("""
                SELECT room_id
                FROM Rooms
                WHERE room_number=? AND room_id!=?
            """, (room_number, room_id)).fetchone()

        if existing:
            flash("Room number already exists.", "danger")
            conn.close()
            return redirect(url_for('edit_room', room_id=room_id))

        conn.execute("""
            UPDATE Rooms
            SET room_number=?, bed_capacity=?, available_beds=?,
                price_per_month=?, room_details=?, gender=?,
                room_type=?, room_status=?
            WHERE room_id=?
        """, (room_number, bed_capacity, available_beds, price,
              room_details, gender, room_type, status, room_id))
        conn.commit()
        conn.close()

        flash('Room updated successfully!', 'success')
        return redirect(url_for('admin_rooms'))

    room = conn.execute("SELECT * FROM Rooms WHERE room_id=?", (room_id,)).fetchone()
    conn.close()

    if not room:
        flash('Room not found.', 'danger')
        return redirect(url_for('admin_rooms'))


    return render_template('room_form.html', room=room)


@app.route('/delete_room/<int:room_id>', methods=['POST'])
def delete_room(room_id):
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()

    room = conn.execute(
        "SELECT * FROM Rooms WHERE room_id=?", (room_id,)
    ).fetchone()

    if not room:
        conn.close()
        flash('Room not found.', 'danger')
        return redirect(url_for('admin_rooms'))

    # Rule: every bed must be free
    if room['available_beds'] != room['bed_capacity']:
        occupied = room['bed_capacity'] - room['available_beds']
        conn.close()
        flash(f"Cannot delete Room {room['room_number']} — {occupied} student(s) "
              f"are still staying in it. The room must be completely empty.", 'danger')
        return redirect(url_for('admin_rooms'))

    # Safety net: no active/pending bookings either
    today = datetime.now().strftime('%Y-%m-%d')
    active = conn.execute("""
        SELECT COUNT(*) AS cnt FROM Bookings
        WHERE room_id=?
          AND booking_status IN ('Pending', 'Approved')
          AND end_date >= ?
    """, (room_id, today)).fetchone()['cnt']

    if active > 0:
        conn.close()
        flash(f"Cannot delete Room {room['room_number']} — it still has active "
              f"or pending bookings.", 'danger')
        return redirect(url_for('admin_rooms'))

    # Soft delete: hide the room, keep all history
    conn.execute("UPDATE Rooms SET is_deleted=1 WHERE room_id=?", (room_id,))
    conn.commit()
    conn.close()

    flash(f"Room {room['room_number']} deleted. Past booking history is preserved.", 'success')
    return redirect(url_for('admin_rooms'))


@app.route('/download_payment_pdf')
def download_payment_pdf():
    """Download payment report as PDF"""

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.platypus import Table, TableStyle, Paragraph, Spacer, SimpleDocTemplate
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from io import BytesIO
    from datetime import datetime

    if session.get('role') not in ('admin', 'warden'):
        return redirect(url_for('login'))

    conn = get_db_connection()

    # ---- Payments ----
    # Join Fine -> Students -> Users so fine-only payments (booking_id NULL) show a student name
    # payment_type distinguishes booking payments from fine payments for display
    # student_name is always pulled live from Users (via the booking's or fine's
    # student_id) rather than from Bookings.student_name, which is just a
    # snapshot taken at booking time and goes stale if the student edits their
    # profile name afterward. b.student_name is kept only as a last-resort
    # fallback in case a student record was deleted.
    payments = conn.execute("""
        SELECT
            p.payment_id,
            p.payment_method,
            p.payment_date,
            p.amount,
            p.payment_status,
            COALESCE(bu.name, fu.name, b.student_name) AS student_name,
            r.room_number,
            CASE WHEN p.fine_id IS NOT NULL THEN 'Fine' ELSE 'Booking' END AS payment_type
        FROM Payment p
        LEFT JOIN Bookings b ON p.booking_id = b.booking_id
        LEFT JOIN Rooms r ON b.room_id = r.room_id
        LEFT JOIN Students bs ON b.student_id = bs.student_id
        LEFT JOIN Users bu ON bs.user_id = bu.user_id
        LEFT JOIN Fine f ON p.fine_id = f.fine_id
        LEFT JOIN Students fs ON f.student_id = fs.student_id
        LEFT JOIN Users fu ON fs.user_id = fu.user_id
        ORDER BY p.payment_date ASC
    """).fetchall()

    total_amount = sum(p['amount'] for p in payments if p['payment_status'] == 'Paid')

    # ---- Booking + overdue ----
    booking_records = conn.execute("""
        SELECT
            b.booking_id,
            b.student_id,
            COALESCE(u.name, b.student_name) AS student_name,
            r.room_number,
            b.total_payment,
            IFNULL(
                (SELECT SUM(p.amount)
                 FROM Payment p
                 WHERE p.booking_id = b.booking_id
                   AND p.payment_status = 'Paid'),
                0
            ) AS paid_amount
        FROM Bookings b
        LEFT JOIN Rooms r ON b.room_id = r.room_id
        LEFT JOIN Students s ON b.student_id = s.student_id
        LEFT JOIN Users u ON s.user_id = u.user_id
    """).fetchall()

    overdue_payments = []

    for rec in booking_records:
        balance = rec['total_payment'] - rec['paid_amount']

        if balance > 0:
            fines = conn.execute("""
                SELECT amount, reason, fine_status
                FROM Fine
                WHERE student_id = ?
                  AND fine_status = 'pending'
            """, (rec['student_id'],)).fetchall()

            fine_total = sum(f['amount'] for f in fines)
            fine_reasons = '; '.join(
                f"{f['reason']} ({f['fine_status']})" for f in fines
            ) if fines else 'None'

            overdue_payments.append({
                'booking_id': rec['booking_id'],
                'student_name': rec['student_name'] or 'N/A',
                'room_number': rec['room_number'] or 'N/A',
                'total': rec['total_payment'],
                'paid': rec['paid_amount'],
                'balance': balance,
                'fine_total': fine_total,
                'fine_reasons': fine_reasons,
                'total_owed': balance + fine_total
            })

    total_overdue = sum(o['balance'] for o in overdue_payments)
    total_fines = sum(o['fine_total'] for o in overdue_payments)

    conn.close()

    # ---- PDF ----
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4))
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        'Title',
        parent=styles['Heading1'],
        fontSize=20,
        alignment=1,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=30
    )

    # Style used for wrapping text inside table cells so long values
    # (names, methods, etc.) wrap onto multiple lines instead of
    # overflowing past the column border.
    cell_style = ParagraphStyle(
        'CellText',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        alignment=1,  # center
    )

    header_cell_style = ParagraphStyle(
        'HeaderCellText',
        parent=cell_style,
        textColor=colors.white,
        fontName='Helvetica-Bold',
    )

    def cell(value):
        """Wrap a value in a Paragraph so it wraps instead of overflowing."""
        return Paragraph(str(value), cell_style)

    story.append(Paragraph("Payment Report", title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles['Normal']))
    story.append(Paragraph(f"Total Revenue: RM {total_amount:,.2f}", styles['Normal']))
    story.append(Paragraph(f"Total Outstanding: RM {total_overdue:,.2f}", styles['Normal']))
    story.append(Paragraph(f"Total Fines: RM {total_fines:,.2f}", styles['Normal']))
    story.append(Spacer(1, 15))

    # ---- Payments Table ----
    story.append(Paragraph("Payments Received", styles['Heading2']))
    story.append(Spacer(1, 10))

    table_data = [[
        Paragraph(h, header_cell_style) for h in
        ['Payment ID', 'Student', 'Room/Type', 'Amount', 'Method', 'Date', 'Status']
    ]]

    for p in payments:
        if p['room_number']:
            room_or_type = p['room_number']
        elif p['payment_type'] == 'Fine':
            room_or_type = 'Fine Payment'
        else:
            room_or_type = 'N/A'

        table_data.append([
            cell(p['payment_id']),
            cell(p['student_name'] or 'N/A'),
            cell(room_or_type),
            cell(f"RM {p['amount']:.2f}"),
            cell(p['payment_method']),
            cell(p['payment_date']),
            cell(p['payment_status']),
        ])

    table = Table(table_data, colWidths=[
        0.9 * inch, 1.6 * inch, 1.1 * inch,
        1.1 * inch, 1.7 * inch, 1.2 * inch, 1.0 * inch
    ], repeatRows=1)

    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2c7cde")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('BACKGROUND', (0, 1), (-1, -1), colors.lightcyan),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))

    story.append(table)

    # ---- Outstandings and Fines Table ----
    if overdue_payments:
        story.append(Spacer(1, 20))
        story.append(Paragraph("Outstandings and Fines", styles['Heading2']))
        story.append(Spacer(1, 10))

        overdue_data = [[
            Paragraph(h, header_cell_style) for h in
            ['Booking ID', 'Student', 'Room', 'Balance', 'Fine', 'Total Owed']
        ]]

        for o in overdue_payments:
            fine_display = f"RM {o['fine_total']:.2f}" if o['fine_total'] > 0 else "-"
            overdue_data.append([
                cell(o['booking_id']),
                cell(o['student_name']),
                cell(o['room_number']),
                cell(f"RM {o['balance']:.2f}"),
                cell(fine_display),
                cell(f"RM {o['total_owed']:.2f}"),
            ])

        overdue_table = Table(overdue_data, colWidths=[
            1.0 * inch, 2.0 * inch, 1.1 * inch,
            1.1 * inch, 1.0 * inch, 1.3 * inch
        ], repeatRows=1)

        overdue_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.red),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, 1), (-1, -1), colors.lightpink),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ]))

        story.append(overdue_table)

    doc.build(story)
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype='application/pdf',
        download_name=f'payment_report_{datetime.now().strftime("%Y%m%d")}.pdf',
        as_attachment=True
    )



@app.route('/student/announcements/search')
def search_announcements():
    """Search announcements by title for students"""
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    title = request.args.get('title', '').strip()

    conn = get_db_connection()

    if title:
        announcements = conn.execute("""
            SELECT title, details, date
            FROM Announcements
            WHERE title LIKE ?
            ORDER BY date DESC
        """, (f'%{title}%',)).fetchall()
    else:
        announcements = conn.execute("""
            SELECT title, details, date
            FROM Announcements
            ORDER BY date DESC
        """).fetchall()

    conn.close()

    return render_template('student_announcements.html',
                           announcements=announcements,
                           search_term=title)



# ==========================
# MAINTENANCE  (student)
# ==========================
@app.route('/maintenance_request')
def maintenance_request():
    if session.get('role') != 'student':
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Get student_id
    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    room_number = 'N/A'
    my_requests = []
    can_submit = False
    payment_message = None
    booking = None

    if student:
        student_id = student['student_id']

        booking = conn.execute("""
            SELECT b.booking_id, r.room_number, b.payment_status
            FROM Bookings b
            JOIN Rooms r ON b.room_id = r.room_id
            WHERE b.student_id=? AND b.booking_status='Approved'
            ORDER BY b.booking_id DESC LIMIT 1
        """, (student_id,)).fetchone()

        if booking:
            room_number = booking['room_number']
            if booking['payment_status'] == 'Paid':
                can_submit = True
            else:
                payment_message = ('You need to complete payment for your '
                                   'room before submitting a maintenance request.')

            # If no approved booking, check pending bookings
        if not booking or room_number == 'N/A':
            pending_booking = conn.execute("""
                      SELECT r.room_number
                      FROM Bookings b
                      JOIN Rooms r ON b.room_id = r.room_id
                      WHERE b.student_id=? AND b.booking_status='Pending'
                      ORDER BY b.booking_id DESC LIMIT 1
                  """, (student_id,)).fetchone()

            if pending_booking:
                room_number = pending_booking['room_number']
                payment_message = 'Your booking is still pending approval, so you cannot submit a maintenance request yet.'

        if room_number != 'N/A':
           my_requests = conn.execute("""
            SELECT request_id as id, request_id,description, request_date as report_date, maintenance_status, image_filename
            FROM MaintenanceRequests
            WHERE student_id=?
            ORDER BY request_id DESC
        """, (student_id,)).fetchall()



    conn.close()
    booking_id = booking['booking_id'] if booking else None
    return render_template('maintenance_request.html',
                           room_number=room_number,
                           my_requests=my_requests,
                           can_submit=can_submit,
                           payment_message=payment_message,
                           booking_id=booking_id
                           )

@app.route('/delete_maintenance/<int:request_id>', methods=['POST'])
def delete_maintenance(request_id):
    if session.get('role') != 'student':
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    if not student:
        conn.close()
        flash('Student record not found.', 'danger')
        return redirect('/maintenance_request')

    student_id = student['student_id']

    # Only allow deleting your own request
    request_row = conn.execute(
        "SELECT student_id FROM MaintenanceRequests WHERE request_id=?", (request_id,)
    ).fetchone()

    if not request_row or request_row['student_id'] != student_id:
        conn.close()
        flash('Request not found.', 'danger')
        return redirect('/maintenance_request')

    conn.execute("DELETE FROM MaintenanceRequests WHERE request_id=?", (request_id,))
    conn.commit()
    conn.close()

    flash('Maintenance request deleted.', 'success')
    return redirect('/maintenance_request')

@app.route('/submit_maintenance', methods=['POST'])
def submit_maintenance():
    if session.get('role') != 'student':
        return redirect('/login')

    user_id     = session['user_id']
    description = request.form['description']
    category    = request.form.get('category')
    priority = CATEGORY_PRIORITY.get(category, 'Low')


    conn = get_db_connection()


    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    if not student:
        conn.close()
        flash('Student record not found.', 'danger')
        return redirect('/maintenance_request')

    student_id = student['student_id']

    booking = conn.execute("""
        SELECT room_id, payment_status FROM Bookings
        WHERE student_id=? AND booking_status='Approved'
        ORDER BY booking_id DESC LIMIT 1
    """, (student_id,)).fetchone()

    if not booking or booking['payment_status'] != 'Paid':
        conn.close()
        flash('You need to complete payment for your room before submitting a maintenance request.', 'danger')
        return redirect('/maintenance_request')

    room_id = booking['room_id'] if booking else None

    photo = request.files.get('photo')
    image_filename = None

    if photo and photo.filename:
        ext = photo.filename.rsplit('.', 1)[-1].lower() if '.' in photo.filename else ''
        if ext in ALLOWED_IMAGE_EXT:

            stamp = datetime.now().strftime('%Y%m%d%H%M%S')
            image_filename = secure_filename(f"maint_{student_id}_{stamp}.{ext}")
            photo.save(os.path.join(MAINT_UPLOAD_FOLDER, image_filename))
        else:
            conn.close()
            flash('Photo must be an image file (jpg, png, gif, webp).', 'danger')
            return redirect(url_for('maintenance_request'))  # adjust endpoint name

    conn.execute("""
        INSERT INTO MaintenanceRequests
        (student_id, room_id, description, category, maintenance_status, request_date, priority, image_filename)
        VALUES (?, ?, ?, ?, 'pending', ?,?,?)
    """, (student_id, room_id, description, category,
          datetime.now().strftime('%Y-%m-%d'), priority, image_filename))

    conn.commit()
    conn.close()
    flash('Maintenance request submitted successfully.', 'success')
    return redirect('/maintenance_request')

# ==========================
# MANAGE MAINTENANCE
# ==========================
@app.route('/manage_maintenance')
def manage_maintenance():
    if  session.get('role') != 'warden':
        return redirect('/login')

    conn = get_db_connection()

    search = request.args.get('q', '').strip()

    sql= ("""
        SELECT
            m.request_id  AS id,
            m.category    AS Category,
            m.description AS Description,
            m.priority,
            u.name AS student_name,
            m.request_date AS report_date,
            m.maintenance_status AS maintenance_status,
            r.room_number  AS room_number,
            m.image_filename
        FROM MaintenanceRequests m
        LEFT JOIN Rooms r ON m.room_id = r.room_id
        LEFT JOIN Students s ON m.student_id = s.student_id
        LEFT JOIN Users u   ON s.user_id   = u.user_id
        
    """)

    params=[]

    if search:
        sql += " WHERE (u.name LIKE ? OR r.room_number LIKE ?)"
        like = f"%{search}%"
        params.extend([like, like])

    sql += " ORDER BY m.request_date DESC"


    maintenance = conn.execute(sql, params).fetchall()
    conn.close()


    return render_template('manage_maintenance.html', maintenance=maintenance, search=search)

@app.route('/complete_maintenance/<int:request_id>', methods=['POST'])
def complete_maintenance(request_id):
    if  session.get('role') != 'warden':
        return redirect('/login')

    conn = get_db_connection()


    request_row = conn.execute(
        "SELECT student_id, description FROM MaintenanceRequests WHERE request_id=?", (request_id,)
    ).fetchone()

    conn.execute("""
        UPDATE MaintenanceRequests SET maintenance_status='completed' WHERE request_id=?
    """, (request_id,))


    if request_row:
        add_notification(
            conn, request_row['student_id'],
            f"Your maintenance request \"{request_row['description'][:40]}\" has been marked done.",
            'success'
        )

    conn.commit()
    conn.close()
    return redirect('/manage_maintenance')

# ==========================
# MANAGE PAYMENTS
# ==========================
@app.route('/manage_payments')
def manage_payments():
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()

    payments = conn.execute("""
        SELECT
            booking_id      AS id,
            student_name    AS student_name,
            room_number     AS room_number,
            total_payment   AS amount,
            payment_status AS status,
            end_date        AS due_date,
            0              AS fine
        FROM Bookings
        ORDER BY booking_id DESC
    """).fetchall()
    conn.close()

    return render_template('manage_payments.html', payments=payments)

@app.route('/mark_paid/<int:booking_id>', methods=['POST'])
def mark_paid(booking_id):
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()

    booking = conn.execute(
        "SELECT student_id, total_payment FROM Bookings WHERE booking_id=?", (booking_id,)
    ).fetchone()


    conn.execute(
        "UPDATE Bookings SET payment_status='Paid' WHERE booking_id=?", (booking_id,)
    )

    if booking:
        add_notification(
            conn, booking['student_id'],
            f"Your payment of RM {booking['total_payment']:.2f} has been confirmed by the warden.",
            'success'
        )

    conn.commit()
    conn.close()
    return redirect('/manage_payments')

@app.route('/issue_fine/<int:booking_id>', methods=['POST'])
def issue_fine(booking_id):
    if session.get('role') != 'warden':
        return redirect('/login')


    fine_amount = 50.00
    conn = get_db_connection()
    booking = conn.execute(
        "SELECT student_id FROM Bookings WHERE booking_id=?", (booking_id,)
    ).fetchone()

    conn.execute("""
        INSERT INTO Payment
        (payment_method, payment_date, amount, payment_status, booking_id)
        VALUES ('Fine', ?, ?, 'Unpaid', ?)
    """, (datetime.now().strftime('%Y-%m-%d'), fine_amount, booking_id))

    if booking:
        add_notification(
            conn, booking['student_id'],
            f"A fine of RM {fine_amount:.2f} has been issued to your account.",
            'warning'
        )

    conn.commit()
    conn.close()
    return redirect('/manage_payments')

@app.route('/generate_receipt/<int:booking_id>')
def generate_receipt(booking_id):
    if session.get('role') != 'admin':
        return redirect('/login')

    conn = get_db_connection()
    booking = conn.execute(
        "SELECT * FROM Bookings WHERE booking_id=?", (booking_id,)
    ).fetchone()
    conn.close()

    if not booking:
        flash('Booking not found')
        return redirect('/manage_payments')

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    p.setFont("Helvetica-Bold", 16)
    p.drawString(200, 800, "HOSTEL PAYMENT RECEIPT")
    p.setFont("Helvetica", 12)
    p.drawString(50, 760, f"Booking ID   : {booking['booking_id']}")
    p.drawString(50, 740, f"Student Name : {booking['student_name']}")
    p.drawString(50, 720, f"Room         : {booking['room_number']}")
    p.drawString(50, 700, f"Start Date   : {booking['start_date']}")
    p.drawString(50, 680, f"End Date     : {booking['end_date']}")
    p.drawString(50, 660, f"Rent/Month   : RM {booking['rent_per_month']:.2f}")
    p.drawString(50, 640, f"Total Paid   : RM {booking['total_payment']:.2f}")
    p.drawString(50, 620, f"Status       : {booking['payment_status']}")
    p.drawString(50, 580, f"Generated    : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    p.save()
    buffer.seek(0)

    return send_file(buffer, mimetype='application/pdf',
                     download_name=f'receipt_{booking_id}.pdf')

# ==========================
# PAYMENT HISTORY  (student)
# ==========================
@app.route('/payment_history')
def payment_history():
    if session.get('role') != 'student':
        return redirect('/login')

    user_id = session['user_id']
    conn = get_db_connection()

    # Get student_id
    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    payments = []
    fines =[]
    last_payment = None
    next_payment = {'amount': 0.00, 'due_date': 'N/A'}
    outstanding = 0.00

    if student:
        student_id = student['student_id']

        payments = conn.execute("""
            SELECT
                b.booking_id    AS id,
                r.room_number   AS room_number,
                b.total_payment AS amount,
                b.end_date      AS date_paid,
                b.payment_status AS payment_status,
                b.receipt_url
            FROM Bookings b
            JOIN Rooms r ON b.room_id = r.room_id
            WHERE b.student_id=?
            ORDER BY b.booking_id DESC
        """, (student_id,)).fetchall()

        fines = conn.execute("""
                    SELECT
                        pf.fine_id,
                        pf.amount,
                        pf.fine_type,
                        pf.reason,
                        pf.fine_status,
                        pf.issued_date,
                        r.room_number AS room_number
                    FROM Fine pf
                    LEFT JOIN Bookings b ON b.student_id = pf.student_id AND b.booking_status = 'Approved'
                    LEFT JOIN Rooms r ON b.room_id = r.room_id
                    WHERE pf.student_id = ?
                    ORDER BY pf.fine_id DESC
                """, (student_id,)).fetchall()

        last_payment = conn.execute("""
            SELECT total_payment AS amount, end_date AS date
            FROM Bookings
            WHERE student_id=? AND payment_status='Paid'
            ORDER BY booking_id DESC LIMIT 1
        """, (student_id,)).fetchone()

        next_payment_row = conn.execute("""
            SELECT total_payment AS amount, end_date AS due_date
            FROM Bookings
            WHERE student_id=? AND payment_status='Unpaid'
            ORDER BY booking_id ASC LIMIT 1
        """, (student_id,)).fetchone()

        if next_payment_row:
            next_payment = next_payment_row

        outstanding = conn.execute("""
            SELECT COALESCE(SUM(total_payment), 0) AS total
            FROM Bookings
            WHERE student_id=? AND payment_status='Unpaid'
        """, (student_id,)).fetchone()['total']

    conn.close()

    return render_template('payment_history.html',
                           payments=payments,
                           fines=fines,
                           last_payment=last_payment,
                           next_payment=next_payment,
                           outstanding=outstanding)

# ==========================
# PAY  (student — redirects to payment_history after marking paid)
# ==========================
@app.route('/pay/<int:booking_id>', methods=['GET', 'POST'])
def pay(booking_id):
    if session.get('role') != 'student':
        return redirect('/login')

    if request.method == 'POST':
        conn = get_db_connection()
        conn.execute(
            "UPDATE Bookings SET payment_status='Paid' WHERE booking_id=?", (booking_id,)
        )
        conn.commit()
        conn.close()
        return redirect('/payment_history')


    conn = get_db_connection()
    booking = conn.execute(
        "SELECT * FROM Bookings WHERE booking_id=?", (booking_id,)
    ).fetchone()
    conn.close()
    return render_template('payment_history.html', booking=booking)

# ==========================

# PAYMENT FINE  (admin + student)
# ==========================


@app.route('/payment_fine')
def payment_fine():
    if session.get('role') not in ('admin','warden','student'):
        return redirect(url_for('login'))

    conn = get_db_connection()

    if session.get('role') == 'warden':

        fines = conn.execute("""
            SELECT pf.fine_id, pf.amount, pf.reason, pf.fine_status,pf.fine_type, pf.issued_date,
                   u.name AS student_name,
                   r.room_number AS room_number
            FROM Fine pf
            JOIN Students s ON pf.student_id = s.student_id
            JOIN Users u ON s.user_id = u.user_id
            LEFT JOIN Bookings b ON b.student_id = s.student_id AND b.booking_status = 'Approved'
            LEFT JOIN Rooms r ON b.room_id = r.room_id
            ORDER BY pf.fine_id DESC
        """).fetchall()
    else:

        student = conn.execute(
            "SELECT student_id FROM Students WHERE user_id=?",
            (session['user_id'],)
        ).fetchone()

        fines = conn.execute("""
            SELECT pf.fine_id, pf.amount, pf.reason, pf.fine_status, pf.fine_type, pf.issued_date,
                   u.name AS student_name,
                   r.room_number AS room_number
            FROM Fine pf
            JOIN Students s ON pf.student_id = s.student_id
            JOIN Users u ON s.user_id = u.user_id
            LEFT JOIN Bookings b ON b.student_id = s.student_id AND b.booking_status = 'Approved'
            LEFT JOIN Rooms r ON b.room_id = r.room_id
            WHERE pf.student_id = ?
            ORDER BY pf.fine_id DESC
        """, (student['student_id'],)).fetchall() if student else []

    total_fines   = sum(f['amount'] for f in fines)
    pending_fines = sum(f['amount'] for f in fines if f['fine_status'] == 'pending')
    paid_fines    = sum(f['amount'] for f in fines if f['fine_status'] == 'paid')

    conn.close()

    base_template = 'base_warden.html' if session.get('role') == 'warden' else 'base_student.html'

    return render_template('payment_fine.html',
                           fines=fines,
                           total_fines=f"{total_fines:.2f}",
                           pending_fines=f"{pending_fines:.2f}",
                           paid_fines=f"{paid_fines:.2f}")



@app.route('/issue_fine_form', methods=['GET', 'POST'])
def issue_fine_form():
    if session.get('role') != 'warden':
        return redirect(url_for('login'))

    conn = get_db_connection()

    if request.method == 'POST':
        amount      = float(request.form['amount'])
        reason      = request.form['reason'].strip()
        student_id  = request.form.get('student_id')
        fine_type   = request.form['fine_type'].strip()
        issued_date = datetime.now().strftime('%Y-%m-%d')

        conn.execute("""
            INSERT INTO Fine (amount, reason, fine_status, fine_type, issued_date, student_id)
            VALUES (?, ?, 'pending', ?, ?, ?)
        """, (amount, reason, fine_type, issued_date, student_id))
        conn.commit()
        conn.close()
        return redirect(url_for('overdue_payments'))


    students = conn.execute("""
        SELECT s.student_id, u.name,
               r.room_number
        FROM Students s
        JOIN Users u ON s.user_id = u.user_id
        LEFT JOIN Bookings b ON b.student_id = s.student_id AND b.booking_status = 'Approved'
        LEFT JOIN Rooms r ON b.room_id = r.room_id
        ORDER BY u.name
    """).fetchall()
    conn.close()

    preselect_student_id = request.args.get('student_id', type=int)
    return render_template('issue_fine_form.html', students=students, preselect_student_id=preselect_student_id)






@app.route('/pay_fine/<int:fine_id>', methods=['GET'])
def pay_fine_form(fine_id):
    if session.get('role') != 'student':
        return redirect('/login')

    conn = get_db_connection()
    fine = conn.execute(
        "SELECT * FROM Fine WHERE fine_id=?", (fine_id,)
    ).fetchone()
    conn.close()

    if not fine:
        flash('Fine not found.', 'danger')
        return redirect(url_for('payment_fine'))

    if fine['fine_status'] == 'paid':
        flash('This fine has already been paid.', 'success')
        return redirect(url_for('payment_fine'))

    return render_template('pay_fine_form.html', fine=fine)


@app.route('/process_fine_payment', methods=['POST'])
def process_fine_payment():
    if session.get('role') != 'student':
        return redirect('/login')

    fine_id        = request.form['fine_id']
    payment_method = request.form['payment_method']

    if payment_method == 'Card':
        holder_name = request.form.get('cardholder_name')
        ref_number  = request.form.get('card_number')

    elif payment_method == 'E-Wallet':
        provider    = request.form.get('ewallet_provider')
        holder_name = request.form.get('ewallet_name')
        ref_number  = request.form.get('ewallet_phone')
        payment_method = f"E-Wallet ({provider})"

    elif payment_method == 'Online Banking':
        bank        = request.form.get('bank_name')
        holder_name = request.form.get('bank_account_name')
        ref_number  = request.form.get('bank_account_number')
        payment_method = f"Online Banking ({bank})"

    else:
        flash('Invalid payment method.', 'danger')
        return redirect(url_for('payment_fine'))

    conn = get_db_connection()

    fine = conn.execute(
        "SELECT * FROM Fine WHERE fine_id=?", (fine_id,)
    ).fetchone()

    if not fine:
        flash('Fine not found.', 'danger')
        conn.close()
        return redirect(url_for('payment_fine'))

    payment_date = datetime.now().strftime('%Y-%m-%d')

    conn.execute("""
        INSERT INTO Payment
        (payment_method, outstanding, payment_date, amount,
         card_holder_name, card_number, payment_status, fine_id)
        VALUES (?, 0, ?, ?, ?, ?, 'Paid', ?)
    """, (payment_method, payment_date, fine['amount'],
          holder_name, ref_number, fine_id))

    conn.execute(
        "UPDATE Fine SET fine_status='paid' WHERE fine_id=?", (fine_id,)
    )

    conn.commit()
    conn.close()

    flash('Fine payment successful!', 'success')
    return redirect(url_for('payment_history'))

# ==========================
# OVERDUE PAYMENTS  (admin + warden)
# ==========================
@app.route('/overdue_payments')
def overdue_payments():
    if session.get('role') not in ('admin','warden'):
        return redirect(url_for('login'))

    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_db_connection()

    overdue = conn.execute("""
        SELECT
            b.booking_id      AS booking_id,
            u.name           AS student_name,
            s.student_id      AS student_id,
            r.room_number     AS room_number,
            b.rent_per_month   AS rent_per_month,
            b.start_date      AS start_date,
            b.end_date        AS end_date,
            b.total_payment   AS total_payment,
            b.payment_status AS payment_status,
            CAST(julianday(?) - julianday(b.end_date) AS INTEGER) AS days_overdue
        FROM Bookings b
        JOIN Students s ON b.student_id = s.student_id
        JOIN Users u ON s.user_id = u.user_id
        JOIN Rooms r ON b.room_id = r.room_id
        WHERE b.payment_status = 'Unpaid'
          AND b.end_date < ?
        ORDER BY b.end_date ASC
    """, (today, today)).fetchall()

    total_overdue_amount = sum(o['total_payment'] for o in overdue)

    conn.close()

    return render_template('overdue_payments.html',
                           overdue=overdue,
                           total_overdue_amount=f"{total_overdue_amount:.2f}",
                           overdue_count=len(overdue))



@app.route('/edit-profile', methods=['GET', 'POST'])
def student_edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    def get_student(cursor):
        cursor.execute("""
            SELECT u.*, s.programme, s.year_of_study, s.emergency_contact, s.gender
            FROM Users u
            JOIN Students s ON u.user_id = s.user_id
            WHERE u.user_id = ?
        """, (user_id,))
        return cursor.fetchone()

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        if request.method == 'GET':
            student = get_student(cursor)
            return render_template('student_edit_profile.html', form_data={}, student=student)

        # ── POST ──
        name              = request.form.get('name', '').strip()
        phone_number      = request.form.get('phone_number', '').strip()
        programme         = request.form.get('programme', '').strip()
        year_of_study     = request.form.get('year_of_study', '').strip()
        address           = request.form.get('address', '').strip()
        emergency_contact = request.form.get('emergency_contact', '').strip()
        current_password  = request.form.get('current_password', '')
        new_password      = request.form.get('new_password', '')
        confirm_password  = request.form.get('confirm_password', '')

        student = get_student(cursor)

        form_data = {
            'name': name,
            'phone_number': phone_number,
            'programme': programme,
            'year_of_study': year_of_study,
            'address': address,
            'emergency_contact': emergency_contact,
        }

        def error(message):
            current_student = get_student(cursor)
            return render_template(
                'student_edit_profile.html',
                student=current_student,
                form_data=form_data,
                message=message,
                success=False
            )

        # 1. Required fields
        if (
                not name or
                not phone_number or
                not address or
                not programme or
                not year_of_study or
                not emergency_contact
        ):
            return error("All fields are required!")

        # 2. Name checks
        if len(name) < 2 or len(name) > 100:
            return error("Please enter a valid name!")

        if any(char.isdigit() for char in name):
            return error("Name cannot contain numbers!")


        # 4. Programme checks
        if any(char.isdigit() for char in programme):
            return error("Programme cannot contain numbers!")

        # 5. Phone number checks
        if not phone_number.isdigit():
            return error("Contact number must be numeric!")

        if not (9 <= len(phone_number) <= 11):
            return error("Contact number must be between 9 and 11 digits!")

        # 6. Emergency contact checks
        if not emergency_contact.isdigit():
            return error("Emergency contact must be numeric!")

        if not (9 <= len(emergency_contact) <= 11):
            return error("Emergency contact must be between 9 and 11 digits!")


        # 8. Optional password change — must verify current password first
        if new_password or confirm_password:
            if not current_password:
                return error("Please enter your current password to set a new one.")

            if not check_password_hash(student['password'], current_password):
                return error("Current password is incorrect.")

            if new_password != confirm_password:
                return error("Passwords do not match.")

            if len(new_password) < 6:
                return error("Password must be at least 6 characters long!")

            if not any(char.isdigit() for char in new_password):
                return error("Password must contain at least one numeric digit!")

            hashed = generate_password_hash(new_password)
            cursor.execute(
                "UPDATE Users SET password = ? WHERE user_id = ?",
                (hashed, user_id)
            )

        cursor.execute("""
            UPDATE Users SET name = ?, phone_number = ?, address = ?
            WHERE user_id = ?
        """, (name, phone_number, address, user_id))

        cursor.execute("""
            UPDATE Students SET programme = ?, year_of_study = ?, emergency_contact = ?
            WHERE user_id = ?
        """, (programme, year_of_study, emergency_contact, user_id))

        conn.commit()
        session['name'] = name

        student = get_student(cursor)
        return render_template(
            'student_edit_profile.html',
            form_data={},
            student=student,
            message="Profile updated successfully!",
            success=True
        )

    finally:
        conn.close()

# ============= Notifications ===========
def send_registration_email(student_email, student_name, approved: bool):

    login_url = f"{app.config['APP_BASE_URL']}/login"

    if approved:
        subject = "Your Hostel Registration has been Approved!"
        status_color ="#4CAF50"
        status_text = "Approved"
        message_body = (
            "Good news! Your hostel registration has been approved by the administration. "
            "You can now login in to browse rooms and book the one that catches your eyes!"
        )

    else:
        subject = "Your Hostel Registration was Not Approved"
        status_color = "#E74C3C"
        status_text = "Not Approved"
        message_body = (
            "We regret to inform you that your hostel registration was not "
            "approved at this time. Please contact the administration office "
            "for more details."
            "Hostel Management Office Number : 04-123 4567"
        )

    html_body = render_template(
        'registration_status_email.html',
        student_name=student_name,
        status_color=status_color,
        status_text=status_text,
        message_body=message_body,
        login_url=login_url
    )

    msg = Message(subject=subject, recipients=[student_email], html=html_body)
    mail.send(msg)

def add_notification(conn, student_id, message, category='info'):
    conn.execute("""
        INSERT INTO Notifications (student_id, message, category, is_read, created_at)
        VALUES (?, ?, ?, 0, ?)
    """, (student_id, message, category, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))

    notifications = conn.execute("""
        SELECT notification_id, message, category, created_at
        FROM Notifications
        WHERE student_id=? AND is_read=0
        ORDER BY notification_id DESC
    """, (student_id,)).fetchall()

@app.route('/dismiss_notification/<int:notification_id>', methods=['POST'])
def dismiss_notification(notification_id):
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    if student:
        conn.execute(
            "DELETE FROM Notifications WHERE notification_id=? AND student_id=?",
            (notification_id, student['student_id'])
        )
        conn.commit()

    conn.close()
    return redirect(request.referrer or url_for('student_dashboard'))

# ==========================================================
# AI CHATBOT  (student) — add this block to app.py
# ==========================================================

# ----------------------------------------------------------
# Static FAQ knowledge — edit this to match your actual hostel rules
# ----------------------------------------------------------
HOSTEL_FAQ = """

- Registration: Students register with their details including programme, gender,
  and date of birth. Gender and date of birth are set at registration and cannot
  be changed later in Manage Profile (contact admin if a correction is needed).
- Room types: Single (1 pax), Double (2 pax), Triple (3 pax), and Quad (4 pax).
  Rooms are gender-specific (Male/Female) and can be filtered by type, gender,
  and maximum price on the booking page. Photos of each room type are shown.
- Room booking: Students can book one room at a time via the "View/Book Rooms" page.
  A new booking cannot be made until the current one expires or is rejected.
  Start date cannot be in the past, and the end date must be after the start date.
  Rent is charged per month; partial months are rounded up to a full month.
- Booking approval: New bookings are "Pending" until the admin approves or rejects
  them. Students can delete their own booking while it is still unpaid.
- Payment: Once a booking is approved, students pay via the "Payment" page using
  Card, E-Wallet, or Online Banking. A receipt can be downloaded after payment.
  Total payment = rent per month x number of months.
- Fines: Wardens may issue fines (e.g. RM 50) for policy violations or overdue
  payments. Fines appear on the student's Payment History page, where they can
  be paid online. Each fine shows the type, reason, issued date, and amount.
- Maintenance requests: Students submit issues via "Maintenance Request" by selecting
  a category and writing a description. An optional photo of the issue can be
  uploaded. Priority (High/Medium/Low) is assigned automatically based on category.
  Maintenance requests can only be submitted after the room payment is completed.
  Students can delete a request while it is still pending. Wardens mark requests
  as done once resolved.
- Roles: Students book rooms, pay, and submit maintenance requests. Wardens manage
  maintenance, fines, and announcements. Admins manage rooms, bookings, students,
  and reports.
- Hostel office hours: Monday–Friday, 9am–5pm.
- Hostel Contact Number: 04-123 4567.
- Warden Contact Number: 04-456 7891.
- If a question is not covered here, advise the student to contact the hostel office.
"""

HOSTEL_EXAMPLES = """
Example questions and answers:

Q: Why can't I book another room?
A: You can only have one booking at a time. If your current booking is still
   pending approval or hasn't expired yet, you must wait until it is approved,
   rejected, or reaches its end date before booking a new room.

Q: Why is my booking still pending?
A: All new bookings must be approved by the admin. Once the admin approves it,
   you'll be able to make payment on the Payment page.

Q: How much do I pay if I stay 2 and a half months?
A: Rent is charged in full months, and partial months are rounded up. A stay of
   2.5 months is charged as 3 months x the room's monthly rent.

Q: Why can't I submit a maintenance request?
A: Maintenance requests can only be submitted after your room payment is
   completed. If your booking is approved but unpaid, go to the Payment page
   and pay first. If your booking is still pending approval, wait for approval.

Q: Can I cancel my booking?
A: Yes, you can delete your own booking from the booking page as long as it is
   still unpaid. Paid bookings cannot be deleted — contact the hostel office.

Q: How do I pay a fine?
A: Fines appear on your Payment History page with the reason and amount. You can
   pay them online the same way as rent (Card, E-Wallet, or Online Banking).

Q: Can I change my gender or date of birth?
A: No. Gender and date of birth are set when you register and cannot be changed
   in Manage Profile. If there is a mistake, contact the hostel office to correct it.

Q: I uploaded a photo with my maintenance request. Who sees it?
A: The warden can see your photo when reviewing maintenance requests. It helps
   them understand the issue before visiting your room.

Q: What rooms are available for female students?
A: Rooms are gender-specific. Use the Gender filter on the View/Book Rooms page
   to see Female rooms, and combine it with room type or price filters if needed.

Q: Who do I contact if my question isn't answered here?
A: Contact the hostel office (04-123 4567) during office hours, Monday–Friday
   9am–5pm, or the warden at 04-456 7891.
"""


HOSTEL_POLICIES = {
    "Booking & Rooms": [
        {"title": "Minimum Booking Charge", "desc": "Bookings for any duration under a full month are still charged at the full monthly rate. Partial-month stays are not prorated."},
        {"title": "Check-In / Check-Out Times", "desc": "Standard check-in is from 2:00 PM and check-out by 12:00 PM, unless otherwise arranged with the warden."}
    ],
    "Payment & Fines": [
        {"title": "Late Payment Fine", "desc": "Outstanding payments not settled within 2 weeks of the due date will incur a fine. The fine is reapplied every 2 weeks the balance remains unpaid."},
        {"title": "Fine Payment", "desc": "All fines must be settled through the payment portal before further bookings or requests can be made."},
        {"title": "Damage Liability", "desc": "Students are financially responsible for any damage to hostel property beyond normal wear and tear."},
    ],
    "Conduct & Safety": [
        {"title": "Guest Policy", "desc": "Overnight guests are not permitted without prior written approval from the warden."},
        {"title": "Quiet Hours", "desc": "Quiet hours are enforced from 11:00 PM to 7:00 AM daily."},
        {"title": "Prohibited Items", "desc": "Cooking appliances, candles, and other fire-hazard items are not allowed in rooms."},
        {"title": "Cleanliness", "desc": "Students are responsible for maintaining cleanliness in their rooms and shared common areas."},
        {"title": "Termination of Stay", "desc": "Repeated policy violations may result in termination of the student's hostel stay, at management's discretion."},
    ],
    "General": [
        {"title": "Maintenance Requests", "desc": "Maintenance requests can only be submitted by students with no outstanding payment balance."},
        {"title": "Emergency Contact", "desc": "Students must keep their emergency contact information up to date in their profile."},
        {"title": "Contacting Management", "desc": "For any concerns, disputes, or clarifications, students should contact their assigned warden or the hostel management admin directly."
                                                   " Hostel Contact Number : 04-123 4567"},
    ],
}

HOSTEL_POLICY_ICONS = {
    "Booking & Rooms": "fa-bed",
    "Payment & Fines": "fa-credit-card",
    "Conduct & Safety": "fa-shield-alt",
    "General": "fa-circle-info",
}

def build_policy_text():
    """Flatten HOSTEL_POLICIES into plain text for the chatbot's system prompt."""
    lines = []
    for category, items in HOSTEL_POLICIES.items():
        lines.append(f"{category}:")
        for item in items:
            lines.append(f"- {item['title']}: {item['desc']}")
    return "\n".join(lines)


# ----------------------------------------------------------
# Build a text summary of the student's own data
# ----------------------------------------------------------
def build_student_context(conn, student_id):
    booking = conn.execute("""
        SELECT b.booking_status AS Status, b.payment_status, r.room_number, b.start_date, b.end_date, b.total_payment
        FROM Bookings b
        LEFT JOIN Rooms r ON b.room_id = r.room_id
        WHERE b.student_id=?
        ORDER BY b.booking_id DESC LIMIT 1
    """, (student_id,)).fetchone()

    fines = conn.execute("""
        SELECT amount, reason, fine_status AS status, issued_date
        FROM Fine
        WHERE student_id=?
        ORDER BY fine_id DESC
    """, (student_id,)).fetchall()

    maintenance = conn.execute("""
        SELECT category AS Category, description AS Description, priority, maintenance_status AS Status, request_date
        FROM MaintenanceRequests
        WHERE student_id=?
        ORDER BY request_id DESC
    """, (student_id,)).fetchall()

    outstanding = conn.execute("""
        SELECT COALESCE(SUM(total_payment), 0) AS total
        FROM Bookings
        WHERE student_id=? AND payment_status='Unpaid'
    """, (student_id,)).fetchone()['total']

    lines = []

    if booking:
        lines.append(
            f"Current booking: Room {booking['room_number']}, status {booking['Status']}, "
            f"payment status {booking['payment_status']}, "
            f"from {booking['start_date']} to {booking['end_date']}, "
            f"total RM {booking['total_payment']:.2f}."
        )
    else:
        lines.append("No room booking on record.")

    lines.append(f"Outstanding payment owed: RM {outstanding:.2f}.")

    if fines:
        fine_lines = [
            f"RM {f['amount']:.2f} ({f['reason']}) — {f['status']}, issued {f['issued_date']}"
            for f in fines
        ]
        lines.append("Fines: " + "; ".join(fine_lines))
    else:
        lines.append("No fines on record.")

    if maintenance:
        m_lines = [
            f"{m['Category']} ({m['priority']}) — {m['Status']}, requested {m['request_date']}"
            for m in maintenance
        ]
        lines.append("Maintenance requests: " + "; ".join(m_lines))
    else:
        lines.append("No maintenance requests on record.")

    return "\n".join(lines)


# ----------------------------------------------------------
# Routes
# ----------------------------------------------------------
@app.route('/chatbot')
def chatbot():
    if session.get('role') != 'student':
        return redirect(url_for('login'))
    return render_template('chatbot.html')


@app.route('/chatbot/message', methods=['POST'])
def chatbot_message():
    if session.get('role') != 'student':
        return jsonify({'error': 'Unauthorized'}), 401

    user_message = request.json.get('message', '').strip()
    if not user_message:
        return jsonify({'error': 'Empty message'}), 400

    user_id = session['user_id']
    conn = get_db_connection()

    student = conn.execute(
        "SELECT student_id FROM Students WHERE user_id=?", (user_id,)
    ).fetchone()

    if not student:
        conn.close()
        return jsonify({'reply': "I couldn't find your student record. Please contact the warden or admin."})

    student_context = build_student_context(conn, student['student_id'])
    conn.close()

    system_prompt = f"""You are a helpful assistant for a student hostel management system.
Answer the student's question using ONLY the information below. Be concise and friendly.
If the question is unrelated to the hostel or their account, politely say you can only help
with hostel-related questions.

HOSTEL FAQ:
{HOSTEL_FAQ}

HOSTEL EXAMPLES
{HOSTEL_EXAMPLES}


THIS STUDENT'S ACCOUNT DATA:
{student_context}
"""

    system_prompt = f"""You are a helpful assistant for a student hostel management system.
    Answer the student's question using ONLY the information below. Be concise and friendly.
    If the question is unrelated to the hostel or their account, politely say you can only help
    with hostel-related questions.

    HOSTEL FAQ:
    {HOSTEL_FAQ}

    HOSTEL POLICIES:
    {build_policy_text()}
    
    HOSTEL EXAMPLES
    {HOSTEL_EXAMPLES}

    THIS STUDENT'S ACCOUNT DATA:
    {student_context}
    """

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            max_completion_tokens=512,
            temperature=0.4
        )
        reply = response.choices[0].message.content
    except Exception as e:
        print("Groq API error:", e)
        reply = "Sorry, I'm having trouble connecting right now. Please try again shortly."

    return jsonify({'reply': reply})


@app.route('/hostel_policy')
def hostel_policy():
    if session.get('role') != 'student':
        return redirect(url_for('login'))

    numbered_policies = {}
    counter = 1
    for category, items in HOSTEL_POLICIES.items():
        numbered_policies[category] = []
        for item in items:
            numbered_policies[category].append({
                'number': counter,
                'title': item['title'],
                'desc': item['desc']
            })
            counter += 1

    return render_template(
        'hostel_policy.html',
        policies=numbered_policies,
        icons=HOSTEL_POLICY_ICONS
    )


# ================= LOGOUT =================


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


print(app.url_map)

if __name__ == '__main__':
    app.run(port=5002,debug=True)