# -*- mode: python ; coding: utf-8 -*-
# Construit JARVIS.exe (dossier dist/JARVIS) :  pyinstaller jarvis.spec --noconfirm
import os
from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(SPECPATH)
datas, binaries, hiddenimports = [], [], []

# paquets qui embarquent des fichiers/DLL/sous-modules chargés dynamiquement
for pkg in ["speech_recognition", "edge_tts", "pyttsx3", "pycaw", "comtypes",
            "certifi", "google.genai", "screen_brightness_control", "websockets"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print(f"[SPEC] {pkg} ignore : {e}")

hiddenimports += ["ha_config", "jarvis_agent", "pyaudio", "pygame", "cv2", "screeninfo", "psutil",
                  "pyautogui", "pyperclip", "win32timezone"]

# ressources embarquees (le frontend doit etre compile : cd frontend && npm install && npm run build)
for src, dst in [("frontend/dist", "frontend/dist"), ("mobile", "mobile"),
                 ("assets", "assets"), ("config_template", "config_template")]:
    if os.path.isdir(os.path.join(ROOT, src)):
        datas.append((os.path.join(ROOT, src), dst))
    else:
        print(f"[SPEC] ATTENTION : {src} introuvable, non embarque")

a = Analysis(
    [os.path.join(ROOT, "src", "main2.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter.test", "pytest", "IPython", "matplotlib", "scipy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="JARVIS",
    console=True,           # garde la console visible : on voit les messages et erreurs de Jarvis
    icon=os.path.join(ROOT, "assets", "jarvis.ico"),
    upx=False,              # UPX declenche plus de faux positifs antivirus
)
coll = COLLECT(exe, a.binaries, a.datas, name="JARVIS", upx=False)
