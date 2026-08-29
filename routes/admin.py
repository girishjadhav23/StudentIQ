from functools import wraps
from flask import Blueprint, abort, render_template, redirect, url_for
from flask_login import current_user
from extensions import login_manager

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
