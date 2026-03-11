#!/usr/bin/env python3
"""
Starlink Billing Fetcher
========================
Entry point — orchestrates login, scraping, downloading and export.

Usage:
    python main.py

Requirements:
    pip install playwright pdfplumber openpyxl rich
    playwright install chromium
"""

import sys
import time

try:
    from playwright.sync_api import sync_playwright
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt
    from rich.panel import Panel
except ImportError as e:
    print(f"[ERROR] Missing dependency: {e}")
    print("Install with: pip install playwright pdfplumber openpyxl rich")
    print("Then run:     playwright install chromium")
    sys.exit(1)

from config import BILLING_URL, SESSION_FILE, CHROME_PATH, OUTPUT_DIR
from auth import login_flow, load_session, save_session, is_on_login_page
from scraper import get_account_list, switch_account, scrape_billing_rows, safe_goto
from downloader import download_invoice_pdf
from excel_export import build_excel, zip_pdfs
from utils import (
    ensure_dirs, parse_currency, ask_month_filter, fmt_date, build_record,
    make_date_range, wait_for_grid,
)

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


def ask_target_account(accounts: list[dict]) -> str | None:
    """
    Ask user whether to process all accounts or just one.
    Returns account_id string to target, or None for all accounts.
    """
    if len(accounts) <= 1:
        return None

    console.print("\n[bold]Account selection:[/bold]")
    console.print("  [cyan]0[/cyan] - All accounts")
    for i, acc in enumerate(accounts, 1):
        console.print(f"  [cyan]{i}[/cyan] - {acc['name']} [{acc['account_id']}]")

    choice = Prompt.ask("Select", default="0")
    try:
        idx = int(choice)
        if idx == 0:
            return None
        if 1 <= idx <= len(accounts):
            selected = accounts[idx - 1]
            console.print(f"  [green]→ Target: {selected['name']} [{selected['account_id']}][/green]")
            return selected["account_id"]
    except ValueError:
        for acc in accounts:
            if choice.upper() in acc["account_id"].upper():
                console.print(f"  [green]→ Target: {acc['name']} [{acc['account_id']}][/green]")
                return acc["account_id"]

    console.print("[yellow]Invalid selection — processing all accounts.[/yellow]")
    return None


def ask_run_mode() -> str:
    """Ask user to choose between invoice fetch or status report."""
    console.print("\n[bold]Run mode:[/bold]")
    console.print("  [cyan]1[/cyan] - Fetch invoices  (download PDFs + Excel)")
    console.print("  [cyan]2[/cyan] - Status report   (billing + subscription info)")

    choice = Prompt.ask("Select", choices=["1", "2"], default="1")
    return "fetch" if choice == "1" else "report"


def _launch_real_browser(pw):
    """
    Launch the user's real Chrome via subprocess + connect over CDP.
    Falls back to Playwright Chromium if CHROME_PATH is not set or not found.
    """
    import os, subprocess, tempfile

    if not CHROME_PATH or not os.path.exists(CHROME_PATH):
        if CHROME_PATH:
            console.print(f"[red]CHROME_PATH not found: {CHROME_PATH}[/red]")
            console.print("[yellow]Edit CHROME_PATH in config.py to point to your Chrome.[/yellow]")
        console.print("[yellow]⚠ Falling back to Playwright Chromium (may trigger bot detection).[/yellow]")
        return None, pw.chromium.launch(headless=False, args=["--start-maximized"])

    user_data_dir = os.path.join(tempfile.gettempdir(), "starlink_chrome_profile")
    os.makedirs(user_data_dir, exist_ok=True)

    cdp_port = 9222
    console.print(f"[green]✓ Launching real Chrome:[/green] [dim]{CHROME_PATH}[/dim]")

    proc = subprocess.Popen([
        CHROME_PATH,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        "--start-maximized",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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

    # ── Run mode ─────────────────────────────────────────────────
    run_mode = ask_run_mode()

    # ── Fetch mode (only for invoice fetch) ──────────────────────
    month_filter = None
    if run_mode == "fetch":
        month_filter = ask_month_filter()
        if month_filter:
            start, end = make_date_range(month_filter)
            console.print(f"[cyan]Fetching: Payment dates {start} → {end}[/cyan]")
        else:
            console.print("[cyan]Fetching all completed invoices (full history)...[/cyan]")

    from datetime import datetime
    run_ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode_slug = (
        f"{month_filter.year}{month_filter.month:02d}"
        if month_filter else "all"
    )
    run_label = f"{mode_slug}_{run_ts}"
    pdf_dir   = OUTPUT_DIR / "invoices" / run_label / mode_slug

    all_records: list[dict] = []

    with sync_playwright() as pw:
        chrome_proc, browser = _launch_real_browser(pw)
        stored = load_session()

        if chrome_proc:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page    = context.new_page()
            if stored:
                console.print("[dim]Note: session cookies not injectable into real Chrome — log in manually if prompted.[/dim]")
        else:
            ctx_opts = {"viewport": {"width": 1400, "height": 900}}
            if stored:
                console.print("[dim]Resuming saved session...[/dim]")
                ctx_opts["storage_state"] = stored
            context = browser.new_context(**ctx_opts)
            page    = context.new_page()

        # ── Auth ──────────────────────────────────────────────────────
        safe_goto(page, BILLING_URL)
        wait_for_grid(page, timeout=15000)

        if is_on_login_page(page):
            if stored and not chrome_proc:
                console.print("[yellow]Saved session expired — clearing...[/yellow]")
                SESSION_FILE.unlink(missing_ok=True)
                context.clear_cookies()
                safe_goto(page, BILLING_URL)
                page.wait_for_timeout(2000)
            login_flow(page)
        else:
            console.print("[green]✓ Session still active.[/green]")

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

        if not accounts:
            accounts = [{"name": "Current Account", "account_id": ""}]

        # ── Target account selection ──────────────────────────────────
        target_acc = ask_target_account(accounts)
        if target_acc:
            accounts = [a for a in accounts if a["account_id"] == target_acc]
            console.print(f"[cyan]Processing 1 account: {accounts[0]['name']}[/cyan]")
        else:
            console.print(f"[cyan]Processing all {len(accounts)} account(s).[/cyan]")

        # ── Route by run mode ─────────────────────────────────────────
        if run_mode == "report":
            from report import collect_account_report
            from excel_export import build_report_excel

            report_rows = []
            for idx, acc in enumerate(accounts):
                acc_name = acc["name"]
                acc_id   = acc["account_id"]
                console.print(
                    f"\n[bold cyan]Account {idx+1}/{len(accounts)}: "
                    f"{acc_name} [{acc_id}][/bold cyan]"
                )
                if acc_id:
                    switch_account(page, acc_id)
                if idx > 0:
                    time.sleep(5)

                row = collect_account_report(page, acc_name, acc_id)
                report_rows.append(row)

            report_path = build_report_excel(report_rows, run_label)
            console.print(Panel.fit(
                "[bold green]✓ Report done![/bold green]\n\n"
                f"📊 Excel : [cyan]{report_path}[/cyan]",
                border_style="green"
            ))

        else:
            # ── Invoice fetch ─────────────────────────────────────────
            for idx, acc in enumerate(accounts):
                acc_name = acc["name"]
                acc_id   = acc["account_id"]

                console.print(
                    f"\n[bold cyan]Account {idx+1}/{len(accounts)}: "
                    f"{acc_name} [{acc_id}][/bold cyan]"
                )

                if acc_id:
                    switch_account(page, acc_id)

                if idx > 0:
                    time.sleep(8)

                def _dl(row_el, inv_no):
                    return download_invoice_pdf(page, inv_no, acc_id or "main",
                                                row_el=row_el, pdf_dir=pdf_dir)

                rows = scrape_billing_rows(page, month_filter, download_fn=_dl)
                console.print(f"  Found [green]{len(rows)}[/green] completed invoice(s).")

                for row in rows:
                    inv_no   = row["invoice_number"]
                    pdf_path = row.get("pdf_path")
                    console.print(f"  [dim]→ {inv_no} | {row['date']} | {row['amount_str']}[/dim]")
                    record = build_record(row, pdf_path, acc_id)
                    all_records.append(record)

            # ── Export ────────────────────────────────────────────────
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

        browser.close()
        if chrome_proc:
            chrome_proc.terminate()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Cancelled by user]")
