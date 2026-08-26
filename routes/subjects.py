from flask import Blueprint, abort, render_template, request, redirect, url_for
from flask_login import current_user, login_required

from extensions import db
from models.subject import Subject

subjects = Blueprint("subjects", __name__)


def _get_owned_subject_or_404(subject_id):
    subject = Subject.query.filter_by(
        id=subject_id,
        user_id=current_user.id,
    ).first()
    if subject is None:
        abort(404)
    return subject


@subjects.route("/subjects")
@login_required
def list_subjects():
    user_subjects = (
        Subject.query.filter_by(user_id=current_user.id)
        .order_by(Subject.created_at.desc())
        .all()
    )
    return render_template("subjects.html", subjects=user_subjects)


@subjects.route("/subjects/add", methods=["GET", "POST"])
@login_required
def add_subject():
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip() or None

        if not name:
            error = "Subject name is required."
        else:
            subject = Subject(
                user_id=current_user.id,
                name=name,
                code=code,
            )
            db.session.add(subject)
            db.session.commit()
            return redirect(url_for("subjects.list_subjects"))

    return render_template("add_subject.html", error=error)


@subjects.route("/subjects/<int:subject_id>/edit", methods=["GET", "POST"])
@login_required
def edit_subject(subject_id):
    subject = _get_owned_subject_or_404(subject_id)
    error = None

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip() or None

        if not name:
            error = "Subject name is required."
        else:
            subject.name = name
            subject.code = code
            db.session.commit()
            return redirect(url_for("subjects.list_subjects"))

    return render_template("edit_subject.html", subject=subject, error=error)


@subjects.route("/subjects/<int:subject_id>/delete", methods=["POST"])
@login_required
def delete_subject(subject_id):
    subject = _get_owned_subject_or_404(subject_id)
    db.session.delete(subject)
    db.session.commit()
    return redirect(url_for("subjects.list_subjects"))
