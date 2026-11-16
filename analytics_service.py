from datetime import datetime
from typing import Dict, List, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
import models
import bkt_service

def ensure_quiz_attempts_exist(db: Session, student_id: int):
    """
    If there are interactions for this student but no quiz_attempts recorded yet,
    backfill them so historical attempts appear in charts and trend graphs.
    """
    attempt_count = db.query(models.QuizAttempt).filter(
        models.QuizAttempt.student_id == student_id
    ).count()
    if attempt_count > 0:
        return

    # Check interactions
    interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student_id
    ).order_by(models.Interaction.created_at.asc()).all()

    if not interactions:
        return

    # Group interactions by (skill_id, date/minute)
    from collections import defaultdict
    groups = defaultdict(list)
    for inter in interactions:
        # Group interactions within ~2 minutes of each other for the same skill
        time_key = inter.created_at.strftime("%Y-%m-%d %H:%M") if inter.created_at else "initial"
        group_key = (inter.skill_id, time_key)
        groups[group_key].append(inter)

    skills_map = {s.skill_id: s for s in db.query(models.Skill).all()}

    for (skill_id, time_key), group_items in groups.items():
        sk = skills_map.get(skill_id)
        subject_id = sk.subject_id if sk else None
        total_q = len(group_items)
        correct_q = sum(1 for item in group_items if item.correct == 1)
        incorrect_q = total_q - correct_q
        pct = round((correct_q / max(1, total_q)) * 100, 1)
        created_time = group_items[0].created_at or datetime.utcnow()

        attempt = models.QuizAttempt(
            student_id=student_id,
            subject_id=subject_id,
            skill_id=skill_id,
            total_questions=total_q,
            score=correct_q,
            incorrect=incorrect_q,
            unanswered=0,
            percentage=pct,
            created_at=created_time
        )
        db.add(attempt)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[AnalyticsService] Backfill attempts error: {e}")


def get_student_dashboard_analytics(db: Session, student_id: int) -> Dict[str, Any]:
    """
    Computes unified, real-data learning analytics for the student dashboard.
    Ensures that cards, pie charts, bar graphs, and line graphs all derive from
    the exact same database source of truth.
    """
    # Make sure historical attempts exist if there are interactions
    ensure_quiz_attempts_exist(db, student_id)

    # 1. Fetch all subjects & skills
    subjects = db.query(models.Subject).all()
    skills = db.query(models.Skill).all()
    total_subjects_count = len(subjects)
    total_topics_count = len(skills)

    skills_by_subject = {}
    for subj in subjects:
        skills_by_subject[subj.id] = []
    for sk in skills:
        if sk.subject_id in skills_by_subject:
            skills_by_subject[sk.subject_id].append(sk)

    # 2. Student masteries
    masteries = db.query(models.StudentSkillMastery).filter(
        models.StudentSkillMastery.student_id == student_id
    ).all()
    mastery_map = {m.skill_id: m.mastery for m in masteries}

    # 3. Interactions for student
    interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student_id
    ).order_by(models.Interaction.created_at.asc()).all()

    total_questions_attempted = len(interactions)
    total_correct = sum(1 for i in interactions if i.correct == 1)
    total_incorrect = total_questions_attempted - total_correct

    # Interaction count per skill
    skill_interaction_counts = {}
    skill_correct_counts = {}
    for i in interactions:
        skill_interaction_counts[i.skill_id] = skill_interaction_counts.get(i.skill_id, 0) + 1
        if i.correct == 1:
            skill_correct_counts[i.skill_id] = skill_correct_counts.get(i.skill_id, 0) + 1

    # 4. Classify each topic: Completed vs In Progress vs Not Yet Attempted
    # Definition of Completed: has_attempts is True AND mastery >= 0.80 (MASTERY_HIGH_THRESHOLD)
    COMPLETION_THRESHOLD = 0.80

    completed_topics_count = 0
    in_progress_topics_count = 0
    not_attempted_topics_count = 0

    topic_details = []
    for sk in skills:
        attempt_cnt = skill_interaction_counts.get(sk.skill_id, 0)
        has_attempts = attempt_cnt > 0
        m_val = mastery_map.get(sk.skill_id, 0.0)

        if not has_attempts:
            status = "Not Yet Attempted"
            not_attempted_topics_count += 1
        elif m_val >= COMPLETION_THRESHOLD:
            status = "Completed"
            completed_topics_count += 1
        else:
            status = "In Progress"
            in_progress_topics_count += 1

        correct_cnt = skill_correct_counts.get(sk.skill_id, 0)
        accuracy = round((correct_cnt / attempt_cnt) * 100, 1) if has_attempts else None

        subj_name = sk.subject.name if sk.subject else "General"

        topic_details.append({
            "skill_id": sk.skill_id,
            "skill_name": sk.skill_name,
            "subject_id": sk.subject_id,
            "subject_name": subj_name,
            "has_attempts": has_attempts,
            "attempt_count": attempt_cnt,
            "mastery": round(m_val * 100, 1),
            "status": status,
            "accuracy": accuracy
        })

    # Overall progress percentage: completed topics out of total topics
    overall_progress_pct = round((completed_topics_count / max(1, total_topics_count)) * 100, 1)

    # Attempted topics mastery average
    attempted_masteries = [m.mastery for m in masteries if skill_interaction_counts.get(m.skill_id, 0) > 0]
    avg_topic_mastery = round((sum(attempted_masteries) / max(1, len(attempted_masteries))) * 100, 1) if attempted_masteries else 0.0

    # 5. Quiz attempts
    quiz_attempts = db.query(models.QuizAttempt).filter(
        models.QuizAttempt.student_id == student_id
    ).order_by(models.QuizAttempt.created_at.asc()).all()

    total_quizzes_attempted = len(quiz_attempts)
    total_unanswered = sum(a.unanswered for a in quiz_attempts)

    if total_quizzes_attempted > 0:
        avg_quiz_score = round(sum(a.percentage for a in quiz_attempts) / total_quizzes_attempted, 1)
    else:
        avg_quiz_score = None

    # 6. Pie Chart 1: Topic Completion Status
    topic_completion_pie = [
        {
            "name": "Completed",
            "value": completed_topics_count,
            "percentage": round((completed_topics_count / max(1, total_topics_count)) * 100, 1),
            "color": "#10b981"
        },
        {
            "name": "In Progress",
            "value": in_progress_topics_count,
            "percentage": round((in_progress_topics_count / max(1, total_topics_count)) * 100, 1),
            "color": "#f59e0b"
        },
        {
            "name": "Not Yet Attempted",
            "value": not_attempted_topics_count,
            "percentage": round((not_attempted_topics_count / max(1, total_topics_count)) * 100, 1),
            "color": "#94a3b8"
        }
    ]

    # 7. Pie Chart 2: Quiz Performance
    total_quiz_answers = total_correct + total_incorrect + total_unanswered
    if total_quiz_answers > 0:
        quiz_performance_pie = [
            {
                "name": "Correct Answers",
                "value": total_correct,
                "percentage": round((total_correct / total_quiz_answers) * 100, 1),
                "color": "#10b981"
            },
            {
                "name": "Incorrect Answers",
                "value": total_incorrect,
                "percentage": round((total_incorrect / total_quiz_answers) * 100, 1),
                "color": "#ef4444"
            },
            {
                "name": "Unanswered Questions",
                "value": total_unanswered,
                "percentage": round((total_unanswered / total_quiz_answers) * 100, 1),
                "color": "#cbd5e1"
            }
        ]
    else:
        quiz_performance_pie = []

    # 8. Subject-wise Analysis (Pie Chart 3 & Bar Chart 1)
    subject_progress_list = []
    subject_pie_data = []

    # Palette for subjects
    subject_colors = {
        "Mathematics": "#3b82f6",       # Blue
        "Science": "#10b981",           # Emerald
        "English": "#f59e0b",           # Amber
        "Computer Science": "#8b5cf6"   # Purple
    }

    for subj in subjects:
        subj_skills = skills_by_subject.get(subj.id, [])
        subj_total_topics = len(subj_skills)
        subj_completed = 0
        subj_in_progress = 0
        subj_not_attempted = 0
        subj_mastery_sum = 0.0
        subj_attempted_count = 0
        subj_correct_count = 0
        subj_questions_count = 0

        for sk in subj_skills:
            cnt = skill_interaction_counts.get(sk.skill_id, 0)
            m = mastery_map.get(sk.skill_id, 0.0)
            subj_questions_count += cnt
            subj_correct_count += skill_correct_counts.get(sk.skill_id, 0)

            if cnt == 0:
                subj_not_attempted += 1
            elif m >= COMPLETION_THRESHOLD:
                subj_completed += 1
                subj_mastery_sum += m
                subj_attempted_count += 1
            else:
                subj_in_progress += 1
                subj_mastery_sum += m
                subj_attempted_count += 1

        subj_progress_pct = round((subj_completed / max(1, subj_total_topics)) * 100, 1)
        subj_accuracy = round((subj_correct_count / max(1, subj_questions_count)) * 100, 1) if subj_questions_count > 0 else None
        subj_avg_mastery = round((subj_mastery_sum / max(1, subj_attempted_count)) * 100, 1) if subj_attempted_count > 0 else 0.0

        color = subject_colors.get(subj.name, "#6366f1")

        subj_data = {
            "subject_id": subj.id,
            "subject_name": subj.name,
            "icon": subj.icon or "📚",
            "color": color,
            "total_topics": subj_total_topics,
            "completed_topics": subj_completed,
            "in_progress_topics": subj_in_progress,
            "not_attempted_topics": subj_not_attempted,
            "progress_percentage": subj_progress_pct,
            "accuracy": subj_accuracy,
            "avg_mastery": subj_avg_mastery,
            "questions_answered": subj_questions_count,
            "correct_answers": subj_correct_count
        }
        subject_progress_list.append(subj_data)

        # For Subject Progress Pie Chart (comparison of topic progress / completed topics across subjects)
        subject_pie_data.append({
            "name": subj.name,
            "value": subj_completed if completed_topics_count > 0 else subj_total_topics,
            "completed": subj_completed,
            "total": subj_total_topics,
            "percentage": subj_progress_pct,
            "color": color,
            "icon": subj.icon
        })

    # 9. Bar Chart 2: Recent Quiz Attempts (last 10 attempts)
    recent_attempts_data = []
    skills_map = {s.skill_id: s for s in skills}
    for idx, att in enumerate(quiz_attempts[-10:]):
        sk = skills_map.get(att.skill_id)
        topic_title = sk.skill_name if sk else "Mixed Practice"
        subj_name = sk.subject.name if (sk and sk.subject) else "All Subjects"
        date_str = att.created_at.strftime("%b %d, %H:%M") if att.created_at else f"Attempt {idx+1}"

        recent_attempts_data.append({
            "attempt_number": idx + 1,
            "label": f"Quiz #{idx + 1}",
            "topic_name": topic_title,
            "subject_name": subj_name,
            "score_percentage": round(att.percentage, 1),
            "score": att.score,
            "total": att.total_questions,
            "date": date_str
        })

    # 10. Bar Chart 3: Topic-wise Quiz Performance (for attempted topics)
    attempted_topic_bars = []
    for td in topic_details:
        if td["has_attempts"]:
            attempted_topic_bars.append({
                "topic_name": td["skill_name"],
                "subject_name": td["subject_name"],
                "accuracy": td["accuracy"] if td["accuracy"] is not None else 0,
                "mastery": td["mastery"],
                "attempts": td["attempt_count"],
                "status": td["status"]
            })

    # 11. Progress Trend Graph (Line Chart over actual attempts)
    trend_graph_data = []
    cumulative_correct = 0
    cumulative_questions = 0

    for idx, att in enumerate(quiz_attempts):
        cumulative_correct += att.score
        cumulative_questions += max(1, att.total_questions)
        cum_accuracy = round((cumulative_correct / cumulative_questions) * 100, 1)

        sk = skills_map.get(att.skill_id)
        topic_name = sk.skill_name if sk else "Quiz"
        date_str = att.created_at.strftime("%b %d, %H:%M") if att.created_at else f"Q{idx+1}"

        trend_graph_data.append({
            "attempt": f"#{idx + 1}",
            "label": f"Attempt {idx + 1}",
            "score": round(att.percentage, 1),
            "cumulative_accuracy": cum_accuracy,
            "topic": topic_name,
            "date": date_str
        })

    has_activity = total_questions_attempted > 0 or total_quizzes_attempted > 0

    return {
        "has_activity": has_activity,
        "overall_progress": {
            "learning_progress_percentage": overall_progress_pct,
            "overall_mastery": avg_topic_mastery,
            "total_subjects": total_subjects_count,
            "total_topics": total_topics_count,
            "completed_topics": completed_topics_count,
            "in_progress_topics": in_progress_topics_count,
            "not_attempted_topics": not_attempted_topics_count,
            "total_quizzes_attempted": total_quizzes_attempted,
            "average_quiz_score": avg_quiz_score,
            "total_questions_attempted": total_questions_attempted,
            "correct_answers": total_correct,
            "incorrect_answers": total_incorrect,
            "unanswered_questions": total_unanswered
        },
        "charts": {
            "topic_completion_pie": topic_completion_pie,
            "quiz_performance_pie": quiz_performance_pie,
            "subject_progress_pie": subject_pie_data,
            "subject_comparison_bar": subject_progress_list,
            "recent_quiz_scores_bar": recent_attempts_data,
            "topic_performance_bar": attempted_topic_bars,
            "progress_trend_line": trend_graph_data
        },
        "topics": topic_details
    }


def get_student_risk_analysis(db: Session, student_id: int) -> Dict[str, Any]:
    """
    Computes dynamic risk analysis for a student based ONLY on actual quiz attempts.
    - Classifies mastery into risk levels:
        0–39%: High
        40–69%: Medium
        70–100%: Low
    - Excludes unattempted concepts.
    - Provides counts for total at risk, high risk, medium risk, and low risk concepts.
    - Computes attempt counts, accuracy, trends, and risk explanations for each attempted concept.
    """
    interactions = db.query(models.Interaction).filter(
        models.Interaction.student_id == student_id
    ).order_by(models.Interaction.created_at.asc()).all()

    if not interactions:
        return {
            "student_id": student_id,
            "has_activity": False,
            "message": "No risk analysis available yet. Complete a quiz to discover your learning gaps.",
            "risk_probability": None,
            "risk_level": "N/A",
            "model_name": "N/A",
            "total_at_risk": 0,
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 0,
            "concept_risks": []
        }

    # Overall ML risk prediction from last interaction
    last_interaction = interactions[-1]
    from ml_service import ml_service
    feat_dict = {
        "attempt_count": last_interaction.attempt_count,
        "hint_count": last_interaction.hint_count,
        "ms_first_response": last_interaction.ms_first_response,
        "skill_id": last_interaction.skill_id,
        "bottom_hint": last_interaction.bottom_hint,
        "actions": last_interaction.actions,
        "overlap_time": last_interaction.overlap_time
    }
    try:
        risk_prob, risk_level, model_name = ml_service.predict_risk(feat_dict, model_type="xgb")
    except Exception as e:
        print(f"[RiskAnalysis] ML prediction error: {e}")
        risk_prob, risk_level, model_name = 0.0, "LOW", "Fallback"

    skills_map = {s.skill_id: s.skill_name for s in db.query(models.Skill).all()}
    masteries = db.query(models.StudentSkillMastery).filter(
        models.StudentSkillMastery.student_id == student_id
    ).all()
    mastery_map = {m.skill_id: m.mastery for m in masteries}

    from collections import defaultdict
    skill_interactions = defaultdict(list)
    for inter in interactions:
        skill_interactions[inter.skill_id].append(inter)

    concept_risks = []
    for skill_id, inter_list in skill_interactions.items():
        skill_name = skills_map.get(skill_id, f"Concept #{skill_id}")
        attempts_count = len(inter_list)
        correct_count = sum(1 for i in inter_list if i.correct == 1)
        accuracy = round((correct_count / max(1, attempts_count)) * 100, 1)

        raw_m = mastery_map.get(skill_id)
        if raw_m is not None:
            mastery_pct = round(raw_m * 100, 1)
        else:
            mastery_pct = accuracy

        # Risk classification:
        # 0–39%: High
        # 40–69%: Medium
        # 70–100%: Low
        if mastery_pct < 40.0:
            c_risk_level = "High"
            explanation = (
                f"Mastery is {mastery_pct}% with {accuracy}% accuracy across {attempts_count} "
                f"attempt{'s' if attempts_count != 1 else ''}. Recent performance indicates "
                f"significant difficulty and learning gaps. Foundational concept revision is strongly advised."
            )
        elif mastery_pct < 70.0:
            c_risk_level = "Medium"
            explanation = (
                f"Mastery is {mastery_pct}% with {accuracy}% accuracy across {attempts_count} "
                f"attempt{'s' if attempts_count != 1 else ''}. Demonstrates developing comprehension "
                f"but requires targeted practice to build stability and avoid mistakes."
            )
        else:
            c_risk_level = "Low"
            explanation = (
                f"Mastery is {mastery_pct}% with {accuracy}% accuracy across {attempts_count} "
                f"attempt{'s' if attempts_count != 1 else ''}. Strong performance, high recall "
                f"accuracy, and solid concept retention demonstrated."
            )

        if attempts_count >= 3:
            mid = attempts_count // 2
            first_half = inter_list[:mid]
            second_half = inter_list[mid:]
            first_acc = sum(i.correct for i in first_half) / max(1, len(first_half))
            second_acc = sum(i.correct for i in second_half) / max(1, len(second_half))
            if second_acc > first_acc + 0.15:
                trend = "Improving"
            elif second_acc < first_acc - 0.15:
                trend = "Declining"
            else:
                trend = "Steady"
        else:
            trend = "Initial Assessment"

        concept_risks.append({
            "skill_id": skill_id,
            "skill_name": skill_name,
            "mastery": mastery_pct,
            "risk_level": c_risk_level,
            "attempts_count": attempts_count,
            "accuracy": accuracy,
            "trend": trend,
            "explanation": explanation
        })

    risk_rank = {"High": 0, "Medium": 1, "Low": 2}
    concept_risks.sort(key=lambda x: (risk_rank.get(x["risk_level"], 3), x["mastery"]))

    high_risk_count = sum(1 for c in concept_risks if c["risk_level"] == "High")
    medium_risk_count = sum(1 for c in concept_risks if c["risk_level"] == "Medium")
    low_risk_count = sum(1 for c in concept_risks if c["risk_level"] == "Low")
    total_at_risk = high_risk_count + medium_risk_count

    return {
        "student_id": student_id,
        "has_activity": True,
        "risk_probability": risk_prob,
        "risk_level": risk_level,
        "model_name": model_name,
        "message": None,
        "total_at_risk": total_at_risk,
        "high_risk_count": high_risk_count,
        "medium_risk_count": medium_risk_count,
        "low_risk_count": low_risk_count,
        "concept_risks": concept_risks
    }

