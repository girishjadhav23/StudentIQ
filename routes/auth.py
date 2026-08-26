from flask import Blueprint, render_template, request, redirect, url_for
from extensions import db
from models.user import User
from werkzeug.security import generate_password_hash

auth = Blueprint("auth", __name__)


@auth.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            return "All fields are required.", 400

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            return "An account with this email already exists.", 400

        password_hash = generate_password_hash(password)

        user = User(
            name=name,
            email=email,
            password_hash=password_hash
        )

        db.session.add(user)
        db.session.commit()

        return redirect(url_for("auth.register_success"))

    return render_template("register.html")


@auth.route("/register/success")
def register_success():
    return "Registration successful!"