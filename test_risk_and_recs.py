from database import SessionLocal
import models, analytics_service, recommendation_service

db = SessionLocal()

print("=== 1. STUDENT 1 (WITH ACTUAL QUIZ DATA) ===")
risk_1 = analytics_service.get_student_risk_analysis(db, 1)
print("Risk has_activity:", risk_1["has_activity"])
print("Total at risk:", risk_1["total_at_risk"])
print("High risk count:", risk_1["high_risk_count"])
print("Medium risk count:", risk_1["medium_risk_count"])
print("Low risk count:", risk_1["low_risk_count"])
print("Concept count:", len(risk_1["concept_risks"]))
for c in risk_1["concept_risks"]:
    print(f" - {c['skill_name']}: mastery={c['mastery']}%, risk={c['risk_level']}, attempts={c['attempts_count']}, trend={c['trend']}")

recs_1 = recommendation_service.generate_recommendations(db, 1)
print(f"\nRecommendations count: {len(recs_1)}")
for r in recs_1:
    print(f" * [{r['priority']}] {r['title']} (skill_id={r['skill_id']}) -> {r['suggested_action'][:55]}...")

print("\n=== 2. STUDENT WITHOUT QUIZ DATA ===")
risk_0 = analytics_service.get_student_risk_analysis(db, 99999)
print("Risk has_activity:", risk_0["has_activity"])
print("Message:", risk_0["message"])
print("Concepts count:", len(risk_0["concept_risks"]))

recs_0 = recommendation_service.generate_recommendations(db, 99999)
print("Recommendations count:", len(recs_0))
print("Rec 0 title:", recs_0[0]["title"])
print("Rec 0 action:", recs_0[0]["suggested_action"])
