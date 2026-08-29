from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db, login_manager
from models.user import User
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

auth = Blueprint("auth", __name__)


@auth.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        if getattr(current_user, "must_change_password", False):
            return redirect(url_for("auth.setup_password"))
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("dashboard.dashboard_home"))
        
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("All fields are required.", "error")
            return render_template("register.html"), 400

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            flash("An account with this email already exists.", "error")
            return render_template("register.html"), 400

        password_hash = generate_password_hash(password)

        user = User(
            name=name,
            email=email,
            password_hash=password_hash,
            role="student",
        )

        db.session.add(user)
        db.session.commit()

        flash("Registration successful! Please login to your account.", "success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        if getattr(current_user, "must_change_password", False):
            return redirect(url_for("auth.setup_password"))
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("dashboard.dashboard_home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if getattr(user, "must_change_password", False):
                flash("Please establish your permanent password to activate your account.", "info")
                return redirect(url_for("auth.setup_password"))

            flash(f"Welcome back, {user.name}!", "success")
            if user.is_admin:
                return redirect(url_for("admin.dashboard"))
            return redirect(url_for("dashboard.dashboard_home"))

        flash("Invalid email or password.", "error")
        return render_template("login.html"), 401

    return render_template("login.html")


@auth.route("/setup-password", methods=["GET", "POST"])
@login_required
def setup_password():
    if not getattr(current_user, "must_change_password", False):
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("dashboard.dashboard_home"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not password or not confirm_password:
            flash("All fields are required.", "error")
            return render_template("setup_password.html"), 400

        if len(password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template("setup_password.html"), 400

        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("setup_password.html"), 400

        if check_password_hash(current_user.password_hash, password):
            flash("New password cannot be the same as the temporary password.", "error")
            return render_template("setup_password.html"), 400

        current_user.password_hash = generate_password_hash(password)
        current_user.must_change_password = False
        db.session.commit()

        flash("Password setup successful! Your account is now fully active.", "success")
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("dashboard.dashboard_home"))

    return render_template("setup_password.html")


@auth.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have logged out successfully.", "success")
    return redirect(url_for("auth.login"))