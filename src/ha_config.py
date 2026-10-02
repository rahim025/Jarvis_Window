# ============================================================
#  ha_config.py — Configuration Home Assistant & Météo
#  Personnalisez CE fichier selon votre installation domotique
#  Ne touchez pas main2.py pour la domotique, tout est ici.
#  Auteur : Rahim Batchabi
# ============================================================

import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Connexion Home Assistant (chargé depuis .env) ────────────
HA_URL    = os.getenv("HA_URL", "")
HA_TOKEN  = os.getenv("HA_TOKEN", "")
HA_HEADERS = {
    "Authorization": f"Bearer {HA_TOKEN}",
    "Content-Type" : "application/json"
}

# ═══════════════════════════════════════════════════════════════
#  SECTION 1 — MÉTÉO PAR DÉFAUT
#  Remplacez par votre ville et ses coordonnées GPS.
#  Coordonnées : https://www.latlong.net/
# ═══════════════════════════════════════════════════════════════
VILLE_PAR_DEFAUT = "Paris"        # ← Votre ville
LAT_PAR_DEFAUT   = 48.8566        # ← Latitude
LON_PAR_DEFAUT   = 2.3522         # ← Longitude

# ═══════════════════════════════════════════════════════════════
#  SECTION 2 — LUMIÈRES
#  Format : "nom vocal" : "entity_id Home Assistant"
# ═══════════════════════════════════════════════════════════════
PIECES_LUMIERES = {
    # "salon"    : "light.salon",
    # "chambre"  : "light.chambre",
    # "toutes"   : "light.all",
}

# ═══════════════════════════════════════════════════════════════
#  SECTION 3 — PRISES CONNECTÉES
# ═══════════════════════════════════════════════════════════════
PIECES_PRISES = {
    # "salon"   : "switch.prise_salon",
}

# ═══════════════════════════════════════════════════════════════
#  SECTION 4 — CAPTEURS TEMPÉRATURE
# ═══════════════════════════════════════════════════════════════
PIECES_CAPTEURS = {
    # "salon"       : "sensor.salon_temperature",
}

PIECES_HUMIDITE = {
    # "bureau" : "sensor.bureau_humidite",
}

HA_TARIFS = {
    "p1": 0.1296, "p2": 0.1603, "p3": 0.1486,
    "p4": 0.1894, "p5": 0.1568, "p6": 0.7562,
}

APPAREILS_ENERGIE = {
    # "tv" : "sensor.prise_salon_mensuel",
}

APPAREILS_BATTERIE = {
    # "telephone" : "sensor.iphone_battery_level",
}

# ═══════════════════════════════════════════════════════════════
#  SECTION 9 — COULEURS RGB
# ═══════════════════════════════════════════════════════════════
COULEURS_MAP = {
    "rouge": [255,0,0], "bleu": [0,0,255], "vert": [0,255,0],
    "blanc": [255,255,255], "orange": [255,140,0], "violet": [148,0,211],
    "rose": [255,20,147], "jaune": [255,255,0], "cyan": [0,255,255],
    "magenta": [255,0,255], "turquoise": [64,224,208], "or": [255,215,0],
    "argent": [192,192,192], "indigo": [75,0,130], "marron": [139,69,19],
    "citron": [255,250,0], "corail": [255,127,80], "lavande": [230,230,250],
}

CODES_METEO = {
    0: "ciel degage", 1: "principalement clair", 2: "partiellement nuageux",
    3: "couvert", 45: "brouillard", 48: "brouillard givrant",
    51: "bruine legere", 53: "bruine moderee", 55: "bruine dense",
    61: "pluie faible", 63: "pluie moderee", 65: "pluie forte",
    71: "neige faible", 73: "neige moderee", 75: "neige forte",
    80: "averses faibles", 81: "averses moderees", 82: "averses violentes",
    85: "averses de neige", 86: "averses de neige fortes",
    95: "orage", 96: "orage avec grele", 99: "orage violent avec grele",
}

# ════════════════════════════════════════════════════════════════
#  FONCTIONS API HOME ASSISTANT (ne pas modifier)
# ════════════════════════════════════════════════════════════════

def ha_appeler_service(domaine, service, entity_id, donnees=None):
    try:
        payload = {"entity_id": entity_id}
        if donnees: payload.update(donnees)
        r = requests.post(f"{HA_URL}/api/services/{domaine}/{service}",
                          headers=HA_HEADERS, json=payload, timeout=5)
        return r.status_code in [200, 201]
    except Exception as e:
        print(f"[HA] Erreur service : {e}")
        return False

def ha_get_etat(entity_id, attribut=None):
    try:
        r    = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=HA_HEADERS, timeout=5)
        data = r.json()
        if attribut: return data.get("attributes", {}).get(attribut, "inconnu")
        return data.get("state", "inconnu")
    except Exception as e:
        print(f"[HA] Erreur get etat : {e}")
        return "inconnu"

def ha_get_calendrier(entity_id):
    try:
        now   = datetime.now()
        start = now.strftime("%Y-%m-%dT00:00:00Z")
        end   = now.strftime("%Y-%m-%dT23:59:59Z")
        r = requests.get(f"{HA_URL}/api/calendars/{entity_id}",
                         headers=HA_HEADERS, params={"start": start, "end": end}, timeout=5)
        return r.json()
    except Exception as e:
        print(f"[HA] Erreur calendrier : {e}")
        return []

def ha_lumiere(entity_id, etat="on", luminosite=None, rgb=None):
    service_name = "toggle" if etat == "toggle" else ("turn_on" if etat == "on" else "turn_off")
    donnees = {}
    if etat == "on":
        if luminosite is not None: donnees["brightness"] = int(luminosite)
        if rgb is not None: donnees["rgb_color"] = rgb
    return ha_appeler_service("light", service_name, entity_id, donnees)

def ha_interrupteur(entity_id, etat="on"):
    return ha_appeler_service("switch", "turn_on" if etat == "on" else "turn_off", entity_id)

def ha_thermostat(entity_id, temperature):
    return ha_appeler_service("climate", "set_temperature", entity_id, {"temperature": temperature})

def ha_scene(scene_id):
    return ha_appeler_service("scene", "turn_on", scene_id)

# ════════════════════════════════════════════════════════════════
#  FONCTIONS MÉTÉO (Open-Meteo gratuit + HA fallback)
# ════════════════════════════════════════════════════════════════

def geocoder_ville(ville):
    try:
        r = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": ville, "count": 1, "language": "fr", "format": "json"}, timeout=5)
        data = r.json()
        if data.get("results"):
            res = data["results"][0]
            return res["latitude"], res["longitude"], res.get("name", ville), res.get("country", "")
    except Exception as e:
        print(f"[METEO] Erreur geocoding : {e}")
    return None, None, ville, ""

def get_meteo_actuelle(ville=None):
    try:
        nom_ville = ville or VILLE_PAR_DEFAUT
        lat, lon, nom_affiche, pays = geocoder_ville(nom_ville)
        if lat is None: lat, lon, nom_affiche = LAT_PAR_DEFAUT, LON_PAR_DEFAUT, VILLE_PAR_DEFAUT
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_direction_10m,weathercode,precipitation",
            "hourly": "temperature_2m,precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min,weathercode,precipitation_sum,wind_speed_10m_max,sunrise,sunset",
            "timezone": "Europe/Paris", "forecast_days": 3, "wind_speed_unit": "kmh",
        }, timeout=8)
        data = r.json()
        cur  = data["current"]
        desc = CODES_METEO.get(cur.get("weathercode", 0), "conditions inconnues")
        temp = round(float(cur.get("temperature_2m", 0)))
        return f"À {nom_affiche}, il fait {temp} degrés et le ciel est {desc}."
    except Exception as e:
        print(f"[METEO] Erreur : {e}")
        return "Je n'arrive pas à récupérer la météo pour le moment."

def get_meteo_ha():
    """Lit la météo depuis Home Assistant (fallback)."""
    try:
        r    = requests.get(f"{HA_URL}/api/states/weather.forecast_maison", headers=HA_HEADERS, timeout=5)
        data = r.json()
        etat  = data.get("state", "inconnu")
        attrs = data.get("attributes", {})
        temp = attrs.get("temperature", "?")
        etats_fr = {
            "sunny": "ensoleillé", "clear-night": "clair",
            "partlycloudy": "partiellement nuageux", "cloudy": "nuageux",
            "rainy": "pluvieux", "pouring": "forte pluie",
            "snowy": "neigeux", "fog": "brumeux",
            "lightning": "orageux", "exceptional": "conditions exceptionnelles",
        }
        desc = etats_fr.get(etat, etat)
        reponse = f"À {VILLE_PAR_DEFAUT}, il fait {temp} degrés et le ciel est {desc}."
        return reponse
    except Exception as e:
        print(f"[METEO HA] Erreur : {e}")
        return None

def get_alertes_meteo(ville=None):
    try:
        nom_ville = ville or VILLE_PAR_DEFAUT
        lat, lon, nom_affiche, _ = geocoder_ville(nom_ville)
        if lat is None: lat, lon, nom_affiche = LAT_PAR_DEFAUT, LON_PAR_DEFAUT, VILLE_PAR_DEFAUT
        r = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon,
            "daily": "weathercode,precipitation_sum,wind_speed_10m_max",
            "timezone": "Europe/Paris", "forecast_days": 3,
        }, timeout=8)
        data = r.json()
        daily = data["daily"]
        alertes = []
        for i in range(len(daily["weathercode"])):
            code  = daily["weathercode"][i]
            pluie = daily.get("precipitation_sum", [0]*3)[i] or 0
            vent  = daily.get("wind_speed_10m_max", [0]*3)[i] or 0
            jour  = ["aujourd hui", "demain", "apres-demain"][i]
            if code in [95, 96, 99]: alertes.append(f"Orage prevu {jour}")
            if code in [71, 73, 75, 85, 86]: alertes.append(f"Neige prevue {jour}")
            if pluie > 20: alertes.append(f"Fortes pluies {jour} ({pluie}mm)")
            if vent > 60: alertes.append(f"Vents forts {jour} ({vent} km/h)")
        if alertes: return f"Alertes meteo pour {nom_affiche} : " + ", ".join(alertes) + "."
        return f"Aucune alerte meteo pour {nom_affiche} dans les 3 prochains jours."
    except Exception as e:
        return f"Impossible de verifier les alertes meteo : {e}"
