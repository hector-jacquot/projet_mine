import json
import os
import smtplib
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.message import EmailMessage
from functools import wraps
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
import pymysql
from flask import (
    Flask,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

APP_NAME = "MineSecur"

# Charger les variables d'environnement depuis le fichier .env
# On utilise le chemin absolu pour être sûr que Windows le trouve
basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, ".env"))

# Métadonnées capteurs (affichage + unités)
CAPTEURS: Dict[str, Dict[str, str]] = {
    "temperature": {"label": "Température", "unit": "°C"},
    "humidite": {"label": "Humidité", "unit": "%"},
    "lumiere": {"label": "Luminosité", "unit": "lux"},
    "presence": {"label": "Présence humaine", "unit": ""},
    "co2": {"label": "CO₂", "unit": "ppm"},
    "ch4": {"label": "Méthane (CH₄)", "unit": "%"},
}


def create_app() -> Flask:
    app = Flask(__name__)

    # Sécurité cookies de session (à adapter si vous êtes en HTTP local)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", os.urandom(32)),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
    )

    @app.before_request
    def load_user():
        g.user = None
        user_id = session.get("user_id")
        if user_id:
            g.user = query_one("SELECT id, email, role FROM utilisateurs WHERE id=%s", (user_id,))

    @app.context_processor
    def inject_globals():
        return {
            "APP_NAME": APP_NAME,
            "user": g.get("user"),
            "capteurs_meta": CAPTEURS,
            "csrf_token": get_or_create_csrf_token(),
        }

    @app.errorhandler(ValueError)
    def handle_value_error(err):
        # Exemple : CSRF invalide.
        flash(str(err), "danger")
        return redirect(request.referrer or url_for("index"))

    @app.template_filter("fmt_dt")
    def fmt_dt(value):
        if not value:
            return ""
        # pymysql renvoie datetime naïf (timezone serveur MySQL). On l'affiche tel quel.
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return str(value)

    # -------- Pages --------
    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            require_csrf()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            if not email or not password:
                flash("Email et mot de passe requis.", "danger")
                return render_template("register.html"), 400

            if len(password) < 8:
                flash("Mot de passe trop court (min 8 caractères).", "danger")
                return render_template("register.html"), 400

            existing = query_one("SELECT id FROM utilisateurs WHERE email=%s", (email,))
            if existing:
                flash("Cet email est déjà utilisé.", "warning")
                return render_template("register.html"), 409

            password_hash = generate_password_hash(password)
            execute(
                "INSERT INTO utilisateurs (email, password, role) VALUES (%s, %s, 'user')",
                (email, password_hash),
            )
            flash("Compte créé. Vous pouvez vous connecter.", "success")
            return redirect(url_for("login"))

        return render_template("register.html")

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            require_csrf()
            email = (request.form.get("email") or "").strip().lower()
            password = request.form.get("password") or ""

            user = query_one(
                "SELECT id, email, password, role FROM utilisateurs WHERE email=%s",
                (email,),
            )
            if not user or not check_password_hash(user["password"], password):
                flash("Identifiants invalides.", "danger")
                return render_template("login.html"), 401

            session.clear()
            session["user_id"] = user["id"]
            session["role"] = user["role"]
            flash("Connexion réussie.", "success")
            return redirect(url_for("affichage"))

        return render_template("login.html")

    @app.get("/logout")
    def logout():
        session.clear()
        flash("Déconnecté.", "info")
        return redirect(url_for("index"))

    @app.route("/gestion", methods=["GET", "POST"])
    @admin_required
    def gestion():
        if request.method == "POST":
            require_csrf()
            capteur_type = (request.form.get("capteur_type") or "").strip()
            seuil_min_raw = (request.form.get("seuil_min") or "").strip()
            seuil_max_raw = (request.form.get("seuil_max") or "").strip()

            if capteur_type not in CAPTEURS:
                flash("Type de capteur invalide.", "danger")
                return redirect(url_for("gestion"))

            seuil_min = parse_float_or_none(seuil_min_raw)
            seuil_max = parse_float_or_none(seuil_max_raw)

            execute(
                """
                UPDATE capteurs 
                SET seuilmin = %s, seuilmax = %s
                WHERE type = %s
                """,
                (seuil_min, seuil_max, capteur_type),
            )
            flash("Seuil mis à jour.", "success")
            return redirect(url_for("gestion"))

        seuils = query_all("SELECT type as capteur_type, seuilmin as seuil_min, seuilmax as seuil_max FROM capteurs")
        seuils_map = {row["capteur_type"]: row for row in seuils}
        # Garantie d'un ordre stable dans l'UI
        ordered = []
        for t in CAPTEURS.keys():
            ordered.append(
                seuils_map.get(
                    t,
                    {"capteur_type": t, "seuil_min": None, "seuil_max": None},
                )
            )
        return render_template("gestion.html", seuils=ordered)

    @app.get("/affichage")
    @login_required
    def affichage():
        latest = get_latest_readings()
        outside = get_outside_temperature()
        seuils = get_thresholds_map()
        return render_template(
            "affichage.html",
            latest=latest,
            seuils=seuils,
            outside=outside,
        )

    # -------- API (Dashboard) --------
    @app.get("/api/dernieres")
    @login_required
    def api_dernieres():
        latest = get_latest_readings()
        seuils = get_thresholds_map()
        payload = {}
        for capteur_type in CAPTEURS.keys():
            row = latest.get(capteur_type)
            payload[capteur_type] = {
                "capteur_type": capteur_type,
                "valeur": row["valeur"] if row else None,
                "buzzer_on": int(row["buzzer_on"]) if row else 0,
                "created_at": row["created_at"].isoformat() if row and row.get("created_at") else None,
                "seuil_min": seuils.get(capteur_type, {}).get("seuil_min"),
                "seuil_max": seuils.get(capteur_type, {}).get("seuil_max"),
            }
        return jsonify(payload)

    @app.get("/api/historique/<capteur_type>")
    @login_required
    def api_historique(capteur_type: str):
        capteur_type = (capteur_type or "").strip().lower()
        if capteur_type not in CAPTEURS:
            return jsonify({"error": "capteur_type invalide"}), 400

        seuils = get_thresholds_map()
        rows = query_all(
            """
            SELECT c.valeur, c.date as created_at
            FROM captures c
            JOIN capteurs s ON c.idCapteur = s.id
            WHERE s.type = %s
            ORDER BY c.date DESC
            LIMIT 10
            """,
            (capteur_type,),
        )
        rows.reverse()
        
        points = []
        for r in rows:
            is_alert, _ = compute_buzzer_state(capteur_type, r["valeur"], seuils.get(capteur_type))
            points.append({
                "valeur": r["valeur"],
                "buzzer_on": 1 if is_alert else 0,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            })
            
        return jsonify({
            "capteur_type": capteur_type,
            "points": points
        })

    @app.get("/api/meteo")
    @login_required
    def api_meteo():
        outside = get_outside_temperature()
        return jsonify(outside)

    # -------- API (IoT / Ingestion) --------
    @app.post("/api/ingest")
    def api_ingest():
        """
        Endpoint de test pour poster des relevés depuis un objet connecté.
        Sécurisation simple via header X-API-KEY.
        """
        expected = os.environ.get("API_KEY")
        if expected:
            provided = request.headers.get("X-API-KEY", "")
            if provided != expected:
                return jsonify({"error": "unauthorized"}), 401

        data = request.get_json(silent=True) or {}
        capteur_type = (data.get("capteur_type") or data.get("type") or "").strip().lower()
        valeur = data.get("valeur", None)

        if capteur_type not in CAPTEURS:
            return jsonify({"error": "capteur_type invalide"}), 400
        try:
            valeur_f = float(valeur)
        except (TypeError, ValueError):
            return jsonify({"error": "valeur invalide"}), 400

        # Trouver l'ID du capteur
        capteur = query_one("SELECT id FROM capteurs WHERE type = %s", (capteur_type,))
        if not capteur:
            return jsonify({"error": "capteur non configuré en BDD"}), 404

        seuils = get_thresholds_map()
        buzzer_on, reason = compute_buzzer_state(capteur_type, valeur_f, seuils.get(capteur_type))

        execute(
            """
            INSERT INTO captures (idCapteur, valeur)
            VALUES (%s, %s)
            """,
            (capteur["id"], valeur_f),
        )

        if buzzer_on and capteur_type in ("co2", "ch4"):
            send_gas_alert_email(capteur_type, valeur_f, reason)

        return jsonify({"ok": True, "buzzer_on": int(buzzer_on), "reason": reason})

    # Route TEMPORAIRE pour voir le schéma de la BDD
    @app.get("/debug/schema")
    def debug_schema():
        try:
            # Voir les colonnes de la table utilisateurs
            cols = query_all("DESCRIBE utilisateurs")
            
            # Voir toutes les tables
            tables = query_all("SHOW TABLES")
            
            return jsonify({
                "tables": tables,
                "utilisateurs_columns": cols
            })
        except Exception as e:
            return jsonify({"error": str(e)})

    # Bootstrap éventuel d'un admin
    try:
        ensure_admin_bootstrap()
    except Exception as e:
        print(f"ATTENTION: Impossible de bootstrap l'admin (les tables existent-elles ?). Erreur: {e}")

    return app


# ---------------- DB ----------------
def get_db():
    # Railway et certains hébergeurs nécessitent SSL pour les connexions distantes
    host = os.environ.get("MYSQL_HOST", "127.0.0.1").strip()
    user = os.environ.get("MYSQL_USER", "root").strip()
    password = os.environ.get("MYSQL_PASSWORD", "").strip()
    db_name = os.environ.get("MYSQL_DB", "minesecur").strip()
    port = int(os.environ.get("MYSQL_PORT", "3306"))

    ssl_config = None
    # Sur Windows avec Railway, SSL est souvent nécessaire pour éviter le "Lost connection"
    if "rlwy.net" in host or os.environ.get("MYSQL_SSL", "0") == "1":
        ssl_config = {"ssl": {"check_hostname": False}}  # Désactiver vérification hostname pour Railway

    # DEBUG: Décommentez la ligne suivante si vous avez un doute sur le chargement du .env
    print(f"DEBUG: Tentative de connexion à {user}@{host}:{port}/{db_name} (SSL: {ssl_config is not None})")

    try:
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=db_name,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
            ssl=ssl_config,
            connect_timeout=30,
            read_timeout=30,
            write_timeout=30,
        )
        # Tester la connexion immédiatement
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
        return conn
    except pymysql.err.OperationalError as e:
        print(f"\n[ERREUR SQL FATALE] Impossible de se connecter à la base de données.")
        print(f"Host: {host}, Port: {port}, User: {user}, DB: {db_name}")
        print(f"Détail: {e}\n")
        print("Vérifiez: 1) Les credentials dans .env  2) Si la BDD Railway est activée  3) Votre connexion internet")
        raise e


def query_one(sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def query_all(sql: str, params: Tuple[Any, ...] = ()) -> list[Dict[str, Any]]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())


def execute(sql: str, params: Tuple[Any, ...] = ()) -> int:
    with get_db() as conn:
        with conn.cursor() as cur:
            return cur.execute(sql, params)


# ---------------- Auth helpers ----------------
def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            flash("Accès administrateur requis.", "warning")
            return redirect(url_for("affichage"))
        return view(*args, **kwargs)

    return wrapped


# ---------------- CSRF (simple) ----------------
def get_or_create_csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = os.urandom(16).hex()
        session["csrf_token"] = token
    return token


def require_csrf():
    expected = session.get("csrf_token")
    provided = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    if not expected or not provided or provided != expected:
        raise ValueError("CSRF token invalide.")


# ---------------- Domain logic ----------------
def parse_float_or_none(value: str) -> Optional[float]:
    if value is None:
        return None
    v = value.strip()
    if v == "":
        return None
    try:
        return float(v.replace(",", "."))
    except ValueError:
        return None


def get_thresholds_map() -> Dict[str, Dict[str, Optional[float]]]:
    rows = query_all("SELECT type, seuilmin, seuilmax FROM capteurs")
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for r in rows:
        out[r["type"]] = {"seuil_min": r["seuilmin"], "seuil_max": r["seuilmax"]}
    return out


def compute_buzzer_state(
    capteur_type: str,
    valeur: float,
    seuil: Optional[Dict[str, Optional[float]]],
) -> Tuple[bool, str]:
    """
    Règles demandées :
    - température/humidité : alerte si valeur > seuil_max
    - lumière : alerte inverse si valeur < seuil_min
    - présence : alerte si valeur == 1
    - CO2/CH4 : alerte si valeur > seuil_max
    """
    seuil_min = (seuil or {}).get("seuil_min")
    seuil_max = (seuil or {}).get("seuil_max")

    if capteur_type == "lumiere" and seuil_min is not None and valeur < float(seuil_min):
        return True, f"Lumière trop faible (< {seuil_min})"

    if capteur_type == "presence":
        if int(valeur) == 1:
            return True, "Présence détectée"
        return False, "OK"

    if seuil_max is not None and valeur > float(seuil_max):
        return True, f"Dépassement (> {seuil_max})"

    if seuil_min is not None and valeur < float(seuil_min):
        return True, f"Sous-seuil (< {seuil_min})"

    return False, "OK"


def get_latest_readings() -> Dict[str, Dict[str, Any]]:
    # On récupère le dernier id de capture pour chaque capteur
    rows = query_all(
        """
        SELECT c.type as capteur_type, cap.valeur, cap.date as created_at
        FROM capteurs c
        LEFT JOIN (
            SELECT idCapteur, valeur, date
            FROM captures
            WHERE (idCapteur, id) IN (
                SELECT idCapteur, MAX(id)
                FROM captures
                GROUP BY idCapteur
            )
        ) cap ON c.id = cap.idCapteur
        """
    )
    
    seuils = get_thresholds_map()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        capteur_type = r["capteur_type"]
        valeur = r["valeur"]
        
        buzzer_on = 0
        if valeur is not None:
            is_alert, _ = compute_buzzer_state(capteur_type, valeur, seuils.get(capteur_type))
            buzzer_on = 1 if is_alert else 0
            
        out[capteur_type] = {
            "capteur_type": capteur_type,
            "valeur": valeur,
            "created_at": r["created_at"],
            "buzzer_on": buzzer_on
        }
    return out


# ---------------- Bonus : météo (Open-Meteo) ----------------
def get_outside_temperature() -> Dict[str, Any]:
    lat = os.environ.get("MINE_LAT")
    lon = os.environ.get("MINE_LON")
    if not lat or not lon:
        return {"ok": False, "temp_c": None, "source": "open-meteo", "error": "coords manquantes"}

    params = urllib.parse.urlencode(
        {"latitude": lat, "longitude": lon, "current": "temperature_2m", "timezone": "UTC"}
    )
    url = f"https://api.open-meteo.com/v1/forecast?{params}"

    try:
        with urllib.request.urlopen(url, timeout=4) as resp:
            raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            temp_c = data.get("current", {}).get("temperature_2m")
            return {
                "ok": True,
                "temp_c": temp_c,
                "source": "open-meteo",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
    except Exception as e:
        return {"ok": False, "temp_c": None, "source": "open-meteo", "error": str(e)}


# ---------------- Bonus : alerte mail ----------------
def send_gas_alert_email(capteur_type: str, valeur: float, reason: str):
    """
    Mode par défaut : simulation (print). Si SMTP_* sont fournis, envoi réel via smtplib.
    Variables :
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_TO
    """
    subject = f"[{APP_NAME}] Alerte gaz : {capteur_type.upper()}"
    body = f"Alerte déclenchée.\nCapteur: {capteur_type}\nValeur: {valeur}\nRaison: {reason}\n"

    smtp_host = os.environ.get("SMTP_HOST")
    smtp_to = os.environ.get("SMTP_TO")
    smtp_from = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USER")

    if not smtp_host or not smtp_to:
        # Simulation
        print(subject)
        print(body)
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = smtp_to
    msg.set_content(body)

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, port, timeout=8) as server:
        server.starttls(context=context)
        if user and password:
            server.login(user, password)
        server.send_message(msg)


def ensure_admin_bootstrap():
    """
    Optionnel : crée un admin si env vars définies.
    ADMIN_BOOTSTRAP_EMAIL, ADMIN_BOOTSTRAP_PASSWORD
    """
    email = (os.environ.get("ADMIN_BOOTSTRAP_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD") or ""
    if not email or not password:
        return

    existing = query_one("SELECT id FROM utilisateurs WHERE email=%s", (email,))
    if existing:
        execute("UPDATE utilisateurs SET role='admin' WHERE email=%s", (email,))
        return

    execute(
        "INSERT INTO utilisateurs (email, password, role) VALUES (%s, %s, 'admin')",
        (email, generate_password_hash(password)),
    )


app = create_app()

if __name__ == "__main__":
    # Lancement dev : python app.py
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
