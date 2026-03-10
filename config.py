import calendar
from pathlib import Path

import sys as _sys


def _long_path(p: Path) -> Path:
    """
    On Windows, prepend \\\\?\\ to absolute paths to bypass the 260-char limit.
    No-op on Linux/macOS.
    """
    if _sys.platform != "win32":
        return p
    p = p.resolve()
    s = str(p)
    if not s.startswith("\\\\?\\"):
        return Path("\\\\?\\" + s)
    return p


STARLINK_BASE       = "https://www.starlink.com"
BILLING_URL         = f"{STARLINK_BASE}/account/billing"
SUBSCRIPTIONS_URL   = f"{STARLINK_BASE}/account/subscriptions"
LOGIN_URL           = "https://starlink.com/auth/login"

OUTPUT_DIR   = _long_path(Path("starlink_output"))
INVOICES_DIR = OUTPUT_DIR / "invoices"
EXCEL_FILE   = OUTPUT_DIR / "starlink_invoices.xlsx"
ZIP_FILE     = OUTPUT_DIR / "starlink_invoices.zip"
SESSION_FILE = OUTPUT_DIR / ".session.json"

EXCEL_HEADERS = [
    "Customer Account",
    "Invoice Number",
    "Invoice Date",
    "Payment Completed Date",
    "Amount Paid",
    "Currency",
    "Product",
    "PDF File",
]

REPORT_HEADERS = [
    "Account",
    "Account ID",
    "Balance Due",
    "Billing Cycle",
    "Subscription Status",
    "Service Plan Status",
    "Ocean Mode",
    "Device Status",
    "Serial No",
    "Uptime",
    "Software Version",
    "Wifi Status",
]

MONTH_NAMES = {i: calendar.month_name[i] for i in range(1, 13)}

# ─────────────────────────────────────────────
#  Browser config
# ─────────────────────────────────────────────
# Auto-detects Chrome path by OS. Override by setting CHROME_PATH manually.
# e.g. CHROME_PATH = "/usr/bin/google-chrome"

import os as _os

def _detect_chrome() -> str | None:
    if _sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            _os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    elif _sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    else:  # Linux / Ubuntu
        candidates = [
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium-browser",
            "/usr/bin/chromium",
            "/snap/bin/chromium",
        ]
    for path in candidates:
        if _os.path.exists(path):
            return path
    return None

CHROME_PATH = _detect_chrome()

OTP_SELECTOR = (
    'input[inputmode="numeric"], '
    'input[autocomplete="one-time-code"], '
    'input[type="number"][maxlength="1"], '
    'input[name*="otp" i], input[name*="code" i], '
    'input[placeholder*="code" i]'
)

# ─────────────────────────────────────────────
#  CAPTCHA detection selectors
# ─────────────────────────────────────────────
CAPTCHA_SELECTORS = [
    'iframe[src*="challenges.cloudflare.com"]',
    '[class*="cf-turnstile"]',
    '#cf-challenge-running',
    '.cf-browser-verification',
    'iframe[src*="hcaptcha.com"]',
    '[class*="h-captcha"]',
    'iframe[src*="recaptcha"]',
    '[class*="g-recaptcha"]',
    '[data-testid*="captcha"]',
]

# ─────────────────────────────────────────────
#  Login form selectors
# ─────────────────────────────────────────────
EMAIL_SELECTORS = [
    'input[type="email"]',
    'input[name="email"]',
    'input[autocomplete="email"]',
    'input[placeholder*="email" i]',
]

PASSWORD_SELECTORS = [
    'input[type="password"]',
    'input[name="password"]',
    'input[autocomplete="current-password"]',
]

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button:has-text("Next")',
    'button:has-text("Continue")',
    'button:has-text("Sign In")',
    'button:has-text("Log In")',
    '[data-testid*="submit"]',
]
