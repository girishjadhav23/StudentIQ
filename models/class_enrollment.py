from datetime import datetime, timezone
from extensions import db


class ClassEnrollment(db.Model):
    __tablename__ = "class_enrollment"
    __table_args__ = (
        db.UniqueConstraint(
            "student_id", "class_section_id", name="uq_student_class_section"
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(
        db.Integer, db.ForeignKey("student_profile.id"), nullable=False
    )
    class_section_id = db.Column(
        db.Integer, db.ForeignKey("class_section.id"), nullable=False
    )
    enrolled_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def __repr__(self):
        return f"<ClassEnrollment student={self.student_id} section={self.class_section_id}>"
