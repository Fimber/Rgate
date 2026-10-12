"""Result card presentation: which template a school uses, and sample data for example photos."""

TEMPLATES = [
    ("classic", "Classic", "Centred crest-style heading, double rule, ruled rows. The traditional booklet look."),
    ("compact", "Compact", "One-line heading and a tight table without remarks. Fits big subject lists on one page."),
    ("colour", "Colour band", "Bold band in your brand colour and tinted rows. Reads well on phones."),
]


def card_options(school):
    """Template context for results/_card.html, from the school's current rules."""
    if school is None:
        return {}
    return {"card_template": school.result_template, "hide_positions": not school.show_positions}


def sample_snapshot(brand_colour="#0B3D2E"):
    """A realistic result used for the example photos in setup and settings."""
    subjects = [
        ("English Language", 8, 9, 7, 52, "A1", "Excellent", "2nd", "64.20"),
        ("Mathematics", 9, 8, 9, 58, "A1", "Excellent", "1st", "61.75"),
        ("Basic Science", 7, 8, 8, 44, "B3", "Good", "5th", "58.10"),
        ("Basic Technology", 6, 7, 8, 41, "C4", "Credit", "9th", "57.40"),
        ("Social Studies", 9, 9, 8, 50, "A1", "Excellent", "3rd", "63.00"),
        ("Civic Education", 8, 7, 9, 47, "B2", "Very good", "4th", "60.30"),
        ("Christian Religious Studies", 7, 8, 7, 49, "B2", "Very good", "6th", "62.85"),
        ("Yoruba", 8, 6, 7, 38, "C5", "Credit", "12th", "55.90"),
        ("Agricultural Science", 7, 7, 8, 45, "B3", "Good", "7th", "59.60"),
        ("Computer Studies", 9, 9, 9, 55, "A1", "Excellent", "1st", "66.10"),
    ]
    rows = []
    for name, ca1, ca2, assignment, exam, grade, remark, position, average in subjects:
        total = ca1 + ca2 + assignment + exam
        rows.append(
            {
                "name": name,
                "components": {
                    "CA1": f"{ca1}.00",
                    "CA2": f"{ca2}.00",
                    "Assignment": f"{assignment}.00",
                    "Exam": f"{exam}.00",
                },
                "total": f"{total}.00",
                "grade": grade,
                "remark": remark,
                "position": position,
                "class_average": average,
            }
        )
    return {
        "result_code": "SAMPLE7KQ4MX",
        "school": {
            "name": "Greenfield College",
            "address": "Nkpolu-Oroworukwo, Port Harcourt, Rivers State",
            "motto": "Knowledge and character",
            "phone": "08011111111",
            "email": "office@greenfield.sch.ng",
            "brand_colour": brand_colour,
        },
        "student": {"name": "Nnamdi Adaeze Chioma", "admission_number": "GFC/001", "sex": "Female", "class": "JSS 1 A"},
        "term": {"session": "2025/2026", "name": "First", "resumption": "2026-01-12", "days_opened": 68},
        "summary": {
            "total": "720.00",
            "average": "72.00",
            "position": "3rd",
            "class_size": 34,
            "subjects_offered": 10,
            "cumulative_average": "72.00",
            "promotion": "Pending",
            "days_present": 64,
            "incomplete": False,
        },
        "subjects": rows,
        "ratings": {"Punctuality": 5, "Neatness": 4, "Politeness": 5, "Honesty": 5, "Attentiveness": 4},
        "comments": {
            "class_teacher": "Adaeze is focused and helpful in class. Keep reading every evening.",
            "head_of_school": "A strong term. Well done.",
        },
        "grading_key": [
            {"label": "A1", "range": "75-100", "remark": "Excellent"},
            {"label": "B2", "range": "70-74.99", "remark": "Very good"},
            {"label": "B3", "range": "65-69.99", "remark": "Good"},
            {"label": "C4-C6", "range": "50-64.99", "remark": "Credit"},
            {"label": "D7-E8", "range": "40-49.99", "remark": "Pass"},
            {"label": "F9", "range": "0-39.99", "remark": "Fail"},
        ],
    }
