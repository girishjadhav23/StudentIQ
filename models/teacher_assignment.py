from datetime import datetime, timezone
from extensions import db


class TeacherAssignment(db.Model):
    __tablename__ = "teacher_assignment"
    __table_args__ = (
        db.UniqueConstraint(
            "teacher_id",
            "subject_id",
            "class_section_id",
            name="uq_teacher_subject_class",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(
        db.Integer, db.ForeignKey("teacher_profile.id"), nullable=False
    )
    subject_id = db.Column(
        db.Integer, db.ForeignKey("subject.id"), nullable=False
    )
    class_section_id = db.Column(
        db.Integer, db.ForeignKey("class_section.id"), nullable=False
    )
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    teacher = db.relationship(
        "TeacherProfile",
        backref=db.backref("assignments", lazy=True, cascade="all, delete-orphan"),
    )
    subject = db.relationship(
        "Subject",
        backref=db.backref("teacher_assignments", lazy=True, cascade="all, delete-orphan"),
    )
    class_section = db.relationship(
        "ClassSection",
        backref=db.backref("teacher_assignments", lazy=True, cascade="all, delete-orphan"),
    )

    def __repr__(self):
        return (
            f"<TeacherAssignment teacher_id={self.teacher_id} "
            f"subject_id={self.subject_id} class_section_id={self.class_section_id}>"
        )
