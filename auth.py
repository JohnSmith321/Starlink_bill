"""
auth.py — Semi-automatic login with CAPTCHA detection.

Provides modular functions so both CLI (main.py) and Web UI (app.py)
can orchestrate the login flow step-by-step.
"""

import json
import getpass
from rich.console import Console
from rich.prompt import Prompt
from config import (
    LOGIN_URL, SESSION_FILE, OTP_SELECTOR,
    CAPTCHA_SELECTORS, EMAIL_SELECTORS, PASSWORD_SELECTORS, SUBMIT_SELECTORS,
)
from utils import wait_for, wait_for_any

console = Console()


# ─────────────────────────────────────────────
#  Session persistence
# ─────────────────────────────────────────────

def save_session(storage_state: dict):
    """Persist browser cookies so we skip login on next run."""
    SESSION_FILE.write_text(json.dumps(storage_state, indent=2))


def load_session() -> dict | None:
    """Load a previously saved session, or return None if not found."""
    if SESSION_FILE.exists():
        try:
            return json.loads(SESSION_FILE.read_text())
        except Exception:
            pass
    return None


# ─────────────────────────────────────────────
#  Login / page detection
# ─────────────────────────────────────────────

def is_on_login_page(page) -> bool:
    url = page.url.lower()
    return "/auth/login" in url or "sign-in" in url or "login" in url


# ─────────────────────────────────────────────
#  CAPTCHA detection
# ─────────────────────────────────────────────

def detect_captcha(page) -> bool:
    """Return True if a CAPTCHA challenge is visible on the page."""
    for sel in CAPTCHA_SELECTORS:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return True
        except Exception:
            pass
    return False


def wait_for_captcha_solved(page, timeout_s: int = 120):
    """
    Poll every second until the CAPTCHA element disappears (user solved it)
    or timeout is reached. Returns True if solved, False if timed out.
    """
    import time
    for _ in range(timeout_s):
        if not detect_captcha(page):
            return True
        time.sleep(1)
    return False


# ─────────────────────────────────────────────
#  Form helpers
# ─────────────────────────────────────────────

def _find_visible(page, selectors: list[str]):
    """Return the first visible element matching any of the selectors."""
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_visible():
                return el
        except Exception:
            pass
    return None


def fill_email(page, email: str) -> bool:
    el = _find_visible(page, EMAIL_SELECTORS)
    if el:
        el.click()
        el.fill(email)
        return True
    return False


def fill_password(page, password: str) -> bool:
    el = _find_visible(page, PASSWORD_SELECTORS)
    if el:
        el.click()
        el.fill(password)
        return True
    return False


def click_submit(page) -> bool:
    el = _find_visible(page, SUBMIT_SELECTORS)
    if el and el.get_attribute("disabled") is None:
        el.click()
        return True
    return False


def _wait_for_next_step(page, timeout: int = 10000):
    """After a login form submit, wait for the next step to appear:
    password field, OTP field, CAPTCHA, or redirect away from login."""
    combined = ", ".join(PASSWORD_SELECTORS + [OTP_SELECTOR] + CAPTCHA_SELECTORS[:3])
    try:
        page.wait_for_selector(combined, timeout=timeout, state="visible")
    except Exception:
        # Fallback: maybe we already left the login page
        page.wait_for_timeout(1500)


def fill_otp(page, otp_code: str) -> bool:
    """
    Fill OTP into either a single input or multiple single-digit boxes.
    Returns True if filled successfully.
    """
    inputs = page.query_selector_all(OTP_SELECTOR)
    if not inputs:
        return False

    visible = [inp for inp in inputs if inp.is_visible()]
    if not visible:
        return False

    digits = [c for c in otp_code if c.isdigit()]

    if len(visible) == 1:
        visible[0].click()
        visible[0].fill(otp_code.strip())
    else:
        for i, inp in enumerate(visible):
            if i < len(digits):
                inp.click()
                inp.fill(digits[i])
                page.wait_for_timeout(80)

    page.wait_for_timeout(500)
    click_submit(page)
    return True


def detect_otp_page(page) -> bool:
    """Return True if an OTP input field is visible."""
    inputs = page.query_selector_all(OTP_SELECTOR)
    return any(inp.is_visible() for inp in inputs)


# ─────────────────────────────────────────────
#  CLI login flow (used by main.py)
# ─────────────────────────────────────────────

def login_flow(page, _email: str = "", _password: str = ""):
    """
    Semi-automatic CLI login:
      1. Prompt for email + password
      2. Auto-fill email → click submit
      3. Detect CAPTCHA → pause for user to solve in browser
      4. Auto-fill password → click submit
      5. Detect CAPTCHA again
      6. Prompt for OTP → auto-fill
      7. Verify login success
    """
    console.print("")
    console.print("[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]")
    console.print("[bold cyan]  Starlink Semi-Auto Login[/bold cyan]")
    console.print("[bold cyan]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]")
    console.print("")

    email    = _email    or Prompt.ask("  Email")
    password = _password or getpass.getpass("  Password: ")

    # Navigate to login if not already there
    if not is_on_login_page(page):
        from scraper import safe_goto
        safe_goto(page, LOGIN_URL)
        # Wait for email field to appear
        wait_for_any(page, EMAIL_SELECTORS, timeout=10000)

    # ── CAPTCHA check (pre-login) ─────────────────────────────────
    if detect_captcha(page):
        console.print("\n[bold red]  ⚠ CAPTCHA detected![/bold red]")
        console.print("  Please solve the CAPTCHA in the browser window.")
        Prompt.ask("  Press [Enter] after solving")
        page.wait_for_timeout(500)

    # ── Step 1: Email ─────────────────────────────────────────────
    console.print("\n  [bold]Step 1: Email[/bold]")
    if fill_email(page, email):
        console.print("  [dim]✓ Filled email[/dim]")
    else:
        console.print("  [yellow]Could not find email field — please fill manually.[/yellow]")

    page.wait_for_timeout(300)
    click_submit(page)
    # Wait for password field, CAPTCHA, or OTP to appear
    _wait_for_next_step(page, timeout=10000)

    # ── CAPTCHA check (after email) ───────────────────────────────
    if detect_captcha(page):
        console.print("\n[bold red]  ⚠ CAPTCHA detected![/bold red]")
        console.print("  Please solve the CAPTCHA in the browser window.")
        Prompt.ask("  Press [Enter] after solving")
        page.wait_for_timeout(500)

    # ── Step 2: Password ──────────────────────────────────────────
    console.print("\n  [bold]Step 2: Password[/bold]")
    if fill_password(page, password):
        console.print("  [dim]✓ Filled password[/dim]")
    else:
        console.print("  [yellow]Could not find password field — please fill manually.[/yellow]")

    page.wait_for_timeout(300)
    click_submit(page)
    # Wait for OTP page, redirect, or CAPTCHA
    _wait_for_next_step(page, timeout=10000)

    # ── CAPTCHA check (after password) ────────────────────────────
    if detect_captcha(page):
        console.print("\n[bold red]  ⚠ CAPTCHA detected![/bold red]")
        console.print("  Please solve the CAPTCHA in the browser window.")
        Prompt.ask("  Press [Enter] after solving")
        page.wait_for_timeout(500)

    # ── Step 3: OTP ───────────────────────────────────────────────
    console.print("\n  [bold]Step 3: OTP[/bold]")

    import time
    for _ in range(15):
        if detect_otp_page(page):
            break
        if not is_on_login_page(page):
            break
        time.sleep(1)

    if detect_otp_page(page):
        console.print("  [green]✓ OTP page detected.[/green]")
        otp = Prompt.ask("  [bold cyan]Enter OTP[/bold cyan] (check your email)")
        if fill_otp(page, otp):
            console.print("  [dim]✓ Filled OTP[/dim]")
        else:
            console.print("  [yellow]Could not auto-fill OTP — please enter manually in browser.[/yellow]")
            Prompt.ask("  Press [Enter] after entering OTP")
        # Wait for redirect away from login
        for _ in range(15):
            if not is_on_login_page(page):
                break
            time.sleep(1)
    elif is_on_login_page(page):
        console.print("  [yellow]OTP not detected. Please complete login manually.[/yellow]")
        Prompt.ask("  Press [Enter] once you are on the account page")
    else:
        console.print("  [dim]No OTP required — already logged in.[/dim]")

    # ── Verify ────────────────────────────────────────────────────
    if is_on_login_page(page):
        console.print("[yellow]Still on login page — waiting...[/yellow]")
        for _ in range(10):
            if not is_on_login_page(page):
                break
            import time; time.sleep(1)
        if is_on_login_page(page):
            console.print("[red]Still on login page. Please finish login manually.[/red]")
            Prompt.ask("Press [Enter] to continue")

    console.print("[green]✓ Login confirmed![/green]")
