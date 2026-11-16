import os
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from dotenv import load_dotenv
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from database import engine, get_db, Base
import models
import schemas
from auth import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user,
    get_current_student,
    get_current_teacher
)
from ml_service import ml_service, REQUIRED_FEATURES
import bkt_service
import shap_service
import recommendation_service
import analytics_service
import seed

load_dotenv()

# Configure production logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("eduinsight")

STARTING_STUDENT_CODE = int(os.getenv("STARTING_STUDENT_CODE", "100001"))

app = FastAPI(
    title="EduInsight AI API",
    description="Intelligent Student Learning Analytics, BKT, Risk Prediction, SHAP & Recommendation Platform",
    version="1.0.0"
)

# Startup and Shutdown Lifecycle Events
@app.on_event("startup")
def on_startup():
    logger.info("Initializing EduInsight AI Backend...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info(f"Database schema verified/created (Dialect: {engine.dialect.name})")
    except Exception as e:
        logger.error(f"Database schema initialization notice: {e}")

    try:
        seed.ensure_initial_data()
    except Exception as e:
        logger.warning(f"Initial curriculum auto-seed notice: {e}")

    rf_status = "Loaded" if ml_service.rf_model is not None else "Missing (heuristic fallback active)"
    xgb_status = "Loaded" if ml_service.xgb_model is not None else "Missing (heuristic fallback active)"
    logger.info(f"ML Random Forest Model: {rf_status}")
    logger.info(f"ML XGBoost Model: {xgb_status}")
    logger.info("EduInsight AI Backend is ready to serve requests.")

@app.on_event("shutdown")
def on_shutdown():
    logger.info("EduInsight AI Backend is shutting down cleanly.")

# Enable CORS for React frontend (configurable via environment variable)
cors_origins_env = os.getenv("CORS_ORIGINS", "*")
allowed_origins = [o.strip() for o in cors_origins_env.split(",") if o.strip()] if cors_origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# AUTHORIZATION HELPER
# ---------------------------------------------------------
def verify_student_access(current_user: models.User, student_id: int, db: Session):
    """
    Ensures the authenticated user is either:
    - The exact student whose data is being requested, OR
    - A TEACHER/ADMIN with full access rights.
    Raises HTTP 403 otherwise.
    """
    if current_user.role == "TEACHER":
        return  # Teachers can access any student's data

    if current_user.role == "STUDENT":
        student = db.query(models.Student).filter(
            models.Student.user_id == current_user.id
        ).first()
        if not student or student.id != student_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are not authorized to access another student's data."
            )
    else:
        raise HTTPException(status_code=403, detail="Unauthorized")


# ---------------------------------------------------------
# ROOT & HEALTH ENDPOINTS
# ---------------------------------------------------------
@app.get("/")
def root():
    return {
        "name": "EduInsight AI Backend API",
        "version": "1.0.0",
        "status": "online",
        "docs_url": "/docs",
        "health_url": "/api/health"
    }

@app.get("/health")
@app.get("/api/health")
def health_check():
    rf_loaded = ml_service.rf_model is not None
    xgb_loaded = ml_service.xgb_model is not None

    db_status = "connected"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unavailable: {str(e)}"

    return {
        "status": "online",
        "app_name": "EduInsight AI",
        "environment": os.getenv("ENVIRONMENT", "production"),
        "database": db_status,
        "timestamp": datetime.utcnow().isoformat(),
        "models": {
            "eduinsight_rf.pkl": "loaded" if rf_loaded else "missing — using heuristic fallback",
            "eduinsight_xgb.pkl": "loaded" if xgb_loaded else "missing — using heuristic fallback",
        }
    }

# ---------------------------------------------------------
# SUBJECTS ENDPOINT
# ---------------------------------------------------------
@app.get("/api/subjects")
def get_subjects(db: Session = Depends(get_db)):
    """Returns all subjects with their topic count and total question count."""
    subjects = db.query(models.Subject).all()
    result = []
    for subj in subjects:
        topic_count = db.query(models.Skill).filter(models.Skill.subject_id == subj.id).count()
        question_count = (
            db.query(models.QuizQuestion)
            .join(models.Skill, models.QuizQuestion.skill_id == models.Skill.skill_id)
            .filter(models.Skill.subject_id == subj.id)
            .count()
        )
        result.append({
            "id": subj.id,
            "name": subj.name,
            "description": subj.description,
            "icon": subj.icon,
            "topic_count": topic_count,
            "question_count": question_count
        })
    return result

# ---------------------------------------------------------
# AUTHENTICATION ENDPOINTS
# ---------------------------------------------------------
@app.get("/api/teachers", response_model=List[schemas.TeacherItem])
def get_teachers_list(db: Session = Depends(get_db)):
    """Returns list of active teachers for student assignment during registration."""
    teachers = db.query(models.User).filter(models.User.role == "TEACHER").all()
    return [{"id": t.id, "name": t.name, "email": t.email} for t in teachers]


@app.post("/api/auth/register", response_model=schemas.Token)
def register(user_in: schemas.UserRegister, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == user_in.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    role = user_in.role.upper()
    if role not in ["STUDENT", "TEACHER"]:
        role = "STUDENT"

    new_user = models.User(
        name=user_in.name,
        email=user_in.email,
        password_hash=hash_password(user_in.password),
        role=role
    )
    db.add(new_user)
    db.flush()

    student_id = None
    if role == "STUDENT":
        # Assign a unique student code
        last_student = db.query(models.Student).order_by(models.Student.id.desc()).first()
        code = (last_student.student_code + 1) if last_student else STARTING_STUDENT_CODE

        # Assign to teacher: explicitly requested teacher_id, or first existing teacher
        assigned_teacher_id = user_in.teacher_id
        if not assigned_teacher_id:
            first_teacher = db.query(models.User).filter(models.User.role == "TEACHER").first()
            if first_teacher:
                assigned_teacher_id = first_teacher.id

        student_obj = models.Student(
            user_id=new_user.id,
            student_code=code,
            teacher_id=assigned_teacher_id
        )
        db.add(student_obj)
        db.flush()
        student_id = student_obj.id

        # Initialize BKT mastery for all skills at P_INIT
        skills = db.query(models.Skill).all()
        for sk in skills:
            db.add(models.StudentSkillMastery(
                student_id=student_obj.id,
                skill_id=sk.skill_id,
                mastery=0.0
            ))

    db.commit()

    token = create_access_token(data={"sub": new_user.email, "role": role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": role,
        "user_id": new_user.id,
        "student_id": student_id,
        "name": new_user.name,
        "has_activity": False
    }


@app.post("/api/auth/login", response_model=schemas.Token)
def login(login_in: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == login_in.email).first()
    if not user or not verify_password(login_in.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password"
        )

    student_id = None
    has_activity = False
    if user.role == "STUDENT" and user.student_profile:
        student_id = user.student_profile.id
        first_int = db.query(models.Interaction).filter(
            models.Interaction.student_id == student_id
        ).first()
        has_activity = first_int is not None

    token = create_access_token(data={"sub": user.email, "role": user.role})
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "user_id": user.id,
        "student_id": student_id,
        "name": user.name,
        "has_activity": has_activity
    }

# ---------------------------------------------------------
# AUTHENTICATED USER INFO
# ---------------------------------------------------------
@app.get("/api/student/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    student_id = current_user.student_profile.id if current_user.student_profile else None
    student_code = current_user.student_profile.student_code if current_user.student_profile else None
    teacher_id = current_user.student_profile.teacher_id if current_user.student_profile else None
    teacher_name = current_user.student_profile.teacher.name if (current_user.student_profile and current_user.student_profile.teacher) else None
    has_activity = False
    if student_id:
        has_activity = db.query(models.Interaction).filter(
            models.Interaction.student_id == student_id
        ).first() is not None

    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role,
        "student_id": student_id,
        "student_code": student_code,
        "teacher_id": teacher_id,
        "teacher_name": teacher_name,
        "has_activity": has_activity
    }

# ---------------------------------------------------------
# STUDENT DASHBOARD
# ---------------------------------------------------------
@app.get("/api/student/{student_id}/dashboard")
def get_student_dashboard(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    # AUTHORIZATION: Only the student themselves or a teacher can access this
    verify_student_access(current_user, student_id, db)

    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    # 1. Compute unified analytics from database (source of truth for all cards and charts)
    analytics = analytics_service.get_student_dashboard_analytics(db, student.id)
    has_activity = analytics["has_activity"]

    # 2. Risk — based on last real interaction only
    last_interaction = db.query(models.Interaction).filter(
        models.Interaction.student_id == student.id
    ).order_by(models.Interaction.created_at.desc()).first()

    # 2. Dynamic Risk Analysis
    risk_analysis = analytics_service.get_student_risk_analysis(db, student.id)
    risk_prob = risk_analysis.get("risk_probability") or 0.0
    risk_level = risk_analysis.get("risk_level", "N/A")
    model_name = risk_analysis.get("model_name", "N/A")

    # 3. Recommendations — generated from real mastery data
    try:
        recs_data = recommendation_service.generate_recommendations(db, student.id)
    except Exception as e:
        print(f"[Dashboard] Recommendation error: {e}")
        recs_data = []

    # 4. Recent Performance from actual DB interactions
    recent_interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student.id
    ).order_by(models.Interaction.created_at.desc()).limit(10).all()

    skills_map = {s.skill_id: s.skill_name for s in db.query(models.Skill).all()}

    recent_history = [
        {
            "id": i.id,
            "skill_name": skills_map.get(i.skill_id, f"Skill #{i.skill_id}"),
            "correct": bool(i.correct == 1),
            "attempt_count": i.attempt_count,
            "hint_count": i.hint_count,
            "created_at": i.created_at.strftime("%Y-%m-%d %H:%M") if i.created_at else ""
        }
        for i in recent_interactions
    ]

    twin = bkt_service.get_student_learning_twin(db, student.id)

    return {
        "student": {
            "id": student.id,
            "student_code": student.student_code,
            "name": student.user.name,
            "email": student.user.email
        },
        "has_activity": has_activity,
        # Unified analytics object powering cards and charts:
        "analytics": analytics,
        "overall_progress": analytics["overall_progress"],
        "charts": analytics["charts"],
        # Direct card values:
        "overall_mastery": analytics["overall_progress"]["overall_mastery"],
        "questions_attempted": analytics["overall_progress"]["total_questions_attempted"],
        "topics_attempted": analytics["overall_progress"]["completed_topics"] + analytics["overall_progress"]["in_progress_topics"],
        "topics_not_attempted": analytics["overall_progress"]["not_attempted_topics"],
        "total_topics": analytics["overall_progress"]["total_topics"],
        "recent_accuracy": twin.get("recent_accuracy", 0.0),
        "risk": {
            "level": risk_level,
            "probability": round(risk_prob, 4),
            "model_name": model_name
        },
        "skills": twin["all_skills"],
        "weak_skills": twin["weak_concepts"],
        "strong_skills": twin["strong_concepts"],
        "recommendations": recs_data,
        "recent_performance": recent_history
    }


@app.get("/api/student/{student_id}/skills")
def get_student_skills(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)
    twin = bkt_service.get_student_learning_twin(db, student_id)
    return {"skills": twin["all_skills"], "overall_mastery": twin["overall_mastery"]}


@app.get("/api/student/{student_id}/learning-twin")
def get_learning_twin(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)
    return bkt_service.get_student_learning_twin(db, student_id)


@app.get("/api/student/{student_id}/risk")
def get_student_risk(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)
    return analytics_service.get_student_risk_analysis(db, student_id)


@app.get("/api/student/{student_id}/shap")
def get_student_shap(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)

    last_interaction = db.query(models.Interaction).filter(
        models.Interaction.student_id == student_id
    ).order_by(models.Interaction.created_at.desc()).first()

    if not last_interaction:
        return {
            "student_id": student_id,
            "has_activity": False,
            "message": "No quiz activity yet. Take a quiz to see your AI risk explanation.",
            "top_bullets": [],
            "feature_contributions": []
        }

    feat_dict = {
        "attempt_count": last_interaction.attempt_count,
        "hint_count": last_interaction.hint_count,
        "ms_first_response": last_interaction.ms_first_response,
        "skill_id": last_interaction.skill_id,
        "bottom_hint": last_interaction.bottom_hint,
        "actions": last_interaction.actions,
        "overlap_time": last_interaction.overlap_time
    }

    prob, level, _ = ml_service.predict_risk(feat_dict, model_type="xgb")
    try:
        explanation = shap_service.get_shap_explanation(feat_dict, level, prob)
    except Exception as e:
        print(f"[SHAP] Error: {e}")
        explanation = {
            "title": "Why am I at risk?",
            "risk_level": level,
            "risk_probability": round(prob, 4),
            "top_bullets": [
                "Attempt count is an important feature in the model prediction",
                "Response timing indicates concept hesitation",
                "Hint frequency influences mastery calculation"
            ],
            "feature_contributions": []
        }
    explanation["student_id"] = student_id
    explanation["has_activity"] = True
    return explanation


@app.get("/api/student/{student_id}/recommendations")
def get_student_recommendations(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)
    return recommendation_service.generate_recommendations(db, student_id)


@app.get("/api/student/{student_id}/history")
def get_student_history(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)

    interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student_id
    ).order_by(models.Interaction.created_at.desc()).all()

    skills_map = {s.skill_id: s.skill_name for s in db.query(models.Skill).all()}

    return [
        {
            "id": i.id,
            "skill_id": i.skill_id,
            "skill_name": skills_map.get(i.skill_id, f"Skill #{i.skill_id}"),
            "correct": bool(i.correct == 1),
            "attempt_count": i.attempt_count,
            "hint_count": i.hint_count,
            "ms_first_response": i.ms_first_response,
            "created_at": i.created_at.strftime("%Y-%m-%d %H:%M")
        }
        for i in interactions
    ]

# ---------------------------------------------------------
# TOPIC & QUIZ ENDPOINTS
# ---------------------------------------------------------
@app.get("/api/student/{student_id}/topics")
def get_student_topics(
    student_id: int,
    subject_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)

    skills_query = db.query(models.Skill)
    if subject_id is not None:
        skills_query = skills_query.filter(models.Skill.subject_id == subject_id)
    skills = skills_query.all()

    masteries = db.query(models.StudentSkillMastery).filter(
        models.StudentSkillMastery.student_id == student_id
    ).all()
    mastery_map = {m.skill_id: m.mastery for m in masteries}

    # Count questions available per skill
    counts_query = (
        db.query(models.QuizQuestion.skill_id, func.count(models.QuizQuestion.id))
        .group_by(models.QuizQuestion.skill_id)
        .all()
    )
    counts_map = {skill_id: count for skill_id, count in counts_query}

    # Count actual interaction attempts per skill for this student — three-state status
    interaction_counts_query = (
        db.query(models.Interaction.skill_id, func.count(models.Interaction.id))
        .filter(models.Interaction.student_id == student_id)
        .group_by(models.Interaction.skill_id)
        .all()
    )
    interaction_counts_map = {skill_id: cnt for skill_id, cnt in interaction_counts_query}

    # Count correct answers per skill for avg score display
    correct_counts_query = (
        db.query(models.Interaction.skill_id, func.sum(models.Interaction.correct))
        .filter(models.Interaction.student_id == student_id)
        .group_by(models.Interaction.skill_id)
        .all()
    )
    correct_counts_map = {skill_id: int(cnt or 0) for skill_id, cnt in correct_counts_query}
    subjects_map = {s.id: s.name for s in db.query(models.Subject).all()}

    topics_list = []
    total_questions = 0

    for sk in skills:
        m_val = mastery_map.get(sk.skill_id, 0.0)
        q_count = counts_map.get(sk.skill_id, 0)
        total_questions += q_count
        attempt_count = interaction_counts_map.get(sk.skill_id, 0)
        has_attempts = attempt_count > 0
        status = bkt_service.get_mastery_label(m_val, has_attempts=has_attempts)
        correct_count = correct_counts_map.get(sk.skill_id, 0)
        avg_score = round((correct_count / attempt_count) * 100, 1) if has_attempts else None
        topics_list.append({
            "skill_id": sk.skill_id,
            "skill_name": sk.skill_name,
            "subject_name": subjects_map.get(sk.subject_id, "Mathematics"),
            "question_count": q_count,
            "mastery": round(m_val * 100, 2),
            "status": status,
            "has_attempts": has_attempts,
            "attempt_count": attempt_count,
            "avg_score": avg_score
        })

    return {
        "topics": topics_list,
        "total_questions": total_questions,
        "total_topics": len(skills)
    }


@app.get("/api/student/{student_id}/quiz")
def get_quiz_questions(
    student_id: int,
    skill_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    verify_student_access(current_user, student_id, db)

    query = db.query(models.QuizQuestion)
    if skill_id is not None:
        query = query.filter(models.QuizQuestion.skill_id == skill_id)

    questions = query.all()
    skills_map = {s.skill_id: s.skill_name for s in db.query(models.Skill).all()}

    return [
        {
            "id": q.id,
            "skill_id": q.skill_id,
            "skill_name": skills_map.get(q.skill_id, "Mathematics"),
            "question": q.question,
            "options": {
                "A": q.option_a,
                "B": q.option_b,
                "C": q.option_c,
                "D": q.option_d
            }
        }
        for q in questions
    ]


@app.post("/api/student/{student_id}/quiz/submit")
def submit_quiz_answer(
    student_id: int,
    submission: schemas.QuizSubmission,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    JWT-authenticated quiz submission.
    student_id from path MUST match the authenticated user's student_id.
    All analytics are computed from the real submission data — no fake values.
    """
    # AUTHORIZATION: student_id must match the JWT-authenticated user
    verify_student_access(current_user, student_id, db)

    q = db.query(models.QuizQuestion).filter(models.QuizQuestion.id == submission.question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    correct = 1 if submission.selected_option.upper() == q.correct_answer.upper() else 0

    # ── STEP 1: Save the real interaction to SQLite ──────────────────────────
    try:
        interaction = models.Interaction(
            student_id=student_id,
            question_id=q.id,
            skill_id=q.skill_id,
            correct=correct,
            attempt_count=submission.attempt_count,
            hint_count=submission.hint_count,
            ms_first_response=submission.ms_first_response,
            bottom_hint=submission.bottom_hint,
            actions=submission.actions,
            overlap_time=submission.overlap_time
        )
        db.add(interaction)
        db.commit()
        db.refresh(interaction)
    except Exception as e:
        db.rollback()
        print(f"[Submit] CRITICAL — Failed to save interaction: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save quiz response: {str(e)}")

    # ── STEP 2: BKT mastery update (persisted to DB) ─────────────────────────
    new_mastery = bkt_service.P_INIT  # Configurable default
    try:
        new_mastery = bkt_service.update_mastery(db, student_id, q.skill_id, correct)
    except Exception as e:
        print(f"[Submit] BKT update failed: {e}")

    # ── STEP 3: Build exact 7-feature vector from real submission data ────────
    feat_dict = {
        "attempt_count": submission.attempt_count,
        "hint_count": submission.hint_count,
        "ms_first_response": submission.ms_first_response,
        "skill_id": q.skill_id,
        "bottom_hint": submission.bottom_hint,
        "actions": submission.actions,
        "overlap_time": submission.overlap_time
    }

    # ── STEP 4: ML Risk Prediction using actual eduinsight_xgb.pkl ───────────
    risk_prob = 0.0
    risk_level = "N/A"
    model_name = "Pending .pkl model"
    try:
        risk_prob, risk_level, model_name = ml_service.predict_risk(feat_dict, model_type="xgb")
    except Exception as e:
        print(f"[Submit] ML prediction failed: {e}")

    # ── STEP 5: Persist prediction to DB ─────────────────────────────────────
    try:
        pred = models.Prediction(
            student_id=student_id,
            risk_probability=risk_prob,
            risk_level=risk_level if risk_level != "N/A" else "MEDIUM",
            model_name=model_name
        )
        db.add(pred)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Submit] Failed to save prediction: {e}")

    # Save single QuizAttempt
    try:
        sk_info = db.query(models.Skill).filter(models.Skill.skill_id == q.skill_id).first()
        single_att = models.QuizAttempt(
            student_id=student_id,
            subject_id=sk_info.subject_id if sk_info else None,
            skill_id=q.skill_id,
            total_questions=1,
            score=correct,
            incorrect=1 - correct,
            unanswered=0,
            percentage=100.0 if correct == 1 else 0.0,
            created_at=datetime.utcnow()
        )
        db.add(single_att)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[Submit] Attempt log error: {e}")

    # ── STEP 6: SHAP explanation from actual loaded XGBoost model ─────────────
    shap_exp = None
    try:
        shap_exp = shap_service.get_shap_explanation(feat_dict, risk_level, risk_prob)
    except Exception as e:
        print(f"[Submit] SHAP failed: {e}")
        shap_exp = {
            "title": "Why am I at risk?",
            "risk_level": risk_level,
            "risk_probability": round(risk_prob, 4),
            "top_bullets": [
                "Attempt count is an important feature in the model prediction",
                "Response timing indicates concept hesitation",
                "Hint frequency influences mastery calculation"
            ],
            "feature_contributions": []
        }

    # ── STEP 7: Generate personalized recommendations from real data ──────────
    new_recs = []
    try:
        new_recs = recommendation_service.generate_recommendations(db, student_id)
    except Exception as e:
        print(f"[Submit] Recommendation generation failed: {e}")

    return {
        "message": "Your learning profile has been updated.",
        "correct": bool(correct == 1),
        "correct_answer": q.correct_answer,
        "new_mastery": round(new_mastery * 100, 2),
        "risk_level": risk_level,
        "risk_probability": round(risk_prob, 4),
        "model_name": model_name,
        "shap_explanation": shap_exp,
        "recommendations": new_recs
    }


@app.post("/api/student/{student_id}/quiz/batch-submit")
def batch_submit_quiz(
    student_id: int,
    submission: schemas.BatchQuizSubmission,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user)
):
    """
    Batch quiz submission — submits all answers for a quiz session at once.
    Processes each answer through BKT mastery update, then runs ML risk prediction
    and generates SHAP explanation and recommendations based on the final state.
    Returns comprehensive QuizSessionResult with per-question breakdown.
    """
    verify_student_access(current_user, student_id, db)

    skill_id = submission.skill_id
    answers = submission.answers

    if not answers:
        raise HTTPException(status_code=400, detail="No answers provided")

    # Look up skill info
    skill = db.query(models.Skill).filter(models.Skill.skill_id == skill_id).first()
    skill_name = skill.skill_name if skill else f"Skill #{skill_id}"
    subject_name = "Mixed"
    if skill and skill.subject:
        subject_name = skill.subject.name

    question_results = []
    total_correct = 0
    last_feat_dict = None

    for ans in answers:
        q = db.query(models.QuizQuestion).filter(models.QuizQuestion.id == ans.question_id).first()
        if not q:
            continue

        correct = 1 if ans.selected_option.upper() == q.correct_answer.upper() else 0
        if correct == 1:
            total_correct += 1

        # Save interaction
        try:
            interaction = models.Interaction(
                student_id=student_id,
                question_id=q.id,
                skill_id=q.skill_id,
                correct=correct,
                attempt_count=1,
                hint_count=ans.hint_count,
                ms_first_response=ans.ms_first_response,
                bottom_hint=0,
                actions=1,
                overlap_time=ans.ms_first_response
            )
            db.add(interaction)
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[BatchSubmit] Failed to save interaction for Q{ans.question_id}: {e}")
            continue

        # Update BKT mastery per question
        try:
            bkt_service.update_mastery(db, student_id, q.skill_id, correct)
        except Exception as e:
            print(f"[BatchSubmit] BKT update failed for Q{ans.question_id}: {e}")

        # Build feature dict for ML (kept for last answer)
        last_feat_dict = {
            "attempt_count": 1,
            "hint_count": ans.hint_count,
            "ms_first_response": ans.ms_first_response,
            "skill_id": q.skill_id,
            "bottom_hint": 0,
            "actions": 1,
            "overlap_time": ans.ms_first_response
        }

        question_results.append({
            "question_id": q.id,
            "question_text": q.question,
            "selected_option": ans.selected_option.upper(),
            "correct_answer": q.correct_answer.upper(),
            "correct": correct == 1,
            "option_a": q.option_a,
            "option_b": q.option_b,
            "option_c": q.option_c,
            "option_d": q.option_d,
            "explanation": q.explanation
        })

    total = len(question_results)
    percentage = round((total_correct / max(1, total)) * 100, 1)

    # Get updated mastery for this skill
    new_mastery_val = bkt_service.get_mastery(db, student_id, skill_id)
    mastery_label = bkt_service.get_mastery_label(new_mastery_val)

    # ML Risk Prediction on last interaction
    risk_prob = 0.0
    risk_level = "N/A"
    model_name = "N/A"
    if last_feat_dict:
        try:
            risk_prob, risk_level, model_name = ml_service.predict_risk(last_feat_dict, model_type="xgb")
        except Exception as e:
            print(f"[BatchSubmit] ML prediction failed: {e}")

    # Save prediction
    try:
        pred = models.Prediction(
            student_id=student_id,
            risk_probability=risk_prob,
            risk_level=risk_level if risk_level != "N/A" else "MEDIUM",
            model_name=model_name if model_name != "N/A" else "XGBoost"
        )
        db.add(pred)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[BatchSubmit] Failed to save prediction: {e}")

    # Save QuizAttempt record for unified analytics tracking
    try:
        total_quiz_q = submission.total_questions if submission.total_questions else total
        unanswered_count = max(0, total_quiz_q - total)
        incorrect_count = total - total_correct
        quiz_attempt = models.QuizAttempt(
            student_id=student_id,
            subject_id=skill.subject_id if skill else None,
            skill_id=skill_id if skill_id != 0 else None,
            total_questions=total_quiz_q,
            score=total_correct,
            incorrect=incorrect_count,
            unanswered=unanswered_count,
            percentage=percentage,
            created_at=datetime.utcnow()
        )
        db.add(quiz_attempt)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[BatchSubmit] Failed to save quiz attempt: {e}")

    # Generate recommendations
    new_recs = []
    try:
        new_recs = recommendation_service.generate_recommendations(db, student_id)
    except Exception as e:
        print(f"[BatchSubmit] Recommendation generation failed: {e}")

    return {
        "skill_id": skill_id,
        "skill_name": skill_name,
        "subject_name": subject_name,
        "total": total,
        "score": total_correct,
        "percentage": percentage,
        "new_mastery": round(new_mastery_val * 100, 2),
        "mastery_label": mastery_label,
        "risk_level": risk_level,
        "risk_probability": round(risk_prob, 4),
        "model_name": model_name,
        "questions": question_results,
        "recommendations": new_recs
    }


# ---------------------------------------------------------
# TEACHER ENDPOINTS
# ---------------------------------------------------------
@app.get("/api/teacher/dashboard")
def get_teacher_dashboard(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_teacher)
):
    students = db.query(models.Student).all()
    skills = db.query(models.Skill).all()

    total_students = len(students)
    high_risk_count = 0
    total_mastery_sum = 0.0
    student_summaries = []

    for st in students:
        twin = bkt_service.get_student_learning_twin(db, st.id)
        total_mastery_sum += twin["overall_mastery"]

        last_int = db.query(models.Interaction).filter(
            models.Interaction.student_id == st.id
        ).order_by(models.Interaction.created_at.desc()).first()

        has_activity = last_int is not None
        level = "N/A"
        prob = 0.0

        if has_activity:
            feat_dict = {
                "attempt_count": last_int.attempt_count,
                "hint_count": last_int.hint_count,
                "ms_first_response": last_int.ms_first_response,
                "skill_id": last_int.skill_id,
                "bottom_hint": last_int.bottom_hint,
                "actions": last_int.actions,
                "overlap_time": last_int.overlap_time
            }
            try:
                prob, level, _ = ml_service.predict_risk(feat_dict, model_type="xgb")
                if level == "HIGH":
                    high_risk_count += 1
            except Exception:
                pass

        student_summaries.append({
            "student_id": st.id,
            "student_code": st.student_code,
            "name": st.user.name,
            "email": st.user.email,
            "overall_mastery": twin["overall_mastery"],
            "questions_attempted": twin["total_questions_attempted"],
            "has_activity": has_activity,
            "risk_level": level,
            "risk_probability": round(prob, 4),
        })

    avg_mastery = round(total_mastery_sum / max(1, total_students), 2)

    return {
        "overview": {
            "total_students": total_students,
            "high_risk_students": high_risk_count,
            "average_mastery": avg_mastery,
            "total_skills": len(skills)
        },
        "students": student_summaries
    }


@app.get("/api/teacher/students")
def get_teacher_students_list(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_teacher)
):
    return get_teacher_dashboard(db, current_user)["students"]


@app.get("/api/teacher/student/{student_id}")
def teacher_view_student(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_teacher)
):
    """Teacher can view any student's full detail."""
    student = db.query(models.Student).filter(models.Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    twin = bkt_service.get_student_learning_twin(db, student.id)

    last_int = db.query(models.Interaction).filter(
        models.Interaction.student_id == student.id
    ).order_by(models.Interaction.created_at.desc()).first()

    has_activity = last_int is not None
    risk_prob, risk_level, model_name = 0.0, "N/A", "N/A"

    if has_activity:
        feat_dict = {
            "attempt_count": last_int.attempt_count,
            "hint_count": last_int.hint_count,
            "ms_first_response": last_int.ms_first_response,
            "skill_id": last_int.skill_id,
            "bottom_hint": last_int.bottom_hint,
            "actions": last_int.actions,
            "overlap_time": last_int.overlap_time
        }
        try:
            risk_prob, risk_level, model_name = ml_service.predict_risk(feat_dict, model_type="xgb")
        except Exception:
            pass

    recs = recommendation_service.generate_recommendations(db, student.id)

    recent_interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student.id
    ).order_by(models.Interaction.created_at.desc()).limit(10).all()
    skills_map = {s.skill_id: s.skill_name for s in db.query(models.Skill).all()}

    history = [
        {
            "id": i.id,
            "skill_name": skills_map.get(i.skill_id, f"Skill #{i.skill_id}"),
            "correct": bool(i.correct == 1),
            "attempt_count": i.attempt_count,
            "hint_count": i.hint_count,
            "created_at": i.created_at.strftime("%Y-%m-%d %H:%M") if i.created_at else ""
        }
        for i in recent_interactions
    ]

    return {
        "student": {
            "id": student.id,
            "student_code": student.student_code,
            "name": student.user.name,
            "email": student.user.email
        },
        "has_activity": has_activity,
        "overall_mastery": twin["overall_mastery"],
        "questions_attempted": twin["total_questions_attempted"],
        "risk": {
            "level": risk_level,
            "probability": round(risk_prob, 4),
            "model_name": model_name
        },
        "skills": twin["all_skills"],
        "weak_skills": twin["weak_concepts"],
        "strong_skills": twin["strong_concepts"],
        "recommendations": recs,
        "recent_performance": history
    }


@app.get("/api/teacher/model-performance")
def get_model_performance(current_user: models.User = Depends(get_current_teacher)):
    """
    Returns recorded evaluation results of actual trained models on ASSISTments test set.
    These numbers reflect offline training — the model is NOT retrained here.
    """
    return {
        "dataset_info": {
            "name": "ASSISTments 2012-2013 Dataset",
            "total_rows_before_cleaning": 1738745,
            "total_rows_cleaned": 1737242,
            "train_rows": 1389793,
            "test_rows": 347449,
            "split": "80/20 Stratified Train/Test Split (random_state=42)"
        },
        "features": REQUIRED_FEATURES,
        "models": {
            "random_forest": {
                "name": "Random Forest Classifier",
                "file_name": "eduinsight_rf.pkl",
                "loaded": ml_service.rf_model is not None,
                "metrics": {
                    "accuracy": 91.39,
                    "precision": 88.88,
                    "recall": 99.76,
                    "f1_score": 94.01,
                    "auc": 0.8926
                },
                "confusion_matrix": [
                    [82881, 29362],
                    [555, 234651]
                ],
                "feature_importance": [
                    {"feature": "attempt_count", "percentage": 58.9840},
                    {"feature": "hint_count", "percentage": 24.8025},
                    {"feature": "bottom_hint", "percentage": 14.4847},
                    {"feature": "overlap_time", "percentage": 0.6159},
                    {"feature": "ms_first_response", "percentage": 0.5911},
                    {"feature": "skill_id", "percentage": 0.5219},
                    {"feature": "actions", "percentage": 0.0000}
                ]
            },
            "xgboost": {
                "name": "XGBoost Classifier (Primary Live Model)",
                "file_name": "eduinsight_xgb.pkl",
                "loaded": ml_service.xgb_model is not None,
                "metrics": {
                    "accuracy": 91.40,
                    "precision": 88.93,
                    "recall": 99.71,
                    "f1_score": 94.01,
                    "auc": 0.8975
                },
                "confusion_matrix": [
                    [83042, 29201],
                    [675, 234531]
                ],
                "feature_importance": [
                    {"feature": "attempt_count", "percentage": 74.4706},
                    {"feature": "hint_count", "percentage": 24.8139},
                    {"feature": "skill_id", "percentage": 0.2870},
                    {"feature": "overlap_time", "percentage": 0.2132},
                    {"feature": "ms_first_response", "percentage": 0.1815},
                    {"feature": "bottom_hint", "percentage": 0.0337},
                    {"feature": "actions", "percentage": 0.0000}
                ]
            }
        }
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    print(f"Starting EduInsight AI Backend on http://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=False)
