"""
EduInsight AI — Database Seeder (v2 — Multi-Subject)
=====================================================
Subjects seeded:
  1. Mathematics   — Algebra, Geometry, Number Systems topics
  2. Science       — Physics, Chemistry, Biology topics
  3. English       — Grammar, Comprehension, Writing topics
  4. Computer Science — Programming, Data Structures, Algorithms topics

Seeds ONLY:
  - 1 teacher account (for admin/demo)
  - Subjects (4 real academic subjects)
  - Skills/Topics (grouped under each subject)
  - Quiz questions (real, no dummy values — 3–5 per topic)

Does NOT seed:
  - Fake student interactions
  - Hardcoded mastery values
  - Random risk/prediction data

Real students register via /api/auth/register and earn real data
by taking quizzes. Their BKT mastery, risk, SHAP, and recommendations
are all computed from their actual interactions.
"""
import os
import sys
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from database import engine, SessionLocal, Base
import models
from auth import hash_password

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.getenv("MODELS_DIR", os.path.join(BASE_DIR, "models"))
XGB_PATH = os.path.join(MODELS_DIR, "eduinsight_xgb.pkl")
RF_PATH = os.path.join(MODELS_DIR, "eduinsight_rf.pkl")

SEED_TEACHER_NAME = os.getenv("SEED_TEACHER_NAME", "Dr. Sarah Jenkins")
SEED_TEACHER_EMAIL = os.getenv("SEED_TEACHER_EMAIL", "teacher@eduinsight.ai")
SEED_TEACHER_PASSWORD = os.getenv("SEED_TEACHER_PASSWORD", "password123")


def check_models_presence():
    print("=" * 60)
    print("CHECKING PRE-TRAINED MODEL FILES IN backend/models/")
    print("=" * 60)
    rf_exists = os.path.exists(RF_PATH)
    xgb_exists = os.path.exists(XGB_PATH)
    if rf_exists:
        print(f"[FOUND]   Random Forest: {RF_PATH}")
    else:
        print(f"[MISSING] Random Forest: {RF_PATH}")
    if xgb_exists:
        print(f"[FOUND]   XGBoost      : {XGB_PATH}")
    else:
        print(f"[MISSING] XGBoost      : {XGB_PATH}")
    if not (rf_exists and xgb_exists):
        print("\n[IMPORTANT] Place your pre-trained .pkl files in backend/models/")
        print("  -> eduinsight_rf.pkl")
        print("  -> eduinsight_xgb.pkl")
        print("  The system uses a heuristic fallback until .pkl files are available.")
    print("=" * 60)


def seed_database(reset: bool = False):
    check_models_presence()

    if reset:
        print("[!] Reset flag passed: Dropping all tables...")
        Base.metadata.drop_all(bind=engine)

    Base.metadata.create_all(bind=engine)

    db: Session = SessionLocal()

    try:
        # Check if already seeded and not resetting
        if not reset and db.query(models.Subject).count() > 0:
            print("[INFO] Database already contains academic curriculum (subjects/skills). Preserving existing records.")
            return

        # ── 1. Seed Teacher Account ─────────────────────────────────────────
        print("\n[1/4] Seeding Teacher Account...")
        teacher_user = models.User(
            name=SEED_TEACHER_NAME,
            email=SEED_TEACHER_EMAIL,
            password_hash=hash_password(SEED_TEACHER_PASSWORD),
            role="TEACHER"
        )
        db.add(teacher_user)
        db.commit()
        print(f"  [+] Teacher: {SEED_TEACHER_EMAIL} / {SEED_TEACHER_PASSWORD}")

        # ── 2. Seed Subjects ────────────────────────────────────────────────
        print("\n[2/4] Seeding Subjects...")
        subjects_data = [
            ("Mathematics", "Algebra, Geometry, Number Systems, and more", "📐"),
            ("Science",     "Physics, Chemistry, and Biology concepts",    "🔬"),
            ("English",     "Grammar, Comprehension, and Writing skills",  "📖"),
            ("Computer Science", "Programming, Data Structures, Algorithms", "💻"),
        ]
        subject_objs = {}
        for s_name, s_desc, s_icon in subjects_data:
            subj = models.Subject(name=s_name, description=s_desc, icon=s_icon)
            db.add(subj)
            db.flush()
            subject_objs[s_name] = subj
        db.commit()
        print(f"  [+] Seeded {len(subjects_data)} subjects.")

        # ── 3. Seed Skills (Topics) ─────────────────────────────────────────
        print("\n[3/4] Seeding Skills (Topics)...")
        # Format: (skill_id, skill_name, subject_name)
        skills_data = [
            # Mathematics
            (45,  "Equation Solving (Two or Fewer Steps)", "Mathematics"),
            (78,  "Finding y-intercept",                   "Mathematics"),
            (102, "Combining Like Terms",                  "Mathematics"),
            (34,  "Finding Slope",                         "Mathematics"),
            (19,  "Pattern Finding & Sequences",           "Mathematics"),
            (105, "Properties of Pyramid (Geometry)",      "Mathematics"),
            (112, "Perimeter of Irregular Figures",        "Mathematics"),
            (88,  "Surface Area of Pyramid",               "Mathematics"),
            (64,  "Division of Mixed Fractions",           "Mathematics"),
            (12,  "Venn Diagrams & Set Theory",            "Mathematics"),

            # Science
            (201, "Newton's Laws of Motion",               "Science"),
            (202, "Work, Energy and Power",                "Science"),
            (203, "Periodic Table & Elements",             "Science"),
            (204, "Chemical Reactions & Equations",        "Science"),
            (205, "Cell Structure and Functions",          "Science"),
            (206, "Photosynthesis",                        "Science"),

            # English
            (301, "Parts of Speech (Grammar)",             "English"),
            (302, "Tenses and Subject-Verb Agreement",     "English"),
            (303, "Reading Comprehension Strategies",      "English"),
            (304, "Essay Writing Structure",               "English"),

            # Computer Science
            (401, "Variables, Data Types & Operators",     "Computer Science"),
            (402, "Conditionals and Loops",                "Computer Science"),
            (403, "Arrays and Lists",                      "Computer Science"),
            (404, "Sorting Algorithms (Bubble & Selection)", "Computer Science"),
        ]

        skill_objs = {}
        for sk_id, sk_name, subj_name in skills_data:
            subj = subject_objs[subj_name]
            sk = models.Skill(skill_id=sk_id, skill_name=sk_name, subject_id=subj.id)
            db.add(sk)
            db.flush()
            skill_objs[sk_id] = sk
        db.commit()
        print(f"  [+] Seeded {len(skills_data)} skills/topics.")

        # ── 4. Seed Quiz Questions ───────────────────────────────────────────
        print("\n[4/4] Seeding Quiz Questions...")

        # Format: (skill_id, question, A, B, C, D, correct_answer, explanation)
        questions_data = [

            # ── Mathematics: Equation Solving (skill 45) ──
            (45, "Solve for x: 2x + 5 = 15",
             "x = 5", "x = 10", "x = 7.5", "x = 4", "A",
             "Subtract 5 from both sides: 2x = 10, then divide by 2: x = 5."),
            (45, "Solve for y: 3y - 9 = 0",
             "y = 0", "y = 3", "y = 9", "y = -3", "B",
             "Add 9 to both sides: 3y = 9, then divide by 3: y = 3."),
            (45, "Solve for z: 4z + 8 = 32",
             "z = 4", "z = 8", "z = 6", "z = 10", "C",
             "Subtract 8: 4z = 24, divide by 4: z = 6."),
            (45, "If 5x - 3 = 22, what is x?",
             "x = 4", "x = 5", "x = 3.8", "x = 6", "B",
             "Add 3: 5x = 25, divide by 5: x = 5."),
            (45, "Solve: 7 - 2x = 1",
             "x = 4", "x = 3", "x = -3", "x = 6", "B",
             "Subtract 7: -2x = -6, divide by -2: x = 3."),

            # ── Mathematics: y-intercept (skill 78) ──
            (78, "Find the y-intercept of y = 3x - 7.",
             "(0, 3)", "(3, 0)", "(0, -7)", "(-7, 0)", "C",
             "The y-intercept is the constant term when x = 0: y = -7."),
            (78, "What is the y-intercept of 2x + 4y = 12?",
             "(0, 3)", "(6, 0)", "(0, 12)", "(0, 6)", "A",
             "Set x = 0: 4y = 12, so y = 3. Y-intercept is (0, 3)."),
            (78, "For y = -5x + 10, what is the y-intercept?",
             "10", "-5", "5", "-10", "A",
             "The y-intercept is the constant: +10."),
            (78, "Which point lies on the y-axis for y = 2x + 6?",
             "(2, 6)", "(0, 6)", "(6, 0)", "(3, 0)", "B",
             "At x = 0: y = 6, so the point is (0, 6)."),

            # ── Mathematics: Combining Like Terms (skill 102) ──
            (102, "Simplify: 5x + 3y - 2x + 7y",
             "7x + 10y", "3x + 10y", "10x + 3y", "3x + 4y", "B",
             "Combine x terms: 5x - 2x = 3x. Combine y terms: 3y + 7y = 10y."),
            (102, "Simplify: 4a + 2b - a - 5b",
             "3a - 3b", "5a - 3b", "3a + 7b", "4a - 3b", "A",
             "4a - a = 3a; 2b - 5b = -3b."),
            (102, "Simplify: 6x² + 3x - 2x² + x",
             "4x² + 4x", "8x² + 4x", "4x² + 2x", "8x² + 2x", "A",
             "6x² - 2x² = 4x²; 3x + x = 4x."),
            (102, "Simplify: 8m - 3n + 2m + 6n",
             "10m + 3n", "6m + 3n", "10m - 3n", "6m - 9n", "A",
             "8m + 2m = 10m; -3n + 6n = 3n."),

            # ── Mathematics: Finding Slope (skill 34) ──
            (34, "Find the slope of the line through (2, 3) and (4, 11).",
             "2", "4", "8", "0.5", "B",
             "Slope = (11-3)/(4-2) = 8/2 = 4."),
            (34, "What is the slope of the horizontal line y = 5?",
             "Undefined", "0", "5", "1", "B",
             "Horizontal lines have a slope of 0."),
            (34, "What is the slope of a vertical line?",
             "0", "1", "Undefined", "-1", "C",
             "Vertical lines have an undefined slope because the run is 0."),
            (34, "Find the slope of: y = -3x + 7",
             "7", "-3", "3", "-7", "B",
             "In y = mx + b, m is the slope. Here m = -3."),
            (34, "The slope of a line through (1, 2) and (3, 6) is:",
             "3", "2", "4", "1", "B",
             "Slope = (6-2)/(3-1) = 4/2 = 2."),

            # ── Mathematics: Pattern Finding (skill 19) ──
            (19, "What is the next number: 2, 6, 18, 54, ...?",
             "108", "162", "216", "72", "B",
             "Each term is multiplied by 3: 54 × 3 = 162."),
            (19, "Find the 6th term of: 3, 7, 11, 15, ...",
             "19", "23", "27", "31", "B",
             "Common difference is 4. 6th term = 3 + (5×4) = 23."),
            (19, "What is the missing number: 5, __, 17, 23, 29?",
             "9", "11", "13", "10", "B",
             "Common difference is 6: 5 + 6 = 11."),
            (19, "In the pattern 1, 4, 9, 16, ..., what is the 5th term?",
             "20", "25", "30", "36", "B",
             "These are perfect squares: 1², 2², 3², 4², 5² = 25."),

            # ── Mathematics: Pyramid Properties (skill 105) ──
            (105, "How many vertices does a square-based pyramid have?",
             "4", "5", "6", "8", "B",
             "A square pyramid has 4 base vertices + 1 apex = 5 vertices."),
            (105, "What shape forms the lateral faces of a pyramid?",
             "Triangles", "Squares", "Rectangles", "Pentagons", "A",
             "All lateral faces of a pyramid are triangles."),
            (105, "How many edges does a square pyramid have?",
             "6", "7", "8", "10", "C",
             "4 base edges + 4 lateral edges = 8 edges."),
            (105, "What is the base of a triangular pyramid (tetrahedron)?",
             "Square", "Pentagon", "Triangle", "Hexagon", "C",
             "A triangular pyramid has a triangular base."),

            # ── Mathematics: Perimeter Irregular (skill 112) ──
            (112, "Perimeter of a figure with sides 4, 7, 5, 3, 6 cm?",
             "20cm", "25cm", "22cm", "27cm", "B",
             "Add all sides: 4+7+5+3+6 = 25 cm."),
            (112, "An L-shape has sides 8, 4, 3, 2, 5, 2 m. What is the perimeter?",
             "24m", "22m", "26m", "20m", "A",
             "Add all sides: 8+4+3+2+5+2 = 24 m."),
            (112, "A rectangle has length 9 cm and width 4 cm. What is the perimeter?",
             "36cm", "13cm", "26cm", "18cm", "C",
             "Perimeter = 2(l + w) = 2(9 + 4) = 26 cm."),

            # ── Mathematics: Surface Area Pyramid (skill 88) ──
            (88, "Total surface area of a square pyramid with base 6m, slant height 5m?",
             "96 sq m", "60 sq m", "84 sq m", "120 sq m", "A",
             "Base area = 6² = 36. Lateral area = (1/2)×4×6×5 = 60. Total = 96 sq m."),
            (88, "Base area 25 sq cm, 4 lateral faces each 15 sq cm. Total SA?",
             "60 sq cm", "85 sq cm", "100 sq cm", "75 sq cm", "B",
             "25 + (4 × 15) = 25 + 60 = 85 sq cm."),
            (88, "A triangular pyramid has base area 16 sq m and 3 lateral faces each 10 sq m. SA?",
             "36 sq m", "46 sq m", "56 sq m", "66 sq m", "B",
             "16 + (3 × 10) = 16 + 30 = 46 sq m."),

            # ── Mathematics: Division Mixed Fractions (skill 64) ──
            (64, "Divide: 2½ ÷ 1¼",
             "2", "1½", "3", "2½", "A",
             "Convert: 5/2 ÷ 5/4 = 5/2 × 4/5 = 2."),
            (64, "Evaluate: 3⅓ ÷ 5/6",
             "4", "2½", "3⅔", "4½", "A",
             "3⅓ = 10/3. 10/3 ÷ 5/6 = 10/3 × 6/5 = 4."),
            (64, "What is 4½ ÷ 1½?",
             "2", "3", "4", "6", "B",
             "9/2 ÷ 3/2 = 9/2 × 2/3 = 3."),

            # ── Mathematics: Venn Diagrams (skill 12) ──
            (12, "In class of 30, 18 play Soccer, 14 Basketball, 5 play both. How many play neither?",
             "3", "5", "8", "2", "A",
             "Soccer only: 13, Basketball only: 9, Both: 5. Total = 27. Neither = 30 - 27 = 3."),
            (12, "Set A has 10 elements, Set B has 15, A∩B has 4. How many in A∪B?",
             "25", "21", "19", "29", "B",
             "A∪B = |A| + |B| - |A∩B| = 10 + 15 - 4 = 21."),
            (12, "In a group of 50, 30 like Tea, 25 like Coffee, 15 like both. How many like neither?",
             "5", "10", "15", "20", "B",
             "|T∪C| = 30 + 25 - 15 = 40. Neither = 50 - 40 = 10."),

            # ── Science: Newton's Laws (skill 201) ──
            (201, "Newton's First Law states that an object at rest remains at rest unless...",
             "acted upon by a net force", "it gains energy", "it loses mass", "it cools down", "A",
             "Newton's First Law (Law of Inertia): an object maintains its state unless a net external force acts on it."),
            (201, "Which quantity is measured in Newtons?",
             "Mass", "Weight (Force)", "Volume", "Speed", "B",
             "Force is measured in Newtons (N). Mass is in kilograms."),
            (201, "F = ma represents Newton's:",
             "First Law", "Second Law", "Third Law", "Law of Gravitation", "B",
             "F = ma is Newton's Second Law: Force equals mass times acceleration."),
            (201, "Action and reaction forces act on:",
             "the same object", "different objects", "only moving objects", "only stationary objects", "B",
             "Newton's Third Law: action and reaction forces act on different objects."),
            (201, "A 5 kg object accelerates at 3 m/s². What force acts on it?",
             "8 N", "2 N", "15 N", "1.67 N", "C",
             "F = m × a = 5 × 3 = 15 N."),

            # ── Science: Work, Energy and Power (skill 202) ──
            (202, "Work done = Force × ?",
             "Time", "Mass", "Displacement", "Velocity", "C",
             "Work (W) = Force (F) × Displacement (d) × cos(θ)."),
            (202, "A 10 N force moves an object 5 m. How much work is done?",
             "2 J", "50 J", "15 J", "0.5 J", "B",
             "W = F × d = 10 × 5 = 50 J."),
            (202, "The SI unit of energy is:",
             "Watt", "Newton", "Joule", "Calorie", "C",
             "Energy and work are both measured in Joules (J)."),
            (202, "Power = Work / ?",
             "Distance", "Time", "Force", "Mass", "B",
             "Power (P) = Work done (W) / Time taken (t). Unit: Watts."),
            (202, "Kinetic energy = ½ × m × ?",
             "v", "v²", "a", "F", "B",
             "KE = ½mv². It depends on the square of velocity."),

            # ── Science: Periodic Table (skill 203) ──
            (203, "What is the atomic number of Carbon?",
             "6", "12", "8", "14", "A",
             "Carbon (C) has atomic number 6 (6 protons)."),
            (203, "Which group of the periodic table contains Noble Gases?",
             "Group 1", "Group 2", "Group 17", "Group 18", "D",
             "Noble gases (He, Ne, Ar, etc.) are in Group 18 (also called Group 0 or VIIIA)."),
            (203, "The element with symbol 'Fe' is:",
             "Fluorine", "Iron", "Francium", "Fermium", "B",
             "Fe comes from the Latin 'Ferrum' meaning Iron."),
            (203, "How many elements are in the modern periodic table?",
             "98", "108", "118", "128", "C",
             "The modern periodic table has 118 confirmed elements."),

            # ── Science: Chemical Reactions (skill 204) ──
            (204, "In the reaction: 2H₂ + O₂ → 2H₂O, what type of reaction is this?",
             "Decomposition", "Displacement", "Combination (Synthesis)", "Neutralisation", "C",
             "Two or more substances combining to form one product = Synthesis/Combination reaction."),
            (204, "A substance with pH below 7 is:",
             "Neutral", "Acidic", "Basic", "Alkaline", "B",
             "pH < 7 indicates an acidic substance. pH 7 = neutral, pH > 7 = basic."),
            (204, "What is produced when an acid reacts with a base?",
             "Gas + Water", "Salt + Water", "Oxide + Water", "Base + Acid", "B",
             "Acid + Base → Salt + Water (neutralisation reaction)."),
            (204, "Which gas is produced when zinc reacts with dilute hydrochloric acid?",
             "Oxygen", "Carbon dioxide", "Hydrogen", "Chlorine", "C",
             "Zn + 2HCl → ZnCl₂ + H₂. Hydrogen gas is released."),

            # ── Science: Cell Structure (skill 205) ──
            (205, "Which organelle is called the 'powerhouse of the cell'?",
             "Nucleus", "Ribosome", "Mitochondria", "Chloroplast", "C",
             "Mitochondria produce ATP (energy), earning the name 'powerhouse of the cell'."),
            (205, "Which organelle contains the cell's genetic material (DNA)?",
             "Cytoplasm", "Nucleus", "Mitochondria", "Vacuole", "B",
             "The nucleus contains DNA organized into chromosomes."),
            (205, "The cell wall is present in:",
             "Animal cells only", "Plant cells only", "Both plant and animal cells", "Neither", "B",
             "Plant cells have a rigid cell wall made of cellulose; animal cells do not."),
            (205, "Which organelle is responsible for protein synthesis?",
             "Golgi apparatus", "Ribosome", "Lysosome", "Vacuole", "B",
             "Ribosomes are the site of protein synthesis in all cells."),

            # ── Science: Photosynthesis (skill 206) ──
            (206, "The raw materials for photosynthesis are CO₂, water, and:",
             "Oxygen", "Sunlight", "Glucose", "Nitrogen", "B",
             "Photosynthesis requires CO₂, H₂O, and sunlight energy."),
            (206, "Photosynthesis primarily takes place in which organelle?",
             "Mitochondria", "Ribosome", "Chloroplast", "Nucleus", "C",
             "Chloroplasts contain chlorophyll and are the site of photosynthesis."),
            (206, "What gas is released as a byproduct of photosynthesis?",
             "Carbon dioxide", "Nitrogen", "Oxygen", "Hydrogen", "C",
             "6CO₂ + 6H₂O + light → C₆H₁₂O₆ + 6O₂. Oxygen is the byproduct."),
            (206, "The green pigment in plants that absorbs sunlight is:",
             "Carotene", "Chlorophyll", "Xanthophyll", "Melanin", "B",
             "Chlorophyll absorbs mainly red and blue light for photosynthesis."),

            # ── English: Parts of Speech (skill 301) ──
            (301, "Identify the noun in: 'The dog chased the cat.'",
             "chased", "the", "dog", "quickly", "C",
             "A noun names a person, place, thing, or idea. 'Dog' and 'cat' are nouns."),
            (301, "Which word is an adjective in: 'She wore a beautiful dress.'?",
             "wore", "she", "beautiful", "dress", "C",
             "An adjective describes a noun. 'Beautiful' describes 'dress'."),
            (301, "In 'He runs fast', the word 'fast' is a(n):",
             "Adjective", "Noun", "Adverb", "Preposition", "C",
             "'Fast' modifies the verb 'runs', so it is an adverb."),
            (301, "Which is a conjunction in: 'I like coffee and tea.'?",
             "like", "and", "coffee", "I", "B",
             "'And' is a coordinating conjunction that joins 'coffee' and 'tea'."),
            (301, "The word 'quickly' is a(n):",
             "Noun", "Verb", "Adjective", "Adverb", "D",
             "'Quickly' modifies a verb and answers 'how', making it an adverb."),

            # ── English: Tenses (skill 302) ──
            (302, "Which sentence uses the past tense correctly?",
             "She go to school", "She goes to school", "She went to school", "She going to school", "C",
             "'Went' is the simple past tense of 'go'."),
            (302, "Choose the correct sentence with present perfect tense:",
             "I eat lunch", "I ate lunch", "I have eaten lunch", "I will eat lunch", "C",
             "Present perfect: have/has + past participle. 'Have eaten' is correct."),
            (302, "The subject and verb must agree in:",
             "Tense only", "Number only", "Both number and person", "Neither", "C",
             "Subject-verb agreement requires matching in both number (singular/plural) and person."),
            (302, "Fill in the blank: 'They ___ football every Sunday.'",
             "plays", "play", "played", "playing", "B",
             "Plural subject 'They' takes the base form 'play' (no 's')."),

            # ── English: Reading Comprehension (skill 303) ──
            (303, "What is the 'main idea' of a passage?",
             "The first sentence", "The central point the author wants to convey", "A supporting detail", "The title", "B",
             "The main idea is the central message or point of the entire passage."),
            (303, "An 'inference' is:",
             "A direct quote from the text", "A conclusion drawn from evidence", "A summary", "An opinion of the reader", "B",
             "Inference means reading between the lines using evidence and reasoning."),
            (303, "A 'context clue' helps you:",
             "Find the author's name", "Understand an unfamiliar word using surrounding text", "Identify the genre", "Count syllables", "B",
             "Context clues in surrounding sentences or phrases help determine word meaning."),

            # ── English: Essay Writing (skill 304) ──
            (304, "A well-structured essay has:",
             "Introduction only", "Body paragraphs only", "Introduction, body, and conclusion", "Just a thesis", "C",
             "A complete essay has three parts: introduction, body paragraphs, and conclusion."),
            (304, "The 'thesis statement' is found in the:",
             "Conclusion", "Body paragraph", "Introduction", "Title", "C",
             "The thesis statement, which states the essay's main argument, is in the introduction."),
            (304, "A 'topic sentence' in a body paragraph:",
             "Concludes the essay", "Introduces the main idea of that paragraph", "Lists examples only", "Starts the essay", "B",
             "Each body paragraph starts with a topic sentence that states the paragraph's main idea."),

            # ── Computer Science: Variables & Data Types (skill 401) ──
            (401, "Which data type stores whole numbers in Python?",
             "float", "str", "int", "bool", "C",
             "'int' stores integers (whole numbers) like 1, 42, -7."),
            (401, "What is the output of: print(type(3.14)) in Python?",
             "<class 'int'>", "<class 'str'>", "<class 'float'>", "<class 'bool'>", "C",
             "3.14 is a floating-point number, so its type is 'float'."),
            (401, "Which operator checks if two values are equal in Python?",
             "=", "==", "!=", "=>", "B",
             "'==' is the equality comparison operator. '=' is the assignment operator."),
            (401, "What does the '%' operator do?",
             "Division", "Exponentiation", "Modulus (remainder)", "Multiplication", "C",
             "The modulus operator '%' returns the remainder of division. E.g., 10 % 3 = 1."),
            (401, "x = 5; x += 3; What is the value of x?",
             "3", "5", "8", "15", "C",
             "'+=' adds the right value to the variable: x = 5 + 3 = 8."),

            # ── Computer Science: Conditionals & Loops (skill 402) ──
            (402, "What does an 'if-else' statement do?",
             "Repeats code", "Makes a decision based on a condition", "Defines a function", "Imports a module", "B",
             "An if-else statement executes different code blocks based on whether a condition is true or false."),
            (402, "How many times does 'for i in range(5)' iterate?",
             "4", "5", "6", "Infinite", "B",
             "range(5) generates 0, 1, 2, 3, 4 — exactly 5 iterations."),
            (402, "Which loop is guaranteed to execute at least once?",
             "for loop", "while loop", "do-while loop", "foreach loop", "C",
             "A do-while loop runs the body first, then checks the condition — guaranteeing at least one execution."),
            (402, "What keyword is used to exit a loop immediately in Python?",
             "exit", "stop", "break", "return", "C",
             "'break' terminates the current loop immediately and continues after the loop."),

            # ── Computer Science: Arrays and Lists (skill 403) ──
            (403, "In Python, a list is defined using:",
             "() parentheses", "[] square brackets", "{} curly braces", "<> angle brackets", "B",
             "Python lists use square brackets: my_list = [1, 2, 3]."),
            (403, "What is the index of the first element in a Python list?",
             "1", "-1", "0", "None", "C",
             "Python uses zero-based indexing: the first element is at index 0."),
            (403, "What does list.append(x) do?",
             "Removes x from list", "Inserts x at position 0", "Adds x to the end of the list", "Sorts the list", "C",
             "append() adds the element x to the end of the list."),
            (403, "What is the length of: [10, 20, 30, 40, 50]?",
             "4", "5", "6", "0", "B",
             "The list has 5 elements, so len() returns 5."),

            # ── Computer Science: Sorting Algorithms (skill 404) ──
            (404, "Bubble sort works by repeatedly:",
             "Dividing the list in half", "Swapping adjacent elements that are out of order", "Finding the minimum element", "Hashing each element", "B",
             "Bubble sort compares and swaps adjacent elements until the list is sorted."),
            (404, "What is the worst-case time complexity of Bubble Sort?",
             "O(n)", "O(n log n)", "O(n²)", "O(log n)", "C",
             "Bubble Sort has O(n²) worst-case complexity due to nested comparisons."),
            (404, "Selection sort works by:",
             "Swapping adjacent elements", "Finding the minimum element and placing it at the front", "Dividing and conquering", "Using a hash table", "B",
             "Selection sort finds the smallest element and swaps it to the correct position."),
            (404, "After one pass of bubble sort on [5, 3, 1, 4, 2], the largest element is:",
             "At index 0", "At the last position", "In the middle", "Unchanged", "B",
             "After one full pass, the largest element 'bubbles up' to the last position."),
        ]

        added = 0
        for row in questions_data:
            sk_id, text, opt_a, opt_b, opt_c, opt_d, ans, expl = row
            db.add(models.QuizQuestion(
                skill_id=sk_id,
                question=text,
                option_a=opt_a,
                option_b=opt_b,
                option_c=opt_c,
                option_d=opt_d,
                correct_answer=ans,
                explanation=expl
            ))
            added += 1
        db.commit()
        print(f"  [+] Seeded {added} quiz questions.")

        print("\n" + "=" * 60)
        print("DATABASE SEEDING COMPLETE")
        print("=" * 60)
        print("\nSubjects & Topics:")
        for s_name, _, s_icon in subjects_data:
            topics_in_subj = [sk_name for _, sk_name, sn in skills_data if sn == s_name]
            print(f"  {s_icon} {s_name}:")
            for t in topics_in_subj:
                print(f"      - {t}")
        print(f"\nReady to use:")
        print(f"  Teacher login  : {SEED_TEACHER_EMAIL} / {SEED_TEACHER_PASSWORD}")
        print(f"  Student login  : Register via the app at /register")
        print("\nNOTE: Students start with P_INIT BKT mastery (0.20).")
        print("      All analytics grow from REAL quiz interactions.")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"\n[-] Error seeding database: {e}")
        raise e
    finally:
        db.close()


def ensure_initial_data(db: Session = None):
    """
    Called on app startup to verify tables and ensure subjects, skills, and quiz questions exist.
    Never drops tables or deletes user records.
    """
    Base.metadata.create_all(bind=engine)
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True
    try:
        if db.query(models.Subject).count() == 0:
            print("[Auto-Seed] Empty database detected. Seeding initial academic curriculum...")
            seed_database(reset=False)
        else:
            print("[Auto-Seed] Database already seeded. Preserving existing records.")
    finally:
        if close_db:
            db.close()


if __name__ == "__main__":
    reset_arg = "--reset" in sys.argv
    seed_database(reset=reset_arg)
