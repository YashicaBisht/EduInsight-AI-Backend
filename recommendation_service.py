import os
from typing import List, Dict, Any
from dotenv import load_dotenv
from sqlalchemy.orm import Session
import models

load_dotenv()

REC_HIGH_ATTEMPTS = float(os.getenv("REC_HIGH_ATTEMPTS", "2.5"))
REC_HIGH_HINTS = float(os.getenv("REC_HIGH_HINTS", "1.5"))
REC_HIGH_RESPONSE_TIME_MS = float(os.getenv("REC_HIGH_RESPONSE_TIME_MS", "10000.0"))

# Risk mastery thresholds:
# 0–39%: High Risk
# 40–69%: Medium Risk
# 70–100%: Low Risk
RISK_HIGH_THRESHOLD = 0.40
RISK_MED_THRESHOLD = 0.70

def generate_recommendations(
    db: Session,
    student_id: int,
    recent_interactions: List[models.Interaction] = None
) -> List[Dict[str, Any]]:
    """
    Generates personalized learning recommendations based ONLY on concepts
    with actual quiz performance data, prioritizing the student's weakest
    concepts first.
    """
    recommendations = []

    # 1. Check actual quiz interactions for this student
    all_interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student_id
    ).order_by(models.Interaction.created_at.desc()).all()

    if not all_interactions:
        # Student has no quiz attempts yet: show clear call-to-action
        return [{
            "recommendation_type": "Getting Started",
            "title": "Complete Your First Quiz",
            "explanation": "No quiz performance data yet. Complete a quiz to discover your learning gaps and receive personalized study recommendations.",
            "priority": "MEDIUM",
            "suggested_action": "Start a quiz from any topic in the Quiz section.",
            "skill_id": None,
            "skill_name": None,
            "mastery": 0.0,
            "risk_level": "None"
        }]

    # Collect set of attempted skill IDs
    attempted_skill_ids = set(i.skill_id for i in all_interactions)

    # 2. Fetch skills metadata
    skills = db.query(models.Skill).all()
    skill_map = {s.skill_id: s.skill_name for s in skills}

    # 3. Fetch mastery records for attempted skills only
    masteries = db.query(models.StudentSkillMastery).filter(
        models.StudentSkillMastery.student_id == student_id,
        models.StudentSkillMastery.skill_id.in_(attempted_skill_ids)
    ).all()
    mastery_map = {m.skill_id: m.mastery for m in masteries}

    # 4. Behavioral recommendations from recent interactions
    if not recent_interactions:
        recent_interactions = all_interactions[:10]

    avg_hints = sum(i.hint_count for i in recent_interactions) / max(1, len(recent_interactions))
    avg_attempts = sum(i.attempt_count for i in recent_interactions) / max(1, len(recent_interactions))
    avg_response_time = sum(i.ms_first_response for i in recent_interactions) / max(1, len(recent_interactions))

    # Rule 1: High attempts pattern
    if avg_attempts > REC_HIGH_ATTEMPTS:
        recommendations.append({
            "recommendation_type": "Strategy Improvement",
            "title": "Refine Solution Strategy",
            "explanation": "You are making multiple attempts before finding the correct answer. Focus on analyzing problem requirements before submitting.",
            "priority": "HIGH",
            "suggested_action": "Read the problem statement carefully and outline your steps before submitting your answer.",
            "skill_id": None,
            "skill_name": None,
            "mastery": None,
            "risk_level": "High"
        })

    # Rule 2: High hint usage pattern
    if avg_hints > REC_HIGH_HINTS:
        recommendations.append({
            "recommendation_type": "Hint Reduction",
            "title": "Build Independent Problem Solving",
            "explanation": "Your recent activities rely heavily on hint prompts. Try working through steps independently first.",
            "priority": "MEDIUM",
            "suggested_action": "Attempt solving the next questions without opening hints until after your first attempt.",
            "skill_id": None,
            "skill_name": None,
            "mastery": None,
            "risk_level": "Medium"
        })

    # Rule 3: High response time pattern
    if avg_response_time > REC_HIGH_RESPONSE_TIME_MS:
        recommendations.append({
            "recommendation_type": "Timed Practice",
            "title": "Speed & Fluency Drills",
            "explanation": "Your average response time is higher than expected. Speed practice will build confidence and recall fluency.",
            "priority": "MEDIUM",
            "suggested_action": "Complete a timed fluency quiz on basic concepts.",
            "skill_id": None,
            "skill_name": None,
            "mastery": None,
            "risk_level": "Medium"
        })

    # 5. Concept-specific recommendations for ATTEMPTED concepts ONLY
    concept_recs = []
    for skill_id in attempted_skill_ids:
        skill_name = skill_map.get(skill_id, f"Skill #{skill_id}")
        raw_m = mastery_map.get(skill_id, 0.20)
        mastery_pct = round(raw_m * 100, 1)

        if raw_m < RISK_HIGH_THRESHOLD:
            # 0–39%: High Risk -> Foundational revision + 5 basic practice questions
            concept_recs.append({
                "recommendation_type": "Concept Revision",
                "title": f"Revise {skill_name}",
                "explanation": f"Your current mastery for {skill_name} is {mastery_pct}%. Recent performance shows this concept needs foundational review.",
                "priority": "HIGH",
                "suggested_action": f"Review the concept explanation for {skill_name} and attempt 5 basic practice questions.",
                "skill_id": skill_id,
                "skill_name": skill_name,
                "mastery": mastery_pct,
                "risk_level": "High"
            })
        elif raw_m < RISK_MED_THRESHOLD:
            # 40–69%: Medium Risk -> Targeted practice 5-10 questions
            concept_recs.append({
                "recommendation_type": "Targeted Practice",
                "title": f"Practice {skill_name}",
                "explanation": f"Your mastery for {skill_name} is in the developing range ({mastery_pct}%). Targeted practice of 5-10 questions will build stability and confidence.",
                "priority": "MEDIUM",
                "suggested_action": f"Complete targeted practice questions on {skill_name}.",
                "skill_id": skill_id,
                "skill_name": skill_name,
                "mastery": mastery_pct,
                "risk_level": "Medium"
            })
        else:
            # 70–100%: Low Risk -> Advanced learning / challenge
            concept_recs.append({
                "recommendation_type": "Advanced Learning",
                "title": f"Mastery Challenge: {skill_name}",
                "explanation": f"You have achieved strong mastery ({mastery_pct}%) in {skill_name}! Challenge yourself with advanced multi-step problems.",
                "priority": "LOW",
                "suggested_action": f"Attempt advanced level questions in {skill_name}.",
                "skill_id": skill_id,
                "skill_name": skill_name,
                "mastery": mastery_pct,
                "risk_level": "Low"
            })

    # Sort concept recommendations: weakest concepts first (lowest mastery first)
    concept_recs.sort(key=lambda x: (
        0 if x["priority"] == "HIGH" else (1 if x["priority"] == "MEDIUM" else 2),
        x["mastery"] if x["mastery"] is not None else 100.0
    ))

    # Behavioral recs + sorted concept recs
    recommendations.extend(concept_recs)

    # Sort all by priority order: HIGH -> MEDIUM -> LOW
    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    recommendations.sort(key=lambda x: (
        priority_order.get(x["priority"], 3),
        x.get("mastery") if x.get("mastery") is not None else 50.0
    ))

    return recommendations
