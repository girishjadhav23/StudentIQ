from datetime import datetime, timezone

from extensions import db


class Subject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(50), nullable=True)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Academic context (nullable for backward compatibility with existing data)
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id"), nullable=True
    )
    semester = db.Column(db.Integer, nullable=True)             # e.g. 5

    def __repr__(self):
        return f"<Subject {self.name}>"
