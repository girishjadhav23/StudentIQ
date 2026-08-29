from flask import Flask, render_template, request, redirect, url_for
from flask_login import current_user
import click
from werkzeug.security import generate_password_hash
from config import Config
from extensions import db, login_manager
from models.user import User
from models.subject import Subject
from models.attendance import Attendance
from models.department import Department
from models.class_section import ClassSection
from models.student_profile import StudentProfile
from models.teacher_profile import TeacherProfile
from models.class_enrollment import ClassEnrollment
from routes.auth import auth
from routes.dashboard import dashboard
from routes.subjects import subjects
from routes.attendance import attendance
from routes.admin import admin

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(auth)
    app.register_blueprint(dashboard)
    app.register_blueprint(subjects)
    app.register_blueprint(attendance)
    app.register_blueprint(admin)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.before_request
    def check_mandatory_password_change():
        if current_user.is_authenticated and getattr(current_user, "must_change_password", False):
            allowed_endpoints = {"auth.setup_password", "auth.logout", "static"}
            if request.endpoint:
                if request.endpoint not in allowed_endpoints and not request.path.startswith("/static"):
                    return redirect(url_for("auth.setup_password"))
            elif not request.path.startswith("/static"):
                return redirect(url_for("auth.setup_password"))

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("403.html"), 403

    @app.cli.command("create-admin")
    @click.option("--name", prompt=True, default="Admin", help="Admin name")
    @click.option("--email", prompt=True, help="Admin email")
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Admin password",
    )
    def create_admin(name, email, password):
        """Create or promote a user to administrator role."""
        email = email.strip().lower()
        name = name.strip()

        if not email or not password:
            click.echo("Error: Email and password are required.")
            return

        user = User.query.filter_by(email=email).first()
        if user:
            user.role = "admin"
            if name:
                user.name = name
            user.password_hash = generate_password_hash(password)
            db.session.commit()
            click.echo(f"User '{email}' updated to admin successfully.")
        else:
            user = User(
                name=name or "Admin",
                email=email,
                password_hash=generate_password_hash(password),
                role="admin",
            )
            db.session.add(user)
            db.session.commit()
            click.echo(f"Admin user '{email}' created successfully.")

    with app.app_context():
        db.create_all()

    @app.route("/")
    def home():
        return render_template("index.html")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)