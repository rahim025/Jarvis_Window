@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo    J.A.R.V.I.S - Installation Windows
echo ========================================
where python >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python est introuvable.
    echo Installez Python depuis python.org et cochez "Add Python to PATH".
    pause
    exit /b 1
)
if not exist venv python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements_windows.txt
if errorlevel 1 (
    echo.
    echo [ATTENTION] Une dependance n'a pas pu s'installer.
    echo Si PyAudio echoue : pip install pipwin ^&^& pipwin install pyaudio
)
where npm >nul 2>&1
if errorlevel 1 (
    echo [INFO] Node.js absent : l'interface 3D ne sera pas disponible.
    echo        Installez Node.js LTS puis relancez ce script.
) else (
    pushd frontend
    call npm install
    call npm run build
    popd
)
if not exist src\.env (
    copy config_template\.env.example src\.env >nul
    echo [INFO] Fichier src\.env cree : ouvrez-le et ajoutez votre GEMINI_API_KEY.
)
echo.
echo Installation terminee. Lancez LANCER_JARVIS.bat
pause
