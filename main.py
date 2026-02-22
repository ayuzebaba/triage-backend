from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI()

origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://clinic-support.vercel.app",
    "https://triage-backend-production.up.railway.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# YES------------------------------
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
    detected_symptoms: Optional[List[str]] = []
    triaged_symptoms: Optional[List[str]] = []
    risk_score: Optional[int] = 0
    current_pathway: Optional[str] = None

# ------------------------------
# Presenting symptom keywords
# ------------------------------
SYMPTOM_KEYWORDS = {
    "headache": [
        "headache", "head pain", "head hurts", "head ache", "pain in my head",
        "head is pounding", "head is killing me", "worst headache"
    ],
    "chest pain": [
        "chest pain", "chest hurts", "chest tightness", "pressure in chest",
        "tightness in chest", "chest discomfort", "heart pain", "pain in chest"
    ],
    "seizure": [
        "seizure", "fitting", "fit", "convulsion", "shaking uncontrollably",
        "blacked out and shook", "epilepsy", "epileptic"
    ],
    "head injury": [
        "hit my head", "head injury", "concussion", "blow to the head",
        "fell and hit", "knocked my head", "sports injury to head", "head trauma"
    ],
    "trauma": [
        "trauma", "boxing", "fight", "assault", "knocked out", "accident",
        "fall", "injured", "injury", "hit by", "run over", "knocked down"
    ],
    "blackout": [
        "blacked out", "blackout", "fainted", "faint", "lost consciousness",
        "passed out", "syncope", "collapsed", "fell unconscious"
    ],
    "rectal bleed": [
        "rectal bleed", "blood in stool", "bleeding from rectum", "blood when wiping",
        "black stool", "bloody stool", "rectal bleeding", "blood in poo",
        "blood in toilet", "blood from back passage"
    ],
    "diarrhea": [
        "diarrhea", "diarrhoea", "loose stool", "watery stool", "frequent bowel",
        "runny stool", "bowels running", "loose bowels"
    ],
    "suicidal thoughts": [
        "suicide", "suicidal", "want to die", "kill myself", "end my life",
        "no reason to live", "better off dead", "harm myself", "hurt myself",
        "not want to be here", "don't want to live"
    ],
    "overdose": [
        "overdose", "took too many", "too many pills", "drug overdose",
        "accidental overdose", "took too much medication", "swallowed too many",
        "took an overdose"
    ],
    "shortness of breath": [
        "shortness of breath", "can't breathe", "cannot breathe", "sob",
        "difficulty breathing", "breathless", "out of breath", "dyspnea",
        "dyspnoea", "struggling to breathe", "hard to breathe"
    ],
    "vomiting": [
        "vomiting", "vomited", "throwing up", "threw up", "been sick",
        "nausea and vomiting", "sick to stomach"
    ],
    "cough": [
        "cough", "coughing", "dry cough", "wet cough", "persistent cough",
        "cannot stop coughing"
    ],
    "sore throat": [
        "sore throat", "throat pain", "throat hurts", "difficulty swallowing",
        "painful swallow", "scratchy throat", "throat is killing me"
    ],
    "dysuria": [
        "dysuria", "burning when urinating", "burning when peeing",
        "pain when urinating", "pain when peeing", "stinging when urinating",
        "burning urine", "painful urination", "pain passing urine"
    ],
    "urinary frequency": [
        "frequent urination", "urinating a lot", "peeing a lot", "going to toilet a lot",
        "cannot hold urine", "urgency to urinate", "urge to urinate"
    ],
    "genital discharge": [
        "discharge", "unusual discharge", "genital discharge",
        "discharge from genitals", "fluid from genitals", "abnormal discharge"
    ],
    "genital sore": [
        "genital sore", "sore on genitals", "ulcer on genitals", "blister on genitals",
        "genital ulcer", "painful sore down there", "sore down below"
    ],
    "dyspareunia": [
        "dyspareunia", "painful intercourse", "pain during sex", "pain after sex",
        "sex is painful", "hurts during sex", "burning after intercourse"
    ],
    "joint pain": [
        "joint pain", "joint ache", "arthritis", "swollen joint", "stiff joints",
        "knee pain", "hip pain", "shoulder pain", "elbow pain", "wrist pain",
        "ankle pain", "painful joints"
    ],
    "migraine": [
        "migraine", "migraine headache", "aura", "visual aura",
        "one sided headache", "throbbing headache with nausea"
    ],
    "abdominal pain": [
        "abdominal pain", "stomach pain", "belly pain", "stomach ache",
        "stomach hurts", "belly hurts", "tummy pain", "cramping", "cramps",
        "pain in stomach", "lower abdominal pain"
    ],
    "low blood sugar": [
        "low blood sugar", "hypoglycemia", "hypoglycaemia", "sugar dropped",
        "diabetic episode", "blood sugar low", "glucose low", "feeling shaky diabetic"
    ],
}

EMERGENCY_SYMPTOMS = {
    "headache", "chest pain", "seizure", "head injury", "trauma",
    "blackout", "rectal bleed", "suicidal thoughts", "overdose", "shortness of breath",
    "low blood sugar"
}

NON_EMERGENCY_SYMPTOMS = {
    "vomiting", "cough", "sore throat", "dysuria", "urinary frequency",
    "genital discharge", "genital sore", "dyspareunia", "joint pain",
    "migraine", "abdominal pain", "diarrhea"
}

GU_CLUSTER = {"dysuria", "urinary frequency", "genital discharge", "genital sore", "dyspareunia"}
UTI_CLUSTER = {"dysuria", "urinary frequency"}
BENIGN_MODIFIER = -1

affirmative_answers = [
    "yes", "yeah", "yep", "yup", "correct", "absolutely", "definitely",
    "i do", "i have", "i am", "it is", "that's right", "thats right",
    "positive", "confirmed", "right", "indeed", "certainly", "sure", "always"
]

negative_answers = [
    "no", "nope", "nah", "negative", "not really", "don't", "dont",
    "i don't", "i dont", "none", "never", "not at all", "no i don't"
]

def is_affirmative(answer: str) -> bool:
    a = answer.lower().strip()
    return any(a.startswith(w) or a == w for w in affirmative_answers)

def is_negative(answer: str) -> bool:
    a = answer.lower().strip()
    return any(a.startswith(w) or a == w for w in negative_answers)

# ------------------------------
# Branching questions
# ------------------------------
HEADACHE_INITIAL = "On a scale of 1 to 10, how severe is this headache?"
HEADACHE_BRANCH_Q = "Is this the worst headache you have ever had, or did it come on suddenly like an explosion or thunderclap?"

HEADACHE_SAH_QUESTIONS = [
    "Do you have any neck stiffness or pain on bending your neck forward?",
    "Do you have sensitivity to light or does light make it worse?",
    "Do you have any fever, confusion, or feel unusually drowsy?",
    "Did the headache reach maximum intensity within seconds to a couple of minutes?",
    "Do you have any nausea or vomiting with this headache?",
    "Have you had any recent illness, infection, or been around anyone unwell?"
]

HEADACHE_MIGRAINE_QUESTIONS = [
    "Is the pain on one side of your head or both sides?",
    "Do you have any visual disturbances, flashing lights, or blind spots before the headache?",
    "Do you have nausea or sensitivity to light and sound?",
    "Have you had headaches like this before?",
    "Have you taken any pain relief and did it help?",
    "Do you have any neck stiffness or fever alongside this headache?"
]

CHEST_PAIN_INITIAL = "Can you describe the chest pain — is it sharp, dull, pressure-like, or burning?"
CHEST_BRANCH_Q = "Does the pain feel like pressure, tightness, squeezing, or a heavy weight on your chest?"

CHEST_CARDIAC_QUESTIONS = [
    "Does the pain spread or radiate to your left arm, jaw, neck, or shoulder?",
    "Do you have shortness of breath alongside the chest pain?",
    "Are you sweating, feeling clammy, or did you feel faint?",
    "Do you have palpitations or feel your heart racing or beating irregularly?",
    "Do you have a history of heart disease, angina, or a previous heart attack?",
    "When exactly did this start — was it at rest or during exertion?"
]

CHEST_NON_CARDIAC_QUESTIONS = [
    "Does the pain change when you breathe in deeply or move?",
    "Do you have a cough, fever, or feel generally unwell?",
    "Do you have any heartburn, acid reflux, or did you recently eat?",
    "Do you have any history of blood clots, recent long travel, or leg swelling?",
    "Does pressing on your chest wall reproduce the pain?",
    "Do you have any shortness of breath or difficulty breathing?"
]

SOB_QUESTIONS = [
    "Did the shortness of breath come on suddenly or gradually?",
    "Do you have any chest pain or tightness alongside this?",
    "Do you have a history of asthma, COPD, heart failure, or blood clots?",
    "Are you wheezing or making any abnormal sounds when breathing?",
    "Do you have a fever, cough, or any recent illness?",
    "Are you breathless at rest right now, or only on exertion?"
]

SEIZURE_QUESTIONS = [
    "Is this the first seizure you have ever had?",
    "How long did the seizure last?",
    "Did you lose consciousness during the seizure?",
    "Are you a known epileptic and were you taking your medications?",
    "Do you have a headache, confusion, or weakness after the seizure?",
    "Did you injure yourself during the seizure?"
]

HEAD_INJURY_QUESTIONS = [
    "Did you lose consciousness after the head injury?",
    "Do you remember the event, or do you have any memory loss around it?",
    "Do you have a headache, vomiting, or confusion now?",
    "Did you have a seizure after the injury?",
    "Is there any bleeding from the head or clear fluid from the nose or ears?",
    "Are you on any blood thinners such as warfarin or aspirin?"
]

TRAUMA_QUESTIONS = [
    "What happened — can you briefly describe the mechanism of injury?",
    "Where on your body were you injured?",
    "Did you lose consciousness at any point?",
    "Is there any active bleeding, deformity, or inability to move a limb?",
    "Do you have any neck or back pain?",
    "Can you move all your limbs and do you have normal sensation?"
]

BLACKOUT_BRANCH_Q = "Are you diabetic or do you have a history of low blood sugar?"

BLACKOUT_HYPOGLY_QUESTIONS = [
    "Have you eaten recently or taken insulin today?",
    "Do you have your glucose meter with you — what is your current reading?",
    "Do you feel shaky, sweaty, or confused right now?",
    "Have you had glucose, juice, or anything sweet since the episode?",
    "Do you have someone with you to help monitor you?"
]

BLACKOUT_CARDIAC_QUESTIONS = [
    "Did you have any warning before blacking out, such as dizziness, palpitations, or chest pain?",
    "How long were you unconscious?",
    "Did anyone witness the episode — did you shake or have any jerking movements?",
    "Do you have a known heart condition or are you on any heart medications?",
    "Did you injure yourself when you fell?",
    "Have you had episodes like this before?"
]

RECTAL_BLEED_QUESTIONS = [
    "How much blood did you notice — a small amount or a large amount?",
    "What colour was the blood — bright red, dark red, or black and tarry?",
    "Do you have any abdominal or rectal pain?",
    "Do you feel dizzy, weak, or lightheaded?",
    "Do you have a history of haemorrhoids, inflammatory bowel disease, or bowel cancer?",
    "Have you had any recent changes in bowel habit, unintentional weight loss, or night sweats?"
]

SUICIDE_QUESTIONS = [
    "I want to make sure you are safe right now. Are you currently having thoughts of ending your life?",
    "Do you have a specific plan in mind for how you would do this?",
    "Have you already done anything to hurt yourself today?",
    "Are you alone right now, or is there someone with you?",
    "Is there anyone — a family member, friend, or anyone — we can contact to be with you right now?"
]

OVERDOSE_QUESTIONS = [
    "What substance or medication was taken, and approximately how much?",
    "How long ago was it taken?",
    "Is the person conscious, breathing normally, and responsive?",
    "Was this intentional or accidental?",
    "Are there any other symptoms such as seizures, confusion, or difficulty breathing?",
    "Is there a packet or bottle nearby that we can identify the substance from?"
]

DIARRHEA_QUESTIONS = [
    "How long have you had the diarrhea?",
    "How many times have you had loose stools today?",
    "Is there any blood or mucus in the stool?",
    "Do you have a fever, vomiting, or abdominal cramps?",
    "Are you able to keep fluids down?",
    "Have you recently travelled abroad or eaten anything that others also ate?"
]

COUGH_QUESTIONS = [
    "How long have you had this cough?",
    "Is it a dry cough or are you coughing up phlegm — and if so, what colour?",
    "Have you coughed up any blood?",
    "Do you have shortness of breath, fever, or chest pain?",
    "Do you have a history of asthma, COPD, or smoking?"
]

SORE_THROAT_QUESTIONS = [
    "How long have you had the sore throat?",
    "Do you have difficulty swallowing or is your airway feeling blocked?",
    "Do you have a fever, swollen glands in your neck, or white patches on your tonsils?",
    "Do you have a rash anywhere on your body?",
    "Have you been in contact with anyone with strep throat or similar illness?"
]

DYSURIA_INITIAL = "Where exactly do you feel the burning or pain — inside when urinating, at the opening, or deeper in the pelvis or lower back?"
DYSURIA_BRANCH_Q = "Do you also have increased frequency or urgency to urinate, or lower abdominal discomfort?"

DYSURIA_UTI_QUESTIONS = [
    "Do you have any fever, chills, or pain in your back or side (flank pain)?",
    "Is your urine cloudy, dark, or does it have an unusual smell?",
    "Have you had a UTI before, and if so how recently?",
    "Are you sexually active, and could this be related to recent sexual activity?",
    "Do you have any blood in your urine?"
]

DYSURIA_STI_QUESTIONS = [
    "Do you have any unusual discharge from the genitals?",
    "Do you have any sores, ulcers, or blisters on or around the genitals?",
    "Do you have any pain or discomfort during or after sexual intercourse?",
    "When did you last have unprotected sexual contact?",
    "Have you been tested for sexually transmitted infections before?"
]

GENITAL_DISCHARGE_QUESTIONS = [
    "How long have you noticed the discharge?",
    "Can you describe the discharge — colour, consistency, and any odour?",
    "Do you have any pain, burning, or itching alongside the discharge?",
    "Do you have any sores, ulcers, or blisters in the genital area?",
    "Do you have any pain during urination or sexual intercourse?",
    "When did you last have unprotected sexual contact?"
]

GENITAL_SORE_QUESTIONS = [
    "Can you describe the sore — is it painful, painless, a blister, or an ulcer?",
    "How long have you had it and has it changed in appearance?",
    "Do you have any discharge, burning on urination, or other genital symptoms?",
    "Do you have any swollen lymph nodes in your groin?",
    "When did you last have unprotected sexual contact?",
    "Have you ever been diagnosed with herpes, syphilis, or any STI before?"
]

DYSPAREUNIA_QUESTIONS = [
    "Is the pain during intercourse, after intercourse, or both?",
    "Where do you feel the pain — superficial at the entry, or deep inside?",
    "Do you have any unusual discharge, bleeding, or other genital symptoms?",
    "Do you have any pelvic pain outside of intercourse?",
    "Have you noticed any changes with your menstrual cycle if applicable?"
]

JOINT_PAIN_QUESTIONS = [
    "Which joints are affected — one joint or multiple?",
    "Is there any swelling, redness, or warmth around the affected joint?",
    "Did the pain start after an injury or come on by itself?",
    "Is the pain worse in the morning and improves with movement, or worse with activity?",
    "Do you have a fever or feel generally unwell?",
    "Do you have a history of gout, rheumatoid arthritis, or any joint condition?"
]

MIGRAINE_QUESTIONS = [
    "How long have you had this migraine?",
    "Do you have any visual aura — flashing lights, zigzag lines, or blind spots — before it starts?",
    "Is the pain on one side or both sides of your head?",
    "Do you have nausea, vomiting, or sensitivity to light and sound?",
    "Have you taken your usual migraine medication and did it help?",
    "Is this migraine typical for you, or does anything feel different this time?"
]

ABDOMINAL_PAIN_QUESTIONS = [
    "Where exactly in your abdomen is the pain — upper, lower, left, right, or all over?",
    "On a scale of 1 to 10, how severe is the pain?",
    "Did the pain come on suddenly or gradually?",
    "Do you have nausea, vomiting, or diarrhea alongside this?",
    "Do you have a fever?",
    "For those who menstruate — is there any chance this could be related to your cycle or pregnancy?"
]

VOMITING_QUESTIONS = [
    "How many times have you vomited and over what period of time?",
    "Is there any blood in the vomit?",
    "Do you have abdominal pain, fever, or diarrhea?",
    "Are you able to keep any fluids down at all?",
    "Could this be related to something you ate, a medication, or alcohol?"
]

LOW_BLOOD_SUGAR_QUESTIONS = [
    "What is your current blood glucose reading if you have a meter?",
    "Have you eaten or drunk anything sweet since the episode started?",
    "Are you shaking, sweating, confused, or feeling faint right now?",
    "Did you take insulin or oral diabetes medication today and at what dose?",
    "Are you alone or is there someone with you?"
]

QUESTION_MAP = {
    "headache_sah": HEADACHE_SAH_QUESTIONS,
    "headache_migraine": HEADACHE_MIGRAINE_QUESTIONS,
    "chest pain_cardiac": CHEST_CARDIAC_QUESTIONS,
    "chest pain_non_cardiac": CHEST_NON_CARDIAC_QUESTIONS,
    "shortness of breath": SOB_QUESTIONS,
    "seizure": SEIZURE_QUESTIONS,
    "head injury": HEAD_INJURY_QUESTIONS,
    "trauma": TRAUMA_QUESTIONS,
    "blackout_hypogly": BLACKOUT_HYPOGLY_QUESTIONS,
    "blackout_cardiac": BLACKOUT_CARDIAC_QUESTIONS,
    "rectal bleed": RECTAL_BLEED_QUESTIONS,
    "suicidal thoughts": SUICIDE_QUESTIONS,
    "overdose": OVERDOSE_QUESTIONS,
    "diarrhea": DIARRHEA_QUESTIONS,
    "cough": COUGH_QUESTIONS,
    "sore throat": SORE_THROAT_QUESTIONS,
    "dysuria_uti": DYSURIA_UTI_QUESTIONS,
    "dysuria_sti": DYSURIA_STI_QUESTIONS,
    "genital discharge": GENITAL_DISCHARGE_QUESTIONS,
    "genital sore": GENITAL_SORE_QUESTIONS,
    "dyspareunia": DYSPAREUNIA_QUESTIONS,
    "joint pain": JOINT_PAIN_QUESTIONS,
    "migraine": MIGRAINE_QUESTIONS,
    "abdominal pain": ABDOMINAL_PAIN_QUESTIONS,
    "vomiting": VOMITING_QUESTIONS,
    "low blood sugar": LOW_BLOOD_SUGAR_QUESTIONS,
}

# ------------------------------
# Red flag rules
# ------------------------------
red_flag_rules = {
    "headache_sah": {
        "threshold": 2,
        "triggers": [
            (3, ["worst headache", "thunderclap", "sudden severe", "explosive"]),
            (2, ["neck stiffness", "stiff neck", "cannot bend neck"]),
            (2, ["sensitivity to light", "photophobia", "light hurts"]),
            (2, ["confusion", "confused", "drowsy", "altered"]),
            (2, ["fever", "high temperature"]),
            (1, ["vomiting", "nausea"]),
        ]
    },
    "headache_migraine": {
        "threshold": 3,
        "triggers": [
            (2, ["neck stiffness", "stiff neck", "fever"]),
            (1, ["first time", "never had this before", "unusual for me"]),
        ]
    },
    "chest pain_cardiac": {
        "threshold": 2,
        "triggers": [
            (3, ["heart attack", "cardiac arrest"]),
            (2, ["radiating to arm", "left arm", "jaw pain", "radiating to jaw"]),
            (2, ["shortness of breath", "can't breathe", "difficulty breathing"]),
            (2, ["sweating", "cold sweat", "clammy"]),
            (2, ["fainted", "syncope", "passed out"]),
            (1, ["crushing", "pressure", "squeezing", "heavy"]),
            (1, ["palpitations", "heart racing", "irregular"]),
        ]
    },
    "chest pain_non_cardiac": {
        "threshold": 3,
        "triggers": [
            (2, ["blood clot", "dvt", "pe", "pulmonary embolism"]),
            (2, ["cannot breathe", "severe shortness of breath"]),
            (1, ["fever", "cough", "pleuritic"]),
        ]
    },
    "shortness of breath": {
        "threshold": 2,
        "triggers": [
            (3, ["cannot breathe at all", "turning blue", "lips blue", "cyanosis"]),
            (2, ["chest pain", "chest tightness"]),
            (2, ["sudden onset", "came on suddenly"]),
            (2, ["blood clot", "pe", "pulmonary embolism"]),
            (1, ["worsening", "getting worse", "severe"]),
        ]
    },
    "seizure": {
        "threshold": 2,
        "triggers": [
            (3, ["multiple seizures", "not waking up", "status epilepticus"]),
            (2, ["first seizure", "never had one before"]),
            (2, ["not taking medication", "missed medication"]),
            (1, ["confusion", "headache after", "weakness"]),
        ]
    },
    "head injury": {
        "threshold": 2,
        "triggers": [
            (3, ["not waking up", "unconscious", "unresponsive"]),
            (2, ["lost consciousness", "blacked out"]),
            (2, ["memory loss", "cannot remember", "amnesia"]),
            (2, ["seizure after", "fitting after"]),
            (2, ["blood thinners", "warfarin", "anticoagulant"]),
            (1, ["vomiting", "severe headache after", "confusion"]),
        ]
    },
    "trauma": {
        "threshold": 2,
        "triggers": [
            (3, ["not breathing", "unconscious", "unresponsive"]),
            (2, ["heavy bleeding", "bleeding heavily", "cannot stop bleeding"]),
            (2, ["neck injury", "spine injury", "cannot move legs"]),
            (2, ["lost consciousness"]),
            (1, ["severe pain", "deformity", "bone visible"]),
        ]
    },
    "blackout_hypogly": {
        "threshold": 1,
        "triggers": [
            (3, ["unconscious", "not waking up", "unresponsive"]),
            (2, ["very low reading", "glucose below 3", "sugar is 2", "sugar is 1"]),
            (2, ["seizure", "fitting"]),
            (1, ["shaking", "sweating", "confused", "aggressive"]),
        ]
    },
    "blackout_cardiac": {
        "threshold": 2,
        "triggers": [
            (3, ["still unconscious", "not waking up"]),
            (2, ["heart condition", "pacemaker", "cardiac"]),
            (2, ["prolonged", "more than a minute", "several minutes"]),
            (2, ["chest pain before", "palpitations before"]),
            (1, ["no warning", "without warning", "sudden"]),
        ]
    },
    "rectal bleed": {
        "threshold": 2,
        "triggers": [
            (3, ["large amount", "soaking", "heavy bleeding", "blood pouring"]),
            (2, ["black stool", "tarry stool", "dark blood", "malaena"]),
            (2, ["dizzy", "lightheaded", "faint", "weak"]),
            (2, ["abdominal pain", "severe cramping"]),
            (1, ["bright red", "small amount"]),
        ]
    },
    "suicidal thoughts": {
        "threshold": 1,
        "triggers": [
            (3, ["have a plan", "planning to", "going to do it", "tonight", "today"]),
            (3, ["already done", "took something", "hurt myself already"]),
            (2, ["alone", "no one with me"]),
            (2, ["hopeless", "no point", "no reason"]),
            (1, ["thinking about it", "thoughts of"]),
        ]
    },
    "overdose": {
        "threshold": 1,
        "triggers": [
            (3, ["unconscious", "not breathing", "unresponsive", "turning blue"]),
            (3, ["overdose confirmed", "took too many", "took too much"]),
            (2, ["seizure", "fitting", "confusion", "slurring"]),
            (2, ["intentional", "on purpose", "wanted to"]),
            (1, ["drowsy", "nausea", "vomiting"]),
        ]
    },
    "diarrhea": {
        "threshold": 2,
        "triggers": [
            (3, ["blood in stool", "bloody diarrhea", "blood and mucus"]),
            (2, ["severe dehydration", "cannot keep fluids", "very weak"]),
            (2, ["high fever", "temperature above 39", "rigors"]),
            (1, ["more than 48 hours", "persistent", "severe cramping"]),
        ]
    },
    "other": {
        "threshold": 2,
        "triggers": [
            (3, ["unconscious", "not breathing", "cardiac arrest"]),
            (2, ["coughing blood", "vomiting blood", "bleeding heavily"]),
            (1, ["severe pain", "excruciating"]),
        ]
    }
}

for sym in ["cough", "sore throat", "dysuria_uti", "dysuria_sti",
            "genital discharge", "genital sore", "dyspareunia",
            "joint pain", "migraine", "abdominal pain", "vomiting", "low blood sugar"]:
    if sym not in red_flag_rules:
        red_flag_rules[sym] = {
            "threshold": 3,
            "triggers": [
                (2, ["severe", "worsening", "cannot cope", "unbearable"]),
                (1, ["fever", "blood", "vomiting"]),
            ]
        }

red_flag_messages = {
    "headache_sah": "🚨 RED FLAG: Your symptoms may indicate a serious neurological emergency such as a subarachnoid haemorrhage or meningitis. Please call 999/112 or go to your nearest emergency department immediately.",
    "headache_migraine": "⚠️ ATTENTION: While this may be a migraine, some features warrant same-day medical review. Please contact your GP or urgent care today.",
    "chest pain_cardiac": "🚨 RED FLAG: Your symptoms are consistent with a possible cardiac event such as a heart attack. Please call 999/112 immediately. Do not drive yourself.",
    "chest pain_non_cardiac": "⚠️ ATTENTION: Your chest pain requires prompt assessment. Please seek medical attention today.",
    "shortness of breath": "🚨 RED FLAG: Severe breathing difficulty can be life-threatening. Please call 999/112 or go to your nearest emergency department immediately.",
    "seizure": "🚨 RED FLAG: A seizure — especially a first seizure or prolonged seizure — requires urgent evaluation. Please go to your nearest emergency department.",
    "head injury": "🚨 RED FLAG: Your head injury requires urgent assessment for possible concussion or intracranial injury. Please go to your nearest emergency department.",
    "trauma": "🚨 RED FLAG: Based on your description, this injury requires immediate emergency attention. Please call 999/112.",
    "blackout_hypogly": "🚨 RED FLAG: A hypoglycaemic episode requires immediate treatment. If you cannot take glucose by mouth, call 999/112 now.",
    "blackout_cardiac": "🚨 RED FLAG: Loss of consciousness may indicate a serious cardiac or neurological cause. Please go to your nearest emergency department immediately.",
    "rectal bleed": "🚨 RED FLAG: Significant rectal bleeding requires urgent assessment. Please go to your nearest emergency department immediately.",
    "suicidal thoughts": "🚨 URGENT: You are not alone and help is here. Please call 999/112 now, or contact the Samaritans on 116 123 (free, 24/7). A clinician wants to support you through this.",
    "overdose": "🚨 RED FLAG: This is a medical emergency. Please call 999/112 immediately. Do not wait for symptoms to worsen.",
    "diarrhea": "⚠️ ATTENTION: Your symptoms suggest possible serious infection or dehydration. Please seek medical attention today.",
    "other": "🚨 RED FLAG: Based on your symptoms, please seek emergency care immediately or call 999/112."
}

completion_messages = {
    "high": "🚨 URGENT: Based on everything you have described, your symptoms require immediate emergency attention. Please call 999/112 or go to your nearest emergency department NOW. Do not wait.",
    "medium": "⚠️ ATTENTION: Based on your symptoms, we recommend you seek medical attention today. Please contact your GP urgently or go to an urgent care centre.",
    "low": "✅ Thank you for the information. Your responses have been recorded. Please contact your GP or a healthcare professional for further assessment."
}

# ------------------------------
# Differential Diagnosis Engine
# Max 3 differentials, ranked by likelihood based on answers
# Each entry: (diagnosis, keywords_that_support_it, weight)
# ------------------------------
DIFFERENTIAL_CANDIDATES = {
    "headache_sah": [
        ("Subarachnoid Haemorrhage (SAH)", ["worst headache", "thunderclap", "sudden", "explosive", "10 out of 10"], 3),
        ("Meningitis / Meningoencephalitis", ["neck stiffness", "fever", "photophobia", "confusion", "rash"], 3),
        ("Hypertensive Emergency", ["severe headache", "history of hypertension", "high blood pressure"], 2),
        ("Migraine", ["nausea", "light sensitivity", "previous headaches"], 1),
        ("COVID-19", ["fever", "recent illness", "around someone unwell"], 1),
    ],
    "headache_migraine": [
        ("Migraine with or without Aura", ["one side", "aura", "flashing lights", "nausea", "light sensitivity", "previous"], 3),
        ("Tension-Type Headache", ["both sides", "stress", "no aura", "dull", "pressure"], 2),
        ("COVID-19", ["fever", "recent illness", "around someone unwell", "loss of smell"], 2),
        ("Cluster Headache", ["one eye", "tearing", "one sided", "severe"], 2),
        ("Medication Overuse Headache", ["took medication", "regular painkillers"], 1),
    ],
    "chest pain_cardiac": [
        ("Acute Myocardial Infarction (MI)", ["pressure", "radiating", "left arm", "jaw", "sweating", "history of heart"], 3),
        ("Unstable Angina", ["exertion", "history of angina", "relieved by rest"], 2),
        ("Pulmonary Embolism (PE)", ["sudden", "shortness of breath", "blood clot", "leg swelling"], 2),
        ("COVID-19 Myocarditis", ["recent covid", "recent illness", "fever", "palpitations"], 1),
        ("Aortic Dissection", ["tearing", "ripping", "radiating to back", "severe"], 1),
    ],
    "chest pain_non_cardiac": [
        ("Musculoskeletal / Costochondritis", ["sharp", "worse on movement", "reproducible on pressing", "after injury"], 3),
        ("Gastro-Oesophageal Reflux (GORD)", ["burning", "after eating", "acid", "heartburn"], 2),
        ("COVID-19", ["cough", "fever", "recent illness", "breathless"], 2),
        ("Pleuritis / Pleurisy", ["worse on breathing", "cough", "fever"], 2),
        ("Pulmonary Embolism (PE)", ["blood clot", "leg swelling", "recent travel", "sudden"], 2),
    ],
    "shortness of breath": [
        ("COVID-19", ["fever", "cough", "recent illness", "loss of smell", "fatigue"], 3),
        ("Asthma Exacerbation", ["wheeze", "history of asthma", "trigger", "tightness"], 3),
        ("Pulmonary Embolism (PE)", ["sudden", "blood clot", "leg swelling", "pleuritic pain"], 2),
        ("Pneumonia", ["fever", "cough", "productive", "unwell"], 2),
        ("Heart Failure", ["gradual", "history of heart", "leg swelling", "orthopnoea"], 1),
    ],
    "seizure": [
        ("Epilepsy (Known or New Onset)", ["first seizure", "history of epilepsy", "tonic clonic"], 3),
        ("Hypoglycaemia-Induced Seizure", ["diabetic", "low sugar", "missed meal", "insulin"], 2),
        ("Meningitis / Encephalitis", ["fever", "neck stiffness", "headache", "confusion"], 2),
        ("Alcohol Withdrawal Seizure", ["alcohol", "stopped drinking", "withdrawal"], 1),
        ("Intracranial Mass", ["headache", "weakness", "vision changes", "gradual onset"], 1),
    ],
    "head injury": [
        ("Concussion", ["brief loss of consciousness", "memory loss", "headache", "dizziness"], 3),
        ("Extradural Haematoma", ["loss of consciousness", "lucid interval", "then deterioration"], 2),
        ("Subdural Haematoma", ["blood thinners", "elderly", "warfarin", "gradual"], 2),
        ("Skull Fracture", ["high impact", "clear fluid from ears or nose", "bruising"], 1),
        ("Cerebral Contusion", ["severe impact", "prolonged unconsciousness", "focal deficit"], 1),
    ],
    "trauma": [
        ("Fracture", ["deformity", "severe pain", "unable to move", "swelling"], 3),
        ("Internal Haemorrhage", ["abdominal trauma", "pale", "collapse", "hypotension"], 2),
        ("Spinal Cord Injury", ["neck pain", "back pain", "numbness", "weakness in legs"], 2),
        ("Pneumothorax", ["chest trauma", "shortness of breath", "chest pain"], 1),
        ("Soft Tissue Injury", ["bruising", "swelling", "able to move", "mild pain"], 1),
    ],
    "blackout_hypogly": [
        ("Hypoglycaemia", ["diabetic", "insulin", "low reading", "shaking", "sweating"], 3),
        ("Insulin Overdose", ["took insulin", "too much insulin", "missed meal"], 2),
        ("Adrenal Insufficiency", ["fatigue", "weight loss", "no history of diabetes"], 1),
    ],
    "blackout_cardiac": [
        ("Vasovagal Syncope", ["trigger", "standing", "pain", "heat", "warning", "brief"], 3),
        ("Cardiac Arrhythmia", ["palpitations before", "heart condition", "no warning", "irregular"], 2),
        ("Orthostatic Hypotension", ["standing up", "dehydration", "medication", "elderly"], 2),
        ("Epileptic Seizure", ["jerking", "tongue biting", "prolonged", "post-ictal confusion"], 1),
        ("Pulmonary Embolism", ["chest pain", "shortness of breath", "leg swelling"], 1),
    ],
    "rectal bleed": [
        ("Haemorrhoids", ["bright red", "after straining", "small amount", "no pain"], 3),
        ("Colorectal Cancer", ["change in bowel habit", "weight loss", "dark blood", "night sweats"], 2),
        ("Inflammatory Bowel Disease", ["mucus", "cramping", "history of IBD", "young patient"], 2),
        ("Upper GI Bleed", ["black tarry stool", "malaena", "vomiting blood", "dark blood"], 2),
        ("Anal Fissure", ["bright red", "painful", "constipation", "tearing sensation"], 1),
    ],
    "suicidal thoughts": [
        ("Major Depressive Disorder", ["low mood", "hopeless", "no energy", "not eating"], 3),
        ("Bipolar Disorder", ["mood swings", "periods of high energy", "depression"], 2),
        ("PTSD", ["trauma", "flashbacks", "nightmares", "anxiety"], 2),
        ("Borderline Personality Disorder", ["impulsive", "unstable relationships", "self harm"], 1),
        ("Acute Situational Crisis", ["recent loss", "bereavement", "job loss", "relationship"], 1),
    ],
    "overdose": [
        ("Paracetamol Overdose", ["paracetamol", "panadol", "acetaminophen", "tablets"], 3),
        ("Opioid Overdose", ["heroin", "morphine", "codeine", "oxycodone", "slow breathing", "pinpoint pupils"], 3),
        ("Benzodiazepine Overdose", ["diazepam", "valium", "xanax", "drowsy", "slurred"], 2),
        ("Alcohol Poisoning", ["alcohol", "drunk", "vodka", "wine", "spirits"], 2),
        ("Tricyclic Antidepressant Overdose", ["amitriptyline", "antidepressant", "irregular heart"], 1),
    ],
    "diarrhea": [
        ("Viral Gastroenteritis", ["sudden onset", "vomiting", "no travel", "others affected", "norovirus"], 3),
        ("COVID-19", ["fever", "cough", "recent illness", "loss of smell", "contact"], 2),
        ("Bacterial Gastroenteritis", ["travel", "food poisoning", "blood in stool", "high fever"], 2),
        ("C. difficile", ["recent antibiotics", "hospital admission", "watery", "offensive smell"], 2),
        ("Inflammatory Bowel Disease", ["blood and mucus", "cramping", "young", "recurrent"], 1),
    ],
    "cough": [
        ("COVID-19", ["dry cough", "fever", "loss of smell", "fatigue", "recent contact"], 3),
        ("Upper Respiratory Tract Infection", ["runny nose", "sore throat", "mild fever", "short duration"], 3),
        ("Asthma", ["wheeze", "history of asthma", "worse at night", "triggers"], 2),
        ("Pneumonia", ["productive cough", "fever", "shortness of breath", "unwell"], 2),
        ("Lung Cancer", ["smoker", "haemoptysis", "weight loss", "chronic cough", "elderly"], 1),
    ],
    "sore throat": [
        ("Viral Pharyngitis", ["mild", "runny nose", "cough", "no exudate", "short duration"], 3),
        ("COVID-19", ["fever", "loss of smell", "fatigue", "contact", "recent"], 3),
        ("Streptococcal Pharyngitis", ["white exudate", "high fever", "swollen glands", "no cough"], 2),
        ("Infectious Mononucleosis", ["young", "fatigue", "splenomegaly", "generalised lymphadenopathy"], 2),
        ("Peritonsillar Abscess", ["asymmetric swelling", "hot potato voice", "trismus", "drooling"], 1),
    ],
    "dysuria_uti": [
        ("Urinary Tract Infection / Cystitis", ["frequency", "urgency", "cloudy urine", "suprapubic pain"], 3),
        ("Pyelonephritis", ["flank pain", "fever", "rigors", "back pain", "unwell"], 2),
        ("STI / Urethritis", ["discharge", "sexual contact", "sores", "no frequency"], 2),
    ],
    "dysuria_sti": [
        ("Chlamydia", ["discharge", "unprotected sex", "painless", "young"], 3),
        ("Gonorrhoea", ["purulent discharge", "unprotected sex", "dysuria", "yellow green"], 2),
        ("Herpes Simplex (HSV)", ["blisters", "painful sores", "ulcers", "burning"], 2),
    ],
    "genital discharge": [
        ("Chlamydia", ["unprotected sex", "painless", "clear discharge", "young"], 3),
        ("Bacterial Vaginosis", ["fishy odour", "grey white discharge", "not painful"], 2),
        ("Gonorrhoea", ["yellow green", "purulent", "dysuria", "unprotected sex"], 2),
        ("Candidiasis", ["thick white", "itching", "no odour", "curdy"], 1),
        ("Trichomonas", ["frothy", "yellow green", "offensive smell", "itching"], 1),
    ],
    "genital sore": [
        ("Herpes Simplex (HSV)", ["painful blisters", "ulcers", "recurrent", "burning"], 3),
        ("Syphilis (Primary)", ["painless ulcer", "hard", "single sore", "groin lymph nodes"], 2),
        ("Chancroid", ["painful ulcer", "soft", "irregular edges", "tropical"], 1),
    ],
    "dyspareunia": [
        ("Vaginismus / Pelvic Floor Dysfunction", ["superficial", "entry pain", "tightness", "anxiety"], 3),
        ("Endometriosis", ["deep pain", "cyclical", "period pain", "deep dyspareunia"], 2),
        ("Pelvic Inflammatory Disease (PID)", ["discharge", "fever", "bilateral pelvic pain", "unprotected sex"], 2),
        ("Atrophic Vaginitis", ["menopause", "dryness", "post-menopausal", "burning"], 1),
        ("STI", ["discharge", "sores", "unprotected sex"], 1),
    ],
    "joint pain": [
        ("Osteoarthritis", ["older age", "worse with activity", "no fever", "large joints"], 3),
        ("Rheumatoid Arthritis", ["morning stiffness", "multiple joints", "symmetrical", "improves with movement"], 2),
        ("Gout", ["sudden onset", "big toe", "red", "hot", "swollen", "alcohol", "meat"], 2),
        ("Reactive Arthritis / COVID-19 Arthralgia", ["recent infection", "recent covid", "fever", "multiple joints"], 2),
        ("Septic Arthritis", ["fever", "single hot swollen joint", "unwell", "elevated temperature"], 1),
    ],
    "migraine": [
        ("Migraine with Aura", ["aura", "flashing lights", "visual", "one sided", "nausea"], 3),
        ("Migraine without Aura", ["one sided", "throbbing", "nausea", "light sensitivity", "no aura"], 3),
        ("COVID-19", ["fever", "fatigue", "loss of smell", "recent contact"], 1),
    ],
    "abdominal pain": [
        ("Appendicitis", ["right lower quadrant", "fever", "nausea", "worse on movement", "rebound"], 3),
        ("Gastroenteritis", ["diarrhea", "vomiting", "fever", "crampy", "others affected"], 2),
        ("Ectopic Pregnancy", ["lower abdominal", "missed period", "shoulder tip pain", "collapse"], 2),
        ("Peptic Ulcer / Gastritis", ["upper abdominal", "burning", "after eating", "history of ulcer"], 2),
        ("Bowel Obstruction", ["distension", "vomiting", "constipation", "colicky"], 1),
    ],
    "vomiting": [
        ("Gastroenteritis", ["diarrhea", "fever", "cramping", "others affected", "food"], 3),
        ("COVID-19", ["fever", "cough", "loss of smell", "recent contact"], 2),
        ("Gastroparesis / Food Poisoning", ["after eating", "specific food", "nausea first"], 2),
        ("Raised Intracranial Pressure", ["headache", "projectile", "no nausea before", "drowsy"], 1),
        ("Medication Side Effect", ["new medication", "started recently", "no other symptoms"], 1),
    ],
    "low blood sugar": [
        ("Hypoglycaemia", ["diabetic", "insulin", "missed meal", "low reading", "shaking"], 3),
        ("Insulinoma", ["recurrent", "non-diabetic", "fasting hypoglycaemia"], 1),
        ("Adrenal Insufficiency", ["fatigue", "weight loss", "dizziness", "non-diabetic"], 1),
    ],
}

def generate_differentials(pathway: str, all_answers: List[AnswerEntry]) -> List[str]:
    """
    Score each candidate differential based on keywords found in all answers.
    Return top 3 ranked by score, minimum score of 1 to be included.
    """
    candidates = DIFFERENTIAL_CANDIDATES.get(pathway, [])
    if not candidates:
        return []

    combined_text = " ".join(entry.answer.lower() for entry in all_answers)
    scored = []

    for diagnosis, keywords, base_weight in candidates:
        score = 0
        for kw in keywords:
            if kw in combined_text:
                score += base_weight
        scored.append((diagnosis, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Return top 3 with score > 0, otherwise return top 3 by base order
    top = [d for d, s in scored if s > 0][:3]
    if not top:
        top = [candidates[0][0], candidates[1][0] if len(candidates) > 1 else None,
               candidates[2][0] if len(candidates) > 2 else None]
        top = [t for t in top if t][:3]

    return top

# ------------------------------
# Priority order
# ------------------------------
SYMPTOM_PRIORITY = [
    "suicidal thoughts", "overdose", "chest pain", "shortness of breath",
    "headache", "seizure", "head injury", "trauma", "blackout",
    "rectal bleed", "low blood sugar", "diarrhea", "abdominal pain",
    "vomiting", "migraine", "dysuria", "urinary frequency",
    "genital discharge", "genital sore", "dyspareunia",
    "cough", "sore throat", "joint pain", "other"
]

def detect_all_symptoms(text: str) -> List[str]:
    text_lower = text.lower()
    found = []
    for symptom, keywords in SYMPTOM_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(symptom)
    return found

def prioritize_symptoms(symptoms: List[str]) -> List[str]:
    def priority_key(s):
        try:
            return SYMPTOM_PRIORITY.index(s)
        except ValueError:
            return len(SYMPTOM_PRIORITY)
    return sorted(symptoms, key=priority_key)

def get_next_symptom_to_triage(detected: List[str], triaged: List[str]) -> Optional[str]:
    for s in prioritize_symptoms(detected):
        if s not in triaged:
            return s
    return None

def resolve_pathway(symptom_key: str, current_pathway: Optional[str]) -> str:
    if current_pathway:
        return current_pathway
    defaults = {
        "headache": "headache_sah",
        "chest pain": "chest pain_cardiac",
        "blackout": "blackout_cardiac",
        "dysuria": "dysuria_uti",
    }
    return defaults.get(symptom_key, symptom_key)

def determine_branch(symptom_key: str, answer: str, question: str) -> Optional[str]:
    answer_lower = answer.lower()
    if symptom_key == "headache" and HEADACHE_BRANCH_Q in question:
        if is_affirmative(answer) or any(w in answer_lower for w in [
            "worst", "thunderclap", "sudden", "explosion", "never had", "10", "worst ever"
        ]):
            return "headache_sah"
        else:
            return "headache_migraine"
    if symptom_key == "chest pain" and CHEST_BRANCH_Q in question:
        if is_affirmative(answer) or any(w in answer_lower for w in [
            "pressure", "tightness", "squeezing", "heavy", "crushing", "elephant"
        ]):
            return "chest pain_cardiac"
        else:
            return "chest pain_non_cardiac"
    if symptom_key == "blackout" and BLACKOUT_BRANCH_Q in question:
        if is_affirmative(answer) or any(w in answer_lower for w in [
            "diabetic", "diabetes", "insulin", "low sugar", "hypoglycemia", "glucose"
        ]):
            return "blackout_hypogly"
        else:
            return "blackout_cardiac"
    if symptom_key == "dysuria" and DYSURIA_BRANCH_Q in question:
        if is_affirmative(answer) or any(w in answer_lower for w in [
            "frequency", "urgency", "lower abdomen", "bladder", "keep going toilet"
        ]):
            return "dysuria_uti"
        else:
            return "dysuria_sti"
    return None

def get_branch_question(symptom_key: str) -> Optional[str]:
    branch_questions = {
        "headache": HEADACHE_BRANCH_Q,
        "chest pain": CHEST_BRANCH_Q,
        "blackout": BLACKOUT_BRANCH_Q,
        "dysuria": DYSURIA_BRANCH_Q,
    }
    return branch_questions.get(symptom_key)

def get_initial_question(symptom_key: str) -> Optional[str]:
    initials = {
        "headache": HEADACHE_INITIAL,
        "chest pain": CHEST_PAIN_INITIAL,
        "dysuria": DYSURIA_INITIAL,
    }
    return initials.get(symptom_key)

def calculate_red_flag_score(all_answers: List[AnswerEntry], pathway: str) -> int:
    rules = red_flag_rules.get(pathway, red_flag_rules["other"])
    score = 0
    for entry in all_answers:
        answer_lower = entry.answer.lower()
        for weight, keywords in rules["triggers"]:
            if any(kw in answer_lower for kw in keywords):
                score += weight
                break
    return max(score, 0)

def determine_risk_level(score: int, pathway: str) -> str:
    rules = red_flag_rules.get(pathway, red_flag_rules["other"])
    threshold = rules["threshold"]
    if score >= threshold * 2:
        return "high"
    elif score >= threshold:
        return "medium"
    return "low"

def check_red_flags(all_answers: List[AnswerEntry], pathway: str) -> tuple:
    score = calculate_red_flag_score(all_answers, pathway)
    rules = red_flag_rules.get(pathway, red_flag_rules["other"])
    red_flag = score >= rules["threshold"]
    risk_level = determine_risk_level(score, pathway)
    return red_flag, risk_level

@app.get("/")
def root():
    return {"message": "Triage AI Backend Running"}

@app.post("/triage")
def triage(symptom: SymptomInput):
    detected_symptoms = list(symptom.detected_symptoms or [])
    triaged_symptoms = list(symptom.triaged_symptoms or [])
    current_pathway = symptom.current_pathway

    if not detected_symptoms:
        detected_symptoms = detect_all_symptoms(symptom.message)
        if not detected_symptoms:
            detected_symptoms = ["other"]

    if symptom.symptom_type and symptom.symptom_type in detected_symptoms:
        symptom_key = symptom.symptom_type
    else:
        symptom_key = get_next_symptom_to_triage(detected_symptoms, triaged_symptoms)
        if not symptom_key:
            symptom_key = "other"

    idx = symptom.question_index
    all_answers = list(symptom.all_answers or [])

    current_question = ""
    if idx == 1:
        initial_q = get_initial_question(symptom_key)
        current_question = initial_q if initial_q else (get_branch_question(symptom_key) or "")
    elif idx == 2 and get_initial_question(symptom_key):
        current_question = get_branch_question(symptom_key) or ""
    else:
        pathway = resolve_pathway(symptom_key, current_pathway)
        questions = QUESTION_MAP.get(pathway, QUESTION_MAP.get(symptom_key, []))
        offset = 2 if get_initial_question(symptom_key) else 1
        if get_branch_question(symptom_key):
            offset += 1
        q_idx = idx - offset
        if 0 <= q_idx - 1 < len(questions):
            current_question = questions[q_idx - 1]

    all_answers.append(AnswerEntry(question=current_question, answer=symptom.message))

    if idx == 0:
        initial_q = get_initial_question(symptom_key)
        if initial_q:
            return {
                "symptom_type": symptom_key,
                "question_index": 1,
                "phase": "triage",
                "next_question": initial_q,
                "red_flag": False,
                "red_flag_message": None,
                "risk_level": "low",
                "detected_symptoms": detected_symptoms,
                "triaged_symptoms": triaged_symptoms,
                "current_pathway": current_pathway,
                "transition_message": None,
                "differential_diagnoses": []
            }
        else:
            branch_q = get_branch_question(symptom_key)
            if branch_q:
                return {
                    "symptom_type": symptom_key,
                    "question_index": 1,
                    "phase": "triage",
                    "next_question": branch_q,
                    "red_flag": False,
                    "red_flag_message": None,
                    "risk_level": "low",
                    "detected_symptoms": detected_symptoms,
                    "triaged_symptoms": triaged_symptoms,
                    "current_pathway": current_pathway,
                    "transition_message": None,
                    "differential_diagnoses": []
                }

    if not current_pathway:
        branch_q = get_branch_question(symptom_key)
        if branch_q:
            branch_answer = None
            for entry in all_answers:
                if branch_q in entry.question or entry.question in branch_q:
                    branch_answer = entry.answer
                    break
            if branch_answer is None:
                return {
                    "symptom_type": symptom_key,
                    "question_index": idx + 1,
                    "phase": "triage",
                    "next_question": branch_q,
                    "red_flag": False,
                    "red_flag_message": None,
                    "risk_level": "low",
                    "detected_symptoms": detected_symptoms,
                    "triaged_symptoms": triaged_symptoms,
                    "current_pathway": None,
                    "transition_message": None,
                    "differential_diagnoses": []
                }
            new_pathway = determine_branch(symptom_key, branch_answer, branch_q)
            if new_pathway:
                current_pathway = new_pathway

    pathway = resolve_pathway(symptom_key, current_pathway)
    questions = QUESTION_MAP.get(pathway, [])
    if not questions:
        questions = QUESTION_MAP.get(symptom_key, [])
        pathway = symptom_key

    offset = 0
    if get_initial_question(symptom_key):
        offset += 1
    if get_branch_question(symptom_key):
        offset += 1

    pathway_q_idx = idx - offset

    red_flag, risk_level = check_red_flags(all_answers, pathway)
    red_flag_message = red_flag_messages.get(pathway) if red_flag else None

    # Generate differentials based on answers so far
    differentials = generate_differentials(pathway, all_answers)

    if red_flag and pathway in ("suicidal thoughts", "overdose") and idx <= 2:
        return {
            "symptom_type": symptom_key,
            "question_index": idx,
            "phase": "done",
            "next_question": red_flag_messages[pathway],
            "red_flag": True,
            "red_flag_message": red_flag_messages[pathway],
            "risk_level": "high",
            "detected_symptoms": detected_symptoms,
            "triaged_symptoms": triaged_symptoms,
            "current_pathway": current_pathway,
            "transition_message": None,
            "differential_diagnoses": differentials
        }

    if symptom.phase == "additional":
        message_lower = symptom.message.lower().strip()
        no_indicators = [
            "no", "nope", "nothing", "that's all", "thats all",
            "no thanks", "done", "nothing else", "no more", "all good", "that is all"
        ]
        if any(message_lower == ind or message_lower.startswith(ind) for ind in no_indicators):
            triaged_symptoms_updated = triaged_symptoms + [symptom_key]
            remaining = [s for s in detected_symptoms if s not in triaged_symptoms_updated]
            if remaining:
                next_sym = get_next_symptom_to_triage(detected_symptoms, triaged_symptoms_updated)
                if next_sym:
                    next_initial = get_initial_question(next_sym)
                    next_branch = get_branch_question(next_sym)
                    first_q = next_initial or next_branch or (QUESTION_MAP.get(next_sym, ["Tell me more about this symptom."])[0])
                    return {
                        "symptom_type": next_sym,
                        "question_index": 1,
                        "phase": "triage",
                        "next_question": first_q,
                        "red_flag": red_flag,
                        "red_flag_message": red_flag_message,
                        "risk_level": risk_level,
                        "detected_symptoms": detected_symptoms,
                        "triaged_symptoms": triaged_symptoms_updated,
                        "current_pathway": None,
                        "transition_message": f"Thank you. Now let me ask you about your {next_sym}.",
                        "differential_diagnoses": differentials
                    }
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
                "current_pathway": current_pathway,
                "transition_message": None,
                "differential_diagnoses": differentials
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
                "current_pathway": current_pathway,
                "transition_message": None,
                "differential_diagnoses": differentials
            }

    if pathway_q_idx >= len(questions):
        triaged_symptoms_updated = triaged_symptoms + [symptom_key]
        remaining = [s for s in detected_symptoms if s not in triaged_symptoms_updated]
        if remaining:
            next_sym = get_next_symptom_to_triage(detected_symptoms, triaged_symptoms_updated)
            next_initial = get_initial_question(next_sym)
            next_branch = get_branch_question(next_sym)
            first_q = next_initial or next_branch or (QUESTION_MAP.get(next_sym, ["Tell me more about this symptom."])[0])
            return {
                "symptom_type": next_sym,
                "question_index": 1,
                "phase": "triage",
                "next_question": first_q,
                "red_flag": red_flag,
                "red_flag_message": red_flag_message,
                "risk_level": risk_level,
                "detected_symptoms": detected_symptoms,
                "triaged_symptoms": triaged_symptoms_updated,
                "current_pathway": None,
                "transition_message": f"Thank you. Now let me ask you about your {next_sym}.",
                "differential_diagnoses": differentials
            }
        else:
            return {
                "symptom_type": symptom_key,
                "question_index": idx,
                "phase": "additional",
                "next_question": "Is there anything else you would like to add, or any other symptoms you would like to mention?",
                "red_flag": red_flag,
                "red_flag_message": red_flag_message,
                "risk_level": risk_level,
                "detected_symptoms": detected_symptoms,
                "triaged_symptoms": triaged_symptoms,
                "current_pathway": current_pathway,
                "transition_message": None,
                "differential_diagnoses": differentials
            }

    next_question = questions[pathway_q_idx]
    return {
        "symptom_type": symptom_key,
        "question_index": idx + 1,
        "phase": "triage",
        "next_question": next_question,
        "red_flag": red_flag,
        "red_flag_message": red_flag_message,
        "risk_level": risk_level,
        "detected_symptoms": detected_symptoms,
        "triaged_symptoms": triaged_symptoms,
        "current_pathway": current_pathway,
        "transition_message": None,
        "differential_diagnoses": differentials
    }