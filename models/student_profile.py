from datetime import datetime, timezone
from extensions import db


class StudentProfile(db.Model):
    __tablename__ = "student_profile"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), unique=True, nullable=False
    )
    roll_no = db.Column(db.String(50), nullable=True)
    admission_year = db.Column(db.Integer, nullable=True)       # e.g. 2024
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id"), nullable=True
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    user = db.relationship("User", backref=db.backref("student_profile", uselist=False))
    department = db.relationship("Department", backref="students")
    enrollments = db.relationship(
        "ClassEnrollment", backref="student", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<StudentProfile user_id={self.user_id} roll={self.roll_no}>"
