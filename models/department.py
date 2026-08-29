from datetime import datetime, timezone
from extensions import db


class Department(db.Model):
    __tablename__ = "department"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    class_sections = db.relationship(
        "ClassSection", backref="department", lazy=True, cascade="all, delete-orphan"
    )
    subjects = db.relationship(
        "Subject", backref="department", lazy=True
    )

    def __repr__(self):
        return f"<Department {self.code} - {self.name}>"
