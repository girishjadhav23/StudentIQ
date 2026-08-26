from flask import Blueprint, render_template
from flask_login import login_required, current_user

from models.subject import Subject
from routes.attendance import calculate_overall_attendance

dashboard = Blueprint("dashboard", __name__)


@dashboard.route("/dashboard")
@login_required
def dashboard_home():
    subject_count = Subject.query.filter_by(user_id=current_user.id).count()
    overall_attendance = calculate_overall_attendance(current_user.id)
    return render_template(
        "dashboard.html",
        user=current_user,
        subject_count=subject_count,
        overall_attendance=overall_attendance,
    )