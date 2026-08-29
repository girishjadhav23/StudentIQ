from datetime import datetime, timezone
from extensions import db


class TeacherProfile(db.Model):
    __tablename__ = "teacher_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    employee_id = db.Column(db.String(50), unique=True, nullable=True)
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id"), nullable=True
    )
    designation = db.Column(db.String(100), nullable=True)     # e.g. "Lecturer"
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = db.relationship("User", backref=db.backref("teacher_profile", uselist=False))
    department = db.relationship("Department", backref="teachers")

    def __repr__(self):
        return f"<TeacherProfile user_id={self.user_id} emp={self.employee_id}>"
