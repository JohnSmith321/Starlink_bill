# Starlink Billing Fetcher

Automatically fetches Starlink invoices across multiple accounts, downloads PDFs, and exports everything to a formatted Excel workbook. Runs as a CLI tool or a Streamlit web UI.

---

## How it works

1. **Launches your real Chrome** via CDP (Chrome DevTools Protocol) to avoid bot detection. Falls back to Playwright Chromium if Chrome is not found.
2. **Semi-auto login** — auto-fills your email and password into the Starlink login form. If a CAPTCHA (Cloudflare Turnstile, hCaptcha, reCAPTCHA) is detected, it pauses and waits for you to solve it in the browser. Then prompts you for the OTP sent to your email and auto-fills it.
3. **Discovers all accounts** by opening the avatar menu and scrolling through the account switcher (supports multi-account setups with 40+ sub-accounts).
4. **Scrapes the billing page** — reads both the invoice table (Grid 0) and the payment table (Grid 1) from the MUI DataGrid, handling pagination automatically.
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
| PDF download | Per-row download with 429 retry + backoff |
| PDF parsing | Extracts structured data from invoice PDFs |
| Excel export | Formatted workbook + summary sheet |
| ZIP archive | All PDFs bundled into one download |
| Session reuse | Skip login on subsequent runs |
| Web UI | Streamlit app — no terminal needed |
| Docker | Run without installing Python |
| Windows long paths | `\\?\` prefix to bypass 260-char path limit |

---

## Run modes

### CLI (terminal)
```bash
python main.py
```

### Web UI (browser)
```bash
streamlit run app.py
```
Open `http://localhost:8501` in your browser. Enter credentials, solve CAPTCHA if prompted, submit OTP, and download results — all from the web interface.

### Docker (no Python required)
```bash
docker-compose up --build
```
Open `http://localhost:8501`.

---

## Setup

### Windows
```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python main.py
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
python main.py
```

### macOS
```bash
# Install Chrome from https://www.google.com/chrome/ first, then:
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python main.py
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

## Project structure

```
starlink_fetcher/
  main.py           — CLI entry point
  app.py            — Streamlit web UI
  config.py         — URLs, paths, selectors, Chrome detection
  auth.py           — Semi-auto login, CAPTCHA detect, OTP fill, session
  scraper.py        — Account discovery, MUI DataGrid scraping
  downloader.py     — PDF download with retry
  pdf_parser.py     — Invoice PDF data extraction
  excel_export.py   — Excel builder + PDF zipper
  utils.py          — Currency/date parsers, shared helpers
  requirements.txt  — Python dependencies
  Dockerfile        — Docker image
  docker-compose.yml
```

## Output structure

```
starlink_output/
  starlink_invoices_202602_20260310_153000.xlsx
  starlink_invoices_202602_20260310_153000.zip
  invoices/
    202602_20260310_153000/
      202602/
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
