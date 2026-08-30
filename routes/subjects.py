from flask import Blueprint, abort, render_template, request, redirect, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from extensions import db
from models.subject import Subject
from models.class_enrollment import ClassEnrollment
from models.teacher_assignment import TeacherAssignment
from models.teacher_profile import TeacherProfile

subjects = Blueprint("subjects", __name__)


@subjects.route("/subjects")
@login_required
def list_subjects():
    if current_user.is_admin:
        return redirect(url_for("admin.list_subjects"))

    if current_user.is_teacher:
        assignments = (
            TeacherAssignment.query
            .join(TeacherProfile, TeacherAssignment.teacher_id == TeacherProfile.id)
            .filter(TeacherProfile.user_id == current_user.id)
            .options(
                joinedload(TeacherAssignment.subject),
                joinedload(TeacherAssignment.class_section),
            )
            .all()
        )
        return render_template("subjects.html", teacher_assignments=assignments, is_teacher=True)

    # Student view: curriculum-derived subjects via ClassEnrollment & TeacherAssignment
    student_profile = getattr(current_user, "student_profile", None)
    curriculum_assignments = []
    class_section = None

    if student_profile:
        enrollment = (
            ClassEnrollment.query
            .filter_by(student_id=student_profile.id, is_active=True)
            .options(joinedload(ClassEnrollment.class_section))
            .first()
        )
        if enrollment and enrollment.class_section:
            class_section = enrollment.class_section
            curriculum_assignments = (
                TeacherAssignment.query
                .filter_by(class_section_id=class_section.id)
                .options(
                    joinedload(TeacherAssignment.subject),
                    joinedload(TeacherAssignment.teacher).joinedload(TeacherProfile.user),
                    joinedload(TeacherAssignment.class_section),
                )
                .all()
            )

    return render_template(
        "subjects.html",
        curriculum_assignments=curriculum_assignments,
        class_section=class_section,
        is_teacher=False,
    )


@subjects.route("/subjects/add", methods=["GET", "POST"])
@login_required
def add_subject():
    if current_user.is_admin:
        return redirect(url_for("admin.add_subject"))
    abort(403)


@subjects.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@login_required
def edit_subject(subject_id):
    if not current_user.is_admin:
        abort(403)
    return redirect(url_for("admin.list_subjects"))


@subjects.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@login_required
def delete_subject(subject_id):
    if not current_user.is_admin:
        abort(403)
    return redirect(url_for("admin.list_subjects"))
