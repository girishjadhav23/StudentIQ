from datetime import datetime, date
from flask import Blueprint, abort, render_template, request, redirect, url_for, flash
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from extensions import db
from models.subject import Subject
from models.attendance import Attendance
from models.class_section import ClassSection
from models.class_enrollment import ClassEnrollment
from models.student_profile import StudentProfile
from models.teacher_profile import TeacherProfile
from models.teacher_assignment import TeacherAssignment
from services.academic import is_teacher_assigned_to_subject_and_class

attendance = Blueprint("attendance", __name__)


def calculate_subject_attendance(subject_id, student_profile_id=None):
    """Calculate attendance statistics for a subject for a specific student profile."""
    query = Attendance.query.filter_by(subject_id=subject_id)
    if student_profile_id is not None:
        query = query.filter_by(student_id=student_profile_id)
    elif current_user.is_authenticated and getattr(current_user, "is_student", False):
        student_profile = getattr(current_user, "student_profile", None)
        if student_profile:
            query = query.filter_by(student_id=student_profile.id)

    attendances = query.order_by(Attendance.date.desc()).all()
    total_classes = len(attendances)
    present_classes = sum(1 for a in attendances if a.status == "Present")
    absent_classes = sum(1 for a in attendances if a.status == "Absent")

    if total_classes == 0:
        percentage = 0.0
    else:
        percentage = round((present_classes / total_classes) * 100, 1)

    return {
        "attendances": attendances,
        "total_classes": total_classes,
        "present_classes": present_classes,
        "absent_classes": absent_classes,
        "percentage": percentage,
    }


def calculate_overall_attendance(user_id):
    """Calculate overall attendance percentage for a student user across all enrolled subjects."""
    user = db.session.get(StudentProfile, user_id)
    # Check if user_id passed is User.id or StudentProfile.id
    student_profile = None
    if user:
        student_profile = user
    else:
        student_profile = StudentProfile.query.filter_by(user_id=user_id).first()

    if not student_profile:
        return 0.0

    all_attendances = Attendance.query.filter_by(student_id=student_profile.id).all()
    total_classes = len(all_attendances)
    if total_classes == 0:
        return 0.0

    present_classes = sum(1 for a in all_attendances if a.status == "Present")
    return round((present_classes / total_classes) * 100, 1)


# =========================================================================
# STUDENT ATTENDANCE VIEW
# =========================================================================

@attendance.route("/subjects/<int:subject_id>/attendance")
@login_required
def view_attendance(subject_id):
    if current_user.is_admin:
        abort(403)

    if current_user.is_teacher:
        return redirect(url_for("attendance.teacher_dashboard"))

    # Student verification
    student_profile = getattr(current_user, "student_profile", None)
    if not student_profile:
        abort(404)

    active_enrollment = (
        ClassEnrollment.query
        .filter_by(student_id=student_profile.id, is_active=True)
        .first()
    )
    if not active_enrollment:
        abort(404)

    # Validate subject belongs to student's class section curriculum
    assigned = (
        TeacherAssignment.query
        .filter_by(class_section_id=active_enrollment.class_section_id, subject_id=subject_id)
        .first()
    )
    if not assigned:
        abort(404)

    subject = db.session.get(Subject, subject_id)
    if not subject:
        abort(404)

    stats = calculate_subject_attendance(subject.id, student_profile_id=student_profile.id)
    return render_template("attendance.html", subject=subject, stats=stats)


# =========================================================================
# TEACHER ATTENDANCE PORTAL & ROSTER MARKING
# =========================================================================

@attendance.route("/teacher/attendance")
@attendance.route("/attendance/teacher")
@login_required
def teacher_dashboard():
    if not current_user.is_teacher:
        abort(403)

    assignments = (
        TeacherAssignment.query
        .join(TeacherProfile, TeacherAssignment.teacher_id == TeacherProfile.id)
        .filter(TeacherProfile.user_id == current_user.id)
        .options(
            joinedload(TeacherAssignment.subject),
            joinedload(TeacherAssignment.class_section),
        )
        .order_by(TeacherAssignment.created_at.desc())
        .all()
    )
    return render_template("teacher_attendance.html", assignments=assignments)


@attendance.route("/subjects/<int:subject_id>/sections/<int:class_section_id>/attendance/mark", methods=["GET", "POST"])
@login_required
def mark_attendance(subject_id, class_section_id):
    # Enforce teacher role
    if not current_user.is_teacher:
        abort(403)

    # Enforce shared ownership helper (must be assigned to this subject + class section)
    if not is_teacher_assigned_to_subject_and_class(current_user.id, subject_id, class_section_id):
        abort(403)

    subject = db.session.get(Subject, subject_id)
    class_section = db.session.get(ClassSection, class_section_id)
    if not subject or not class_section:
        abort(404)

    enrollments = (
        ClassEnrollment.query
        .filter_by(class_section_id=class_section_id, is_active=True)
        .join(StudentProfile)
        .options(
            joinedload(ClassEnrollment.student).joinedload(StudentProfile.user),
        )
        .order_by(StudentProfile.roll_no.asc())
        .all()
    )

    today_str = date.today().isoformat()

    if request.method == "POST":
        date_str = request.form.get("date", "").strip()
        if not date_str:
            flash("Attendance date is required.", "error")
            return redirect(url_for("attendance.mark_attendance", subject_id=subject_id, class_section_id=class_section_id))

        try:
            record_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            flash("Invalid date format.", "error")
            return redirect(url_for("attendance.mark_attendance", subject_id=subject_id, class_section_id=class_section_id))

        if record_date > date.today():
            flash("Attendance date cannot be in the future.", "error")
            return render_template(
                "mark_attendance.html",
                subject=subject,
                class_section=class_section,
                enrollments=enrollments,
                selected_date=date_str,
                today=today_str,
                existing_records={},
            ), 400

        try:
            for enrollment in enrollments:
                student = enrollment.student
                status = request.form.get(f"status_{student.id}", "Present").strip()
                if status not in ("Present", "Absent"):
                    status = "Present"

                # Same-session correction / upsert scoped to (student, subject, class_section, date)
                existing = Attendance.query.filter_by(
                    student_id=student.id,
                    subject_id=subject.id,
                    class_section_id=class_section.id,
                    date=record_date,
                ).first()

                if existing:
                    existing.status = status
                else:
                    new_att = Attendance(
                        student_id=student.id,
                        subject_id=subject.id,
                        class_section_id=class_section.id,
                        date=record_date,
                        status=status,
                    )
                    db.session.add(new_att)

            db.session.commit()
            flash(f"Attendance for {len(enrollments)} student(s) successfully recorded for {record_date}.", "success")
            return redirect(url_for("attendance.mark_attendance", subject_id=subject_id, class_section_id=class_section_id, date=date_str))
        except Exception:
            db.session.rollback()
            flash("Failed to save attendance due to a server error.", "error")
            return render_template(
                "mark_attendance.html",
                subject=subject,
                class_section=class_section,
                enrollments=enrollments,
                selected_date=date_str,
                today=today_str,
                existing_records={},
            ), 500

    # GET request
    selected_date_str = request.args.get("date", today_str).strip()
    try:
        selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    except ValueError:
        selected_date = date.today()
        selected_date_str = today_str

    existing_attendances = (
        Attendance.query
        .filter_by(
            subject_id=subject_id,
            class_section_id=class_section_id,
            date=selected_date,
        )
        .all()
    )
    existing_records = {a.student_id: a.status for a in existing_attendances}

    return render_template(
        "mark_attendance.html",
        subject=subject,
        class_section=class_section,
        enrollments=enrollments,
        selected_date=selected_date_str,
        today=today_str,
        existing_records=existing_records,
    )
