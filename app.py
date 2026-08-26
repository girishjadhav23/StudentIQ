from flask import Flask, render_template
from config import Config
from extensions import db, login_manager
from models.user import User
from routes.auth import auth

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    app.register_blueprint(auth)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    with app.app_context():
        db.create_all()

    @app.route("/")
    def home():
        return render_template("index.html")

    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)