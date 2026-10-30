"""
dulink.py - Automatizare browser pentru platforma Dulink

Citeste selectoarele CSS direct din config.yaml - nu mai trebuie
sa editezi codul, doar fisierul de configurare.

Cum gasesti selectoarele corecte:
  1. Deschide Dulink in Chrome
  2. F12 → tab "Elements"
  3. Click pe elementul dorit (buton, camp, etc.)
  4. Click dreapta pe linia evidentiata → "Copy" → "Copy selector"
  5. Lipeste in config.yaml la selectorul corespunzator
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    TimeoutError as PlaywrightTimeoutError,
)

logger = logging.getLogger(__name__)


class DulinkBot:
    def __init__(
        self,
        url: str,
        email: str,
        password: str,
        plant_name: str,
        selectors: dict,
        headless: bool = True,
        slow_mo: int = 100,
        timeout: int = 30000,
        screenshot_on_error: bool = True,
    ):
        self.url = url.rstrip("/")
        self.email = email
        self.password = password
        self.plant_name = plant_name
        self.sel = selectors          # selectoarele din config.yaml
        self.headless = headless
        self.slow_mo = slow_mo
        self.timeout = timeout
        self.screenshot_on_error = screenshot_on_error
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page = None

    # ──────────────────────────────────────────────
    # Public
    # ──────────────────────────────────────────────

    async def apply_schedule(self, dulink_settings: List[Dict]) -> bool:
        async with async_playwright() as p:
            try:
                await self._start_browser(p)
                await self._login()
                await self._navigate_to_battery_settings()
                await self._navigate_to_pv_priority()
                await self._clear_existing_schedule()
                await self._set_new_schedule(dulink_settings)
                await self._save_settings()
                logger.info("✅ Program aplicat cu succes in Dulink!")
                return True
            except PlaywrightTimeoutError as e:
                logger.error(f"Timeout: {e}")
                await self._screenshot("timeout_error")
                return False
            except Exception as e:
                logger.error(f"Eroare: {e}", exc_info=True)
                await self._screenshot("error")
                return False
            finally:
                if self._browser:
                    await self._browser.close()

    async def verify_connection(self) -> bool:
        async with async_playwright() as p:
            try:
                await self._start_browser(p)
                await self._login()
                await self._navigate_to_plant()
                logger.info("✅ Conexiune verificata!")
                return True
            except Exception as e:
                logger.error(f"Verificare esuata: {e}")
                await self._screenshot("verify_error")
                return False
            finally:
                if self._browser:
                    await self._browser.close()

    # ──────────────────────────────────────────────
    # Browser
    # ──────────────────────────────────────────────

    async def _start_browser(self, playwright) -> None:
        self._browser = await playwright.chromium.launch(
            headless=self.headless,
            slow_mo=self.slow_mo,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        self._page = await self._context.new_page()
        self._page.set_default_timeout(self.timeout)

    # ──────────────────────────────────────────────
    # Login
    # ──────────────────────────────────────────────

    async def _login(self) -> None:
        logger.info(f"Login la {self.url}...")
        await self._page.goto(f"{self.url}/login", wait_until="networkidle")

        # Email
        await self._page.fill(self.sel["email_field"], self.email)
        logger.debug("Email completat")

        # Parola
        await self._page.fill(self.sel["password_field"], self.password)
        logger.debug("Parola completata")

        # Checkbox termeni si conditii
        await self._accept_terms()

        # Buton login
        await self._page.click(self.sel["login_button"])
        await self._page.wait_for_load_state("networkidle")

        # Verifica daca a reusit
        if "login" in self._page.url.lower():
            err = await self._get_error_text()
            raise Exception(
                f"Login esuat! {err or 'Verifica email/parola si selectorul login_button din config.yaml'}"
            )
        new_url = "https://www.dulink.dunext.com/plantDetail/plantOverview?id=QyuLjBoezfyWx08F6HYCM9MniJ0GRaIR-ylP0yU1umU"

        self._page = await self._page.context.new_page()
        await self._page.goto(new_url, wait_until="networkidle")
        await asyncio.sleep(0.7)
        logger.info("✅ Login reusit!")

    async def _accept_terms(self) -> None:
        """
        Bifeaza checkbox-ul cu termenii si conditiile.

        Dulink foloseste Element UI (Vue) unde checkbox-ul are structura:
          <label class="el-checkbox ...">
            <span class="el-checkbox__input">
              <input type="checkbox" class="el-checkbox__original">  ← input-ul real
            </span>
          </label>

        Strategii incercate in ordine:
          1. Gaseste <input> ascuns inauntrul selectorului si il bifeaza direct
          2. Click pe label (outer element)
          3. Click pe .el-checkbox__input (zona vizuala a bifei)
          4. JavaScript fortat
        """
        selector = self.sel.get("terms_checkbox", "")
        if not selector:
            return

        try:
            # Asteapta sa apara elementul (poate fi intr-un modal)
            await self._page.wait_for_selector(selector, timeout=5000)
        except Exception:
            logger.debug("Checkbox termeni nu a aparut in 5s - continuam fara")
            return

        try:
            # ── Gaseste checkbox-ul corect (Terms, nu Remember Password) ──
            # Strategia 1: cauta dupa textul din label (agree / terms / accept)
            terms_el = await self._find_terms_checkbox()

            if not terms_el:
                # Strategia 2: ia ULTIMUL checkbox de pe pagina (Terms e dupa Remember Me)
                all_checkboxes = await self._page.query_selector_all(selector)
                if all_checkboxes:
                    terms_el = all_checkboxes[-1]
                    logger.debug(f"Folosesc ultimul din {len(all_checkboxes)} checkboxuri")

            if not terms_el:
                logger.warning("Checkbox Terms negasit")
                return

            # ── Verifica daca e deja bifat ────────────────────────────────
            inner_input = await terms_el.query_selector(
                "input[type='checkbox'], .el-checkbox__original, input"
            )
            if inner_input:
                is_checked = await inner_input.is_checked()
                if is_checked:
                    logger.debug("Termeni deja bifati")
                    return

            # ── Click pe zona vizuala a bifei ────────────────────────────
            check_zone = await terms_el.query_selector(
                ".el-checkbox__input, span:first-child"
            )
            target = check_zone or terms_el
            await target.click()
            await asyncio.sleep(0.4)

            # ── Verifica daca a functionat ────────────────────────────────
            if inner_input:
                is_checked = await inner_input.is_checked()
                if is_checked:
                    logger.debug("✅ Termeni bifati")
                    return

            # ── Fallback: JavaScript direct ───────────────────────────────
            if inner_input:
                await self._page.evaluate(
                    "(el) => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); }",
                    inner_input
                )
                await asyncio.sleep(0.3)
                logger.debug("✅ Termeni bifati (JS fallback)")

        except Exception as e:
            logger.warning(f"Nu s-a putut bifa checkbox-ul termeni: {e}")

    # async def _switch_to_new_tab(self) -> None:
    #     """
    #     Asteapta deschiderea unui tab nou si comuta pe el.
    #     Folosit dupa click pe planta care se deschide intr-un tab separat.
    #     """
    #     try:
    #         # Asteapta maxim 8 secunde sa apara un tab nou
    #         new_page = await self._context.wait_for_event("page", timeout=8000)
    #         await new_page.wait_for_load_state("networkidle")
    #         # Comuta referinta principala pe noul tab
    #         self._page = new_page
    #         logger.info(f"✅ Comutat pe tab nou: {new_page.url}")
    #     except Exception as e:
    #         # Daca nu s-a deschis tab nou, ramane pe pagina curenta
    #         logger.debug(f"Nu s-a deschis tab nou (ramane pe tab curent): {e}")

    async def _find_terms_checkbox(self):
        """
        Cauta checkbox-ul de Terms dupa textul din jur.
        Returneaza elementul checkbox sau None.
        """
        # Cuvinte cheie din label-ul Terms (in diverse limbi)
        keywords = ["agree", "terms", "accept", "conditions", "acord", "termeni", "conditii"]

        for kw in keywords:
            try:
                # Cauta label care contine textul si are un checkbox inauntru
                el = await self._page.query_selector(
                    f"label:has-text('{kw}'), "
                    f".el-checkbox:has-text('{kw}'), "
                    f"[class*='checkbox']:has-text('{kw}')"
                )
                if el:
                    logger.debug(f"Terms checkbox gasit dupa textul '{kw}'")
                    return el
            except Exception:
                continue

        return None

    # ──────────────────────────────────────────────
    # Navigare planta
    # ──────────────────────────────────────────────

    # async def _navigate_to_plant(self) -> None:
    #     logger.info(f"Navighez la planta '{self.plant_name}'...")

    #     # Click pe meniul cu plante (daca exista)
    #     plants_menu_sel = self.sel.get("plants_menu", "")
    #     if plants_menu_sel:
    #         try:
    #             el = await self._page.query_selector(plants_menu_sel)
    #             if el:
    #                 await el.click()
    #                 await self._page.wait_for_load_state("networkidle")
    #         except Exception:
    #             pass

    #     # Cauta planta dupa text
    #     plant_found = False

    #     # Incearca selectorul specific din config
    #     plant_card_sel = self.sel.get("plant_card", "")
    #     if plant_card_sel:
    #         try:
    #             cards = await self._page.query_selector_all(plant_card_sel)
    #             for card in cards:
    #                 text = await card.inner_text()
    #                 if self.plant_name.lower() in text.lower():
    #                     await card.click()
    #                     plant_found = True
    #                     break
    #         except Exception:
    #             pass

    #     # Fallback: cauta dupa text direct
    #     if not plant_found:
    #         try:
    #             await self._page.click(f'text="{self.plant_name}"')
    #             plant_found = True
    #         except Exception:
    #             pass

    #     if not plant_found:
    #         raise Exception(
    #             f"Planta '{self.plant_name}' nu a fost gasita!\n"
    #             "  Verifica:\n"
    #             "  1. 'plant_name' in config.yaml sa fie identic cu ce apare in Dulink\n"
    #             "  2. Selectorul 'plant_card' din config.yaml\n"
    #             "  Ruleaza cu 'headless: false' pentru a vedea ce face bot-ul."
    #         )

    #     # Planta se deschide intr-un tab nou - comuta pe el
    #     await self._switch_to_new_tab()
    #     logger.info(f"✅ Planta '{self.plant_name}' gasita!")

    # ──────────────────────────────────────────────
    # Setari baterie
    # ──────────────────────────────────────────────
    

    async def _navigate_to_battery_settings(self) -> None:
        logger.info("Navighez la Operation Strategy...")

        # Incearca selectorul din config (daca e completat)
        settings_sel = self.sel.get("settings_menu", "")
        if settings_sel:
            try:
                el = await self._page.query_selector(settings_sel)
                if el:
                    await el.click()
                    await self._page.wait_for_load_state("networkidle")
            except Exception:
                pass

        # Click pe "Operation Strategy"
        # Structura HTML confirmata:
        #   <div class="title-box">
        #     <div class="card-name">Operation Strategy</div>
        #     <div class="work-mode-value">Self-consumption</div>
        #   </div>

        # Asteapta ca pagina sa fie complet incarcata
        await asyncio.sleep(1.5)

        clicked = False

        # Strategia 1: Playwright locator dupa text - cel mai fiabil
        try:
            loc = self._page.locator('.card-name', has_text="Operation Strategy")
            await loc.wait_for(state="visible", timeout=8000)
            await loc.click()
            await self._page.wait_for_load_state("networkidle")
            logger.info("✅ Operation Strategy deschis (locator text)")
            clicked = True
        except Exception as e:
            logger.debug(f"Locator .card-name esuat: {e}")

        # Strategia 2: get_by_text
        if not clicked:
            try:
                await self._page.get_by_text("Operation Strategy").first.click()
                await self._page.wait_for_load_state("networkidle")
                logger.info("✅ Operation Strategy deschis (get_by_text)")
                clicked = True
            except Exception as e:
                logger.debug(f"get_by_text esuat: {e}")

        # Strategia 3: JavaScript click direct pe elementul cu textul cautat
        if not clicked:
            try:
                result = await self._page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('.card-name, .title-box, div');
                        for (const el of els) {
                            if (el.textContent.trim().includes('Operation Strategy')) {
                                el.click();
                                return true;
                            }
                        }
                        return false;
                    }
                """)
                if result:
                    await asyncio.sleep(1)
                    logger.info("✅ Operation Strategy deschis (JavaScript)")
                    clicked = True
            except Exception as e:
                logger.debug(f"JS click esuat: {e}")

        # Strategia 4: selector din config (manual)
        if not clicked:
            battery_sel = self.sel.get("battery_section", "")
            if battery_sel:
                try:
                    await self._page.locator(battery_sel).first.click()
                    await self._page.wait_for_load_state("networkidle")
                    logger.info(f"✅ Operation Strategy deschis (config: {battery_sel})")
                    clicked = True
                except Exception as e:
                    logger.debug(f"Config selector esuat: {e}")

        if not clicked:
            await self._screenshot("operation_strategy_not_found")
            logger.warning(
                "Nu s-a putut da click pe 'Operation Strategy'!\n"
                "  Am salvat un screenshot in logs/ ca sa vezi starea paginii.\n"
                "  Verifica daca pagina s-a incarcat complet inainte de click."
            )

        await asyncio.sleep(1.5)
    
    async def _navigate_to_pv_priority(self) -> None:
        logger.info("Merg la TOU Schedule...")
        pv_sel = self.sel.get("pv_energy", "")
        if pv_sel:
            try:
                cel = await self._page.query_selector(pv_sel)
                if cel:
                    await cel.click()
                    await self._page.wait_for_load_state("networkidle")
            except Exception:
                pass

        await asyncio.sleep(0.7)
        

    async def _clear_existing_schedule(self) -> None:
        """
        Sterge toate randurile existente.
        Strategia: gaseste toate icoanele de stergere si da click pe ultimul
        (de la coada spre inceput), asteptand disparitia fiecarui rand.
        """
        await asyncio.sleep(1)
        logger.info("Sterg programul existent...")

        # Selectoare pentru iconita de stergere (cos de gunoi) din coloana Action
        # Confirmat: Element UI foloseste i.el-icon-delete sau similar
        delete_selectors = [
            self.sel.get("delete_row_button", ""),
            'i.el-icon-delete',
            '.el-icon-delete',
            'i[class*="delete"]',
            'i[class*="trash"]',
            '[class*="icon-delete"]',
            'td:last-child i',
            'td:last-child svg',
        ]
        # Filtreaza selectoarele goale
        delete_selectors = [s for s in delete_selectors if s]

        for attempt in range(30):
            found = False
            for sel in delete_selectors:
                try:
                    icons = await self._page.query_selector_all(sel)
                    if not icons:
                        continue

                    # Click pe ULTIMUL icon (evita stale references)
                    target = icons[-1]
                    await target.scroll_into_view_if_needed()
                    await target.click()
                    await asyncio.sleep(0.6)
                    await self._confirm_dialog()
                    await asyncio.sleep(0.4)
                    found = True
                    logger.debug(f"Rand {attempt+1} sters cu '{sel}'")
                    break
                except Exception as e:
                    logger.debug(f"Delete '{sel}' esuat: {e}")
                    continue

                if not found:
                    logger.info(f"✅ Stergere finalizata dupa {attempt} randuri")
                break
                # Verifica ca fereastra/modalul e inca deschis dupa stergeri
        await asyncio.sleep(0.5)
        logger.info("Stergere completa, continui cu adaugarea intervalelor...")

    async def _set_new_schedule(self, settings: List[Dict]) -> None:
        logger.info(f"Setez {len(settings)} intervale...")
 
        for i, s in enumerate(settings):
            mode_ro = "INCARCARE" if s["mode"] == "charge" else "DESCARCARE"
            logger.info(
                f"  [{i+1}/{len(settings)}] {mode_ro}: "
                f"{s['start_time']} → {s['end_time']} @ {s['price']:.0f} RON/MWh"
            )
            await self._add_time_slot(s["start_time"], s["end_time"], s["mode"])
            await asyncio.sleep(0.5)

    async def _add_time_slot(self, start_time: str, end_time: str, mode: str) -> None:
        """
        Adauga un rand nou in tabelul de programare Dulink.
 
        Structura confirmata din screenshot:
          No. | Start Time | End Time | Type | Maximum Power(kW) | Action
          (Nu exista coloana Mode!)
 
        Type: 'Charge' sau 'Discharge'
        Butoanele sunt dropdown-uri Element UI (custom, nu <select> nativ).
        """
        type_value = (
            self.sel.get("type_charge_value", "Charge") if mode == "charge"
            else self.sel.get("type_discharge_value", "Discharge")
        )

         # ── 1. Noteaza ID-urile existente inainte de Add ──────────
        existing_ids = await self._page.evaluate("""
            () => [...document.querySelectorAll('input.el-select__input')]
                  .map(el => el.id)
        """)

        # ── 2. Click Add Time Segment ─────────────────────────────
        for text in ["Add Time Segment", "Add Segment", "Add Time", "Add"]:
            try:
                loc = self._page.get_by_text(text, exact=False).first
                if await loc.count() > 0:
                    await loc.click()
                    break
            except Exception:
                continue

        # ── 3. Asteapta input-urile noi ───────────────────────────
        new_inputs = []
        for _ in range(20):
            await asyncio.sleep(0.3)
            all_ids = await self._page.evaluate("""
                () => [...document.querySelectorAll('input.el-select__input')]
                      .map(el => el.id)
            """)
            new_inputs = [id for id in all_ids if id not in existing_ids]
            if len(new_inputs) >= 3:
                break

        if len(new_inputs) < 3:
            logger.warning(f"Nu au aparut input-uri noi (gasit {len(new_inputs)})")
            return

        # new_inputs[0]=Start Time, new_inputs[1]=End Time, new_inputs[2]=Type
        for field_name, input_id, value in [
            ("Start Time", new_inputs[0], start_time),
            ("End Time",   new_inputs[1], end_time),
            ("Type",       new_inputs[2], type_value),
        ]:
            # Click undeva neutru ca sa inchida dropdown-ul precedent
            await self._page.mouse.click(10, 10)
            await asyncio.sleep(0.3)

            # Deschide dropdown-ul specific acestui input
            await self._page.evaluate(f"""
                () => {{
                    const inp = document.getElementById('{input_id}');
                    if (inp) inp.closest('.el-select__wrapper').click();
                }}
            """)

            # Asteapta ca ACEST input sa aiba aria-expanded=true
            for _ in range(15):
                await asyncio.sleep(0.2)
                expanded = await self._page.evaluate(f"""
                    () => {{
                        const inp = document.getElementById('{input_id}');
                        return inp && inp.getAttribute('aria-expanded') === 'true';
                    }}
                """)
                if expanded:
                    break

            # Obtine listbox-ul exact al acestui dropdown (aria-controls)
            listbox_id = await self._page.evaluate(f"""
                () => {{
                    const inp = document.getElementById('{input_id}');
                    return inp ? inp.getAttribute('aria-controls') : null;
                }}
            """)

            # Selecteaza optiunea din listbox-ul corect
            found = await self._page.evaluate(f"""
                (args) => {{
                    const box = document.getElementById(args.id);
                    const items = box
                        ? box.querySelectorAll('li, .el-select-dropdown__item')
                        : document.querySelectorAll('.el-select-dropdown__item');
                    for (const item of items) {{
                        if (item.textContent.trim() === args.val) {{
                            item.scrollIntoView({{block:'nearest', behavior:'instant'}});
                            item.click();
                            return true;
                        }}
                    }}
                    return false;
                }}
            """, {"id": listbox_id, "val": value})

            if not found:
                logger.warning(f"{field_name}: '{value}' negasit in listbox {listbox_id}")
            await asyncio.sleep(0.4)
 
        # ── 5. Maximum Power (kW) = 250 constant ─────────────────
        power_kw = self.sel.get("max_power_kw", 250)
        await asyncio.sleep(0.3)
 
        # Incearca mai multe abordari pentru a gasi campul de putere
        power_filled = False
 
        # Abordarea 1: selector din config
        power_sel = self.sel.get("power_input", "")
        if power_sel:
            try:
                inputs = await self._page.query_selector_all(power_sel)
                if inputs:
                    await inputs[-1].triple_click()
                    await inputs[-1].fill(str(power_kw))
                    power_filled = True
                    logger.debug(f"Power setat la {power_kw} kW (config sel)")
            except Exception:
                pass
 
        # Abordarea 2: JavaScript - gaseste ultimul input numeric din tabel
        if not power_filled:
            result = await self._page.evaluate(f"""
                (power) => {{
                    // Gaseste toate randurile din tabelul de programare
                    const rows = document.querySelectorAll('tr');
                    if (!rows.length) return false;
                    const lastRow = rows[rows.length - 1];
                    // Cauta input numeric in ultimul rand
                    const inputs = lastRow.querySelectorAll('input[type="number"], input[type="text"]');
                    if (inputs.length) {{
                        const inp = inputs[inputs.length - 1];
                        inp.focus();
                        inp.select();
                        inp.value = String(power);
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        return true;
                    }}
                    return false;
                }}
            """, power_kw)
            if result:
                power_filled = True
                logger.debug(f"Power setat la {power_kw} kW (JS lastRow)")
 
        if not power_filled:
            logger.warning(f"Campul Maximum Power nu a fost gasit. Seteaza 'power_input' in config.yaml")

 
    # async def _click_last_row_dropdown(self, col_index: int, value: str, field_name: str) -> None:
    #     """
    #     Click pe al col_index-lea dropdown din ultimul rand al tabelului.
    #     col_index: 0=Start Time, 1=End Time, 2=Type
    #     """
    #     triggered = await self._page.evaluate("""
    #         (colIndex) => {
    #             const rows = document.querySelectorAll('tr');
    #             if (!rows.length) return false;
    #             const lastRow = rows[rows.length - 1];
    #             // Cauta input-urile din dropdown-urile Element UI
    #             const triggers = lastRow.querySelectorAll(
    #                 '.el-select__wrapper'
    #             );
    #             if (colIndex >= triggers.length) return false;
    #             triggers[colIndex].click();
    #             return true;
    #         }
    #     """, col_index)

    #     await asyncio.sleep(0.5)

    #     if triggered:
    #         found = await self._click_dropdown_option(value)
    #         if not found:
    #             logger.warning(f"{field_name}: optiunea '{value}' nu a fost gasita")
    #     else:
    #         logger.warning(f"{field_name}: dropdown col {col_index} negasit in ultimul rand")
    
    async def _select_time_dropdown(self, selector: str, time_value: str, field_name: str) -> None:
        """
        Selecteaza o ora dintr-un dropdown Element UI de timp.
 
        Element UI dropdown flow:
          1. Click pe trigger (ultimul dropdown de acest tip = randul nou adaugat)
          2. Asteapta sa apara lista cu optiuni (.el-select-dropdown)
          3. Click pe optiunea cu ora exacta
        """
        if not selector:
            logger.warning(f"{field_name}: selector negasit in config.yaml")
            return
 
        try:
            # Ia ultimul dropdown de acest tip (randul tocmai adaugat)
            elements = await self._page.query_selector_all(selector)
            if not elements:
                logger.warning(f"{field_name}: niciun element gasit cu '{selector}'")
                return
 
            target = elements[-1]
 
            # Verifica daca e select nativ
            tag = await target.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                await target.select_option(label=time_value)
                logger.debug(f"{field_name} = {time_value} (select nativ)")
                return
 
            # Element UI custom dropdown
            await target.click()
            await asyncio.sleep(0.5)
 
            # Cauta optiunea exacta in lista deschisa
            # Element UI pune dropdown-ul la sfarsitul body-ului, nu in tabel
            found = await self._click_dropdown_option(time_value)
            if found:
                logger.debug(f"{field_name} = {time_value}")
            else:
                logger.warning(f"{field_name}: optiunea '{time_value}' nu a fost gasita in dropdown")
                # Inchide dropdown-ul
                await self._page.keyboard.press("Escape")
 
        except Exception as e:
            logger.warning(f"Eroare {field_name} ({time_value}): {e}")
 
    async def _select_dropdown(self, selector: str, value: str, field_name: str) -> None:
        """Selecteaza o valoare dintr-un dropdown generic (Type etc.)"""
        if not selector or not value:
            return
 
        try:
            elements = await self._page.query_selector_all(selector)
            if not elements:
                logger.warning(f"{field_name}: '{selector}' negasit")
                return
 
            target = elements[-1]
            tag = await target.evaluate("el => el.tagName.toLowerCase()")
 
            if tag == "select":
                try:
                    await target.select_option(label=value)
                except Exception:
                    await target.select_option(value=value)
                logger.debug(f"{field_name} = '{value}'")
                return
 
            # Element UI custom dropdown
            await target.click()
            await asyncio.sleep(0.5)
 
            found = await self._click_dropdown_option(value)
            if found:
                logger.debug(f"{field_name} = '{value}'")
            else:
                logger.warning(f"{field_name}: optiunea '{value}' nu a fost gasita")
                await self._page.keyboard.press("Escape")
 
        except Exception as e:
            logger.warning(f"Eroare {field_name}: {e}")
 
    async def _click_dropdown_option(self, value: str) -> bool:
        """
        Cauta si da click pe o optiune dintr-un dropdown Element UI deschis.
 
        Problema: dropdown-ul are scroll si nu toate optiunile sunt vizibile.
        Solutie: JavaScript scrollIntoView + click direct pe element.
        """
        await asyncio.sleep(0.3)
 
        # Strategia 1: JavaScript - scroll pana la optiune si click
        # Cel mai fiabil pentru dropdown-uri cu scroll
        result = await self._page.evaluate(f"""
            (value) => {{
                // Cauta in toate dropdown-urile Element UI deschise
                const selectors = [
                    '.el-select-dropdown__item',
                    '.el-scrollbar__view li',
                    '[class*="select-dropdown"] li',
                ];
                for (const sel of selectors) {{
                    const items = document.querySelectorAll(sel);
                    for (const item of items) {{
                        if (item.textContent.trim() === value) {{
                            item.scrollIntoView({{block: 'nearest', behavior: 'instant'}});
                            item.click();
                            return true;
                        }}
                    }}
                }}
                return false;
            }}
        """, value)
 
        if result:
            await asyncio.sleep(0.3)
            return True
 
        # Strategia 2: Playwright locator cu text exact
        try:
            loc = self._page.locator(
                f'.el-select-dropdown__item, .el-scrollbar__view li'
            ).filter(has_text=value).first
            if await loc.count() > 0:
                await loc.scroll_into_view_if_needed()
                await loc.click()
                await asyncio.sleep(0.3)
                return True
        except Exception:
            pass
 
        return False

    async def _save_settings(self) -> None:
        logger.info("Salvez setarile...")
        
        save_sel = self.sel.get("save_button", 'button:has-text("Submit")')
        try:
            btn = await self._page.query_selector(save_sel)
            if btn:
                await btn.click()
                await asyncio.sleep(3.5)
                await self._page.wait_for_load_state("networkidle")
                await asyncio.sleep(3.5)
                logger.info("✅ Setari salvate!")
            else:
                logger.warning(f"Buton Save negasit cu selectorul: {save_sel}")
        except Exception as e:
            logger.error(f"Eroare la salvare: {e}")

    # ──────────────────────────────────────────────
    # Utilitare
    # ──────────────────────────────────────────────

    async def _confirm_dialog(self) -> None:
        try:
            for sel in ['button:has-text("OK")', 'button:has-text("Yes")', 'button:has-text("Da")']:
                btn = await self._page.query_selector(sel)
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.2)
                    return
        except Exception:
            pass

    async def _get_error_text(self) -> str:
        for sel in ['.error-message', '.alert-danger', '[role="alert"]']:
            try:
                el = await self._page.query_selector(sel)
                if el:
                    return await el.inner_text()
            except Exception:
                pass
        return ""

    async def _screenshot(self, name: str) -> None:
        if not self.screenshot_on_error or not self._page:
            return
        try:
            Path("logs").mkdir(exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"logs/screenshot_{name}_{ts}.png"
            await self._page.screenshot(path=path, full_page=True)
            logger.info(f"Screenshot: {path}")
        except Exception:
            pass




