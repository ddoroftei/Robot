#!/bin/bash
# setup.sh - Instalare automata Dulink Arbitrage Bot

set -e

echo "======================================"
echo "  Dulink Arbitrage Bot - Setup"
echo "======================================"

# Verifica Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 nu este instalat!"
    echo "   Instaleaza Python 3.10+ de pe https://www.python.org"
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "✅ Python $PYTHON_VERSION detectat"

# Creeaza mediu virtual
echo ""
echo "📦 Creez mediu virtual Python..."
python3 -m venv venv

# Activeaza
source venv/bin/activate 2>/dev/null || source venv/Scripts/activate 2>/dev/null

# Instaleaza dependente
echo ""
echo "📥 Instalez dependentele..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Instaleaza Chromium pentru Playwright
echo ""
echo "🌐 Instalez Chromium (necesar pentru automatizare browser)..."
playwright install chromium

echo ""
echo "======================================"
echo "✅ Instalare completa!"
echo ""
echo "Urmatorii pasi:"
echo "  1. Editeaza config.yaml cu datele tale"
echo "  2. Testeaza conexiunea: python main.py test"
echo "  3. Simuleaza: python main.py simulate"  
echo "  4. Ruleaza: python main.py run"
echo "======================================"
