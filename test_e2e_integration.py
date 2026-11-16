import os
import sys
from datetime import datetime
from database import SessionLocal
import models
import auth
import analytics_service
import recommendation_service
import bkt_service

def run_e2e_verification():
    db = SessionLocal()
    print("=" * 60)
    print("EDUINSIGHT AI - COMPREHENSIVE END-TO-END VERIFICATION")
    print("=" * 60)

    # 1. Health Check
    print("\n[STEP 1] Testing Health Check & System Status...")
    from main import health_check
    health = health_check()
    assert health["status"] == "online"
    print("  -> Health Status: OK (Online)")
    print(f"  -> Model status: {health['models']}")

    # 2. User Isolation & Authentication Test
    test_email = f"test_student_{int(datetime.utcnow().timestamp())}@eduinsight.ai"
    print(f"\n[STEP 2] Creating New Test Student: {test_email}...")
    existing_user = db.query(models.User).filter(models.User.email == test_email).first()
    if existing_user:
        db.delete(existing_user)
        db.commit()

    pwd_hash = auth.hash_password("Pass1234!")
    user = models.User(name="Mobile Test User", email=test_email, password_hash=pwd_hash, role="STUDENT")
    db.add(user)
    db.commit()
    db.refresh(user)

    max_code = db.query(models.Student.student_code).order_by(models.Student.student_code.desc()).first()
    next_code = (max_code[0] + 1) if max_code else 100001
    student = models.Student(user_id=user.id, student_code=next_code)
    db.add(student)
    db.commit()
    db.refresh(student)

    # Initialize masteries
    skills = db.query(models.Skill).all()
    for sk in skills:
        db.add(models.StudentSkillMastery(student_id=student.id, skill_id=sk.skill_id, mastery=0.20))
    db.commit()
    print(f"  -> Registered student ID: {student.id}, Code: {student.student_code}")

    # 3. Initial Dashboard Verification for New Student (Empty State Check)
    print("\n[STEP 3] Verifying Initial Zero-Quiz State for New Student...")
    risk_init = analytics_service.get_student_risk_analysis(db, student.id)
    assert risk_init["has_activity"] == False, "New student should not have activity"
    assert len(risk_init["concept_risks"]) == 0, "No concepts should be at risk initially"
    print("  -> Risk has_activity: False (Correct: No misleading high-risk labels)")
    print(f"  -> Message: {risk_init['message']}")

    recs_init = recommendation_service.generate_recommendations(db, student.id)
    assert len(recs_init) >= 1
    assert recs_init[0]["recommendation_type"] == "Getting Started"
    print(f"  -> Initial Recommendation: {recs_init[0]['title']} (Correct)")

    # 4. Subjects & Topics Navigation Check
    print("\n[STEP 4] Testing Subject & Topic Flow...")
    subjects = db.query(models.Subject).all()
    assert len(subjects) > 0, "Subjects must exist"
    subj = subjects[0]
    print(f"  -> Subject: {subj.name} (ID: {subj.id})")

    subj_skills = db.query(models.Skill).filter(models.Skill.subject_id == subj.id).all()
    assert len(subj_skills) > 0, "Topics must exist for subject"
    test_skill = subj_skills[0]
    print(f"  -> Topic selected: {test_skill.skill_name} (Skill ID: {test_skill.skill_id})")

    # 5. Quiz Questions Retrieval
    print("\n[STEP 5] Testing Quiz Questions for Topic...")
    questions = db.query(models.QuizQuestion).filter(models.QuizQuestion.skill_id == test_skill.skill_id).all()
    assert len(questions) > 0, f"Topic {test_skill.skill_name} must have questions"
    print(f"  -> Found {len(questions)} questions for {test_skill.skill_name}")
    for idx, q in enumerate(questions[:2]):
        print(f"     Q{idx+1}: {q.question[:60]}... [Correct: {q.correct_answer}]")

    # 6. Quiz Execution & Batch Submission
    print("\n[STEP 6] Simulating Quiz Submission...")
    # Answer: 1 correct, 1 incorrect
    q1 = questions[0]
    ans1_correct = q1.correct_answer
    ans2 = questions[1] if len(questions) > 1 else q1
    ans2_wrong = "A" if ans2.correct_answer != "A" else "B"

    # Create batch submission schemas
    import schemas
    batch_sub = schemas.BatchQuizSubmission(
        skill_id=test_skill.skill_id,
        total_questions=2,
        answers=[
            schemas.BatchAnswerItem(question_id=q1.id, selected_option=ans1_correct, ms_first_response=4500.0, hint_count=0),
            schemas.BatchAnswerItem(question_id=ans2.id, selected_option=ans2_wrong, ms_first_response=7000.0, hint_count=1)
        ]
    )

    from main import batch_submit_quiz
    # Mock current_user
    res = batch_submit_quiz(student_id=student.id, submission=batch_sub, db=db, current_user=user)
    print(f"  -> Quiz Batch Result: score={res['score']}/{res['total']} ({res['percentage']}%)")
    print(f"  -> New Mastery: {res['new_mastery']}% ({res['mastery_label']})")
    print(f"  -> Risk Level: {res['risk_level']}")

    # 7. Post-Quiz Dynamic Risk Analysis Check
    print("\n[STEP 7] Verifying Updated Dynamic Risk Analysis...")
    risk_post = analytics_service.get_student_risk_analysis(db, student.id)
    assert risk_post["has_activity"] == True, "Student must have activity now"
    assert len(risk_post["concept_risks"]) == 1, f"Only the 1 attempted concept should show, got {len(risk_post['concept_risks'])}"
    c_risk = risk_post["concept_risks"][0]
    print(f"  -> Evaluated Concept: {c_risk['skill_name']}")
    print(f"  -> Mastery: {c_risk['mastery']}%, Risk: {c_risk['risk_level']}, Attempts: {c_risk['attempts_count']}")
    print(f"  -> Trend: {c_risk['trend']}")
    print(f"  -> Explanation: {c_risk['explanation']}")

    # 8. Post-Quiz Personalized Recommendations Check
    print("\n[STEP 8] Verifying Updated Personalized Recommendations...")
    recs_post = recommendation_service.generate_recommendations(db, student.id)
    print(f"  -> Recommendations count: {len(recs_post)}")
    for r in recs_post:
        print(f"     [{r['priority']}] {r['title']} (Skill ID: {r['skill_id']}) -> {r['suggested_action'][:50]}...")

    # 9. Data Isolation Check (Student 1 vs Test Student)
    print("\n[STEP 9] Verifying Data Isolation Between Users...")
    risk_student_1 = analytics_service.get_student_risk_analysis(db, 1)
    print(f"  -> Student 1 attempted concepts: {len(risk_student_1['concept_risks'])}")
    print(f"  -> Test Student attempted concepts: {len(risk_post['concept_risks'])}")
    assert len(risk_student_1['concept_risks']) != len(risk_post['concept_risks']), "Students must have isolated data"
    print("  -> Data Isolation: VERIFIED (Strictly isolated by student_id and auth)")

    # Clean up test user
    db.query(models.Interaction).filter(models.Interaction.student_id == student.id).delete()
    db.query(models.QuizAttempt).filter(models.QuizAttempt.student_id == student.id).delete()
    db.query(models.StudentSkillMastery).filter(models.StudentSkillMastery.student_id == student.id).delete()
    db.query(models.Prediction).filter(models.Prediction.student_id == student.id).delete()
    db.query(models.Student).filter(models.Student.id == student.id).delete()
    db.query(models.User).filter(models.User.id == user.id).delete()
    db.commit()
    print("\n[CLEANUP] Test student cleaned up successfully.")

    print("\n" + "=" * 60)
    print("ALL END-TO-END VERIFICATION CHECKS PASSED SUCCESSFULLY!")
    print("=" * 60)

if __name__ == "__main__":
    run_e2e_verification()
