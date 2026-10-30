@echo off
REM setup.bat - Instalare automata Dulink Arbitrage Bot (Windows)

echo ======================================
echo   Dulink Arbitrage Bot - Setup
echo ======================================

REM Verifica Python
python --version >nul 2>&1
if errorlevel 1 (
    echo X Python nu este instalat!
    echo   Descarca Python 3.10+ de pe https://www.python.org
    pause
    exit /b 1
)

echo [OK] Python detectat

REM Creeaza mediu virtual
echo.
echo Creez mediu virtual Python...
python -m venv venv

REM Activeaza
call venv\Scripts\activate

REM Instaleaza dependente
echo.
echo Instalez dependentele...
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

REM Instaleaza Chromium
echo.
echo Instalez Chromium (necesar pentru automatizare browser)...
playwright install chromium

echo.
echo ======================================
echo [OK] Instalare completa!
echo.
echo Urmatorii pasi:
echo   1. Editeaza config.yaml cu datele tale
echo   2. Testeaza conexiunea: python main.py test
echo   3. Simuleaza: python main.py simulate
echo   4. Ruleaza: python main.py run
echo ======================================
pause
