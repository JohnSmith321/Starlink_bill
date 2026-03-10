#!/usr/bin/env python3
"""
Starlink Billing Fetcher
========================
Entry point — orchestrates login, scraping, downloading and export.
All logic lives in the dedicated modules:

    config.py       — constants (URLs, paths, column headers)
    auth.py         — login, OTP handling, session save/load
    scraper.py      — billing page scraping, account switching
    downloader.py   — PDF download per invoice
    pdf_parser.py   — data extraction from downloaded PDFs
    excel_export.py — Excel workbook builder and PDF zipper
    utils.py        — shared helpers (currency parser, date parser, prompts)

Usage:
    python main.py

Requirements:
    pip install playwright pdfplumber openpyxl rich
    playwright install chromium
"""

import sys

try:
    from playwright.sync_api import sync_playwright
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.panel import Panel
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Install with: pip install playwright pdfplumber openpyxl rich")
    print("Then run:     playwright install chromium")
    sys.exit(1)

from config import BILLING_URL, MONTH_NAMES, SESSION_FILE, CHROME_PATH, OUTPUT_DIR, INVOICES_DIR
from auth import login_flow, load_session, save_session, is_on_login_page
from scraper import get_account_list, switch_account, scrape_billing_rows, safe_goto
from downloader import download_invoice_pdf
from excel_export import build_excel, zip_pdfs
from utils import ensure_dirs, parse_currency, ask_month_filter, fmt_date, build_record

console = Console()


def print_summary(all_records: list[dict]):
    tbl = Table(title="Export Summary", show_header=True, header_style="bold green")
    tbl.add_column("Account")
    tbl.add_column("Invoice")
    tbl.add_column("Payment Date")
    tbl.add_column("Amount")
    for rec in all_records:
        tbl.add_row(
            rec["customer_account"],
            rec["invoice_number"],
            str(rec["payment_date"]),
            f"{rec['currency']} {rec['amount']:,.2f}",
        )
    console.print(tbl)



def _launch_real_browser(pw):
    """
    Launch the user's real Chrome via subprocess + connect over CDP.
    This is the only way to get a true Chrome instance — not "Chrome for Testing".

    Falls back to Playwright Chromium if CHROME_PATH is not set or not found.
    """
    import os, subprocess, time, tempfile

    path = CHROME_PATH if CHROME_PATH else None

    if not path or not os.path.exists(path):
        if path:
            console.print(f"[red]CHROME_PATH not found: {path}[/red]")
            console.print("[yellow]Edit CHROME_PATH in config.py to point to your Chrome.[/yellow]")
        console.print("[yellow]⚠ Falling back to Playwright Chromium (may trigger bot detection).[/yellow]")
        return None, pw.chromium.launch(headless=False, args=["--start-maximized"])

    # Use a temp user-data-dir so Chrome launches fresh without conflicting
    # with your regular Chrome profile
    user_data_dir = os.path.join(tempfile.gettempdir(), "starlink_chrome_profile")
    os.makedirs(user_data_dir, exist_ok=True)

    cdp_port = 9222
    console.print(f"[green]✓ Launching real Chrome:[/green] [dim]{path}[/dim]")

    proc = subprocess.Popen([
        path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Wait for Chrome to start and open CDP port
    time.sleep(8)

    try:
        browser = pw.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
        console.print("[green]✓ Connected to real Chrome via CDP.[/green]")
        return proc, browser
    except Exception as e:
        console.print(f"[red]Could not connect to Chrome CDP: {e}[/red]")
        proc.terminate()
        console.print("[yellow]Falling back to Playwright Chromium.[/yellow]")
        return None, pw.chromium.launch(headless=False, args=["--start-maximized"])


def main():
    console.print(Panel.fit(
        "[bold cyan]Starlink Billing Fetcher[/bold cyan]\n"
        "[dim]Downloads completed invoices and exports to Excel[/dim]",
        border_style="cyan"
    ))

    ensure_dirs()

    console.print("\n[bold]Starlink Account Login[/bold]")

    # ── Fetch mode ────────────────────────────────────────────────────
    month_filter = ask_month_filter()
    if month_filter:
        console.print(f"[cyan]Fetching: {MONTH_NAMES[month_filter.month]} {month_filter.year}[/cyan]")
    else:
        console.print("[cyan]Fetching all completed invoices (full history)...[/cyan]")

    from datetime import datetime as _dt
    from pathlib import Path as _Path
    run_ts    = _dt.now().strftime("%Y%m%d_%H%M%S")
    mode_slug = (
        f"{month_filter.year}{month_filter.month:02d}"
        if month_filter else "all"
    )
    run_label = f"{mode_slug}_{run_ts}"
    # PDF folder: starlink_output/invoices/{run_label}/{mode_slug}/
    pdf_dir   = OUTPUT_DIR / "invoices" / run_label / mode_slug

    all_records: list[dict] = []

    with sync_playwright() as pw:
        # Launch real Chrome via CDP, or fall back to Playwright Chromium
        chrome_proc, browser = _launch_real_browser(pw)

        # Restore saved session if available (only for Playwright Chromium)
        stored = load_session()

        if chrome_proc:
            # Real Chrome via CDP — use the existing default context
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page    = context.new_page()
            if stored:
                console.print("[dim]Note: session cookies not injectable into real Chrome — log in manually if prompted.[/dim]")
        else:
            # Playwright Chromium — can inject saved session
            ctx_opts = {"viewport": {"width": 1400, "height": 900}}
            if stored:
                console.print("[dim]Resuming saved session...[/dim]")
                ctx_opts["storage_state"] = stored
            context = browser.new_context(**ctx_opts)
            page    = context.new_page()

        # ── Auth ──────────────────────────────────────────────────────
        safe_goto(page, BILLING_URL)
        page.wait_for_timeout(3000)

        if is_on_login_page(page):
            # If we had a saved session and it's expired, clear it
            if stored and not chrome_proc:
                console.print("[yellow]Saved session expired — clearing...[/yellow]")
                SESSION_FILE.unlink(missing_ok=True)
                context.clear_cookies()
                safe_goto(page, BILLING_URL)
                page.wait_for_timeout(2000)
            login_flow(page)
        else:
            console.print("[green]✓ Session still active.[/green]")

        # Save session (Playwright Chromium only — CDP context state not portable)
        if not chrome_proc:
            save_session(context.storage_state())

        # ── Account discovery ─────────────────────────────────────────
        console.print("\n[bold]Discovering accounts...[/bold]")
        accounts = get_account_list(page)

        if accounts:
            tbl = Table(title="Accounts Found", show_header=True, header_style="bold cyan")
            tbl.add_column("Name")
            tbl.add_column("Account ID")
            for acc in accounts:
                tbl.add_row(acc["name"], acc["account_id"])
            console.print(tbl)

            console.print(f"[cyan]Processing all {len(accounts)} account(s) automatically.[/cyan]")

        if not accounts:
            accounts = [{"name": "Current Account", "account_id": ""}]

        # ── Per-account fetch loop ────────────────────────────────────
        for idx, acc in enumerate(accounts):
            acc_name = acc["name"]
            acc_id   = acc["account_id"]

            console.print(
                f"\n[bold cyan]Account {idx+1}/{len(accounts)}: "
                f"{acc_name} [{acc_id}][/bold cyan]"
            )

            if acc_id:
                switch_account(page, acc_id)

            # Polite delay between accounts to avoid rate limiting
            if idx > 0:
                import time
                time.sleep(8)

            def _dl(row_el, inv_no):
                return download_invoice_pdf(page, inv_no, acc_id or "main",
                                            row_el=row_el, pdf_dir=pdf_dir)

            rows = scrape_billing_rows(page, month_filter, download_fn=_dl)
            console.print(f"  Found [green]{len(rows)}[/green] completed invoice(s).")

            for row in rows:
                inv_no   = row["invoice_number"]
                pdf_path = row.get("pdf_path")   # already downloaded during scraping
                console.print(f"  [dim]→ {inv_no} | {row['date']} | {row['amount_str']}[/dim]")
                record = build_record(row, pdf_path, acc_id)
                all_records.append(record)

        browser.close()
        if chrome_proc:
            chrome_proc.terminate()

    # ── Export ────────────────────────────────────────────────────────
    console.print(f"\n[bold]Exporting {len(all_records)} invoice(s)...[/bold]")

    if all_records:
        excel_path = build_excel(all_records, run_label)
        zip_path   = zip_pdfs(run_label, pdf_dir)
        print_summary(all_records)
        console.print(Panel.fit(
            "[bold green]✓ Done![/bold green]\n\n"
            f"📊 Excel : [cyan]{excel_path}[/cyan]\n"
            f"📦 ZIP   : [cyan]{zip_path}[/cyan]\n"
            f"📁 PDFs  : [cyan]starlink_output/invoices/[/cyan]",
            border_style="green"
        ))
    else:
        console.print("[yellow]No completed invoices found matching your criteria.[/yellow]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Cancelled by user]")
