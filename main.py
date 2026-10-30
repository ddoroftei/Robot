"""
main.py - Entry point Dulink Arbitrage Bot

Utilizare:
  python main.py run        - Ruleaza acum (obtine preturi + aplica in Dulink)
  python main.py simulate   - Simuleaza fara a aplica in Dulink
  python main.py schedule   - Porneste scheduler zilnic automat
  python main.py test       - Verifica login + navigare (browser vizibil)
  python main.py prices     - Afiseaza preturile OPCOM
"""

import os
config["dulink"]["email"]      = os.getenv("DULINK_EMAIL",    config["dulink"]["email"])
config["dulink"]["password"]   = os.getenv("DULINK_PASSWORD", config["dulink"]["password"])

import asyncio, argparse, logging, logging.handlers, sys
from pathlib import Path
from datetime import datetime

import yaml
sys.path.insert(0, str(Path(__file__).parent))

from src.opcom import OPCOMScraper
from src.arbitrage import ArbitrageEngine
from src.dulink import DulinkBot
from src.scheduler import ArbitrageScheduler


def setup_logging(config: dict) -> None:
    lc = config.get("logging", {})
    level = getattr(logging, lc.get("level", "INFO").upper())
    log_file = lc.get("file", "logs/arbitrage.log")
    Path("logs").mkdir(exist_ok=True)
    fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
    dfmt = "%d.%m.%Y %H:%M:%S"
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(logging.Formatter(fmt, dfmt))
    fh = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=lc.get("max_size_mb", 10)*1024*1024,
        backupCount=lc.get("backup_count", 5), encoding="utf-8"
    )
    fh.setFormatter(logging.Formatter(fmt, dfmt))
    logging.basicConfig(level=level, handlers=[ch, fh])
    for noisy in ["playwright", "urllib3", "httpx"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def load_config(path: str = "config.yaml") -> dict:
    p = Path(path)
    if not p.exists():
        print(f"❌ Fisierul '{path}' nu exista! Editeaza config.yaml cu datele tale.")
        sys.exit(1)
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)
  import os
  config["dulink"]["email"]      = os.getenv("DULINK_EMAIL",    config["dulink"]["email"])
  config["dulink"]["password"]   = os.getenv("DULINK_PASSWORD", config["dulink"]["password"])


def build_components(config: dict):
    dc = config["dulink"]
    ac = config["arbitrage"]
    bc = config.get("browser", {})

    scraper = OPCOMScraper(currency=ac.get("currency", "RON"))

    engine = ArbitrageEngine(
        battery_efficiency=ac.get("battery_efficiency", 0.90)
    )

    bot = DulinkBot(
        url=dc["url"],
        email=dc["email"],
        password=dc["password"],
        plant_name=dc["plant_name"],
        selectors=dc.get("selectors", {}),
        headless=bc.get("headless", True),
        slow_mo=bc.get("slow_mo", 100),
        timeout=bc.get("timeout", 30000),
        screenshot_on_error=bc.get("screenshot_on_error", True),
    )
    return scraper, engine, bot


async def cmd_run(config: dict, simulate: bool = False, day: str = "tomorrow") -> bool:
    scraper, engine, bot = build_components(config)

    if day == "today":
        print("\n📡 Obtin preturile OPCOM pentru AZI (test)...")
        prices = await scraper.get_today_prices()
    else:
        print("\n📡 Obtin preturile OPCOM pentru maine...")
        prices = await scraper.get_tomorrow_prices()

    if not prices:
        print("❌ Preturile nu sunt disponibile inca.")
        print("   OPCOM publica de obicei dupa ora 12:00-13:00.")
        print("   Incearca mai tarziu sau ruleaza cu 'python main.py prices' sa verifici.")
        return False

    scraper.print_price_table(prices)

    print("\n🧮 Calculez programul automat de arbitraj...")
    sched = engine.calculate_schedule(prices, datetime.now())
    print(sched.summary())

    settings = engine.to_dulink_format(sched)

    if not settings:
        print("\n⚠️  Nu s-au gasit intervale de arbitraj rentabile pentru maine.")
        return True  # Nu e o eroare, pur si simplu nu merita azi

    print(f"\n📋 {len(settings)} intervale vor fi setate in Dulink:")
    for s in settings:
        emoji = "🔋" if s["mode"] == "charge" else "⚡"
        mode_ro = "INCARCARE" if s["mode"] == "charge" else "DESCARCARE"
        print(f"   {emoji} {mode_ro}: {s['start_time']} → {s['end_time']} @ {s['price']:.0f} RON/MWh")

    if simulate:
        print("\n🔵 MOD SIMULARE - Nimic nu a fost modificat in Dulink.")
        return True

    print("\n🤖 Aplic in Dulink...")
    success = await bot.apply_schedule(settings)
    if not success:
        print("❌ Eroare la aplicare. Verifica logs/ pentru detalii si screenshot.")
    return success


async def cmd_test(config: dict) -> None:
    _, _, bot = build_components(config)
    dc = config["dulink"]
    print(f"\n🔌 Test conexiune Dulink...")
    print(f"   URL:    {dc['url']}")
    print(f"   Email:  {dc['email']}")
    print(f"   Planta: {dc['plant_name']}")
    print(f"\n   Se deschide browser-ul... (inchide-l manual dupa verificare)\n")
    bot.headless = False
    bot.slow_mo = 800
    ok = await bot.verify_connection()
    if ok:
        print("\n✅ Totul functioneaza! Credentialele si planta sunt corecte.")
    else:
        print("\n❌ Ceva nu a mers. Urmeaza pasii din sectiunea Depanare din README.")


async def cmd_prices(config: dict, day: str = "tomorrow") -> None:
    scraper = OPCOMScraper(currency=config["arbitrage"].get("currency", "RON"))
    if day == "today":
        print("\n📊 Preturi OPCOM AZI:")
        prices = await scraper.get_today_prices()
    else:
        print("\n📊 Preturi OPCOM MAINE:")
        prices = await scraper.get_tomorrow_prices()

    if prices:
        scraper.print_price_table(prices)
        # Arata si cum ar imparti botul orele
        engine = ArbitrageEngine(
            battery_efficiency=config["arbitrage"].get("battery_efficiency", 0.90)
        )
        sched = engine.calculate_schedule(prices, datetime.now())
        print(sched.summary())
    else:
        print("❌ Preturile nu sunt disponibile inca (OPCOM publica dupa ~12:00-13:00).")


def cmd_schedule(config: dict) -> None:
    sc = config.get("scheduler", {})
    run_time = sc.get("run_time", "12:00")
    tz = sc.get("timezone", "Europe/Bucharest")
    run_on_start = sc.get("run_on_start", False)
    retry_count = sc.get("retry_count", 5)
    retry_wait = sc.get("retry_wait_minutes", 15)

    print(f"\n⏰ Scheduler pornit")
    print(f"   Ora de executie: {run_time} ({tz})")
    print(f"   Reincercari:     {retry_count}x la fiecare {retry_wait} min")
    print(f"   Ctrl+C pentru a opri\n")

    scheduler = ArbitrageScheduler(
        run_time=run_time, timezone=tz, run_on_start=run_on_start,
        retry_count=retry_count, retry_wait_minutes=retry_wait
    )

    async def job():
        return await cmd_run(config)

    scheduler.set_job(job)
    scheduler.start()


def main():
    parser = argparse.ArgumentParser(
        description="Dulink Arbitrage Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Comenzi:
  run       - Obtine preturi OPCOM si aplica in Dulink
  simulate  - Ca 'run' dar nu aplica nimic (doar afiseaza)
  test      - Verifica login + navigare (browser vizibil)
  prices    - Afiseaza preturile OPCOM si programul calculat
  schedule  - Porneste scheduler automat zilnic

Exemple:
  python main.py simulate              # Primul test recomandat
  python main.py prices                # Verifica preturile de maine
  python main.py test                  # Verifica conexiunea la Dulink
  python main.py run                   # Ruleaza efectiv
  python main.py schedule              # Porneste automatul zilnic
  python main.py run --visible         # Cu browser vizibil
        """
    )
    parser.add_argument("command", choices=["run", "simulate", "schedule", "test", "prices"])
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--day", choices=["today", "tomorrow"], default="tomorrow")
    parser.add_argument("--visible", action="store_true", help="Deschide browser vizibil")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)

    if args.visible:
        config.setdefault("browser", {})["headless"] = False
        config.setdefault("browser", {})["slow_mo"] = 600

    if args.command == "run":
        sys.exit(0 if asyncio.run(cmd_run(config, day=args.day)) else 1)
    elif args.command == "simulate":
        asyncio.run(cmd_run(config, simulate=True, day=args.day))
    elif args.command == "test":
        asyncio.run(cmd_test(config))
    elif args.command == "prices":
        asyncio.run(cmd_prices(config, day=args.day))
    elif args.command == "schedule":
        cmd_schedule(config)


if __name__ == "__main__":
    main()