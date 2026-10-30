"""
opcom.py - Scraper preturi PZU de pe OPCOM.ro la intervale de 15 minute

Foloseste Playwright pentru a incarca pagina complet (JavaScript inclus),
deoarece tabelul de 96 intervale x 15min e incarcat dinamic via AJAX.

URL: https://www.opcom.ro/grafice-ip-raportPIP-si-volumTranzactionat/ro

Returneaza Dict[int, float] unde cheia e slot-ul 0-95:
  slot 0  = 00:00-00:15
  slot 4  = 01:00-01:15
  slot 95 = 23:45-24:00
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Optional

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

BASE_URL = "https://www.opcom.ro/grafice-ip-raportPIP-si-volumTranzactionat/ro"


def slot_to_time(slot: int) -> str:
    """Slot 0-95 → 'HH:MM'. Ex: 0→'00:00', 6→'01:30', 95→'23:45'"""
    return f"{slot // 4:02d}:{(slot % 4) * 15:02d}"


def slot_end_time(slot: int) -> str:
    """Ora de sfarsit a unui slot. Slot 95 → '24:00'"""
    if slot + 1 == 96:
        return "24:00"
    return slot_to_time(slot + 1)


class OPCOMScraper:
    def __init__(self, currency: str = "RON"):
        self.currency = currency.upper()

    async def get_today_prices(self) -> Dict[int, float]:
        """96 preturi x 15 min pentru AZI."""
        return await self._fetch_async(datetime.now())

    async def get_tomorrow_prices(self) -> Dict[int, float]:
        """96 preturi x 15 min pentru MAINE (disponibile dupa ~13:00)."""
        return await self._fetch_async(datetime.now() + timedelta(days=1))

    async def get_prices_for_date(self, date: datetime) -> Dict[int, float]:
        return await self._fetch_async(date)

    async def _fetch_async(self, date: datetime) -> Dict[int, float]:
        date_str = date.strftime("%d.%m.%Y")
        logger.info(f"Obtin preturi OPCOM PZU 15min pentru {date_str}...")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                # Intercepteaza raspunsurile JSON/XHR ca sa gasim endpoint-ul cu date
                api_prices = {}

                async def handle_response(response):
                    try:
                        url = response.url
                        if any(kw in url.lower() for kw in ["pzu", "pip", "dam", "price", "pret", "pt15", "15min"]):
                            ct = response.headers.get("content-type", "")
                            if "json" in ct:
                                data = await response.json()
                                prices = self._try_parse_json(data)
                                if len(prices) > len(api_prices):
                                    api_prices.update(prices)
                                    logger.info(f"✅ Date gasite via API: {url}")
                    except Exception:
                        pass

                page.on("response", handle_response)

                # Incarca pagina
                await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
                await self._select_date(page, date)

                # Incearca sa apese butonul/tab-ul PT15
                await self._click_pt15(page)

                # Asteapta reincarcarea datelor
                await asyncio.sleep(3)
                await page.wait_for_load_state("networkidle")

                # Daca API-ul a returnat date, folosim acelea
                if len(api_prices) >= 80:
                    logger.info(f"✅ {len(api_prices)} intervale via interceptare API")
                    return api_prices

                # Altfel parseaza HTML-ul
                html = await page.content()
                prices = self._parse_15min_table(html)

                if prices:
                    logger.info(f"✅ {len(prices)} intervale obtinute pentru {date_str}")
                else:
                    logger.warning(f"Nu s-au gasit 96 intervale pentru {date_str}")

                return prices

            except Exception as e:
                logger.error(f"Eroare fetch OPCOM: {e}")
                return {}
            finally:
                await browser.close()

    async def _click_pt15(self, page) -> None:
        """
        Apasa tab-ul '15min' din pagina OPCOM.
        Confirmat din screenshot: tab-urile sunt '15min', '30min', '60min'.
        """
        pt15_selectors = [
            # Confirmat din screenshot - tab-urile au textul exact
            'button:has-text("15min")',
            'a:has-text("15min")',
            'li:has-text("15min")',
            'span:has-text("15min")',
            '[class*="tab"]:has-text("15min")',
            '[class*="btn"]:has-text("15min")',
            'text="15min"',
        ]

        for sel in pt15_selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    await el.click()
                    await asyncio.sleep(2)
                    await page.wait_for_load_state("networkidle")
                    logger.debug(f"✅ Tab 15min apasat cu: {sel}")
                    return
            except Exception:
                continue

        logger.debug("Tab 15min negasit - probabil deja activ implicit")

    async def _select_date(self, page, date: datetime) -> None:
        """Incearca sa selecteze data in pagina OPCOM daca exista un picker."""
        try:
            # Cauta input de tip data sau selector
            date_selectors = [
                'input[type="date"]',
                'input[placeholder*="data" i]',
                'input[placeholder*="date" i]',
                '.date-picker input',
                '#date',
            ]
            for sel in date_selectors:
                el = await page.query_selector(sel)
                if el:
                    await el.fill(date.strftime("%Y-%m-%d"))
                    await page.keyboard.press("Enter")
                    await page.wait_for_load_state("networkidle")
                    logger.debug(f"Data selectata: {date.strftime('%d.%m.%Y')}")
                    break
        except Exception as e:
            logger.debug(f"Selectare data esuata (normal daca nu exista picker): {e}")

    async def _wait_for_96_rows(self, page) -> None:
        """Asteapta pana cand tabelul de 96 randuri e incarcat."""
        try:
            # Asteapta ca tabelele sa fie populate
            await page.wait_for_load_state("networkidle")
            await asyncio.sleep(2)  # buffer suplimentar pentru AJAX

            # Verifica daca avem ~96 randuri - daca nu, mai asteapta
            for attempt in range(5):
                html = await page.content()
                prices = self._parse_15min_table(html)
                if len(prices) >= 80:
                    logger.debug(f"Tabel 96 intervale incarcat dupa {attempt+1} verificari")
                    return
                logger.debug(f"Verificare {attempt+1}: {len(prices)} intervale, mai astept...")
                await asyncio.sleep(2)

        except Exception as e:
            logger.debug(f"Wait for rows: {e}")

    def _try_parse_json(self, data) -> Dict[int, float]:
        """Incearca sa extraga preturi din raspuns JSON al API-ului OPCOM."""
        prices = {}
        try:
            # Diferite structuri posibile de JSON
            items = []
            if isinstance(data, list):
                items = data
            elif isinstance(data, dict):
                for key in ["data", "prices", "results", "values", "intervals"]:
                    if key in data and isinstance(data[key], list):
                        items = data[key]
                        break

            for i, item in enumerate(items):
                if isinstance(item, (int, float)):
                    prices[i] = float(item)
                elif isinstance(item, dict):
                    # Cauta campul cu pretul
                    for price_key in ["price", "pret", "value", "val", "p"]:
                        if price_key in item:
                            prices[i] = float(item[price_key])
                            break
        except Exception:
            pass

        return prices

    def _parse_15min_table(self, html: str) -> Dict[int, float]:
        """
        Parseaza tabelul cu 96 intervale de 15 minute din HTML.
        Returneaza { slot 0-95: pret RON/MWh }.
        """
        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")

        # Incearca sa gaseasca tabelul cu cel mai multe randuri (cel de 96)
        best_prices = {}

        for table in tables:
            prices = self._try_parse_table(table)
            if len(prices) > len(best_prices):
                best_prices = prices

        return best_prices

    def _try_parse_table(self, table) -> Dict[int, float]:
        """
        Parseaza tabelul OPCOM cu structura confirmata din screenshot:

          Col 0: tara (ex: 'Romania')   ← ignoram
          Col 1: interval (1-96)         ← numarul intervalului
          Col 2: ROPEX_DAM_15min [Lei/MWh] ← PRETUL pe care il vrem

        Tabelul de 30min are aceeasi structura dar cu intervale 1-48.
        Tabelul de 60min are intervale 1-24.
        """
        rows = table.find_all("tr")
        if len(rows) < 5:
            return {}

        prices = {}

        for row in rows:
            cells = row.find_all(["td", "th"])

            # Tabelul are minim 3 coloane: tara | interval | pret | ...
            if len(cells) < 3:
                continue

            try:
                # Col 1: numarul intervalului
                interval_text = cells[1].get_text(strip=True)
                clean = re.sub(r"[^\d]", "", interval_text)
                if not clean:
                    continue
                interval = int(clean)
                if not (1 <= interval <= 96):
                    continue

                # Col 2: pretul ROPEX_DAM_15min [Lei/MWh]
                price_text = cells[2].get_text(strip=True)
                price = self._parse_ron_price(price_text)
                if price is None or price <= 0:
                    continue

                slot = interval - 1  # 1-96 → 0-95
                prices[slot] = price

            except (ValueError, TypeError, IndexError):
                continue

        return prices

    def _parse_ron_price(self, text: str) -> Optional[float]:
        """Format romanesc: '1.089,85' → 1089.85"""
        try:
            text = text.strip()
            text = text.replace(".", "").replace(",", ".")
            text = re.sub(r"[^\d.]", "", text)
            return float(text) if text else None
        except (ValueError, AttributeError):
            return None

    def print_price_table(self, prices: Dict[int, float]) -> None:
        if not prices:
            print("Nu exista preturi disponibile.")
            return

        avg = sum(prices.values()) / len(prices)
        min_s = min(prices, key=prices.get)
        max_s = max(prices, key=prices.get)

        print(f"\n{'='*55}")
        print(f"{'Interval':<18} {'RON/MWh':>12} {'':>10}")
        print(f"{'='*55}")

        for slot in sorted(prices.keys()):
            p = prices[slot]
            marker = ""
            if p <= avg * 0.85:  #de modificat si in arbitrage.py
                marker = "🔋 ieftin"
            elif p >= avg * 1.30:
                marker = "⚡ scump"
            start = slot_to_time(slot)
            end = slot_end_time(slot)
            print(f"{start}-{end}   {p:>10.2f}   {marker}")

        print(f"{'='*55}")
        print(f"Medie: {avg:.2f} RON/MWh  |  "
              f"Min: {prices[min_s]:.2f} @ {slot_to_time(min_s)}  |  "
              f"Max: {prices[max_s]:.2f} @ {slot_to_time(max_s)}")