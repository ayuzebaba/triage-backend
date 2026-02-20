from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI()

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------
# Data Models
# ------------------------------
class AnswerEntry(BaseModel):
    question: str
    answer: str

class SymptomInput(BaseModel):
    message: str
    symptom_type: Optional[str] = None
    question_index: int = 0
    phase: str = "triage"
    all_answers: Optional[List[AnswerEntry]] = []
    detected_symptoms: Optional[List[str]] = []   # all symptoms found in initial message
    triaged_symptoms: Optional[List[str]] = []     # symptoms already fully triaged

# ------------------------------
# Symptom detection keywords
# ------------------------------
SYMPTOM_KEYWORDS = {
    "headache": [
        "headache", "head pain", "migraine", "throbbing head", "head hurts", "head ache"
    ],
    "chest pain": [
        "chest pain", "chest hurts", "chest tightness", "pressure in chest",
        "tightness in chest", "chest discomfort"
    ],
    "running nose": [
        "running nose", "runny nose", "nasal discharge", "nose running",
        "congestion", "blocked nose", "stuffy nose", "sneezing"
    ],
    "fever": [
        "fever", "high temperature", "feeling hot", "chills", "sweating and cold",
        "temperature", "febrile"
    ],
    "cough": [
        "cough", "coughing", "dry cough", "wet cough", "persistent cough"
    ],
    "sore throat": [
        "sore throat", "throat pain", "throat hurts", "difficulty swallowing",
        "painful swallow", "scratchy throat"
    ],
    "shortness of breath": [
        "shortness of breath", "can't breathe", "cannot breathe",
        "difficulty breathing", "breathless", "out of breath"
    ],
    "abdominal pain": [
        "abdominal pain", "stomach pain", "belly pain", "stomach ache",
        "stomach hurts", "belly hurts", "tummy pain", "cramping", "cramps"
    ],
    "dizziness": [
        "dizzy", "dizziness", "lightheaded", "light-headed", "vertigo",
        "spinning", "unsteady", "balance problems"
    ],
    "nausea": [
        "nausea", "nauseous", "feeling sick", "want to vomit", "queasy"
    ],
    "vomiting": [
        "vomiting", "vomited", "throwing up", "threw up", "been sick"
    ],
    "fatigue": [
        "fatigue", "tired", "exhausted", "weakness", "weak", "no energy",
        "lethargic", "lethargy"
    ],
    "rash": [
        "rash", "skin rash", "hives", "spots on skin", "itchy skin",
        "skin irritation", "red spots"
    ],
    "back pain": [
        "back pain", "back hurts", "lower back", "upper back", "spine pain"
    ],
    "joint pain": [
        "joint pain", "joint ache", "arthritis", "swollen joint", "stiff joints"
    ],
}

# Symptoms that are commonly benign / viral in nature
BENIGN_SYMPTOMS = {
    "running nose", "cough", "sore throat", "fever", "fatigue", "nausea"
}

# When these benign symptoms appear alongside a potentially serious symptom,
# reduce the red flag score by this amount
BENIGN_MODIFIER = -1

# ------------------------------
# Red flag question tags
# ------------------------------
red_flag_question_tags = {
    "Is this the worst headache of your life, or did it come on suddenly like a thunderclap?": ("headache", 3),
    "Do you have any neck stiffness, fever, confusion, or visual disturbances?": ("headache", 2),
    "Do you have nausea, vomiting, or sensitivity to light or sound?": ("headache", 1),
    "Does the pain radiate to your left arm, shoulder, or jaw?": ("chest pain", 2),
    "Do you have shortness of breath or difficulty breathing?": ("chest pain", 2),
    "Do you have sweating, palpitations, or did you feel faint?": ("chest pain", 2),
    "Can you describe the type of pain? (pressure, crushing, sharp, burning)": ("chest pain", 1),
}

affirmative_answers = [
    "yes", "yeah", "yep", "yup", "correct", "absolutely", "definitely",
    "i do", "i have", "i am", "it is", "that's right", "thats right",
    "positive", "confirmed", "right", "indeed", "certainly", "sure"
]

# ------------------------------
# Red flag rules
# ------------------------------
red_flag_rules = {
    "headache": {
        "threshold": 2,
        "triggers": [
            (3, ["worst headache of my life", "worst headache ever", "thunderclap", "sudden severe headache"]),
            (2, ["neck stiffness", "stiff neck", "photophobia", "sensitivity to light"]),
            (2, ["confusion", "confused", "disoriented", "altered consciousness"]),
            (2, ["seizure", "fitting", "fit"]),
            (2, ["vision loss", "blurred vision", "double vision"]),
            (1, ["fever", "high temperature", "vomiting", "weakness", "numbness"]),
        ]
    },
    "chest pain": {
        "threshold": 2,
        "triggers": [
            (3, ["heart attack", "cardiac arrest"]),
            (2, ["radiating to arm", "radiating to jaw", "left arm pain", "jaw pain"]),
            (2, ["shortness of breath", "can't breathe", "cannot breathe", "difficulty breathing"]),
            (2, ["sweating", "cold sweat", "drenched in sweat"]),
            (2, ["fainted", "syncope", "passed out", "loss of consciousness"]),
            (1, ["crushing", "pressure", "squeezing", "elephant on my chest", "heavy chest"]),
            (1, ["palpitations", "heart racing", "fast heart", "irregular heartbeat"]),
        ]
    },
    "shortness of breath": {
        "threshold": 2,
        "triggers": [
            (3, ["cannot breathe at all", "turning blue", "lips turning blue"]),
            (2, ["chest pain", "chest tightness", "heart racing"]),
            (2, ["sudden onset", "came on suddenly"]),
            (1, ["worsening", "getting worse", "severe"]),
        ]
    },
    "abdominal pain": {
        "threshold": 2,
        "triggers": [
            (3, ["severe", "excruciating", "worst pain"]),
            (2, ["rigid abdomen", "board-like", "rebound tenderness"]),
            (2, ["vomiting blood", "blood in stool", "black stool"]),
            (1, ["fever", "nausea", "vomiting"]),
        ]
    },
    "other": {
        "threshold": 2,
        "triggers": [
            (3, ["unconscious", "not breathing", "cardiac arrest"]),
            (2, ["coughing blood", "vomiting blood", "bleeding heavily"]),
            (2, ["can't breathe", "cannot breathe", "severe difficulty breathing"]),
            (1, ["severe pain", "excruciating", "worst pain"]),
        ]
    }
}

red_flag_messages = {
    "headache": "🚨 RED FLAG: Based on your symptoms, there are signs that may indicate a serious neurological condition such as meningitis or a subarachnoid haemorrhage. Please call 999/112 or go to your nearest emergency department immediately.",
    "chest pain": "🚨 RED FLAG: Based on your symptoms, there are signs that may indicate a serious cardiac event such as a heart attack. Please call 999/112 or go to your nearest emergency department immediately.",
    "shortness of breath": "🚨 RED FLAG: Severe difficulty breathing can indicate a life-threatening condition. Please call 999/112 or go to your nearest emergency department immediately.",
    "abdominal pain": "🚨 RED FLAG: Your abdominal symptoms may indicate a serious condition requiring urgent care. Please go to your nearest emergency department immediately.",
    "other": "🚨 RED FLAG: Based on your symptoms, there are signs of a potentially serious condition. Please seek emergency care immediately or call 999/112."
}

# Risk-stratified completion messages
completion_messages = {
    "high": "🚨 URGENT: Based on everything you have described, your symptoms require immediate emergency attention. Please call 999/112 or go to your nearest emergency department NOW. Do not wait.",
    "medium": "⚠️ ATTENTION: Based on your symptoms, we recommend you seek medical attention today. Please contact your GP urgently or go to an urgent care centre. Do not ignore these symptoms.",
    "low": "✅ Thank you for the information. Your responses have been recorded. Please contact your GP or a healthcare professional for further assessment."
}

# ------------------------------
# Follow-up questions per symptom
# ------------------------------
follow_up_questions = {
    "headache": [
        "When did the headache start?",
        "Is this the worst headache of your life, or did it come on suddenly like a thunderclap?",
        "Can you describe the type of pain? (sharp, dull, throbbing)",
        "Where exactly is the pain located?",
        "Do you have nausea, vomiting, or sensitivity to light or sound?",
        "Do you have any neck stiffness, fever, confusion, or visual disturbances?",
        "Have you taken any medication for it, and if so, did it help?"
    ],
    "chest pain": [
        "When did the chest pain start?",
        "Can you describe the type of pain? (pressure, crushing, sharp, burning)",
        "Does the pain radiate to your left arm, shoulder, or jaw?",
        "Do you have shortness of breath or difficulty breathing?",
        "Do you have sweating, palpitations, or did you feel faint?",
        "Do you have any history of heart disease or similar episodes before?"
    ],
    "running nose": [
        "How long have you had the runny nose?",
        "Is the discharge clear, yellow, or green?",
        "Do you have any other symptoms such as sore throat or cough?",
        "Do you have a fever or feel generally unwell?"
    ],
    "fever": [
        "How high is your temperature?",
        "How long have you had the fever?",
        "Do you have any other symptoms such as rash, neck stiffness, or confusion?",
        "Have you taken any medication to bring the fever down?"
    ],
    "cough": [
        "How long have you had the cough?",
        "Is it a dry cough or are you bringing up phlegm?",
        "Do you have any shortness of breath or chest pain?",
        "Do you have a fever or feel generally unwell?"
    ],
    "sore throat": [
        "How long have you had the sore throat?",
        "Do you have difficulty swallowing?",
        "Do you have a fever or swollen glands in your neck?",
        "Do you have any other symptoms such as rash or ear pain?"
    ],
    "shortness of breath": [
        "When did the shortness of breath start?",
        "Did it come on suddenly or gradually?",
        "Do you have any chest pain or tightness?",
        "Do you have a history of asthma, COPD, or heart problems?",
        "Are you experiencing it right now at rest?"
    ],
    "abdominal pain": [
        "Where exactly is the pain located in your abdomen?",
        "When did it start and how severe is it on a scale of 1 to 10?",
        "Is the pain constant or does it come and go?",
        "Do you have nausea, vomiting, or diarrhoea?",
        "Do you have a fever or any changes in your bowel habits?"
    ],
    "dizziness": [
        "When did the dizziness start?",
        "Does the room feel like it is spinning, or do you feel lightheaded?",
        "Is it triggered by standing up or moving your head?",
        "Do you have any hearing loss, ringing in the ears, or nausea?"
    ],
    "nausea": [
        "How long have you been feeling nauseous?",
        "Have you actually vomited?",
        "Do you have any abdominal pain or diarrhoea?",
        "Could this be related to something you ate or a medication?"
    ],
    "vomiting": [
        "How many times have you vomited and how long has this been going on?",
        "Is there any blood in the vomit?",
        "Do you have abdominal pain or diarrhoea alongside this?",
        "Are you able to keep any fluids down?"
    ],
    "fatigue": [
        "How long have you been feeling this way?",
        "Is the fatigue constant or does it come and go?",
        "Do you have any other symptoms such as fever, weight loss, or shortness of breath?",
        "Has anything changed recently such as sleep, diet, or stress levels?"
    ],
    "rash": [
        "Where on your body is the rash?",
        "When did it appear and is it spreading?",
        "Is it itchy, painful, or neither?",
        "Do you have a fever or any other symptoms alongside the rash?"
    ],
    "back pain": [
        "Where exactly is the pain — lower back, upper back, or between the shoulders?",
        "When did it start and what were you doing?",
        "Does the pain radiate anywhere such as down your leg?",
        "Do you have any numbness, tingling, or weakness in your legs?"
    ],
    "joint pain": [
        "Which joints are affected?",
        "Is there any swelling, redness, or warmth around the joint?",
        "When did it start and did anything trigger it?",
        "Do you have a fever or feel generally unwell?"
    ],
    "other": [
        "Can you describe your symptom in more detail?",
        "When did it start, and how severe is it on a scale of 1 to 10?",
        "Does anything make it better or worse?",
        "Do you have any other symptoms alongside this?",
        "Do you have any relevant medical history or are you currently on any medications?"
    ]
}

# Priority order — more serious symptoms triaged first
SYMPTOM_PRIORITY = [
    "chest pain", "shortness of breath", "abdominal pain",
    "headache", "dizziness", "vomiting", "fever",
    "cough", "sore throat", "running nose",
    "nausea", "fatigue", "rash", "back pain", "joint pain", "other"
]

# ------------------------------
# Helper functions
# ------------------------------
def detect_all_symptoms(text: str) -> List[str]:
    """Detect all symptoms mentioned in the text."""
    text_lower = text.lower()
    found = []
    for symptom, keywords in SYMPTOM_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(symptom)
    return found

def prioritize_symptoms(symptoms: List[str]) -> List[str]:
    """Sort symptoms by clinical priority."""
    def priority_key(s):
        try:
            return SYMPTOM_PRIORITY.index(s)
        except ValueError:
            return len(SYMPTOM_PRIORITY)
    return sorted(symptoms, key=priority_key)

def get_next_symptom_to_triage(detected: List[str], triaged: List[str]) -> str:
    """Get the next highest-priority symptom that hasn't been triaged yet."""
    prioritized = prioritize_symptoms(detected)
    for s in prioritized:
        if s not in triaged:
            return s
    return None

def is_affirmative(answer: str) -> bool:
    answer = answer.lower().strip()
    return any(answer.startswith(a) or answer == a for a in affirmative_answers)

def is_negative(answer: str) -> bool:
    negatives = ["no", "nope", "nah", "negative", "not really", "don't",
                 "dont", "i don't", "i dont", "none"]
    answer = answer.lower().strip()
    return any(answer.startswith(n) or answer == n for n in negatives)

def has_benign_co_symptoms(detected_symptoms: List[str]) -> bool:
    """Check if benign symptoms are present alongside serious ones."""
    has_serious = any(s not in BENIGN_SYMPTOMS for s in detected_symptoms)
    has_benign = any(s in BENIGN_SYMPTOMS for s in detected_symptoms)
    return has_serious and has_benign

def calculate_red_flag_score(all_answers: List[AnswerEntry], symptom_key: str,
                              detected_symptoms: List[str]) -> int:
    rules = red_flag_rules.get(symptom_key, red_flag_rules["other"])
    score = 0
    scored_tags = set()

    for entry in all_answers:
        question = entry.question.strip()
        answer = entry.answer.strip()

        # Method 1: Question-aware scoring
        if question in red_flag_question_tags:
            tag_symptom, weight = red_flag_question_tags[question]
            if tag_symptom == symptom_key and question not in scored_tags:
                if is_affirmative(answer):
                    score += weight
                    scored_tags.add(question)
                elif not is_negative(answer):
                    answer_lower = answer.lower()
                    for w, keywords in rules["triggers"]:
                        if any(kw in answer_lower for kw in keywords):
                            score += w
                            scored_tags.add(question)
                            break

        # Method 2: Direct keyword scanning
        answer_lower = answer.lower()
        for w, keywords in rules["triggers"]:
            if any(kw in answer_lower for kw in keywords):
                score += w
                break

    # Apply benign co-symptom modifier
    if has_benign_co_symptoms(detected_symptoms):
        score += BENIGN_MODIFIER

    return max(score, 0)

def determine_risk_level(score: int, symptom_key: str) -> str:
    rules = red_flag_rules.get(symptom_key, red_flag_rules["other"])
    threshold = rules["threshold"]
    if score >= threshold * 2:
        return "high"
    elif score >= threshold:
        return "medium"
    return "low"

def check_red_flags(all_answers: List[AnswerEntry], symptom_key: str,
                    detected_symptoms: List[str]) -> tuple:
    score = calculate_red_flag_score(all_answers, symptom_key, detected_symptoms)
    rules = red_flag_rules.get(symptom_key, red_flag_rules["other"])
    red_flag = score >= rules["threshold"]
    risk_level = determine_risk_level(score, symptom_key)
    return red_flag, risk_level

@app.get("/")
def root():
    return {"message": "Triage AI Backend Running"}

@app.post("/triage")
def triage(symptom: SymptomInput):
    # --- Detect all symptoms on first message ---
    detected_symptoms = list(symptom.detected_symptoms or [])
    triaged_symptoms = list(symptom.triaged_symptoms or [])

    if not detected_symptoms:
        detected_symptoms = detect_all_symptoms(symptom.message)
        if not detected_symptoms:
            detected_symptoms = ["other"]

    # --- Determine which symptom to triage now ---
    if symptom.symptom_type and symptom.symptom_type in detected_symptoms:
        symptom_key = symptom.symptom_type.lower()
    else:
        symptom_key = get_next_symptom_to_triage(detected_symptoms, triaged_symptoms)
        if not symptom_key:
            symptom_key = "other"

    if symptom_key not in follow_up_questions:
        symptom_key = "other"

    # --- Build answer history ---
    questions = follow_up_questions.get(symptom_key, follow_up_questions["other"])
    idx = symptom.question_index

    current_question = ""
    if idx > 0 and idx <= len(questions):
        current_question = questions[idx - 1]

    all_answers = list(symptom.all_answers or [])
    all_answers.append(AnswerEntry(question=current_question, answer=symptom.message))

    # --- Red flag check ---
    red_flag, risk_level = check_red_flags(all_answers, symptom_key, detected_symptoms)
    red_flag_message = red_flag_messages.get(symptom_key) if red_flag else None

    phase = symptom.phase

    # --- Additional info phase ---
    if phase == "additional":
        message_lower = symptom.message.lower().strip()
        no_indicators = [
            "no", "nope", "nothing", "that's all", "thats all",
            "no thanks", "done", "nothing else", "no more", "all good", "that is all"
        ]
        if any(message_lower == ind or message_lower.startswith(ind) for ind in no_indicators):
            # Check if there are more symptoms to triage
            remaining = [s for s in detected_symptoms if s not in triaged_symptoms]
            if remaining:
                # Move to next symptom
                triaged_symptoms.append(symptom_key)
                next_symptom = get_next_symptom_to_triage(detected_symptoms, triaged_symptoms)
                if next_symptom:
                    next_questions = follow_up_questions.get(next_symptom, follow_up_questions["other"])
                    return {
                        "symptom_type": next_symptom,
                        "question_index": 1,
                        "phase": "triage",
                        "next_question": next_questions[0],
                        "red_flag": red_flag,
                        "red_flag_message": red_flag_message,
                        "risk_level": risk_level,
                        "detected_symptoms": detected_symptoms,
                        "triaged_symptoms": triaged_symptoms,
                        "transition_message": f"Now let me ask you about your {next_symptom}."
                    }

            # All symptoms triaged — final completion
            return {
                "symptom_type": symptom_key,
                "question_index": idx,
                "phase": "done",
                "next_question": completion_messages[risk_level],
                "red_flag": red_flag,
                "red_flag_message": red_flag_message,
                "risk_level": risk_level,
                "detected_symptoms": detected_symptoms,
                "triaged_symptoms": triaged_symptoms,
                "transition_message": None
            }
        else:
            return {
                "symptom_type": symptom_key,
                "question_index": idx,
                "phase": "additional",
                "next_question": "Thank you for sharing that. Is there anything else you would like to add?",
                "red_flag": red_flag,
                "red_flag_message": red_flag_message,
                "risk_level": risk_level,
                "detected_symptoms": detected_symptoms,
                "triaged_symptoms": triaged_symptoms,
                "transition_message": None
            }

    # --- Normal triage phase ---
    if idx >= len(questions):
        # Done with this symptom's questions
        triaged_symptoms.append(symptom_key)
        remaining = [s for s in detected_symptoms if s not in triaged_symptoms]

        if remaining:
            # Move to next symptom automatically
            next_symptom = get_next_symptom_to_triage(detected_symptoms, triaged_symptoms)
            next_questions = follow_up_questions.get(next_symptom, follow_up_questions["other"])
            return {
                "symptom_type": next_symptom,
                "question_index": 1,
                "phase": "triage",
                "next_question": next_questions[0],
                "red_flag": red_flag,
                "red_flag_message": red_flag_message,
                "risk_level": risk_level,
                "detected_symptoms": detected_symptoms,
                "triaged_symptoms": triaged_symptoms,
                "transition_message": f"Thank you. Now let me ask you a few questions about your {next_symptom}."
            }
        else:
            # All done — go to additional info phase
            next_question = "Is there anything else you would like to add, or any other symptoms you would like to mention?"
            next_phase = "additional"
    else:
        next_question = questions[idx]
        next_phase = "triage"

    return {
        "symptom_type": symptom_key,
        "question_index": idx + 1,
        "phase": next_phase,
        "next_question": next_question,
        "red_flag": red_flag,
        "red_flag_message": red_flag_message,
        "risk_level": risk_level,
        "detected_symptoms": detected_symptoms,
        "triaged_symptoms": triaged_symptoms,
        "transition_message": None
    }