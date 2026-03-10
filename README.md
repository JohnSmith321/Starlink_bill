# Starlink Billing Fetcher

Downloads invoices and exports to Excel. Works on Windows, Ubuntu, and macOS.

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
# Install Chrome (required — script uses your real Chrome, not Playwright's bundled one)
wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" | sudo tee /etc/apt/sources.list.d/google-chrome.list
sudo apt update && sudo apt install -y google-chrome-stable

# Or install Chromium instead:
# sudo apt install -y chromium-browser

# Python setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed as fallback
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

`config.py` auto-detects Chrome by OS. If it doesn't find it, set manually:
```python
CHROME_PATH = "/usr/bin/google-chrome"   # Ubuntu
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"  # Windows
```

---

## Output structure

```
starlink_output/
  starlink_invoices_202602_20260304_151518.xlsx
  starlink_invoices_202602_20260304_151518.zip
  invoices/
    starlink_invoices_202602_20260304_151518/
      202602/
        INV-DF-PHL-xxxx.pdf
```
