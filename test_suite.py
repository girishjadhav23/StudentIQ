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
from routes.attendance import calculate_subject_attendance, calculate_overall_attendance


class TestStudentIQ(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        self.app.config["WTF_CSRF_ENABLED"] = False
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
            user = User(name="Owner", email="o@vvp.edu", password_hash=generate_password_hash("pass"), role="student")
            db.session.add(user)
            db.session.commit()
            uid = user.id

        self.client.post("/login", data={"email": "o@vvp.edu", "password": "pass"})
        
        # Add subject
        add_resp = self.client.post("/subjects/add", data={"name": "Data Structures", "code": "DS-301"}, follow_redirects=True)
        self.assertEqual(add_resp.status_code, 200)
        self.assertIn(b"Data Structures", add_resp.data)

        with self.app.app_context():
            subj = Subject.query.filter_by(user_id=uid, name="Data Structures").first()
            self.assertIsNotNone(subj)
            sid = subj.id

        # Edit subject
        edit_resp = self.client.post(f"/subjects/{sid}/edit", data={"name": "Advanced Data Structures", "code": "ADS-301"}, follow_redirects=True)
        self.assertEqual(edit_resp.status_code, 200)
        self.assertIn(b"Advanced Data Structures", edit_resp.data)

        # Delete subject
        del_resp = self.client.post(f"/subjects/{sid}/delete", follow_redirects=True)
        self.assertEqual(del_resp.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(Subject.query.get(sid))

    def test_12_subject_ownership_isolation(self):
        with self.app.app_context():
            u1 = User(name="U1", email="u1@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            u2 = User(name="U2", email="u2@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add_all([u1, u2])
            db.session.commit()

            s1 = Subject(user_id=u1.id, name="U1 Subject")
            db.session.add(s1)
            db.session.commit()
            s1_id = s1.id

        # U2 logs in and tries to edit U1's subject
        self.client.post("/login", data={"email": "u2@vvp.edu", "password": "p"})
        resp = self.client.get(f"/subjects/{s1_id}/edit")
        self.assertEqual(resp.status_code, 404)

    def test_13_attendance_logging_and_calculations(self):
        with self.app.app_context():
            u = User(name="Att User", email="att@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()
            s = Subject(user_id=u.id, name="Physics")
            db.session.add(s)
            db.session.commit()
            sid = s.id
            uid = u.id

        self.client.post("/login", data={"email": "att@vvp.edu", "password": "p"})
        d1 = date.today() - timedelta(days=2)
        d2 = date.today() - timedelta(days=1)

        self.client.post(f"/subjects/{sid}/attendance/add", data={"date": str(d1), "status": "Present"}, follow_redirects=True)
        self.client.post(f"/subjects/{sid}/attendance/add", data={"date": str(d2), "status": "Absent"}, follow_redirects=True)

        with self.app.app_context():
            stats = calculate_subject_attendance(sid)
            self.assertEqual(stats["total_classes"], 2)
            self.assertEqual(stats["present_classes"], 1)
            self.assertEqual(stats["absent_classes"], 1)
            self.assertEqual(stats["percentage"], 50.0)

            overall = calculate_overall_attendance(uid)
            self.assertEqual(overall, 50.0)

    def test_14_future_attendance_rejected(self):
        with self.app.app_context():
            u = User(name="Future Att", email="fut@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()
            s = Subject(user_id=u.id, name="Math")
            db.session.add(s)
            db.session.commit()
            sid = s.id

        self.client.post("/login", data={"email": "fut@vvp.edu", "password": "p"})
        future_date = date.today() + timedelta(days=5)
        resp = self.client.post(f"/subjects/{sid}/attendance/add", data={"date": str(future_date), "status": "Present"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"cannot be in the future", resp.data)

    def test_15_duplicate_date_attendance_rejected(self):
        with self.app.app_context():
            u = User(name="Dup Att", email="dup@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()
            s = Subject(user_id=u.id, name="Math")
            db.session.add(s)
            db.session.commit()
            sid = s.id

        self.client.post("/login", data={"email": "dup@vvp.edu", "password": "p"})
        d = date.today() - timedelta(days=1)
        self.client.post(f"/subjects/{sid}/attendance/add", data={"date": str(d), "status": "Present"})
        resp = self.client.post(f"/subjects/{sid}/attendance/add", data={"date": str(d), "status": "Absent"})
        self.assertIn(b"already exists", resp.data)

    def test_16_delete_attendance_record(self):
        with self.app.app_context():
            u = User(name="Del Att", email="del@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()
            s = Subject(user_id=u.id, name="Math")
            db.session.add(s)
            db.session.commit()
            att = Attendance(subject_id=s.id, date=date.today() - timedelta(days=1), status="Present")
            db.session.add(att)
            db.session.commit()
            aid = att.id
            sid = s.id

        self.client.post("/login", data={"email": "del@vvp.edu", "password": "p"})
        resp = self.client.post(f"/subjects/{sid}/attendance/{aid}/delete", follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(Attendance.query.get(aid))

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
            u = User(name="Sub User", email="sub@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

        self.client.post("/login", data={"email": "sub@vvp.edu", "password": "p"})
        resp = self.client.post("/subjects/add", data={"name": "", "code": "101"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Subject name is required", resp.data)

    def test_30_edit_subject_requires_name(self):
        with self.app.app_context():
            u = User(name="Sub User", email="sub2@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()
            s = Subject(user_id=u.id, name="OS")
            db.session.add(s)
            db.session.commit()
            sid = s.id

        self.client.post("/login", data={"email": "sub2@vvp.edu", "password": "p"})
        resp = self.client.post(f"/subjects/{sid}/edit", data={"name": ""})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Subject name is required", resp.data)

    def test_31_delete_nonexistent_subject_404(self):
        with self.app.app_context():
            u = User(name="Sub User", email="sub3@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()

        self.client.post("/login", data={"email": "sub3@vvp.edu", "password": "p"})
        resp = self.client.post("/subjects/99999/delete")
        self.assertEqual(resp.status_code, 404)

    def test_32_delete_nonexistent_attendance_404(self):
        with self.app.app_context():
            u = User(name="Sub User", email="sub4@vvp.edu", password_hash=generate_password_hash("p"), role="student")
            db.session.add(u)
            db.session.commit()
            s = Subject(user_id=u.id, name="DBMS")
            db.session.add(s)
            db.session.commit()
            sid = s.id

        self.client.post("/login", data={"email": "sub4@vvp.edu", "password": "p"})
        resp = self.client.post(f"/subjects/{sid}/attendance/99999/delete")
        self.assertEqual(resp.status_code, 404)

    # =========================================================================
    # PHASE 2 TESTS: Admin Foundation & Authorization
    # =========================================================================

    def test_33_cli_create_admin_new_user(self):
        runner = CliRunner()
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

        runner = CliRunner()
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


if __name__ == "__main__":
    unittest.main()
