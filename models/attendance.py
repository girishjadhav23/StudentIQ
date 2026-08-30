from datetime import datetime, timezone
from extensions import db


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (
        db.UniqueConstraint(
            "student_id",
            "subject_id",
            "class_section_id",
            "date",
            name="uq_student_subject_class_date",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("student_profile.id"), nullable=False
    )
    subject_id = db.Column(
        db.Integer, db.ForeignKey("subject.id"), nullable=False
    )
    class_section_id = db.Column(
        db.Integer, db.ForeignKey("class_section.id"), nullable=False
    )
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # "Present" / "Absent"
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    student = db.relationship(
        "StudentProfile",
        backref=db.backref("attendances", lazy=True, cascade="all, delete-orphan"),
    )
    subject = db.relationship(
        "Subject",
        backref=db.backref("attendances", lazy=True, cascade="all, delete-orphan"),
    )
    class_section = db.relationship(
        "ClassSection",
        backref=db.backref("attendances", lazy=True, cascade="all, delete-orphan"),
    )

    def __repr__(self):
        return (
            f"<Attendance student_id={self.student_id} subject_id={self.subject_id} "
            f"class_section_id={self.class_section_id} date={self.date} status={self.status}>"
        )
