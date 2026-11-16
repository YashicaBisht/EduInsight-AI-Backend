from typing import List, Optional
from pydantic import BaseModel, EmailStr

# Auth Schemas
class TeacherItem(BaseModel):
    id: int
    name: str
    email: str

    class Config:
        from_attributes = True

class UserRegister(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "STUDENT"  # STUDENT or TEACHER
    student_code: Optional[int] = None
    teacher_id: Optional[int] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    student_id: Optional[int] = None
    name: str
    has_activity: Optional[bool] = False

class UserResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    student_id: Optional[int] = None
    student_code: Optional[int] = None
    teacher_id: Optional[int] = None
    teacher_name: Optional[str] = None
    has_activity: Optional[bool] = False

    class Config:
        from_attributes = True

# Subject Schema
class SubjectSchema(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    icon: Optional[str] = "📚"
    topic_count: int = 0
    question_count: int = 0

# Teacher Quiz Question Schemas
class TeacherQuizQuestionCreate(BaseModel):
    skill_id: int
    question: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_answer: str  # A, B, C, or D
    explanation: Optional[str] = None

# Quiz Submission Schema (single question)
class QuizSubmission(BaseModel):
    question_id: int
    selected_option: str
    attempt_count: int = 1
    hint_count: int = 0
    ms_first_response: float = 5000.0
    bottom_hint: int = 0
    actions: int = 1
    overlap_time: float = 5000.0

# Single answer in a batch submission
class BatchAnswerItem(BaseModel):
    question_id: int
    selected_option: str
    ms_first_response: float = 5000.0
    hint_count: int = 0

# Batch Quiz Submission Schema (full quiz session at once)
class BatchQuizSubmission(BaseModel):
    skill_id: int
    answers: List[BatchAnswerItem]
    total_questions: Optional[int] = None

# Per-question result in session result
class QuestionResultItem(BaseModel):
    question_id: int
    question_text: str
    selected_option: str
    correct_answer: str
    correct: bool
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    explanation: Optional[str] = None

# Full quiz session result
class QuizSessionResult(BaseModel):
    skill_id: int
    skill_name: str
    subject_name: str
    total: int
    score: int
    percentage: float
    new_mastery: float
    mastery_label: str
    risk_level: str
    risk_probability: float
    model_name: str
    questions: List[QuestionResultItem]
    recommendations: List[dict] = []

# Skill & Mastery Schemas
class SkillMasterySchema(BaseModel):
    skill_id: int
    skill_name: str
    mastery: float
    status: str  # Mastered, Developing, Needs Improvement

class WeakSkillSchema(BaseModel):
    skill_id: int
    skill_name: str
    mastery: float

class StrongSkillSchema(BaseModel):
    skill_id: int
    skill_name: str
    mastery: float

# Risk Prediction Schema
class RiskInfoSchema(BaseModel):
    model_config = {"protected_namespaces": ()}
    level: str  # HIGH, MEDIUM, LOW
    probability: float
    model_name: str = "XGBoost"

# SHAP Explanation Schema
class ShapFeatureContribution(BaseModel):
    feature_name: str
    friendly_label: str
    value: float
    shap_value: float
    impact: str  # "Increases Risk" or "Decreases Risk"

class ShapExplanationResponse(BaseModel):
    student_id: int
    title: str = "Why am I at risk?"
    risk_level: str
    risk_probability: float
    top_bullets: List[str]
    feature_contributions: List[ShapFeatureContribution]

# Recommendation Schema
class RecommendationSchema(BaseModel):
    id: Optional[int] = None
    recommendation_type: str
    title: str
    explanation: str
    priority: str  # HIGH, MEDIUM, LOW
    suggested_action: str
    skill_id: Optional[int] = None

# Recent Activity / History Schema
class RecentActivitySchema(BaseModel):
    id: int
    skill_name: str
    correct: bool
    attempt_count: int
    hint_count: int
    created_at: str

# Student Dashboard Response Schema
class StudentInfo(BaseModel):
    id: int
    student_code: int
    name: str
    email: str

class StudentDashboardResponse(BaseModel):
    student: StudentInfo
    overall_mastery: float
    questions_attempted: int
    risk: RiskInfoSchema
    skills: List[SkillMasterySchema]
    weak_skills: List[WeakSkillSchema]
    strong_skills: List[StrongSkillSchema]
    recommendations: List[RecommendationSchema]
    recent_performance: List[RecentActivitySchema]
