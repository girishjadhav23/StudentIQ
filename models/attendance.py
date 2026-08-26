from datetime import datetime, timezone
from extensions import db


class Attendance(db.Model):
    __tablename__ = "attendance"
    __table_args__ = (
        db.UniqueConstraint("subject_id", "date", name="uq_subject_date"),
    )

    id = db.Column(db.Integer, primary_key=True)
    subject_id = db.Column(db.Integer, db.ForeignKey("subject.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(20), nullable=False)
    created_at = db.Column(
        db.DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    subject = db.relationship(
        "Subject",
        backref=db.backref("attendances", lazy=True, cascade="all, delete-orphan"),
    )

    def __repr__(self):
        return f"<Attendance subject_id={self.subject_id} date={self.date} status={self.status}>"
