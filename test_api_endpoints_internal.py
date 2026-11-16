import os
import sys
import time
from database import SessionLocal
import models
import schemas
import auth
from main import (
    health_check,
    root,
    get_subjects,
    get_student_topics,
    get_quiz_questions,
    batch_submit_quiz,
    get_student_dashboard,
    get_student_risk,
    get_student_recommendations,
    verify_student_access,
    register,
    login
)
from fastapi import HTTPException

def run_tests():
    print("=" * 70)
    print("EDUINSIGHT AI - PHASE 2 BACKEND ENDPOINT VERIFICATION")
    print("=" * 70)
    db = SessionLocal()

    # 1. Health Checks
    print("\n[TEST 1] Testing /health and /api/health...")
    h = health_check()
    assert h["status"] == "online"
    assert h["database"] == "connected"
    print(f"  ✓ /health: status={h['status']}, db={h['database']}")
    print(f"  ✓ Model fallback status: {h['models']}")

    r = root()
    assert r["status"] == "online"
    print(f"  ✓ / (root): name='{r['name']}', status={r['status']}")

    # 2. Authentication: Register
    unique_email = f"phase2_student_{int(time.time())}@eduinsight.ai"
    print(f"\n[TEST 2] Testing /api/auth/register with email: {unique_email}...")
    reg_req = schemas.UserRegister(
        name="Phase2 Production Student",
        email=unique_email,
        password="TestPassword123!",
        role="STUDENT"
    )
    reg_res = register(user_in=reg_req, db=db)
    assert reg_res["access_token"] is not None
    token = reg_res["access_token"]
    student_id = reg_res["student_id"]
    user_id = reg_res["user_id"]
    print(f"  ✓ Student registered: student_id={student_id}")

    # 3. Authentication: Login
    print("\n[TEST 3] Testing /api/auth/login...")
    login_req = schemas.UserLogin(email=unique_email, password="TestPassword123!")
    login_res = login(login_in=login_req, db=db)
    assert login_res["access_token"] is not None
    assert login_res["token_type"] == "bearer"
    assert login_res["student_id"] == student_id
    print(f"  ✓ Login successful, JWT issued (token_type={login_res['token_type']})")

    # 4. User Profile & Token Verification
    print("\n[TEST 4] Testing User Profile & Token Auth Context...")
    user = auth.get_current_user(token=token, db=db)
    student = auth.get_current_student(current_user=user, db=db)
    assert user.email == unique_email
    assert student.id == student_id
    print(f"  ✓ Token decoded: user='{user.name}', student_id={student.id}")

    # 5. Subjects Endpoint
    print("\n[TEST 5] Testing /api/subjects...")
    subjects = get_subjects(db=db)
    assert len(subjects) >= 4, f"Expected at least 4 subjects, found {len(subjects)}"
    print(f"  ✓ /api/subjects returned {len(subjects)} academic subjects:")
    for s in subjects:
        print(f"     - [{s['icon']}] {s['name']}: {s['topic_count']} topics, {s['question_count']} questions")

    # 6. Topics Endpoint
    print(f"\n[TEST 6] Testing /api/student/{student_id}/topics...")
    topics_data = get_student_topics(student_id=student_id, current_user=user, db=db)
    topics = topics_data.get("topics", [])
    assert len(topics) >= 10, f"Expected >= 10 topics, got {len(topics)}"
    print(f"  ✓ /api/student/{student_id}/topics returned {len(topics)} topics across all subjects (total_topics={topics_data['total_topics']})")

    # 7. Quiz Generation Endpoint
    target_skill_id = 45 # Equation Solving
    print(f"\n[TEST 7] Testing /api/student/{student_id}/quiz (skill_id={target_skill_id})...")
    questions = get_quiz_questions(student_id=student_id, skill_id=target_skill_id, current_user=user, db=db)
    assert len(questions) > 0
    print(f"  ✓ Generated {len(questions)} questions for skill {target_skill_id} ({questions[0]['skill_name']})")

    # 8. Quiz Submission (Batch Submit)
    print(f"\n[TEST 8] Testing /api/student/{student_id}/quiz/batch-submit...")
    q1 = questions[0]
    sub_payload = schemas.BatchQuizSubmission(
        skill_id=target_skill_id,
        total_questions=2,
        answers=[
            schemas.BatchAnswerItem(question_id=q1["id"], selected_option="A", ms_first_response=4200.0, hint_count=0),
            schemas.BatchAnswerItem(question_id=questions[1]["id"], selected_option="B", ms_first_response=7500.0, hint_count=1)
        ]
    )
    submit_res = batch_submit_quiz(student_id=student_id, submission=sub_payload, current_user=user, db=db)
    assert "new_mastery" in submit_res
    print(f"  ✓ Quiz submitted: score={submit_res['score']}/{submit_res['total']} ({submit_res['percentage']}%)")
    print(f"  ✓ New mastery calculated: {submit_res['new_mastery']}% ({submit_res['mastery_label']})")
    print(f"  ✓ Risk Level: {submit_res['risk_level']}")

    # 9. Dashboard Analytics Endpoint
    print(f"\n[TEST 9] Testing /api/student/{student_id}/dashboard...")
    dash = get_student_dashboard(student_id=student_id, current_user=user, db=db)
    assert "analytics" in dash
    assert "overall_progress" in dash
    assert "charts" in dash
    assert "recommendations" in dash
    print(f"  ✓ Dashboard metrics: topics_attempted={dash['topics_attempted']}, overall_mastery={dash['overall_mastery']}%")

    # 10. Risk Prediction Endpoint
    print(f"\n[TEST 10] Testing /api/student/{student_id}/risk...")
    risk = get_student_risk(student_id=student_id, current_user=user, db=db)
    assert risk["has_activity"] is True
    assert len(risk["concept_risks"]) == 1, f"Expected 1 attempted concept, found {len(risk['concept_risks'])}"
    print(f"  ✓ Dynamic Risk: {len(risk['concept_risks'])} concept evaluated ({risk['concept_risks'][0]['skill_name']} -> {risk['concept_risks'][0]['risk_level']} Risk)")

    # 11. Recommendations Endpoint
    print(f"\n[TEST 11] Testing /api/student/{student_id}/recommendations...")
    recs = get_student_recommendations(student_id=student_id, current_user=user, db=db)
    assert len(recs) >= 1
    print(f"  ✓ Recommendations: {len(recs)} generated, top priority='{recs[0]['priority']}' for '{recs[0]['skill_name']}'")

    # 12. Security & Data Isolation
    print("\n[TEST 12] Testing Security Authorization Rules...")
    # Attempt cross-student access with this student's auth
    try:
        verify_student_access(current_user=user, student_id=99999, db=db)
        assert False, "Should have raised HTTP 403"
    except HTTPException as e:
        assert e.status_code == 403
        print("  ✓ Cross-student data access correctly blocked with HTTP 403 Forbidden")

    # Attempt with fake/invalid token
    try:
        auth.get_current_user(token="invalid_jwt_token_xyz", db=db)
        assert False, "Should have raised HTTP 401"
    except HTTPException as e:
        assert e.status_code == 401
        print("  ✓ Invalid JWT credentials correctly rejected with HTTP 401 Unauthorized")

    # Clean up test user
    print("\n[CLEANUP] Cleaning up test student data...")
    db.query(models.Interaction).filter(models.Interaction.student_id == student_id).delete()
    db.query(models.QuizAttempt).filter(models.QuizAttempt.student_id == student_id).delete()
    db.query(models.StudentSkillMastery).filter(models.StudentSkillMastery.student_id == student_id).delete()
    db.query(models.Prediction).filter(models.Prediction.student_id == student_id).delete()
    db.query(models.Student).filter(models.Student.id == student_id).delete()
    db.query(models.User).filter(models.User.id == user_id).delete()
    db.commit()
    db.close()
    print("  ✓ Test student data cleanly purged.")

    print("\n" + "=" * 70)
    print("ALL 12 BACKEND API & PRODUCTION REQUIREMENTS VERIFIED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    run_tests()
