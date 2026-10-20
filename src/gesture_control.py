# -*- coding: utf-8 -*-
"""
J.A.R.V.I.S — Contrôle du PC avec les gestes de la main (webcam).

Fonctionnement :
  webcam (OpenCV) -> suivi de la main (MediaPipe, 21 points) -> reconnaissance de gestes
  -> souris Windows (curseur, clics, glisser, molette).
  Un aperçu de la caméra (avec le squelette de la main) est envoyé à l'interface web.

GESTES (main en face de la caméra) :
  ☝  Index levé, autres doigts repliés ........ POINTER (le curseur suit le bout de l'index)
  🤏  Pincer pouce + index (rapide) ............ CLIC GAUCHE   (2 fois = double clic)
  🤏  Pincer pouce + index (maintenu) .......... GLISSER-DÉPOSER (bouger la main en gardant la pince)
  🤏  Pincer pouce + majeur .................... CLIC DROIT
  ✌  Index + majeur levés ..................... DÉFILER : bouger la main vers le haut / bas / gauche / droite
  ✋  Main ouverte (5 doigts) ................... PAUSE (rien ne bouge)
"""
import base64
import math
import os
import platform
import threading
import time
from collections import deque

try:
    import cv2
except ImportError:  # géré au démarrage avec un message clair
    cv2 = None
try:
    import numpy as np
except ImportError:
    np = None

# ══════════════════════════════════════════════════════════════════════════════
# RÉGLAGES (à ajuster si besoin)
# ══════════════════════════════════════════════════════════════════════════════
ZONE = (0.18, 0.82, 0.12, 0.78)   # zone de la caméra (x0, x1, y0, y1) qui couvre tout l'écran
PINCE_ON = 0.32          # distance pouce-doigt / taille de la main : en dessous = pincé
PINCE_OFF = 0.50         # au-dessus = relâché (hystérésis, évite les clics fantômes)
DOIGT_ETENDU = 1.20      # bout du doigt / articulation, distance au poignet : au-dessus = doigt levé
BOUT_SORTI = 0.85        # une pince n'est valable que si le bout du doigt n'est pas replié dans la paume
DELAI_GLISSER_S = 0.35   # pince maintenue plus longtemps que ça = glisser-déposer
FRAMES_STABLES = 2       # un geste doit être vu sur 2 images de suite avant d'être pris en compte
PERTE_MAIN_S = 0.30      # main perdue plus longtemps = on relâche tout
ZONE_MORTE_PX = 3        # le curseur ne bouge pas pour moins de 3 pixels (anti-tremblement)
ZONE_MORTE_DEFIL = 0.05  # défilement : la main doit s'écarter d'au moins 5 % de l'image
VITESSE_DEFIL = 70.0     # crans de molette par seconde pour un écart de 100 % (plus grand = plus rapide)
APERCU_W, APERCU_H = 280, 210
APERCU_FPS = 12
URL_MODELE = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
              "hand_landmarker/float16/latest/hand_landmarker.task")

LIAISONS_MAIN = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10),
                 (10, 11), (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18),
                 (18, 19), (19, 20), (0, 17)]

LIBELLES = {
    "absent": "Aucune main",
    "none": "…",
    "point": "Pointer",
    "pinch": "Clic / glisser",
    "pinch_right": "Clic droit",
    "scroll": "Défilement",
    "open": "Pause",
}
COULEURS_BGR = {  # couleur du point sur l'index dans l'aperçu
    "point": (255, 229, 0), "pinch": (80, 220, 80), "pinch_right": (0, 165, 255),
    "scroll": (0, 230, 255), "open": (160, 160, 160), "none": (160, 160, 160),
}


# ══════════════════════════════════════════════════════════════════════════════
# RECONNAISSANCE DES GESTES (fonctions pures : testables sans caméra)
# ══════════════════════════════════════════════════════════════════════════════
def _d(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _etendu(lm, bout, pip):
    return _d(lm[bout], lm[0]) > _d(lm[pip], lm[0]) * DOIGT_ETENDU


def classer(lm, pose_prec="none"):
    """lm = 21 points (x, y) normalisés. Renvoie : point | pinch | pinch_right | scroll | open | none."""
    taille = max(_d(lm[0], lm[9]), 1e-6)  # poignet -> base du majeur
    ri = _d(lm[4], lm[8]) / taille        # pouce <-> index
    rm = _d(lm[4], lm[12]) / taille       # pouce <-> majeur
    seuil_i = PINCE_OFF if pose_prec == "pinch" else PINCE_ON
    seuil_m = PINCE_OFF if pose_prec == "pinch_right" else PINCE_ON
    index_sorti = _d(lm[8], lm[0]) / taille > BOUT_SORTI
    majeur_sorti = _d(lm[12], lm[0]) / taille > BOUT_SORTI

    if ri < seuil_i and ri <= rm and index_sorti:
        return "pinch"
    if rm < seuil_m and majeur_sorti:
        return "pinch_right"

    idx = _etendu(lm, 8, 6)
    mid = _etendu(lm, 12, 10)
    ann = _etendu(lm, 16, 14)
    aur = _etendu(lm, 20, 18)
    if idx and mid and ann and aur:
        return "open"
    if idx and mid and not ann and not aur:
        return "scroll"
    if idx and not mid and not ann and not aur:
        return "point"
    return "none"


# ══════════════════════════════════════════════════════════════════════════════
# SOURIS
# ══════════════════════════════════════════════════════════════════════════════
class _Souris:
    """Souris Windows via l'API native (rapide, sans le coin 'failsafe' de pyautogui)."""

    LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP = 0x0002, 0x0004, 0x0008, 0x0010
    WHEEL, HWHEEL = 0x0800, 0x1000

    def __init__(self):
        self.win = platform.system() == "Windows"
        if self.win:
            import ctypes
            from ctypes import wintypes
            self._ct = ctypes
            self._u32 = ctypes.windll.user32
            self._u32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                              wintypes.DWORD, ctypes.c_size_t]
            self._pt = wintypes.POINT
            self.largeur = self._u32.GetSystemMetrics(0)
            self.hauteur = self._u32.GetSystemMetrics(1)
        else:
            import pyautogui
            self._pg = pyautogui
            self.largeur, self.hauteur = pyautogui.size()
        self._appuye = set()

    def position(self):
        if self.win:
            p = self._pt()
            self._u32.GetCursorPos(self._ct.byref(p))
            return float(p.x), float(p.y)
        x, y = self._pg.position()
        return float(x), float(y)

    def deplacer(self, x, y):
        x = int(min(max(x, 0), self.largeur - 1))
        y = int(min(max(y, 0), self.hauteur - 1))
        if self.win:
            self._u32.SetCursorPos(x, y)
        else:
            self._pg.moveTo(x, y, _pause=False)

    def presser(self, bouton="gauche"):
        if self.win:
            self._u32.mouse_event(self.LEFTDOWN if bouton == "gauche" else self.RIGHTDOWN, 0, 0, 0, 0)
        else:
            self._pg.mouseDown(button="left" if bouton == "gauche" else "right", _pause=False)
        self._appuye.add(bouton)

    def relacher(self, bouton="gauche"):
        if self.win:
            self._u32.mouse_event(self.LEFTUP if bouton == "gauche" else self.RIGHTUP, 0, 0, 0, 0)
        else:
            self._pg.mouseUp(button="left" if bouton == "gauche" else "right", _pause=False)
        self._appuye.discard(bouton)

    def clic(self, bouton="gauche"):
        self.presser(bouton)
        self.relacher(bouton)

    def molette(self, verticale=0, horizontale=0):
        """Crans de molette : verticale > 0 = vers le haut ; horizontale > 0 = vers la droite."""
        if self.win:
            if verticale:
                self._u32.mouse_event(self.WHEEL, 0, 0, (verticale * 120) & 0xFFFFFFFF, 0)
            if horizontale:
                self._u32.mouse_event(self.HWHEEL, 0, 0, (horizontale * 120) & 0xFFFFFFFF, 0)
        else:
            if verticale:
                self._pg.scroll(verticale * 120, _pause=False)
            if horizontale:
                self._pg.hscroll(horizontale * 120, _pause=False)

    def tout_relacher(self):
        for b in list(self._appuye):
            try:
                self.relacher(b)
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
# MACHINE À ÉTATS : gestes -> actions souris
# ══════════════════════════════════════════════════════════════════════════════
class _Etat:
    def __init__(self, souris):
        self.s = souris
        self.pose = "none"
        self.cand, self.cand_n = "none", 0
        self.curseur = None
        self.hist = deque(maxlen=16)  # (t, x, y) : positions récentes du curseur
        self.drag = False
        self.drag_off = (0.0, 0.0)
        self.pince_debut = 0.0
        self.ancre = None
        self.acc_v = 0.0
        self.acc_h = 0.0
        self.dernier_t = None
        self.perdu_depuis = None

    # -- utilitaires -----------------------------------------------------------
    def _vers_ecran(self, p):
        x0, x1, y0, y1 = ZONE
        sx = min(max((p[0] - x0) / (x1 - x0), 0.0), 1.0)
        sy = min(max((p[1] - y0) / (y1 - y0), 0.0), 1.0)
        return sx * (self.s.largeur - 1), sy * (self.s.hauteur - 1)

    def _suivre(self, cible, t):
        if self.curseur is None:
            self.curseur = self.s.position()
        cx, cy = self.curseur
        dist = math.hypot(cible[0] - cx, cible[1] - cy)
        if dist < ZONE_MORTE_PX:
            return
        alpha = 0.20 + 0.65 * min(1.0, dist / (0.15 * self.s.largeur))  # lent = précis, rapide = réactif
        cx += (cible[0] - cx) * alpha
        cy += (cible[1] - cy) * alpha
        self.curseur = (cx, cy)
        self.s.deplacer(cx, cy)
        self.hist.append((t, cx, cy))

    def _revenir_avant_pince(self, t):
        """Au début d'une pince, le bout de l'index a bougé : on remet le curseur où il était juste avant."""
        for ts, x, y in self.hist:
            if t - ts <= 0.25:
                self.curseur = (x, y)
                self.s.deplacer(x, y)
                return

    # -- transitions -----------------------------------------------------------
    def _entrer(self, pose, lm, t):
        if pose == "pinch":
            self.pince_debut = t
            self._revenir_avant_pince(t)
        elif pose == "pinch_right":
            self._revenir_avant_pince(t)
            self.s.clic("droit")
        elif pose == "scroll":
            self.ancre = ((lm[8][0] + lm[12][0]) / 2, (lm[8][1] + lm[12][1]) / 2)
            self.acc_v = self.acc_h = 0.0

    def _quitter(self, pose, t):
        if pose == "pinch":
            if self.drag:
                self.s.relacher("gauche")
                self.drag = False
            else:
                self.s.clic("gauche")
        if pose in ("point", "pinch", "pinch_right"):
            self.curseur = None  # on se resynchronise avec la vraie position (si la souris a bougé)
            if pose != "point":
                self.hist.clear()

    # -- boucle ----------------------------------------------------------------
    def traiter(self, lm, t):
        dt = 0.03 if self.dernier_t is None else min(max(t - self.dernier_t, 0.0), 0.1)
        self.dernier_t = t

        if lm is None:
            if self.perdu_depuis is None:
                self.perdu_depuis = t
            if t - self.perdu_depuis > PERTE_MAIN_S and self.pose != "none":
                self._quitter(self.pose, t)
                self.s.tout_relacher()
                self.drag = False
                self.pose, self.cand, self.cand_n = "none", "none", 0
            return "absent"
        self.perdu_depuis = None

        brut = classer(lm, self.pose)
        if brut == self.pose:
            self.cand, self.cand_n = brut, 0
        else:
            self.cand_n = self.cand_n + 1 if brut == self.cand else 1
            self.cand = brut
            if self.cand_n >= FRAMES_STABLES:
                self._quitter(self.pose, t)
                self._entrer(brut, lm, t)
                self.pose, self.cand_n = brut, 0

        self._agir(self.pose, lm, t, dt)
        return self.pose

    def _agir(self, pose, lm, t, dt):
        if pose == "point":
            self._suivre(self._vers_ecran(lm[8]), t)

        elif pose == "pinch":
            milieu = ((lm[4][0] + lm[8][0]) / 2, (lm[4][1] + lm[8][1]) / 2)
            if not self.drag and t - self.pince_debut >= DELAI_GLISSER_S:
                cx, cy = self.curseur or self.s.position()
                mx, my = self._vers_ecran(milieu)
                self.drag_off = (cx - mx, cy - my)
                self.curseur = (cx, cy)
                self.s.presser("gauche")
                self.drag = True
            if self.drag:
                mx, my = self._vers_ecran(milieu)
                self._suivre((mx + self.drag_off[0], my + self.drag_off[1]), t)

        elif pose == "scroll":
            px, py = (lm[8][0] + lm[12][0]) / 2, (lm[8][1] + lm[12][1]) / 2
            dx, dy = px - self.ancre[0], py - self.ancre[1]
            if abs(dx) > abs(dy):  # un seul axe à la fois : le plus marqué
                exc = abs(dx) - ZONE_MORTE_DEFIL
                if exc > 0:
                    self.acc_h += math.copysign(exc, dx) * VITESSE_DEFIL * dt
                self.acc_v = 0.0
            else:
                exc = abs(dy) - ZONE_MORTE_DEFIL
                if exc > 0:
                    self.acc_v += math.copysign(exc, -dy) * VITESSE_DEFIL * dt  # main vers le haut = défile vers le haut
                self.acc_h = 0.0
            nv, nh = int(self.acc_v), int(self.acc_h)
            if nv or nh:
                nv, nh = max(-8, min(8, nv)), max(-8, min(8, nh))
                self.s.molette(verticale=nv, horizontale=nh)
                self.acc_v -= int(self.acc_v)
                self.acc_h -= int(self.acc_h)


# ══════════════════════════════════════════════════════════════════════════════
# DÉTECTION DE LA MAIN (MediaPipe : ancienne API 'solutions' ou nouvelle API 'tasks')
# ══════════════════════════════════════════════════════════════════════════════
def _assurer_modele(dossier):
    """Nouvelle API MediaPipe : le modèle hand_landmarker.task est téléchargé une seule fois (~8 Mo)."""
    chemin = os.path.join(dossier, "models", "hand_landmarker.task")
    if os.path.isfile(chemin) and os.path.getsize(chemin) > 1_000_000:
        return chemin
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    try:
        import requests
        print("[GESTES] Téléchargement du modèle de suivi des mains (une seule fois)…")
        r = requests.get(URL_MODELE, timeout=60)
        r.raise_for_status()
        tmp = chemin + ".part"
        with open(tmp, "wb") as f:
            f.write(r.content)
        os.replace(tmp, chemin)
        return chemin
    except Exception as e:
        raise RuntimeError(
            f"Modèle de suivi des mains introuvable et téléchargement impossible ({e}). "
            f"Téléchargez {URL_MODELE} et placez le fichier ici : {chemin}")


class _Detecteur:
    def __init__(self, dossier_donnees):
        try:
            import mediapipe as mp
        except ImportError:
            raise RuntimeError("Le module 'mediapipe' n'est pas installé : pip install mediapipe")
        self._mp = mp
        self._legacy = hasattr(mp, "solutions") and hasattr(mp.solutions, "hands")
        self._dernier_ts = 0
        if self._legacy:
            self._hands = mp.solutions.hands.Hands(
                max_num_hands=1, model_complexity=0,
                min_detection_confidence=0.6, min_tracking_confidence=0.5)
        else:
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            chemin = _assurer_modele(dossier_donnees)
            options = vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=chemin),
                running_mode=vision.RunningMode.VIDEO, num_hands=1,
                min_hand_detection_confidence=0.6, min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5)
            self._landmarker = vision.HandLandmarker.create_from_options(options)

    def detecter(self, rgb):
        """Renvoie 21 points [(x, y), ...] normalisés (0-1), ou None si aucune main."""
        if self._legacy:
            res = self._hands.process(rgb)
            if not res.multi_hand_landmarks:
                return None
            return [(p.x, p.y) for p in res.multi_hand_landmarks[0].landmark]
        ts = max(int(time.monotonic() * 1000), self._dernier_ts + 1)  # doit toujours augmenter
        self._dernier_ts = ts
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        res = self._landmarker.detect_for_video(image, ts)
        if not res.hand_landmarks:
            return None
        return [(p.x, p.y) for p in res.hand_landmarks[0]]

    def fermer(self):
        try:
            (self._hands if self._legacy else self._landmarker).close()
        except Exception:
            pass


def _ouvrir_camera():
    index = int(os.getenv("JARVIS_CAMERA_INDEX", "0") or 0)
    backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY] if platform.system() == "Windows" else [cv2.CAP_ANY]
    for be in backends:
        cap = cv2.VideoCapture(index, be)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        cap.release()
    raise RuntimeError("Webcam introuvable ou déjà utilisée par une autre application "
                       "(changez de caméra avec JARVIS_CAMERA_INDEX=1 dans le fichier .env).")


# ══════════════════════════════════════════════════════════════════════════════
# CONTRÔLEUR (thread) — c'est lui que main2.py utilise
# ══════════════════════════════════════════════════════════════════════════════
class GestureController:
    """emit(dict) : fonction appelée (depuis le thread) pour envoyer des messages à l'interface web."""

    def __init__(self, emit, data_dir=None):
        self._emit = emit
        self._data_dir = data_dir or os.getcwd()
        self._thread = None
        self._stop = threading.Event()

    @property
    def actif(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        if self.actif:
            if not self._stop.is_set():
                return  # déjà en marche
            self._thread.join(timeout=3)  # un arrêt est en cours : on attend la fin avant de relancer
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-gestes")
        self._thread.start()

    def stop(self, attendre=True):
        self._stop.set()
        t = self._thread
        if attendre and t and t is not threading.current_thread():
            t.join(timeout=3)

    def _apercu(self, frame, lm, pose):
        petit = cv2.resize(frame, (APERCU_W, APERCU_H))
        x0, x1, y0, y1 = ZONE
        cv2.rectangle(petit, (int(x0 * APERCU_W), int(y0 * APERCU_H)),
                      (int(x1 * APERCU_W), int(y1 * APERCU_H)), (255, 229, 0), 1)  # zone active
        if lm:
            pts = [(int(x * APERCU_W), int(y * APERCU_H)) for x, y in lm]
            for a, b in LIAISONS_MAIN:
                cv2.line(petit, pts[a], pts[b], (255, 229, 0), 1, cv2.LINE_AA)
            for p in pts:
                cv2.circle(petit, p, 2, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(petit, pts[8], 7, COULEURS_BGR.get(pose, (160, 160, 160)), 2, cv2.LINE_AA)
            if pose in ("pinch", "pinch_right"):
                cv2.line(petit, pts[4], pts[8] if pose == "pinch" else pts[12],
                         COULEURS_BGR[pose], 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", petit, [cv2.IMWRITE_JPEG_QUALITY, 55])
        if not ok:
            return
        self._emit({"action": "gesture_frame", "data": base64.b64encode(buf.tobytes()).decode("ascii"),
                    "pose": pose, "label": LIBELLES.get(pose, pose)})

    def _run(self):
        cap = det = souris = None
        erreur = ""
        try:
            if cv2 is None or np is None:
                raise RuntimeError("opencv-python et numpy sont nécessaires : pip install opencv-python numpy")
            self._emit({"action": "gesture_status", "active": True, "message": "Démarrage de la caméra…"})
            souris = _Souris()
            det = _Detecteur(self._data_dir)
            cap = _ouvrir_camera()
            etat = _Etat(souris)
            self._emit({"action": "gesture_status", "active": True, "message": ""})
            print("[GESTES] Contrôle par gestes actif.")
            echecs, dernier_apercu, pose = 0, 0.0, "absent"
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    echecs += 1
                    if echecs > 60:
                        raise RuntimeError("La webcam ne renvoie plus d'image.")
                    time.sleep(0.03)
                    continue
                echecs = 0
                frame = cv2.flip(frame, 1)  # effet miroir : la main droite va vers la droite à l'écran
                lm = det.detecter(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                pose = etat.traiter(lm, time.monotonic())
                maintenant = time.monotonic()
                if maintenant - dernier_apercu >= 1.0 / APERCU_FPS:
                    dernier_apercu = maintenant
                    self._apercu(frame, lm, pose)
        except Exception as e:
            erreur = str(e) or e.__class__.__name__
            print(f"[GESTES] Erreur : {erreur}")
        finally:
            if souris:
                souris.tout_relacher()
            if cap is not None:
                cap.release()
            if det is not None:
                det.fermer()
            print("[GESTES] Contrôle par gestes arrêté.")
            self._emit({"action": "gesture_status", "active": False, "error": erreur})
