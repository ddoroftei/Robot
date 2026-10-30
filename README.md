# ⚡ Dulink Arbitrage Bot

Bot de arbitraj automat pentru baterie fotovoltaica: incarca din retea cand curentul e ieftin, descarca in retea cand e scump, folosind preturile PZU de pe OPCOM.

```
OPCOM (preturi PZU) ──▶ Analiza arbitraj ──▶ Dulink (setari invertor)
```

---

## 📋 Cuprins

1. [Instalare locala](#instalare-locala)
2. [Configurare](#configurare)
3. [Utilizare](#utilizare)
4. [Adaptarea selectoarelor Dulink](#adaptarea-selectoarelor-dulink)
5. [Deployment pe server](#deployment-pe-server)
6. [Depanare](#depanare)

---

## 🖥️ Instalare locala

### Cerinte
- Python 3.10+
- Windows / Linux / macOS

### Pasi

```bash
# 1. Cloneaza / descarca proiectul
cd dulink-arbitrage

# 2. Creeaza mediu virtual Python
python -m venv venv

# Windows:
venv\Scripts\activate

# Linux/Mac:
source venv/bin/activate

# 3. Instaleaza dependentele
pip install -r requirements.txt

# 4. Instaleaza browser-ul Chromium pentru Playwright
playwright install chromium

# 5. Configureaza botul
# Editeaza config.yaml cu datele tale
```

---

## ⚙️ Configurare

Editeaza **`config.yaml`** cu datele tale:

```yaml
dulink:
  url: "https://www.dulink.com"         # URL-ul platformei tale
  email: "email@exemplu.com"             # Contul tau
  password: "parola_ta"
  plant_name: "Instalatia Mea"           # Exact cum apare in Dulink

arbitrage:
  charge_price_limit: 250.0    # Incarci bateria daca pretul e SUB aceasta valoare (RON/MWh)
  discharge_price_limit: 450.0  # Descarci bateria daca pretul e PESTE aceasta valoare (RON/MWh)
  max_charge_hours: 6           # Max ore de incarcare pe zi
  max_discharge_hours: 6        # Max ore de descarcare pe zi
  battery_efficiency: 0.90      # Eficienta round-trip (90%)

scheduler:
  run_time: "13:30"             # Ora de rulare zilnica (dupa publicarea preturilor OPCOM)
```

---

## 🚀 Utilizare

### Verificare conexiune Dulink (primul pas!)
```bash
python main.py test
```
Deschide browser-ul vizibil, se logeaza si verifica ca gaseste planta. Daca da eroare, ajusteaza selectoarele (vezi sectiunea de mai jos).

### Afisare preturi OPCOM
```bash
python main.py prices            # Preturi maine
python main.py prices --day today  # Preturi azi
```

### Simulare (fara a aplica setarile)
```bash
python main.py simulate
```
Afiseaza ce ar face botul fara sa modifice nimic in Dulink. **Foloseste asta pentru a verifica logica inainte de prima rulare reala.**

### Rulare manuala
```bash
python main.py run
```
Obtine preturile OPCOM si aplica setarile in Dulink.

### Rulare cu browser vizibil (debug)
```bash
python main.py run --visible
```

### Scheduler zilnic automat
```bash
python main.py schedule
```
Ruleaza continuu si executa botul zilnic la ora configurata (`run_time`).

---

## 🔧 Adaptarea selectoarelor Dulink

> ⚠️ **Aceasta este partea cea mai importanta!** Selectoarele din `src/dulink.py` sunt generice si este OBLIGATORIU sa le adaptezi la interfata reala a platformei tale Dulink.

### Cum gasesti selectoarele corecte

1. **Deschide Dulink in Chrome/Firefox**
2. **F12** → Tab "Elements" (Inspector)
3. Click pe elementul de interes (buton, camp, dropdown)
4. Click dreapta pe elementul evidentiat in Inspector → "Copy selector" sau "Copy XPath"
5. Inlocuieste selectoarele din `src/dulink.py`

### Ce trebuie adaptat

#### Login (`_login`)
```python
# Cauta si inlocuieste cu selectoarele reale:
await self._page.fill('input[type="email"]', self.email)   # Campul email
await self._page.fill('input[type="password"]', self.password)  # Campul parola
await self._page.click('button[type="submit"]')            # Butonul Login
```

#### Navigare la planta (`_navigate_to_plant`)
```python
# Adapteaza meniul unde apar plantele/proiectele
await self._page.click('a:has-text("Plants")')
# Adapteaza cum e selectata planta
await self._page.click(f'text="{self.plant_name}"')
```

#### Setari baterie (`_navigate_to_battery_settings`)
```python
# Adapteaza calea catre setarile de programare
await self._page.click('a:has-text("Settings")')
await self._page.click('a:has-text("Battery")')
```

#### Adaugare interval (`_add_time_slot`)
```python
# Adapteaza la interfata de programare din Dulink
# Poate fi tabel, calendar, sau campuri individuale
await self._page.click('button:has-text("Add")')
await self._page.fill('.start-time input', start_time)
await self._page.fill('.end-time input', end_time)
await self._page.select_option('select', label=mode_label)
```

### Debugging rapid
```bash
# Ruleaza cu browser vizibil + viteza redusa
python main.py run --visible
```

---

## 🌐 Deployment pe server

### Optiunea 1: VPS Linux (recomandat)

```bash
# Pe server (Ubuntu/Debian)
sudo apt update && sudo apt install -y python3.10 python3.10-venv

# Configureaza proiectul (la fel ca local)
cd dulink-arbitrage
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium --with-deps  # --with-deps instaleaza si dependentele sistem

# Ruleaza ca serviciu systemd
sudo nano /etc/systemd/system/dulink-arbitrage.service
```

Continut fisier serviciu systemd:
```ini
[Unit]
Description=Dulink Arbitrage Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/dulink-arbitrage
ExecStart=/home/ubuntu/dulink-arbitrage/venv/bin/python main.py schedule
Restart=always
RestartSec=60
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
# Activeaza si porneste serviciul
sudo systemctl daemon-reload
sudo systemctl enable dulink-arbitrage
sudo systemctl start dulink-arbitrage

# Verificare status
sudo systemctl status dulink-arbitrage
sudo journalctl -u dulink-arbitrage -f
```

### Optiunea 2: Docker

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget gnupg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium --with-deps

COPY . .

CMD ["python", "main.py", "schedule"]
```

```bash
docker build -t dulink-arbitrage .
docker run -d \
  -v $(pwd)/config.yaml:/app/config.yaml \
  -v $(pwd)/logs:/app/logs \
  --name dulink-bot \
  dulink-arbitrage
```

### Optiunea 3: GitHub Actions (gratuit, fara server)

```yaml
# .github/workflows/arbitrage.yml
name: Dulink Arbitrage
on:
  schedule:
    - cron: '30 11 * * *'  # 13:30 Romania = 11:30 UTC (iarna)
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: playwright install chromium --with-deps
      - run: python main.py run
        env:
          # Credentialele ca GitHub Secrets
          DULINK_EMAIL: ${{ secrets.DULINK_EMAIL }}
          DULINK_PASSWORD: ${{ secrets.DULINK_PASSWORD }}
```

---

## 🐛 Depanare

| Problema | Solutie |
|----------|---------|
| Login esuat | Verifica email/parola in `config.yaml`. Ruleaza `python main.py test` |
| Planta nu e gasita | Verifica `plant_name` sa fie identic cu cel din Dulink |
| Preturi OPCOM indisponibile | OPCOM publica dupa ~13:00. Incearca `python main.py prices` |
| Selectoare invalide | Ruleaza cu `--visible` si adapteaza selectoarele din `src/dulink.py` |
| Nicio ora de arbitraj | Ajusteaza pragurile `charge_price_limit` / `discharge_price_limit` |
| Browser nu porneste | Ruleaza `playwright install chromium` |

### Log-uri
```bash
# Urmareste log-urile in timp real
tail -f logs/arbitrage.log

# Cauta erori
grep "ERROR" logs/arbitrage.log
```

### Screenshot-uri de eroare
Cand apare o eroare, botul salveaza automat un screenshot in `logs/screenshot_*.png`.

---

## 📊 Cum functioneaza arbitrajul

```
1. OPCOM publica la ~13:00 preturile PZU pentru ziua urmatoare (24 ore)

2. Botul analizeaza preturile:
   - Ore ieftine (< charge_price_limit) → candidate pentru INCARCARE din retea
   - Ore scumpe (> discharge_price_limit) → candidate pentru DESCARCARE in retea

3. Selecteaza top N ore pentru fiecare categorie (max_charge_hours / max_discharge_hours)

4. Grupeaza orele consecutive in intervale continue

5. Verifica ca arbitrajul e profitabil (tine cont de eficienta bateriei)

6. Aplica setarile in Dulink prin automatizare browser
```

### Exemplu
```
Preturi maine (RON/MWh):
  02:00 - 03:00: 180 ← incarcare (sub 250)
  03:00 - 04:00: 195 ← incarcare (sub 250)
  18:00 - 19:00: 520 ← descarcare (peste 450)
  19:00 - 20:00: 490 ← descarcare (peste 450)

Program aplicat in Dulink:
  [INCARCARE]  02:00 - 04:00 @ 187 RON/MWh
  [DESCARCARE] 18:00 - 20:00 @ 505 RON/MWh
  
  Spread: 318 RON/MWh × eficienta 90% = 286 RON/MWh profit net
```
