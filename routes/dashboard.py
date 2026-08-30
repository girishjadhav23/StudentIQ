from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user

from models.class_enrollment import ClassEnrollment
from models.teacher_assignment import TeacherAssignment
from models.teacher_profile import TeacherProfile
from routes.attendance import calculate_overall_attendance

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/dashboard")
@login_required
def dashboard_home():
    if current_user.is_admin:
        return redirect(url_for("admin.dashboard"))

    subject_count = 0
    overall_attendance = 0.0

    if current_user.is_teacher:
        subject_count = (
            TeacherAssignment.query
            .join(TeacherProfile, TeacherAssignment.teacher_id == TeacherProfile.id)
            .filter(TeacherProfile.user_id == current_user.id)
            .count()
        )
    else:
        student_profile = getattr(current_user, "student_profile", None)
        if student_profile:
            enrollment = ClassEnrollment.query.filter_by(student_id=student_profile.id, is_active=True).first()
            if enrollment:
                subject_count = TeacherAssignment.query.filter_by(class_section_id=enrollment.class_section_id).count()
            overall_attendance = calculate_overall_attendance(current_user.id)

    return render_template(
        "dashboard.html",
        user=current_user,
        subject_count=subject_count,
        overall_attendance=overall_attendance,
    )