# J.A.R.V.I.S — Assistant IA personnel (Windows)

Version Windows 10/11 du projet, créée par **Rahim Batchabi**
(portée depuis les versions macOS et Linux).

## Installation

1. Installez **Python 3.10 à 3.13** (cochez *Add Python to PATH*) et, pour l'interface 3D, **Node.js LTS**.
2. Double-cliquez sur `INSTALLER_JARVIS.bat`.
3. Ouvrez `src\.env` et renseignez au minimum `GEMINI_API_KEY`
   (vous pouvez copier votre ancien `.env` dans `src\`).
4. Double-cliquez sur `LANCER_JARVIS.bat`, puis dites « Jarvis ».

## Installer sans Python (JARVIS_Setup.exe)

**Méthode GitHub (recommandée, rien à installer)**
1. Envoyez ce dossier sur un dépôt GitHub (le fichier `.env` n'est jamais envoyé : il est dans `.gitignore`).
2. Onglet **Actions** → *Construire JARVIS_Setup.exe* → **Run workflow** (ou simplement un push).
3. Quand c'est vert, ouvrez l'exécution et téléchargez l'artefact **JARVIS_Setup** : c'est l'installateur.

**Méthode locale** : double-cliquez sur `CONSTRUIRE_EXE.bat` (Python + Node.js requis, et Inno Setup pour l'installateur).

Après l'installation : au premier lancement, le Bloc-notes s'ouvre sur votre fichier de clés
(`%APPDATA%\JARVIS\.env`) : ajoutez `GEMINI_API_KEY`, enregistrez, puis relancez Jarvis.
Vos données (mémoire, profil, clés, `credentials.json` Google) restent dans `%APPDATA%\JARVIS`
et survivent aux mises à jour.

Si Windows SmartScreen ou Defender avertit : *Informations complémentaires → Exécuter quand même*
(l'installateur n'est pas signé numériquement).

## Avec Cursor

Ouvrez ce dossier dans Cursor, puis dans le terminal :

```
venv\Scripts\activate
cd src
python main2.py
```

## Ce qui a été adapté pour Windows

- Lancement/fermeture d'applications (Chrome, Spotify, Discord, Office, Adobe, Cursor, VS Code…) :
  chemins connus, registre Windows, menu Démarrer, protocoles (`spotify:`, `discord://`…).
- Volume (pycaw), luminosité, veille, arrêt/redémarrage (`shutdown`), corbeille.
- Mode boulot : disposition des 4 fenêtres via l'API Windows (sans pywin32).
- Libération automatique des ports 8765 et 8080 (`netstat` + `taskkill`).
- Console et fichiers en UTF-8 (corrige l'erreur `charmap`).
- Dossiers `frontend/` et `mobile/` détectés à la racine ou dans `src/`.
- `os.chdir` retiré du serveur de secours (il cassait les chemins relatifs).
- Correction : le mot « ea » (EA App) déclenchait l'ouverture d'EA dans « bureau ».
- Jarvis ne ferme jamais son propre terminal avec « ferme terminal ».
- `jarvis_agent.py` réécrit (l'ancien appelait une méthode inexistante).
- Vérification des mises à jour désactivée (elle pointait vers le serveur d'un autre auteur).

## TikTok

Mettez `TIKTOK_USERNAME=votre_pseudo` dans `src\\.env`, puis demandez « combien d'abonnés j'ai sur TikTok ».

## Dépannage

- **PyAudio ne s'installe pas** : `pip install pipwin` puis `pipwin install pyaudio`.
- **Pas d'interface 3D** : installez Node.js puis relancez `INSTALLER_JARVIS.bat`.
- **Micro muet** : Paramètres → Confidentialité → Microphone → autoriser les applications de bureau.
- **Fenêtre native** : `pip install pywebview` puis `JARVIS_FENETRE=1` dans `src\.env`.

## Sécurité

Ne publiez jamais `src\.env` (déjà dans `.gitignore`).
