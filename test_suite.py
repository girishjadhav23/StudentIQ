import unittest
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from click.testing import CliRunner

from app import create_app
from extensions import db
from models.user import User
from models.subject import Subject
from models.attendance import Attendance
from models.department import Department
from models.class_section import ClassSection
from models.student_profile import StudentProfile
from models.teacher_profile import TeacherProfile
from models.class_enrollment import ClassEnrollment
from models.teacher_assignment import TeacherAssignment
from routes.attendance import calculate_subject_attendance, calculate_overall_attendance
from services.academic import is_teacher_assigned_to_subject_and_class
from unittest.mock import patch


class TestStudentIQ(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "WTF_CSRF_ENABLED": False,
        })
        self.client = self.app.test_client()

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    # =========================================================================
    # PHASE 1 TESTS: Baseline & Existing Capabilities
    # =========================================================================

    def test_01_user_model_roles_and_properties(self):
        student = User(name="Student", email="s@vvp.edu", password_hash="hash", role="student")
        teacher = User(name="Teacher", email="t@vvp.edu", password_hash="hash", role="teacher")
        admin = User(name="Admin", email="a@vvp.edu", password_hash="hash", role="admin")
        default_user = User(name="Default", email="d@vvp.edu", password_hash="hash")

        self.assertTrue(student.is_student)
        self.assertFalse(student.is_teacher)
        self.assertFalse(student.is_admin)

        self.assertTrue(teacher.is_teacher)
        self.assertFalse(teacher.is_student)
        self.assertFalse(teacher.is_admin)

        self.assertTrue(admin.is_admin)
        self.assertFalse(admin.is_student)
        self.assertFalse(admin.is_teacher)

        self.assertEqual(default_user.role, "student")
        self.assertTrue(default_user.is_student)

    def test_02_public_registration_creates_student_only(self):
        response = self.client.post(
            "/register",
            data={"name": "Girish Student", "email": "girish@vvp.edu", "password": "Pass123"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            user = User.query.filter_by(email="girish@vvp.edu").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.name, "Girish Student")
            self.assertEqual(user.role, "student")
            self.assertTrue(user.is_student)
            self.assertFalse(user.is_admin)
            self.assertTrue(check_password_hash(user.password_hash, "Pass123"))

    def test_03_registration_prevents_duplicate_email(self):
        self.client.post("/register", data={"name": "User 1", "email": "test@vvp.edu", "password": "123"})
        response = self.client.post("/register", data={"name": "User 2", "email": "test@vvp.edu", "password": "456"})
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"already exists", response.data)

    def test_04_registration_requires_all_fields(self):
        response = self.client.post("/register", data={"name": "", "email": "a@vvp.edu", "password": "123"})
        self.assertEqual(response.status_code, 400)

    def test_05_student_login_success_and_redirect(self):
        with self.app.app_context():
            user = User(name="Student", email="s@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            db.session.add(user)
            db.session.commit()

        response = self.client.post("/login", data={"email": "s@vvp.edu", "password": "pass"}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/dashboard"))

    def test_06_teacher_login_success(self):
        with self.app.app_context():
            user = User(name="Prof Charan", email="charan@vvp.edu", password_hash=generate_password_hash("teacher123"), role="teacher")
            db.session.add(user)
            db.session.commit()

        response = self.client.post("/login", data={"email": "charan@vvp.edu", "password": "teacher123"}, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Prof Charan", response.data)

    def test_07_login_fails_with_invalid_credentials(self):
        response = self.client.post("/login", data={"email": "nobody@vvp.edu", "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertIn(b"Invalid email or password", response.data)

    def test_08_logout_flow(self):
        with self.app.app_context():
            user = User(name="User", email="u@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            db.session.add(user)
            db.session.commit()

        self.client.post("/login", data={"email": "u@vvp.edu", "password": "pass"})
        response = self.client.get("/logout", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"logged out", response.data)

    def test_09_unauthenticated_dashboard_redirects_to_login(self):
        response = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_10_authenticated_student_views_dashboard(self):
        with self.app.app_context():
            user = User(name="Student View", email="sv@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            db.session.add(user)
            db.session.commit()

        self.client.post("/login", data={"email": "sv@vvp.edu", "password": "pass"})
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Welcome, Student View!", response.data)

    def test_11_subject_crud_lifecycle(self):
        with self.app.app_context():
            admin = User(name="Admin Sub", email="adm_sub@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            student = User(name="Student Sub", email="stu_sub@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            db.session.add_all([admin, student])
            db.session.commit()

        # Student cannot manually create subjects -> 403
        self.client.post("/login", data={"email": "stu_sub@vvp.edu", "password": "pass"})
        stu_add = self.client.post("/subjects/add", data={"name": "Illegal Subject"})
        self.assertEqual(stu_add.status_code, 403)
        self.client.get("/logout")

        # Admin can create subjects via admin catalog
        self.client.post("/login", data={"email": "adm_sub@vvp.edu", "password": "pass"})
        add_resp = self.client.post("/admin/subjects/add", data={"name": "Data Structures", "code": "DS-301"}, follow_redirects=True)
        self.assertEqual(add_resp.status_code, 200)
        self.assertIn(b"Data Structures", add_resp.data)

        with self.app.app_context():
            subj = Subject.query.filter_by(name="Data Structures").first()
            self.assertIsNotNone(subj)
            self.assertEqual(subj.code, "DS-301")

    def test_12_subject_ownership_isolation(self):
        with self.app.app_context():
            u1 = User(name="U1", email="u1@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u1)
            db.session.commit()
            s1 = Subject(user_id=u1.id, name="U1 Subject")
            db.session.add(s1)
            db.session.commit()
            s1_id = s1.id

        # Student cannot edit or delete subjects -> 403
        self.client.post("/login", data={"email": "u1@vvp.edu", "password": "p"})
        resp = self.client.get(f"/subjects/{s1_id}/edit")
        self.assertEqual(resp.status_code, 403)
        del_resp = self.client.post(f"/subjects/{s1_id}/delete")
        self.assertEqual(del_resp.status_code, 403)

    def test_13_attendance_logging_and_calculations(self):
        with self.app.app_context():
            dept = Department(name="Computer Engineering", code="CE")
            db.session.add(dept)
            db.session.commit()

            u = User(name="Att User", email="att@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

            sp = StudentProfile(user_id=u.id, roll_no="101", admission_year=2024, department_id=dept.id)
            cs = ClassSection(department_id=dept.id, name="SY-CE-A", academic_year="2026-27", semester=3, year_of_study=2)
            s = Subject(user_id=u.id, name="Physics", department_id=dept.id, semester=3)
            db.session.add_all([sp, cs, s])
            db.session.commit()

            d1 = date.today() - timedelta(days=2)
            d2 = date.today() - timedelta(days=1)
            att1 = Attendance(student_id=sp.id, subject_id=s.id, class_section_id=cs.id, date=d1, status="Present")
            att2 = Attendance(student_id=sp.id, subject_id=s.id, class_section_id=cs.id, date=d2, status="Absent")
            db.session.add_all([att1, att2])
            db.session.commit()

            stats = calculate_subject_attendance(s.id, student_profile_id=sp.id)
            self.assertEqual(stats["total_classes"], 2)
            self.assertEqual(stats["present_classes"], 1)
            self.assertEqual(stats["absent_classes"], 1)
            self.assertEqual(stats["percentage"], 50.0)

            overall = calculate_overall_attendance(u.id)
            self.assertEqual(overall, 50.0)

    def test_14_future_attendance_rejected(self):
        with self.app.app_context():
            admin = User(name="Admin User", email="adm_fut@vvp.edu", password_hash=generate_password_hash("p"), role="admin")
            dept = Department(name="Computer", code="CO_FUT")
            db.session.add_all([admin, dept])
            db.session.commit()

            teach = User(name="Teach Fut", email="tfut@vvp.edu", password_hash=generate_password_hash("p"), role="teacher")
            db.session.add(teach)
            db.session.commit()

            tp = TeacherProfile(user_id=teach.id, employee_id="EMP-FUT", department_id=dept.id)
            cs = ClassSection(department_id=dept.id, name="CO-FUT-A", academic_year="2026-27", semester=3, year_of_study=2)
            s = Subject(user_id=admin.id, name="Math", department_id=dept.id, semester=3)
            db.session.add_all([tp, cs, s])
            db.session.commit()

            ta = TeacherAssignment(teacher_id=tp.id, subject_id=s.id, class_section_id=cs.id)
            db.session.add(ta)
            db.session.commit()
            sid, csid = s.id, cs.id

        self.client.post("/login", data={"email": "tfut@vvp.edu", "password": "p"})
        future_date = date.today() + timedelta(days=5)
        resp = self.client.post(f"/subjects/{sid}/sections/{csid}/attendance/mark", data={"date": str(future_date)})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"cannot be in the future", resp.data)

    def test_15_duplicate_date_attendance_rejected(self):
        with self.app.app_context():
            dept = Department(name="Electronics", code="EX")
            db.session.add(dept)
            db.session.commit()

            u = User(name="Dup Att", email="dup@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

            sp = StudentProfile(user_id=u.id, roll_no="102", department_id=dept.id)
            cs = ClassSection(department_id=dept.id, name="SY-EX-A", academic_year="2026-27", semester=3, year_of_study=2)
            s = Subject(user_id=u.id, name="Math", department_id=dept.id, semester=3)
            db.session.add_all([sp, cs, s])
            db.session.commit()

            d = date.today() - timedelta(days=1)
            att1 = Attendance(student_id=sp.id, subject_id=s.id, class_section_id=cs.id, date=d, status="Present")
            db.session.add(att1)
            db.session.commit()

            # Unique constraint prevents duplicate for same student, subject, class_section, date
            from sqlalchemy.exc import IntegrityError
            att2 = Attendance(student_id=sp.id, subject_id=s.id, class_section_id=cs.id, date=d, status="Absent")
            db.session.add(att2)
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_16_delete_attendance_record(self):
        with self.app.app_context():
            dept = Department(name="Civil", code="CV")
            db.session.add(dept)
            db.session.commit()

            u = User(name="Del Att", email="del@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

            sp = StudentProfile(user_id=u.id, roll_no="103", department_id=dept.id)
            cs = ClassSection(department_id=dept.id, name="SY-CV-A", academic_year="2026-27", semester=3, year_of_study=2)
            s = Subject(user_id=u.id, name="Surveying", department_id=dept.id, semester=3)
            db.session.add_all([sp, cs, s])
            db.session.commit()

            att = Attendance(student_id=sp.id, subject_id=s.id, class_section_id=cs.id, date=date.today() - timedelta(days=1), status="Present")
            db.session.add(att)
            db.session.commit()
            aid = att.id

            db.session.delete(att)
            db.session.commit()
            self.assertIsNone(db.session.get(Attendance, aid))

    def test_17_department_model_and_relationships(self):
        with self.app.app_context():
            dept = Department(name="Computer Engineering", code="CE")
            db.session.add(dept)
            db.session.commit()
            self.assertEqual(dept.code, "CE")
            self.assertEqual(dept.name, "Computer Engineering")

    def test_18_class_section_model_and_department(self):
        with self.app.app_context():
            dept = Department(name="Information Technology", code="IT")
            db.session.add(dept)
            db.session.commit()
            section = ClassSection(department_id=dept.id, name="TY-IT-A", semester=5, year_of_study=3, academic_year="2026-27")
            db.session.add(section)
            db.session.commit()
            self.assertEqual(section.department.code, "IT")
            self.assertEqual(section.name, "TY-IT-A")
            self.assertIn(section, dept.class_sections)

    def test_19_student_profile_model_and_user_backref(self):
        with self.app.app_context():
            dept = Department(name="Mechanical", code="ME")
            db.session.add(dept)
            user = User(name="Mech Student", email="mech@vvp.edu", password_hash="p", role="student")
            db.session.add(user)
            db.session.commit()

            profile = StudentProfile(user_id=user.id, roll_no="ME-101", admission_year=2024, department_id=dept.id)
            db.session.add(profile)
            db.session.commit()

            self.assertEqual(user.student_profile.roll_no, "ME-101")
            self.assertEqual(profile.user.name, "Mech Student")
            self.assertEqual(profile.department.code, "ME")

    def test_20_teacher_profile_model_and_user_backref(self):
        with self.app.app_context():
            dept = Department(name="Civil Engineering", code="CIVIL")
            db.session.add(dept)
            user = User(name="Prof Civil", email="prof_civ@vvp.edu", password_hash="p", role="teacher")
            db.session.add(user)
            db.session.commit()

            t_profile = TeacherProfile(user_id=user.id, employee_id="EMP-999", department_id=dept.id, designation="HOD")
            db.session.add(t_profile)
            db.session.commit()

            self.assertEqual(user.teacher_profile.employee_id, "EMP-999")
            self.assertEqual(t_profile.user.name, "Prof Civil")
            self.assertEqual(t_profile.department.code, "CIVIL")

    def test_21_class_enrollment_relationship(self):
        with self.app.app_context():
            dept = Department(name="Electrical", code="EE")
            db.session.add(dept)
            db.session.commit()

            section = ClassSection(department_id=dept.id, name="SY-EE-B", semester=3, year_of_study=2, academic_year="2026-27")
            user = User(name="EE Student", email="ee@vvp.edu", password_hash="p", role="student")
            db.session.add_all([section, user])
            db.session.commit()

            sp = StudentProfile(user_id=user.id, roll_no="EE-501", admission_year=2025, department_id=dept.id)
            db.session.add(sp)
            db.session.commit()

            enrollment = ClassEnrollment(student_id=sp.id, class_section_id=section.id)
            db.session.add(enrollment)
            db.session.commit()

            self.assertEqual(enrollment.student.roll_no, "EE-501")
            self.assertEqual(enrollment.class_section.name, "SY-EE-B")

    def test_22_subject_optional_department_and_semester(self):
        with self.app.app_context():
            dept = Department(name="Automobile", code="AE")
            user = User(name="AE User", email="ae@vvp.edu", password_hash="p", role="student")
            db.session.add_all([dept, user])
            db.session.commit()

            subj = Subject(user_id=user.id, name="Thermodynamics", code="AE-401", department_id=dept.id, semester=4)
            db.session.add(subj)
            db.session.commit()

            self.assertEqual(subj.department_id, dept.id)
            self.assertEqual(subj.semester, 4)

    def test_23_empty_attendance_calculation(self):
        with self.app.app_context():
            u = User(name="Empty User", email="empty@vvp.edu", password_hash="p", role="student")
            db.session.add(u)
            db.session.commit()
            self.assertEqual(calculate_overall_attendance(u.id), 0.0)

    def test_24_home_page_renders_successfully(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"V.V.P. Polytechnic", response.data)

    def test_25_login_page_renders_successfully(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Sign In to StudentIQ", response.data)

    def test_26_register_page_renders_successfully(self):
        response = self.client.get("/register")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Register New User", response.data)

    def test_27_authenticated_user_accessing_login_redirects(self):
        with self.app.app_context():
            u = User(name="Logged User", email="lu@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

        self.client.post("/login", data={"email": "lu@vvp.edu", "password": "p"})
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/dashboard"))

    def test_28_authenticated_user_accessing_register_redirects(self):
        with self.app.app_context():
            u = User(name="Logged User", email="lu2@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

        self.client.post("/login", data={"email": "lu2@vvp.edu", "password": "p"})
        resp = self.client.get("/register")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/dashboard"))

    def test_29_add_subject_requires_name(self):
        with self.app.app_context():
            admin = User(name="Admin Sub", email="adm_sub_req@vvp.edu", password_hash=generate_password_hash("p"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "adm_sub_req@vvp.edu", "password": "p"})
        resp = self.client.post("/admin/subjects/add", data={"name": "", "code": "101"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Subject name is required", resp.data)

    def test_30_edit_subject_requires_admin(self):
        with self.app.app_context():
            u = User(name="Sub User", email="sub2@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()
            s = Subject(user_id=u.id, name="OS")
            db.session.add(s)
            db.session.commit()
            sid = s.id

        self.client.post("/login", data={"email": "sub2@vvp.edu", "password": "p"})
        resp = self.client.post(f"/subjects/{sid}/edit", data={"name": "New OS"})
        self.assertEqual(resp.status_code, 403)

    def test_31_delete_nonexistent_subject_403_for_student(self):
        with self.app.app_context():
            u = User(name="Sub User", email="sub3@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

        self.client.post("/login", data={"email": "sub3@vvp.edu", "password": "p"})
        resp = self.client.post("/subjects/99999/delete")
        self.assertEqual(resp.status_code, 403)

    def test_32_unauthorized_attendance_marking_blocked(self):
        with self.app.app_context():
            u = User(name="Sub User", email="sub4@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

        self.client.post("/login", data={"email": "sub4@vvp.edu", "password": "p"})
        resp = self.client.post("/subjects/99999/sections/99999/attendance/mark", data={"date": str(date.today())})
        self.assertEqual(resp.status_code, 403)

    # =========================================================================
    # PHASE 2 TESTS: Admin Foundation & Authorization
    # =========================================================================

    def test_33_cli_create_admin_new_user(self):
        runner = self.app.test_cli_runner()
        result = runner.invoke(
            self.app.cli.get_command(self.app, "create-admin"),
            ["--name", "Head Admin", "--email", "admin@vvp.edu", "--password", "AdminPass123"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("created successfully", result.output)

        with self.app.app_context():
            admin_user = User.query.filter_by(email="admin@vvp.edu").first()
            self.assertIsNotNone(admin_user)
            self.assertEqual(admin_user.name, "Head Admin")
            self.assertEqual(admin_user.role, "admin")
            self.assertTrue(admin_user.is_admin)
            self.assertTrue(check_password_hash(admin_user.password_hash, "AdminPass123"))

    def test_34_cli_create_admin_upgrade_existing_user(self):
        with self.app.app_context():
            user = User(name="Existing User", email="promote@vvp.edu", password_hash=generate_password_hash("oldpass"), role="student")
            db.session.add(user)
            db.session.commit()

        runner = self.app.test_cli_runner()
        result = runner.invoke(
            self.app.cli.get_command(self.app, "create-admin"),
            ["--name", "Promoted Admin", "--email", "promote@vvp.edu", "--password", "NewAdminPass123"],
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("updated to admin successfully", result.output)

        with self.app.app_context():
            updated_user = User.query.filter_by(email="promote@vvp.edu").first()
            self.assertEqual(updated_user.role, "admin")
            self.assertTrue(updated_user.is_admin)
            self.assertTrue(check_password_hash(updated_user.password_hash, "NewAdminPass123"))

    def test_35_admin_login_redirects_to_admin_dashboard(self):
        with self.app.app_context():
            admin = User(name="Admin Login", email="admin_login@vvp.edu", password_hash=generate_password_hash("adm123"), role="admin")
            db.session.add(admin)
            db.session.commit()

        response = self.client.post("/login", data={"email": "admin_login@vvp.edu", "password": "adm123"}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/admin/dashboard"))

    def test_36_admin_accesses_admin_dashboard_with_confirmation(self):
        with self.app.app_context():
            admin = User(name="Chief Admin", email="chief@vvp.edu", password_hash=generate_password_hash("adm123"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "chief@vvp.edu", "password": "adm123"})
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Admin &amp; HOD Workspace", response.data)
        self.assertIn(b"Chief Admin", response.data)
        self.assertIn(b"Administrator Confirmation", response.data)
        self.assertIn(b"Phase 2 Admin Foundation Active", response.data)

    def test_37_admin_index_route_redirects_to_admin_dashboard(self):
        with self.app.app_context():
            admin = User(name="Admin Direct", email="admdirect@vvp.edu", password_hash=generate_password_hash("adm123"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "admdirect@vvp.edu", "password": "adm123"})
        response = self.client.get("/admin/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/admin/dashboard"))

    def test_38_unauthenticated_admin_access_redirects_to_login(self):
        response = self.client.get("/admin/dashboard", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_39_student_attempting_admin_access_receives_403_forbidden(self):
        with self.app.app_context():
            student = User(name="Sneaky Student", email="student@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            db.session.add(student)
            db.session.commit()

        self.client.post("/login", data={"email": "student@vvp.edu", "password": "pass"})
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"403 - Access Forbidden", response.data)
        self.assertIn(b"Access Denied", response.data)
        self.assertIn(b"Administrator Privileges Required", response.data)

    def test_40_teacher_attempting_admin_access_receives_403_forbidden(self):
        with self.app.app_context():
            teacher = User(name="Regular Teacher", email="teacher@vvp.edu", password_hash=generate_password_hash("pass"), role="teacher")
            db.session.add(teacher)
            db.session.commit()

        self.client.post("/login", data={"email": "teacher@vvp.edu", "password": "pass"})
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"403 - Access Forbidden", response.data)
        self.assertIn(b"Access Denied", response.data)

    def test_41_authenticated_admin_visiting_login_redirects_to_admin_dashboard(self):
        with self.app.app_context():
            admin = User(name="Admin Auth", email="auth_adm@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "auth_adm@vvp.edu", "password": "pass"})
        resp = self.client.get("/login")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/admin/dashboard"))

    def test_42_authenticated_admin_visiting_register_redirects_to_admin_dashboard(self):
        with self.app.app_context():
            admin = User(name="Admin Reg", email="reg_adm@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "reg_adm@vvp.edu", "password": "pass"})
        resp = self.client.get("/register")
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/admin/dashboard"))

    # =========================================================================
    # PHASE 3 TESTS: Faculty Provisioning (/admin/add-faculty)
    # =========================================================================

    def test_43_unauthenticated_add_faculty_redirects_to_login(self):
        response = self.client.get("/admin/add-faculty", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_44_student_accessing_add_faculty_receives_403(self):
        with self.app.app_context():
            student = User(name="Student User", email="student_p3@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            db.session.add(student)
            db.session.commit()

        self.client.post("/login", data={"email": "student_p3@vvp.edu", "password": "pass"})
        response = self.client.get("/admin/add-faculty")
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"403 - Access Forbidden", response.data)

        # POST attempt as student also returns 403
        post_resp = self.client.post("/admin/add-faculty", data={"name": "X", "email": "x@vvp.edu", "employee_id": "EMP-X", "department_id": "1"})
        self.assertEqual(post_resp.status_code, 403)

    def test_45_teacher_accessing_add_faculty_receives_403(self):
        with self.app.app_context():
            teacher = User(name="Teacher User", email="teacher_p3@vvp.edu", password_hash=generate_password_hash("pass"), role="teacher")
            db.session.add(teacher)
            db.session.commit()

        self.client.post("/login", data={"email": "teacher_p3@vvp.edu", "password": "pass"})
        response = self.client.get("/admin/add-faculty")
        self.assertEqual(response.status_code, 403)
        self.assertIn(b"403 - Access Forbidden", response.data)

    def test_46_admin_can_access_add_faculty_page_get(self):
        with self.app.app_context():
            admin = User(name="Admin User", email="admin_p3@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            dept = Department(name="Computer Engineering", code="CO")
            db.session.add_all([admin, dept])
            db.session.commit()

        self.client.post("/login", data={"email": "admin_p3@vvp.edu", "password": "pass"})
        response = self.client.get("/admin/add-faculty")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Add Faculty Member", response.data)
        self.assertIn(b"Computer Engineering", response.data)

    def test_47_valid_faculty_creation_succeeds_with_temp_password(self):
        with self.app.app_context():
            admin = User(name="Admin User", email="admin_create@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            dept = Department(name="Information Technology", code="IT")
            db.session.add_all([admin, dept])
            db.session.commit()
            dept_id = dept.id

        self.client.post("/login", data={"email": "admin_create@vvp.edu", "password": "pass"})
        response = self.client.post(
            "/admin/add-faculty",
            data={
                "name": "Prof. Rajesh Kumar",
                "email": "rajesh@vvp.edu",
                "employee_id": "EMP-2041",
                "department_id": str(dept_id),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Faculty Account Created Successfully", response.data)
        self.assertIn(b"Prof. Rajesh Kumar", response.data)
        self.assertIn(b"rajesh@vvp.edu", response.data)
        self.assertIn(b"EMP-2041", response.data)
        self.assertIn(b"Temporary Password", response.data)

        with self.app.app_context():
            created_user = User.query.filter_by(email="rajesh@vvp.edu").first()
            self.assertIsNotNone(created_user)
            self.assertEqual(created_user.name, "Prof. Rajesh Kumar")
            self.assertEqual(created_user.role, "teacher")
            self.assertTrue(created_user.is_teacher)
            self.assertFalse(created_user.is_student)
            self.assertFalse(created_user.is_admin)
            self.assertTrue(created_user.must_change_password)

            # Check linked profile
            self.assertIsNotNone(created_user.teacher_profile)
            self.assertEqual(created_user.teacher_profile.employee_id, "EMP-2041")
            self.assertEqual(created_user.teacher_profile.department_id, dept_id)
            self.assertEqual(created_user.teacher_profile.department.name, "Information Technology")

    def test_48_duplicate_email_rejected(self):
        with self.app.app_context():
            admin = User(name="Admin User", email="admin_dup@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            existing = User(name="Existing Person", email="existing@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            dept = Department(name="Civil Engineering", code="CE")
            db.session.add_all([admin, existing, dept])
            db.session.commit()
            dept_id = dept.id

        self.client.post("/login", data={"email": "admin_dup@vvp.edu", "password": "pass"})
        response = self.client.post(
            "/admin/add-faculty",
            data={
                "name": "Prof. New Person",
                "email": "Existing@VVP.edu ",  # test normalization
                "employee_id": "EMP-9999",
                "department_id": str(dept_id),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"already exists", response.data)

    def test_49_duplicate_employee_id_rejected(self):
        with self.app.app_context():
            admin = User(name="Admin User", email="admin_dup_emp@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            t_user = User(name="Teacher One", email="t1@vvp.edu", password_hash=generate_password_hash("pass"), role="teacher")
            dept = Department(name="Mechanical Engineering", code="ME")
            db.session.add_all([admin, t_user, dept])
            db.session.commit()

            profile = TeacherProfile(user_id=t_user.id, employee_id="EMP-1001", department_id=dept.id)
            db.session.add(profile)
            db.session.commit()
            dept_id = dept.id

        self.client.post("/login", data={"email": "admin_dup_emp@vvp.edu", "password": "pass"})
        response = self.client.post(
            "/admin/add-faculty",
            data={
                "name": "Teacher Two",
                "email": "t2@vvp.edu",
                "employee_id": "EMP-1001",
                "department_id": str(dept_id),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Employee ID already exists", response.data)

    def test_50_missing_required_fields_rejected(self):
        with self.app.app_context():
            admin = User(name="Admin User", email="admin_missing@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            dept = Department(name="Automobile", code="AE")
            db.session.add_all([admin, dept])
            db.session.commit()
            dept_id = dept.id

        self.client.post("/login", data={"email": "admin_missing@vvp.edu", "password": "pass"})

        # Missing name
        resp = self.client.post("/admin/add-faculty", data={"name": "", "email": "a@vvp.edu", "employee_id": "E1", "department_id": str(dept_id)})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"All fields are required", resp.data)

        # Missing email
        resp = self.client.post("/admin/add-faculty", data={"name": "A", "email": "", "employee_id": "E1", "department_id": str(dept_id)})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"All fields are required", resp.data)

        # Missing employee_id
        resp = self.client.post("/admin/add-faculty", data={"name": "A", "email": "a@vvp.edu", "employee_id": "", "department_id": str(dept_id)})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"All fields are required", resp.data)

        # Missing department_id
        resp = self.client.post("/admin/add-faculty", data={"name": "A", "email": "a@vvp.edu", "employee_id": "E1", "department_id": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"All fields are required", resp.data)

        # Invalid department_id
        resp = self.client.post("/admin/add-faculty", data={"name": "A", "email": "a@vvp.edu", "employee_id": "E1", "department_id": "99999"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"valid department", resp.data)

    def test_51_transaction_rollback_on_failure(self):
        with self.app.app_context():
            admin = User(name="Admin User", email="admin_rb@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            dept = Department(name="Electrical", code="EE")
            db.session.add_all([admin, dept])
            db.session.commit()
            dept_id = dept.id

        self.client.post("/login", data={"email": "admin_rb@vvp.edu", "password": "pass"})

        # Monkeypatch db.session.commit to raise an exception to verify rollback
        from unittest.mock import patch
        with patch.object(db.session, "commit", side_effect=Exception("Database commit error")):
            resp = self.client.post(
                "/admin/add-faculty",
                data={
                    "name": "Failed Faculty",
                    "email": "failed_fac@vvp.edu",
                    "employee_id": "EMP-FAIL",
                    "department_id": str(dept_id),
                },
            )
            self.assertEqual(resp.status_code, 500)

        with self.app.app_context():
            # Verify user was NOT created due to rollback
            self.assertIsNone(User.query.filter_by(email="failed_fac@vvp.edu").first())
            self.assertIsNone(TeacherProfile.query.filter_by(employee_id="EMP-FAIL").first())

    def test_52_public_registration_cannot_specify_role(self):
        # Even if a malicious user passes role='teacher' or role='admin' to /register
        response = self.client.post(
            "/register",
            data={
                "name": "Attacker",
                "email": "attacker@vvp.edu",
                "password": "pass",
                "role": "admin",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            user = User.query.filter_by(email="attacker@vvp.edu").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.role, "student")
            self.assertTrue(user.is_student)
            self.assertFalse(user.is_admin)
            self.assertFalse(user.is_teacher)

    # =========================================================================
    # PHASE 3.5 TESTS: Department Management CRUD (/admin/departments)
    # =========================================================================

    def test_53_unauthenticated_department_access_redirects(self):
        endpoints = [
            ("/admin/departments", "GET"),
            ("/admin/departments/add", "GET"),
            ("/admin/departments/add", "POST"),
            ("/admin/departments/1/edit", "GET"),
            ("/admin/departments/1/delete", "POST"),
        ]
        for url, method in endpoints:
            if method == "GET":
                resp = self.client.get(url, follow_redirects=False)
            else:
                resp = self.client.post(url, follow_redirects=False)
            self.assertEqual(resp.status_code, 302, f"Failed for {method} {url}")
            self.assertIn("/login", resp.location)

    def test_54_student_and_teacher_cannot_access_department_crud_403(self):
        with self.app.app_context():
            student = User(name="Student Dept", email="s_dept@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            teacher = User(name="Teacher Dept", email="t_dept@vvp.edu", password_hash=generate_password_hash("pass"), role="teacher")
            db.session.add_all([student, teacher])
            db.session.commit()

        # Student attempt
        self.client.post("/login", data={"email": "s_dept@vvp.edu", "password": "pass"})
        resp = self.client.get("/admin/departments")
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post("/admin/departments/add", data={"name": "X", "code": "X"})
        self.assertEqual(resp.status_code, 403)
        self.client.get("/logout")

        # Teacher attempt
        self.client.post("/login", data={"email": "t_dept@vvp.edu", "password": "pass"})
        resp = self.client.get("/admin/departments")
        self.assertEqual(resp.status_code, 403)
        resp = self.client.post("/admin/departments/add", data={"name": "X", "code": "X"})
        self.assertEqual(resp.status_code, 403)

    def test_55_admin_list_departments_empty_and_populated(self):
        with self.app.app_context():
            admin = User(name="Admin Dept", email="adm_dept@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "adm_dept@vvp.edu", "password": "pass"})

        # Empty list
        resp = self.client.get("/admin/departments")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No Departments Found", resp.data)

        # Populated list
        with self.app.app_context():
            dept = Department(name="Computer Engineering", code="CO")
            db.session.add(dept)
            db.session.commit()

        resp = self.client.get("/admin/departments")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Computer Engineering", resp.data)
        self.assertIn(b"CO", resp.data)

    def test_56_admin_add_department_success_and_normalization(self):
        with self.app.app_context():
            admin = User(name="Admin Dept Add", email="adm_add@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "adm_add@vvp.edu", "password": "pass"})

        # GET add form
        get_resp = self.client.get("/admin/departments/add")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn(b"Add Academic Department", get_resp.data)

        # POST add with leading/trailing spaces and lowercase code
        post_resp = self.client.post(
            "/admin/departments/add",
            data={"name": "  Civil Engineering  ", "code": "  ce  "},
            follow_redirects=True,
        )
        self.assertEqual(post_resp.status_code, 200)
        self.assertIn(b"created successfully", post_resp.data)
        self.assertIn(b"Civil Engineering", post_resp.data)
        self.assertIn(b"CE", post_resp.data)

        with self.app.app_context():
            dept = Department.query.filter_by(code="CE").first()
            self.assertIsNotNone(dept)
            self.assertEqual(dept.name, "Civil Engineering")
            self.assertEqual(dept.code, "CE")

    def test_57_admin_add_department_duplicate_name_and_code_rejected(self):
        with self.app.app_context():
            admin = User(name="Admin Dept Dup", email="adm_dup_d@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            dept = Department(name="Mechanical Engineering", code="ME")
            db.session.add_all([admin, dept])
            db.session.commit()

        self.client.post("/login", data={"email": "adm_dup_d@vvp.edu", "password": "pass"})

        # Duplicate name (case-insensitive)
        resp = self.client.post("/admin/departments/add", data={"name": "mechanical engineering", "code": "M2"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"already exists", resp.data)

        # Duplicate code (case-insensitive)
        resp = self.client.post("/admin/departments/add", data={"name": "New Mechanical", "code": "me"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"already exists", resp.data)

    def test_58_admin_add_department_missing_fields_rejected(self):
        with self.app.app_context():
            admin = User(name="Admin Dept Req", email="adm_req@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "adm_req@vvp.edu", "password": "pass"})

        # Missing name
        resp = self.client.post("/admin/departments/add", data={"name": "", "code": "EE"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"required", resp.data)

        # Missing code
        resp = self.client.post("/admin/departments/add", data={"name": "Electrical", "code": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"required", resp.data)

    def test_59_admin_edit_department_lifecycle(self):
        with self.app.app_context():
            admin = User(name="Admin Dept Edit", email="adm_edit@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            d1 = Department(name="Electronics", code="ET")
            d2 = Department(name="Information Tech", code="IT")
            db.session.add_all([admin, d1, d2])
            db.session.commit()
            d1_id = d1.id

        self.client.post("/login", data={"email": "adm_edit@vvp.edu", "password": "pass"})

        # GET edit form
        resp = self.client.get(f"/admin/departments/{d1_id}/edit")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Edit Department", resp.data)
        self.assertIn(b"Electronics", resp.data)

        # POST valid edit
        resp = self.client.post(
            f"/admin/departments/{d1_id}/edit",
            data={"name": "Electronics & Telecom", "code": "EXTC"},
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"updated successfully", resp.data)

        with self.app.app_context():
            updated = db.session.get(Department, d1_id)
            self.assertEqual(updated.name, "Electronics & Telecom")
            self.assertEqual(updated.code, "EXTC")

        # Duplicate name of another dept
        resp = self.client.post(f"/admin/departments/{d1_id}/edit", data={"name": "Information Tech", "code": "EXTC"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"already exists", resp.data)

        # Duplicate code of another dept
        resp = self.client.post(f"/admin/departments/{d1_id}/edit", data={"name": "Electronics & Telecom", "code": "it"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"already exists", resp.data)

        # 404 for non-existent dept
        resp = self.client.get("/admin/departments/99999/edit")
        self.assertEqual(resp.status_code, 404)

    def test_60_admin_delete_department_safe_deletion_protection(self):
        with self.app.app_context():
            admin = User(name="Admin Dept Del", email="adm_del@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            d_clean = Department(name="Clean Dept", code="CD")
            d_busy = Department(name="Busy Dept", code="BD")
            db.session.add_all([admin, d_clean, d_busy])
            db.session.commit()

            # Link a teacher to d_busy
            t_user = User(name="Teacher Busy", email="t_busy@vvp.edu", password_hash=generate_password_hash("pass"), role="teacher")
            db.session.add(t_user)
            db.session.commit()
            t_prof = TeacherProfile(user_id=t_user.id, employee_id="EMP-BUSY", department_id=d_busy.id)
            db.session.add(t_prof)
            db.session.commit()

            clean_id = d_clean.id
            busy_id = d_busy.id

        self.client.post("/login", data={"email": "adm_del@vvp.edu", "password": "pass"})

        # Delete busy department -> blocked by safe deletion check
        resp = self.client.post(f"/admin/departments/{busy_id}/delete", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Cannot delete department", resp.data)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Department, busy_id))

        # Delete clean department -> succeeds
        resp = self.client.post(f"/admin/departments/{clean_id}/delete", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"deleted successfully", resp.data)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Department, clean_id))

        # 404 for non-existent dept
        resp = self.client.post("/admin/departments/99999/delete")
        self.assertEqual(resp.status_code, 404)

    def test_61_add_department_populates_add_faculty_dropdown(self):
        with self.app.app_context():
            admin = User(name="Admin Pop", email="adm_pop@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add(admin)
            db.session.commit()

        self.client.post("/login", data={"email": "adm_pop@vvp.edu", "password": "pass"})

        # Create department via admin route
        self.client.post("/admin/departments/add", data={"name": "Applied Science", "code": "AS"}, follow_redirects=True)

        # GET /admin/add-faculty should now have Applied Science option in select
    # =========================================================================
    # PHASE 4 TESTS: Mandatory First-Login Password Change (/setup-password)
    # =========================================================================

    def test_62_unauthenticated_setup_password_redirects_to_login(self):
        get_resp = self.client.get("/setup-password", follow_redirects=False)
        self.assertEqual(get_resp.status_code, 302)
        self.assertIn("/login", get_resp.location)

        post_resp = self.client.post("/setup-password", data={"password": "Pass", "confirm_password": "Pass"}, follow_redirects=False)
        self.assertEqual(post_resp.status_code, 302)
        self.assertIn("/login", post_resp.location)

    def test_63_authenticated_user_without_mandatory_change_redirects_away(self):
        # Student with must_change_password=False
        with self.app.app_context():
            student = User(name="Normal Student", email="norm_s@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            admin = User(name="Normal Admin", email="norm_a@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add_all([student, admin])
            db.session.commit()

        self.client.post("/login", data={"email": "norm_s@vvp.edu", "password": "pass"})
        resp = self.client.get("/setup-password", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/dashboard"))
        self.client.get("/logout")

        self.client.post("/login", data={"email": "norm_a@vvp.edu", "password": "pass"})
        resp = self.client.get("/setup-password", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/admin/dashboard"))

    def test_64_teacher_with_must_change_password_redirected_on_login(self):
        with self.app.app_context():
            teacher = User(
                name="New Teacher",
                email="new_t@vvp.edu",
                password_hash=generate_password_hash("TempPass123"),
                role="teacher",
                must_change_password=True,
            )
            db.session.add(teacher)
            db.session.commit()

        login_resp = self.client.post("/login", data={"email": "new_t@vvp.edu", "password": "TempPass123"}, follow_redirects=False)
        self.assertEqual(login_resp.status_code, 302)
        self.assertTrue(login_resp.location.endswith("/setup-password"))

    def test_65_teacher_cannot_bypass_setup_password_page(self):
        with self.app.app_context():
            teacher = User(
                name="Bypass Teacher",
                email="bypass_t@vvp.edu",
                password_hash=generate_password_hash("TempPass123"),
                role="teacher",
                must_change_password=True,
            )
            db.session.add(teacher)
            db.session.commit()

        self.client.post("/login", data={"email": "bypass_t@vvp.edu", "password": "TempPass123"})

        # Direct access to dashboard is intercepted
        resp = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/setup-password"))

        # Direct access to subjects is intercepted
        resp = self.client.get("/subjects", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.location.endswith("/setup-password"))

        # Access to setup-password returns 200
        resp = self.client.get("/setup-password")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Set Permanent Password", resp.data)
        self.assertIn(b"Bypass Teacher", resp.data)

    def test_66_setup_password_validation_rejections(self):
        with self.app.app_context():
            teacher = User(
                name="Val Teacher",
                email="val_t@vvp.edu",
                password_hash=generate_password_hash("TempSecret123"),
                role="teacher",
                must_change_password=True,
            )
            db.session.add(teacher)
            db.session.commit()

        self.client.post("/login", data={"email": "val_t@vvp.edu", "password": "TempSecret123"})

        # Missing fields
        resp = self.client.post("/setup-password", data={"password": "", "confirm_password": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"All fields are required", resp.data)

        # Minimum length (< 6 chars)
        resp = self.client.post("/setup-password", data={"password": "12345", "confirm_password": "12345"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"at least 6 characters", resp.data)

        # Password mismatch
        resp = self.client.post("/setup-password", data={"password": "NewSecret123", "confirm_password": "WrongSecret123"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Passwords do not match", resp.data)

        # Same as temporary password
        resp = self.client.post("/setup-password", data={"password": "TempSecret123", "confirm_password": "TempSecret123"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"cannot be the same as the temporary password", resp.data)

    def test_67_successful_password_setup_lifecycle(self):
        with self.app.app_context():
            teacher = User(
                name="Active Teacher",
                email="active_t@vvp.edu",
                password_hash=generate_password_hash("TempSecret123"),
                role="teacher",
                must_change_password=True,
            )
            db.session.add(teacher)
            db.session.commit()
            uid = teacher.id

        # Login with temp pass
        self.client.post("/login", data={"email": "active_t@vvp.edu", "password": "TempSecret123"})

        # Submit valid new password
        post_resp = self.client.post(
            "/setup-password",
            data={"password": "NewPermPass@123", "confirm_password": "NewPermPass@123"},
            follow_redirects=False,
        )
        self.assertEqual(post_resp.status_code, 302)
        self.assertTrue(post_resp.location.endswith("/dashboard"))

        # Verify DB state
        with self.app.app_context():
            updated_user = db.session.get(User, uid)
            self.assertFalse(updated_user.must_change_password)
            self.assertTrue(check_password_hash(updated_user.password_hash, "NewPermPass@123"))

        # Can now access dashboard
        dash_resp = self.client.get("/dashboard")
        self.assertEqual(dash_resp.status_code, 200)
        self.assertIn(b"Welcome, Active Teacher!", dash_resp.data)

        # Logout
        self.client.get("/logout")

        # Old temp password no longer works
        old_login = self.client.post("/login", data={"email": "active_t@vvp.edu", "password": "TempSecret123"})
        self.assertEqual(old_login.status_code, 401)

        # New password works and takes user directly to dashboard (no setup redirect)
        new_login = self.client.post("/login", data={"email": "active_t@vvp.edu", "password": "NewPermPass@123"}, follow_redirects=False)
        self.assertEqual(new_login.status_code, 302)
        self.assertTrue(new_login.location.endswith("/dashboard"))

    def test_68_end_to_end_admin_provision_to_teacher_activation(self):
        with self.app.app_context():
            admin = User(name="Admin E2E", email="adm_e2e@vvp.edu", password_hash=generate_password_hash("AdminPass123"), role="admin")
            dept = Department(name="Computer Tech", code="CT")
            db.session.add_all([admin, dept])
            db.session.commit()
            dept_id = dept.id

        # 1. Admin logs in and provisions faculty
        self.client.post("/login", data={"email": "adm_e2e@vvp.edu", "password": "AdminPass123"})
        prov_resp = self.client.post(
            "/admin/add-faculty",
            data={
                "name": "Prof. Anjali Sharma",
                "email": "anjali@vvp.edu",
                "employee_id": "EMP-CT-01",
                "department_id": str(dept_id),
            },
        )
        self.assertEqual(prov_resp.status_code, 200)

        # Extract generated temp password
        import re
        html = prov_resp.data.decode("utf-8")
        match = re.search(r"<code[^>]*>([A-Za-z0-9_-]+)</code>", html)
        self.assertIsNotNone(match)
        temp_pw = match.group(1)

        self.client.get("/logout")

        # 2. Teacher logs in with temp password
        t_login = self.client.post("/login", data={"email": "anjali@vvp.edu", "password": temp_pw}, follow_redirects=False)
        self.assertEqual(t_login.status_code, 302)
        self.assertTrue(t_login.location.endswith("/setup-password"))

        # 3. Teacher sets permanent password
        setup_resp = self.client.post(
            "/setup-password",
            data={"password": "MySecretPass@2026", "confirm_password": "MySecretPass@2026"},
            follow_redirects=True,
        )
        self.assertEqual(setup_resp.status_code, 200)
        self.assertIn(b"Welcome, Prof. Anjali Sharma!", setup_resp.data)

        # 4. Confirm DB state
        with self.app.app_context():
            fac = User.query.filter_by(email="anjali@vvp.edu").first()
            self.assertFalse(fac.must_change_password)
            self.assertEqual(fac.role, "teacher")
            self.assertEqual(fac.teacher_profile.employee_id, "EMP-CT-01")

    def test_69_student_and_admin_logins_unaffected(self):
        with self.app.app_context():
            student = User(name="Regular Student", email="reg_s@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            admin = User(name="Regular Admin", email="reg_a@vvp.edu", password_hash=generate_password_hash("pass"), role="admin")
            db.session.add_all([student, admin])
            db.session.commit()

        # Student login -> direct to dashboard
        s_resp = self.client.post("/login", data={"email": "reg_s@vvp.edu", "password": "pass"}, follow_redirects=False)
        self.assertEqual(s_resp.status_code, 302)
        self.assertTrue(s_resp.location.endswith("/dashboard"))
        self.client.get("/logout")

        # Admin login -> direct to admin dashboard
        a_resp = self.client.post("/login", data={"email": "reg_a@vvp.edu", "password": "pass"}, follow_redirects=False)
        self.assertEqual(a_resp.status_code, 302)
        self.assertTrue(a_resp.location.endswith("/admin/dashboard"))

    # =========================================================================
    # PHASE 5 TESTS: Teacher-Subject-Class Assignment Management
    # =========================================================================

    def _setup_assignment_prerequisites(self):
        """Helper to create admin, department, teacher, subject, and class section."""
        with self.app.app_context():
            admin = User(name="Admin User", email="admin_p5@vvp.edu", password_hash=generate_password_hash("adminpass"), role="admin")
            dept = Department(name="Computer Engineering", code="CO")
            db.session.add_all([admin, dept])
            db.session.commit()

            teacher_user = User(name="Prof. Rajesh Kulkarni", email="kulkarni@vvp.edu", password_hash=generate_password_hash("teachpass"), role="teacher")
            db.session.add(teacher_user)
            db.session.commit()

            teacher_profile = TeacherProfile(user_id=teacher_user.id, employee_id="EMP-CO-101", department_id=dept.id, designation="Assistant Professor")
            subject = Subject(user_id=teacher_user.id, name="Operating Systems", code="OS-22415", department_id=dept.id, semester=4)
            class_section = ClassSection(department_id=dept.id, name="SY-CO-A", academic_year="2026-27", semester=4, year_of_study=2)

            db.session.add_all([teacher_profile, subject, class_section])
            db.session.commit()

            return {
                "admin_id": admin.id,
                "teacher_id": teacher_profile.id,
                "subject_id": subject.id,
                "class_section_id": class_section.id,
                "dept_id": dept.id,
            }

    def test_70_admin_get_assignments_empty_and_populated(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        # Empty state
        resp = self.client.get("/admin/assignments")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No Assignments Found", resp.data)

        # Create one assignment
        with self.app.app_context():
            assignment = TeacherAssignment(
                teacher_id=ids["teacher_id"],
                subject_id=ids["subject_id"],
                class_section_id=ids["class_section_id"],
            )
            db.session.add(assignment)
            db.session.commit()

        # Populated state
        resp = self.client.get("/admin/assignments")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Prof. Rajesh Kulkarni", resp.data)
        self.assertIn(b"EMP-CO-101", resp.data)
        self.assertIn(b"Operating Systems", resp.data)
        self.assertIn(b"SY-CO-A", resp.data)

    def test_71_admin_get_assignments_add_form(self):
        self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        resp = self.client.get("/admin/assignments/add")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Allocate Faculty to Subject", resp.data)
        self.assertIn(b"Prof. Rajesh Kulkarni", resp.data)
        self.assertIn(b"Operating Systems", resp.data)
        self.assertIn(b"SY-CO-A", resp.data)

    def test_72_admin_post_valid_assignment(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Successfully assigned", resp.data)

        with self.app.app_context():
            assignment = TeacherAssignment.query.filter_by(
                teacher_id=ids["teacher_id"],
                subject_id=ids["subject_id"],
                class_section_id=ids["class_section_id"],
            ).first()
            self.assertIsNotNone(assignment)
            self.assertEqual(assignment.teacher.user.name, "Prof. Rajesh Kulkarni")

    def test_73_duplicate_assignment_rejected(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        # Initial assignment
        self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
        )

        # Duplicate POST
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"already assigned", resp.data)

        with self.app.app_context():
            count = TeacherAssignment.query.filter_by(
                teacher_id=ids["teacher_id"],
                subject_id=ids["subject_id"],
                class_section_id=ids["class_section_id"],
            ).count()
            self.assertEqual(count, 1)

    def test_74_unique_constraint_enforced_at_db_level(self):
        ids = self._setup_assignment_prerequisites()
        from sqlalchemy.exc import IntegrityError

        with self.app.app_context():
            a1 = TeacherAssignment(
                teacher_id=ids["teacher_id"],
                subject_id=ids["subject_id"],
                class_section_id=ids["class_section_id"],
            )
            a2 = TeacherAssignment(
                teacher_id=ids["teacher_id"],
                subject_id=ids["subject_id"],
                class_section_id=ids["class_section_id"],
            )
            db.session.add(a1)
            db.session.commit()

            db.session.add(a2)
            with self.assertRaises(IntegrityError):
                db.session.commit()
            db.session.rollback()

    def test_75_missing_fields_rejected(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        # Missing teacher_id
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": "",
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"required", resp.data)

        # Missing subject_id
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": "",
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"required", resp.data)

        # Missing class_section_id
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": "",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"required", resp.data)

    def test_76_invalid_or_nonexistent_ids_rejected(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        # Non-numeric ID
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": "abc",
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Invalid selection values", resp.data)

        # Non-existent teacher ID
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": "99999",
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Selected teacher does not exist", resp.data)

        # Non-existent subject ID
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": "99999",
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Selected subject does not exist", resp.data)

        # Non-existent class section ID
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": "99999",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Selected class section does not exist", resp.data)

    def test_77_student_blocked_with_403(self):
        ids = self._setup_assignment_prerequisites()
        with self.app.app_context():
            student = User(name="Test Student", email="student_p5@vvp.edu", password_hash=generate_password_hash("stupass"), role="student")
            db.session.add(student)
            db.session.commit()

        self.client.post("/login", data={"email": "student_p5@vvp.edu", "password": "stupass"})

        # GET /admin/assignments -> 403
        resp = self.client.get("/admin/assignments")
        self.assertEqual(resp.status_code, 403)

        # GET /admin/assignments/add -> 403
        resp = self.client.get("/admin/assignments/add")
        self.assertEqual(resp.status_code, 403)

        # POST /admin/assignments/add -> 403
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_78_teacher_blocked_with_403(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "kulkarni@vvp.edu", "password": "teachpass"})

        # GET /admin/assignments -> 403
        resp = self.client.get("/admin/assignments")
        self.assertEqual(resp.status_code, 403)

        # GET /admin/assignments/add -> 403
        resp = self.client.get("/admin/assignments/add")
        self.assertEqual(resp.status_code, 403)

        # POST /admin/assignments/add -> 403
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
        )
        self.assertEqual(resp.status_code, 403)

    def test_79_unauthenticated_redirects_to_login(self):
        ids = self._setup_assignment_prerequisites()

        # GET /admin/assignments
        resp = self.client.get("/admin/assignments", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.location)

        # GET /admin/assignments/add
        resp = self.client.get("/admin/assignments/add", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.location)

        # POST /admin/assignments/add
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(ids["class_section_id"]),
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.location)

    def test_80_simulated_db_error_triggers_rollback(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        with patch("extensions.db.session.commit", side_effect=Exception("Simulated DB Crash")):
            resp = self.client.post(
                "/admin/assignments/add",
                data={
                    "teacher_id": str(ids["teacher_id"]),
                    "subject_id": str(ids["subject_id"]),
                    "class_section_id": str(ids["class_section_id"]),
                },
            )
            self.assertEqual(resp.status_code, 500)
            self.assertIn(b"database error", resp.data)

        # Confirm no row persisted
        with self.app.app_context():
            count = TeacherAssignment.query.count()
            self.assertEqual(count, 0)

    def test_81_academic_consistency_advisory_warning(self):
        ids = self._setup_assignment_prerequisites()
        self.client.post("/login", data={"email": "admin_p5@vvp.edu", "password": "adminpass"})

        # Create a second department with a class section in Mechanical Engineering (ME)
        with self.app.app_context():
            me_dept = Department(name="Mechanical Engineering", code="ME")
            db.session.add(me_dept)
            db.session.commit()

            me_class = ClassSection(department_id=me_dept.id, name="TY-ME-A", academic_year="2026-27", semester=5, year_of_study=3)
            db.session.add(me_class)
            db.session.commit()
            me_class_id = me_class.id

        # Assign CO subject to ME class section -> should create assignment with non-blocking advisory note
        resp = self.client.post(
            "/admin/assignments/add",
            data={
                "teacher_id": str(ids["teacher_id"]),
                "subject_id": str(ids["subject_id"]),
                "class_section_id": str(me_class_id),
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Note: Subject", resp.data)
        self.assertIn(b"differs in department", resp.data)

        with self.app.app_context():
            assigned = TeacherAssignment.query.filter_by(
                teacher_id=ids["teacher_id"],
                subject_id=ids["subject_id"],
                class_section_id=me_class_id,
            ).first()
            self.assertIsNotNone(assigned)

    # =========================================================================
    # PHASE 6 TESTS: Curriculum-Derived Student Subjects & Per-Student Attendance
    # =========================================================================

    def _setup_phase6_environment(self):
        """Helper to create Dept, 2 Teachers, 2 Subjects, 2 ClassSections, Enrollments, and Assignments."""
        with self.app.app_context():
            dept = Department(name="Computer Engineering", code="CO_P6")
            db.session.add(dept)
            db.session.commit()

            # Teacher 1 & Teacher 2
            t1_user = User(name="Prof. Verma", email="verma@vvp.edu", password_hash=generate_password_hash("p"), role="teacher")
            t2_user = User(name="Prof. Kulkarni", email="kulkarni_p6@vvp.edu", password_hash=generate_password_hash("p"), role="teacher")
            # Student 1 & Student 2
            s1_user = User(name="Aarav Mehta", email="aarav@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            s2_user = User(name="Diya Patil", email="diya@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            # Unenrolled student
            s3_user = User(name="Rohan Joshi", email="rohan@vvp.edu", password_hash=generate_password_hash("p"), role="student")

            db.session.add_all([t1_user, t2_user, s1_user, s2_user, s3_user])
            db.session.commit()

            t1_prof = TeacherProfile(user_id=t1_user.id, employee_id="EMP-V01", department_id=dept.id)
            t2_prof = TeacherProfile(user_id=t2_user.id, employee_id="EMP-K02", department_id=dept.id)

            s1_prof = StudentProfile(user_id=s1_user.id, roll_no="101", department_id=dept.id)
            s2_prof = StudentProfile(user_id=s2_user.id, roll_no="102", department_id=dept.id)
            s3_prof = StudentProfile(user_id=s3_user.id, roll_no="103", department_id=dept.id)

            sec_a = ClassSection(department_id=dept.id, name="TY-CO-A", academic_year="2026-27", semester=5, year_of_study=3)
            sec_b = ClassSection(department_id=dept.id, name="TY-CO-B", academic_year="2026-27", semester=5, year_of_study=3)

            subj_os = Subject(user_id=t1_user.id, name="Operating Systems", code="OS-501", department_id=dept.id, semester=5)
            subj_db = Subject(user_id=t2_user.id, name="Database Systems", code="DB-502", department_id=dept.id, semester=5)

            db.session.add_all([t1_prof, t2_prof, s1_prof, s2_prof, s3_prof, sec_a, sec_b, subj_os, subj_db])
            db.session.commit()

            # Enroll Student 1 and Student 2 in Section A
            enr1 = ClassEnrollment(student_id=s1_prof.id, class_section_id=sec_a.id, is_active=True)
            enr2 = ClassEnrollment(student_id=s2_prof.id, class_section_id=sec_a.id, is_active=True)

            # Assign Teacher 1 to OS in Section A
            assign1 = TeacherAssignment(teacher_id=t1_prof.id, subject_id=subj_os.id, class_section_id=sec_a.id)
            # Assign Teacher 2 to DB in Section B
            assign2 = TeacherAssignment(teacher_id=t2_prof.id, subject_id=subj_db.id, class_section_id=sec_b.id)

            db.session.add_all([enr1, enr2, assign1, assign2])
            db.session.commit()

            return {
                "t1_user_id": t1_user.id,
                "t2_user_id": t2_user.id,
                "s1_user_id": s1_user.id,
                "s2_user_id": s2_user.id,
                "s3_user_id": s3_user.id,
                "t1_prof_id": t1_prof.id,
                "t2_prof_id": t2_prof.id,
                "s1_prof_id": s1_prof.id,
                "s2_prof_id": s2_prof.id,
                "s3_prof_id": s3_prof.id,
                "sec_a_id": sec_a.id,
                "sec_b_id": sec_b.id,
                "subj_os_id": subj_os.id,
                "subj_db_id": subj_db.id,
            }

    def test_82_student_subjects_derived_from_class_enrollment_and_teacher_assignment(self):
        ids = self._setup_phase6_environment()
        self.client.post("/login", data={"email": "aarav@vvp.edu", "password": "p"})

        resp = self.client.get("/subjects")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Operating Systems", resp.data)
        self.assertIn(b"OS-501", resp.data)
        self.assertIn(b"Prof. Verma", resp.data)
        # Database Systems is assigned to Section B, so Aarav in Section A does not see it
        self.assertNotIn(b"Database Systems", resp.data)
        # No student self-add subject button
        self.assertNotIn(b"Add Subject", resp.data)

    def test_83_student_subjects_update_dynamically_with_curriculum_changes(self):
        ids = self._setup_phase6_environment()

        # Add Database Systems to Section A via TeacherAssignment
        with self.app.app_context():
            assign3 = TeacherAssignment(
                teacher_id=ids["t2_prof_id"],
                subject_id=ids["subj_db_id"],
                class_section_id=ids["sec_a_id"],
            )
            db.session.add(assign3)
            db.session.commit()

        # Student in Section A now sees both OS and DB
        self.client.post("/login", data={"email": "aarav@vvp.edu", "password": "p"})
        resp = self.client.get("/subjects")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Operating Systems", resp.data)
        self.assertIn(b"Database Systems", resp.data)

    def test_84_teacher_sees_only_own_assigned_subject_class_combinations(self):
        ids = self._setup_phase6_environment()
        # Teacher 1 (assigned to OS for Section A)
        self.client.post("/login", data={"email": "verma@vvp.edu", "password": "p"})

        resp = self.client.get("/teacher/attendance")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Operating Systems", resp.data)
        self.assertIn(b"TY-CO-A", resp.data)
        self.assertNotIn(b"Database Systems", resp.data)
        self.assertNotIn(b"TY-CO-B", resp.data)

    def test_85_teacher_views_roster_for_assigned_combination(self):
        ids = self._setup_phase6_environment()
        self.client.post("/login", data={"email": "verma@vvp.edu", "password": "p"})

        resp = self.client.get(f"/subjects/{ids['subj_os_id']}/sections/{ids['sec_a_id']}/attendance/mark")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Aarav Mehta", resp.data)
        self.assertIn(b"101", resp.data)
        self.assertIn(b"Diya Patil", resp.data)
        self.assertIn(b"102", resp.data)
        # Rohan is not enrolled in Section A
        self.assertNotIn(b"Rohan Joshi", resp.data)

    def test_86_teacher_marks_attendance_for_assigned_class(self):
        ids = self._setup_phase6_environment()
        self.client.post("/login", data={"email": "verma@vvp.edu", "password": "p"})

        today_str = date.today().isoformat()
        resp = self.client.post(
            f"/subjects/{ids['subj_os_id']}/sections/{ids['sec_a_id']}/attendance/mark",
            data={
                "date": today_str,
                f"status_{ids['s1_prof_id']}": "Present",
                f"status_{ids['s2_prof_id']}": "Absent",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)

        # Verify DB records
        with self.app.app_context():
            a1 = Attendance.query.filter_by(
                student_id=ids["s1_prof_id"],
                subject_id=ids["subj_os_id"],
                class_section_id=ids["sec_a_id"],
                date=date.today(),
            ).first()
            self.assertIsNotNone(a1)
            self.assertEqual(a1.status, "Present")

            a2 = Attendance.query.filter_by(
                student_id=ids["s2_prof_id"],
                subject_id=ids["subj_os_id"],
                class_section_id=ids["sec_a_id"],
                date=date.today(),
            ).first()
            self.assertIsNotNone(a2)
            self.assertEqual(a2.status, "Absent")

    def test_87_teacher_denied_403_for_unassigned_combination(self):
        ids = self._setup_phase6_environment()
        # Teacher 1 is NOT assigned to Section B / DB
        self.client.post("/login", data={"email": "verma@vvp.edu", "password": "p"})

        get_resp = self.client.get(f"/subjects/{ids['subj_db_id']}/sections/{ids['sec_b_id']}/attendance/mark")
        self.assertEqual(get_resp.status_code, 403)

        post_resp = self.client.post(
            f"/subjects/{ids['subj_db_id']}/sections/{ids['sec_b_id']}/attendance/mark",
            data={"date": date.today().isoformat()},
        )
        self.assertEqual(post_resp.status_code, 403)

    def test_88_duplicate_same_session_attendance_upsert_correction(self):
        ids = self._setup_phase6_environment()
        self.client.post("/login", data={"email": "verma@vvp.edu", "password": "p"})

        today_str = date.today().isoformat()
        # 1. Initial submission: Student 1 = Absent
        self.client.post(
            f"/subjects/{ids['subj_os_id']}/sections/{ids['sec_a_id']}/attendance/mark",
            data={
                "date": today_str,
                f"status_{ids['s1_prof_id']}": "Absent",
                f"status_{ids['s2_prof_id']}": "Absent",
            },
        )

        # 2. Correction submission for same session: Student 1 = Present
        self.client.post(
            f"/subjects/{ids['subj_os_id']}/sections/{ids['sec_a_id']}/attendance/mark",
            data={
                "date": today_str,
                f"status_{ids['s1_prof_id']}": "Present",
                f"status_{ids['s2_prof_id']}": "Absent",
            },
        )

        with self.app.app_context():
            # Total attendance rows for this subject+section+date must remain 2 (no duplicates)
            count = Attendance.query.filter_by(
                subject_id=ids["subj_os_id"],
                class_section_id=ids["sec_a_id"],
                date=date.today(),
            ).count()
            self.assertEqual(count, 2)

            updated = Attendance.query.filter_by(
                student_id=ids["s1_prof_id"],
                subject_id=ids["subj_os_id"],
                class_section_id=ids["sec_a_id"],
                date=date.today(),
            ).first()
            self.assertEqual(updated.status, "Present")

    def test_89_student_and_unauthenticated_blocked_from_marking_attendance(self):
        ids = self._setup_phase6_environment()

        # Unauthenticated -> redirect to login
        resp = self.client.get(f"/subjects/{ids['subj_os_id']}/sections/{ids['sec_a_id']}/attendance/mark", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login", resp.location)

        # Student -> 403
        self.client.post("/login", data={"email": "aarav@vvp.edu", "password": "p"})
        resp = self.client.get(f"/subjects/{ids['subj_os_id']}/sections/{ids['sec_a_id']}/attendance/mark")
        self.assertEqual(resp.status_code, 403)

    def test_90_shared_ownership_helper_unit_test(self):
        ids = self._setup_phase6_environment()
        with self.app.app_context():
            # Teacher 1 assigned to OS in Sec A -> True
            self.assertTrue(is_teacher_assigned_to_subject_and_class(ids["t1_user_id"], ids["subj_os_id"], ids["sec_a_id"]))
            # Teacher 1 not assigned to DB in Sec B -> False
            self.assertFalse(is_teacher_assigned_to_subject_and_class(ids["t1_user_id"], ids["subj_db_id"], ids["sec_b_id"]))
            # Student is not a teacher -> False
            self.assertFalse(is_teacher_assigned_to_subject_and_class(ids["s1_user_id"], ids["subj_os_id"], ids["sec_a_id"]))

    def test_91_student_can_view_own_subject_attendance(self):
        ids = self._setup_phase6_environment()

        # Log attendance
        with self.app.app_context():
            att = Attendance(
                student_id=ids["s1_prof_id"],
                subject_id=ids["subj_os_id"],
                class_section_id=ids["sec_a_id"],
                date=date.today() - timedelta(days=1),
                status="Present",
            )
            db.session.add(att)
            db.session.commit()

        self.client.post("/login", data={"email": "aarav@vvp.edu", "password": "p"})
        resp = self.client.get(f"/subjects/{ids['subj_os_id']}/attendance")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Operating Systems", resp.data)
        self.assertIn(b"100.0%", resp.data)

    def test_92_student_without_enrollment_sees_empty_subjects_list(self):
        ids = self._setup_phase6_environment()
        # Rohan is not enrolled in any class section
        self.client.post("/login", data={"email": "rohan@vvp.edu", "password": "p"})
        resp = self.client.get("/subjects")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"No Subjects Allocated", resp.data)


if __name__ == "__main__":
    unittest.main()



