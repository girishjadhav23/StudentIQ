import secrets
import string
from functools import wraps
from flask import Blueprint, abort, render_template, redirect, url_for, request, flash
from flask_login import current_user
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash

from extensions import db, login_manager
from models.user import User
from models.teacher_profile import TeacherProfile
from models.department import Department
from models.subject import Subject
from models.class_section import ClassSection
from models.teacher_assignment import TeacherAssignment

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
    assignment_count = TeacherAssignment.query.count()
    return render_template(
        "admin/dashboard.html",
        user=current_user,
        dept_count=dept_count,
        faculty_count=faculty_count,
        assignment_count=assignment_count,
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


# =========================================================================
# TEACHER ASSIGNMENTS MANAGEMENT
# =========================================================================

@admin.route("/assignments")
@admin_required
def list_assignments():
    assignments = (
        TeacherAssignment.query
        .options(
            joinedload(TeacherAssignment.teacher).joinedload(TeacherProfile.user),
            joinedload(TeacherAssignment.teacher).joinedload(TeacherProfile.department),
            joinedload(TeacherAssignment.subject).joinedload(Subject.department),
            joinedload(TeacherAssignment.class_section).joinedload(ClassSection.department),
        )
        .order_by(TeacherAssignment.created_at.desc())
        .all()
    )
    return render_template("admin/assignments/list.html", assignments=assignments)


@admin.route("/assignments/add", methods=["GET", "POST"])
@admin_required
def add_assignment():
    teachers = (
        TeacherProfile.query
        .join(User)
        .options(
            joinedload(TeacherProfile.user),
            joinedload(TeacherProfile.department),
        )
        .order_by(User.name.asc())
        .all()
    )
    subjects = (
        Subject.query
        .options(joinedload(Subject.department))
        .order_by(Subject.name.asc())
        .all()
    )
    class_sections = (
        ClassSection.query
        .options(joinedload(ClassSection.department))
        .order_by(ClassSection.name.asc())
        .all()
    )

    error = None

    if request.method == "POST":
        teacher_id_raw = request.form.get("teacher_id", "").strip()
        subject_id_raw = request.form.get("subject_id", "").strip()
        class_section_id_raw = request.form.get("class_section_id", "").strip()

        if not teacher_id_raw or not subject_id_raw or not class_section_id_raw:
            error = "Teacher, subject, and class section are all required."
            flash(error, "error")
            return render_template(
                "admin/assignments/add.html",
                teachers=teachers,
                subjects=subjects,
                class_sections=class_sections,
                error=error,
                form_data=request.form,
            ), 400

        try:
            teacher_id = int(teacher_id_raw)
            subject_id = int(subject_id_raw)
            class_section_id = int(class_section_id_raw)
        except (ValueError, TypeError):
            error = "Invalid selection values."
            flash(error, "error")
            return render_template(
                "admin/assignments/add.html",
                teachers=teachers,
                subjects=subjects,
                class_sections=class_sections,
                error=error,
                form_data=request.form,
            ), 400

        teacher = db.session.get(TeacherProfile, teacher_id)
        subject = db.session.get(Subject, subject_id)
        class_section = db.session.get(ClassSection, class_section_id)

        if not teacher:
            error = "Selected teacher does not exist."
            flash(error, "error")
            return render_template(
                "admin/assignments/add.html",
                teachers=teachers,
                subjects=subjects,
                class_sections=class_sections,
                error=error,
                form_data=request.form,
            ), 400

        if not subject:
            error = "Selected subject does not exist."
            flash(error, "error")
            return render_template(
                "admin/assignments/add.html",
                teachers=teachers,
                subjects=subjects,
                class_sections=class_sections,
                error=error,
                form_data=request.form,
            ), 400

        if not class_section:
            error = "Selected class section does not exist."
            flash(error, "error")
            return render_template(
                "admin/assignments/add.html",
                teachers=teachers,
                subjects=subjects,
                class_sections=class_sections,
                error=error,
                form_data=request.form,
            ), 400

        existing = TeacherAssignment.query.filter_by(
            teacher_id=teacher.id,
            subject_id=subject.id,
            class_section_id=class_section.id,
        ).first()

        if existing:
            error = f"Teacher {teacher.user.name} is already assigned to {subject.name} for {class_section.name}."
            flash(error, "error")
            return render_template(
                "admin/assignments/add.html",
                teachers=teachers,
                subjects=subjects,
                class_sections=class_sections,
                error=error,
                form_data=request.form,
            ), 400

        try:
            assignment = TeacherAssignment(
                teacher_id=teacher.id,
                subject_id=subject.id,
                class_section_id=class_section.id,
            )
            db.session.add(assignment)
            db.session.commit()

            # Optional advisory warning if department mismatch
            if (
                subject.department_id
                and class_section.department_id
                and subject.department_id != class_section.department_id
            ):
                flash(
                    f"Note: Subject '{subject.name}' ({subject.department.code if subject.department else 'N/A'}) "
                    f"differs in department from Class Section '{class_section.name}' "
                    f"({class_section.department.code if class_section.department else 'N/A'}). "
                    f"Assignment created successfully.",
                    "info",
                )
            else:
                flash(
                    f"Successfully assigned {teacher.user.name} to {subject.name} for {class_section.name}.",
                    "success",
                )
            return redirect(url_for("admin.list_assignments"))
        except Exception:
            db.session.rollback()
            error = "Failed to create teacher assignment due to a database error."
            flash(error, "error")
            return render_template(
                "admin/assignments/add.html",
                teachers=teachers,
                subjects=subjects,
                class_sections=class_sections,
                error=error,
                form_data=request.form,
            ), 500

    return render_template(
        "admin/assignments/add.html",
        teachers=teachers,
        subjects=subjects,
        class_sections=class_sections,
        error=error,
        form_data={},
    )


# =========================================================================
# ADMIN SUBJECT MANAGEMENT
# =========================================================================

@admin.route("/subjects")
@admin_required
def list_subjects():
    all_subjects = (
        Subject.query
        .options(joinedload(Subject.department))
        .order_by(Subject.name.asc())
        .all()
    )
    return render_template("admin/subjects/list.html", subjects=all_subjects)


@admin.route("/subjects/add", methods=["GET", "POST"])
@admin_required
def add_subject():
    departments = Department.query.order_by(Department.name.asc()).all()
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        department_id_raw = request.form.get("department_id", "").strip()
        semester_raw = request.form.get("semester", "").strip()

        if not name:
            error = "Subject name is required."
            flash(error, "error")
            return render_template("admin/subjects/add.html", departments=departments, error=error, form_data=request.form), 400

        dept_id = None
        if department_id_raw:
            try:
                dept_id = int(department_id_raw)
                dept = db.session.get(Department, dept_id)
                if not dept:
                    error = "Selected department does not exist."
                    flash(error, "error")
                    return render_template("admin/subjects/add.html", departments=departments, error=error, form_data=request.form), 400
            except ValueError:
                error = "Invalid department."
                flash(error, "error")
                return render_template("admin/subjects/add.html", departments=departments, error=error, form_data=request.form), 400

        semester = None
        if semester_raw:
            try:
                semester = int(semester_raw)
                if semester < 1 or semester > 8:
                    error = "Semester must be between 1 and 8."
                    flash(error, "error")
                    return render_template("admin/subjects/add.html", departments=departments, error=error, form_data=request.form), 400
            except ValueError:
                error = "Invalid semester value."
                flash(error, "error")
                return render_template("admin/subjects/add.html", departments=departments, error=error, form_data=request.form), 400

        try:
            subject = Subject(
                user_id=current_user.id,
                name=name,
                code=code or None,
                department_id=dept_id,
                semester=semester,
            )
            db.session.add(subject)
            db.session.commit()
            flash(f"Subject '{subject.name}' created successfully!", "success")
            return redirect(url_for("admin.list_subjects"))
        except Exception:
            db.session.rollback()
            error = "Failed to create subject due to a database error."
            flash(error, "error")
            return render_template("admin/subjects/add.html", departments=departments, error=error, form_data=request.form), 500

    return render_template("admin/subjects/add.html", departments=departments, error=error, form_data={})

