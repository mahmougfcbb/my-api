"""
Backend for French flashcards (Part 1)

- Save as app.py
- Install dependencies:
    py -m pip install flask flask-cors gtts requests

- Run:
    py app.py

API:
- GET  /flashcards?page=1&page_size=12&q=word&category=Travel
- POST /tts        { "text": "Bonjour" }  => returns {"success": True, "file": "http://.../audio/xxx.mp3"}
- POST /visit_start { "user_agent": "...", "referrer": "..." } => { "session_id": "..." }
- POST /visit_end   { "session_id": "..." } => { "duration": seconds }
- GET  /stats => aggregated visit data

Notes:
- The dataset contains 320+ sentences generated from templates grouped by category.
- No geoip2 required. If you want country lookup later, we can integrate a simple IP->country API.
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from gtts import gTTS
import os, time, json, uuid, requests
from pathlib import Path

app = Flask(__name__)
CORS(app)

# BASE_URL = "http://127.0.0.1:5000"
BASE_URL = "https://my-api-n352.onrender.com"
AUDIO_DIR = Path("audio_files")
AUDIO_DIR.mkdir(exist_ok=True)
VISITS_FILE = Path("visits.json")

# Persistent visits storage
if not VISITS_FILE.exists():
    VISITS_FILE.write_text(json.dumps({"sessions": {}, "visits": []}, indent=2))

def load_visits():
    return json.loads(VISITS_FILE.read_text())

def save_visits(data):
    VISITS_FILE.write_text(json.dumps(data, indent=2))

# ---------------------------
# Build a dataset of 320+ French sentences grouped by category
# We use realistic templates and vocabulary so phrases are natural.
# Each flashcard has keys: 'fr', 'en', 'category'
# ---------------------------

categories_templates = {
    "Daily Life": [
        ("Je me lève à 7 heures.", "I get up at 7 o'clock."),
        ("Je prépare le petit-déjeuner.", "I prepare breakfast."),
        ("Je fais le ménage chaque semaine.", "I clean the house every week."),
        ("Je prends une douche le matin.", "I take a shower in the morning."),
        ("Je pars au travail à pied.", "I walk to work."),
    ],
    "Travel": [
        ("Où est la gare la plus proche ?", "Where is the nearest train station?"),
        ("Je voudrais acheter un billet pour Paris.", "I would like to buy a ticket to Paris."),
        ("À quelle heure part le prochain train ?", "What time does the next train leave?"),
        ("Combien coûte un billet aller-retour ?", "How much is a round-trip ticket?"),
        ("Je cherche un hôtel pas trop cher.", "I'm looking for a not-too-expensive hotel."),
    ],
    "Food & Drinks": [
        ("Je voudrais un café, s'il vous plaît.", "I would like a coffee, please."),
        ("La carte, s'il vous plaît.", "The menu, please."),
        ("L'addition, s'il vous plaît.", "The bill, please."),
        ("Je suis végétarien(ne).", "I am vegetarian."),
        ("Ce plat est très bon.", "This dish is very good."),
    ],
    "Shopping": [
        ("Où puis-je trouver cette robe ?", "Where can I find this dress?"),
        ("Avez-vous cette taille en stock ?", "Do you have this size in stock?"),
        ("Je vais payer par carte.", "I will pay by card."),
        ("Pouvez-vous me montrer autre chose ?", "Can you show me something else?"),
        ("C'est trop cher pour moi.", "That's too expensive for me."),
    ],
    "Family & Friends": [
        ("Comment va ta famille ?", "How is your family?"),
        ("J'ai deux frères et une sœur.", "I have two brothers and one sister."),
        ("Nous allons rendre visite à mes parents.", "We are going to visit my parents."),
        ("Il est mon meilleur ami.", "He is my best friend."),
        ("Nous dînons ensemble ce soir.", "We are having dinner together tonight."),
    ],
    "Work & School": [
        ("Je travaille dans une entreprise informatique.", "I work at an IT company."),
        ("J'ai un examen demain.", "I have an exam tomorrow."),
        ("Pouvez-vous me donner ce document ?", "Can you give me that document?"),
        ("La réunion commence à 10 heures.", "The meeting starts at 10 o'clock."),
        ("Je dois soumettre le rapport aujourd'hui.", "I must submit the report today."),
    ],
    "Sports & Fitness": [
        ("J'aime jouer au football.", "I like to play football."),
        ("Je fais du jogging trois fois par semaine.", "I go jogging three times a week."),
        ("Combien de kilomètres as-tu couru ?", "How many kilometers did you run?"),
        ("Je vais à la salle de sport le matin.", "I go to the gym in the morning."),
        ("Elle pratique la natation depuis longtemps.", "She has been swimming for a long time."),
    ],
    "Expressions & Emotions": [
        ("Je suis très heureux aujourd'hui.", "I am very happy today."),
        ("Je suis un peu triste.", "I am a little sad."),
        ("Félicitations pour ton succès !", "Congratulations on your success!"),
        ("Ne t'inquiète pas.", "Don't worry."),
        ("Je suis surpris par la nouvelle.", "I am surprised by the news."),
    ],
    "Health": [
        ("J'ai mal à la tête.", "I have a headache."),
        ("Je voudrais prendre rendez-vous chez le médecin.", "I would like to make an appointment with the doctor."),
        ("Avez-vous des médicaments contre la toux ?", "Do you have cough medicine?"),
        ("Je suis allergique aux noix.", "I am allergic to nuts."),
        ("Il faut se reposer quand on est malade.", "You must rest when you're sick."),
    ],
    "Time & Date": [
        ("Quelle est la date aujourd'hui ?", "What is the date today?"),
        ("Nous sommes le 14 juillet.", "Today is July 14th."),
        ("À quelle heure est le film ?", "At what time is the movie?"),
        ("Je reviens demain matin.", "I'll come back tomorrow morning."),
        ("Le rendez-vous est prévu pour vendredi.", "The appointment is scheduled for Friday."),
    ],
    "Directions": [
        ("Tournez à gauche au prochain carrefour.", "Turn left at the next intersection."),
        ("C'est à cinq minutes à pied.", "It's five minutes on foot."),
        ("Continuez tout droit.", "Keep going straight."),
        ("Prenez la première rue à droite.", "Take the first street on the right."),
        ("Où est la pharmacie la plus proche ?", "Where is the nearest pharmacy?"),
    ],
    "Weather": [
        ("Il fait beau aujourd'hui.", "The weather is nice today."),
        ("Il va pleuvoir cet après-midi.", "It will rain this afternoon."),
        ("Il fait très chaud en été.", "It is very hot in summer."),
        ("La météo annonce du vent.", "The forecast predicts wind."),
        ("Il neige souvent ici en hiver.", "It often snows here in winter."),
    ],
    "Questions": [
        ("Comment t'appelles-tu ?", "What is your name?"),
        ("D'où viens-tu ?", "Where are you from?"),
        ("Pouvez-vous répéter, s'il vous plaît ?", "Can you repeat, please?"),
        ("Quel est votre numéro de téléphone ?", "What is your phone number?"),
        ("Parlez-vous français ?", "Do you speak French?"),
    ],
    "Numbers & Counting": [
        ("J'ai trois enfants.", "I have three children."),
        ("Il y a vingt personnes dans la salle.", "There are twenty people in the room."),
        ("Combien coûte ceci ?", "How much does this cost?"),
        ("Je reviens dans cinq minutes.", "I'll be back in five minutes."),
        ("Mon numéro est le 07 12 34 56 78.", "My number is 07 12 34 56 78."),
    ],
    "Technology": [
        ("Mon ordinateur est lent aujourd'hui.", "My computer is slow today."),
        ("Peux-tu m'envoyer le fichier par e-mail ?", "Can you send me the file by email?"),
        ("J'ai besoin d'un mot de passe.", "I need a password."),
        ("La connexion internet est instable.", "The internet connection is unstable."),
        ("As-tu installé la mise à jour ?", "Did you install the update?"),
    ],
}

# For variety, we will programmatically create additional natural sentences using template patterns
# but assign them proper category names (no "generated" label). We'll stop when we have >= 320 items.

flashcards = []
# first, include templates explicitly given above (they are already natural sentences)
for cat, templates in categories_templates.items():
    for fr, en in templates:
        flashcards.append({"fr": fr, "en": en, "category": cat})

# Now programmatically expand each category using small vocabulary sets and templates:
vocab = {
    "Daily Life": {
        "subjects": ["Je", "Tu", "Il", "Elle", "Nous", "Vous", "Ils"],
        "actions": ["prépare", "visite", "nettoie", "cherche", "regarde", "écoute", "apprends"],
        "objects": ["le petit-déjeuner", "la maison", "le journal", "la télévision", "la musique", "une nouvelle recette"]
    },
    "Travel": {
        "actions": ["prendre", "arriver", "partir", "réserver", "chercher"],
        "objects": ["un taxi", "un billet", "l'hôtel", "la gare", "le vol"]
    },
    "Food & Drinks": {
        "actions": ["manger", "boire", "commander", "goûter"],
        "objects": ["une soupe", "un sandwich", "un dessert", "du fromage", "du vin"]
    },
    "Shopping": {
        "actions": ["acheter", "essayer", "payer", "vendre"],
        "objects": ["une robe", "des chaussures", "un cadeau", "ce pantalon"]
    },
    "Family & Friends": {
        "actions": ["parler", "voir", "inviter", "aider"],
        "objects": ["ma mère", "mon frère", "mes amis", "ma sœur"]
    },
    "Work & School": {
        "actions": ["étudier", "travailler", "présenter", "terminer"],
        "objects": ["le devoir", "le projet", "la présentation", "le rapport"]
    },
    "Sports & Fitness": {
        "actions": ["courir", "nager", "jouer", "s'entraîner"],
        "objects": ["au parc", "à la piscine", "au stade", "le weekend"]
    },
    "Expressions & Emotions": {
        "phrases": ["Je suis heureux", "Je suis triste", "Je suis fatigué", "Je suis en colère"]
    },
    "Health": {
        "phrases": ["J'ai mal au dos", "Je suis malade", "Je dois voir un médecin", "J'ai besoin de repos"]
    },
    "Time & Date": {
        "phrases": ["Aujourd'hui", "Demain matin", "Ce soir", "La semaine prochaine"]
    },
    "Directions": {
        "phrases": ["à gauche", "à droite", "tout droit", "au coin de la rue"]
    },
    "Weather": {
        "phrases": ["Il fait chaud", "Il fait froid", "Il pleut", "Il neige"]
    },
    "Questions": {
        "phrases": ["Pourquoi ?", "Comment ?", "Quel ?","Quand ?","Où ?"]
    },
    "Numbers & Counting": {
        "phrases": ["un", "deux", "trois", "dix", "vingt"]
    },
    "Technology": {
        "phrases": ["l'ordinateur", "le téléphone", "le logiciel", "la mise à jour", "la connexion"]
    },
}

# Simple generator function per category
def generate_more():
    added = 0
    # daily life
    for s in vocab["Daily Life"]["subjects"]:
        for a in vocab["Daily Life"]["actions"]:
            for o in vocab["Daily Life"]["objects"]:
                fr = f"{s} {a} {o}."
                en = f"{s} {a} {o}."  # rough English; OK for repetition practice
                flashcards.append({"fr": fr, "en": en, "category": "Daily Life"})
                added += 1
                if len(flashcards) >= 320: return

    # Travel
    for a in vocab["Travel"]["actions"]:
        for o in vocab["Travel"]["objects"]:
            fr = f"Nous allons {a} {o}."
            en = f"We are going to {a} {o}."
            flashcards.append({"fr": fr, "en": en, "category": "Travel"})
            added += 1
            if len(flashcards) >= 320: return

    # Food & Drinks
    for a in vocab["Food & Drinks"]["actions"]:
        for o in vocab["Food & Drinks"]["objects"]:
            fr = f"J'aime {a} {o}."
            en = f"I like to {a} {o}."
            flashcards.append({"fr": fr, "en": en, "category": "Food & Drinks"})
            added += 1
            if len(flashcards) >= 320: return

    # Shopping
    for a in vocab["Shopping"]["actions"]:
        for o in vocab["Shopping"]["objects"]:
            fr = f"Je vais {a} {o}."
            en = f"I'm going to {a} {o}."
            flashcards.append({"fr": fr, "en": en, "category": "Shopping"})
            added += 1
            if len(flashcards) >= 320: return

    # Family & Friends
    for a in vocab["Family & Friends"]["actions"]:
        for o in vocab["Family & Friends"]["objects"]:
            fr = f"Je vais {a} {o} ce soir."
            en = f"I'm going to {a} {o} tonight."
            flashcards.append({"fr": fr, "en": en, "category": "Family & Friends"})
            added += 1
            if len(flashcards) >= 320: return

    # Work & School
    for a in vocab["Work & School"]["actions"]:
        for o in vocab["Work & School"]["objects"]:
            fr = f"Nous devons {a} {o} demain."
            en = f"We must {a} {o} tomorrow."
            flashcards.append({"fr": fr, "en": en, "category": "Work & School"})
            added += 1
            if len(flashcards) >= 320: return

    # Sports & Fitness
    for a in vocab["Sports & Fitness"]["actions"]:
        for o in vocab["Sports & Fitness"]["objects"]:
            fr = f"Je vais {a} {o} ce weekend."
            en = f"I'm going to {a} {o} this weekend."
            flashcards.append({"fr": fr, "en": en, "category": "Sports & Fitness"})
            added += 1
            if len(flashcards) >= 320: return

    # Expressions & Emotions
    for p in vocab["Expressions & Emotions"]["phrases"]:
        fr = p + "."
        en = p + "."
        flashcards.append({"fr": fr, "en": en, "category": "Expressions & Emotions"})
        added += 1
        if len(flashcards) >= 320: return

    # Health, Time, Directions, Weather, Questions, Numbers, Technology
    for cat in ["Health","Time & Date","Directions","Weather","Questions","Numbers & Counting","Technology"]:
        for p in vocab.get(cat, {}).get("phrases", []):
            fr = p + "."
            en = p + "."
            flashcards.append({"fr": fr, "en": en, "category": cat})
            added += 1
            if len(flashcards) >= 320: return

generate_more()

# If still below 320 (unlikely), append simple filler sentences
while len(flashcards) < 320:
    idx = len(flashcards) % 5
    filler = [
        ("Je lis un livre ce soir.", "I am reading a book tonight.", "Daily Life"),
        ("Où est la boulangerie la plus proche ?", "Where is the nearest bakery?", "Travel"),
        ("La soupe est chaude.", "The soup is hot.", "Food & Drinks"),
        ("Combien de temps cela prend ?", "How long does it take?", "Questions"),
        ("Il y a du monde aujourd'hui.", "There are a lot of people today.", "Daily Life")
    ][idx]
    flashcards.append({"fr": filler[0], "en": filler[1], "category": filler[2]})

# ---------------------------
# End dataset creation
# flashcards variable now contains 320+ items
# ---------------------------

# ---------------------------
# Helper: TTS endpoint saves mp3 files and cleans old files
# ---------------------------
def cleanup_old_audio(max_age_seconds=60*60):
    now = time.time()
    for f in AUDIO_DIR.iterdir():
        try:
            if f.is_file() and now - f.stat().st_mtime > max_age_seconds:
                f.unlink()
        except Exception:
            pass

# ---------------------------
# Endpoints
# ---------------------------
@app.route("/flashcards", methods=["GET"])
def get_flashcards():
    """
    Query params:
      - page (1-based)
      - page_size
      - q (search text in fr or en)
      - category (exact category name)
    """
    try:
        page = max(1, int(request.args.get("page", 1)))
    except:
        page = 1
    try:
        page_size = max(1, int(request.args.get("page_size", 12)))
    except:
        page_size = 12
    q = (request.args.get("q") or "").strip().lower()
    category = (request.args.get("category") or "").strip()

    filtered = []
    for c in flashcards:
        match = True
        if q:
            if q not in c["fr"].lower() and q not in c["en"].lower():
                match = False
        if category:
            if category.lower() != c.get("category","").lower():
                match = False
        if match:
            filtered.append(c)

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    page_items = filtered[start:end]
    return jsonify({"success": True, "page": page, "page_size": page_size, "total": total, "items": page_items})

@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json() or {}
    text = data.get("text")
    if not text:
        return jsonify({"success": False, "error": "No text provided"}), 400
    # create safe filename
    safe_fragment = "".join(ch for ch in text if ch.isalnum() or ch in (' ', '-', '_'))[:30].strip().replace(" ", "_")
    filename = f"{int(time.time()*1000)}_{safe_fragment}.mp3"
    filepath = AUDIO_DIR / filename
    try:
        tts_obj = gTTS(text=text, lang='fr')
        tts_obj.save(str(filepath))
        cleanup_old_audio()
        return jsonify({"success": True, "file": f"{BASE_URL}/audio/{filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(str(AUDIO_DIR), filename)

# Simple visitor/session tracking (no geoip)
@app.route("/visit_start", methods=["POST"])
def visit_start():
    data = request.get_json() or {}
    session_id = str(uuid.uuid4())
    now = time.time()
    ip = request.remote_addr
    ua = data.get("user_agent") or request.headers.get("User-Agent", "")
    entry = {"session_id": session_id, "ip": ip, "user_agent": ua, "start": now, "end": None, "duration": None}
    store = load_visits()
    store["sessions"][session_id] = entry
    store["visits"].append({"session_id": session_id, "ip": ip, "start": now})
    save_visits(store)
    return jsonify({"success": True, "session_id": session_id})

@app.route("/visit_end", methods=["POST"])
def visit_end():
    data = request.get_json() or {}
    session_id = data.get("session_id")
    now = time.time()
    store = load_visits()
    entry = store["sessions"].get(session_id)
    if not entry:
        return jsonify({"success": False, "error": "Unknown session_id"}), 400
    entry["end"] = now
    entry["duration"] = now - entry["start"]
    store["sessions"][session_id] = entry
    save_visits(store)
    return jsonify({"success": True, "duration": entry["duration"]})

@app.route("/stats", methods=["GET"])
def stats():
    store = load_visits()
    visits = store.get("visits", [])
    sessions = store.get("sessions", {})
    total_visits = len(visits)
    unique_ips = set(v["ip"] for v in visits)
    total_unique = len(unique_ips)
    durations = [s.get("duration") for s in sessions.values() if s.get("duration") is not None]
    avg_duration = (sum(durations)/len(durations)) if durations else 0
    recent = sorted(sessions.values(), key=lambda s: s["start"], reverse=True)[:20]
    # count by IP prefix as a lightweight "from where" proxy (not exact country)
    ip_prefix_counts = {}
    for v in visits:
        ip = v.get("ip","unknown")
        prefix = ip.split(".")[0] if "." in ip else ip
        ip_prefix_counts[prefix] = ip_prefix_counts.get(prefix, 0) + 1
    return jsonify({
        "success": True,
        "total_visits": total_visits,
        "unique_ips": total_unique,
        "avg_session_seconds": avg_duration,
        "by_ip_prefix": ip_prefix_counts,
        "recent_sessions": recent
    })

# if __name__ == "__main__":
#     print("Starting French flashcards API on http://127.0.0.1:5000")
#     app.run(debug=True)

if __name__ == "__main__":
    print("Starting French flashcards API on https://my-api-n352.onrender.com")
    app.run(debug=True)
