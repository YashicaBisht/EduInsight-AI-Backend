import os
from typing import Dict, List, Any
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import models

load_dotenv()

# BKT Prototype Parameters (configurable via environment variables)
P_INIT = float(os.getenv("BKT_P_INIT", "0.20"))
P_LEARN = float(os.getenv("BKT_P_LEARN", "0.15"))
P_GUESS = float(os.getenv("BKT_P_GUESS", "0.20"))
P_SLIP = float(os.getenv("BKT_P_SLIP", "0.10"))

MASTERY_HIGH_THRESHOLD = float(os.getenv("MASTERY_HIGH_THRESHOLD", "0.80"))
MASTERY_MED_THRESHOLD = float(os.getenv("MASTERY_MED_THRESHOLD", "0.60"))

def update_mastery(db: Session, student_id: int, skill_id: int, correct: int) -> float:
    """
    Updates student BKT concept mastery given question response (1 = correct, 0 = incorrect).
    BKT Formula:
      Posterior P(L_t | obs):
        If correct (1): P(L_t) * (1 - P_SLIP) / [ P(L_t) * (1 - P_SLIP) + (1 - P(L_t)) * P_GUESS ]
        If incorrect (0): P(L_t) * P_SLIP / [ P(L_t) * P_SLIP + (1 - P(L_t)) * (1 - P_GUESS) ]
      Transition P(L_{t+1}):
        P(L_t | obs) + (1 - P(L_t | obs)) * P_LEARN
    """
    # Fetch existing mastery or initialize with P_INIT
    record = db.query(models.StudentSkillMastery).filter(
        models.StudentSkillMastery.student_id == student_id,
        models.StudentSkillMastery.skill_id == skill_id
    ).first()

    p_prev = record.mastery if record else P_INIT

    # Step 1: Posterior update based on observation
    if correct == 1:
        p_obs = (p_prev * (1.0 - P_SLIP)) / (p_prev * (1.0 - P_SLIP) + (1.0 - p_prev) * P_GUESS)
    else:
        p_obs = (p_prev * P_SLIP) / (p_prev * P_SLIP + (1.0 - p_prev) * (1.0 - P_GUESS))

    # Step 2: Learning transition update
    p_new = p_obs + (1.0 - p_obs) * P_LEARN

    # Clamp mastery between 0.01 and 0.99 for numerical stability
    p_new = max(0.01, min(0.99, float(p_new)))

    # Save to database
    if record:
        record.mastery = p_new
    else:
        record = models.StudentSkillMastery(
            student_id=student_id,
            skill_id=skill_id,
            mastery=p_new
        )
        db.add(record)

    db.commit()
    db.refresh(record)
    return p_new

def get_mastery(db: Session, student_id: int, skill_id: int) -> float:
    """Returns current mastery for a student + skill."""
    record = db.query(models.StudentSkillMastery).filter(
        models.StudentSkillMastery.student_id == student_id,
        models.StudentSkillMastery.skill_id == skill_id
    ).first()
    return record.mastery if record else P_INIT

def get_mastery_label(mastery: float, has_attempts: bool = True) -> str:
    """
    Classifies numerical mastery into human-readable level.
    When has_attempts is False (no quiz history), returns 'Not Yet Attempted'
    instead of 'Needs Improvement' to avoid misleading zero-state labels.
    """
    if not has_attempts:
        return "Not Yet Attempted"
    if mastery >= MASTERY_HIGH_THRESHOLD:
        return "Mastered"
    elif mastery >= MASTERY_MED_THRESHOLD:
        return "Developing"
    else:
        return "Needs Improvement"

def get_student_learning_twin(db: Session, student_id: int) -> Dict[str, Any]:
    """
    Generates dynamic Learning Twin representation for student concept state.
    Uses attempt history to distinguish 'Not Yet Attempted' from 'Needs Improvement'.
    """
    # Fetch all skills
    skills = db.query(models.Skill).all()
    skill_dict = {s.skill_id: s.skill_name for s in skills}

    # Fetch student masteries
    masteries = db.query(models.StudentSkillMastery).filter(
        models.StudentSkillMastery.student_id == student_id
    ).all()
    mastery_map = {m.skill_id: m.mastery for m in masteries}

    # Count actual interactions per skill
    from sqlalchemy import func as sqlfunc
    interaction_counts_query = (
        db.query(models.Interaction.skill_id, sqlfunc.count(models.Interaction.id))
        .filter(models.Interaction.student_id == student_id)
        .group_by(models.Interaction.skill_id)
        .all()
    )
    skill_attempt_count = {skill_id: cnt for skill_id, cnt in interaction_counts_query}

    all_skills_data = []
    strong_concepts = []
    developing_concepts = []
    weak_concepts = []
    attempted_skill_ids = set(skill_attempt_count.keys())

    total_mastery_sum = 0.0

    for s_id, s_name in skill_dict.items():
        m_val = mastery_map.get(s_id, 0.0)
        has_attempts = s_id in attempted_skill_ids
        total_mastery_sum += m_val
        status = get_mastery_label(m_val, has_attempts=has_attempts)

        skill_info = {
            "skill_id": s_id,
            "skill_name": s_name,
            "mastery": round(m_val * 100, 2),
            "status": status,
            "has_attempts": has_attempts,
            "attempt_count": skill_attempt_count.get(s_id, 0)
        }

        all_skills_data.append(skill_info)

        if not has_attempts:
            pass  # not yet attempted — not weak, just unstarted
        elif m_val >= MASTERY_HIGH_THRESHOLD:
            strong_concepts.append(skill_info)
        elif m_val >= MASTERY_MED_THRESHOLD:
            developing_concepts.append(skill_info)
        else:
            weak_concepts.append(skill_info)

    # Overall mastery: only count attempted skills to avoid diluting with zeros
    attempted_masteries = [mastery_map.get(s_id, 0.0) for s_id in attempted_skill_ids]
    overall_mastery = round((sum(attempted_masteries) / max(1, len(attempted_masteries))) * 100, 2) if attempted_masteries else 0.0

    # Fetch recent interactions
    interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student_id
    ).order_by(models.Interaction.created_at.desc()).limit(20).all()

    total_attempts = len(interactions)
    correct_count = sum(1 for i in interactions if i.correct == 1)
    recent_accuracy = round((correct_count / total_attempts * 100), 2) if total_attempts > 0 else 0.0

    avg_hints = round(sum(i.hint_count for i in interactions) / max(1, total_attempts), 1)
    avg_response_time = round(sum(i.ms_first_response for i in interactions) / max(1, total_attempts), 0)

    return {
        "student_id": student_id,
        "overall_mastery": overall_mastery,
        "recent_accuracy": recent_accuracy,
        "total_questions_attempted": total_attempts,
        "avg_hints_per_question": avg_hints,
        "avg_response_time_ms": avg_response_time,
        "all_skills": all_skills_data,
        "strong_concepts": strong_concepts,
        "developing_concepts": developing_concepts,
        "weak_concepts": weak_concepts,
        "topics_attempted": len(attempted_skill_ids),
        "topics_not_attempted": len(skill_dict) - len(attempted_skill_ids),
        "total_topics": len(skill_dict)
    }
