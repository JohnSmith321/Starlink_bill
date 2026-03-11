"""
Streamlit Web UI for Starlink Billing Fetcher.
Run with:  streamlit run app.py
"""

# Fix Playwright on Windows: Streamlit/Tornado uses SelectorEventLoop which
# doesn't support subprocess creation. Switch to ProactorEventLoop policy
# BEFORE any Playwright import so its internal loop can spawn processes.
import sys
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import os
import subprocess
import tempfile
import streamlit as st
import time
import pandas as pd
from datetime import date, datetime
from pathlib import Path

# ─────────────────────────────────────────────
#  Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Starlink Billing Fetcher",
    page_icon="🛰️",
    layout="centered",
)

# ─────────────────────────────────────────────
#  Session state defaults
# ─────────────────────────────────────────────
DEFAULTS = {
    "step": "credentials",   # credentials → launching → captcha → otp → fetching → done
    "pw": None,
    "browser": None,
    "page": None,
    "context": None,
    "chrome_proc": None,
    "logs": [],
    "records": [],
    "report_rows": [],
    "excel_path": None,
    "zip_path": None,
    "error": None,
    "month_filter": None,
    "email": "",
    "password": "",
    "target_account": "",
    "run_mode": "fetch",
    "captcha_detected": False,
    "otp_needed": False,
    "fetch_done": False,
}

for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


def log(msg: str):
    st.session_state.logs.append(f"`{datetime.now().strftime('%H:%M:%S')}` {msg}")


def cleanup_browser():
    """Safely close browser and Playwright resources."""
    try:
        if st.session_state.browser:
            st.session_state.browser.close()
    except Exception:
        pass
    try:
        if st.session_state.chrome_proc:
            st.session_state.chrome_proc.terminate()
    except Exception:
        pass
    try:
        if st.session_state.pw:
            st.session_state.pw.stop()
    except Exception:
        pass
    st.session_state.browser = None
    st.session_state.page = None
    st.session_state.context = None
    st.session_state.chrome_proc = None
    st.session_state.pw = None


# ─────────────────────────────────────────────
#  Header
# ─────────────────────────────────────────────
st.title("Starlink Billing Fetcher")
st.caption("Downloads invoices and exports to Excel — no terminal needed.")

# ─────────────────────────────────────────────
#  Sidebar: logs
# ─────────────────────────────────────────────
with st.sidebar:
    st.header("Activity Log")
    if st.session_state.logs:
        for entry in reversed(st.session_state.logs[-50:]):
            st.markdown(entry, unsafe_allow_html=True)
    else:
        st.info("Logs will appear here.")

    if st.button("Reset", type="secondary"):
        cleanup_browser()
        for key, default in DEFAULTS.items():
            st.session_state[key] = default
        st.rerun()

# ═════════════════════════════════════════════
#  STEP: credentials
# ═════════════════════════════════════════════
if st.session_state.step == "credentials":
    st.subheader("1. Login Credentials")

    with st.form("cred_form"):
        email    = st.text_input("Email", value=st.session_state.email)
        password = st.text_input("Password", type="password", value=st.session_state.password)

        st.divider()
        st.subheader("2. Run Mode")
        run_mode = st.radio("Select mode", ["Fetch invoices", "Status report"], horizontal=True)

        st.divider()
        st.subheader("3. Fetch Options")
        fetch_mode = st.radio("Date range", ["All invoices (full history)", "Single month"],
                              horizontal=True)

        col1, col2 = st.columns(2)
        now = datetime.now()
        year  = col1.number_input("Year",  min_value=2019, max_value=2035, value=now.year)
        month = col2.number_input("Month", min_value=1,    max_value=12,   value=now.month)

        st.divider()
        st.subheader("4. Account Filter (optional)")
        target_account = st.text_input(
            "Target Account ID",
            value=st.session_state.target_account,
            placeholder="Leave empty for all accounts, or enter ACC-xxx",
        )

        submitted = st.form_submit_button("Start", type="primary", width="stretch")

    if submitted:
        if not email or not password:
            st.error("Please enter both email and password.")
        else:
            st.session_state.email    = email
            st.session_state.password = password
            st.session_state.run_mode = "report" if run_mode == "Status report" else "fetch"
            st.session_state.target_account = target_account.strip()
            if fetch_mode == "Single month":
                st.session_state.month_filter = date(int(year), int(month), 1)
            else:
                st.session_state.month_filter = None
            st.session_state.step = "launching"
            st.rerun()


# ═════════════════════════════════════════════
#  STEP: launching browser + auto-fill
# ═════════════════════════════════════════════
elif st.session_state.step == "launching":
    st.subheader("Launching browser...")
    progress = st.progress(0, text="Starting Chrome...")

    try:
        from playwright.sync_api import sync_playwright
        from config import BILLING_URL, LOGIN_URL, CHROME_PATH
        from auth import (
            load_session, is_on_login_page, detect_captcha,
            fill_email, fill_password, click_submit, detect_otp_page,
            _wait_for_next_step,
        )
        from scraper import safe_goto
        from utils import wait_for_any, wait_for_grid

        # Launch Playwright
        pw = sync_playwright().start()
        st.session_state.pw = pw
        log("Playwright started.")
        progress.progress(10, text="Detecting Chrome...")

        # Launch browser
        chrome_proc = None

        if CHROME_PATH and os.path.exists(CHROME_PATH):
            user_data_dir = os.path.join(tempfile.gettempdir(), "starlink_chrome_profile")
            os.makedirs(user_data_dir, exist_ok=True)
            cdp_port = 9222

            log(f"Launching Chrome: {CHROME_PATH}")
            progress.progress(20, text="Launching Chrome...")

            chrome_proc = subprocess.Popen([
                CHROME_PATH,
                f"--remote-debugging-port={cdp_port}",
                f"--user-data-dir={user_data_dir}",
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-extensions",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            progress.progress(40, text="Waiting for Chrome to start...")
            time.sleep(8)

            try:
                browser = pw.chromium.connect_over_cdp(f"http://localhost:{cdp_port}")
                st.session_state.chrome_proc = chrome_proc
                log("Connected to Chrome via CDP.")
            except Exception as e:
                chrome_proc.terminate()
                log(f"CDP failed: {e} — falling back to Playwright Chromium.")
                browser = pw.chromium.launch(headless=False, args=["--start-maximized"])
        else:
            log("Chrome not found — using Playwright Chromium.")
            browser = pw.chromium.launch(headless=False, args=["--start-maximized"])

        st.session_state.browser = browser
        progress.progress(50, text="Setting up page...")

        # Create context + page
        if st.session_state.chrome_proc:
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        else:
            stored = load_session()
            ctx_opts = {"viewport": {"width": 1400, "height": 900}}
            if stored:
                ctx_opts["storage_state"] = stored
                log("Loaded saved session.")
            context = browser.new_context(**ctx_opts)

        page = context.new_page()
        st.session_state.context = context
        st.session_state.page = page

        progress.progress(60, text="Navigating to Starlink...")
        safe_goto(page, BILLING_URL)
        # Wait for grid or login page instead of fixed timeout
        wait_for_grid(page, timeout=15000)

        if not is_on_login_page(page):
            log("Session still active — skipping login!")
            progress.progress(100, text="Already logged in!")
            st.session_state.step = "fetching"
            time.sleep(1)
            st.rerun()

        # Navigate to login
        progress.progress(70, text="Login page detected — filling credentials...")
        safe_goto(page, LOGIN_URL)
        # Wait for email field
        from config import EMAIL_SELECTORS
        wait_for_any(page, EMAIL_SELECTORS, timeout=10000)

        # Check CAPTCHA before filling
        if detect_captcha(page):
            log("CAPTCHA detected before login!")
            st.session_state.captcha_detected = True
            st.session_state.step = "captcha"
            progress.progress(75, text="CAPTCHA detected!")
            st.rerun()

        # Fill email
        if fill_email(page, st.session_state.email):
            log("Filled email.")
        page.wait_for_timeout(300)
        click_submit(page)
        # Wait for next step (password/captcha/OTP)
        _wait_for_next_step(page, timeout=10000)

        progress.progress(80, text="Email submitted...")

        # Check CAPTCHA after email
        if detect_captcha(page):
            log("CAPTCHA detected after email step!")
            st.session_state.captcha_detected = True
            st.session_state.step = "captcha"
            st.rerun()

        # Fill password
        if fill_password(page, st.session_state.password):
            log("Filled password.")
        page.wait_for_timeout(300)
        click_submit(page)
        # Wait for OTP/redirect/captcha
        _wait_for_next_step(page, timeout=10000)

        progress.progress(90, text="Password submitted...")

        # Check CAPTCHA after password
        if detect_captcha(page):
            log("CAPTCHA detected after password step!")
            st.session_state.captcha_detected = True
            st.session_state.step = "captcha"
            st.rerun()

        # Check if OTP is needed
        if detect_otp_page(page):
            log("OTP page detected.")
            st.session_state.otp_needed = True
            st.session_state.step = "otp"
            progress.progress(95, text="OTP required...")
            st.rerun()

        # If already logged in
        if not is_on_login_page(page):
            log("Login successful!")
            progress.progress(100, text="Logged in!")
            st.session_state.step = "fetching"
            time.sleep(1)
            st.rerun()

        # Fallback: wait for OTP or manual completion
        log("Waiting for OTP page...")
        for _ in range(15):
            if detect_otp_page(page):
                st.session_state.step = "otp"
                st.rerun()
            if not is_on_login_page(page):
                st.session_state.step = "fetching"
                st.rerun()
            time.sleep(1)

        st.session_state.step = "otp"
        st.rerun()

    except Exception as e:
        st.error(f"Error: {e}")
        log(f"ERROR: {e}")
        cleanup_browser()
        st.session_state.step = "credentials"


# ═════════════════════════════════════════════
#  STEP: captcha
# ═════════════════════════════════════════════
elif st.session_state.step == "captcha":
    st.subheader("CAPTCHA Challenge")
    st.warning("A CAPTCHA has been detected in the browser window.")
    st.info("Please switch to the Chrome window and solve the CAPTCHA, then click **Continue** below.")

    col1, col2 = st.columns(2)
    if col1.button("Continue", type="primary", width="stretch"):
        page = st.session_state.page
        if page:
            from auth import detect_captcha, fill_password, click_submit, detect_otp_page, is_on_login_page, _wait_for_next_step
            page.wait_for_timeout(500)

            if detect_captcha(page):
                st.error("CAPTCHA still detected! Please solve it first.")
            else:
                log("CAPTCHA solved!")

                if fill_password(page, st.session_state.password):
                    log("Filled password after CAPTCHA.")
                    page.wait_for_timeout(300)
                    click_submit(page)
                    _wait_for_next_step(page, timeout=10000)

                    if detect_captcha(page):
                        st.session_state.step = "captcha"
                        st.rerun()

                if detect_otp_page(page):
                    st.session_state.step = "otp"
                    st.rerun()
                elif not is_on_login_page(page):
                    st.session_state.step = "fetching"
                    st.rerun()
                else:
                    st.session_state.step = "otp"
                    st.rerun()

    if col2.button("Cancel", width="stretch"):
        cleanup_browser()
        st.session_state.step = "credentials"
        st.rerun()


# ═════════════════════════════════════════════
#  STEP: otp
# ═════════════════════════════════════════════
elif st.session_state.step == "otp":
    st.subheader("Enter OTP")
    st.info("An OTP code has been sent to your email. Enter it below.")

    with st.form("otp_form"):
        otp_code = st.text_input("OTP Code", max_chars=10, placeholder="123456")
        submitted = st.form_submit_button("Submit OTP", type="primary", width="stretch")

    if submitted and otp_code:
        page = st.session_state.page
        if page:
            from auth import fill_otp, is_on_login_page, detect_captcha

            if detect_captcha(page):
                st.session_state.step = "captcha"
                st.rerun()

            if fill_otp(page, otp_code):
                log("Filled OTP.")
            else:
                log("Could not auto-fill OTP — please enter manually in browser.")

            # Wait for redirect away from login
            for _ in range(15):
                if not is_on_login_page(page):
                    break
                time.sleep(1)

            if detect_captcha(page):
                st.session_state.step = "captcha"
                st.rerun()

            if is_on_login_page(page):
                st.error("Still on login page. Please check OTP and try again.")
            else:
                log("Login successful!")

                if not st.session_state.chrome_proc and st.session_state.context:
                    from auth import save_session
                    save_session(st.session_state.context.storage_state())
                    log("Session saved for next time.")

                st.session_state.step = "fetching"
                st.rerun()

    if st.button("I already entered OTP manually in the browser"):
        page = st.session_state.page
        if page:
            from auth import is_on_login_page
            time.sleep(2)
            if not is_on_login_page(page):
                log("Login confirmed (manual OTP).")
                st.session_state.step = "fetching"
                st.rerun()
            else:
                st.error("Still on login page — please complete login first.")


# ═════════════════════════════════════════════
#  STEP: fetching
# ═════════════════════════════════════════════
elif st.session_state.step == "fetching":
    run_mode = st.session_state.run_mode
    page     = st.session_state.page
    month_f  = st.session_state.month_filter

    if run_mode == "report":
        st.subheader("Generating Status Report")
    else:
        st.subheader("Fetching Invoices")
        if month_f:
            from utils import make_date_range
            start, end = make_date_range(month_f)
            st.info(f"Fetching: **Payment dates {start} → {end}**")
        else:
            st.info("Fetching: **All invoices (full history)**")

    status_area  = st.empty()
    progress_bar = st.progress(0)

    try:
        from config import BILLING_URL, OUTPUT_DIR
        from auth import save_session
        from scraper import get_account_list, switch_account, scrape_billing_rows, safe_goto
        from downloader import download_invoice_pdf
        from excel_export import build_excel, zip_pdfs, build_report_excel
        from utils import ensure_dirs, build_record

        ensure_dirs()

        # Save session
        if not st.session_state.chrome_proc and st.session_state.context:
            try:
                save_session(st.session_state.context.storage_state())
            except Exception:
                pass

        # Run label
        run_ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
        mode_slug = f"{month_f.year}{month_f.month:02d}" if month_f else "all"
        run_label = f"{mode_slug}_{run_ts}"
        pdf_dir   = OUTPUT_DIR / "invoices" / run_label / mode_slug

        # ── Account discovery ─────────────────────────
        status_area.text("Discovering accounts...")
        log("Discovering accounts...")
        accounts = get_account_list(page)
        if not accounts:
            accounts = [{"name": "Current Account", "account_id": ""}]
        log(f"Found {len(accounts)} account(s).")

        # Filter to target account if specified
        target = st.session_state.target_account
        if target:
            filtered = [a for a in accounts if target.upper() in a["account_id"].upper()]
            if filtered:
                accounts = filtered
                log(f"Targeting account: {accounts[0]['name']} [{accounts[0]['account_id']}]")
            else:
                log(f"Target account '{target}' not found — processing all.")

        progress_bar.progress(10)

        if run_mode == "report":
            # ── Report mode ─────────────────────────────
            from report import collect_account_report

            report_rows = []
            total_accs = len(accounts)
            for idx, acc in enumerate(accounts):
                acc_name = acc["name"]
                acc_id   = acc["account_id"]
                status_area.text(f"Report {idx+1}/{total_accs}: {acc_name} [{acc_id}]")
                log(f"Reporting: {acc_name} [{acc_id}]")

                if acc_id:
                    switch_account(page, acc_id)
                if idx > 0:
                    time.sleep(5)

                row = collect_account_report(page, acc_name, acc_id)
                report_rows.append(row)

                pct = 10 + int(80 * (idx + 1) / total_accs)
                progress_bar.progress(min(pct, 90))

            status_area.text("Exporting report...")
            report_path = build_report_excel(report_rows, run_label)
            log(f"Report: {report_path}")

            st.session_state.report_rows = report_rows
            st.session_state.excel_path  = report_path
            st.session_state.zip_path    = None
            st.session_state.records     = []

        else:
            # ── Invoice fetch mode ──────────────────────
            all_records = []
            total_accs = len(accounts)
            for idx, acc in enumerate(accounts):
                acc_name = acc["name"]
                acc_id   = acc["account_id"]
                status_area.text(f"Account {idx+1}/{total_accs}: {acc_name} [{acc_id}]")
                log(f"Processing account: {acc_name} [{acc_id}]")

                if acc_id:
                    switch_account(page, acc_id)
                if idx > 0:
                    time.sleep(8)

                def _dl(row_el, inv_no):
                    return download_invoice_pdf(page, inv_no, acc_id or "main",
                                                row_el=row_el, pdf_dir=pdf_dir)

                rows = scrape_billing_rows(page, month_f, download_fn=_dl)
                log(f"  Found {len(rows)} invoice(s) for {acc_name}.")

                for row in rows:
                    pdf_path = row.get("pdf_path")
                    record = build_record(row, pdf_path, acc_id)
                    all_records.append(record)

                pct = 10 + int(80 * (idx + 1) / total_accs)
                progress_bar.progress(min(pct, 90))

            # ── Export ────────────────────────────────────
            status_area.text("Exporting to Excel...")
            log(f"Exporting {len(all_records)} invoice(s)...")

            excel_path = None
            zip_path   = None
            if all_records:
                excel_path = build_excel(all_records, run_label)
                zip_path   = zip_pdfs(run_label, pdf_dir)
                log(f"Excel: {excel_path}")
                log(f"ZIP: {zip_path}")

            st.session_state.records    = all_records
            st.session_state.excel_path = excel_path
            st.session_state.zip_path   = zip_path

        progress_bar.progress(100)
        status_area.text("Done!")
        log("Complete!")

        cleanup_browser()
        st.session_state.step = "done"
        st.rerun()

    except Exception as e:
        st.error(f"Error during fetch: {e}")
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())


# ═════════════════════════════════════════════
#  STEP: done — results
# ═════════════════════════════════════════════
elif st.session_state.step == "done":
    records     = st.session_state.records
    report_rows = st.session_state.report_rows
    excel_path  = st.session_state.excel_path
    zip_path    = st.session_state.zip_path
    run_mode    = st.session_state.run_mode

    if run_mode == "report" and report_rows:
        st.subheader(f"Status Report: {len(report_rows)} account(s)")

        df = pd.DataFrame(report_rows)
        st.dataframe(df, width="stretch", hide_index=True)

        if excel_path and Path(excel_path).exists():
            with open(excel_path, "rb") as f:
                st.download_button(
                    label="Download Report Excel",
                    data=f.read(),
                    file_name=Path(excel_path).name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    width="stretch",
                )

    elif records:
        st.subheader(f"Results: {len(records)} invoice(s)")

        df = pd.DataFrame(records)
        display_cols = ["customer_account", "invoice_number", "invoice_date", "payment_date", "amount", "currency"]
        st.dataframe(df[display_cols], width="stretch", hide_index=True)

        st.divider()
        col1, col2 = st.columns(2)

        if excel_path and Path(excel_path).exists():
            with open(excel_path, "rb") as f:
                col1.download_button(
                    label="Download Excel",
                    data=f.read(),
                    file_name=Path(excel_path).name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary",
                    width="stretch",
                )

        if zip_path and Path(zip_path).exists():
            with open(zip_path, "rb") as f:
                col2.download_button(
                    label="Download PDFs (ZIP)",
                    data=f.read(),
                    file_name=Path(zip_path).name,
                    mime="application/zip",
                    width="stretch",
                )

        st.divider()
        for cur in df["currency"].unique():
            total = df[df["currency"] == cur]["amount"].sum()
            st.metric(f"Total ({cur})", f"{cur} {total:,.2f}")
    else:
        st.warning("No data found matching your criteria.")

    if st.button("Run Again", type="primary"):
        for key, default in DEFAULTS.items():
            st.session_state[key] = default
        st.rerun()
