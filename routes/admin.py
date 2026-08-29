import secrets
import string
from functools import wraps
from flask import Blueprint, abort, render_template, redirect, url_for, request, flash
from flask_login import current_user
from werkzeug.security import generate_password_hash

from extensions import db, login_manager
from models.user import User
from models.teacher_profile import TeacherProfile
from models.department import Department

admin = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(f):
    """Reusable decorator ensuring the authenticated user has the 'admin' role."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not getattr(current_user, "is_admin", False):
            abort(403)
        return f(*args, **kwargs)
    return decorated_function


@admin.route("/dashboard")
@admin_required
def dashboard():
    return render_template("admin/dashboard.html", user=current_user)


@admin.route("/")
@admin_required
def index():
    return redirect(url_for("admin.dashboard"))


@admin.route("/add-faculty", methods=["GET", "POST"])
@admin_required
def add_faculty():
    departments = Department.query.order_by(Department.name.asc()).all()
    created_faculty = None
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        employee_id = request.form.get("employee_id", "").strip().upper()
        department_id_raw = request.form.get("department_id", "").strip()

        if not name or not email or not employee_id or not department_id_raw:
            error = "All fields are required."
            flash(error, "error")
            return render_template(
                "admin/add_faculty.html",
                departments=departments,
                error=error,
                form_data=request.form,
            ), 400

        # Validate department existence
        try:
            dept_id = int(department_id_raw)
            dept = db.session.get(Department, dept_id)
        except (ValueError, TypeError):
            dept = None

        if not dept:
            error = "Please select a valid department."
            flash(error, "error")
            return render_template(
                "admin/add_faculty.html",
                departments=departments,
                error=error,
                form_data=request.form,
            ), 400

        # Validate duplicate email
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            error = "A user with this email already exists."
            flash(error, "error")
            return render_template(
                "admin/add_faculty.html",
                departments=departments,
                error=error,
                form_data=request.form,
            ), 400

        # Validate duplicate employee_id
        existing_emp = TeacherProfile.query.filter_by(employee_id=employee_id).first()
        if existing_emp:
            error = "A faculty member with this Employee ID already exists."
            flash(error, "error")
            return render_template(
                "admin/add_faculty.html",
                departments=departments,
                error=error,
                form_data=request.form,
            ), 400

        # Generate cryptographically secure temporary password
        alphabet = string.ascii_letters + string.digits
        temp_password = "".join(secrets.choice(alphabet) for _ in range(10))
        password_hash = generate_password_hash(temp_password)

        try:
            user = User(
                name=name,
                email=email,
                password_hash=password_hash,
                role="teacher",
                must_change_password=True,
            )
            db.session.add(user)
            db.session.flush()

            profile = TeacherProfile(
                user_id=user.id,
                employee_id=employee_id,
                department_id=dept.id,
            )
            db.session.add(profile)
            db.session.commit()

            created_faculty = {
                "name": user.name,
                "email": user.email,
                "employee_id": profile.employee_id,
                "department": dept.name,
                "temp_password": temp_password,
            }
            flash(f"Faculty account for {user.name} created successfully!", "success")
        except Exception:
            db.session.rollback()
            error = "Failed to create faculty account due to a server error."
            flash(error, "error")
            return render_template(
                "admin/add_faculty.html",
                departments=departments,
                error=error,
                form_data=request.form,
            ), 500

    return render_template(
        "admin/add_faculty.html",
        departments=departments,
        created_faculty=created_faculty,
        error=error,
        form_data={},
    )
