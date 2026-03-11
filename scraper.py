from datetime import date
from rich.console import Console
from config import BILLING_URL
from utils import parse_row_date, wait_for, wait_for_grid, wait_for_rows, wait_for_menu, make_date_range

console = Console()
import time as _time


def safe_goto(page, url: str, retries: int = 5, base_wait: int = 30):
    """
    Navigate to url with automatic retry on HTTP error responses (429, 5xx).
    Waits base_wait * attempt seconds between retries.
    """
    for attempt in range(1, retries + 1):
        try:
            page.goto(url, wait_until="domcontentloaded")
            return
        except Exception as e:
            msg = str(e)
            if "ERR_HTTP_RESPONSE_CODE_FAILURE" in msg or "429" in msg or "503" in msg:
                wait = base_wait * attempt
                console.print(f"  [yellow]HTTP error navigating to {url} (attempt {attempt}/{retries}) — waiting {wait}s...[/yellow]")
                _time.sleep(wait)
            else:
                raise  # non-rate-limit error, propagate immediately
    # Final attempt — let it raise naturally
    page.goto(url, wait_until="domcontentloaded")


# ─────────────────────────────────────────────
#  Account discovery
# ─────────────────────────────────────────────

def _open_avatar_menu(page):
    """
    Click the HN/avatar circle button in the top-right to open the account menu.
    Returns True if opened successfully.
    """
    for sel in [
        '.MuiAvatar-root',
        'button .MuiAvatar-root',
        '[class*="MuiAvatar"]',
        'button[class*="Avatar"]',
        'button[class*="avatar"]',
    ]:
        el = page.query_selector(sel)
        if el:
            btn = el.query_selector("xpath=ancestor-or-self::button") or el
            btn.click()
            # Wait for menu to appear instead of fixed timeout
            if wait_for_menu(page, timeout=5000):
                return True
            # Menu didn't appear — try next selector
            continue

    # Fallback: last button in header with short alphabetic text (initials)
    btns = page.query_selector_all('header button')
    for btn in reversed(btns):
        txt = (btn.inner_text() or "").strip()
        if 1 <= len(txt) <= 3 and txt.replace(" ", "").isalpha():
            btn.click()
            if wait_for_menu(page, timeout=5000):
                return True

    return False


def _collect_menu_accounts(page) -> list[dict]:
    """
    Read all account entries from the avatar dropdown.
    Handles TWO-LEVEL menu: level 1 shows current user + chevron,
    level 2 is the full scrollable account list.
    """
    import re
    SKIP = {"language", "settings", "sign out", "sign in"}
    accounts = []
    seen_ids  = set()

    def scrape_items():
        items = page.query_selector_all('.MuiMenuItem-root, [role="menuitem"], [role="option"]')
        for item in items:
            text  = (item.inner_text() or "").strip()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            if not lines:
                continue
            name   = lines[0]
            acc_id = next((l for l in lines[1:] if "ACC-" in l), "")
            if not acc_id:
                m = re.search(r"ACC-[A-Z0-9-]+", text)
                acc_id = m.group(0) if m else ""
            if name.lower() in SKIP or not acc_id:
                continue
            if acc_id not in seen_ids:
                seen_ids.add(acc_id)
                accounts.append({"name": name, "account_id": acc_id})

    # First pass
    scrape_items()

    # Look for sub-menu trigger (chevron/arrow)
    items = page.query_selector_all('.MuiMenuItem-root, [role="menuitem"]')
    for item in items:
        text = (item.inner_text() or "").strip()
        if not text or text.lower() in SKIP:
            continue
        has_chevron = item.query_selector(
            '[class*="ChevronRight"], [class*="chevronRight"], '
            '[class*="ArrowRight"], [class*="arrowRight"], '
            '[data-testid*="chevron"], [data-testid*="arrow"]'
        )
        if not has_chevron:
            svgs = item.query_selector_all('svg')
            has_chevron = svgs[-1] if svgs else None
        if has_chevron:
            console.print(f"  [dim]Opening sub-menu: {text[:60]}[/dim]")
            item.click()
            # Wait for sub-menu items to load
            wait_for_menu(page, timeout=5000)
            break

    # Scroll the full list
    def get_scroll_container():
        for sel in [
            '.MuiMenu-paper', '.MuiMenu-list', '.MuiPopover-paper',
            '[role="menu"]', '[role="listbox"]', '[class*="MuiList-root"]',
        ]:
            el = page.query_selector(sel)
            if el:
                return el
        return None

    for attempt in range(40):
        prev_count = len(seen_ids)
        scrape_items()

        container = get_scroll_container()
        if container:
            try:
                page.evaluate("el => { el.scrollTop += 300; }", container)
            except Exception:
                pass
        else:
            page.keyboard.press("ArrowDown")

        page.wait_for_timeout(300)
        scrape_items()

        if len(seen_ids) == prev_count:
            if container:
                try:
                    page.evaluate("el => { el.scrollTop += 500; }", container)
                except Exception:
                    pass
            page.wait_for_timeout(600)
            scrape_items()
            if len(seen_ids) == prev_count:
                break

    return accounts


def get_account_list(page) -> list[dict]:
    """Open the avatar menu and collect all accounts."""
    accounts = []
    try:
        safe_goto(page, BILLING_URL)
        wait_for_grid(page, timeout=15000)

        opened = _open_avatar_menu(page)
        if not opened:
            btns = page.query_selector_all('header button, nav button')
            console.print(f"[yellow]Could not open account switcher. Header buttons found: {len(btns)}[/yellow]")
            for b in btns:
                console.print(f"  [dim]btn text={b.inner_text()!r} class={b.get_attribute('class')!r}[/dim]")
            return []

        accounts = _collect_menu_accounts(page)

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        if accounts:
            console.print(f"[green]Found {len(accounts)} account(s).[/green]")
        else:
            console.print("[yellow]No accounts found in switcher — using current only.[/yellow]")

    except Exception as e:
        console.print(f"[yellow]Account list warning: {e}[/yellow]")

    finally:
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass
        try:
            page.mouse.click(10, 10)
            page.wait_for_timeout(300)
        except Exception:
            pass

    return accounts


def switch_account(page, account_id: str):
    """Open avatar menu, click the account, then navigate to billing page."""
    try:
        safe_goto(page, BILLING_URL)
        wait_for_grid(page, timeout=15000)

        opened = _open_avatar_menu(page)
        if not opened:
            console.print(f"[yellow]Could not open account switcher for {account_id}[/yellow]")
            return

        items = page.query_selector_all('.MuiMenuItem-root, [role="menuitem"]')
        found_direct = False
        chevron_item = None
        for item in items:
            text = (item.inner_text() or "")
            if account_id in text:
                item.click()
                # Wait for account switch to complete — grid should re-render
                wait_for_grid(page, timeout=15000)
                safe_goto(page, BILLING_URL)
                wait_for_grid(page, timeout=15000)
                found_direct = True
                break
            if chevron_item is None and text.strip().lower() not in {"language","settings","sign out",""}:
                has_chevron = item.query_selector(
                    '[class*="ChevronRight"], [class*="chevronRight"], '
                    '[class*="ArrowRight"], [class*="arrowRight"]'
                )
                if not has_chevron:
                    svgs = item.query_selector_all('svg')
                    has_chevron = svgs[-1] if svgs else None
                if has_chevron:
                    chevron_item = item

        if found_direct:
            return

        # Open sub-menu
        if chevron_item:
            chevron_item.click()
            wait_for_menu(page, timeout=5000)

        def find_and_click():
            items = page.query_selector_all('.MuiMenuItem-root, [role="menuitem"], [role="option"]')
            for item in items:
                if account_id in (item.inner_text() or ""):
                    item.click()
                    return True
            return False

        if find_and_click():
            wait_for_grid(page, timeout=15000)
            safe_goto(page, BILLING_URL)
            wait_for_grid(page, timeout=15000)
            return

        # Scroll to find account
        for sel in ['.MuiMenu-paper', '.MuiPopover-paper', '[role="menu"]']:
            menu = page.query_selector(sel)
            if menu:
                for _ in range(20):
                    page.evaluate("el => { el.scrollTop += 250; }", menu)
                    page.wait_for_timeout(300)
                    if find_and_click():
                        wait_for_grid(page, timeout=15000)
                        safe_goto(page, BILLING_URL)
                        wait_for_grid(page, timeout=15000)
                        return
                break

        console.print(f"[yellow]Account {account_id} not found in menu.[/yellow]")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        page.mouse.click(10, 10)

    except Exception as e:
        console.print(f"[yellow]Account switch warning: {e}[/yellow]")
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass


# ─────────────────────────────────────────────
#  MUI DataGrid helpers
# ─────────────────────────────────────────────

def get_all_cells(row) -> dict:
    cells = row.query_selector_all(".MuiDataGrid-cell")
    result = {}
    for cell in cells:
        field = cell.get_attribute("data-field") or ""
        text  = (cell.inner_text() or "").strip()
        result[field] = text
    return result


def get_all_grids(page) -> list:
    return page.query_selector_all(".MuiDataGrid-root")


def click_next_page(grid) -> bool:
    btn = grid.query_selector(
        '.MuiTablePaginationActions-root button:last-child, '
        'button[aria-label="Go to next page"], '
        'button[title="Next page"]'
    )
    if btn and btn.get_attribute("disabled") is None:
        btn.click()
        return True
    return False


# ─────────────────────────────────────────────
#  Invoice table (Grid 0)
# ─────────────────────────────────────────────

PAID_STATUSES   = {"paid", "complete", "completed", "success", "succeeded"}
FAILED_STATUSES = {"failed", "error", "declined", "void", "voided", "refunded"}


def build_invoice_lookup(page) -> dict[str, dict]:
    """Read all rows from Grid 0 (invoice table), re-querying fresh each page."""
    lookup = {}
    while True:
        grids = get_all_grids(page)
        if not grids:
            break
        grid = grids[0]
        for row in grid.query_selector_all(".MuiDataGrid-row"):
            cells = get_all_cells(row)
            inv_no = cells.get("invoiceNumber", "")
            if inv_no:
                lookup[inv_no] = {
                    "invoice_date": cells.get("invoiceDate", ""),
                    "amount_str":   cells.get("invoiceTotalNaturalAmount", ""),
                    "status":       cells.get("status", ""),
                }
        grids = get_all_grids(page)
        if grids and click_next_page(grids[0]):
            # Wait for rows to update after pagination
            wait_for_rows(page, timeout=8000)
        else:
            break
    console.print(f"  [dim]Invoice grid: {len(lookup)} invoice(s).[/dim]")
    return lookup


# ─────────────────────────────────────────────
#  Payment table (Grid 1) — scrape + download together
# ─────────────────────────────────────────────

def scrape_and_download_page(grid, month_filter, invoice_lookup, download_fn) -> tuple[list[dict], bool]:
    """
    Process one page of the payment table.
    Uses date range: day 5 of selected month → day 6 of next month (inclusive).
    """
    row_els    = grid.query_selector_all(".MuiDataGrid-row")
    results    = []
    stop_early = False

    # Build date range if filtering
    date_start, date_end = None, None
    if month_filter:
        date_start, date_end = make_date_range(month_filter)

    for row_el in row_els:
        cells = get_all_cells(row_el)
        if not cells:
            continue

        inv_no      = cells.get("appliedInvoices") or cells.get("invoiceNumber") or ""
        pay_date    = cells.get("paymentDate") or cells.get("date") or ""
        amount_str  = cells.get("amount") or cells.get("total") or ""
        status      = cells.get("status") or ""

        if not inv_no:
            continue

        if status.lower() in FAILED_STATUSES:
            continue

        inv_info         = invoice_lookup.get(inv_no, {})
        invoice_date_str = inv_info.get("invoice_date") or pay_date
        amount_str       = inv_info.get("amount_str") or amount_str

        payment_row_date = parse_row_date(pay_date)

        if month_filter and payment_row_date:
            # Stop scrolling once payment date is before the range start
            if payment_row_date < date_start:
                stop_early = True
                break
            # Include only rows within [date_start, date_end]
            if not (date_start <= payment_row_date <= date_end):
                continue

        # ── Download PDF NOW while row_el is still attached ──
        pdf_path = download_fn(row_el, inv_no)

        results.append({
            "date":           pay_date,
            "row_date":       payment_row_date,
            "invoice_number": inv_no,
            "amount_str":     amount_str,
            "invoice_date":   invoice_date_str,
            "status":         status,
            "pdf_path":       pdf_path,
        })

    return results, stop_early


# ─────────────────────────────────────────────
#  Main scrape entry point
# ─────────────────────────────────────────────

def scrape_billing_rows(page, month_filter: date | None = None, download_fn=None) -> list[dict]:
    """
    Scrape billing rows. download_fn(row_el, invoice_number) is called
    immediately per row while the DOM element is still live.
    """
    safe_goto(page, BILLING_URL)
    # Wait for DataGrid to render instead of fixed timeout
    wait_for_grid(page, timeout=15000)

    if month_filter:
        start, end = make_date_range(month_filter)
        console.print(f"[cyan]  Scraping billing page ({start} → {end})...[/cyan]")
    else:
        console.print("[cyan]  Scraping billing page (full history)...[/cyan]")

    grids = get_all_grids(page)
    console.print(f"  [dim]{len(grids)} DataGrid(s) found.[/dim]")

    if not grids:
        console.print("[red]No DataGrids found.[/red]")
        return []

    invoice_lookup = build_invoice_lookup(page)

    if len(grids) < 2:
        console.print("[yellow]Only one grid — using invoice table.[/yellow]")
        rows = []
        date_start, date_end = None, None
        if month_filter:
            date_start, date_end = make_date_range(month_filter)
        for inv_no, info in invoice_lookup.items():
            if info["status"].lower() not in PAID_STATUSES:
                continue
            row_date = parse_row_date(info["invoice_date"])
            if month_filter and row_date:
                if not (date_start <= row_date <= date_end):
                    continue
            pdf_path = download_fn(None, inv_no) if download_fn else None
            rows.append({
                "date": info["invoice_date"], "row_date": row_date,
                "invoice_number": inv_no, "amount_str": info["amount_str"],
                "invoice_date": info["invoice_date"], "status": info["status"],
                "pdf_path": pdf_path,
            })
        return rows

    all_rows: list[dict]    = []
    seen:     set[str]      = set()
    page_num  = 1
    _noop     = download_fn or (lambda el, inv: None)

    while True:
        console.print(f"  [dim]Payment table page {page_num}...[/dim]")

        fresh_grids = get_all_grids(page)
        if len(fresh_grids) < 2:
            console.print("[yellow]Payment grid disappeared — stopping.[/yellow]")
            break
        pay_grid = fresh_grids[1]

        rows, stop_early = scrape_and_download_page(pay_grid, month_filter, invoice_lookup, _noop)

        for r in rows:
            if r["invoice_number"] not in seen:
                seen.add(r["invoice_number"])
                all_rows.append(r)

        if rows:
            console.print(f"  [dim]+{len(rows)} row(s) (total: {len(all_rows)})[/dim]")

        if stop_early:
            console.print("  [dim]Reached earlier dates — stopping.[/dim]")
            break

        fresh_grids = get_all_grids(page)
        if len(fresh_grids) < 2:
            break
        if click_next_page(fresh_grids[1]):
            page_num += 1
            # Wait for rows to update after pagination
            wait_for_rows(page, timeout=8000)
        else:
            console.print("  [dim]No more pages.[/dim]")
            break

    return all_rows
