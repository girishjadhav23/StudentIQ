from datetime import datetime, date

from flask import Blueprint, abort, render_template, request, redirect, url_for
from flask_login import current_user, login_required

from extensions import db
from models.subject import Subject
from models.attendance import Attendance

attendance = Blueprint("attendance", __name__)


def _get_owned_subject_or_404(subject_id):
    subject = Subject.query.filter_by(
        id=subject_id,
        user_id=current_user.id,
    ).first()
    if subject is None:
        abort(404)
    return subject


def calculate_subject_attendance(subject_id):
    attendances = (
        Attendance.query.filter_by(subject_id=subject_id)
        .order_by(Attendance.date.desc())
        .all()
    )
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
    user_subjects = Subject.query.filter_by(user_id=user_id).all()
    if not user_subjects:
        return 0.0

    subject_ids = [s.id for s in user_subjects]
    all_attendances = Attendance.query.filter(Attendance.subject_id.in_(subject_ids)).all()

    total_classes = len(all_attendances)
    if total_classes == 0:
        return 0.0

    present_classes = sum(1 for a in all_attendances if a.status == "Present")
    return round((present_classes / total_classes) * 100, 1)


@attendance.route("/subjects/<int:subject_id>/attendance")
@login_required
def view_attendance(subject_id):
    subject = _get_owned_subject_or_404(subject_id)
    stats = calculate_subject_attendance(subject.id)
    return render_template("attendance.html", subject=subject, stats=stats)


@attendance.route("/subjects/<int:subject_id>/attendance/add", methods=["GET", "POST"])
@login_required
def add_attendance(subject_id):
    subject = _get_owned_subject_or_404(subject_id)
    error = None

    if request.method == "POST":
        date_str = request.form.get("date", "").strip()
        status = request.form.get("status", "").strip()

        if not date_str:
            error = "Date is required."
        elif status not in ("Present", "Absent"):
            error = "Status must be Present or Absent."
        else:
            try:
                record_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                error = "Invalid date format."

            if not error and record_date > date.today():
                error = "Attendance date cannot be in the future."

            if not error:
                existing = Attendance.query.filter_by(
                    subject_id=subject.id,
                    date=record_date,
                ).first()
                if existing:
                    error = "An attendance record for this date already exists."

            if not error:
                record = Attendance(
                    subject_id=subject.id,
                    date=record_date,
                    status=status,
                )
                db.session.add(record)
                db.session.commit()
                return redirect(
                    url_for("attendance.view_attendance", subject_id=subject.id)
                )

    return render_template("add_attendance.html", subject=subject, error=error)


@attendance.route(
    "/subjects/<int:subject_id>/attendance/<int:attendance_id>/delete",
    methods=["POST"],
)
@login_required
def delete_attendance(subject_id, attendance_id):
    subject = _get_owned_subject_or_404(subject_id)
    record = Attendance.query.filter_by(
        id=attendance_id,
        subject_id=subject.id,
    ).first()
    if record is None:
        abort(404)

    db.session.delete(record)
    db.session.commit()
    return redirect(url_for("attendance.view_attendance", subject_id=subject.id))
