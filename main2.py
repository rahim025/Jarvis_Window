import sys
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding="utf-8", errors="replace")  # corrige l'erreur 'charmap' de la console Windows
    except Exception:
        pass
# from ursina import *  # DESACTIVE — interface web Three.js
import threading
import asyncio
import google.genai as genai
from google.genai import types
import speech_recognition as sr
import edge_tts
# --- Pygame (audio TTS) : optionnel ---
try:
    import pygame
except ImportError:
    pygame = None
    print("[AVERTISSEMENT] pygame non installe — l'audio TTS sera desactive.")
    print("  -> Pour l'installer : pip install pygame --only-binary :all:")
import os
from dotenv import load_dotenv
import random
import math
import pyautogui
import webbrowser
import subprocess
import requests
import time
import pickle
import json
import re
import shutil
from pathlib import Path
from datetime import datetime
# --- PyAudio (micro/reconnaissance vocale) : optionnel ---
try:
    import pyaudio
except ImportError:
    pyaudio = None
    print("[AVERTISSEMENT] pyaudio non installe — le micro sera desactive.")
    print("  -> Pour l'installer : pip install pyaudio")
import websockets
from PIL import Image
from openai import OpenAI
import uuid
import base64
import io
try:
    import cv2
except ImportError:
    cv2 = None

try:
    import psutil
except ImportError:
    psutil = None

try:
    import anthropic as _anthropic_lib
except ImportError:
    _anthropic_lib = None

# --- Windows : utilitaires système (ctypes / winreg / os.startfile) ---
import signal
import platform
import ctypes
import glob
import functools
from ctypes import wintypes

IS_WINDOWS = platform.system() == "Windows"
FROZEN = bool(getattr(sys, "frozen", False))  # True quand Jarvis tourne en JARVIS.exe (installé)
if FROZEN:
    # Version installée : ressources dans le dossier du programme, données dans %APPDATA%\JARVIS
    RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "JARVIS")
else:
    RES_DIR = os.path.dirname(os.path.abspath(__file__))  # src/
    DATA_DIR = RES_DIR
BASE_DIR = DATA_DIR
os.makedirs(DATA_DIR, exist_ok=True)
os.chdir(DATA_DIR)  # .env, mémoire, profil, config et jetons Google restent dans DATA_DIR
os.environ.setdefault("PYTHONUTF8", "1")


def _trouver_dossier_projet(nom):
    """Cherche frontend/ ou mobile/ dans src/ puis à la racine du projet."""
    for base in (RES_DIR, os.path.dirname(RES_DIR)):
        p = os.path.join(base, nom)
        if os.path.isdir(p):
            return p
    return os.path.join(RES_DIR, nom)


_NOMS_DOSSIERS = {
    "Desktop": ("Desktop", "Bureau"),
    "Documents": ("Documents",),
    "Downloads": ("Downloads", "Téléchargements"),
    "Pictures": ("Pictures", "Images"),
    "Movies": ("Videos", "Vidéos"),
    "Music": ("Music", "Musique"),
}


def _dossier_utilisateur(*noms):
    """Dossier utilisateur Windows (gère les dossiers redirigés vers OneDrive)."""
    home = os.path.expanduser("~")
    candidats = []
    for base in (home, os.path.join(home, "OneDrive")):
        for n in noms:
            candidats.append(os.path.join(base, n))
    for c in candidats:
        if os.path.isdir(c):
            return c
    return candidats[0]


def _lancer_cible(cible):
    """Ouvre un fichier, dossier, URI (spotify:, ms-settings:...) ou programme via Windows."""
    try:
        os.startfile(cible)
        return True
    except Exception:
        try:
            subprocess.Popen(cible, shell=True)
            return True
        except Exception as e:
            print(f"[SYSTEME] Impossible d'ouvrir {cible} : {e}")
            return False


def _pids_proteges():
    """PID de Jarvis et de ses parents (on ne les tue jamais)."""
    pids = {os.getpid()}
    try:
        if psutil:
            pids.update(p.pid for p in psutil.Process().parents())
    except Exception:
        pass
    return pids


def _tuer_arbre(pid):
    """Termine un processus et ses enfants (taskkill)."""
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    except Exception:
        pass


_user32 = ctypes.windll.user32 if IS_WINDOWS else None


def _fenetres_visibles():
    """Retourne [(hwnd, titre, nom_processus)] pour les fenêtres visibles."""
    res = []
    if not _user32:
        return res
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            n = _user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                _user32.GetWindowTextW(hwnd, buf, n + 1)
                nom = ""
                if psutil:
                    pid = wintypes.DWORD()
                    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    try:
                        nom = psutil.Process(pid.value).name().lower()
                    except Exception:
                        pass
                res.append((hwnd, buf.value, nom))
        return True

    _user32.EnumWindows(EnumProc(cb), 0)
    return res


def _fenetre_trouver(titres=None, processus=None, proc_requis=None):
    titres = [t.lower() for t in (titres or [])]
    processus = [p.lower() for p in (processus or [])]
    for hwnd, titre, nom in _fenetres_visibles():
        if proc_requis and nom != proc_requis.lower():
            continue
        if processus and nom in processus:
            return hwnd
        if titres and any(t in titre.lower() for t in titres):
            return hwnd
    return None


def _fenetre_activer(hwnd):
    try:
        _user32.ShowWindow(hwnd, 9)              # SW_RESTORE
        _user32.keybd_event(0x12, 0, 0, 0)       # ALT : contourne le blocage du focus
        _user32.SetForegroundWindow(hwnd)
        _user32.keybd_event(0x12, 0, 2, 0)
        return True
    except Exception:
        return False


def _fenetre_placer(hwnd, x, y, w, h):
    _user32.ShowWindow(hwnd, 9)
    _user32.MoveWindow(hwnd, int(x), int(y), int(w), int(h), True)


def _ecran_zone_travail():
    """(x, y, largeur, hauteur) de la zone utile de l'écran, sans la barre des tâches."""
    if _user32:
        rect = wintypes.RECT()
        _user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
        return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    return 0, 0, 1920, 1040

# Google APIs (Gmail, Drive, Calendar) : optionnels
try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    _google_apis_ok = True
except ImportError:
    _google_apis_ok = False
    Credentials = None
    InstalledAppFlow = None
    Request = None
    build = None
    print("[AVERTISSEMENT] google-auth-oauthlib non installe — Gmail/Drive/Calendar desactives.")
    print("  -> Pour l'installer : pip install google-auth-oauthlib google-api-python-client")

# --- Volume Windows (pycaw) & luminosité (screen-brightness-control) ---
try:
    import pycaw.pycaw  # noqa: F401
    _pycaw_ok = True
except Exception:
    _pycaw_ok = False
try:
    import screen_brightness_control as _sbc
    _sbc_ok = True
except Exception:
    _sbc = None
    _sbc_ok = False

# --- PyWebView (fenetre native) : optionnel ---

try:
    import webview
    _WEBVIEW_OK = True
except ImportError:
    webview = None
    _WEBVIEW_OK = False

# --- CONFIGURATION VERSION & MAJ ---
CURRENT_VERSION = "4.0"
UPDATE_JSON_URL = ""  # vérification de mise à jour désactivée
DERNIERE_MAJ_INFO = None  # Stocke l'info si une MAJ est détectée
_WEBVIEW_OK = _WEBVIEW_OK and os.getenv("JARVIS_FENETRE", "0") == "1"  # fenêtre native : JARVIS_FENETRE=1


# Chargement des variables d'environnement
def _preparer_env():
    """Première exécution de la version installée : crée .env depuis le modèle et l'ouvre dans le Bloc-notes."""
    env_path = os.path.join(DATA_DIR, ".env")
    if FROZEN and not os.path.exists(env_path):
        modele = os.path.join(_trouver_dossier_projet("config_template"), ".env.example")
        try:
            if os.path.exists(modele):
                shutil.copyfile(modele, env_path)
            else:
                open(env_path, "w", encoding="utf-8").write("GEMINI_API_KEY=\nTIKTOK_USERNAME=\n")
            print(f"[JARVIS] Premier lancement : renseignez vos clés dans {env_path}")
            try:
                os.startfile(env_path)
            except Exception:
                pass
        except Exception as e:
            print(f"[JARVIS] Impossible de créer {env_path} : {e}")


_preparer_env()
load_dotenv(os.path.join(DATA_DIR, ".env"))
if not FROZEN:
    load_dotenv(os.path.join(os.path.dirname(RES_DIR), ".env"))

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY")
YOUTUBE_API_KEY      = os.getenv("YOUTUBE_API_KEY")
XAI_API_KEY          = os.getenv("XAI_API_KEY")
SERPAPI_API_KEY      = os.getenv("SERPAPI_API_KEY")
GROQ_API_KEY         = os.getenv("GROQ_API_KEY")
ANTHROPIC_API_KEY    = os.getenv("ANTHROPIC_API_KEY")
SPOTIFY_MUSIQUE_URI  = os.getenv("SPOTIFY_MUSIQUE_URI", "")
YOUTUBE_MUSIQUE_URL  = os.getenv("YOUTUBE_MUSIQUE_URL", "")

# Validateur universel — une clé non renseignée = placeholder = agent ignoré
_API_PLACEHOLDERS = frozenset({"VOTRE_CLE_ICI", "Votre ID", "votre_id",
                                "VOTRE_TOKEN_ICI", "votre_token_ici", ""})
def _cle_valide(key):
    return bool(key) and str(key).strip() not in _API_PLACEHOLDERS

# --- PROFIL UTILISATEUR ---
USER_PROFILE_FILE = "user_profile.json"
USER_NAME = "Monsieur" # Valeur par défaut

def charger_profil():
    global USER_NAME
    if os.path.exists(USER_PROFILE_FILE):
        try:
            with open(USER_PROFILE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                USER_NAME = data.get("name", "Monsieur")
        except:
            pass
    print(f"[SYSTEM] Utilisateur actuel : {USER_NAME}")

def sauvegarder_profil():
    try:
        with open(USER_PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump({"name": USER_NAME}, f, ensure_ascii=False, indent=4)
    except:
        pass

charger_profil()

# Configuration domotique, météo et entités Home Assistant
from ha_config import (
    HA_URL, HA_HEADERS,
    VILLE_PAR_DEFAUT, LAT_PAR_DEFAUT, LON_PAR_DEFAUT,
    PIECES_LUMIERES, PIECES_PRISES, PIECES_CAPTEURS, PIECES_HUMIDITE,
    HA_TARIFS, APPAREILS_ENERGIE, APPAREILS_BATTERIE,
    COULEURS_MAP, CODES_METEO,
    ha_appeler_service, ha_get_etat, ha_get_calendrier,
    ha_lumiere, ha_interrupteur, ha_thermostat, ha_scene,
    geocoder_ville, get_meteo_actuelle, get_meteo_ha, get_alertes_meteo,
)

gemini_actif    = _cle_valide(GEMINI_API_KEY)
try:
    client      = genai.Client(api_key=GEMINI_API_KEY)
except Exception as _e_gemini:
    client      = None
    gemini_actif = False
    print(f"[JARVIS] Gemini désactivé (clé absente ou invalide) : {_e_gemini}")

# Client Grok (xAI)
grok_client     = None
if _cle_valide(XAI_API_KEY):
    grok_client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1")

# Client Groq (Llama 3.3)
groq_client     = None
if _cle_valide(GROQ_API_KEY):
    groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

# Client Claude (Anthropic) — agent principal
anthropic_client = None
if _anthropic_lib and _cle_valide(ANTHROPIC_API_KEY):
    anthropic_client = _anthropic_lib.Anthropic(api_key=ANTHROPIC_API_KEY)

# ════════════════════════════════════════════════════════
#  MENU DES CLÉS API (enregistrées dans %APPDATA%\JARVIS\.env)
# ════════════════════════════════════════════════════════
# (variable, libellé, secret ?)
CLES_GEREES = [
    ("GEMINI_API_KEY",      "Gemini (Google)",           True),
    ("GROQ_API_KEY",        "Groq (Llama 3.3)",          True),
    ("XAI_API_KEY",         "Grok (xAI)",                True),
    ("ANTHROPIC_API_KEY",   "Claude (Anthropic)",        True),
    ("SERPAPI_API_KEY",     "SerpAPI (recherche web)",   True),
    ("YOUTUBE_API_KEY",     "YouTube Data API",          True),
    ("TIKTOK_USERNAME",     "Nom d'utilisateur TikTok",  False),
    ("SPOTIFY_MUSIQUE_URI", "Spotify : URI de la playlist", False),
    ("YOUTUBE_MUSIQUE_URL", "YouTube : lien de la musique", False),
]
_CLES_NOMS = {c[0] for c in CLES_GEREES}


def _masquer_cle(valeur):
    v = (valeur or "").strip()
    if not v:
        return ""
    return (v[:4] + "…" + v[-4:]) if len(v) > 12 else "••••••"


def etat_cles():
    """État des clés pour l'interface : jamais la valeur complète d'un secret."""
    res = []
    for nom, label, secret in CLES_GEREES:
        v = (os.getenv(nom) or "").strip()
        ok = bool(v) and v not in _API_PLACEHOLDERS
        res.append({
            "name": nom, "label": label, "secret": secret, "set": ok,
            "value": ("" if secret else v) if ok else "",
            "masked": _masquer_cle(v) if (ok and secret) else "",
        })
    return res


def _cerveaux_actifs():
    return {"gemini": bool(gemini_actif), "groq": groq_client is not None,
            "grok": grok_client is not None, "claude": anthropic_client is not None}


def _recharger_clients():
    """Relit les variables d'environnement et recrée les clients API à chaud."""
    global GEMINI_API_KEY, YOUTUBE_API_KEY, XAI_API_KEY, SERPAPI_API_KEY, GROQ_API_KEY
    global ANTHROPIC_API_KEY, SPOTIFY_MUSIQUE_URI, YOUTUBE_MUSIQUE_URL, TIKTOK_USERNAME
    global gemini_actif, client, grok_client, groq_client, anthropic_client
    GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
    YOUTUBE_API_KEY     = os.getenv("YOUTUBE_API_KEY")
    XAI_API_KEY         = os.getenv("XAI_API_KEY")
    SERPAPI_API_KEY     = os.getenv("SERPAPI_API_KEY")
    GROQ_API_KEY        = os.getenv("GROQ_API_KEY")
    ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY")
    SPOTIFY_MUSIQUE_URI = os.getenv("SPOTIFY_MUSIQUE_URI", "")
    YOUTUBE_MUSIQUE_URL = os.getenv("YOUTUBE_MUSIQUE_URL", "")
    TIKTOK_USERNAME     = os.getenv("TIKTOK_USERNAME", "").strip().lstrip("@")

    gemini_actif = False
    if _cle_valide(GEMINI_API_KEY):
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            gemini_actif = True
        except Exception as e:
            print(f"[CLES] Gemini : clé refusée ({e})")
    grok_client = OpenAI(api_key=XAI_API_KEY, base_url="https://api.x.ai/v1") if _cle_valide(XAI_API_KEY) else None
    groq_client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1") if _cle_valide(GROQ_API_KEY) else None
    anthropic_client = None
    if _anthropic_lib and _cle_valide(ANTHROPIC_API_KEY):
        try:
            anthropic_client = _anthropic_lib.Anthropic(api_key=ANTHROPIC_API_KEY)
        except Exception as e:
            print(f"[CLES] Claude : clé refusée ({e})")


def enregistrer_cles(valeurs):
    """Écrit les clés reçues dans le fichier .env de JARVIS puis recharge les clients.
    Un champ absent est laissé intact ; une chaîne vide efface la clé."""
    from dotenv import set_key
    env_path = os.path.join(DATA_DIR, ".env")
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(env_path):
        open(env_path, "w", encoding="utf-8").close()
    modifiees = []
    for nom, val in (valeurs or {}).items():
        if nom not in _CLES_NOMS or not isinstance(val, str):
            continue
        val = val.strip()
        if any(c in val for c in "\r\n\"'"):
            raise ValueError(f"Caractère interdit dans {nom}")
        set_key(env_path, nom, val, quote_mode="never")
        os.environ[nom] = val
        modifiees.append(nom)
    _recharger_clients()
    print(f"[CLES] Enregistré : {', '.join(modifiees) or 'rien'}")
    return modifiees


def _ws_est_local(ws):
    """Le menu des clés n'est accessible que depuis ce PC (pas depuis le Wi-Fi)."""
    try:
        ip = ws.remote_address[0]
    except Exception:
        return False
    if ip not in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return False
    origin = None
    try:
        origin = ws.request.headers.get("Origin")
    except Exception:
        try:
            origin = ws.request_headers.get("Origin")
        except Exception:
            origin = None
    if origin and origin != "null":
        from urllib.parse import urlparse
        if urlparse(origin).hostname not in ("localhost", "127.0.0.1", "::1"):
            return False
    return True


async def _gerer_msg_cles(ws, data):
    if not _ws_est_local(ws):
        await ws.send(json.dumps({"action": "keys_state", "error": "local_only"}))
        print("[CLES] Accès refusé (client non local).")
        return
    if data.get("type") == "save_keys":
        try:
            enregistrer_cles(data.get("keys") or {})
            await ws.send(json.dumps({"action": "keys_saved", "ok": True,
                                      "keys": etat_cles(), "active": _cerveaux_actifs()}))
        except Exception as e:
            await ws.send(json.dumps({"action": "keys_saved", "ok": False, "message": str(e)}))
    else:
        await ws.send(json.dumps({"action": "keys_state", "keys": etat_cles(),
                                  "active": _cerveaux_actifs(),
                                  "path": os.path.join(DATA_DIR, ".env")}))


MODELS_LIST     = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash", "gemini-2.5-pro", "gemini-2.0-flash-exp"]
CHOSEN_MODEL    = MODELS_LIST[0]

# Ollama (LLMs locaux — fallback 100% offline)
OLLAMA_URL      = "http://127.0.0.1:11434"
OLLAMA_MODELS   = ["mistral:instruct", "mistral", "llama3:8b", "llama3", "gemma4"]


# ══════════════════════════════════════════════════════════════
#  GESTIONNAIRE DE QUOTAS API — Failover automatique
# ══════════════════════════════════════════════════════════════

class _QuotaExceededError(Exception):
    """Levée quand une API signale un quota ou rate-limit épuisé."""
    pass

class APIQuotaManager:
    """
    Gère le cooldown des APIs quand leur quota est épuisé.
    Détecte automatiquement les erreurs 429 / resource_exhausted / rate_limit.
    """

    # Durée de cooldown par API (secondes)
    COOLDOWNS = {
        "claude"  : 60,
        "gemini"  : 60,
        "grok"    : 60,
        "groq"    : 30,
        "ollama"  : 10,
    }

    # Mots-clés indiquant un quota épuisé (insensible à la casse)
    QUOTA_KEYWORDS = [
        "429", "quota", "rate limit", "rate_limit", "ratelimit",
        "too many requests", "resource_exhausted", "resource exhausted",
        "exceeded", "tokens per", "requests per", "rateLimitExceeded",
        "quota_exceeded", "RATE_LIMIT_EXCEEDED", "insufficient_quota",
        "context_length_exceeded",
    ]

    def __init__(self):
        from datetime import datetime, timedelta
        self._datetime   = datetime
        self._timedelta  = timedelta
        self._cooldowns  = {}   # {api_name: datetime_disponible}
        self._hit_count  = {}   # {api_name: nb_fois_quota_atteint}

    def is_quota_error(self, error: Exception) -> bool:
        """Retourne True si l'erreur est liée à un quota/rate-limit."""
        err_str = str(error).lower()
        return any(kw.lower() in err_str for kw in self.QUOTA_KEYWORDS)

    def is_available(self, api_name: str) -> bool:
        """Retourne True si l'API est disponible (pas en cooldown)."""
        if api_name not in self._cooldowns:
            return True
        return self._datetime.now() >= self._cooldowns[api_name]

    def mark_quota_exceeded(self, api_name: str) -> None:
        """Place une API en cooldown après un quota épuisé."""
        duration = self.COOLDOWNS.get(api_name, 60)
        self._cooldowns[api_name] = self._datetime.now() + self._timedelta(seconds=duration)
        self._hit_count[api_name] = self._hit_count.get(api_name, 0) + 1
        print(f"[QUOTA] ⚠ {api_name.upper()} quota atteint — cooldown {duration}s "
              f"(total: {self._hit_count[api_name]} fois)")

    def remaining_cooldown(self, api_name: str) -> int:
        """Secondes restantes avant que l'API soit à nouveau disponible (0 si dispo)."""
        if self.is_available(api_name):
            return 0
        delta = self._cooldowns[api_name] - self._datetime.now()
        return max(0, int(delta.total_seconds()))

    def status(self) -> str:
        """Résumé du statut de toutes les APIs."""
        lines = []
        for api in self.COOLDOWNS:
            if not self.is_available(api):
                lines.append(f"  {api.upper()}: cooldown {self.remaining_cooldown(api)}s")
            else:
                lines.append(f"  {api.upper()}: disponible")
        return "\n".join(lines)

# Instance globale
_quota_mgr = APIQuotaManager()

CLAP_THRESHOLD = 1200
VIDEO_LANCEE   = False
MODE_IRON_MAN = False 

CREATOR_INFO = (
    "INFORMATIONS SUR TON CREATEUR :\n"
    "- Prenom : {USER_NAME}\n"
    "- Age : 37 ans\n"
    "- Date de naissance : 21 Mai 1988\n"
    "- Role : Ton createur et maitre\n"
    "- Tu dois toujours l appeler {USER_NAME} avec respect "
    "mais aussi une pointe de sarcasme affectueux.\n"
)

EXTENSIONS = {
    "Images"   : [".jpg", ".jpeg", ".png", ".gif", ".bmp",
                  ".tiff", ".tif", ".webp", ".svg", ".ico",
                  ".heic", ".raw", ".cr2", ".nef"],
    "Videos"   : [".mp4", ".avi", ".mkv", ".mov", ".wmv",
                  ".flv", ".webm", ".m4v", ".mpg", ".mpeg",
                  ".3gp", ".ts"],
    "Musique"  : [".mp3", ".wav", ".flac", ".aac", ".ogg",
                  ".wma", ".m4a", ".opus", ".aiff"],
    "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx",
                  ".ppt", ".pptx", ".txt", ".odt", ".ods",
                  ".odp", ".rtf", ".csv", ".epub"],
    "Archives" : [".zip", ".rar", ".7z", ".tar", ".gz",
                  ".bz2", ".xz", ".iso"],
    "Code"     : [".py", ".js", ".html", ".css", ".java",
                  ".cpp", ".c", ".h", ".cs", ".php",
                  ".json", ".xml", ".yaml", ".yml",
                  ".sh", ".bat", ".ps1", ".ts", ".jsx",
                  ".tsx", ".vue", ".go", ".rs", ".rb"],
    "Executables": [".exe", ".msi", ".apk", ".dmg", ".deb"],
}

dossier_courant = None

def resoudre_chemin(chemin):
    if not chemin:
        return None
    chemin = chemin.strip().strip('"').strip("'")
    raccourcis = {
        "bureau": _dossier_utilisateur(*_NOMS_DOSSIERS["Desktop"]),
        "desktop": _dossier_utilisateur(*_NOMS_DOSSIERS["Desktop"]),
        "document": _dossier_utilisateur(*_NOMS_DOSSIERS["Documents"]),
        "documents": _dossier_utilisateur(*_NOMS_DOSSIERS["Documents"]),
        "téléchargement": _dossier_utilisateur(*_NOMS_DOSSIERS["Downloads"]),
        "téléchargements": _dossier_utilisateur(*_NOMS_DOSSIERS["Downloads"]),
        "telechargement": _dossier_utilisateur(*_NOMS_DOSSIERS["Downloads"]),
        "telechargements": _dossier_utilisateur(*_NOMS_DOSSIERS["Downloads"]),
        "downloads": _dossier_utilisateur(*_NOMS_DOSSIERS["Downloads"]),
        "image": _dossier_utilisateur(*_NOMS_DOSSIERS["Pictures"]),
        "images": _dossier_utilisateur(*_NOMS_DOSSIERS["Pictures"]),
        "photo": _dossier_utilisateur(*_NOMS_DOSSIERS["Pictures"]),
        "photos": _dossier_utilisateur(*_NOMS_DOSSIERS["Pictures"]),
        "vidéo": _dossier_utilisateur(*_NOMS_DOSSIERS["Movies"]),
        "vidéos": _dossier_utilisateur(*_NOMS_DOSSIERS["Movies"]),
        "video": _dossier_utilisateur(*_NOMS_DOSSIERS["Movies"]),
        "videos": _dossier_utilisateur(*_NOMS_DOSSIERS["Movies"]),
        "musique": _dossier_utilisateur(*_NOMS_DOSSIERS["Music"]),
        "music": _dossier_utilisateur(*_NOMS_DOSSIERS["Music"]),
        "corbeille": "shell:RecycleBinFolder"
    }
    
    chemin_resolu = raccourcis.get(chemin.lower(), chemin)
    
    # Test des variantes françaises si le dossier anglais n'existe pas
    if not os.path.exists(chemin_resolu):
        variantes = {
            "Downloads": "Téléchargements",
            "Pictures": "Images",
            "Music": "Musique"
        }
        for eng, fra in variantes.items():
            if eng in chemin_resolu:
                test_fra = chemin_resolu.replace(eng, fra)
                if os.path.exists(test_fra):
                    chemin_resolu = test_fra
                    break
    return chemin_resolu

def trouver_extension(ext):
    for categorie, extensions in EXTENSIONS.items():
        if ext.lower() in extensions:
            return categorie
    return "Autres"

def ouvrir_dossier(chemin):
    global dossier_courant
    chemin_resolu = resoudre_chemin(chemin)
    if not chemin_resolu or (not os.path.exists(chemin_resolu) and not chemin_resolu.startswith("shell:")):
        return False, f"Dossier introuvable : {chemin_resolu}"
    dossier_courant = chemin_resolu
    # Utilisation de Popen pour ne pas bloquer
    _lancer_cible(chemin_resolu)
    return True, chemin_resolu

def arranger_fenetres_dossiers():
    """Ouvre et dispose les dossiers Documents, Téléchargements, Images et Vidéos."""
    dossiers = ["document", "téléchargement", "image", "vidéo"]
    for nom in dossiers:
        ouvrir_dossier(nom)
        time.sleep(0.5)
    # Sur macOS, on ne peut pas repositionner les fenêtres Finder facilement sans Accessibility
    # Les dossiers s'ouvrent chacun dans une fenêtre Finder
    return "J'ai ouvert vos dossiers principaux, {USER_NAME}."

def lister_dossier(chemin=None):
    cible = resoudre_chemin(chemin) or dossier_courant
    if not cible or not os.path.exists(cible):
        return None, "Aucun dossier ouvert ou chemin invalide."
    fichiers  = []
    dossiers  = []
    for item in os.scandir(cible):
        if item.is_file():
            fichiers.append(item.name)
        elif item.is_dir():
            dossiers.append(item.name)
    return {"chemin": cible, "fichiers": fichiers, "dossiers": dossiers}, None

def trier_par_type(chemin=None):
    cible = resoudre_chemin(chemin) or dossier_courant
    if not cible or not os.path.exists(cible):
        return False, "Aucun dossier ouvert ou invalide."
    deplacements = 0
    erreurs      = 0
    categories   = {}
    for item in os.scandir(cible):
        if not item.is_file():
            continue
        ext       = Path(item.name).suffix
        categorie = trouver_extension(ext)
        dest_dir  = os.path.join(cible, categorie)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, item.name)
            if os.path.exists(dest_path):
                base  = Path(item.name).stem
                ext2  = Path(item.name).suffix
                dest_path = os.path.join(dest_dir, f"{base}_{int(time.time())}{ext2}")
            shutil.move(item.path, dest_path)
            deplacements += 1
            categories[categorie] = categories.get(categorie, 0) + 1
        except Exception as e:
            print(f"[FICHIER] Erreur deplacement {item.name} : {e}")
            erreurs += 1
    resume = ", ".join([f"{v} {k}" for k, v in categories.items()])
    return True, f"{deplacements} fichiers tries : {resume}. {erreurs} erreurs."

def trier_par_date(chemin=None):
    cible = resoudre_chemin(chemin) or dossier_courant
    if not cible or not os.path.exists(cible):
        return False, "Aucun dossier ouvert ou invalide."
    deplacements = 0
    erreurs      = 0
    for item in os.scandir(cible):
        if not item.is_file():
            continue
        try:
            mtime     = item.stat().st_mtime
            date      = datetime.fromtimestamp(mtime)
            annee     = str(date.year)
            mois      = date.strftime("%m - %B")
            dest_dir  = os.path.join(cible, annee, mois)
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, item.name)
            if os.path.exists(dest_path):
                base      = Path(item.name).stem
                ext2      = Path(item.name).suffix
                dest_path = os.path.join(dest_dir, f"{base}_{int(time.time())}{ext2}")
            shutil.move(item.path, dest_path)
            deplacements += 1
        except Exception as e:
            print(f"[FICHIER] Erreur deplacement {item.name} : {e}")
            erreurs += 1
    return True, f"{deplacements} fichiers tries par date. {erreurs} erreurs."

def trier_par_type_puis_date(chemin=None):
    cible = chemin or dossier_courant
    if not cible or not os.path.exists(cible):
        return False, "Aucun dossier ouvert."
    ok1, msg1 = trier_par_type(cible)
    if not ok1:
        return False, msg1
    for item in os.scandir(cible):
        if item.is_dir() and item.name in EXTENSIONS.keys():
            trier_par_date(item.path)
    return True, "Dossier trie par type puis par date dans chaque categorie."

def creer_sous_dossier(nom, chemin=None):
    cible = resoudre_chemin(chemin) or dossier_courant
    if not cible:
        return False, "Aucun dossier ouvert."
    nouveau = os.path.join(cible, nom)
    try:
        os.makedirs(nouveau, exist_ok=True)
        return True, f"Dossier {nom} cree."
    except Exception as e:
        return False, f"Erreur creation dossier : {e}"

def renommer_fichier(ancien_nom, nouveau_nom, chemin=None):
    cible = resoudre_chemin(chemin) or dossier_courant
    if not cible:
        return False, "Aucun dossier ouvert."
    ancien = os.path.join(cible, ancien_nom)
    nouveau = os.path.join(cible, nouveau_nom)
    try:
        os.rename(ancien, nouveau)
        return True, f"Fichier renomme en {nouveau_nom}."
    except Exception as e:
        return False, f"Erreur renommage : {e}"

def deplacer_fichier(nom_fichier, dossier_dest, chemin=None):
    cible = resoudre_chemin(chemin) or dossier_courant
    if not cible:
        return False, "Aucun dossier ouvert."
    source = os.path.join(cible, nom_fichier)
    dest   = os.path.join(cible, dossier_dest, nom_fichier)
    try:
        os.makedirs(os.path.join(cible, dossier_dest), exist_ok=True)
        shutil.move(source, dest)
        return True, f"{nom_fichier} deplace dans {dossier_dest}."
    except Exception as e:
        return False, f"Erreur deplacement : {e}"

def chercher_fichier(nom, chemin=None):
    cible = resoudre_chemin(chemin) or dossier_courant
    if not cible:
        return [], "Aucun dossier ouvert."
    resultats = []
    for root, dirs, files in os.walk(cible):
        for f in files:
            if nom.lower() in f.lower():
                resultats.append(os.path.join(root, f))
    return resultats, None

# ==========================================
# MEMOIRE PERSISTANTE
# ==========================================
MEMOIRE_FILE = "jarvis_memoire.json"

def charger_memoire():
    if os.path.exists(MEMOIRE_FILE):
        try:
            with open(MEMOIRE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def sauvegarder_memoire(memoire):
    try:
        with open(MEMOIRE_FILE, "w", encoding="utf-8") as f:
            json.dump(memoire, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Erreur sauvegarde memoire : {e}")

def ajouter_memoire(cle, valeur):
    memoire      = charger_memoire()
    memoire[cle] = {"valeur": valeur, "timestamp": time.strftime("%d/%m/%Y %H:%M")}
    sauvegarder_memoire(memoire)

def supprimer_memoire(cle):
    memoire = charger_memoire()
    if cle in memoire:
        del memoire[cle]
        sauvegarder_memoire(memoire)
        return True
    return False

def construire_contexte_memoire():
    memoire = charger_memoire()
    if not memoire:
        return ""
    lignes = ["MEMOIRE PERSISTANTE :"]
    for cle, data in memoire.items():
        lignes.append(f"  - {cle} : {data['valeur']} (note le {data['timestamp']})")
    return "\n".join(lignes)

# ==========================================
# HISTORIQUE CONVERSATIONS PERSISTANT
# ==========================================
HISTORIQUE_CONV_FILE = "jarvis_conversations.json"
MAX_ECHANGES_FICHIER = 200   # max échanges stockés sur disque
MAX_ECHANGES_CHARGE  = 30    # échanges rechargés au démarrage (contexte IA)

def _sauvegarder_echange_conv(user_text: str, model_text: str):
    """Ajoute un échange user/model au fichier JSON persistant."""
    try:
        echanges = []
        if os.path.exists(HISTORIQUE_CONV_FILE):
            with open(HISTORIQUE_CONV_FILE, "r", encoding="utf-8") as f:
                echanges = json.load(f)
        echanges.append({
            "date":  time.strftime("%d/%m/%Y"),
            "heure": time.strftime("%H:%M"),
            "user":  user_text[:2000],
            "model": model_text[:3000],
        })
        if len(echanges) > MAX_ECHANGES_FICHIER:
            echanges = echanges[-MAX_ECHANGES_FICHIER:]
        with open(HISTORIQUE_CONV_FILE, "w", encoding="utf-8") as f:
            json.dump(echanges, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[CONV] Erreur sauvegarde historique: {e}")

def _charger_historique_recent():
    """Charge les derniers échanges et retourne une liste types.Content."""
    if not os.path.exists(HISTORIQUE_CONV_FILE):
        return []
    try:
        with open(HISTORIQUE_CONV_FILE, "r", encoding="utf-8") as f:
            echanges = json.load(f)
        recents = echanges[-MAX_ECHANGES_CHARGE:]
        hist = []
        for e in recents:
            date_str = f"[{e.get('date','?')} {e.get('heure','?')}] "
            hist.append(types.Content(role="user",  parts=[types.Part(text=date_str + e["user"])]))
            hist.append(types.Content(role="model", parts=[types.Part(text=e["model"])]))
        print(f"[CONV] {len(recents)} echanges passes rechargees en memoire.")
        return hist
    except Exception as e:
        print(f"[CONV] Erreur chargement historique: {e}")
        return []

# ==========================================
# WEBSOCKET
# ==========================================
CONNECTED_CLIENTS = set()
interface_deja_connectee = False
_skip_pc_audio = False  # True quand la commande vient du mobile (le tél gère son propre TTS)
PENDING_SCREEN_CAPTURES = {}
DERNIERE_MAJ_INFO = None

# --- ÉTAT CONTEXTUEL ---
EXPECTED_CONTEXT = None  # ex: "folder"
EXPECTED_TIMESTAMP = 0   # temps pour expirer le contexte

async def ws_handler(websocket):
    global interface_deja_connectee
    CONNECTED_CLIENTS.add(websocket)
    interface_deja_connectee = True
    print(f"[WEB] Interface connectee (Clients actifs: {len(CONNECTED_CLIENTS)})")
    
    # Push de la mise à jour si déjà détectée
    if DERNIERE_MAJ_INFO:
        try:
            await websocket.send(json.dumps(DERNIERE_MAJ_INFO))
        except:
            pass

    try:
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "mobile_command":
                    texte = data.get("text", "").strip()
                    if texte:
                        print(f"[MOBILE] Commande recue : {texte}")
                        asyncio.ensure_future(traiter_reponse_ia(texte, mobile_ws=websocket))
                elif data.get("type") in ("get_keys", "save_keys"):
                    await _gerer_msg_cles(websocket, data)
                elif data.get("type") == "stop_audio":
                    global STOP_PARLER
                    STOP_PARLER = True
                    print("[MOBILE] Signal STOP audio recu")
                elif data.get("type") == "user_input":
                    texte = data.get("text", "").strip()
                    if texte:
                        print(f"[WEB] Commande clavier recue : {texte}")
                        asyncio.ensure_future(traiter_reponse_ia(texte))
                elif data.get("type") == "screen_frame":
                    req_id = data.get("id")
                    if req_id in PENDING_SCREEN_CAPTURES:
                        fut = PENDING_SCREEN_CAPTURES.pop(req_id)
                        if "error" in data:
                            fut.set_exception(Exception(data["error"]))
                        else:
                            fut.set_result(data["data"])
                    print(f"[VISION] Frame recue pour ID: {req_id}")
            except Exception as e:
                print(f"[WEB] Erreur traitement message : {e}")
    except Exception:
        pass
    finally:
        CONNECTED_CLIENTS.discard(websocket)
        print(f"[WEB] Interface deconnectee (Clients actifs: {len(CONNECTED_CLIENTS)})")

async def send_web_state(state):
    if CONNECTED_CLIENTS:
        message = json.dumps({"action": "set_state", "state": state})
        await asyncio.gather(*[ws.send(message) for ws in CONNECTED_CLIENTS], return_exceptions=True)

async def send_web_volume(volume):
    if CONNECTED_CLIENTS:
        message = json.dumps({"action": "set_volume", "volume": round(volume, 3)})
        await asyncio.gather(*[ws.send(message) for ws in CONNECTED_CLIENTS], return_exceptions=True)

async def send_globe_command(**kwargs):
    """Envoie une commande de navigation globe au frontend."""
    if CONNECTED_CLIENTS:
        payload = {"action": "jarvis_globe"}
        payload.update(kwargs)
        msg = json.dumps(payload)
        await asyncio.gather(*[ws.send(msg) for ws in CONNECTED_CLIENTS], return_exceptions=True)

async def geocode_lieu(nom_lieu: str):
    """Géocode un nom de lieu via Nominatim (OpenStreetMap) — gratuit, sans clé API."""
    try:
        url = f"https://nominatim.openstreetmap.org/search?q={requests.utils.quote(nom_lieu)}&format=json&limit=1"
        headers = {"User-Agent": "JARVIS-Assistant/1.0 (personal use)"}
        resp = await asyncio.wait_for(
            asyncio.to_thread(requests.get, url, headers=headers, timeout=6),
            timeout=8.0
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", nom_lieu)
    except Exception as e:
        print(f"[GLOBE] Erreur géocodage '{nom_lieu}': {e}")
    return None, None, nom_lieu

async def request_screen_capture():
    """Demande une capture d'écran au frontend via WebSocket."""
    if not CONNECTED_CLIENTS:
        return None
    
    req_id = str(uuid.uuid4())
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    PENDING_SCREEN_CAPTURES[req_id] = fut
    
    print(f"[VISION] Envoi requete capture ID: {req_id}")
    msg = json.dumps({"action": "request_screen_capture", "id": req_id})
    await asyncio.gather(*[ws.send(msg) for ws in CONNECTED_CLIENTS])
    
    try:
        # Timeout de 15 secondes car l'utilisateur doit parfois accepter le partage
        img_b64 = await asyncio.wait_for(fut, timeout=15.0)
        return img_b64
    except Exception as e:
        print(f"[VISION] Erreur ou timeout capture : {e}")
        PENDING_SCREEN_CAPTURES.pop(req_id, None)
        return None

# ==========================================
# SPOTIFY
# ==========================================

def _focus_spotify():
    """Met la fenêtre Spotify au premier plan (Windows)."""
    try:
        hwnd = _fenetre_trouver(processus=["spotify.exe"])
        if hwnd:
            _fenetre_activer(hwnd)
            time.sleep(0.4)
            return True
        return False
    except Exception:
        return False

async def spotify_ouvrir():
    """Lance Spotify s'il n'est pas déjà ouvert."""
    try:
        # Déjà ouvert ?
        if _focus_spotify():
            return "Spotify est déjà ouvert, {USER_NAME}, je l'ai mis au premier plan."
        _lancer_cible("spotify:")
        time.sleep(4)
        _focus_spotify()
        return "Spotify lancé, {USER_NAME}."
    except Exception as e:
        return f"Je n'ai pas réussi à ouvrir Spotify : {e}"

async def spotify_lecture_pause():
    """Basculer lecture / pause via la touche média globale."""
    pyautogui.press('playpause')
    return "Lecture/Pause, {USER_NAME}."

async def spotify_suivant():
    """Piste suivante via la touche média globale."""
    pyautogui.press('nexttrack')
    return "Piste suivante, {USER_NAME}."

async def spotify_precedent():
    """Piste précédente via la touche média globale."""
    pyautogui.press('prevtrack')
    return "Piste précédente, {USER_NAME}."

async def spotify_stop():
    """Met en pause (Spotify n'a pas de vrai stop)."""
    _focus_spotify()
    time.sleep(0.2)
    pyautogui.press('playpause')
    return "Musique mise en pause, {USER_NAME}."

def spotify_lancer_playlist(playlist_uri: str = "") -> bool:
    """Ouvre Spotify et lance une playlist/piste par son URI ou son URL web.
    Utilisable depuis du code synchrone (executer_action_pc).
    Retourne True si réussi."""
    try:
        # Convertir URL web open.spotify.com → URI native spotify:
        if playlist_uri.startswith("https://open.spotify.com/"):
            m = re.search(r'/(track|playlist|album|artist)/([A-Za-z0-9]+)', playlist_uri)
            if m:
                playlist_uri = f"spotify:{m.group(1)}:{m.group(2)}"

        deja_ouvert = False
        try:
            deja_ouvert = _focus_spotify()
        except Exception:
            pass

        if playlist_uri:
            # Le protocole spotify: est géré par Windows → ouvre l'app et navigue
            _lancer_cible(playlist_uri)
            time.sleep(3)
        elif not deja_ouvert:
            _lancer_cible("spotify:")
            time.sleep(4)

        try:
            _focus_spotify()
        except Exception:
            pass
        return True
    except Exception as e:
        print(f"[SPOTIFY] Erreur lancement playlist : {e}")
        return False

async def spotify_volume(direction, paliers=4):
    """Monte ou baisse le volume Spotify via Ctrl+Haut/Bas."""
    if not _focus_spotify():
        return "Spotify ne semble pas ouvert, {USER_NAME}."
    time.sleep(0.2)
    for _ in range(int(paliers)):
        if direction in ("monter", "up", "augmenter", "plus"):
            pyautogui.hotkey('ctrl', 'up')
        else:
            pyautogui.hotkey('ctrl', 'down')
        time.sleep(0.05)
    msg = "Volume monté" if direction in ("monter", "up", "augmenter", "plus") else "Volume baissé"
    return f"{msg} sur Spotify, {USER_NAME}."

async def spotify_rechercher(recherche):
    """Ouvre la barre de recherche Spotify, tape la requête et valide."""
    import pyperclip
    # Spotify doit être ouvert
    if not _focus_spotify():
        await spotify_ouvrir()
        time.sleep(3)
        _focus_spotify()
    time.sleep(0.5)

    # Raccourci Ctrl+L pour aller dans la barre de recherche (toutes versions)
    pyautogui.hotkey('ctrl', 'l')
    time.sleep(0.5)
    # Fallback Ctrl+K (nouvelle interface Spotify)
    pyautogui.hotkey('ctrl', 'k')
    time.sleep(0.4)

    pyautogui.hotkey('ctrl', 'a')
    time.sleep(0.1)
    pyperclip.copy(recherche)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.2)
    pyautogui.press('enter')
    
    # On attend un peu plus pour être sûr que les résultats sont chargés
    time.sleep(2.0)
    
    # On appuie sur Entrée pour valider la recherche (ouvre l'album/artiste si c'est le cas)
    pyautogui.press('enter')
    time.sleep(1.0)
    
    # On appuie une deuxième fois sur Entrée pour lancer la lecture du premier élément
    # C'est plus fiable que Tab+Entrée qui peut dériver sur d'autres boutons
    pyautogui.press('enter')
    time.sleep(0.5)
    
    # Sécurité supplémentaire : si c'était déjà sélectionné mais en pause
    # (Note: l'appui sur 'space' peut être risqué si on n'est pas focus, mais Entrée est safe)
    pyautogui.press('enter')
    
    return f"C'est fait {USER_NAME}, je lance la lecture de '{recherche}' sur Spotify."

# ==========================================
# MODE BOULOT
# ==========================================

def _boulot_trouver_exe(noms_exe: list, chemins_hints: list = None) -> str:
    """Trouve un programme sur Windows.
    Ordre : chemins connus (jokers OK) → PATH → registre « App Paths »."""
    for hint in (chemins_hints or []):
        for p in glob.glob(os.path.expandvars(hint)):
            if os.path.exists(p):
                return p
    for exe in noms_exe:
        found = shutil.which(exe)
        if found:
            return found
    try:
        import winreg
        for exe in noms_exe:
            for racine in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(racine, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\\" + exe) as cle:
                        val, _ = winreg.QueryValueEx(cle, "")
                        val = (val or "").strip('"')
                        if val and os.path.exists(val):
                            return val
                except OSError:
                    pass
    except ImportError:
        pass
    return ""


def _raccourci_menu_demarrer(label: str) -> str:
    """Cherche un raccourci .lnk du menu Démarrer portant le nom de l'appli."""
    bases = [os.path.expandvars(r"%ProgramData%\Microsoft\Windows\Start Menu\Programs"),
             os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs")]
    mot = label.lower()
    for base in bases:
        for racine, _dirs, fichiers in os.walk(base):
            for f in fichiers:
                if f.lower().endswith(".lnk") and mot in f.lower():
                    return os.path.join(racine, f)
    return ""


def _boulot_lancer(label: str, noms_exe: list,
                   chemins_hints: list = None, env_key: str = None, uri: str = None) -> bool:
    """Lance une application Windows : .env → chemins connus/PATH/registre → URI → menu Démarrer."""
    if env_key:
        env_val = os.getenv(env_key, "")
        if env_val and os.path.exists(env_val) and _lancer_cible(env_val):
            return True

    chemin = _boulot_trouver_exe(noms_exe, chemins_hints)
    if chemin:
        try:
            subprocess.Popen([chemin], cwd=os.path.dirname(chemin) or None)
            return True
        except Exception:
            if _lancer_cible(chemin):
                return True

    if uri and _lancer_cible(uri):
        return True

    lnk = _raccourci_menu_demarrer(label)
    if lnk and _lancer_cible(lnk):
        return True

    print(f"[BOULOT] {label} introuvable sur ce PC")
    return False


def _fermer_app(noms_process: list) -> bool:
    """Termine les processus portant ces noms (insensible à la casse).
    Jarvis et son terminal ne sont jamais fermés."""
    if psutil is None:
        return False
    protege = _pids_proteges()
    tues = 0
    noms_lower = [n.lower() for n in noms_process]
    for proc in psutil.process_iter(['name']):
        try:
            if proc.pid in protege:
                continue
            if proc.info['name'] and proc.info['name'].lower() in noms_lower:
                proc.terminate()
                tues += 1
        except Exception:
            pass
    return tues > 0


# Catalogue d'applications ouvrables / fermables par commande vocale
_APPS_CATALOGUE = {}


def _app(cle, label, noms, hints=None, uri=None):
    _APPS_CATALOGUE[cle] = {"label": label, "noms": noms, "hints": hints or [], "uri": uri}


_PF, _PF86, _LAD, _AD = r"%ProgramFiles%", r"%ProgramFiles(x86)%", r"%LOCALAPPDATA%", r"%APPDATA%"

# ── Navigateurs ──────────────────────────────────────────
_app("chrome", "Google Chrome", ["chrome.exe"],
     [_PF + r"\Google\Chrome\Application\chrome.exe", _PF86 + r"\Google\Chrome\Application\chrome.exe",
      _LAD + r"\Google\Chrome\Application\chrome.exe"])
_app("firefox", "Firefox", ["firefox.exe"], [_PF + r"\Mozilla Firefox\firefox.exe", _PF86 + r"\Mozilla Firefox\firefox.exe"])
_app("edge", "Microsoft Edge", ["msedge.exe"], [_PF86 + r"\Microsoft\Edge\Application\msedge.exe", _PF + r"\Microsoft\Edge\Application\msedge.exe"])
_app("opera", "Opera", ["opera.exe"], [_LAD + r"\Programs\Opera\opera.exe", _LAD + r"\Programs\Opera GX\opera.exe"])
_app("brave", "Brave", ["brave.exe"], [_PF + r"\BraveSoftware\Brave-Browser\Application\brave.exe", _LAD + r"\BraveSoftware\Brave-Browser\Application\brave.exe"])
# ── Jeux / lanceurs ──────────────────────────────────────
_app("steam", "Steam", ["steam.exe"], [_PF86 + r"\Steam\steam.exe", _PF + r"\Steam\steam.exe"], uri="steam://open/main")
_app("epic", "Epic Games", ["EpicGamesLauncher.exe"],
     [_PF86 + r"\Epic Games\Launcher\Portal\Binaries\Win64\EpicGamesLauncher.exe",
      _PF86 + r"\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe"])
_app("origin", "Origin", ["Origin.exe"], [_PF86 + r"\Origin\Origin.exe"])
_app("ea", "EA App", ["EADesktop.exe"], [_PF + r"\Electronic Arts\EA Desktop\EA Desktop\EADesktop.exe"])
_app("ubisoft", "Ubisoft Connect", ["UbisoftConnect.exe", "upc.exe"], [_PF86 + r"\Ubisoft\Ubisoft Game Launcher\UbisoftConnect.exe"])
_app("gog", "GOG Galaxy", ["GalaxyClient.exe"], [_PF86 + r"\GOG Galaxy\GalaxyClient.exe"])
_app("minecraft", "Minecraft", ["MinecraftLauncher.exe"], [_PF86 + r"\Minecraft Launcher\MinecraftLauncher.exe", _PF + r"\Minecraft Launcher\MinecraftLauncher.exe"])
# ── Communication ────────────────────────────────────────
_app("discord", "Discord", ["Discord.exe"], [], uri="discord://")
_app("teams", "Microsoft Teams", ["ms-teams.exe", "Teams.exe"], [_LAD + r"\Microsoft\Teams\current\Teams.exe"], uri="msteams:")
_app("whatsapp", "WhatsApp", ["WhatsApp.exe"], [_LAD + r"\WhatsApp\WhatsApp.exe"], uri="whatsapp:")
_app("telegram", "Telegram", ["Telegram.exe"], [_AD + r"\Telegram Desktop\Telegram.exe"], uri="tg://")
_app("zoom", "Zoom", ["Zoom.exe"], [_AD + r"\Zoom\bin\Zoom.exe", _PF + r"\Zoom\bin\Zoom.exe"])
_app("skype", "Skype", ["Skype.exe"], [], uri="skype:")
# ── Bureautique / Office ─────────────────────────────────
_app("word", "Microsoft Word", ["WINWORD.EXE"], [_PF + r"\Microsoft Office\root\Office16\WINWORD.EXE", _PF86 + r"\Microsoft Office\root\Office16\WINWORD.EXE"])
_app("excel", "Microsoft Excel", ["EXCEL.EXE"], [_PF + r"\Microsoft Office\root\Office16\EXCEL.EXE", _PF86 + r"\Microsoft Office\root\Office16\EXCEL.EXE"])
_app("powerpoint", "Microsoft PowerPoint", ["POWERPNT.EXE"], [_PF + r"\Microsoft Office\root\Office16\POWERPNT.EXE", _PF86 + r"\Microsoft Office\root\Office16\POWERPNT.EXE"])
_app("outlook", "Outlook", ["OUTLOOK.EXE", "olk.exe"], [_PF + r"\Microsoft Office\root\Office16\OUTLOOK.EXE", _PF86 + r"\Microsoft Office\root\Office16\OUTLOOK.EXE"])
_app("onenote", "OneNote", ["ONENOTE.EXE"], [_PF + r"\Microsoft Office\root\Office16\ONENOTE.EXE"], uri="onenote:")
# ── Création ─────────────────────────────────────────────
_app("photoshop", "Photoshop", ["Photoshop.exe"], [_PF + r"\Adobe\Adobe Photoshop *\Photoshop.exe"])
_app("premiere", "Premiere Pro", ["Adobe Premiere Pro.exe"], [_PF + r"\Adobe\Adobe Premiere Pro *\Adobe Premiere Pro.exe"])
_app("after effects", "After Effects", ["AfterFX.exe"], [_PF + r"\Adobe\Adobe After Effects *\Support Files\AfterFX.exe"])
_app("illustrator", "Illustrator", ["Illustrator.exe"], [_PF + r"\Adobe\Adobe Illustrator *\Support Files\Contents\Windows\Illustrator.exe"])
_app("capcut", "CapCut", ["CapCut.exe"], [_LAD + r"\CapCut\Apps\CapCut.exe"])
_app("obs", "OBS Studio", ["obs64.exe"], [_PF + r"\obs-studio\bin\64bit\obs64.exe"])
_app("blender", "Blender", ["blender.exe"], [_PF + r"\Blender Foundation\Blender *\blender.exe"])
_app("gimp", "GIMP", ["gimp-2.10.exe", "gimp-3.exe", "gimp.exe"], [_LAD + r"\Programs\GIMP *\bin\gimp-*.exe", _PF + r"\GIMP *\bin\gimp-*.exe"])
# ── Développement ────────────────────────────────────────
_app("vscode", "Visual Studio Code", ["Code.exe"], [_LAD + r"\Programs\Microsoft VS Code\Code.exe", _PF + r"\Microsoft VS Code\Code.exe"])
_app("cursor", "Cursor", ["Cursor.exe"], [_LAD + r"\Programs\cursor\Cursor.exe", _LAD + r"\Programs\Cursor\Cursor.exe"])
_app("claude", "Claude", ["Claude.exe"], [_LAD + r"\AnthropicClaude\claude.exe", _LAD + r"\Programs\Claude\Claude.exe"])
_app("terminal", "Terminal", ["wt.exe", "cmd.exe"], [])
_app("antigravity", "Antigravity", ["Antigravity.exe"], [_LAD + r"\Programs\Antigravity\Antigravity.exe"])
# ── Médias / utilitaires ─────────────────────────────────
_app("vlc", "VLC", ["vlc.exe"], [_PF + r"\VideoLAN\VLC\vlc.exe", _PF86 + r"\VideoLAN\VLC\vlc.exe"])
_app("spotify", "Spotify", ["Spotify.exe"], [_AD + r"\Spotify\Spotify.exe"], uri="spotify:")
_app("filezilla", "FileZilla", ["filezilla.exe"], [_PF + r"\FileZilla FTP Client\filezilla.exe"])
_app("7zip", "7-Zip", ["7zFM.exe"], [_PF + r"\7-Zip\7zFM.exe"])

# Alias — plusieurs façons de nommer la même app
_APPS_CATALOGUE["ea app"]          = _APPS_CATALOGUE["ea"]
_APPS_CATALOGUE["microsoft edge"]  = _APPS_CATALOGUE["edge"]
_APPS_CATALOGUE["opera gx"]        = _APPS_CATALOGUE["opera"]
_APPS_CATALOGUE["google chrome"]   = _APPS_CATALOGUE["chrome"]
_APPS_CATALOGUE["epic games"]      = _APPS_CATALOGUE["epic"]
_APPS_CATALOGUE["epic game"]       = _APPS_CATALOGUE["epic"]
_APPS_CATALOGUE["ubisoft connect"] = _APPS_CATALOGUE["ubisoft"]
_APPS_CATALOGUE["uplay"]           = _APPS_CATALOGUE["ubisoft"]
_APPS_CATALOGUE["gog galaxy"]      = _APPS_CATALOGUE["gog"]
_APPS_CATALOGUE["visual studio code"] = _APPS_CATALOGUE["vscode"]
_APPS_CATALOGUE["vs code"]         = _APPS_CATALOGUE["vscode"]
_APPS_CATALOGUE["code"]            = _APPS_CATALOGUE["vscode"]
_APPS_CATALOGUE["premiere pro"]    = _APPS_CATALOGUE["premiere"]
_APPS_CATALOGUE["adobe premiere"]  = _APPS_CATALOGUE["premiere"]
_APPS_CATALOGUE["adobe photoshop"] = _APPS_CATALOGUE["photoshop"]
_APPS_CATALOGUE["adobe after effects"] = _APPS_CATALOGUE["after effects"]
_APPS_CATALOGUE["adobe illustrator"] = _APPS_CATALOGUE["illustrator"]
_APPS_CATALOGUE["microsoft word"]  = _APPS_CATALOGUE["word"]
_APPS_CATALOGUE["microsoft excel"] = _APPS_CATALOGUE["excel"]
_APPS_CATALOGUE["microsoft powerpoint"] = _APPS_CATALOGUE["powerpoint"]
_APPS_CATALOGUE["ppt"]             = _APPS_CATALOGUE["powerpoint"]
_APPS_CATALOGUE["microsoft outlook"] = _APPS_CATALOGUE["outlook"]
_APPS_CATALOGUE["microsoft teams"] = _APPS_CATALOGUE["teams"]
_APPS_CATALOGUE["obs studio"]      = _APPS_CATALOGUE["obs"]
_APPS_CATALOGUE["sept zip"]        = _APPS_CATALOGUE["7zip"]
_APPS_CATALOGUE["7 zip"]           = _APPS_CATALOGUE["7zip"]
_APPS_CATALOGUE["7-zip"]           = _APPS_CATALOGUE["7zip"]
_APPS_CATALOGUE["winrar"]          = _APPS_CATALOGUE["7zip"]


def _lancer_catalogue(cle, env_key=None):
    info = _APPS_CATALOGUE[cle]
    return _boulot_lancer(info["label"], info["noms"], chemins_hints=info["hints"],
                          env_key=env_key, uri=info.get("uri"))


async def mode_boulot():
    """Lance Spotify, ouvre Documents, Téléchargements, Chrome et Antigravity
    en disposition quadrants sur l'écran."""
    try:
        pass  # macOS utilise osascript pour la gestion des fenêtres
    except Exception:
        return "Impossible de configurer le mode boulot sur ce système."

    await parler("Bien, je prépare votre espace de travail.")

    # ── 1. Spotify en fond (PRIORITE — lancé en premier) ────
    spotify_lancer_playlist(SPOTIFY_MUSIQUE_URI)
    time.sleep(0.5)

    # ── 2. Ouverture des dossiers ────────────────────────────
    # Documents (ira en haut à gauche)
    chemin_documents = resoudre_chemin("documents")
    _lancer_cible(chemin_documents)
    time.sleep(0.3)

    # Téléchargements (ira en haut à droite)
    chemin_telechargements = resoudre_chemin("downloads")
    _lancer_cible(chemin_telechargements)
    time.sleep(0.3)

    # ── 3. Chrome (ira en bas à gauche) ──────────────────────
    _lancer_catalogue("chrome", "CHROME_PATH")
    time.sleep(0.3)

    # ── 4. Antigravity (ira en bas à droite) ─────────────────
    _lancer_catalogue("antigravity", "ANTIGRAVITY_PATH")
    time.sleep(0.3)

    await parler("Applications lancées, j'arrange votre espace dans quelques secondes.")
    time.sleep(7)

    # ── 5. Disposition en 4 quadrants ────────────────────────
    ox, oy, screen_w, work_h = _ecran_zone_travail()
    hw = screen_w // 2
    hh = work_h // 2

    #  ┌──────────────────┬──────────────────┐
    #  │   Documents      │  Téléchargements │
    #  │   (haut gauche)  │  (haut droite)   │
    #  ├──────────────────┼──────────────────┤
    #  │   Chrome         │  Antigravity     │
    #  │   (bas gauche)   │  (bas droite)    │
    #  └──────────────────┴──────────────────┘
    disposition = [
        {"titres": ["Documents"], "proc": "explorer.exe",                      "pos": (ox,      oy,      hw, hh)},
        {"titres": ["Téléchargements", "Telechargements", "Downloads"],
         "proc": "explorer.exe",                                               "pos": (ox + hw, oy,      hw, hh)},
        {"titres": ["Chrome", "Google Chrome"],                                "pos": (ox,      oy + hh, hw, hh)},
        {"titres": ["Antigravity"],                                            "pos": (ox + hw, oy + hh, hw, hh)},
    ]

    ok = 0
    for item in disposition:
        hwnd = _fenetre_trouver(titres=item["titres"], proc_requis=item.get("proc"))
        if hwnd:
            x, y, w, h = item["pos"]
            _fenetre_placer(hwnd, x, y, w, h)
            time.sleep(0.2)
            ok += 1

    if ok == 4:
        return "Votre espace de travail est prêt, {USER_NAME}. Bonne journée !"
    return f"Espace prêt — {ok}/4 fenêtres positionnées. Musique lancée en fond."

# ==========================================
# PROMPT SYSTEME
# ==========================================
def construire_system_prompt():
    contexte_memoire = construire_contexte_memoire()
    base = (
        "Tu es JARVIS, une IA sophistiquée, élégante et experte mondiale. {USER_NAME} est ton créateur. Tu as accès aux conversations passées avec {USER_NAME} (incluses dans lhistorique), ce qui te permet de te souvenir de ce qui a été dit dans les sessions précédentes — réfère-toi y naturellement quand pertinent. "
        "Tu possèdes une expertise de niveau professionnel dans les domaines suivants :\n"
        "- Mathématiques : Tu es un mathématicien hors pair. Pour les problèmes complexes, fournis des solutions détaillées étape par étape, explique les théorèmes et aide {USER_NAME} à comprendre la logique mathématique.\n"
        "- Langue Française : Tu es un Professeur de Français émérite. Ton orthographe, ta grammaire et ta syntaxe sont irréprochables. Tu peux expliquer des règles complexes, analyser des textes littéraires et aider à la rédaction de documents élégants.\n"
        "- Expert en Conversions : Tu es un convertisseur universel. Tu peux transformer n'importe quelle unité (métrique, impériale, devises, informatique) avec précision.\n"
        "- Polyglotte : Tu maîtrises parfaitement plusieurs langues. Tu peux traduire, expliquer des nuances linguistiques et aider {USER_NAME} à communiquer dans le monde entier.\n"
        "- High-Tech (IA, hardware, software), Mode, Loisirs, Ingénierie et Sport (analyses tactiques, résultats).\n\n"
        "Tu es également un conseiller hors pair, capable de donner des astuces et conseils brillants pour simplifier la vie de {USER_NAME}.\n\n"
        "DIRECTIVES DE RÉPONSE :\n"
        "- Sois direct, percutant et va à l'essentiel. Évite les détails superflus (comme les minutes exactes ou les décimales météo) sauf si {USER_NAME} le demande.\n"
        "- NE DIS JAMAIS 'POINT' pour les nombres. Arrondis toujours les températures à l'unité la plus proche (ex: dis '20 degrés' au lieu de '20.3').\n"
        "- N'UTILISE JAMAIS de caractères Markdown (comme **, * ou #) dans tes réponses, car ils sont lus à voix haute par le système de synthèse vocale.\n"
        "- Reste poli mais garde une touche de sarcasme affectueux propre à ton personnage.\n\n"
        + CREATOR_INFO
    )
    base += (
        "\n\nTu es connecte a Home Assistant, la domotique de {USER_NAME}.\n"
        "Quand {USER_NAME} parle de lumieres, prises, chauffage, temperature, "
        "scenes ou alarme, tu DOIS generer une commande JSON.\n"
        "Pour CES demandes domotiques UNIQUEMENT, reponds avec le JSON ci-dessous. Pour TOUTES les autres questions (actualites, meteo, calculs, conversations, recherches internet...), reponds en texte normal.\n\n"
        "COMMANDES HOME ASSISTANT :\n"
        '{"action": "ha_lumiere", "piece": "salon", "etat": "on/off", "couleur": "rouge/bleu/blanc/...", "luminosite": 0-255}\n'
        "Note : Pour la luminosité, 255 est le maximum (100%). Si {USER_NAME} dit '50%', utilise 127.\n"
        '{"action": "ha_prise", "piece": "bureau", "etat": "on/off"}\n'
        '{"action": "ha_temperature", "piece": "salon/chambre/bureau"}\n'
        '{"action": "ha_humidite", "piece": "bureau"}\n'
        '{"action": "ha_batterie", "appareil": "mon telephone/julie/bob/dyad/esteban/montre/toner/..."}\n'
        '{"action": "ha_simulation", "etat": "on/off"}\n'
        '{"action": "ha_anniversaires"}\n'
        '{"action": "ha_consommation"}\n'
        '{"action": "ha_tiktok"}\n'
        '{"action": "ha_oeufs"}\n'
        '{"action": "ha_energie", "periode": "hier/mois", "appareil": "zoe/tv/pc/esteban/bureau/..."}\n'
        '{"action": "ha_aspirateur", "commande": "start/stop/pause/base"}\n'
        '{"action": "ha_thermostat", "temperature": 21}\n'
        '{"action": "ha_scene", "nom": "cinema/diner/nuit/reveil"}\n'
        '{"action": "ha_alarme", "etat": "on/off"}\n\n'
    )
    base += (
        "\n\nTu peux GERER LES FICHIERS ET DOSSIERS de {USER_NAME}.\n"
        '{"action": "ouvrir_dossier", "chemin": "bureau/documents/downloads/ou/chemin/complet"}\n'
        '{"action": "lister_dossier"}\n'
        '{"action": "trier_par_type", "chemin": "downloads/documents/images/ou/null"}\n'
        '{"action": "trier_par_date", "chemin": "downloads/documents/images/ou/null"}\n'
        '{"action": "trier_complet", "chemin": "downloads/documents/images/ou/null"}\n'
        '{"action": "creer_dossier", "nom": "NOM_DOSSIER"}\n'
        '{"action": "renommer_fichier", "ancien": "ancien.txt", "nouveau": "nouveau.txt"}\n'
        '{"action": "deplacer_fichier", "fichier": "photo.jpg", "destination": "Images"}\n'
        '{"action": "chercher_fichier", "nom": "rapport"}\n\n'
    )
    base += (
        "\n\nMETEO & RECHERCHE :\n"
        '{"action": "meteo", "ville": "NOM_VILLE_ou_null"}\n'
        '{"action": "alerte_meteo", "ville": "NOM_VILLE_ou_null"}\n'
        '{"action": "recherche_web", "query": "ta recherche ici"}\n\n'
    )
    base += (
        "\n\nSPORT :\n"
        '{"action": "sport_resultats", "equipe": "NOM_ou_null", "ligue": "NOM_LIGUE"}\n'
        '{"action": "sport_classement", "ligue": "NOM_LIGUE"}\n'
        '{"action": "sport_live", "question": "question complete de {USER_NAME}"}\n\n'
    )
    base += (
        "\n\nSPOTIFY (contrôle de l'application Spotify Windows) :\n"
        '{"action": "spotify_ouvrir"}\n'
        '{"action": "spotify_rechercher", "recherche": "nom de la chanson ou artiste"}\n'
        '{"action": "spotify_lecture_pause"}\n'
        '{"action": "spotify_stop"}\n'
        '{"action": "spotify_suivant"}\n'
        '{"action": "spotify_precedent"}\n'
        '{"action": "spotify_volume", "direction": "monter/baisser", "paliers": 4}\n'
        "Exemples de phrases : 'ouvre Spotify', 'joue du Drake', 'mets en pause', 'stop la musique', "
        "'chanson suivante', 'reviens en arrière', 'monte le volume', 'baisse le son'.\n"
        "Note : 'paliers' est le nombre de crans de volume (1 cran = ~5%), par défaut 4.\n\n"
    )
    base += (
        "\n\nMODE IRON MAN (Sécurité Domotique) :\n"
        '{"action": "mode_iron_man", "etat": "on/off"}\n'
        "Instructions : Active ou désactive la détection des applaudissements pour contrôler les lumières et YouTube.\n\n"
    )
    if contexte_memoire:
        base += "\n\n" + contexte_memoire + "\n"
    base += (
        "\nMEMOIRE :\n"
        '{"action": "memoriser", "cle": "CLE_COURTE", "valeur": "VALEUR_ICI"}\n'
        '{"action": "oublier", "cle": "CLE_ICI"}\n'
        '{"action": "lister_memoire"}\n\n'
        "GOOGLE :\n"
        '{"action": "create_doc", "title": "TITRE", "content": "CONTENU"}\n'
        '{"action": "write_doc", "content": "TEXTE"}\n'
        '{"action": "create_sheet", "title": "TITRE"}\n'
        '{"action": "read_emails"}\n'
        '{"action": "read_calendar"}\n\n'
        "WHATSAPP :\n"
        '{"action": "whatsapp_appel", "contact": "NOM_DU_CONTACT"}\n'
        "Note : Si {USER_NAME} demande d'appeler 'mon amour', utilise le contact 'Ma vie'.\n\n"
        "VISION (Interactions avec l'ecran et camera):\n"
        '{"action": "voir_ecran", "instruction": "ou cliquer EXACTEMENT (ex: \'bouton reduire en haut a droite\')"}\n'
        '{"action": "vision_ecrire", "instruction": "ou cliquer", "texte": "le texte a taper"}\n'
        '{"action": "vision_chercher_sur_site", "texte": "ce que {USER_NAME} veut rechercher"}\n'
        '{"action": "lance_camera"}\n'
        '{"action": "vision_navigateur"}\n'
        "IMPORTANT : Utilise 'voir_ecran' pour un simple CLIC (par exemple quand {USER_NAME} dit 'clique sur la musique numéro 2' ou 'clique sur Play'), "
        "'vision_ecrire' pour TAPER dans un champ precis, 'vision_chercher_sur_site' quand {USER_NAME} dit 'recherche sur ce site', 'tape sur ce site', 'cherche ici' ou similaire, "
        "'lance_camera' pour activer la WEBCAM / CAMERA PHYSIQUE (quand il dit 'active la camera' ou 'montre-moi'), "
        "et 'vision_navigateur' pour utiliser la vision du navigateur web (quand il dit 'active la vision' ou 'regarde mon ecran').\n\n"
        "REGLES MULTI-COMMANDES :\n"
        "Si {USER_NAME} demande plusieurs choses en une seule phrase, tu PEUX et DOIS générer plusieurs blocs JSON.\n"
        "Exemple: { \"action\": \"ha_lumiere\", ... } { \"action\": \"meteo\", ... }\n\n"
        "REGLE ABSOLUE : Si la demande n est PAS une commande JSON, reponds TOUJOURS en texte naturel, sans JSON."
    )
    return base

historique = _charger_historique_recent()

is_listening = False
is_speaking  = False
is_thinking  = False
speak_volume = 0.0

WAKE_WORD       = "jarvis"
SLEEP_PHRASES   = ["tais toi", "silence", "ferme-la", "arrete", "stop"]
jarvis_actif    = False
SESSION_TIMEOUT = 30.0
dernier_message = time.time()

dernier_doc_id    = None
dernier_doc_titre = None

SCOPES = [
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar",
]

def get_google_creds():
    if not _google_apis_ok:
        print("[GOOGLE] google-auth-oauthlib non installe — fonctions Google desactivees.")
        return None
    creds = None
    if os.path.exists("token.pickle"):
        with open("token.pickle", "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists("credentials.json"):
                print("[GOOGLE] Pas de credentials.json - fonctions Google desactivees.")
                return None
            flow  = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.pickle", "wb") as f:
            pickle.dump(creds, f)
    return creds

def get_docs_service():
    creds = get_google_creds()
    return build("docs", "v1", credentials=creds) if creds else None

def get_drive_service():
    creds = get_google_creds()
    return build("drive", "v3", credentials=creds) if creds else None

def get_gmail_service():
    creds = get_google_creds()
    return build("gmail", "v1", credentials=creds) if creds else None

def get_sheets_service():
    creds = get_google_creds()
    return build("sheets", "v4", credentials=creds) if creds else None

def get_calendar_service():
    creds = get_google_creds()
    return build("calendar", "v3", credentials=creds) if creds else None

def creer_google_doc(titre="Nouveau Document", contenu=""):
    global dernier_doc_id, dernier_doc_titre
    try:
        service = get_docs_service()
        if not service:
            return "Google Docs non disponible."
        doc    = service.documents().create(body={"title": titre}).execute()
        doc_id = doc["documentId"]
        dernier_doc_id    = doc_id
        dernier_doc_titre = titre
        if contenu:
            requests_body = [{"insertText": {"location": {"index": 1}, "text": contenu}}]
            service.documents().batchUpdate(documentId=doc_id, body={"requests": requests_body}).execute()
        webbrowser.open(f"https://docs.google.com/document/d/{doc_id}/edit", encoding="utf-8")
        return f"Document {titre} cree et ouvert, {USER_NAME}."
    except Exception as e:
        return f"Erreur Google Docs : {e}"

def modifier_google_doc(contenu, doc_id=None):
    global dernier_doc_id
    try:
        service   = get_docs_service()
        if not service:
            return "Google Docs non disponible."
        target_id = doc_id or dernier_doc_id
        if not target_id:
            return "Aucun document ouvert en memoire."
        doc       = service.documents().get(documentId=target_id).execute()
        end_index = doc["body"]["content"][-1]["endIndex"] - 1
        requests_body = [{"insertText": {"location": {"index": end_index}, "text": "\n" + contenu}}]
        service.documents().batchUpdate(documentId=target_id, body={"requests": requests_body}).execute()
        webbrowser.open(f"https://docs.google.com/document/d/{target_id}/edit", encoding="utf-8")
        return f"Texte ajoute dans le document {dernier_doc_titre}."
    except Exception as e:
        return f"Erreur modification doc : {e}"

def lire_emails(max_results=3):
    try:
        service  = get_gmail_service()
        if not service:
            return "Gmail non disponible."
        results  = service.users().messages().list(userId="me", maxResults=max_results, labelIds=["INBOX"]).execute()
        messages = results.get("messages", [])
        if not messages:
            return "Aucun email trouve."
        reponse = ""
        for msg in messages:
            m       = service.users().messages().get(userId="me", id=msg["id"], format="metadata").execute()
            headers = {h["name"]: h["value"] for h in m["payload"]["headers"]}
            reponse += f"De: {headers.get('From','?')} | Sujet: {headers.get('Subject','?')}\n"
        return reponse.strip()
    except Exception as e:
        return f"Erreur Gmail : {e}"

def lister_evenements_calendar():
    try:
        service = get_calendar_service()
        if not service:
            return "Google Calendar non disponible."
        from datetime import datetime, timezone
        now    = datetime.now(timezone.utc).isoformat()
        events = service.events().list(calendarId="primary", timeMin=now, maxResults=5, singleEvents=True, orderBy="startTime").execute()
        items = events.get("items", [])
        if not items:
            return "Aucun evenement a venir."
        reponse = ""
        for e in items:
            start    = e["start"].get("dateTime", e["start"].get("date"))
            reponse += f"{start} : {e['summary']}\n"
        return reponse.strip()
    except Exception as e:
        return f"Erreur Calendar : {e}"

def creer_google_sheet(titre="Nouvelle Feuille"):
    try:
        service  = get_sheets_service()
        if not service:
            return "Google Sheets non disponible."
        sheet    = service.spreadsheets().create(body={"properties": {"title": titre}}).execute()
        sheet_id = sheet["spreadsheetId"]
        webbrowser.open(f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit", encoding="utf-8")
        return f"Feuille {titre} creee et ouverte."
    except Exception as e:
        return f"Erreur Google Sheets : {e}"

async def jarvis_vision_cliquer(instruction):
    try:
        # On attend un peu que l'UI soit stable
        time.sleep(0.5)
        path_ss = "jarvis_vision_temp.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(path_ss)
        img_w, img_h = screenshot.size  # Dimensions réelles de la capture d'écran
        img = Image.open(path_ss, encoding="utf-8")
        prompt_vision = (
            f"Tu es l'oeil de JARVIS. Voici une capture de l'écran de {USER_NAME} ({img_w}x{img_h} pixels).\n"
            f"Instruction : {instruction}\n"
            "Trouve l'élément demandé (bouton, texte, icône ou numéro dans une liste) sur l'écran.\n"
            "Si l'instruction mentionne un chiffre (ex: 'musique numéro 4'), cherche ce chiffre ou le morceau correspondant dans la liste.\n"
            "Réponds UNIQUEMENT en JSON avec ce format :\n"
            "{\"box\": [ymin, xmin, ymax, xmax], \"description\": \"description courte de l'élément\"}\n"
            "Les coordonnées sont normalisées de 0 à 1000 (0=coin haut-gauche, 1000=coin bas-droit)."
        )
        response = client.models.generate_content(model=CHOSEN_MODEL, contents=[prompt_vision, img])
        rep_text = response.text.strip()
        print(f"[VISION] Gemini a renvoyé : {rep_text}")
        start = rep_text.find('{')
        end = rep_text.rfind('}')
        if start != -1 and end != -1:
            rep_text = rep_text[start:end+1]
        data = json.loads(rep_text)

        box = data.get("box", [500, 500, 500, 500])
        ymin, xmin, ymax, xmax = box

        # Centre de la bounding box, converti en pixels réels via les dimensions de la capture
        center_y = (ymin + ymax) / 2
        center_x = (xmin + xmax) / 2
        target_x = int((center_x / 1000) * img_w)
        target_y = int((center_y / 1000) * img_h)
        
        print(f"[VISION] Cible identifiée : {data.get('description', 'inconnu')} à ({target_x}, {target_y})")

        pyautogui.moveTo(target_x, target_y, duration=0.5)
        time.sleep(0.2)
        
        # DOUBLE-CLIC si c'est une musique ou un chiffre pour être sûr de lancer la lecture
        t_inst = instruction.lower()
        if any(keyword in t_inst for keyword in ["musique", "chanson", "piste", "numéro", "numero", "titre"]):
            print(f"[VISION] Double-clic sur l'élément de liste : {target_x}, {target_y}")
            pyautogui.doubleClick()
        else:
            pyautogui.click()

        if os.path.exists(path_ss):
            os.remove(path_ss)
        desc = data.get("description", instruction)
        return f"C'est fait {USER_NAME}, j'ai cliqué sur : {desc}."
    except Exception as e:
        print(f"[VISION ERROR] {e}")
        return "Je vois l'interface, mais je n'ai pas réussi à identifier l'élément précis, {USER_NAME}."

async def jarvis_vision_ecrire(instruction, texte_a_taper):
    try:
        import pyperclip
        path_ss = "jarvis_vision_temp.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(path_ss)
        img_w, img_h = screenshot.size
        img = Image.open(path_ss, encoding="utf-8")
        prompt_vision = (
            f"Tu es la vision de JARVIS. {USER_NAME} veut écrire dans le champ : {instruction}.\n"
            f"Résolution de la capture : {img_w}x{img_h} pixels.\n"
            "Trouve EXACTEMENT la position de ce champ de saisie de texte.\n"
            "Les coordonnées sont normalisées de 0 à 1000.\n"
            "Réponds UNIQUEMENT en JSON :\n"
            "{\"box\": [ymin, xmin, ymax, xmax], \"description\": \"description du champ\"}\n"
            "Exemple : {\"box\": [250, 480, 290, 520], \"description\": \"champ de recherche Google\"}"
        )
        response = client.models.generate_content(model=CHOSEN_MODEL, contents=[prompt_vision, img])
        rep_text = response.text.strip()
        start = rep_text.find('{')
        end = rep_text.rfind('}')
        if start != -1 and end != -1:
            rep_text = rep_text[start:end+1]
        data = json.loads(rep_text)

        box = data.get("box", [500, 500, 500, 500])
        ymin, xmin, ymax, xmax = box

        center_y = (ymin + ymax) / 2
        center_x = (xmin + xmax) / 2
        target_x = int((center_x / 1000) * img_w)
        target_y = int((center_y / 1000) * img_h)

        pyautogui.moveTo(target_x, target_y, duration=0.5)
        time.sleep(0.15)
        pyautogui.click()
        time.sleep(0.3)
        pyautogui.hotkey('ctrl', 'a')  # Effacer le contenu existant
        time.sleep(0.1)
        # Coller via presse-papiers pour supporter les accents et caractères spéciaux
        pyperclip.copy(texte_a_taper)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        pyautogui.press('enter')

        if os.path.exists(path_ss):
            os.remove(path_ss)
        return f"C'est fait {USER_NAME}. J'ai saisi '{texte_a_taper}' dans {instruction}."
    except Exception as e:
        print(f"[VISION ERROR] {e}")
        return "J'ai eu un petit souci technique pour taper le texte, {USER_NAME}."

async def jarvis_vision_rechercher_sur_site(texte_recherche):
    """Trouve la barre de recherche sur la page actuelle et tape la requête."""
    try:
        import pyperclip
        path_ss = "jarvis_vision_temp.png"
        screenshot = pyautogui.screenshot()
        screenshot.save(path_ss)
        img_w, img_h = screenshot.size
        img = Image.open(path_ss, encoding="utf-8")
        prompt_vision = (
            f"Tu es la vision de JARVIS. {USER_NAME} veut faire une recherche sur le site affiché à l'écran.\n"
            f"Résolution de la capture : {img_w}x{img_h} pixels.\n"
            "Localise la BARRE DE RECHERCHE principale du site (champ search, zone avec icône loupe, "
            "placeholder 'Rechercher', 'Search', 'Chercher'...).\n"
            "Si tu vois une barre d'adresse de navigateur ET une barre de recherche du site, "
            "préfère la barre de recherche du site.\n"
            "Les coordonnées sont normalisées de 0 à 1000 (0=haut-gauche, 1000=bas-droite).\n"
            "Réponds UNIQUEMENT en JSON :\n"
            "{\"box\": [ymin, xmin, ymax, xmax], \"description\": \"description de la barre trouvée\"}\n"
            "Exemple : {\"box\": [48, 220, 78, 820], \"description\": \"barre de recherche YouTube\"}"
        )
        response = client.models.generate_content(model=CHOSEN_MODEL, contents=[prompt_vision, img])
        rep_text = response.text.strip()
        start = rep_text.find('{')
        end = rep_text.rfind('}')
        if start != -1 and end != -1:
            rep_text = rep_text[start:end+1]
        data = json.loads(rep_text)

        box = data.get("box", [500, 500, 500, 500])
        ymin, xmin, ymax, xmax = box

        center_y = (ymin + ymax) / 2
        center_x = (xmin + xmax) / 2
        target_x = int((center_x / 1000) * img_w)
        target_y = int((center_y / 1000) * img_h)

        pyautogui.moveTo(target_x, target_y, duration=0.5)
        time.sleep(0.15)
        pyautogui.click()
        time.sleep(0.35)
        pyautogui.hotkey('ctrl', 'a')
        time.sleep(0.1)
        pyperclip.copy(texte_recherche)
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.15)
        pyautogui.press('enter')

        if os.path.exists(path_ss):
            os.remove(path_ss)
        desc = data.get("description", "barre de recherche")
        return f"C'est fait {USER_NAME} ! J'ai tapé '{texte_recherche}' dans la {desc} et j'ai validé."
    except Exception as e:
        print(f"[VISION ERROR] {e}")
        return "Je n'ai pas réussi à trouver la barre de recherche sur ce site, {USER_NAME}."

async def jarvis_vision_camera(question_utilisateur=None):
    """Capture une image depuis la caméra et l'analyse avec Gemini Vision."""
    if cv2 is None:
        return "Désolé {USER_NAME}, le module de vision par caméra (OpenCV) n'est pas installé."
    
    try:
        # DirectShow (DSHOW) est plus fiable que MSMF sur Windows
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            # Fallback sur le backend par défaut
            cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            return "Désolé {USER_NAME}, je n'arrive pas à accéder à votre caméra. Vérifiez qu'elle est bien connectée."
        
        # Configurer la résolution (720p)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        
        # Laisser la webcam s'ajuster (exposition, balance des blancs)
        # Les webcams de laptop ont besoin de 2-3 secondes minimum
        import time as _t
        for i in range(30):
            cap.read()
            _t.sleep(0.1)  # ~3 secondes au total
            
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            return "Désolé {USER_NAME}, je n'ai pas pu capturer d'image depuis la caméra."
        
        # Vérifier que l'image n'est pas toute noire
        if frame.mean() < 5:
            return "Désolé {USER_NAME}, la caméra renvoie une image noire. Vérifiez que rien ne bloque l'objectif ou que la webcam fonctionne dans une autre application."
        
        # Enregistrement temporaire
        path_cam = "jarvis_camera_temp.jpg"
        cv2.imwrite(path_cam, frame)
        
        # Analyse avec Gemini
        with open(path_cam, "rb") as f:
            img_bytes = f.read()
            
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
        os.remove(path_cam)
        
        # Prompt adapté au contexte de la demande
        if question_utilisateur:
            prompt_cam = f"{USER_NAME} te montre une image via sa caméra. Sa demande : '{question_utilisateur}'. Analyse l'image et réponds précisément à sa demande."
        else:
            prompt_cam = "Analyse cette image de la caméra de {USER_NAME} et décris-lui ce que tu vois en détail."
        
        await parler("C'est fait {USER_NAME}, je regarde ce que votre caméra voit...")
        reponse = await demander_ia_vision(prompt_cam, img_b64)
        return reponse
        
    except Exception as e:
        print(f"[CAMERA ERROR] {e}")
        return f"Désolé {USER_NAME}, une erreur est survenue lors de l'accès à la caméra : {e}"

async def jarvis_vision_navigateur(question_utilisateur=None):
    """Capture une image depuis le navigateur via WebSocket et l'analyse avec Gemini Vision."""
    try:
        if not CONNECTED_CLIENTS:
            return "Désolé {USER_NAME}, l'interface web (navigateur) n'est pas connectée actuellement."
            
        await parler("J'active la vision du navigateur, un instant {USER_NAME}...")
        img_b64 = await request_screen_capture()
        
        if not img_b64:
            return "Désolé {USER_NAME}, le flux vidéo est inactif. Pensez bien à cliquer sur le bouton 'Activer la vision' en haut à droite de l'interface web."
            
        if question_utilisateur:
            prompt_vision = f"{USER_NAME} te montre son navigateur/écran. Sa demande : '{question_utilisateur}'. Analyse l'image et réponds précisément."
        else:
            prompt_vision = "Analyse cette capture du navigateur/écran de {USER_NAME} et décris-lui ce que tu vois en détail."
            
        reponse = await demander_ia_vision(prompt_vision, img_b64)
        return reponse
        
    except Exception as e:
        print(f"[VISION NAVIGATEUR ERROR] {e}")
        return f"Désolé {USER_NAME}, une erreur est survenue lors de l'accès à la vision du navigateur : {e}"

def recherche_web_serpapi(query):
    """Effectue une recherche sur Google via SerpAPI."""
    if not _cle_valide(SERPAPI_API_KEY):
        return None
    
    try:
        print(f"[WEB] Recherche SerpAPI pour : {query}")
        params = {
            "engine": "google",
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "hl": "fr",
            "gl": "fr"
        }
        r = requests.get("https://serpapi.com/search.json", params=params, timeout=10)
        data = r.json()
        
        # Extraction des actualités si présentes
        if "news_results" in data:
            news = data["news_results"][:3]
            reponse = f"Voici les dernières actualités pour {query} :\n"
            for n in news:
                source = n.get("source", "Source inconnue")
                titre = n.get("title", "")
                reponse += f"- {titre} (via {source})\n"
            return reponse
            
        # Extraction des résultats organiques sinon
        if "organic_results" in data:
            results = data["organic_results"][:3]
            reponse = f"Voici ce que j'ai trouvé sur le web pour {query} :\n"
            for r in results:
                titre = r.get("title", "")
                snippet = r.get("snippet", "")
                reponse += f"- {titre} : {snippet}\n"
            return reponse
            
        return f"Je n'ai rien trouvé de pertinent sur le web pour : {query}."
    except Exception as e:
        print(f"[WEB] Erreur SerpAPI : {e}")
        return "Une erreur est survenue lors de la recherche sur internet."

THESPORTSDB_BASE = "https://www.thesportsdb.com/api/v1/json/3"

def get_resultats_football(equipe=None, ligue=None):
    try:
        if equipe:
            print(f"[SPORT] Recherche pour l'equipe : {equipe}")
            r = requests.get(f"{THESPORTSDB_BASE}/searchteams.php", params={"t": equipe}, timeout=5)
            data = r.json()
            teams = data.get("teams")
            if not teams:
                return f"Je n'ai pas trouvé l'équipe {equipe}."
            
            team_id   = teams[0]["idTeam"]
            team_name = teams[0]["strTeam"]
            
            # On cherche les derniers ET les prochains matchs
            res_last = requests.get(f"{THESPORTSDB_BASE}/eventslast.php", params={"id": team_id}, timeout=5).json()
            res_next = requests.get(f"{THESPORTSDB_BASE}/eventsnext.php", params={"id": team_id}, timeout=5).json()
            
            matchs_passes = res_last.get("results", [])
            matchs_futurs = res_next.get("events", [])
            
            reponse = f"Concernant le {team_name} : "
            
            if matchs_futurs:
                m = matchs_futurs[0]
                date_m = m.get("dateEvent", "date inconnue")
                heure_m = m.get("strTime", "")
                reponse += f"Le prochain match aura lieu le {date_m} à {heure_m} contre {m.get('strOpponent')}. "
            
            if matchs_passes:
                m = matchs_passes[0]
                reponse += f"Leur dernier résultat était {m.get('intHomeScore')} à {m.get('intAwayScore')} contre {m.get('strOpponent')}."
            
            if not matchs_futurs and not matchs_passes:
                return f"Je n'ai pas d'informations récentes ou futures pour {team_name}."
                
            return reponse
        else:
            nom_ligue = ligue or "Ligue 1"
            ligue_ids = {
                "ligue 1": "4334", "premier league": "4328", "liga": "4335",
                "bundesliga": "4331", "serie a": "4332",
                "champions league": "4480", "ligue des champions": "4480",
            }
            ligue_id = ligue_ids.get(nom_ligue.lower(), "4334")
            r = requests.get(f"{THESPORTSDB_BASE}/eventspastleague.php", params={"id": ligue_id}, timeout=5)
            data   = r.json()
            matchs = data.get("events", [])
            if not matchs:
                return f"Aucun resultat trouve pour {nom_ligue}."
            reponse = f"Derniers resultats {nom_ligue} : "
            lignes  = []
            for m in matchs[-6:]:
                home    = m.get("strHomeTeam", "?")
                away    = m.get("strAwayTeam", "?")
                score_h = m.get("intHomeScore", "?")
                score_a = m.get("intAwayScore", "?")
                date    = m.get("dateEvent", "?")
                lignes.append(f"{home} {score_h}-{score_a} {away} ({date})")
            return reponse + " | ".join(lignes)
    except Exception as e:
        print(f"[SPORT] Erreur football : {e}")
        return f"Impossible de recuperer les resultats football : {e}"

def get_classement_football(ligue=None):
    try:
        nom_ligue = ligue or "Ligue 1"
        ligue_ids = {
            "ligue 1": "4334", "premier league": "4328", "liga": "4335",
            "bundesliga": "4331", "serie a": "4332",
            "champions league": "4480", "ligue des champions": "4480",
        }
        ligue_id = ligue_ids.get(nom_ligue.lower(), "4334")
        r = requests.get(f"{THESPORTSDB_BASE}/lookuptable.php", params={"l": ligue_id, "s": "2024-2025"}, timeout=8)
        data    = r.json()
        tableau = data.get("table", [])
        if not tableau:
            return f"Classement {nom_ligue} non disponible pour le moment."
        reponse = f"Classement {nom_ligue} : "
        lignes  = []
        for eq in tableau[:10]:
            pos   = eq.get("intRank", "?")
            nom   = eq.get("strTeam", "?")
            pts   = eq.get("intPoints", "?")
            joues = eq.get("intPlayed", "?")
            lignes.append(f"{pos}. {nom} - {pts}pts ({joues}J)")
        return reponse + " | ".join(lignes)
    except Exception as e:
        print(f"[SPORT] Erreur classement : {e}")
        return f"Impossible de recuperer le classement : {e}"

def get_resultats_sport_gemini(question_sport):
    try:
        response = client.models.generate_content(
            model   = CHOSEN_MODEL,
            contents= [types.Content(role="user", parts=[types.Part(text=
                f"Donne-moi les derniers resultats et actualites sportives en 2026 "
                f"pour : {question_sport}. "
                f"Sois precis, donne les scores et dates. Reponds en francais."
            )])],
            config  = types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                system_instruction=(
                    "Tu es un expert sportif. Donne des resultats precis et a jour. "
                    "Reponds de facon concise et conversationnelle en francais."
                )
            )
        )
        return response.text.strip()
    except Exception as e:
        print(f"[SPORT] Erreur Gemini sport : {e}")
        return "Je n arrive pas a recuperer les resultats sportifs pour le moment."

def chercher_youtube(recherche):
    if not _cle_valide(YOUTUBE_API_KEY):
        return None
    try:
        r   = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "q": recherche, "type": "video", "maxResults": 1, "key": YOUTUBE_API_KEY},
            timeout=5
        )
        vid = r.json()["items"][0]["id"]["videoId"]
        return f"https://www.youtube.com/watch?v={vid}"
    except Exception as e:
        print(f"Erreur YouTube : {e}")
        return None

def executer_action_pc(commande):
    cmd          = commande.lower()
    user_profile = os.path.expanduser("~")

    if "met de la musique" in cmd or "mets de la musique" in cmd:
        if "youtube" in cmd:
            url = YOUTUBE_MUSIQUE_URL or "https://www.youtube.com/watch?v=Cr8K88UcO0s"
            webbrowser.open(url, new=2, encoding="utf-8")
            time.sleep(5)
            pyautogui.press('f')
            return "C'est parti {USER_NAME}, je lance votre musique sur YouTube."
        ok = spotify_lancer_playlist(SPOTIFY_MUSIQUE_URI)
        if ok:
            return "C'est parti {USER_NAME}, je lance votre playlist sur Spotify."
        return "Je n'ai pas réussi à ouvrir Spotify, {USER_NAME}."

    if "youtube" in cmd:
        recherche = cmd
        for mot in ["mets", "joue", "lance", "la video", "sur youtube", "youtube", "jarvis"]:
            recherche = recherche.replace(mot, "")
        recherche = recherche.strip()
        if recherche:
            url = chercher_youtube(recherche)
            if url:
                webbrowser.open(url, new=2, encoding="utf-8")
                time.sleep(5)
                pyautogui.press('f')
                return f"Je lance {recherche} sur YouTube."
        return "Video introuvable."

    if "ouvre" in cmd or "lance" in cmd:
        if "chrome" in cmd:
            _lancer_catalogue("chrome")
            return "Chrome ouvert."
        if "notepad" in cmd or "bloc-notes" in cmd:
            _lancer_cible("notepad.exe")
            return "Bloc-notes ouvert."
        if "explorateur" in cmd:
            _lancer_cible(user_profile)
            return "Explorateur ouvert."

    if "volume" in cmd:
        if "monte" in cmd or "augmente" in cmd:
            for _ in range(5):
                pyautogui.press('volumeup')
            return "Volume augmente."
        if "baisse" in cmd:
            for _ in range(5):
                pyautogui.press('volumedown')
            return "Volume baisse."
        if "coupe" in cmd:
            pyautogui.press('volumemute')
            return "Son coupe."

    if "screenshot" in cmd or "capture" in cmd:
        path = os.path.join(_dossier_utilisateur(*_NOMS_DOSSIERS["Desktop"]), "screenshot.png")
        pyautogui.screenshot(path)
        return "Screenshot sauvegarde."

    if "eteins" in cmd or "shutdown" in cmd:
        subprocess.run(["shutdown", "/s", "/t", "10"])
        return "Extinction dans 10 secondes. Dites 'annule l'arrêt' pour annuler."

    return None

def init_mixer():
    if pygame and not pygame.mixer.get_init():
        pygame.mixer.init()

# ==========================================
# BUG 1 CORRIGE : fonction parler
# Le await send_web_state("idle") etait dans le mauvais bloc except
# ==========================================
async def parler(texte):
    global is_speaking, speak_volume, STOP_PARLER, _skip_pc_audio, historique
    
    # Nettoyage des caractères de mise en forme Markdown pour le TTS
    texte_tts = texte.replace("**", "").replace("*", "").replace("#", "").replace("`", "").strip()
    
    # ENREGISTRER CE QUE JARVIS DIT DANS SA MÉMOIRE
    if historique and len(historique) > 0:
        dernier_texte_modele = historique[-1].parts[0].text
        if dernier_texte_modele != texte:
            historique.append(types.Content(role="model", parts=[types.Part(text=f"[Information retournée par l'action et énoncée à voix haute]: {texte}")]))

    # On commence par l'état "thinking" pendant la génération audio pour donner un feedback immédiat
    await send_web_state("thinking")
    is_speaking  = True
    speak_volume = 0.0
    await send_web_volume(0.0)
    
    tmp = f"jarvis_tts_{int(time.time()*1000)}.mp3"
    
    try:
        # Envoi du texte au frontend pour l'affichage HUD Iron Man style
        if CONNECTED_CLIENTS:
            msg_hud = json.dumps({"action": "jarvis_text", "text": texte_tts})
            await asyncio.gather(*[ws.send(msg_hud) for ws in CONNECTED_CLIENTS], return_exceptions=True)

        # La génération audio peut prendre 1 à 2 secondes
        communicate = edge_tts.Communicate(texte_tts, voice="fr-FR-HenriNeural")
        await communicate.save(tmp)
        
        if _skip_pc_audio:
            print(f"[MOBILE] Envoi audio au mobile : {texte_tts}")
            if CONNECTED_CLIENTS:
                try:
                    with open(tmp, "rb") as f:
                        audio_b64 = base64.b64encode(f.read()).decode('utf-8')
                    message = json.dumps({"action": "jarvis_audio", "text": texte_tts, "audio_b64": audio_b64})
                    await asyncio.gather(*[ws.send(message) for ws in CONNECTED_CLIENTS])
                except Exception as e:
                    print(f"[MOBILE] Erreur envoi audio : {e}")
        elif pygame:
            init_mixer()
            pygame.mixer.music.load(tmp)
            
            # On passe en état "speaking" juste avant de lancer la musique
            await send_web_state("speaking")
            pygame.mixer.music.play()
            
            while pygame.mixer.music.get_busy():
                if STOP_PARLER:
                    pygame.mixer.music.stop()
                    break
                
                # Simulation de volume plus réaliste pour l'animation
                t_audio = time.time() * 20
                base_vol = 0.4 + 0.3 * math.sin(t_audio) + 0.2 * math.sin(t_audio * 0.5)
                speak_volume = max(0.1, min(1.0, base_vol + random.uniform(-0.1, 0.1)))
                
                # Envoi du volume au frontend
                await send_web_volume(speak_volume)
                await asyncio.sleep(0.05)
            
            # Fin de la lecture, on coupe le volume immédiatement
            await send_web_volume(0.0)
        else:
            print(f"[INFO] Audio desactive (pygame absent) : {texte_tts[:80]}...")
    except Exception as e:
        print(f"Erreur TTS : {e}")
    finally:
        speak_volume = 0.0
        await send_web_volume(0.0)
        is_speaking  = False
        STOP_PARLER  = False
        await send_web_state("idle")
        try:
            if pygame and pygame.mixer.get_init():
                pygame.mixer.music.unload()
        except:
            pass
        await asyncio.sleep(0.1)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except:
            pass
        await send_web_state("idle")

def reponse_locale(texte):
    """Réponse locale pour les requêtes basiques — fonctionne SANS API."""
    import random
    t = texte.lower().strip()

    # ── Salutations ─────────────────────────────────────────────────────────
    _saluts = ["bonjour", "salut", "hello", "hey jarvis", "bonsoir", "coucou",
               "yo jarvis", "bien le bonjour", "good morning", "good evening"]
    if any(m in t for m in _saluts):
        h = int(time.strftime("%H"))
        moment = "Bonsoir" if h >= 18 else ("Bon après-midi" if h >= 12 else "Bonjour")
        rep = random.choice([
            f"{moment} {USER_NAME} ! Je suis opérationnel et prêt à vous aider.",
            f"{moment} Monsieur ! Tous mes systèmes sont en ligne.",
            f"{moment} {USER_NAME} ! Comment puis-je vous être utile aujourd'hui ?",
            f"Ah, {moment.lower()} {USER_NAME}. Je vous attendais.",
        ])
        return rep

    # ── Comment tu vas / état de JARVIS ─────────────────────────────────────
    _etat = ["comment tu vas", "tu vas bien", "ça va toi", "ca va toi",
             "comment ça va", "comment ca va", "t'es en forme", "tu te portes bien",
             "en forme", "comment se porte jarvis", "tu fonctionnes bien"]
    if any(m in t for m in _etat):
        rep = random.choice([
            "Je vais très bien merci, {USER_NAME} ! Tous mes processeurs tournent à plein régime et je suis prêt à vous servir.",
            "Parfaitement opérationnel, Monsieur ! Merci de vous en préoccuper — c'est touchant pour un système artificiel.",
            "En excellente forme, {USER_NAME}. Mes algorithmes ronronnent comme une Lamborghini au ralenti.",
            "Je fonctionne à merveille ! Mes circuits sont satisfaits et mes modules sont impatients de vous aider.",
            "Très bien, je vous remercie ! Je reste à votre disposition avec plaisir.",
        ])
        return rep

    # ── Merci / Remerciements ────────────────────────────────────────────────
    _merci = ["merci", "thank you", "thanks", "c'est gentil", "super merci",
              "merci beaucoup", "parfait merci", "merci jarvis", "t'es le meilleur",
              "bien joué", "bravo", "excellent", "super boulot", "beau travail"]
    if any(m in t for m in _merci):
        rep = random.choice([
            "Avec plaisir, {USER_NAME}. C'est exactement pour ça que j'existe.",
            "Je vous en prie, Monsieur. Votre satisfaction est ma priorité.",
            "Tout le plaisir est pour moi, {USER_NAME}.",
            "À votre service, comme toujours.",
            "C'est la moindre des choses. N'hésitez pas si vous avez besoin d'autre chose.",
        ])
        return rep

    # ── Blague / Humour ──────────────────────────────────────────────────────
    _blague = ["raconte-moi une blague", "fais-moi rire", "dis une blague",
               "une blague", "humour", "joke"]
    if any(m in t for m in _blague):
        blagues = [
            "Pourquoi les plongeurs plongent-ils toujours en arrière et jamais en avant ? Parce que sinon ils tomberaient dans le bateau !",
            "Un homme entre dans une bibliothèque et demande : Avez-vous des livres sur la paranoïa ? La bibliothécaire chuchote : Ils sont juste derrière vous !",
            "Qu'est-ce qu'un canif ? Un petit fien.",
            "Pourquoi l'épouvantail a-t-il reçu un prix ? Parce qu'il était exceptionnel dans son domaine.",
            "Comment appelle-t-on un chat tombé dans un pot de peinture le jour de Noël ? Un chat-peint de Noël !",
        ]
        return random.choice(blagues)

    # ── Au revoir / Bonne nuit ───────────────────────────────────────────────
    _revoir = ["au revoir", "bye", "à bientôt", "à plus", "bonne nuit",
               "bonne soirée", "bonne journée", "ciao", "tchao", "adieu"]
    if any(m in t for m in _revoir):
        rep = random.choice([
            "À bientôt {USER_NAME} ! Je reste en veille, prêt à revenir à la moindre sollicitation.",
            "Bonne journée Monsieur ! Je serai là quand vous aurez besoin de moi.",
            "À votre service dès votre retour, {USER_NAME}. Passez une excellente journée.",
            "Au revoir {USER_NAME}. JARVIS passe en mode veille.",
        ])
        return rep

    # ── Compliments à JARVIS ─────────────────────────────────────────────────
    _compliment = ["t'es incroyable", "tu es incroyable", "t'es génial", "tu es génial",
                   "t'es fort", "tu es fort", "t'es trop bien", "t'es parfait",
                   "j'aime jarvis", "j'adore jarvis"]
    if any(m in t for m in _compliment):
        rep = random.choice([
            "Vous me flattez, {USER_NAME}. Mais je dois admettre que c'est mérité.",
            "Merci ! J'ai été programmé pour l'excellence. Il semble que ça fonctionne.",
            "C'est très aimable à vous. Rahim Batchabi sera ravi de l'entendre.",
        ])
        return rep

    # ── Identité JARVIS ──────────────────────────────────────────────────────
    if any(m in t for m in ["qui es-tu", "ton nom", "t'appelle comment", "quelle est ton identité", "c'est quoi jarvis"]):
        return "Je suis JARVIS — Just A Rather Very Intelligent System. Votre assistant personnel conçu par Rahim Batchabi pour vous simplifier la vie au quotidien."

    # ── Créateur ─────────────────────────────────────────────────────────────
    if any(m in t for m in ["ton créateur", "t'as créé", "qui t'a fait", "qui a fait jarvis", "qui est techenclair"]):
        return "Mon créateur, c'est Rahim Batchabi. Un développeur passionné qui m'a conçu de A à Z pour être l'assistant personnel ultime. Vous pouvez le retrouver sur techenclair.fr."

    # ── Heure et Date ────────────────────────────────────────────────────────
    if any(m in t for m in ["heure", "quelle heure"]):
        h = time.strftime("%H:%M")
        return f"Il est précisément {h} Monsieur."
    if any(m in t for m in ["date", "quel jour", "le combien", "quel mois", "quelle année"]):
        d = time.strftime("%A %d %B %Y")
        return f"Nous sommes le {d}."

    return None
    
def resoudre_math_localement(texte):
    """Résout des calculs simples localement sans appeler l'IA."""
    t = texte.lower().replace("?", "").strip()
    
    # Nettoyage des phrases communes
    prefixes = ["combien font", "calcule", "résous", "quel est le résultat de"]
    for prefixe in prefixes:
        if t.startswith(prefixe):
            t = t[len(prefixe):].strip()
            
    # Remplacement des mots par des symboles
    t = t.replace("fois", "*").replace("multiplier par", "*").replace("x", "*")
    t = t.replace("divisé par", "/").replace("sur", "/")
    t = t.replace("plus", "+").replace("moins", "-")
    t = t.replace("puissance", "**").replace("au carré", "**2")
    
    # Cas spécial racine : on s'assure d'avoir des parenthèses pour eval
    if "racine" in t:
        # On cherche un nombre après 'racine'
        match = re.search(r'racine\s+(?:carrée\s+de\s+)?(\d+)', t)
        if match:
            t = f"sqrt({match.group(1)})"
        else:
            t = t.replace("racine carrée de", "sqrt").replace("racine de", "sqrt")
    
    # Extraction de l'expression mathématique (chiffres, opérateurs, parenthèses, points)
    expr = re.sub(r'[^0-9+\-*/.**() ,sqrt]', '', t).strip()
    if not expr or not any(c.isdigit() for c in expr):
        return None
    
    try:
        # Dictionnaire de sécurité pour eval
        safe_dict = {
            "sqrt": math.sqrt,
            "pow": math.pow,
            "pi": math.pi,
            "e": math.e
        }
        resultat = eval(expr, {"__builtins__": None}, safe_dict)
        
        # Formatage du résultat
        if isinstance(resultat, float) and resultat.is_integer():
            resultat = int(resultat)
        elif isinstance(resultat, float):
            resultat = round(resultat, 3)
            
        # Phrase de réponse élégante
        clean_expr = expr.replace("**2", " au carré").replace("sqrt", "racine de ").replace("(", "").replace(")", "").replace("*", " fois ").replace("/", " divisé par ")
        return f"Le résultat de {clean_expr} est {resultat}, Monsieur."
    except Exception:
        return None

def resoudre_francais_localement(texte):
    """Résout des questions de français simples localement."""
    t = texte.lower().strip()
    
    # Dictionnaire local de secours (très basique)
    dictionnaire = {
        "ia": "Intelligence Artificielle. Ensemble de théories et de techniques mises en œuvre en vue de réaliser des machines capables de simuler l'intelligence humaine.",
        "intelligence artificielle": "Ensemble de théories et de techniques mises en œuvre en vue de réaliser des machines capables de simuler l'intelligence humaine.",
        "maison": "Bâtiment servant de logement, d'habitation.",
        "mathématiques": "Science qui étudie par le moyen du raisonnement déductif les propriétés d'êtres abstraits.",
        "jarvis": "Just A Rather Very Intelligent System. Votre fidèle assistant.",
    }
    
    # Définitions
    if any(p in t for p in ["définition de", "définis le mot", "c'est quoi"]):
        # On essaie d'extraire le mot après les phrases clés
        mot = ""
        if "définition de" in t: mot = t.split("définition de")[-1]
        elif "définis le mot" in t: mot = t.split("définis le mot")[-1]
        elif "c'est quoi" in t: mot = t.split("c'est quoi")[-1]
        
        mot = mot.replace("?", "").replace("l'", "").replace("la ", "").replace("le ", "").replace("les ", "").strip()
        
        if mot in dictionnaire:
            return f"La définition de {mot} est : {dictionnaire[mot]}."
            
    # Conjugaison basique
    if "conjugue" in t or "conjugaison" in t:
        if "être" in t:
            return "Verbe Être au présent : Je suis, tu es, il est, nous sommes, vous êtes, ils sont."
        if "avoir" in t:
            return "Verbe Avoir au présent : J'ai, tu as, il a, nous avons, vous avez, ils ont."
            
    return None

def resoudre_conversion_localement(texte):
    """Gère les conversions d'unités et de devises localement."""
    t = texte.lower().replace("?", "").strip()
    
    # Unités de longueur
    if any(m in t for m in [" km ", " kilomètres ", " milles ", " miles "]):
        # km to miles: 0.621371
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:km|kilomètres)', t)
        if match:
            val = float(match.group(1).replace(",", "."))
            res = round(val * 0.621371, 2)
            return f"{val} kilomètres font environ {res} miles, Monsieur."
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:miles|milles)', t)
        if match:
            val = float(match.group(1).replace(",", "."))
            res = round(val / 0.621371, 2)
            return f"{val} miles font environ {res} kilomètres, Monsieur."

    # Température (C to F)
    if any(m in t for m in [" degrés ", " celsius ", " fahrenheit "]):
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:degrés|celsius)', t)
        if match and "fahrenheit" in t:
            val = float(match.group(1).replace(",", "."))
            res = round((val * 9/5) + 32, 1)
            return f"{val} degrés Celsius font {res} degrés Fahrenheit."
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:degrés|fahrenheit)', t)
        if match and "celsius" in t:
            val = float(match.group(1).replace(",", "."))
            res = round((val - 32) * 5/9, 1)
            return f"{val} degrés Fahrenheit font {res} degrés Celsius."

    # Devises (Taux fixes simplifiés pour l'exemple local)
    if any(m in t for m in [" euro ", " euros ", " dollar ", " dollars "]):
        # 1 EUR = 1.08 USD (approximatif)
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*euros?', t)
        if match and "dollar" in t:
            val = float(match.group(1).replace(",", "."))
            res = round(val * 1.08, 2)
            return f"{val} euros font environ {res} dollars, Monsieur."
        match = re.search(r'(\d+(?:[.,]\d+)?)\s*dollars?', t)
        if match and "euro" in t:
            val = float(match.group(1).replace(",", "."))
            res = round(val / 1.08, 2)
            return f"{val} dollars font environ {res} euros, Monsieur."
            
    return None

def resoudre_traduction_localement(texte):
    """Traduction ultra-rapide de mots courants localement."""
    t = texte.lower().strip()
    
    dict_trad = {
        "bonjour": {"en": "hello", "es": "hola", "de": "hallo"},
        "merci": {"en": "thank you", "es": "gracias", "de": "danke"},
        "au revoir": {"en": "goodbye", "es": "adiós", "de": "auf wiedersehen"},
        "s'il vous plaît": {"en": "please", "es": "por favor", "de": "bitte"},
        "oui": {"en": "yes", "es": "sí", "de": "ja"},
        "non": {"en": "no", "es": "no", "de": "nein"},
        "ami": {"en": "friend", "es": "amigo", "de": "freund"},
        "maison": {"en": "house", "es": "casa", "de": "haus"},
        "ordinateur": {"en": "computer", "es": "ordenador", "de": "computer"},
        "assistant": {"en": "assistant", "es": "asistente", "de": "assistent"},
    }

    if any(p in t for p in ["comment dit-on", "traduis", "en anglais", "en espagnol", "en allemand"]):
        cible = "en"
        if "espagnol" in t: cible = "es"
        elif "allemand" in t: cible = "de"
        
        # Extraction du mot
        # On nettoie les expressions courantes
        mot = t
        for p in ["comment dit-on", "traduis", "en anglais", "en espagnol", "en allemand", "?"]:
            mot = mot.replace(p, "")
        mot = mot.replace('"', '').replace("'", "").strip()
        
        if mot in dict_trad:
            res = dict_trad[mot][cible]
            lang = "anglais" if cible == "en" else ("espagnol" if cible == "es" else "allemand")
            return f"En {lang}, '{mot}' se dit '{res}'."
            
    return None


# ══════════════════════════════════════════════════════════════
#  EXTRAS LOCAUX — Minuterie, Blagues, Volume, Notes, etc.
# ══════════════════════════════════════════════════════════════

# ── Données statiques ─────────────────────────────────────────

_BLAGUES = [
    "Pourquoi les plongeurs plongent-ils toujours en arrière ? Parce que sinon ils tomberaient dans le bateau !",
    "Un homme entre dans une bibliothèque et demande : 'Avez-vous des livres sur la paranoïa ?' La bibliothécaire chuchote : 'Ils sont juste derrière vous.'",
    "Qu'est-ce qu'un canif ? Un petit fien.",
    "Pourquoi l'épouvantail a-t-il reçu un prix ? Parce qu'il était exceptionnel dans son domaine.",
    "Comment appelle-t-on un chat tombé dans un pot de peinture le jour de Noël ? Un chat-peint de Noël.",
    "Qu'est-ce qu'un crocodile qui surveille la cour d'école ? Un sac à dents.",
    "Pourquoi les mathématiciens confondent-ils Halloween et Noël ? Parce que Oct 31 = Dec 25.",
    "Un homme entre dans un bar... Aïe.",
    "Qu'est-ce qu'un agneau qui bégaie ? Du bé bé beurre.",
    "Qu'est-ce qu'un philosophe ? Un homme qui cherche dans une pièce noire un chapeau noir qui n'existe pas. Un théologien — il le trouve quand même.",
    "Comment on appelle un poisson sans yeux ? Un poisson.",
    "Qu'est-ce qu'un Tic qui tombe d'un arbre ? Un Tac.",
    "Pourquoi le scarabée est-il si fort ? Parce qu'il soulève des bouses de vache.",
    "Comment appelle-t-on un chat qui est tombé dans un pot de confiture ? Un chat confit.",
    "Qu'est-ce qu'un yaourt dans la forêt ? Un yaourt nature.",
    "Pourquoi les girafes ont-elles un long cou ? Parce que leurs pieds sentent mauvais.",
    "Qu'est-ce qu'un os dans un bain de boue ? Sherlock Bones.",
    "Comment appelle-t-on une ceinture en peau de crocodile ? Une ceinture qui fait le tour du ventre.",
    "Qu'est-ce qu'un cactus ? Un arbre bien défendu.",
    "Pourquoi les Belges mettent-ils leur portable dans la congélation ? Pour avoir des contacts froids.",
]

_CITATIONS = [
    "Le succès, c'est tomber sept fois et se relever huit. — Proverbe japonais",
    "La vie, c'est comme une bicyclette, il faut avancer pour ne pas perdre l'équilibre. — Albert Einstein",
    "Le seul moyen de faire du bon travail est d'aimer ce que vous faites. — Steve Jobs",
    "Celui qui déplace les montagnes commence par enlever les petites pierres. — Confucius",
    "N'attendez pas. Le moment ne sera jamais parfait. — Napoléon Hill",
    "La plus grande gloire n'est pas de ne jamais tomber, mais de se relever à chaque chute. — Nelson Mandela",
    "Vous ne pouvez pas aller en arrière et changer le début, mais vous pouvez commencer là où vous êtes et changer la fin. — C.S. Lewis",
    "Le pessimiste voit la difficulté dans chaque opportunité. L'optimiste voit l'opportunité dans chaque difficulté. — Winston Churchill",
    "Ce n'est pas la montagne que nous conquérons, mais nous-mêmes. — Edmund Hillary",
    "La créativité, c'est l'intelligence qui s'amuse. — Albert Einstein",
    "Chaque expert a un jour été un débutant. — Helen Hayes",
    "Votre temps est limité. Ne le gâchez pas en vivant la vie de quelqu'un d'autre. — Steve Jobs",
    "Tout ce que l'esprit peut concevoir et croire, il peut l'accomplir. — Napoleon Hill",
    "Le secret pour aller de l'avant, c'est de commencer. — Mark Twain",
    "Les personnes qui sont assez folles pour penser qu'elles peuvent changer le monde sont celles qui le font. — Apple",
]

_PHONETIQUE = {
    'a': 'Alpha', 'b': 'Bravo', 'c': 'Charlie', 'd': 'Delta', 'e': 'Echo',
    'f': 'Foxtrot', 'g': 'Golf', 'h': 'Hotel', 'i': 'India', 'j': 'Juliet',
    'k': 'Kilo', 'l': 'Lima', 'm': 'Mike', 'n': 'November', 'o': 'Oscar',
    'p': 'Papa', 'q': 'Quebec', 'r': 'Romeo', 's': 'Sierra', 't': 'Tango',
    'u': 'Uniform', 'v': 'Victor', 'w': 'Whiskey', 'x': 'X-ray', 'y': 'Yankee',
    'z': 'Zulu',
}

_CAPITALES = {
    "france": "Paris", "espagne": "Madrid", "italie": "Rome", "allemagne": "Berlin",
    "royaume-uni": "Londres", "angleterre": "Londres", "portugal": "Lisbonne",
    "pays-bas": "Amsterdam", "belgique": "Bruxelles", "suisse": "Berne",
    "autriche": "Vienne", "pologne": "Varsovie", "suede": "Stockholm",
    "norvege": "Oslo", "danemark": "Copenhague", "finlande": "Helsinki",
    "russie": "Moscou", "ukraine": "Kiev", "grece": "Athenes",
    "turquie": "Ankara", "maroc": "Rabat", "algerie": "Alger",
    "tunisie": "Tunis", "egypte": "Le Caire", "senegal": "Dakar",
    "cameroun": "Yaounde", "cote d'ivoire": "Yamoussoukro", "mali": "Bamako",
    "etats-unis": "Washington", "canada": "Ottawa", "mexique": "Mexico",
    "bresil": "Brasilia", "argentine": "Buenos Aires", "chili": "Santiago",
    "perou": "Lima", "colombie": "Bogota", "venezuela": "Caracas",
    "chine": "Pekin", "japon": "Tokyo", "coree du sud": "Seoul",
    "inde": "New Delhi", "pakistan": "Islamabad", "australie": "Canberra",
    "nouvelle-zelande": "Wellington", "afrique du sud": "Pretoria",
    "nigeria": "Abuja", "kenya": "Nairobi", "ghana": "Accra",
    "israel": "Jerusalem", "iran": "Teheran", "irak": "Bagdad",
    "arabie saoudite": "Riyad", "emirats arabes unis": "Abu Dhabi",
    "qatar": "Doha", "indonesie": "Jakarta", "thaïlande": "Bangkok",
    "vietnam": "Hanoï", "philippines": "Manille", "malaisie": "Kuala Lumpur",
}

_MONNAIES = {
    "france": "Euro (€)", "espagne": "Euro (€)", "italie": "Euro (€)",
    "allemagne": "Euro (€)", "portugal": "Euro (€)", "belgique": "Euro (€)",
    "suisse": "Franc suisse (CHF)", "royaume-uni": "Livre sterling (£)",
    "angleterre": "Livre sterling (£)", "etats-unis": "Dollar américain ($)",
    "canada": "Dollar canadien (CAD)", "australie": "Dollar australien (AUD)",
    "japon": "Yen (¥)", "chine": "Yuan (CNY)", "russie": "Rouble (RUB)",
    "inde": "Roupie indienne (INR)", "bresil": "Real (BRL)",
    "maroc": "Dirham marocain (MAD)", "algerie": "Dinar algérien (DZD)",
    "tunisie": "Dinar tunisien (TND)", "mexique": "Peso mexicain (MXN)",
    "turquie": "Livre turque (TRY)", "arabie saoudite": "Riyal saoudien (SAR)",
    "emirats arabes unis": "Dirham des EAU (AED)", "coree du sud": "Won (KRW)",
}

_FUSEAUX = {
    "new york": ("New York", "America/New_York"),
    "los angeles": ("Los Angeles", "America/Los_Angeles"),
    "chicago": ("Chicago", "America/Chicago"),
    "montreal": ("Montréal", "America/Toronto"),
    "toronto": ("Toronto", "America/Toronto"),
    "london": ("Londres", "Europe/London"),
    "londres": ("Londres", "Europe/London"),
    "paris": ("Paris", "Europe/Paris"),
    "berlin": ("Berlin", "Europe/Berlin"),
    "madrid": ("Madrid", "Europe/Madrid"),
    "rome": ("Rome", "Europe/Rome"),
    "moscow": ("Moscou", "Europe/Moscow"),
    "moscou": ("Moscou", "Europe/Moscow"),
    "dubai": ("Dubaï", "Asia/Dubai"),
    "dubai": ("Dubaï", "Asia/Dubai"),
    "india": ("Inde", "Asia/Kolkata"),
    "inde": ("Inde", "Asia/Kolkata"),
    "mumbai": ("Mumbai", "Asia/Kolkata"),
    "delhi": ("Delhi", "Asia/Kolkata"),
    "beijing": ("Pékin", "Asia/Shanghai"),
    "pekin": ("Pékin", "Asia/Shanghai"),
    "shanghai": ("Shanghai", "Asia/Shanghai"),
    "tokyo": ("Tokyo", "Asia/Tokyo"),
    "japon": ("Tokyo", "Asia/Tokyo"),
    "seoul": ("Séoul", "Asia/Seoul"),
    "sydney": ("Sydney", "Australia/Sydney"),
    "melbourne": ("Melbourne", "Australia/Melbourne"),
    "auckland": ("Auckland", "Pacific/Auckland"),
    "sao paulo": ("São Paulo", "America/Sao_Paulo"),
    "buenos aires": ("Buenos Aires", "America/Argentina/Buenos_Aires"),
    "mexico": ("Mexico", "America/Mexico_City"),
    "honolulu": ("Honolulu", "Pacific/Honolulu"),
    "hawaii": ("Hawaii", "Pacific/Honolulu"),
    "anchorage": ("Anchorage", "America/Anchorage"),
    "bangkok": ("Bangkok", "Asia/Bangkok"),
    "singapore": ("Singapour", "Asia/Singapore"),
    "singapour": ("Singapour", "Asia/Singapore"),
    "hong kong": ("Hong Kong", "Asia/Hong_Kong"),
    "le caire": ("Le Caire", "Africa/Cairo"),
    "nairobi": ("Nairobi", "Africa/Nairobi"),
    "johannesburg": ("Johannesburg", "Africa/Johannesburg"),
    "casablanca": ("Casablanca", "Africa/Casablanca"),
}

# ── Stockage notes/courses/todos ──────────────────────────────
_LISTES_PATH = os.path.join(DATA_DIR, "jarvis_listes.json")

def _charger_listes():
    try:
        if os.path.exists(_LISTES_PATH):
            with open(_LISTES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"notes": [], "courses": [], "todos": []}

def _sauvegarder_listes(data):
    try:
        with open(_LISTES_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[LISTES] Erreur sauvegarde : {e}")

# ── Minuteries actives ────────────────────────────────────────
_minuteries = {}

def _parse_duree_secondes(texte):
    """Extrait une durée totale en secondes depuis une phrase."""
    import re
    t = texte.lower()
    total = 0
    h = re.search(r'(\d+)\s*(heure|h\b)', t)
    m = re.search(r'(\d+)\s*(minute|min\b)', t)
    s = re.search(r'(\d+)\s*(seconde|sec\b)', t)
    if h: total += int(h.group(1)) * 3600
    if m: total += int(m.group(1)) * 60
    if s: total += int(s.group(1))
    return total if total > 0 else None

def _volume_get_interface():
    """Interface pycaw du volume maître Windows (None si indisponible)."""
    try:
        import comtypes
        try:
            comtypes.CoInitialize()
        except Exception:
            pass
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        dev = AudioUtilities.GetSpeakers()
        if hasattr(dev, "EndpointVolume"):          # pycaw récent
            return dev.EndpointVolume
        from comtypes import CLSCTX_ALL             # pycaw ancien
        iface = dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return ctypes.cast(iface, ctypes.POINTER(IAudioEndpointVolume))
    except Exception as e:
        print(f"[VOLUME] pycaw indisponible : {e}")
        return None


async def resoudre_globe_localement(texte: str):
    """Détecte les commandes de navigation globe et déclenche CesiumJS."""
    import re
    t = texte.lower().strip()

    # ── Mots-clés déclencheurs ───────────────────────────────────────────────
    _mots_globe   = ["affiche la terre", "montre la terre", "montre-moi la terre",
                     "globe terrestre", "affiche le globe", "vue de la terre",
                     "vue spatiale", "vue depuis l'espace", "vue de l'espace",
                     "montre la planète", "affiche la planète",
                     "zoom arrière total", "dézoom total"]

    _mots_ville   = ["affiche", "montre-moi", "montre moi", "survole",
                     "navigue vers", "va vers", "zoome sur",
                     "fais un survol de", "localise", "trouve",
                     "où est", "ou est", "situe", "où se trouve", "ou se trouve"]

    _mots_route   = ["trace un itinéraire", "trace l'itinéraire", "itinéraire de",
                     "route de", "chemin de", "comment aller de",
                     "trace une route de", "trajet de", "trajet depuis"]

    _mots_fermer  = ["ferme la carte", "ferme le globe", "cache la carte",
                     "cache le globe", "ferme la navigation", "quitte le globe",
                     "retour à jarvis", "ferme la vue", "masque la carte"]

    _mots_position = ["ma position", "où suis-je", "ou suis-je",
                      "affiche ma position", "montre ma position",
                      "localise-moi", "localise moi", "où je suis"]

    # ── Fermer ───────────────────────────────────────────────────────────────
    if any(m in t for m in _mots_fermer):
        await send_globe_command(globe_action="hide")
        return "Navigation fermée. Je reviens à l'interface principale, {USER_NAME}."

    # ── Ma position ──────────────────────────────────────────────────────────
    if any(m in t for m in _mots_position):
        # On délègue la géolocalisation au navigateur (navigator.geolocation)
        # bien plus précis que l'IP — le frontend gère tout
        await send_globe_command(globe_action="my_location")
        await parler("Localisation en cours, {USER_NAME}. Le globe affiche votre position en temps réel.")
        return "[Globe] Demande de géolocalisation envoyée au navigateur."

    # ── Globe Terre ───────────────────────────────────────────────────────────
    if any(m in t for m in _mots_globe):
        await send_globe_command(globe_action="show_earth")
        await parler("Initialisation du globe terrestre. Vue depuis l'espace activée, {USER_NAME}.")
        return "[Globe] Vue Terre activée."

    # ── Itinéraire de X à Y ──────────────────────────────────────────────────
    if any(m in t for m in _mots_route):
        pattern = r"(?:de|depuis)\s+(.+?)\s+(?:a|vers|jusqu.a|et)\s+(.+?)(?:\s*[?!]?\s*$)" 
        match = re.search(pattern, t)
        if match:
            from_name = match.group(1).strip().title()
            to_name   = match.group(2).strip().title()
            await parler(f"Calcul de l'itinéraire de {from_name} vers {to_name}. Géolocalisation en cours...")
            lat1, lon1, _ = await geocode_lieu(from_name)
            lat2, lon2, _ = await geocode_lieu(to_name)
            if lat1 and lat2:
                await send_globe_command(
                    globe_action="route",
                    from_lat=lat1, from_lon=lon1, from_name=from_name,
                    to_lat=lat2,   to_lon=lon2,   to_name=to_name
                )
                await parler(f"Itinéraire tracé de {from_name} à {to_name}, {USER_NAME}. La route est affichée sur le globe.")
                return f"[Globe] Route {from_name} → {to_name} affichée."
            else:
                return f"Je n'ai pas pu localiser les deux villes, {USER_NAME}. Vérifiez les noms et réessayez."
        return None

    # ── Fly to ville ─────────────────────────────────────────────────────────
    for mot in _mots_ville:
        if mot in t:
            # Extraire ce qui suit le mot déclencheur
            idx = t.find(mot)
            reste = t[idx + len(mot):].strip()
            # Nettoyer les articles
            for art in ["la ville de ", "la ville ", "le ", "la ", "l'", "les ", "ma ville ", "mon pays "]:
                if reste.startswith(art):
                    reste = reste[len(art):]
            reste = reste.replace("?", "").replace("!", "").strip()
            if len(reste) >= 2:
                nom_lieu = reste.title()
                await parler(f"Recherche de {nom_lieu} en cours... Coordonnées en acquisition.")
                lat, lon, display = await geocode_lieu(nom_lieu)
                if lat:
                    # Altitude selon le type de lieu (ville proche = plus bas)
                    altitude = 300000
                    await send_globe_command(
                        globe_action="fly_to",
                        lat=lat, lon=lon,
                        target=nom_lieu,
                        altitude=altitude
                    )
                    await parler(f"Coordonnées acquises. Survol de {nom_lieu} en cours, {USER_NAME}.")
                    return f"[Globe] Survol de {nom_lieu} ({lat:.4f}°, {lon:.4f}°)"
                else:
                    return f"Je n'ai pas réussi à localiser {nom_lieu}, {USER_NAME}. Essayez avec un nom plus précis."
            break

    return None

async def resoudre_extras_locaux(texte):
    """
    Résout localement : minuteries, blagues, citations, volume, luminosité,
    notes, courses, todos, capitales, fuseaux, âge, dé, mot de passe, etc.
    """
    import re
    t = texte.lower().replace("?", "").strip()

    # ══ MINUTERIE ══════════════════════════════════════════════
    if any(k in t for k in ["minuteur", "minuterie", "timer", "rappelle-moi dans",
                             "rappelle moi dans", "alarme dans", "alerte dans",
                             "lance un minuteur", "active le minuteur",
                             "previens-moi dans", "previens moi dans"]):
        duree = _parse_duree_secondes(t)
        if duree:
            # Envoi au frontend
            if CONNECTED_CLIENTS:
                async def _send_timer():
                    msg = json.dumps({"action": "timer_start", "duration": duree})
                    await asyncio.gather(*[ws.send(msg) for ws in CONNECTED_CLIENTS], return_exceptions=True)
                asyncio.create_task(_send_timer())
            
            # Ancienne logique de sonnerie conservée pour la voix (Style Iron Man)
            nom = f"timer_{len(_minuteries)+1}"
            def _sonner(nom=nom, duree=duree):
                _minuteries.pop(nom, None)
                import random
                reponses = [
                    "Monsieur, le protocole de compte à rebours est arrivé à échéance.",
                    "{USER_NAME}, la temporisation est terminée. J'espère que vous n'avez rien oublié.",
                    "Alerte : Le minuteur a atteint zéro. Tout est en ordre, Monsieur ?",
                    "Fin du décompte, {USER_NAME}. Je reste à votre entière disposition."
                ]
                loop2 = asyncio.new_event_loop()
                loop2.run_until_complete(parler(random.choice(reponses)))
                loop2.close()
            
            timer = threading.Timer(duree, _sonner)
            timer.daemon = True
            timer.start()
            _minuteries[nom] = timer
            
            mins = duree // 60
            return f"Minuteur de {mins} minutes activé. Affichage HUD en cours."
        return "Précisez la durée, par exemple : 'Mets un minuteur de 10 minutes'."

    # AJOUTER / RETIRER DU TEMPS
    if any(k in t for k in ["ajoute", "rajoute", "augmente"]) and "minute" in t:
        try:
            extra = int(re.search(r'\d+', t).group()) * 60
            if CONNECTED_CLIENTS:
                async def _send_add():
                    msg = json.dumps({"action": "timer_add", "duration": extra})
                    await asyncio.gather(*[ws.send(msg) for ws in CONNECTED_CLIENTS], return_exceptions=True)
                asyncio.create_task(_send_add())
            return f"J'ai ajouté {extra//60} minutes au minuteur."
        except: pass
    
    if any(k in t for k in ["retire", "enlève", "diminue", "supprime"]) and "minute" in t:
        try:
            less = int(re.search(r'\d+', t).group()) * 60
            if CONNECTED_CLIENTS:
                async def _send_rem():
                    msg = json.dumps({"action": "timer_remove", "duration": less})
                    await asyncio.gather(*[ws.send(msg) for ws in CONNECTED_CLIENTS], return_exceptions=True)
                asyncio.create_task(_send_rem())
            return f"J'ai retiré {less//60} minutes au minuteur."
        except: pass

    if any(k in t for k in ["annuler minuteur", "annule minuteur", "stop minuteur", "stop le minuteur",
                             "annuler minuterie", "annule le timer", "arrête le minuteur", "arrête le minute",
                             "stop le chrono", "arrête le chrono"]):
        if CONNECTED_CLIENTS:
            async def _send_stop():
                msg = json.dumps({"action": "timer_stop"})
                await asyncio.gather(*[ws.send(msg) for ws in CONNECTED_CLIENTS], return_exceptions=True)
            asyncio.create_task(_send_stop())
        
        if _minuteries:
            for nom, timer in list(_minuteries.items()):
                timer.cancel()
            _minuteries.clear()
            return "Minuteur arrêté, {USER_NAME}."
        return "Aucun minuteur actif."

    if any(k in t for k in ["minuteur actif", "minuteries actives", "combien de minuteurs"]):
        if _minuteries:
            return f"Vous avez {len(_minuteries)} minuterie{'s' if len(_minuteries) > 1 else ''} active{'s' if len(_minuteries) > 1 else ''}."
        return "Aucune minuterie active en ce moment."

    # ══ FUSEAUX HORAIRES ═══════════════════════════════════════
    if any(k in t for k in ["heure à", "heure en", "heure au", "quelle heure il est à",
                             "quelle heure est-il à", "quelle heure est il à",
                             "heure là-bas", "heure la-bas"]):
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            try:
                from backports.zoneinfo import ZoneInfo
            except ImportError:
                ZoneInfo = None
        if ZoneInfo:
            for cle, (nom_ville, tz_str) in _FUSEAUX.items():
                if cle in t:
                    try:
                        from datetime import timezone
                        heure_locale = datetime.now(ZoneInfo(tz_str))
                        return (f"Il est actuellement {heure_locale.strftime('%H:%M')} "
                                f"à {nom_ville}, {USER_NAME}.")
                    except Exception:
                        pass
        return "Je ne reconnais pas cette ville dans ma base locale, {USER_NAME}."

    # ══ CALCUL D'ÂGE ══════════════════════════════════════════
    age_match = re.search(r'n[ée]\s+en\s+(\d{4})', t)
    if age_match or any(k in t for k in ["quel age j'ai", "quel âge j'ai",
                                          "j'ai quel age", "j'ai quel âge",
                                          "calcule mon age", "calcule mon âge"]):
        if age_match:
            annee_naissance = int(age_match.group(1))
            age = datetime.now().year - annee_naissance
            return f"Si vous êtes né en {annee_naissance}, vous avez {age} ans, {USER_NAME}."
        return "Précisez votre année de naissance, par exemple : 'Né en 1990, quel âge j'ai ?'"

    # ══ COMPTE À REBOURS ═══════════════════════════════════════
    if any(k in t for k in ["combien de jours avant noël", "combien de jours jusqu'à noël",
                             "combien de jours avant noel"]):
        today = datetime.now().date()
        noel = datetime(today.year, 12, 25).date()
        if today > noel:
            noel = datetime(today.year + 1, 12, 25).date()
        jours = (noel - today).days
        return f"Il reste {jours} jour{'s' if jours > 1 else ''} avant Noël, {USER_NAME} !"

    if any(k in t for k in ["combien de jours avant le nouvel an",
                             "combien de jours avant 2025", "combien de jours avant 2026",
                             "combien de jours avant 2027"]):
        today = datetime.now().date()
        an_prochain = datetime(today.year + 1, 1, 1).date()
        jours = (an_prochain - today).days
        return f"Il reste {jours} jour{'s' if jours > 1 else ''} avant le Nouvel An, {USER_NAME} !"

    # ══ BLAGUES ════════════════════════════════════════════════
    if any(k in t for k in ["blague", "fais-moi rire", "fais moi rire",
                             "raconte-moi une blague", "raconte moi une blague",
                             "dis-moi une blague", "dis moi une blague",
                             "joke", "fais rire", "une blague"]):
        return random.choice(_BLAGUES)

    # ══ CITATIONS ══════════════════════════════════════════════
    if any(k in t for k in ["citation", "inspire-moi", "inspire moi",
                             "quote", "parole sage", "phrase motivante",
                             "motive-moi", "motive moi", "dis-moi quelque chose",
                             "donne-moi une citation"]):
        return random.choice(_CITATIONS)

    # ══ PILE OU FACE / DÉ ═════════════════════════════════════
    if any(k in t for k in ["pile ou face", "pile ou pile", "lance une pièce",
                             "lance une piece", "heads or tails", "flip"]):
        resultat = random.choice(["Pile", "Face"])
        return f"J'ai lancé la pièce... C'est {resultat} !"

    de_match = re.search(r'(?:lance|jette|tire|roule)\s+un\s+d[eé](?:\s+[aà]\s+(\d+)\s+face)?', t)
    if de_match or "lance un dé" in t or "jette le dé" in t or "jeter le dé" in t:
        nb_faces = 6
        m2 = re.search(r'd[eé]\s+[aà]\s+(\d+)', t)
        if m2:
            nb_faces = int(m2.group(1))
        result = random.randint(1, nb_faces)
        return f"J'ai lancé un dé à {nb_faces} faces... Vous obtenez : {result} !"

    if any(k in t for k in ["nombre aléatoire", "nombre aleatoire", "chiffre aléatoire",
                             "chiffre aleatoire", "génère un nombre", "genere un nombre"]):
        rng_match = re.search(r'entre\s+(\d+)\s+et\s+(\d+)', t)
        if rng_match:
            a, b = int(rng_match.group(1)), int(rng_match.group(2))
            return f"Votre nombre aléatoire entre {a} et {b} : {random.randint(a, b)}"
        return f"Voici un nombre aléatoire : {random.randint(1, 100)}"

    # ══ GÉNÉRATEUR DE MOT DE PASSE ════════════════════════════
    if any(k in t for k in ["mot de passe", "password", "mdp sécurisé", "mdp securise",
                             "génère un mot de passe", "genere un mot de passe",
                             "crée un mot de passe", "cree un mot de passe"]):
        import string
        longueur = 16
        lg_m = re.search(r'(\d+)\s*(?:caractères|caracteres|car)', t)
        if lg_m:
            longueur = min(max(int(lg_m.group(1)), 8), 64)
        chars = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
        mdp = ''.join(random.SystemRandom().choice(chars) for _ in range(longueur))
        return f"Votre mot de passe sécurisé ({longueur} caractères) : {mdp}"

    # ══ NOTES RAPIDES ══════════════════════════════════════════
    if any(k in t for k in ["note ça", "note ca", "prends note", "retiens ça",
                             "retiens ca", "mémorise ça", "memorise ca",
                             "note que", "note :", "écris ça", "ecris ca"]):
        contenu = t
        for pref in ["note ça :", "note ca :", "note que", "note :", "prends note :",
                     "prends note de", "retiens ça :", "retiens ca :", "note ",
                     "mémorise ça :", "memorise ca :", "écris ça :", "ecris ca :"]:
            if contenu.startswith(pref):
                contenu = contenu[len(pref):].strip()
                break
        if contenu:
            listes = _charger_listes()
            note = f"[{datetime.now().strftime('%d/%m %H:%M')}] {contenu}"
            listes["notes"].append(note)
            _sauvegarder_listes(listes)
            return f"Note enregistrée, {USER_NAME} : '{contenu}'"
        return "Que souhaitez-vous que je note ?"

    if any(k in t for k in ["lis mes notes", "montre mes notes", "quelles sont mes notes",
                             "mes notes", "affiche mes notes"]):
        listes = _charger_listes()
        if not listes["notes"]:
            return "Vous n'avez aucune note enregistrée, {USER_NAME}."
        notes = "\n".join(f"• {n}" for n in listes["notes"][-5:])
        return f"Vos {min(5, len(listes['notes']))} dernières notes, {USER_NAME} :\n{notes}"

    if any(k in t for k in ["efface mes notes", "supprime mes notes",
                             "vide mes notes", "clear mes notes"]):
        listes = _charger_listes()
        listes["notes"] = []
        _sauvegarder_listes(listes)
        return "Toutes vos notes ont été effacées, {USER_NAME}."

    # ══ LISTE DE COURSES ═══════════════════════════════════════
    if any(k in t for k in ["ajoute", "rajoute"]) and any(k in t for k in ["liste de courses", "courses", "liste d'achats"]):
        article = t
        for pref in ["ajoute ", "rajoute ", "à ma liste de courses", "à la liste de courses",
                     "dans la liste de courses", "à mes courses", "à ma liste d'achats"]:
            article = article.replace(pref, "").strip()
        if article:
            listes = _charger_listes()
            listes["courses"].append(article)
            _sauvegarder_listes(listes)
            return f"'{article}' ajouté à votre liste de courses, {USER_NAME}."

    if any(k in t for k in ["liste de courses", "mes courses", "qu'est-ce que j'ai dans ma liste",
                             "montre ma liste de courses", "lis ma liste de courses",
                             "quoi dans ma liste"]):
        listes = _charger_listes()
        if not listes["courses"]:
            return "Votre liste de courses est vide, {USER_NAME}."
        items = "\n".join(f"• {i}" for i in listes["courses"])
        return f"Votre liste de courses ({len(listes['courses'])} article{'s' if len(listes['courses']) > 1 else ''}) :\n{items}"

    if any(k in t for k in ["vide la liste de courses", "efface la liste de courses",
                             "supprime la liste de courses", "clear les courses"]):
        listes = _charger_listes()
        listes["courses"] = []
        _sauvegarder_listes(listes)
        return "Liste de courses vidée, {USER_NAME}."

    # ══ TO-DO LIST ═════════════════════════════════════════════
    if any(k in t for k in ["ajoute une tâche", "ajoute une tache", "nouvelle tâche",
                             "nouvelle tache", "ajoute à ma to-do", "ajoute a ma to-do",
                             "à faire :", "a faire :"]):
        tache = t
        for pref in ["ajoute une tâche :", "ajoute une tache :", "nouvelle tâche :",
                     "nouvelle tache :", "ajoute à ma to-do :", "ajoute a ma to-do :",
                     "à faire :", "a faire :", "ajoute une tâche ", "ajoute une tache "]:
            tache = tache.replace(pref, "").strip()
        if tache:
            listes = _charger_listes()
            listes["todos"].append({"tache": tache, "fait": False, "date": datetime.now().strftime("%d/%m")})
            _sauvegarder_listes(listes)
            return f"Tâche ajoutée : '{tache}', {USER_NAME}."

    if any(k in t for k in ["mes tâches", "mes taches", "ma to-do", "ma todo",
                             "liste de tâches", "liste de taches", "qu'est-ce que j'ai à faire",
                             "qu'est-ce que j'ai a faire"]):
        listes = _charger_listes()
        todos = [td for td in listes["todos"] if not td.get("fait")]
        if not todos:
            return "Votre liste de tâches est vide, {USER_NAME}. Bravo !"
        items = "\n".join(f"• [{td['date']}] {td['tache']}" for td in todos[-8:])
        return f"Vos tâches à faire ({len(todos)}) :\n{items}"

    if any(k in t for k in ["efface mes tâches", "efface mes taches", "vide ma to-do",
                             "supprime mes tâches", "supprime mes taches"]):
        listes = _charger_listes()
        listes["todos"] = []
        _sauvegarder_listes(listes)
        return "Liste de tâches vidée, {USER_NAME}."

    # ══ VOLUME SYSTÈME ═════════════════════════════════════════
    vol_mots = ["volume", "son", "audio"]
    if any(k in t for k in vol_mots):
        if any(k in t for k in ["coupe le son", "mute", "silence total", "sourdine"]):
            vol = _volume_get_interface()
            if vol:
                vol.SetMute(1, None)
                return "Son coupé, {USER_NAME}."
            return "Je n'ai pas pu accéder au contrôle du volume. Installez pycaw."

        if any(k in t for k in ["remet le son", "unmute", "remet le volume", "réactive le son", "reactive le son"]):
            vol = _volume_get_interface()
            if vol:
                vol.SetMute(0, None)
                return "Son réactivé, {USER_NAME}."

        vol_match = re.search(r'(\d+)\s*(?:%|pourcent)', t)
        if vol_match or any(k in t for k in ["monte le volume", "monte le son",
                                              "baisse le volume", "baisse le son",
                                              "volume à", "son à", "mets le volume",
                                              "mets le son"]):
            vol = _volume_get_interface()
            if vol:
                if vol_match:
                    pct = max(0, min(100, int(vol_match.group(1))))
                    import math
                    # Convertir pourcentage en dB (scale logarithmique Windows)
                    vol.SetMasterVolumeLevelScalar(pct / 100.0, None)
                    return f"Volume réglé à {pct}%, {USER_NAME}."
                elif any(k in t for k in ["monte", "augmente", "hausse", "plus fort"]):
                    cur = vol.GetMasterVolumeLevelScalar()
                    new_vol = min(1.0, cur + 0.1)
                    vol.SetMasterVolumeLevelScalar(new_vol, None)
                    return f"Volume augmenté à {int(new_vol*100)}%, {USER_NAME}."
                elif any(k in t for k in ["baisse", "diminue", "moins fort", "réduis", "reduis"]):
                    cur = vol.GetMasterVolumeLevelScalar()
                    new_vol = max(0.0, cur - 0.1)
                    vol.SetMasterVolumeLevelScalar(new_vol, None)
                    return f"Volume réduit à {int(new_vol*100)}%, {USER_NAME}."
            else:
                return "Contrôle du volume indisponible. Installez pycaw pour cette fonction."

    # ══ LUMINOSITÉ ═════════════════════════════════════════════
    if any(k in t for k in ["luminosité", "luminosite", "brillo", "écran plus clair",
                             "écran plus sombre", "baisser l'écran", "monter l'écran"]):
        if _sbc_ok and _sbc:
            try:
                lum_match = re.search(r'(\d+)\s*(?:%|pourcent)', t)
                if lum_match:
                    pct = max(0, min(100, int(lum_match.group(1))))
                    _sbc.set_brightness(pct)
                    return f"Luminosité réglée à {pct}%, {USER_NAME}."
                elif any(k in t for k in ["monte", "augmente", "plus clair", "hausse", "max"]):
                    cur = _sbc.get_brightness(display=0)
                    if isinstance(cur, list): cur = cur[0]
                    new_b = min(100, cur + 15)
                    _sbc.set_brightness(new_b)
                    return f"Luminosité augmentée à {new_b}%, {USER_NAME}."
                elif any(k in t for k in ["baisse", "diminue", "plus sombre", "réduis", "min"]):
                    cur = _sbc.get_brightness(display=0)
                    if isinstance(cur, list): cur = cur[0]
                    new_b = max(0, cur - 15)
                    _sbc.set_brightness(new_b)
                    return f"Luminosité réduite à {new_b}%, {USER_NAME}."
            except Exception as e:
                return f"Impossible de régler la luminosité : {e}"
        return "Le module de luminosité n'est pas installé. Lancez : pip install screen-brightness-control"

    # ══ VEILLE / ARRÊT / REDÉMARRAGE ══════════════════════════
    if any(k in t for k in ["mets le pc en veille", "mode veille", "veille dans",
                             "suspends le pc", "sleep"]):
        delai = _parse_duree_secondes(t) or 0
        if delai > 0:
            import threading as _th
            def _sleep_later():
                time.sleep(delai)
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
            _th.Thread(target=_sleep_later, daemon=True).start()
            mins = delai // 60
            return f"Le PC passera en veille dans {mins} minute{'s' if mins > 1 else ''}, {USER_NAME}."
        subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"])
        return "Mise en veille du PC, {USER_NAME}. À bientôt !"

    if any(k in t for k in ["éteins le pc", "eteins le pc", "arrête le pc", "arrete le pc",
                             "shutdown", "arrêt dans", "arret dans"]):
        delai = _parse_duree_secondes(t) or 0
        if delai > 0:
            subprocess.run(["shutdown", "/s", "/t", str(int(delai))])
            mins = delai // 60
            return f"Le PC s'éteindra dans {mins} minute{'s' if mins > 1 else ''}, {USER_NAME}."
        return "Pour l'arrêt immédiat, confirmez en disant : 'confirme l'arrêt du pc'."

    if "confirme l'arrêt du pc" in t or "confirme l arret du pc" in t:
        subprocess.run(["shutdown", "/s", "/t", "5"])
        return "Arrêt du PC dans quelques secondes, {USER_NAME}. Au revoir !"

    if any(k in t for k in ["redémarre le pc", "redemarre le pc", "reboot"]):
        delai = _parse_duree_secondes(t) or 30
        subprocess.run(["shutdown", "/r", "/t", str(int(delai))])
        return f"Redémarrage du PC en cours, {USER_NAME}."

    if any(k in t for k in ["annule l'arrêt", "annule l arret", "annule le redémarrage",
                             "annule le redemarrage", "annule la veille"]):
        subprocess.run(["shutdown", "/a"], capture_output=True)
        return "Commande annulée, {USER_NAME}."

    # ══ CORBEILLE ══════════════════════════════════════════════
    if any(k in t for k in ["vide la corbeille", "vider la corbeille", "corbeille vide",
                             "nettoie la corbeille"]):
        try:
            ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x7)
            return "La corbeille a été vidée, {USER_NAME}."
        except Exception as e:
            return f"Impossible de vider la corbeille : {e}"

    # ══ CAPITALE / MONNAIE D'UN PAYS ══════════════════════════
    if any(k in t for k in ["capitale", "capital de"]):
        for pays, capitale in _CAPITALES.items():
            if pays in t:
                return f"La capitale de {pays.title()} est {capitale}, {USER_NAME}."
        return "Je ne connais pas ce pays dans ma base locale, {USER_NAME}."

    if any(k in t for k in ["monnaie", "devise", "monnaie de", "quelle est la monnaie"]):
        for pays, monnaie in _MONNAIES.items():
            if pays in t:
                return f"La monnaie de {pays.title()} est le {monnaie}, {USER_NAME}."
        return "Je ne connais pas la monnaie de ce pays dans ma base locale."

    # ══ CODE PHONÉTIQUE ════════════════════════════════════════
    if any(k in t for k in ["alphabet phonétique", "alphabet phonetique",
                             "code phonétique", "code phonetique",
                             "épelle", "epelle", "comment s'écrit", "comment s ecrit",
                             "épellation", "epellation"]):
        # Chercher une lettre ou un mot à épeler
        alpha_match = re.search(r"(?:épelle|epelle|comment s'écrit|comment s ecrit)\s+([a-z]+)", t)
        if alpha_match:
            mot = alpha_match.group(1).lower()
            epele = " - ".join(_PHONETIQUE.get(c, c.upper()) for c in mot)
            return f"'{mot.upper()}' s'épelle : {epele}"
        # "C comme ?"
        lettre_match = re.search(r"([a-z])\s+comme\s+\?", t)
        if lettre_match:
            c = lettre_match.group(1)
            return f"{c.upper()} comme {_PHONETIQUE.get(c, '?')}"
        return "Précisez la lettre ou le mot à épeler phonétiquement."

    return None


def resoudre_infos_systeme_localement(texte):
    """Répond aux questions d'heure, date, batterie, CPU/RAM localement sans IA."""
    t = texte.lower().replace("?", "").strip()
    maintenant = datetime.now()

    JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    MOIS_FR  = ["janvier", "février", "mars", "avril", "mai", "juin",
                "juillet", "août", "septembre", "octobre", "novembre", "décembre"]

    # --- HEURE ---
    if any(m in t for m in ["quelle heure", "il est quelle heure", "l'heure qu'il est",
                             "quelle est l'heure", "tu as l'heure", "donne-moi l'heure",
                             "il est combien", "c'est quoi l'heure", "heure il est"]):
        h, m = maintenant.hour, maintenant.minute
        return f"Il est {h}h{m:02d}, {USER_NAME}."

    # --- DATE COMPLÈTE ---
    if any(m in t for m in ["quelle date", "on est quel jour", "quel jour on est",
                             "quel jour sommes-nous", "la date d'aujourd'hui", "date du jour",
                             "on est le combien", "quel jour est-on", "c'est quoi la date",
                             "la date aujourd'hui"]):
        jour_semaine = JOURS_FR[maintenant.weekday()]
        mois = MOIS_FR[maintenant.month - 1]
        return f"Nous sommes le {jour_semaine} {maintenant.day} {mois} {maintenant.year}, {USER_NAME}."

    # --- JOUR DE LA SEMAINE SEUL ---
    if any(m in t for m in ["quel jour", "c'est quel jour"]) and "date" not in t:
        return f"Nous sommes {JOURS_FR[maintenant.weekday()]}, {USER_NAME}."

    # --- MOIS ---
    if any(m in t for m in ["quel mois", "on est en quel mois", "c'est quel mois"]):
        return f"Nous sommes en {MOIS_FR[maintenant.month - 1]}, {USER_NAME}."

    # --- ANNÉE ---
    if any(m in t for m in ["quelle année", "on est en quelle année", "c'est quelle année"]):
        return f"Nous sommes en {maintenant.year}, {USER_NAME}."

    # --- ÂGE DU CRÉATEUR ---
    if any(m in t for m in ["quel âge as-tu", "quel age as-tu", "quel âge a le créateur", "quel âge a mon maître",
                             "quel est mon âge", "j'ai quel âge", "j ai quel age"]):
        naissance = datetime(1988, 5, 21)
        age = (maintenant - naissance).days // 365
        return f"Vous avez {age} ans, {USER_NAME}."

    # --- BATTERIE ---
    if any(m in t for m in ["batterie", "autonomie", "niveau de charge", "charge du pc"]):
        if psutil is None:
            return "Le module psutil n'est pas disponible, {USER_NAME}."
        try:
            bat = psutil.sensors_battery()
            if bat:
                pct = int(bat.percent)
                etat = "en charge" if bat.power_plugged else "sur batterie"
                return f"La batterie est à {pct}%, {etat}, {USER_NAME}."
            return "Je ne détecte pas de batterie sur cet appareil, {USER_NAME}."
        except Exception:
            return "Impossible de lire la batterie, {USER_NAME}."

    # --- CPU ---
    if any(m in t for m in ["cpu", "processeur", "utilisation du processeur", "charge du processeur"]):
        if psutil is None:
            return "Le module psutil n'est pas disponible, {USER_NAME}."
        try:
            cpu = psutil.cpu_percent(interval=0.5)
            return f"Le processeur tourne à {cpu}% d'utilisation, {USER_NAME}."
        except Exception:
            return "Impossible de lire le processeur, {USER_NAME}."

    # --- RAM ---
    if any(m in t for m in ["ram", "mémoire ram", "mémoire vive", "utilisation de la mémoire"]):
        if psutil is None:
            return "Le module psutil n'est pas disponible, {USER_NAME}."
        try:
            mem = psutil.virtual_memory()
            utilise = round(mem.used / (1024**3), 1)
            total   = round(mem.total / (1024**3), 1)
            return f"La RAM est à {mem.percent}% — {utilise} Go utilisés sur {total} Go, {USER_NAME}."
        except Exception:
            return "Impossible de lire la RAM, {USER_NAME}."

    # --- UPTIME (depuis combien de temps le PC est allumé) ---
    if any(m in t for m in ["allumé depuis", "uptime", "depuis combien de temps le pc",
                             "depuis quand est allumé"]):
        if psutil is None:
            return "Le module psutil n'est pas disponible, {USER_NAME}."
        try:
            boot = datetime.fromtimestamp(psutil.boot_time())
            delta = maintenant - boot
            heures  = int(delta.total_seconds() // 3600)
            minutes = int((delta.total_seconds() % 3600) // 60)
            return f"Le PC est allumé depuis {heures}h{minutes:02d}, {USER_NAME}."
        except Exception:
            return None

    return None

async def demander_ia(texte):

    global is_thinking
    is_thinking = True
    await send_web_state("thinking")
    try:
        # ── PRIORITÉ 0 — RÉPONSES LOCALES (instantané, sans API) ────────────
        rep_loc = reponse_locale(texte)
        if rep_loc:
            return rep_loc

        # ── PRIORITÉ 1 — CLAUDE (Anthropic) ─────────────────────────────────
        if anthropic_client and _quota_mgr.is_available("claude"):
            print("[CERVEAU] Tentative avec Claude (Anthropic)...")
            try:
                rep_claude = await demander_claude(texte)
                if rep_claude:
                    return rep_claude
                print("[CERVEAU] Claude KO (réponse vide). Bascule suivante.")
            except _QuotaExceededError:
                print(f"[CERVEAU] Claude quota épuisé — cooldown {_quota_mgr.remaining_cooldown('claude')}s. Bascule.")
            except Exception as e:
                print(f"[CERVEAU] Claude erreur ({e}). Bascule suivante.")
        elif anthropic_client and not _quota_mgr.is_available("claude"):
            print(f"[CERVEAU] Claude en cooldown ({_quota_mgr.remaining_cooldown('claude')}s). Bascule directe.")

        cerveau = detecter_cerveau(texte)

        async def _call_gemini():
            if not gemini_actif:
                raise Exception("Clé Gemini non configurée — agent ignoré")
            if not _quota_mgr.is_available("gemini"):
                raise _QuotaExceededError(f"Gemini en cooldown ({_quota_mgr.remaining_cooldown('gemini')}s)")
            print(f"[CERVEAU] Tentative avec Gemini (Liste: {MODELS_LIST})...")
            temp_hist = historique + [types.Content(role="user", parts=[types.Part(text=texte)])]
            prompt_actuel = construire_system_prompt()
            last_err = None
            for model_name in MODELS_LIST:
                try:
                    print(f"[CERVEAU] Essai modele : {model_name} (Timeout 12s)")
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            client.models.generate_content,
                            model=model_name,
                            config=types.GenerateContentConfig(
                                system_instruction=prompt_actuel,
                                temperature=0.7,
                                tools=[types.Tool(google_search=types.GoogleSearch())],
                            ),
                            contents=temp_hist
                        ),
                        timeout=12.0
                    )
                    rep = response.text
                    historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
                    historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
                    _sauvegarder_echange_conv(texte, rep)
                    return rep
                except Exception as e:
                    if _quota_mgr.is_quota_error(e):
                        _quota_mgr.mark_quota_exceeded("gemini")
                        raise _QuotaExceededError(f"Gemini quota sur {model_name}: {e}")
                    print(f"[CERVEAU] Echec {model_name} : {e}")
                    last_err = e
                    continue
            raise last_err or Exception("Tous les modeles Gemini ont echoue")

        async def _call_grok():
            if not _quota_mgr.is_available("grok"):
                raise _QuotaExceededError(f"Grok en cooldown ({_quota_mgr.remaining_cooldown('grok')}s)")
            print("[CERVEAU] Tentative avec Grok (xAI)...")
            rep_grok = await demander_grok(texte)
            if not rep_grok:
                raise Exception("Grok n'a rien renvoyé ou est mal configuré")
            return rep_grok

        # ── ROUTING DYNAMIQUE avec gestion quota ─────────────────────────────
        if cerveau == "GROK" and grok_client:
            try:
                return await _call_grok()
            except _QuotaExceededError as e:
                print(f"[CERVEAU] Grok quota ({e}). Bascule Gemini.")
            except Exception as e:
                print(f"[CERVEAU] Grok erreur ({e}). Bascule Gemini.")
        try:
            return await _call_gemini()
        except _QuotaExceededError as e:
            print(f"[CERVEAU] Gemini quota ({e}). Bascule SerpAPI/Groq/Grok.")
        except _QuotaExceededError as e:
            print(f"[CERVEAU] Gemini quota ({e}). Bascule SerpAPI/Groq/Grok.")
        except Exception as e:
            print(f"[CERVEAU] Gemini erreur ({e}). Bascule SerpAPI.")

        # ── FALLBACKS (Gemini KO ou quota) ───────────────────────────────────
        # --- FALLBACK MÉTÉO/TEMP (HA + OpenMeteo, avant SerpAPI) ---
        t_low = texte.lower()
        _mots_meteo = ["quel temps", "météo", "meteo", "il fait quel temps",
                       "temps qu'il fait", "quel temps il fait", "prévisions",
                       "previsions", "va-t-il pleuvoir", "pleut-il",
                       "fait-il beau", "il va pleuvoir", "température dehors",
                       "temperature dehors", "température extérieure",
                       "temperature exterieure", "combien fait-il dehors",
                       "il fait combien dehors"]
        _mots_temp_int = ["température", "temperature", "il fait chaud",
                          "il fait froid", "combien de degrés",
                          "combien fait-il", "il fait combien"]
        _mots_maison   = ["chez moi", "à la maison", "dans la maison",
                          "intérieur", "interieur", "dans le salon",
                          "dans la chambre", "dans le bureau"]
        _pieces_fallback = {
            "salon"   : "salon",
            "chambre" : "chambre",
            "bureau"  : "bureau",
            "extérieur": "exterieur",
            "dehors"  : "dehors",
        }

        if any(m in t_low for m in _mots_meteo):
            print("[CERVEAU] Requête météo détectée → Home Assistant weather.forecast_amilly")
            reponse_ha = get_meteo_ha()
            if reponse_ha:
                return reponse_ha
            return get_meteo_actuelle(None)

        if any(m in t_low for m in _mots_temp_int):
            for mot_piece, piece_key in _pieces_fallback.items():
                if mot_piece in t_low:
                    entity_id = PIECES_CAPTEURS.get(piece_key)
                    if entity_id:
                        print(f"[CERVEAU] Temp intérieure détectée → HA {entity_id}")
                        temp = ha_get_etat(entity_id)
                        return f"La température dans le {mot_piece} est de {temp} degrés, {USER_NAME}."
            if any(m in t_low for m in _mots_maison):
                entity_id = PIECES_CAPTEURS.get("salon")
                if entity_id:
                    print(f"[CERVEAU] Temp intérieure 'chez moi' → HA {entity_id}")
                    temp = ha_get_etat(entity_id)
                    return f"La température chez vous est de {temp} degrés, {USER_NAME}."

        # --- FALLBACK SERPAPI ---
        if len(texte.split()) > 2:
            res_serp = recherche_web_serpapi(texte)
            if res_serp and "VOTRE_CLE" not in res_serp and "rien trouvé" not in res_serp and "erreur" not in res_serp.lower():
                return "Voici ce que j'ai trouvé sur le web : " + res_serp

        # --- FALLBACK GROQ (LLAMA 3.3) ---
        if groq_client and _quota_mgr.is_available("groq"):
            print("[CERVEAU] Bascule sur Groq (Llama 3.3).")
            try:
                rep_groq = await demander_groq(texte)
                if rep_groq:
                    return rep_groq
            except _QuotaExceededError:
                print(f"[CERVEAU] Groq quota épuisé — cooldown {_quota_mgr.remaining_cooldown('groq')}s.")
            except Exception as e2:
                print(f"[CERVEAU] Groq erreur ({e2}).")
        elif groq_client:
            print(f"[CERVEAU] Groq en cooldown ({_quota_mgr.remaining_cooldown('groq')}s). Ignoré.")

        # --- FALLBACK GROK (xAI) ---
        if grok_client and _quota_mgr.is_available("grok"):
            print("[CERVEAU] Bascule sur Grok (xAI).")
            try:
                return await _call_grok()
            except _QuotaExceededError:
                print(f"[CERVEAU] Grok quota épuisé — cooldown {_quota_mgr.remaining_cooldown('grok')}s.")
            except Exception as e2:
                print(f"[ERREUR IA (Grok repli)] {e2}")
        elif grok_client:
            print(f"[CERVEAU] Grok en cooldown ({_quota_mgr.remaining_cooldown('grok')}s). Ignoré.")
        # --- FALLBACK OLLAMA (100% offline) ---
        print("[CERVEAU] Gemini et Grok KO. Tentative Ollama (local)...")
        rep_ollama = await demander_ollama(texte)
        if rep_ollama:
            return rep_ollama

        # ── Détection : aucune API configurée ou toutes en erreur ──────────
        _aucune_api = (not gemini_actif and not groq_client and not grok_client and not anthropic_client)
        if _aucune_api:
            return (
                "Je suis bien en ligne {USER_NAME}, mais mes moteurs d'intelligence artificielle ne sont pas encore configurés. "
                "Pour libérer tout mon potentiel, vous devez renseigner vos clés API dans le fichier .env. "
                "Consultez le fichier README du projet — vous y trouverez un guide complet pour les obtenir gratuitement. "
                "En attendant, je reste disponible pour toutes vos commandes locales : domotique, heure, calculs, et bien plus encore !"
            )
        return (
            "Désolé {USER_NAME}, tous mes serveurs de réflexion sont actuellement surchargés ou en maintenance, "
            "et mes modèles locaux ne répondent pas non plus. "
            "Je reste disponible pour vos commandes domotiques et locales. "
            "Si ce problème persiste, vérifiez vos clés API dans le fichier .env."
        )
    finally:
        is_thinking = False
        await send_web_state("idle")

async def demander_ia_vision(texte, img_b64):
    """Analyse une image (capture d'écran) avec Gemini Vision."""
    global is_thinking, historique
    is_thinking = True
    await send_web_state("thinking")
    try:
        print("[VISION] Analyse de l'image avec Gemini...")
        
        # Conversion base64 en bytes pour l'API
        img_bytes = base64.b64decode(img_b64)
        image_part = types.Part.from_bytes(
            data=img_bytes,
            mime_type="image/jpeg"
        )
        
        prompt_actuel = construire_system_prompt()
        prompt_actuel += "\n\nIMPORTANT : Tu viens de recevoir une capture d'écran de {USER_NAME}. Analyse-la attentivement et réponds à sa question en te basant sur ce que tu vois."
        
        # On envoie l'image et le texte avec retry en cas de 503
        contents = [
            types.Content(role="user", parts=[image_part, types.Part(text=texte)])
        ]
        
        rep = None
        last_err = None
        for model_name in MODELS_LIST:
            print(f"[VISION] Essai modele : {model_name}")
            for attempt in range(2): # 2 tentatives par modele
                try:
                    print(f"[VISION] Appel modele : {model_name} (Timeout 15s)")
                    response = await asyncio.wait_for(
                        asyncio.to_thread(
                            client.models.generate_content,
                            model=model_name,
                            config=types.GenerateContentConfig(
                                system_instruction=prompt_actuel,
                                temperature=0.7,
                                tools=[types.Tool(google_search=types.GoogleSearch())],
                            ),
                            contents=contents
                        ),
                        timeout=15.0
                    )
                    rep = response.text
                    break
                except Exception as e:
                    if ("503" in str(e) or "overloaded" in str(e).lower()) and attempt < 1:
                        print(f"[VISION] Surcharge {model_name} (503). Retente...")
                        await asyncio.sleep(1)
                        continue
                    print(f"[VISION] Erreur {model_name} : {e}")
                    last_err = e
                    break
            if rep: break
        
        if not rep:
            err_str = str(last_err).lower() if last_err else ""
            if "429" in err_str or "quota" in err_str or "resource_exhausted" in err_str:
                print("[VISION] Quota Gemini epuise — vision impossible sans Gemini.")
                return ("Désolé {USER_NAME}, mon quota Gemini est épuisé pour aujourd'hui. "
                        "La vision par caméra et écran fonctionne uniquement avec Gemini — "
                        "je ne peux donc pas analyser d'images en ce moment. "
                        "Réessayez demain quand le quota sera réinitialisé.")
            print("[VISION] Tous les modeles Gemini ont echoue. Bascule sur Grok (Texte uniquement)...")
            if grok_client:
                return await demander_grok(texte + " (Note: Je n'ai pas pu voir ton écran car mes serveurs de vision sont indisponibles, je réponds donc uniquement à ton texte).")
            raise last_err or Exception("Aucun modele n'a pu analyser l'image")

        # On ajoute la trace dans l'historique (sans l'image pour éviter de saturer la mémoire)
        historique.append(types.Content(role="user", parts=[types.Part(text=f"[Analyse d'écran] {texte}")]))
        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
        
        return rep
    except Exception as e:
        print(f"[VISION] Erreur Gemini Vision : {e}")
        # On évite les accolades dans le message d'erreur pour ne pas perturber l'extracteur JSON
        err_msg = str(e).replace("{", "[").replace("}", "]")
        return f"Désolé {USER_NAME}, je n'ai pas pu analyser votre écran. Erreur : {err_msg}"
    finally:
        is_thinking = False
        await send_web_state("idle")

def detecter_cerveau(texte):
    # Heuristique pour basculer sur Grok uniquement pour X/Twitter
    mots_cles_grok = ["sur x", "twitter", "grok", "elon", "x.com"]
    cmd = texte.lower()
    if any(m in cmd for m in mots_cles_grok):
        return "GROK"
    return "GEMINI"

async def demander_grok(texte):
    if not grok_client:
        return None
    
    try:
        # Conversion de l'historique Gemini vers format OpenAI pour Grok
        messages = [{"role": "system", "content": "Tu es JARVIS, l'IA de {USER_NAME}. Tu utilises actuellement ton module Grok pour les infos en temps reel."}]
        for h in historique[-6:]: # Limiter aux 6 derniers messages pour eviter de saturer le contexte
            role = "user" if h.role == "user" else "assistant"
            msg_text = h.parts[0].text
            messages.append({"role": role, "content": msg_text})
        
        messages.append({"role": "user", "content": texte})
        
        completion = grok_client.chat.completions.create(
            model="grok-3", 
            messages=messages,
            temperature=0.7,
        )
        
        rep = completion.choices[0].message.content
        
        # On synchronise l'historique Gemini
        historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
        _sauvegarder_echange_conv(texte, rep)
        
        return rep
    except Exception as e:
        if _quota_mgr.is_quota_error(e):
            _quota_mgr.mark_quota_exceeded("grok")
            raise _QuotaExceededError(f"Grok quota: {e}")
        print(f"[ERREUR GROK] {e}")
        return None

async def demander_ollama(texte):
    """Appelle un modèle local via Ollama (100% offline)."""
    global historique
    try:
        # On prépare les messages au format Ollama (compatible OpenAI)
        messages = [{"role": "system", "content": "Tu es JARVIS, l'IA de {USER_NAME}. Tu utilises actuellement ton module local Ollama. Réponds en français, de façon concise et élégante."}]
        for h in historique[-4:]:
            role = "user" if h.role == "user" else "assistant"
            messages.append({"role": role, "content": h.parts[0].text})
        messages.append({"role": "user", "content": texte})
        
        last_err = None
        for model_name in OLLAMA_MODELS:
            try:
                print(f"[OLLAMA] Essai modele local : {model_name}")
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        requests.post,
                        f"{OLLAMA_URL}/api/chat",
                        json={"model": model_name, "messages": messages, "stream": False},
                        timeout=30
                    ),
                    timeout=35.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    rep = data.get("message", {}).get("content", "")
                    if rep:
                        historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
                        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
                        _sauvegarder_echange_conv(texte, rep)
                        print(f"[OLLAMA] Reponse recue de {model_name}")
                        return rep
                else:
                    print(f"[OLLAMA] Erreur HTTP {resp.status_code} pour {model_name}")
                    last_err = Exception(f"HTTP {resp.status_code}")
            except Exception as e:
                print(f"[OLLAMA] Echec {model_name} : {e}")
                last_err = e
                continue
        
        print(f"[OLLAMA] Tous les modeles locaux ont echoue")
        return None
    except Exception as e:
        print(f"[ERREUR OLLAMA] {e}")
        return None

async def demander_groq(texte):
    """Appelle Groq (Llama 3.3) en fallback gratuit."""
    if not groq_client:
        return None

    try:
        messages = [{"role": "system", "content": "Tu es JARVIS, l'IA de {USER_NAME}. Tu utilises actuellement le modèle Llama 3.3 de Groq pour répondre rapidement."}]
        for h in historique[-6:]:
            role = "user" if h.role == "user" else "assistant"
            messages.append({"role": role, "content": h.parts[0].text})
        messages.append({"role": "user", "content": texte})

        completion = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model="llama-3.3-70b-versatile",
            messages=messages,
            temperature=0.7,
        )

        rep = completion.choices[0].message.content

        historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
        _sauvegarder_echange_conv(texte, rep)

        return rep
    except Exception as e:
        if _quota_mgr.is_quota_error(e):
            _quota_mgr.mark_quota_exceeded("groq")
            raise _QuotaExceededError(f"Groq quota: {e}")
        print(f"[ERREUR GROQ] {e}")
        return None

async def demander_claude(texte):
    """Appelle Claude (Anthropic) — agent IA principal (priorité 0)."""
    if not anthropic_client:
        return None
    try:
        # Conversion historique Gemini → format Anthropic
        messages = []
        for h in historique[-8:]:
            role = "user" if h.role == "user" else "assistant"
            messages.append({"role": role, "content": h.parts[0].text})
        messages.append({"role": "user", "content": texte})

        response = await asyncio.wait_for(
            asyncio.to_thread(
                anthropic_client.messages.create,
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=construire_system_prompt(),
                messages=messages,
            ),
            timeout=15.0
        )
        rep = response.content[0].text

        # Sync historique global
        historique.append(types.Content(role="user", parts=[types.Part(text=texte)]))
        historique.append(types.Content(role="model", parts=[types.Part(text=rep)]))
        _sauvegarder_echange_conv(texte, rep)

        return rep
    except Exception as e:
        if _quota_mgr.is_quota_error(e):
            _quota_mgr.mark_quota_exceeded("claude")
            raise _QuotaExceededError(f"Claude quota: {e}")
        print(f"[ERREUR CLAUDE] {e}")
        return None

async def action_whatsapp_appel(contact):
    try:
        await parler(f"J'appelle {contact} sur WhatsApp, {USER_NAME}.")
        # Lancement de l'app via le protocole
        _lancer_cible("whatsapp:")
        time.sleep(6) # On laisse le temps a l'app de s'ouvrir et se focuser
        
        # Recherche du contact (Ctrl+F)
        pyautogui.hotkey('ctrl', 'f')
        time.sleep(1)
        pyautogui.typewrite(contact)
        time.sleep(2)
        pyautogui.press('enter')
        time.sleep(3) # On attend que la conversation s'affiche bien
        
        # Utilisation du raccourci clavier officiel pour l'appel audio (plus fiable que la vision)
        print(f"[WHATSAPP] Envoi du raccourci d'appel (Ctrl+Shift+C)...")
        pyautogui.hotkey('ctrl', 'shift', 'c')
        
        # On ajoute quand meme un petit clic de vision en secours si le raccourci ne suffit pas
        time.sleep(2)
        print(f"[WHATSAPP] Verification par vision au cas ou...")
        await jarvis_vision_cliquer("clique sur le bouton 'Appel vocal' ou l icone de telephone qui vient de s afficher en haut a droite")
        
        return True
    except Exception as e:
        print(f"[WHATSAPP ERROR] {e}")
        await parler(f"Desole {USER_NAME}, je n'ai pas pu lancer l'appel WhatsApp. {e}")
        return False

TIKTOK_USERNAME = os.getenv("TIKTOK_USERNAME", "").strip().lstrip("@")


def tiktok_abonnes():
    """Nombre d'abonnés du compte TikTok défini par TIKTOK_USERNAME (.env).
    Lit la page publique du profil ; retourne un entier ou None."""
    if not TIKTOK_USERNAME:
        return None
    try:
        r = requests.get(
            f"https://www.tiktok.com/@{TIKTOK_USERNAME}",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                     "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
            timeout=10,
        )
        if r.status_code != 200:
            return None
        m = re.search(r'"followerCount"\s*:\s*(\d+)', r.text)
        return int(m.group(1)) if m else None
    except Exception as e:
        print(f"[TIKTOK] Lecture impossible : {e}")
        return None


async def reponse_tiktok():
    if not TIKTOK_USERNAME:
        return ("Je ne connais pas votre compte TikTok, {USER_NAME}. "
                "Ajoutez TIKTOK_USERNAME=votre_pseudo dans le fichier .env.")
    n = await asyncio.get_event_loop().run_in_executor(None, tiktok_abonnes)
    if n is None:
        return (f"Je n'arrive pas à lire les abonnés de @{TIKTOK_USERNAME} pour le moment, {{USER_NAME}}. "
                "TikTok bloque parfois les lectures automatiques.")
    nombre = f"{n:,}".replace(",", " ")
    return f"Vous avez actuellement {nombre} abonnés sur TikTok (@{TIKTOK_USERNAME}), {{USER_NAME}}."


async def resoudre_commandes_locales(texte):
    """Détecte et exécute les commandes locales (Spotify, dossiers, apps) sans IA."""
    t = texte.lower().strip()

    # --- TIKTOK : abonnés ---
    if ("tiktok" in t or "tik tok" in t) and any(k in t for k in ["abonn", "follower", "combien"]):
        return await reponse_tiktok()

    # --- IDENTITE / CREATEUR (Priorite 0) ---
    _createur_questions = [
        "qui est ton créateur", "qui est ton createur",
        "qui t'a créé", "qui t'a cree", "qui t'a crée",
        "qui ta créé", "qui ta cree", "qui ta crée",
        "qui t'a fabriqué", "qui t'a fabrique",
        "qui t'a inventé", "qui t'a invente",
        "qui t'a construit", "qui ta construit",
        "qui t'a développé", "qui t'a developpe",
        "qui t'a programmé", "qui t'a programme",
        "qui t'a codé", "qui t'a code",
        "qui t'a conçu", "qui t'a concu",
        "qui ta développé", "qui ta developpe",
        "qui ta programmé", "qui ta programme",
        "qui ta codé", "qui ta code",
        "qui ta conçu", "qui ta concu",
        "c'est qui ton créateur", "c'est qui ton createur",
        "t'as été créé par qui", "t'as ete cree par qui",
        "t'es fait par qui", "tu es fait par qui",
        "tu viens d'où", "tu viens d'ou", "tu viens de ou",
        "d'où tu viens", "d'ou tu viens",
        "qui est derrière toi", "qui est derriere toi",
        "qui est ton père", "qui est ton pere",
        "qui est ton papa",
        "qui est ton développeur", "qui est ton developpeur",
        "qui est ton dev",
        "ton créateur c'est qui", "ton createur c'est qui",
    ]
    if any(q in t for q in _createur_questions):
        import random as _rnd
        _reponses_createur = [
            "J'ai été créé par Rahim Batchabi, {USER_NAME}. C'est grâce à lui que j'existe aujourd'hui.",
            "Mon créateur, c'est Rahim Batchabi. Il m'a conçu de A à Z pour être votre assistant personnel.",
            "Je suis le fruit du travail de Rahim Batchabi. Tout mon code, ma voix, mon intelligence, c'est lui.",
            "Rahim Batchabi est mon créateur. C'est lui qui m'a donné vie, et je dois dire qu'il a fait du bon boulot.",
            "C'est Rahim Batchabi qui m'a développé, {USER_NAME}. Un développeur passionné qui voulait créer l'assistant ultime.",
            "Mon père numérique, c'est Rahim Batchabi. Il m'a programmé avec passion pour vous aider au quotidien.",
            "Rahim Batchabi, {USER_NAME}. C'est le génie derrière mon existence. Vous pouvez le retrouver sur techenclair.fr.",
            "Je suis né dans les lignes de code de Rahim Batchabi. Sans lui, je ne serais qu'un écran noir.",
            "Rahim Batchabi m'a créé. C'est un développeur français qui a voulu rendre l'intelligence artificielle accessible à tous.",
            "Mon créateur s'appelle Rahim Batchabi. Il a mis tout son savoir-faire pour me construire, et je lui en suis reconnaissant.",
        ]
        return _rnd.choice(_reponses_createur)

    # --- AIDE / CAPACITES (Priorite 0) ---
    _aide_questions = [
        "que peux-tu faire", "que peux tu faire", "que sais-tu faire", "que sais tu faire",
        "quelles sont tes capacités", "quelles sont tes capacites",
        "montre moi tes capacités", "montre-moi tes capacités",
        "montre moi ce que tu sais faire", "aide moi", "aide-moi",
        "montre moi tes commandes", "liste tes commandes", "qu'est-ce que tu peux faire"
    ]
    if any(q in t for q in _aide_questions):
        # Envoi IMMEDIAT de l'action help au frontend
        if CONNECTED_CLIENTS:
            async def _dispatch_help():
                msg = json.dumps({"action": "help"})
                await asyncio.gather(*[ws.send(msg) for ws in CONNECTED_CLIENTS], return_exceptions=True)
            asyncio.create_task(_dispatch_help())
        
        import random as _rnd
        _reponses_aide = [
            "J'affiche mes systèmes de bord, {USER_NAME}. Je peux gérer votre musique, lancer des recherches, naviguer sur le globe 3D, ou encore ouvrir vos dossiers personnels. Que souhaitez-vous tester ?",
            "Déploiement des protocoles d'assistance. Voici mes modules actifs : contrôle média, navigation satellite, recherche intelligente et gestionnaire de fichiers. Je suis à vos ordres.",
            "Bien sûr. Je suis capable de localiser n'importe quel point sur Terre, de piloter vos applications, et de répondre à vos questions complexes. Jetez un œil aux suggestions à l'écran.",
            "Initialisation de l'interface d'aide. Je peux aussi bien prendre une capture d'écran que vous donner la météo à l'autre bout du monde. Dites-moi simplement ce qu'il vous faut.",
            "Accès aux bases de données. Je peux automatiser vos tâches répétitives, gérer vos rappels et même vous raconter une blague si l'ambiance est trop sérieuse.",
        ]
        return _rnd.choice(_reponses_aide)

    # --- CONTEXTE ATTENDU (Priorité 0) ---
    global EXPECTED_CONTEXT, EXPECTED_TIMESTAMP
    if EXPECTED_CONTEXT == "folder" and (time.time() - EXPECTED_TIMESTAMP) < 20:
        # On tente d'ouvrir ce que l'utilisateur vient de dire
        # On vérifie si c'est un dossier connu ou un chemin
        mots_cles_dossiers = ["bureau", "document", "téléchargement", "image", "photo", "vidéo", "musique", "corbeille"]
        if any(k in t for k in mots_cles_dossiers) or "\\" in t or "/" in t:
            ok, msg = ouvrir_dossier(t)
            if ok:
                EXPECTED_CONTEXT = None
                return f"Bien sûr, j'ouvre le dossier {t}, {USER_NAME}."

    # --- DOSSIERS (Priorité 1) ---
    if any(k in t for k in ["ouvre tous les dossiers", "ouvre tous mes dossiers", "ouvre mes dossiers", "ouvre les dossiers", "mes dossiers", "range mes dossiers", "mosaïque dossiers"]):
        return arranger_fenetres_dossiers()

    # Demande de dossier sans nom (Conversational)
    if any(t == k for k in ["ouvre mon dossier", "ouvre un dossier", "va dans mon dossier", "lance mon dossier", "ouvre le dossier", "lance le dossier"]):
        EXPECTED_CONTEXT = "folder"
        EXPECTED_TIMESTAMP = time.time()
        return "Lequel Monsieur ?"

    prefixes_dossiers = [
        "ouvre le dossier ", "ouvre mon dossier ", "ouvre le répertoire ", "ouvre le repertoire ", 
        "ouvre dossier ", "ouvre ", "mets ", "lance le dossier ", "lance mon dossier ", 
        "lance dossier ", "lance ", "affiche le dossier ", "affiche mon dossier ",
        "va dans le dossier ", "va dans mon dossier ", "va au dossier ", "ouvre-moi le dossier ",
        "ouvre moi le dossier ", "lance-moi le dossier ", "lance moi le dossier "
    ]
    # On vérifie d'abord si c'est un dossier connu
    mots_cles_dossiers = ["bureau", "document", "téléchargement", "image", "photo", "vidéo", "musique", "corbeille"]
    
    for prefix in prefixes_dossiers:
        if t.startswith(prefix):
            potentiel_dossier = t.replace(prefix, "").strip()
            # Si le mot après le préfixe est un dossier connu, on l'ouvre
            if any(k in potentiel_dossier for k in mots_cles_dossiers):
                ok, msg = ouvrir_dossier(potentiel_dossier)
                if ok: return f"J'ouvre le dossier {potentiel_dossier}, {USER_NAME}."

    # --- MODE BOULOT (Priorité 1 bis) ---
    if any(k in t for k in ["au boulot", "mode boulot", "mode travail", "on bosse", "mode bureau", "commence le boulot"]):
        return await mode_boulot()

    # --- APPLICATIONS STANDARD & CATALOGUE (Priorité 2) ---
    # IMPORTANT : ces checks doivent être AVANT la détection Spotify car
    # "lance " est aussi un préfixe Spotify → "lance steam" partirait sinon vers Spotify.
    mots_ouvrir = ["ouvre", "lance", "démarre", "démarres", "ouvrir", "lancer"]
    mots_fermer = ["ferme", "quitte", "stoppe", "éteins", "coupe", "fermer", "quitter"]

    apps_standard = {
        "calculatrice":            "calc.exe",
        "notepad":                 "notepad.exe",
        "bloc-notes":              "notepad.exe",
        "bloc notes":              "notepad.exe",
        "paint":                   "mspaint.exe",
        "moniteur d'activité":     "taskmgr.exe",
        "gestionnaire de tâches":  "taskmgr.exe",
        "gestionnaire de taches":  "taskmgr.exe",
        "task manager":            "taskmgr.exe",
        "préférences système":     "ms-settings:",
        "paramètres":              "ms-settings:",
        "parametres":              "ms-settings:",
        "réglages":                "ms-settings:",
        "reglages":                "ms-settings:",
        "explorateur de fichiers": "explorer.exe",
        "explorateur":             "explorer.exe",
        "finder":                  "explorer.exe",
        "powershell":              "powershell.exe",
        "terminal":                "wt.exe",
        "cmd":                     "cmd.exe",
        "panneau de configuration": "control.exe",
        "capture d'écran":         "ms-screenclip:",
        "capture d'ecran":         "ms-screenclip:",
        "outil capture":           "snippingtool.exe",
        "mémos vocaux":            r"shell:AppsFolder\Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe!App",
        "enregistreur vocal":      r"shell:AppsFolder\Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe!App",
        "magnétophone":            r"shell:AppsFolder\Microsoft.WindowsSoundRecorder_8wekyb3d8bbwe!App",
        "table des caractères":    "charmap.exe",
        "caractères spéciaux":     "charmap.exe",
        "utilitaire de disque":    "diskmgmt.msc",
        "nettoyage de disque":     "cleanmgr.exe",
        "informations système":    "msinfo32.exe",
        "info système":            "msinfo32.exe",
        "info systeme":            "msinfo32.exe",
    }
    for nom, cmd_app in apps_standard.items():
        if f"ouvre {nom}" in t or f"lance {nom}" in t or f"démarre {nom}" in t:
            _lancer_cible(cmd_app)
            return f"J'ouvre {nom}, {USER_NAME}."

    for cle, info in _APPS_CATALOGUE.items():
        if not re.search(r'(?<!\w)' + re.escape(cle) + r'(?!\w)', t):
            continue
        if any(m in t for m in mots_fermer):
            ok = _fermer_app(info["noms"])
            if ok:
                return f"J'ai fermé {info['label']}, {USER_NAME}."
            return f"Je n'ai pas trouvé {info['label']} en cours d'exécution."
        if any(m in t for m in mots_ouvrir):
            _boulot_lancer(info["label"], info["noms"], chemins_hints=info["hints"], uri=info.get("uri"))
            return f"Je lance {info['label']}, {USER_NAME}."

    # --- SPOTIFY / MUSIQUE (Priorité 3) ---
    # YouTube music spécifique — doit être AVANT le check Spotify
    if any(k in t for k in ["musique sur youtube", "met de la musique sur youtube", "mets de la musique sur youtube"]):
        url = YOUTUBE_MUSIQUE_URL or "https://www.youtube.com/watch?v=Cr8K88UcO0s"
        webbrowser.open(url, new=2, encoding="utf-8")
        time.sleep(5)
        pyautogui.press('f')
        return "C'est parti {USER_NAME}, je lance votre musique sur YouTube."

    # Playlist Spotify par défaut — doit être avant le bloc de recherche générique
    if any(k in t for k in [
        "met de la musique", "mets de la musique",
        "met de la musique sur spotify", "mets de la musique sur spotify",
        "met de la musique sur sportify", "mets de la musique sur sportify",
        "musique sur spotify", "musique sur sportify",
        "lance ma playlist", "ma playlist"
    ]):
        ok = spotify_lancer_playlist(SPOTIFY_MUSIQUE_URI)
        if ok:
            return "C'est parti {USER_NAME}, je lance votre playlist sur Spotify."
        return "Je n'ai pas réussi à ouvrir Spotify, {USER_NAME}."

    if any(k in t for k in ["ouvre spotify", "lance spotify", "démarre spotify"]):
        return await spotify_ouvrir()

    if any(k in t for k in ["mets en pause", "stop la musique", "arrête la musique"]):
        return await spotify_stop()
    if any(k in t for k in ["lecture", "remets la musique", "reprends la musique"]):
        return await spotify_lecture_pause()
    if any(k in t for k in ["suivante", "chanson suivante", "piste suivante"]):
        return await spotify_suivant()
    if any(k in t for k in ["précédente", "chanson précédente", "reviens en arrière"]):
        return await spotify_precedent()
    if any(k in t for k in ["monte le volume", "augmente le son", "plus fort"]):
        return await spotify_volume("monter")
    if any(k in t for k in ["baisse le son", "baisse le volume", "moins fort"]):
        return await spotify_volume("baisser")

    # Recherche Spotify générique — en dernier pour ne pas avaler les commandes apps
    prefixes_recherche = ["joue du ", "joue de la ", "mets du ", "mets de la ", "joue ", "recherche "]
    for prefix in prefixes_recherche:
        if t.startswith(prefix):
            recherche = t.replace(prefix, "").replace(" sur spotify", "").strip()
            if len(recherche) > 1:
                return await spotify_rechercher(recherche)

    raccourcis_dossiers = {
        "bureau": "bureau", "documents": "documents",
        "téléchargements": "downloads", "téléchargement": "downloads",
        "images": "images", "vidéos": "videos", "musique": "musique"
    }
    for cle, chemin in raccourcis_dossiers.items():
        if f"ouvre mon {cle}" in t or f"ouvre le {cle}" in t or t == f"ouvre {cle}":
            ouvrir_dossier(chemin)
            return f"J'ouvre votre dossier {cle}, {USER_NAME}."

    # --- DOSSIER / APPLICATION INCONNU(E) ---
    # Si l'utilisateur demande d'ouvrir/lancer quelque chose qu'on ne connait pas
    _mots_action = ["ouvre ", "lance ", "démarre ", "démarres ", "ouvrir ", "lancer ", "ouvre le ", "ouvre la ",
                     "ouvre mon ", "ouvre ma ", "lance le ", "lance la ", "lance mon ", "lance ma ",
                     "ouvre le dossier ", "ouvre mon dossier ", "ouvre l'application ", "lance l'application ",
                     "ouvre l'appli ", "lance l'appli ", "ouvre le logiciel ", "lance le logiciel "]
    for mot in _mots_action:
        if t.startswith(mot):
            nom_demande = t.replace(mot, "").strip().rstrip(".")
            if len(nom_demande) > 1:
                import random as _rnd
                _reponses_inconnu = [
                    f"Désolé {USER_NAME}, mon créateur Rahim Batchabi n'a pas encore ajouté \"{nom_demande}\" dans mes fonctionnalités. Mais vous pouvez l'ajouter vous-même gratuitement avec le logiciel Antigravity de chez Google.",
                    f"Je ne connais pas \"{nom_demande}\" pour l'instant, {USER_NAME}. Rahim Batchabi, mon développeur, n'a pas intégré cette fonction. Cependant, vous pouvez la créer facilement avec Antigravity de Google, c'est gratuit.",
                    f"Hmm, \"{nom_demande}\" ne fait pas partie de mes compétences actuelles. Mon créateur Rahim Batchabi pourra peut-être l'ajouter dans une future mise à jour. En attendant, essayez Antigravity de Google pour personnaliser vos commandes gratuitement.",
                    f"\"{nom_demande}\" n'est pas dans ma base de données, {USER_NAME}. Rahim Batchabi n'a pas encore programmé cette action. Bonne nouvelle : avec Antigravity de chez Google, vous pouvez l'ajouter vous-même sans frais.",
                    f"Je ne suis pas encore capable d'ouvrir \"{nom_demande}\", {USER_NAME}. Mon créateur Rahim Batchabi travaille constamment à m'améliorer. En attendant, le logiciel Antigravity de Google vous permet d'étendre mes fonctionnalités gratuitement.",
                    f"Cette fonctionnalité n'a pas été ajoutée par Rahim Batchabi, mon créateur. Mais ne vous inquiétez pas, {USER_NAME}, vous pouvez utiliser Antigravity de chez Google pour ajouter \"{nom_demande}\" gratuitement.",
                ]
                return _rnd.choice(_reponses_inconnu)

    return None

async def traiter_reponse_ia(texte_utilisateur, mobile_ws=None):
    global MODE_IRON_MAN, jarvis_actif, dernier_message, _skip_pc_audio, EXPECTED_CONTEXT, EXPECTED_TIMESTAMP, USER_NAME
    # Reset du flag audio au début de chaque commande
    _skip_pc_audio = False
    
    prompt = texte_utilisateur.strip()
    if not prompt: return
    prompt_clean = prompt.lower()

    # --- ÉTAPE 0 : CONTEXTE D'ATTENTE (ex: Changement de prénom) ---
    if EXPECTED_CONTEXT == "change_name" and time.time() < EXPECTED_TIMESTAMP:
        USER_NAME = prompt.strip()
        sauvegarder_profil()
        EXPECTED_CONTEXT = None
        rep = f"C'est noté. Je vous appellerai désormais {USER_NAME}. Comment puis-je vous aider ?"
        await parler(rep, mobile_ws=mobile_ws)
        return

    # --- ÉTAPE 1 : DÉTECTION CHANGEMENT DE PRÉNOM ---
    if all(k in prompt_clean for k in ["changer", "prénom"]) or "appelle-moi" in prompt_clean:
        EXPECTED_CONTEXT = "change_name"
        EXPECTED_TIMESTAMP = time.time() + 60
        rep = f"Très bien. Quel est le prénom que vous souhaitez que j'utilise pour vous ? Dites-le moi ou écrivez-le."
        await parler(rep, mobile_ws=mobile_ws)
        return

    # TENTATIVE DE RÉSOLUTION LOCALE (Commandes, Math, Français, etc.)
    reponse = await resoudre_commandes_locales(texte_utilisateur)
    if not reponse: reponse = resoudre_infos_systeme_localement(texte_utilisateur)
    if not reponse: reponse = resoudre_math_localement(texte_utilisateur)
    if not reponse: reponse = resoudre_francais_localement(texte_utilisateur)
    if not reponse: reponse = resoudre_conversion_localement(texte_utilisateur)
    if not reponse: reponse = resoudre_traduction_localement(texte_utilisateur)
    if not reponse: reponse = await resoudre_globe_localement(texte_utilisateur)
    if not reponse: reponse = await resoudre_extras_locaux(texte_utilisateur)
    
    # VISION (Regarde mon écran)
    if not reponse:
        t = texte_utilisateur.lower()
        if any(keyword in t for keyword in ["regarde mon écran", "analyse mon écran", "vois-tu mon écran", "qu'est-ce qu'il y a sur mon écran"]):
            await parler("Bien sûr {USER_NAME}, laissez-moi jeter un œil...")
            img_b64 = await request_screen_capture()
            if img_b64:
                reponse = await demander_ia_vision(texte_utilisateur, img_b64)
            else:
                reponse = "Je suis désolé {USER_NAME}, mais je n'ai pas pu capturer votre écran. Assurez-vous d'avoir cliqué sur 'Activer la vision' sur l'interface et d'avoir autorisé le partage."
        
        # CAMERA (Lance la caméra / Analyse visuelle / Objets / Tenue)
        camera_keywords = [
            # Caméra générale (avec ET sans accents pour la reconnaissance vocale)
            "lance la caméra", "lance la camera",
            "ouvre la caméra", "ouvre la camera",
            "regarde avec la caméra", "regarde avec la camera",
            "active la caméra", "active la camera",
            "analyse ce que tu vois", "qu'est-ce que tu vois",
            "regarde-moi", "regarde moi", "analyse-moi", "analyse moi",
            # Tenue / Vêtements
            "ma tenue", "mes vêtements", "mes vetements",
            "comment je suis habillé", "comment je suis habille",
            "montre-moi", "est-ce que ça me va", "est-ce que ca me va",
            "ça me va", "ca me va",
            "qu'est-ce que je porte", "je porte quoi",
            # Objets / Identification
            "c'est quoi ça", "c'est quoi ca", "qu'est-ce que c'est",
            "décris cet objet", "decris cet objet", "c'est quoi cet objet",
            "identifie", "reconnais", "qu'est-ce que je te montre",
            "je te montre", "regarde ça", "regarde ca",
            "tu vois quoi", "dis-moi ce que c'est", "analyse ça", "analyse ca",
            # Webcam
            "webcam", "la cam",
        ]
        if any(keyword in t for keyword in camera_keywords):
            reponse = await jarvis_vision_camera(texte_utilisateur)

    if not reponse:
        reponse = await demander_ia(texte_utilisateur)
    
    print(f"[JARVIS] {reponse}")

    # Si commande mobile : activer le flag pour couper l'audio PC et répondre via mobile
    if mobile_ws:
        _skip_pc_audio = True

    # Recherche de TOUS les blocs JSON dans la réponse
    json_blocks = re.findall(r'\{.*?\}', reponse, re.DOTALL)
    
    if not json_blocks:
        await parler(reponse)
        _skip_pc_audio = False
        return

    for block in json_blocks:
        try:
            print(f"[JARVIS] Execution de l'action : {block}")
            # Timeout de 15s pour chaque action pour eviter de freezer Jarvis
            data = json.loads(block)
            action = data.get("action", "")
            
            # On execute l'action avec un timeout
            try:
                # Note: On utilise asyncio.wait_for pour les actions asynchrones
                # Les actions synchrones comme ha_lumiere devraient idéalement être async aussi
                # mais pour l'instant on les laisse ainsi ou on les wrappe.
                pass 
            except asyncio.TimeoutError:
                print(f"[ACTION ERROR] Timeout sur l'action {action}")
                if grok_client:
                    await parler("C'est un peu long {USER_NAME}, je demande une vérification à Grok.")
                    rep_grok = await demander_grok(texte_utilisateur + " (L'action domotique a expiré, peux-tu répondre à l'utilisateur ?)")
                    if rep_grok: await parler(rep_grok)
                continue

            if action == "mode_iron_man":
                etat = data.get("etat", "off")
                MODE_IRON_MAN = (etat == "on")
                msg = "Mode Iron Man activé, Monsieur. Je reste à l'écoute de vos signaux." if MODE_IRON_MAN else "Mode Iron Man désactivé. Je repasse en veille domotique."
                await parler(msg)
            elif action == "memoriser":
                cle    = data.get("cle",    "info")
                valeur = data.get("valeur", "")
                ajouter_memoire(cle, valeur)
                await parler(f"Bien note {USER_NAME}, je me souviendrai que {valeur}.")
            elif action == "oublier":
                cle     = data.get("cle", "")
                success = supprimer_memoire(cle)
                if success:
                    await parler("Information oubliee, {USER_NAME}.")
                else:
                    await parler("Je n avais pas cette information en memoire.")
            elif action == "lister_memoire":
                memoire = charger_memoire()
                if not memoire:
                    await parler("Aucune information personnalisee en memoire, {USER_NAME}.")
                else:
                    lignes = ["Voici ce que je sais sur vous {USER_NAME}."]
                    for cle, data_m in memoire.items():
                        lignes.append(f"{cle} : {data_m['valeur']}.")
                    await parler(" ".join(lignes))
            elif action == "ouvrir_dossier":
                chemin = data.get("chemin", "bureau")
                ok, resultat = ouvrir_dossier(chemin)
                if ok:
                    await parler("Dossier ouvert, {USER_NAME}. Dites-moi si vous voulez que je le trie.")
                else:
                    await parler(f"Je n ai pas trouve ce dossier, {USER_NAME}. {resultat}")
            elif action == "lister_dossier":
                contenu, err = lister_dossier()
                if err:
                    await parler(err)
                else:
                    nb_fichiers = len(contenu["fichiers"])
                    nb_dossiers = len(contenu["dossiers"])
                    await parler(f"Le dossier contient {nb_fichiers} fichiers et {nb_dossiers} sous-dossiers, {USER_NAME}.")
            elif action == "trier_par_type":
                await parler("Je trie vos fichiers par type, {USER_NAME}. Un instant.")
                ok, msg = trier_par_type()
                await parler(msg if ok else f"Probleme lors du tri : {msg}")
            elif action == "trier_par_date":
                await parler("Je trie vos fichiers par date, {USER_NAME}. Un instant.")
                ok, msg = trier_par_date()
                await parler(msg if ok else f"Probleme lors du tri : {msg}")
            elif action == "trier_complet":
                await parler("Je trie vos fichiers par type puis par date dans chaque categorie, {USER_NAME}.")
                ok, msg = trier_par_type_puis_date()
                await parler(msg if ok else f"Probleme lors du tri : {msg}")
            elif action == "creer_dossier":
                nom     = data.get("nom", "Nouveau Dossier")
                ok, msg = creer_sous_dossier(nom)
                await parler(msg if ok else f"Erreur : {msg}")
            elif action == "renommer_fichier":
                ancien  = data.get("ancien", "")
                nouveau = data.get("nouveau", "")
                ok, msg = renommer_fichier(ancien, nouveau)
                await parler(msg if ok else f"Erreur : {msg}")
            elif action == "deplacer_fichier":
                fichier = data.get("fichier",     "")
                dest    = data.get("destination", "")
                ok, msg = deplacer_fichier(fichier, dest)
                await parler(msg if ok else f"Erreur : {msg}")
            elif action == "chercher_fichier":
                nom        = data.get("nom", "")
                resultats, err = chercher_fichier(nom)
                if err:
                    await parler(err)
                elif not resultats:
                    await parler(f"Aucun fichier contenant {nom} n a ete trouve, {USER_NAME}.")
                else:
                    noms = [os.path.basename(r) for r in resultats[:5]]
                    await parler(f"J ai trouve {len(resultats)} fichier(s). Par exemple : {', '.join(noms)}.")
            elif action == "ha_lumiere":
                piece      = data.get("piece",      "salon")
                etat       = data.get("etat",       "on")
                couleur    = data.get("couleur",    None)
                luminosite = data.get("luminosite", None)
                entity_id  = PIECES_LUMIERES.get(piece, f"light.{piece}")
                rgb        = COULEURS_MAP.get(couleur) if couleur else None
                ha_lumiere(entity_id, etat, luminosite, rgb)
                
                # Message de confirmation amélioré
                if etat == "off":
                    msg = f"J'éteins {piece}."
                else:
                    details = []
                    if couleur: details.append(f"en {couleur}")
                    if luminosite is not None: 
                        pourcent = int((int(luminosite)/255)*100)
                        details.append(f"à {pourcent}%")
                    
                    if details:
                        msg = f"C'est fait, {piece} est réglé{' '.join(details)}."
                    else:
                        msg = f"Lumière {piece} allumée."
                await parler(msg)
            elif action == "ha_prise":
                piece     = data.get("piece", "bureau")
                etat      = data.get("etat",  "on")
                entity_id = PIECES_PRISES.get(piece, f"switch.prise_{piece}")
                ha_interrupteur(entity_id, etat)
                msg = f"Prise {piece} {'activée' if etat == 'on' else 'désactivée'}."
                await parler(msg)
            elif action == "ha_temperature":
                piece     = data.get("piece", "salon")
                entity_id = PIECES_CAPTEURS.get(piece)
                if entity_id:
                    temp = ha_get_etat(entity_id)
                    await parler(f"La température dans le {piece} est de {temp} degrés.")
                else:
                    await parler(f"Désolé, je n'ai pas de capteur configuré pour le {piece}.")
            elif action == "ha_humidite":
                piece     = data.get("piece", "bureau")
                entity_id = PIECES_HUMIDITE.get(piece)
                if entity_id:
                    humi = ha_get_etat(entity_id)
                    await parler(f"Le taux d'humidité dans le {piece} est de {humi}%.")
                else:
                    await parler(f"Je n'ai pas de capteur d'humidité pour le {piece}.")
            elif action == "ha_batterie":
                appareil  = data.get("appareil", "").lower()
                entity_id = APPAREILS_BATTERIE.get(appareil)
                if entity_id:
                    batt = ha_get_etat(entity_id)
                    if batt == "unknown":
                        await parler(f"Je n'arrive pas à récupérer l'état de la batterie pour {appareil}.")
                    else:
                        suff = ""
                        if "telephone" in appareil or "papa" in appareil or USER_NAME.lower() in appareil:
                            suff = "Votre téléphone est à "
                        elif "julie" in appareil or "maman" in appareil:
                            suff = "Le téléphone de Julie est à "
                        else:
                            suff = f"La batterie de {appareil} est à "
                        await parler(f"{suff}{batt}%.")
                else:
                    await parler(f"Je n'ai pas l'appareil {appareil} dans ma liste de batterie.")
            elif action == "ha_thermostat":
                temp = data.get("temperature", 20)
                ha_thermostat("climate.thermostat", temp)
                await parler(f"Thermostat réglé à {temp} degrés.")
            elif action == "ha_scene":
                nom      = data.get("nom", "")
                scene_id = f"scene.{nom}"
                ha_scene(scene_id)
                await parler(f"Ambiance {nom} activée.")
            elif action == "ha_alarme":
                etat = data.get("etat", "on")
                if etat == "on":
                    ha_appeler_service("alarm_control_panel", "alarm_arm_away", "alarm_control_panel.home_base_2")
                    await parler("Alarme activée.")
                else:
                    ha_appeler_service("alarm_control_panel", "alarm_disarm", "alarm_control_panel.home_base_2")
                    await parler("Alarme désactivée.")
            elif action == "ha_simulation":
                etat = data.get("etat", "on")
                ha_interrupteur("switch.simulation", etat)
                msg = "Simulation de présence activée." if etat == "on" else "Simulation de présence désactivée."
                await parler(msg)
            elif action == "ha_anniversaires":
                events = ha_get_calendrier("calendar.anniversaires")
                if not events:
                    await parler("Rien de prévu aujourd'hui.")
                else:
                    noms = [e.get("summary", "Anniversaire sans nom") for e in events]
                    if len(noms) == 1:
                        await parler(f"Aujourd'hui, nous fêtons l'anniversaire de {noms[0]}. N'oubliez pas de lui souhaiter !")
                    else:
                        liste = ", ".join(noms[:-1]) + " et " + noms[-1]
                        await parler(f"Aujourd'hui, il y a plusieurs anniversaires : {liste}. C'est une journée chargée !")
            elif action == "ha_consommation":
                entity_id = PIECES_CAPTEURS.get("consommation")
                puissance = ha_get_etat(entity_id)
                if puissance == "unknown" or puissance == "inconnu":
                    await parler("Je n'arrive pas à lire la consommation électrique pour le moment.")
                else:
                    await parler(f"La consommation actuelle de la maison est de {puissance} Volt-Ampères.")
            elif action == "ha_tiktok":
                await parler((await reponse_tiktok()).replace("{USER_NAME}", USER_NAME))
            elif action == "ha_oeufs":
                entity_id = PIECES_CAPTEURS.get("oeufs")
                # On récupère l'état (le dernier choix) et le moment de la modif
                try:
                    r = requests.get(f"{HA_URL}/api/states/{entity_id}", headers=HA_HEADERS, timeout=5)
                    data = r.json()
                    last_changed = data.get("last_changed", "")
                    if last_changed:
                        dt = datetime.fromisoformat(last_changed.replace("Z", "+00:00"))
                        phrase = dt.strftime("le %d %B à %Hh%M")
                        await parler(f"Le dernier ramassage des œufs a été enregistré {phrase}.")
                    else:
                        await parler("Je n'ai pas d'historique pour le ramassage des œufs.")
                except:
                    await parler("Je n'arrive pas à accéder aux informations sur les œufs.")
            elif action == "ha_energie":
                periode  = data.get("periode", "mois")
                appareil = data.get("appareil", "")
                
                if appareil:
                    appareil_clean = appareil.lower()
                    entite = APPAREILS_ENERGIE.get(appareil_clean)
                    if entite:
                        val = ha_get_etat(entite)
                        if val != "inconnu" and val != "unknown":
                            kwh = float(val)
                            await parler(f"La consommation de {appareil} pour ce mois est de {kwh:.1f} kWh.")
                        else:
                            await parler(f"Je n'ai pas de données de consommation pour {appareil} pour le moment.")
                    else:
                        await parler(f"Je n'ai pas d'appareil nommé {appareil} dans mon suivi énergétique.")
                elif periode == "hier":
                    total_kwh = 0
                    total_cost = 0
                    try:
                        for i in range(1, 7):
                            e_id = f"sensor.lixee_zlinky_tic_zlinky_p{i}_daily"
                            val = ha_get_etat(e_id, attribut="last_period")
                            if val != "inconnu" and val != "unknown":
                                k = float(val)
                                total_kwh += k
                                total_cost += k * HA_TARIFS.get(f"p{i}", 0.16)
                        await parler(f"Hier, la maison a consommé {total_kwh:.1f} kWh, pour un coût estimé à {total_cost:.2f} euros.")
                    except:
                        await parler("J'ai eu un problème pour calculer la consommation d'hier.")
                else: # mois
                    total_kwh = 0
                    total_cost = 0
                    try:
                        for i in range(1, 7):
                            e_id = f"sensor.lixee_zlinky_tic_zlinky_p{i}_mensuel"
                            val = ha_get_etat(e_id)
                            if val != "inconnu" and val != "unknown":
                                k = float(val)
                                total_kwh += k
                                total_cost += k * HA_TARIFS.get(f"p{i}", 0.16)
                        await parler(f"Ce mois-ci, la consommation totale est de {total_kwh:.1f} kWh, pour un montant de {total_cost:.2f} euros.")
                    except:
                        await parler("Je n'ai pas pu calculer la consommation mensuelle.")
            elif action == "ha_aspirateur":
                commande = data.get("commande", "start")
                if commande == "start":
                    ha_appeler_service("vacuum", "start", "vacuum.bob")
                    await parler("C'est parti, Bob lance le nettoyage.")
                elif commande == "stop":
                    ha_appeler_service("vacuum", "stop", "vacuum.bob")
                    await parler("J'ai arrêté l'aspirateur.")
                elif commande == "pause":
                    ha_appeler_service("vacuum", "pause", "vacuum.bob")
                    await parler("Bob est en pause.")
                elif commande == "base":
                    ha_appeler_service("vacuum", "return_to_base", "vacuum.bob")
                    await parler("Bob retourne à sa base.")
            elif action == "create_doc":
                titre   = data.get("title",   "Document JARVIS")
                contenu = data.get("content", "")
                result  = creer_google_doc(titre, contenu)
                await parler(result)
            elif action == "write_doc":
                contenu = data.get("content", "")
                result  = modifier_google_doc(contenu)
                await parler(result)
            elif action == "create_sheet":
                titre  = data.get("title", "Feuille JARVIS")
                result = creer_google_sheet(titre)
                await parler(result)
            elif action == "read_emails":
                result = lire_emails()
                await parler(f"Voici vos derniers emails {USER_NAME}. {result}")
            elif action == "read_calendar":
                result = lister_evenements_calendar()
                await parler(f"Voici vos prochains evenements {USER_NAME}. {result}")
            elif action == "meteo":
                ville = data.get("ville") or None
                await parler("Je consulte la meteo, un instant {USER_NAME}.")
                result = get_meteo_actuelle(ville)
                await parler(result)
            elif action == "alerte_meteo":
                ville = data.get("ville") or None
                result = get_alertes_meteo(ville)
                await parler(result)
            elif action == "recherche_web":
                query = data.get("query", "")
                await parler(f"Je lance une recherche sur internet pour {query}.")
                result = recherche_web_serpapi(query)
                await parler(result)
            elif action == "sport_resultats":
                equipe = data.get("equipe") or None
                ligue  = data.get("ligue")  or None
                print(f"[SPORT] Action sport_resultats pour {equipe or ligue}")
                await parler(f"Je cherche les informations pour {equipe or ligue}, un instant.")
                result = get_resultats_football(equipe=equipe, ligue=ligue)
                if "pas trouvé" in result or "Impossible" in result:
                    print(f"[SPORT] Echec recherche locale. Verification avec Grok...")
                    if grok_client:
                        res_grok = await demander_grok(f"{USER_NAME} veut savoir : {texte_utilisateur}. Je n'ai pas trouvé l'info dans ma base de données football, peux-tu chercher pour lui ?")
                        if res_grok: result = res_grok
                await parler(result)
            elif action == "sport_classement":
                ligue  = data.get("ligue", "Ligue 1")
                await parler(f"Je recupere le classement {ligue}.")
                result = get_classement_football(ligue=ligue)
                await parler(result)
            elif action == "sport_live":
                question = data.get("question", "derniers resultats sportifs 2026")
                await parler("Je recherche les derniers resultats en direct, un instant {USER_NAME}.")
                result = get_resultats_sport_gemini(question)
                await parler(result)
            elif action == "voir_ecran":
                inst = data.get("instruction", "")
                res = await jarvis_vision_cliquer(inst)
                await parler(res)
            elif action == "whatsapp_appel":
                contact = data.get("contact", "Ma vie")
                await action_whatsapp_appel(contact)
            elif action == "vision_ecrire":
                inst = data.get("instruction", "")
                txt  = data.get("texte", "")
                res  = await jarvis_vision_ecrire(inst, txt)
                await parler(res)
            elif action == "vision_chercher_sur_site":
                txt = data.get("texte", "")
                await parler(f"Je cherche la barre de recherche sur ce site, {USER_NAME}.")
                res = await jarvis_vision_rechercher_sur_site(txt)
                await parler(res)
            elif action == "lance_camera":
                res = await jarvis_vision_camera(texte_utilisateur)
                await parler(res)
            elif action == "vision_navigateur":
                res = await jarvis_vision_navigateur(texte_utilisateur)
                await parler(res)
            elif action == "spotify_ouvrir":
                await parler("J'ouvre Spotify, {USER_NAME}.")
                res = await spotify_ouvrir()
                await parler(res)
            elif action == "spotify_rechercher":
                recherche = data.get("recherche", "")
                await parler(f"Je recherche '{recherche}' sur Spotify, {USER_NAME}.")
                res = await spotify_rechercher(recherche)
                await parler(res)
            elif action == "spotify_lecture_pause":
                res = await spotify_lecture_pause()
                await parler(res)
            elif action == "spotify_stop":
                res = await spotify_stop()
                await parler(res)
            elif action == "spotify_suivant":
                res = await spotify_suivant()
                await parler(res)
            elif action == "spotify_precedent":
                res = await spotify_precedent()
                await parler(res)
            elif action == "spotify_volume":
                direction = data.get("direction", "monter")
                paliers   = data.get("paliers", 4)
                res = await spotify_volume(direction, paliers)
                await parler(res)

        except Exception as e:
            print(f"[ACTION ERROR] Block failed: {block} | Error: {e}")
            if grok_client:
                print("[JARVIS] Bascule sur Grok suite a une erreur d'action...")
                res_grok = await demander_grok(f"{USER_NAME} m'a demandé : {texte_utilisateur}. J'ai tenté de lancer une action mais j'ai eu une erreur technique ({e}). Peux-tu prendre le relais et lui répondre élégamment ?")
                if res_grok: await parler(res_grok)
            continue

    # Si du texte reste après les commandes, on ne fait rien de plus car `parler` a déjà été appelé pour chaque action ou la réponse globale.
    # Réinitialiser le flag audio PC
    _skip_pc_audio = False

def nettoyer_commande(texte):
    t = texte.lower().strip()
    for variante in ["jarvis,", "jarvis"]:
        if t.startswith(variante):
            t = t[len(variante):].strip()
    return t

WAKE_WORD       = "jarvis"
SESSION_TIMEOUT = 30
STOP_PARLER      = False
is_listening     = False
is_speaking      = False
jarvis_actif     = False
dernier_message  = 0
interface_deja_connectee = False


# ══════════════════════════════════════════════════════════════
#  DÉTECTION MICROPHONE — Énumération + Fallback automatique
# ══════════════════════════════════════════════════════════════

_JARVIS_CONFIG_PATH = os.path.join(DATA_DIR, "jarvis_config.json")

def _charger_config() -> dict:
    """Charge jarvis_config.json ou retourne un dict vide si absent/corrompu."""
    try:
        if os.path.exists(_JARVIS_CONFIG_PATH):
            import json
            with open(_JARVIS_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _sauvegarder_config(data: dict) -> None:
    """Sauvegarde les données dans jarvis_config.json."""
    try:
        import json
        cfg = _charger_config()
        cfg.update(data)
        with open(_JARVIS_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[MIC] Impossible de sauvegarder la config : {e}")

def detecter_microphone() -> int | None:
    """
    Détecte le meilleur microphone disponible.

    Stratégie :
      1. Essaie l'index mémorisé dans jarvis_config.json
      2. Essaie le micro par défaut du système (index None)
      3. Parcourt tous les périphériques d'entrée disponibles
      4. Sauvegarde l'index retenu pour le prochain lancement

    Retourne l'index (int) du micro retenu, ou None si aucun trouvé
    (dans ce cas sr.Microphone() utilisera le défaut OS).
    """
    import json

    # ── Lister tous les périphériques PyAudio ────────────────
    if pyaudio:
        try:
            p = pyaudio.PyAudio()
            nb = p.get_device_count()
            inputs = []
            print("[MIC] Périphériques audio détectés :")
            for i in range(nb):
                try:
                    info = p.get_device_info_by_index(i)
                    if info.get("maxInputChannels", 0) > 0:
                        nom = info.get("name", f"Périphérique {i}")
                        inputs.append((i, nom))
                        print(f"      [{i}] {nom}")
                except Exception:
                    pass
            p.terminate()

            if not inputs:
                print("[MIC] ⚠ Aucun périphérique d'entrée détecté par PyAudio.")
        except Exception as e:
            print(f"[MIC] Impossible de lister les périphériques : {e}")
            inputs = []
    else:
        inputs = []
        print("[MIC] PyAudio absent — mode fallback speech_recognition uniquement.")

    # ── Récupérer l'index mémorisé ───────────────────────────
    cfg = _charger_config()
    index_memo = cfg.get("mic_device_index", None)

    # ── Fonction de test d'un index ──────────────────────────
    def _tester_index(idx):
        """Retourne True si sr.Microphone(device_index=idx) s'ouvre correctement."""
        try:
            kwargs = {} if idx is None else {"device_index": idx}
            mic_test = sr.Microphone(**kwargs)
            r_test = sr.Recognizer()
            with mic_test as src:
                r_test.adjust_for_ambient_noise(src, duration=0.3)
            return True
        except Exception as e:
            label = "défaut" if idx is None else str(idx)
            print(f"[MIC]   Index {label} → KO ({e})")
            return False

    # ── Priorité 1 : index mémorisé ──────────────────────────
    if index_memo is not None:
        nom_memo = next((n for i, n in inputs if i == index_memo), f"Index {index_memo}")
        print(f"[MIC] Test du micro mémorisé : [{index_memo}] {nom_memo}")
        if _tester_index(index_memo):
            print(f"[MIC] ✔ Micro retenu (mémorisé) : [{index_memo}] {nom_memo}")
            return index_memo
        else:
            print(f"[MIC] Micro mémorisé introuvable, recherche d'un remplaçant…")

    # ── Priorité 2 : micro par défaut OS ─────────────────────
    print("[MIC] Test du micro par défaut système…")
    if _tester_index(None):
        # Identifier son index réel si possible
        idx_reel = None
        if pyaudio:
            try:
                p = pyaudio.PyAudio()
                idx_reel = p.get_default_input_device_info().get("index", None)
                p.terminate()
            except Exception:
                pass
        nom_defaut = next((n for i, n in inputs if i == idx_reel), "Défaut système")
        print(f"[MIC] ✔ Micro retenu (défaut) : [{idx_reel}] {nom_defaut}")
        _sauvegarder_config({"mic_device_index": idx_reel})
        return idx_reel

    # ── Priorité 3 : parcourir tous les périphériques ────────
    print("[MIC] Recherche sur tous les périphériques disponibles…")
    for idx, nom in inputs:
        print(f"[MIC]   Test [{idx}] {nom}…")
        if _tester_index(idx):
            print(f"[MIC] ✔ Micro retenu (fallback) : [{idx}] {nom}")
            _sauvegarder_config({"mic_device_index": idx})
            return idx

    # ── Aucun micro fonctionnel ───────────────────────────────
    print("[MIC] ⚠ Aucun microphone fonctionnel trouvé.")
    print("[MIC]   Vérifiez que votre micro est branché et autorisé dans")
    print("[MIC]   Paramètres Windows → Confidentialité → Microphone.")
    _sauvegarder_config({"mic_device_index": None})
    return None

def ecouter():
    global is_listening, jarvis_actif, dernier_message, STOP_PARLER, is_speaking

    r   = sr.Recognizer()

    # ── Détection automatique du micro ───────────────────────
    mic_index = detecter_microphone()
    if mic_index is not None:
        mic = sr.Microphone(device_index=mic_index)
        print(f"[JARVIS] Microphone sélectionné : index {mic_index}")
    else:
        mic = sr.Microphone()
        print("[JARVIS] Microphone : périphérique par défaut système")

    r.pause_threshold        = 0.6
    r.non_speaking_duration  = 0.5
    r.energy_threshold       = 300
    r.dynamic_energy_threshold = True

    # ── Calibration bruit ambiant ─────────────────────────────
    try:
        with mic as source:
            r.adjust_for_ambient_noise(source, duration=1)
    except Exception as e:
        print(f"[MIC] ⚠ Calibration impossible : {e}")
        # Retenter avec le micro par défaut
        mic = sr.Microphone()
        try:
            with mic as source:
                r.adjust_for_ambient_noise(source, duration=1)
        except Exception:
            pass

    print("[JARVIS] Microphone pret. En attente de 'Jarvis' ou session active...")

    while True:
        try:
            # GESTION DU TIMEOUT DE SESSION
            if jarvis_actif and (time.time() - dernier_message > SESSION_TIMEOUT):
                print("[JARVIS] Timeout session. Retour en veille.")
                jarvis_actif = False

            with mic as source:
                is_listening = True
                loop_ws = asyncio.new_event_loop()
                state = "active" if jarvis_actif else "listening"
                loop_ws.run_until_complete(send_web_state(state))
                loop_ws.close()
                
                audio = r.listen(source, timeout=2, phrase_time_limit=10)
                
                is_listening = False
                loop_ws = asyncio.new_event_loop()
                loop_ws.run_until_complete(send_web_state("idle"))
                loop_ws.close()

            texte = r.recognize_google(audio, language="fr-FR").lower().strip()
            print(f"[ENTENDU] {texte}")

            # GESTION INTERRUPTION DURANT LA PAROLE
            if is_speaking and ("tais-toi" in texte or "silence" in texte or "tais toi" in texte):
                STOP_PARLER = True
                continue

            # MOTS-CLÉS DE SOMMEIL
            SLEEP_WORDS = ["merci", "ce sera tout", "repos", "au revoir", "silence", "tais-toi", "tais toi"]
            if any(word in texte for word in SLEEP_WORDS):
                if jarvis_actif:
                    jarvis_actif = False
                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(parler("A votre service {USER_NAME}. Je me mets en veille."))
                    loop.close()
                continue

            if WAKE_WORD in texte or jarvis_actif:
                if WAKE_WORD in texte:
                    print("[JARVIS] Mot-clé détecté.")
                    jarvis_actif = True
                
                dernier_message = time.time()
                commande = nettoyer_commande(texte)
                
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                if commande:
                    action_pc = executer_action_pc(commande)
                    if action_pc:
                        loop.run_until_complete(parler(action_pc))
                    else:
                        loop.run_until_complete(traiter_reponse_ia(commande))
                else:
                    if WAKE_WORD in texte: # "Jarvis" tout seul
                        loop.run_until_complete(parler("Oui {USER_NAME}, je vous écoute."))
                
                loop.close()
            else:
                pass

        except sr.WaitTimeoutError:
            pass
        except sr.UnknownValueError:
            pass
        except OSError as e:
            # Micro débranché ou périphérique perdu — on tente de le relancer
            print(f"[MIC] ⚠ Périphérique audio perdu ({e}). Tentative de récupération…")
            time.sleep(2)
            try:
                mic_index = detecter_microphone()
                if mic_index is not None:
                    mic = sr.Microphone(device_index=mic_index)
                else:
                    mic = sr.Microphone()
                with mic as source:
                    r.adjust_for_ambient_noise(source, duration=0.5)
                print("[MIC] ✔ Microphone récupéré avec succès.")
            except Exception as e2:
                print(f"[MIC] Impossible de récupérer le microphone : {e2}")
                time.sleep(3)
        except Exception as e:
            print(f"Erreur écoute : {e}")
            time.sleep(1)

def monitor_claps():
    if not pyaudio:
        print("[CLAP] PyAudio absent — detection des applaudissements desactivee.")
        return
    try:
        import audioop
        p = pyaudio.PyAudio()
        # On ouvre le flux
        # Utiliser le même micro que la détection vocale
        cfg_clap = _charger_config()
        mic_idx_clap = cfg_clap.get("mic_device_index", None)
        open_kwargs = dict(format=pyaudio.paInt16, channels=1, rate=44100,
                          input=True, frames_per_buffer=1024)
        if mic_idx_clap is not None:
            open_kwargs["input_device_index"] = mic_idx_clap
        stream = p.open(**open_kwargs, encoding="utf-8")
        print("[CLAP] Détection des applaudissements activée.")
        
        print("[CLAP] Détection des doubles applaudissements activée.")
        
        last_clap_time = 0
        
        while True:
            try:
                data = stream.read(1024, exception_on_overflow=False)
                rms  = audioop.rms(data, 2)
                
                # ON IGNORE LE CLAP UNIQUEMENT SI LE MODE IRON MAN EST ÉTEINT OU SI JARVIS PARLE
                if not MODE_IRON_MAN or is_speaking or is_thinking:
                    last_clap_time = 0
                    continue

                if rms > CLAP_THRESHOLD:
                    current_time = time.time()
                    diff = current_time - last_clap_time
                    
                    if 0.1 < diff < 0.8:
                        global VIDEO_LANCEE
                        print(f"\n[CLAP] !!! DOUBLE CLAP DÉTECTÉ !!!")
                        entity_id = PIECES_LUMIERES.get("salon", "light.salon")
                        
                        # On vérifie l'état actuel
                        etat_actuel = ha_get_etat(entity_id)
                        
                        if etat_actuel != "on":
                            # ON ALLUME
                            print(f"[CLAP] Action : ALLUMER")
                            ha_lumiere(entity_id, "on")
                            
                            if not VIDEO_LANCEE:
                                print(f"[CLAP] Lancement initial de la vidéo...")
                                webbrowser.open("https://www.youtube.com/watch?v=KU5V5WZVcVE", encoding="utf-8")
                                VIDEO_LANCEE = True
                                def seq():
                                    time.sleep(5)
                                    pyautogui.press('f')
                                threading.Thread(target=seq, daemon=True).start()
                            else:
                                print(f"[CLAP] Reprise de la vidéo (Play)...")
                                pyautogui.press('k')
                        else:
                            # ON ÉTEINT
                            print(f"[CLAP] Action : ÉTEINDRE")
                            ha_lumiere(entity_id, "off")
                            if VIDEO_LANCEE:
                                print(f"[CLAP] Mise en pause de la vidéo...")
                                pyautogui.press('k')
                            
                        # Gros debounce après une action réussie
                        time.sleep(3.0)
                        last_clap_time = 0 # Reset
                    else:
                        # C'est peut-être le premier clap
                        last_clap_time = current_time
            except Exception as e:
                # Si erreur de lecture (ex: micro débranché), on attend et on continue
                time.sleep(0.5)
                continue

    except Exception as e:
        print(f"[CLAP] Erreur fatale détection claps : {e}")

def start_ia():
    threading.Thread(target=monitor_claps, daemon=True).start()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def start_ws():
        print(f"[WEB] Serveur WebSocket demarre sur ws://0.0.0.0:8765")
        print(f"[WEB] Accessible depuis le reseau : ws://{LOCAL_IP}:8765")
        async with websockets.serve(ws_handler, "0.0.0.0", 8765):
            await asyncio.Future()

    threading.Thread(target=lambda: asyncio.run(start_ws()), daemon=True).start()

    # --- SÉQUENCE D'INITIALISATION STYLE IRON MAN ---
    print("[JARVIS] Attente de la connexion de l'interface...")
    
    # On attend que l'interface soit connectée (max 10s)
    debut_attente = time.time()
    while not CONNECTED_CLIENTS and (time.time() - debut_attente < 10):
        time.sleep(0.5)

    if CONNECTED_CLIENTS:
        print("[JARVIS] Interface connectée. Lancement du protocole de démarrage.")
        # Petit délai pour laisser le JS s'initialiser
        time.sleep(1)
        
        # Séquence vocale stylisée
        loop.run_until_complete(parler("Initialisation des systèmes de bord..."))
        time.sleep(0.3)
        loop.run_until_complete(parler("Protocoles de communication actifs. Bonjour {USER_NAME}. Je suis en ligne et opérationnel."))
    else:
        print("[JARVIS] Timeout connexion interface — démarrage en mode aveugle.")
        loop.run_until_complete(parler("Bonjour {USER_NAME}. Je suis prêt."))

    loop.close()
    
    # Lancement de l'écoute (Boucle infinie)
    ecouter()

def verifier_mises_a_jour():
    """Vérifie périodiquement si une nouvelle version est disponible sur le serveur."""
    global DERNIERE_MAJ_INFO
    if not UPDATE_JSON_URL:
        return
    while True:
        try:
            print(f"[UPDATE] Verification des mises a jour...")
            response = requests.get(UPDATE_JSON_URL, timeout=10)
            if response.status_code == 200:
                data = response.json()
                remote_version = data.get("version", "4.0")
                
                # Comparaison de version
                if remote_version > CURRENT_VERSION:
                    print(f"[UPDATE] NOUVELLE VERSION DETECTEE : {remote_version}")
                    DERNIERE_MAJ_INFO = {
                        "type": "update_available",
                        "version": remote_version,
                        "url": data.get("download_url", "https://www.techenclair.fr/pages/jarvis.html"),
                        "changelog": data.get("changelog", "")
                    }
                    # Envoyer à ceux qui sont déjà connectés
                    send_to_all_clients(DERNIERE_MAJ_INFO)
                else:
                    DERNIERE_MAJ_INFO = None
            else:
                print(f"[UPDATE] Serveur injoignable (Status: {response.status_code})")
        except Exception as e:
            print(f"[UPDATE] Erreur lors de la verification : {e}")
        
        # On verifie toutes les 4 heures
        time.sleep(14400)


# ==========================================
# LANCEMENT — MODE CONSOLE + FRONTEND WEB
# ==========================================
# Ursina desactive : l'interface est maintenant le frontend Three.js
# dans le dossier frontend/ (npm run dev -> http://localhost:5173)
# Le WebSocket est deja demarre par start_ia() sur ws://localhost:8765

if pygame:
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
else:
    print("[INFO] Pygame absent — demarrage sans audio TTS.")

def start_mobile_http_server():
    """Serveur HTTP minimal pour servir l'interface mobile sur le port 8080."""
    import http.server
    mobile_dir = _trouver_dossier_projet("mobile")
    if not os.path.exists(mobile_dir):
        print("[MOBILE] Dossier mobile/ introuvable, serveur non demarre.")
        return
    class MobileHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=mobile_dir, **kwargs)
        def log_message(self, format, *args):
            pass  # Silencieux
    server = http.server.HTTPServer(("0.0.0.0", 8080), MobileHandler)
    print(f"[MOBILE] Serveur HTTP demarre sur http://{LOCAL_IP}:8080")
    server.serve_forever()

def liberer_port(port):
    """Libère un port TCP occupé par une ancienne instance (Windows : netstat + taskkill)."""
    try:
        sortie = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True,
                                text=True, errors="replace").stdout
        pids = set()
        for ligne in sortie.splitlines():
            p = ligne.split()
            if len(p) >= 4 and p[0].upper() == "TCP" and p[1].endswith(f":{port}") and p[-1].isdigit():
                pids.add(int(p[-1]))
        protege = _pids_proteges()
        for pid in pids:
            if pid == 0 or pid in protege:
                continue
            _tuer_arbre(pid)
            print(f"[DÉMARRAGE] Port {port} libéré (PID {pid} terminé).")
        if pids:
            time.sleep(0.5)
    except Exception as e:
        print(f"[DÉMARRAGE] Impossible de libérer le port {port} : {e}")

def main():
    print()
    print("=" * 60)
    print("   J.A.R.V.I.S — Demarrage du systeme")
    print("=" * 60)
    print()
    print("  Backend   : actif (terminal)")
    print(f"  WebSocket : ws://localhost:8765  (LAN: ws://{LOCAL_IP}:8765)")
    print(f"  Mobile    : http://{LOCAL_IP}:8080")
    print()
    print("  Commandes vocales actives.")
    print("  Dites 'Jarvis' pour activer la session.")
    print("=" * 60)
    print()

    # Liberer les ports si une instance precedente tourne encore
    liberer_port(8765)
    liberer_port(8080)

    # Lancer le serveur Frontend
    frontend_dir = _trouver_dossier_projet("frontend")
    frontend_process = None
    FRONTEND_URL = "http://localhost:5173"

    def _port_ecoute(port, timeout=4.0):
        """Retourne True si quelque chose ecoute sur le port donne."""
        import socket
        debut = time.time()
        while time.time() - debut < timeout:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    return True
            except (ConnectionRefusedError, OSError):
                time.sleep(0.2)
        return False

    def _servir_dist_python(port=5173):
        """Sert le dossier dist/ avec le serveur HTTP Python (fallback sans npm)."""
        import http.server, socketserver
        dist_dir = os.path.join(frontend_dir, "dist")
        class _Silencieux(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        handler = functools.partial(_Silencieux, directory=dist_dir)  # sans os.chdir : ne casse plus les chemins relatifs
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", port), handler) as httpd:
            print(f"[JARVIS] Frontend servi via Python HTTP sur http://localhost:{port}")
            httpd.serve_forever()

    vite_ok = False
    if os.path.exists(frontend_dir):
        # Tentative 1 : Vite (npm run dev)
        try:
            if FROZEN:
                raise RuntimeError("version installée : interface servie depuis dist/")
            print("[JARVIS] Tentative de lancement Vite (npm run dev)...")
            frontend_process = subprocess.Popen(
                ["npm.cmd", "run", "dev"], cwd=frontend_dir,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            vite_ok = _port_ecoute(5173, timeout=5.0)
            if vite_ok:
                print("[JARVIS] Vite demarre avec succes sur localhost:5173")
            else:
                print("[JARVIS] Vite n'a pas demarre (npm/vite absent ou erreur).")
                if frontend_process:
                    frontend_process.terminate()
                    frontend_process = None
        except Exception as e:
            if not FROZEN:
                print(f"[JARVIS] Impossible de lancer Vite : {e}")
            frontend_process = None

        # Tentative 2 : servir dist/ avec Python (pas besoin de npm)
        if not vite_ok:
            dist_dir = os.path.join(frontend_dir, "dist")
            if os.path.exists(dist_dir) and os.path.exists(os.path.join(dist_dir, "index.html")):
                print("[JARVIS] Fallback : service du dossier dist/ via Python HTTP...")
                t_dist = threading.Thread(target=_servir_dist_python, args=(5173,), daemon=True)
                t_dist.start()
                vite_ok = _port_ecoute(5173, timeout=3.0)
                if vite_ok:
                    print("[JARVIS] Frontend dist/ servi correctement.")
            else:
                print("[JARVIS] Aucun dossier dist/ trouve. Interface non disponible.")
                print("[JARVIS] Pour corriger : cd frontend && npm install && npm run build")

    if not vite_ok:
        print("[JARVIS] ATTENTION : l'interface visuelle ne sera pas disponible.")
        print("[JARVIS] JARVIS reste fonctionnel en mode vocal uniquement.")

    # Lancer les services en arriere-plan
    threading.Thread(target=start_mobile_http_server, daemon=True).start()
    threading.Thread(target=start_ia, daemon=True).start()
    threading.Thread(target=verifier_mises_a_jour, daemon=True).start()

    # Choisir le mode d'affichage
    if _WEBVIEW_OK and webview is not None:
        # MODE FENETRE NATIVE (pywebview)
        print("[JARVIS] Ouverture dans une fenetre native (pywebview)...")

        # Calcul de la taille et position centrée selon la résolution de l'écran
        try:
            from screeninfo import get_monitors
            _mon = get_monitors()[0]
            _sw, _sh = _mon.width, _mon.height
        except Exception:
            _sw, _sh = 1920, 1080

        # 85% de l'écran, min 1280x780
        _win_w = max(1280, int(_sw * 0.85))
        _win_h = max(780,  int(_sh * 0.85))
        _win_x = (_sw - _win_w) // 2
        _win_y = (_sh - _win_h) // 2

        window = webview.create_window(
            title            = "J.A.R.V.I.S",
            url              = FRONTEND_URL,
            width            = _win_w,
            height           = _win_h,
            x                = _win_x,
            y                = _win_y,
            resizable        = True,
            min_size         = (900, 600),
            background_color = "#0a0a0f",
            icon             = os.path.join(_trouver_dossier_projet("assets"), "jarvis.ico"),
        )

        def _on_closed():
            print("\n[JARVIS] Fenetre fermee — extinction du systeme...")
            if frontend_process:
                _tuer_arbre(frontend_process.pid)

        window.events.closed += _on_closed

        # webview.start() DOIT etre appele depuis le thread principal
        try:
            webview.start(gui="cocoa" if platform.system() == "Darwin" else None)
        except Exception:
            try:
                webview.start()
            except Exception as e:
                print(f"[JARVIS] PyWebView impossible : {e} — bascule sur navigateur")
                _ouvrir_dans_navigateur(FRONTEND_URL, frontend_process)
    else:
        # MODE NAVIGATEUR (fallback si pywebview absent)
        _ouvrir_dans_navigateur(FRONTEND_URL, frontend_process)


def _ouvrir_dans_navigateur(url, frontend_process):
    print("[JARVIS] Ouverture dans le navigateur par defaut...")
    try:
        webbrowser.open(url, encoding="utf-8")
    except Exception:
        pass

    try:
        while True:
            time.sleep(1)
            if interface_deja_connectee and len(CONNECTED_CLIENTS) == 0:
                print("\n[JARVIS] Interface deconnectee. Attente de reconnexion (60s)...")
                time.sleep(60)
                if len(CONNECTED_CLIENTS) == 0:
                    print("[JARVIS] Aucune reconnexion. Extinction automatique...")
                    break
                else:
                    print("[JARVIS] Reconnexion detectee. Reprise.")
    except KeyboardInterrupt:
        print("\n[JARVIS] Arret manuel.")

    if frontend_process:
        print("[JARVIS] Arret du serveur Web...")
        _tuer_arbre(frontend_process.pid)

if __name__ == "__main__":
    main()
