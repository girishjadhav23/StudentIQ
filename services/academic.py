from models.teacher_assignment import TeacherAssignment
from models.teacher_profile import TeacherProfile


def is_teacher_assigned_to_subject_and_class(teacher_user_id: int, subject_id: int, class_section_id: int) -> bool:
    """Check whether a teacher (by User.id) is allocated to a subject and class section in TeacherAssignment."""
    assignment = (
        TeacherAssignment.query
        .join(TeacherProfile, TeacherAssignment.teacher_id == TeacherProfile.id)
        .filter(
            TeacherProfile.user_id == teacher_user_id,
            TeacherAssignment.subject_id == subject_id,
            TeacherAssignment.class_section_id == class_section_id,
        )
        .first()
    )
    return assignment is not None
