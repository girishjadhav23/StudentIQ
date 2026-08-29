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
    dept_count = Department.query.count()
    faculty_count = TeacherProfile.query.count()
    return render_template(
        "admin/dashboard.html",
        user=current_user,
        dept_count=dept_count,
        faculty_count=faculty_count,
    )


@admin.route("/")
@admin_required
def index():
    return redirect(url_for("admin.dashboard"))


# =========================================================================
# DEPARTMENT MANAGEMENT
# =========================================================================

@admin.route("/departments")
@admin_required
def departments():
    dept_list = Department.query.order_by(Department.name.asc()).all()
    return render_template("admin/departments.html", departments=dept_list)


@admin.route("/departments/add", methods=["GET", "POST"])
@admin_required
def add_department():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()

        if not name or not code:
            error = "Both department name and code are required."
            flash(error, "error")
            return render_template("admin/add_department.html", error=error, form_data=request.form), 400

        # Check duplicate name (case-insensitive)
        if Department.query.filter(db.func.lower(Department.name) == name.lower()).first():
            error = f"A department with name '{name}' already exists."
            flash(error, "error")
            return render_template("admin/add_department.html", error=error, form_data=request.form), 400

        # Check duplicate code (case-insensitive)
        if Department.query.filter(db.func.upper(Department.code) == code.upper()).first():
            error = f"A department with code '{code}' already exists."
            flash(error, "error")
            return render_template("admin/add_department.html", error=error, form_data=request.form), 400

        dept = Department(name=name, code=code)
        db.session.add(dept)
        db.session.commit()
        flash(f"Department '{dept.name} ({dept.code})' created successfully!", "success")
        return redirect(url_for("admin.departments"))

    return render_template("admin/add_department.html", error=error, form_data={})


@admin.route("/departments/<int:dept_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_department(dept_id):
    dept = db.session.get(Department, dept_id)
    if not dept:
        abort(404)

    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()

        if not name or not code:
            error = "Both department name and code are required."
            flash(error, "error")
            return render_template("admin/edit_department.html", department=dept, error=error, form_data=request.form), 400

        # Check duplicate name excluding self
        if Department.query.filter(db.func.lower(Department.name) == name.lower(), Department.id != dept.id).first():
            error = f"A department with name '{name}' already exists."
            flash(error, "error")
            return render_template("admin/edit_department.html", department=dept, error=error, form_data=request.form), 400

        # Check duplicate code excluding self
        if Department.query.filter(db.func.upper(Department.code) == code.upper(), Department.id != dept.id).first():
            error = f"A department with code '{code}' already exists."
            flash(error, "error")
            return render_template("admin/edit_department.html", department=dept, error=error, form_data=request.form), 400

        dept.name = name
        dept.code = code
        db.session.commit()
        flash(f"Department '{dept.name} ({dept.code})' updated successfully!", "success")
        return redirect(url_for("admin.departments"))

    return render_template("admin/edit_department.html", department=dept, error=error, form_data={"name": dept.name, "code": dept.code})


@admin.route("/departments/<int:dept_id>/delete", methods=["POST"])
@admin_required
def delete_department(dept_id):
    dept = db.session.get(Department, dept_id)
    if not dept:
        abort(404)

    # Safe deletion checks
    faculty_count = len(dept.teachers)
    subject_count = len(dept.subjects)
    section_count = len(dept.class_sections)
    student_count = len(dept.students)

    if faculty_count > 0 or subject_count > 0 or section_count > 0 or student_count > 0:
        reasons = []
        if faculty_count > 0:
            reasons.append(f"{faculty_count} faculty member(s)")
        if subject_count > 0:
            reasons.append(f"{subject_count} subject(s)")
        if section_count > 0:
            reasons.append(f"{section_count} class section(s)")
        if student_count > 0:
            reasons.append(f"{student_count} student(s)")

        flash(f"Cannot delete department '{dept.name}' because it is associated with {', '.join(reasons)}.", "error")
        return redirect(url_for("admin.departments"))

    name = dept.name
    db.session.delete(dept)
    db.session.commit()
    flash(f"Department '{name}' deleted successfully.", "success")
    return redirect(url_for("admin.departments"))


# =========================================================================
# FACULTY PROVISIONING
# =========================================================================

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
