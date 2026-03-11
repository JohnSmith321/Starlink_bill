# Starlink Billing Fetcher

Automatically fetches Starlink invoices across multiple accounts, downloads PDFs, and exports everything to a formatted Excel workbook. Also generates account status reports (billing + subscription info). Runs as a CLI tool or a Streamlit web UI.

---

## How it works

1. **Launches your real Chrome** via CDP (Chrome DevTools Protocol) to avoid bot detection. Falls back to Playwright Chromium if Chrome is not found.
2. **Semi-auto login** — auto-fills your email and password into the Starlink login form. If a CAPTCHA (Cloudflare Turnstile, hCaptcha, reCAPTCHA) is detected, it pauses and waits for you to solve it in the browser. Then prompts you for the OTP sent to your email and auto-fills it.
3. **Discovers all accounts** by opening the avatar menu and scrolling through the account switcher (supports multi-account setups with 40+ sub-accounts).
4. **Scrapes the billing page** — reads both the invoice table (Grid 0) and the payment table (Grid 1) from the MUI DataGrid, handling pagination automatically. Uses proper element waits (wait-for-selector) instead of fixed timeouts for reliability.
5. **Downloads each invoice PDF** by clicking the invoice link in the table row. Retries on HTTP 429 rate limits with exponential backoff. Uses two strategies: direct browser download, then new-tab fallback.
6. **Parses each PDF** with pdfplumber to extract: customer account, invoice number, invoice date, total amount, currency, and product description.
7. **Exports to Excel** — a formatted `.xlsx` with styled headers, alternating row colors, and a summary sheet with totals by currency. Also zips all PDFs into a single archive.
8. **Saves the browser session** so subsequent runs can skip login (Playwright Chromium only).

---

## Features

| Feature | Details |
|---|---|
| Semi-auto login | Auto-fills email + password, pauses for CAPTCHA, prompts for OTP |
| CAPTCHA detection | Cloudflare Turnstile, hCaptcha, reCAPTCHA |
| Multi-account | Auto-discovers and processes all sub-accounts |
| Single account targeting | Process only one specified account (by ACC-ID) |
| Date range filter | Single-month mode: day 5 of selected month → day 6 of next month |
| PDF download | Per-row download with 429 retry + backoff |
| PDF parsing | Extracts structured data from invoice PDFs |
| Excel export | Formatted workbook + summary sheet |
| ZIP archive | All PDFs bundled into one download |
| Status report | Scrapes billing + subscription pages (balance, plan, device, wifi) |
| Session reuse | Skip login on subsequent runs |
| Smart waits | Uses wait-for-selector instead of fixed timeouts |
| Web UI | Streamlit app — no terminal needed |
| Docker | Run without installing Python |
| Windows long paths | `\\?\` prefix to bypass 260-char path limit |

---

## Run modes

### CLI (terminal)
```bash
python main.py
```
Choose between:
- **Fetch invoices** — download PDFs + export Excel
- **Status report** — scrape billing + subscription info per account

### Web UI (browser)
```bash
streamlit run app.py
```
Open `http://localhost:8501` in your browser. Enter credentials, choose mode (fetch or report), optionally target a single account, solve CAPTCHA if prompted, submit OTP, and download results — all from the web interface.

### Docker (no Python required)
```bash
docker-compose up --build
```
Open `http://localhost:8501`. Docker runs headless — falls back to Playwright Chromium (may trigger bot detection). Best for servers or users who can't install Python.

---

## Setup

### Windows
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium

# CLI mode
python main.py

# Web UI mode
streamlit run app.py
```

### Ubuntu / Debian
```bash
# Install Chrome (recommended — avoids bot detection)
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable

# Python setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# CLI mode
python main.py

# Web UI mode
streamlit run app.py
```

### macOS
```bash
# Install Chrome from https://www.google.com/chrome/ first, then:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# CLI mode
python main.py

# Web UI mode
streamlit run app.py
```

---

## Chrome path

`config.py` auto-detects Chrome by OS. If detection fails, set it manually:
```python
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"  # Windows
CHROME_PATH = "/usr/bin/google-chrome"   # Ubuntu
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"  # macOS
```

---

## Date filtering

When using **Single month** mode, invoices are filtered by **Payment Completed Date**:
- **Start**: day 5 of the selected month
- **End**: day 6 of the following month (inclusive)

Example: selecting January 2026 fetches payments from **2026-01-05** to **2026-02-06**.

---

## Status report

The report mode scrapes two pages per account:

**From billing page** (`/account/billing`):
- Balance Due
- Billing Cycle

**From subscriptions page** (`/account/subscriptions`):
- Subscription Status (restriction warnings, service messages)
- Service Plan Status (Active / Inactive / Paused)
- Ocean Mode (On / Off)
- Starlink Device Status (Online / No Internet / Disconnected)
- Starlink Serial No
- Starlink Uptime
- Software Version
- Wifi Status (On / Off)

Output: formatted Excel workbook with one row per account.

---

## Project structure

```
starlink_fetcher/
  main.py           — CLI entry point (fetch + report modes)
  app.py            — Streamlit web UI
  config.py         — URLs, paths, selectors, Chrome detection
  auth.py           — Semi-auto login, CAPTCHA detect, OTP fill, session
  scraper.py        — Account discovery, MUI DataGrid scraping
  downloader.py     — PDF download with retry
  pdf_parser.py     — Invoice PDF data extraction
  excel_export.py   — Excel builder (invoices + report) + PDF zipper
  report.py         — Account status report scraper
  utils.py          — Currency/date parsers, wait helpers, shared logic
  requirements.txt  — Python dependencies
  Dockerfile        — Docker image
  docker-compose.yml
```

## Output structure

```
starlink_output/
  starlink_invoices_202601_20260310_153000.xlsx    # invoice export
  starlink_invoices_202601_20260310_153000.zip     # PDF archive
  starlink_report_all_20260310_160000.xlsx         # status report
  invoices/
    202601_20260310_153000/
      202601/
        INV-DF-PHL-xxxx.pdf
        INV-DF-PHL-yyyy.pdf
```

---

## Dependencies

- **playwright** — browser automation
- **pdfplumber** — PDF text extraction
- **openpyxl** — Excel writing
- **rich** — CLI formatting and prompts
- **streamlit** — web UI
- **pandas** — data display in web UI

---

## Changelog

### 2026-03-11
- **`auth.py`** — Moved `import time` to module top level (was inline inside functions). Tightened `is_on_login_page` to only match `/auth/login` and `/sign-in`, preventing false positives on any URL containing the word "login".
- **`config.py`** — `OUTPUT_DIR` now resolves relative to the script file (`__file__`) rather than the current working directory, so the output folder is always predictable regardless of where the script is launched from.
- **`utils.py`** — Fixed `parse_currency` regex to strip the full `PHP`/`USD` prefix string rather than individual characters, avoiding accidental stripping of letters from numeric values. Added `ValueError` guard on float conversion.
- **`main.py`** — Fixed `_dl` closure capturing loop variable by binding `acc_id` and `pdf_dir` as default arguments. Moved `pdf_dir` definition inside the invoice-fetch branch (not created in report mode).
- **`app.py`** — Removed unused imports (`os`, `subprocess`, `tempfile`). Fixed `_dl` closure (same as `main.py`). Added `cleanup_browser()` call in the fetch error handler to prevent orphaned browser processes on exception.
- **`.dockerignore`** — Expanded to exclude `venv/`, `__pycache__/`, `.git/`, `starlink_output/`, `*.zip`, and `.session.json`, keeping the Docker build context lean.
