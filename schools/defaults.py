DEFAULT_LEVELS = [
    ("Creche", "skills"),
    ("Nursery 1", "skills"),
    ("Nursery 2", "skills"),
    ("Nursery 3", "skills"),
    ("Primary 1", "scored"),
    ("Primary 2", "scored"),
    ("Primary 3", "scored"),
    ("Primary 4", "scored"),
    ("Primary 5", "scored"),
    ("Primary 6", "scored"),
    ("JSS 1", "scored"),
    ("JSS 2", "scored"),
    ("JSS 3", "scored"),
    ("SSS 1", "scored"),
    ("SSS 2", "scored"),
    ("SSS 3", "scored"),
]

PRIMARY_SUBJECTS = [
    "English Language",
    "Mathematics",
    "Basic Science",
    "Social Studies",
    "Civic Education",
    "Christian Religious Studies",
    "Quantitative Reasoning",
    "Verbal Reasoning",
    "Computer Studies",
    "Creative Arts",
    "Physical and Health Education",
    "French",
]

JUNIOR_SUBJECTS = [
    "English Language",
    "Mathematics",
    "Basic Science",
    "Basic Technology",
    "Social Studies",
    "Civic Education",
    "Business Studies",
    "Computer Studies",
    "Agricultural Science",
    "Home Economics",
    "Cultural and Creative Arts",
    "PHE",
    "CRS",
    "French",
]

SENIOR_SUBJECTS = [
    "English Language",
    "Mathematics",
    "Civic Education",
    "Biology",
    "Chemistry",
    "Physics",
    "Economics",
    "Government",
    "Literature in English",
    "Further Mathematics",
    "Computer Studies",
    "Agricultural Science",
    "CRS",
    "Commerce",
    "Accounting",
    "Geography",
]

NURSERY_SKILLS = [
    "Recognises colours",
    "Counts 1 to 20",
    "Identifies letters",
    "Follows simple instructions",
    "Shares with others",
    "Uses the toilet independently",
    "Sings and recites",
    "Holds a pencil",
]

DEFAULT_COMPONENTS = [("CA1", 10, 1), ("CA2", 10, 2), ("Assignment", 10, 3), ("Exam", 70, 4)]

SECONDARY_GRADES = [
    (75, 100, "A1", "Excellent"),
    (70, 74.99, "B2", "Very good"),
    (65, 69.99, "B3", "Good"),
    (60, 64.99, "C4", "Credit"),
    (55, 59.99, "C5", "Credit"),
    (50, 54.99, "C6", "Credit"),
    (45, 49.99, "D7", "Pass"),
    (40, 44.99, "E8", "Pass"),
    (0, 39.99, "F9", "Fail"),
]

PRIMARY_GRADES = [
    (70, 100, "A", "Excellent"),
    (60, 69.99, "B", "Very good"),
    (50, 59.99, "C", "Good"),
    (40, 49.99, "D", "Fair"),
    (0, 39.99, "E", "Fail"),
]

AFFECTIVE = ["Punctuality", "Neatness", "Politeness", "Honesty", "Attentiveness"]
PSYCHOMOTOR = ["Handwriting", "Sports", "Drawing", "Verbal fluency"]

COMMENT_BANK = [
    ("class_teacher", 70, 100, "An outstanding term. Keep this excellent standard."),
    ("class_teacher", 55, 69.99, "A good result. A little more effort will produce distinction."),
    ("class_teacher", 40, 54.99, "A fair performance. More seriousness is required next term."),
    ("class_teacher", 0, 39.99, "This result is below expectation. The student needs close support."),
    ("head_of_school", 70, 100, "Excellent work. The school is proud of this performance."),
    ("head_of_school", 55, 69.99, "A commendable effort. Aim higher next term."),
    ("head_of_school", 40, 54.99, "There is room for improvement. Parents should supervise home study."),
    ("head_of_school", 0, 39.99, "This performance is not satisfactory. A meeting with the school is advised."),
]


def subjects_for_level(name):
    lowered = name.lower()
    if "sss" in lowered or "ss " in lowered:
        return SENIOR_SUBJECTS
    if "jss" in lowered:
        return JUNIOR_SUBJECTS
    if "primary" in lowered:
        return PRIMARY_SUBJECTS
    return []
