@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================
echo    J.A.R.V.I.S - Construction de l'installateur
echo ========================================
where python >nul 2>&1 || (echo [ERREUR] Python introuvable. & pause & exit /b 1)
if not exist venv python -m venv venv
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements_windows.txt pyinstaller || (echo [ERREUR] Installation des dependances. & pause & exit /b 1)
where npm >nul 2>&1
if errorlevel 1 (
    echo [ATTENTION] Node.js absent : l'interface 3D ne sera pas incluse.
) else (
    pushd frontend
    call npm install
    call npm run build
    popd
)
pyinstaller jarvis.spec --noconfirm || (echo [ERREUR] PyInstaller a echoue. & pause & exit /b 1)
set ISCC=
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe
if defined ISCC (
    "%ISCC%" installer.iss
    echo.
    echo Termine : installer_output\JARVIS_Setup.exe
) else (
    echo.
    echo Inno Setup non installe : telechargez-le sur jrsoftware.org pour creer JARVIS_Setup.exe.
    echo En attendant, vous pouvez lancer dist\JARVIS\JARVIS.exe directement.
)
pause
