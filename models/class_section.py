from datetime import datetime, timezone
from extensions import db


class ClassSection(db.Model):
    __tablename__ = "class_section"

    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(
        db.Integer, db.ForeignKey("department.id"), nullable=False
    )
    name = db.Column(db.String(100), nullable=False)          # e.g. "TY-CO-A"
    academic_year = db.Column(db.String(20), nullable=False)   # e.g. "2026-27"
    semester = db.Column(db.Integer, nullable=False)            # e.g. 5
    year_of_study = db.Column(db.Integer, nullable=False)      # e.g. 3 (Third Year)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    enrollments = db.relationship(
        "ClassEnrollment", backref="class_section", lazy=True, cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<ClassSection {self.name} sem={self.semester} year={self.academic_year}>"
