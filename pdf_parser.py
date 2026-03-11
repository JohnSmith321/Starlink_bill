import re
import pdfplumber
from pathlib import Path
from datetime import datetime
from rich.console import Console
from utils import parse_currency

console = Console()


def extract_pdf_data(pdf_path: Path) -> dict:
    """
    Parse a Starlink invoice PDF and return a dict with:
        customer_account, invoice_number, invoice_date,
        amount (float), currency (str), product (str)

    All fields default to empty string / 0.0 if not found.
    """
    data = {
        "customer_account": "",
        "invoice_number":   "",
        "invoice_date":     "",
        "amount":           0.0,
        "currency":         "",
        "product":          "",
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

        # Customer Account — e.g. ACC-8451203-98745-21
        m = re.search(r"Customer Account[:\s]+([A-Z0-9\-]+)", text)
        if m:
            data["customer_account"] = m.group(1).strip()

        # Invoice Number — e.g. INV-DF-PHL-2597761-52558-21
        m = re.search(r"(INV-[A-Z0-9\-]+)", text)
        if m:
            data["invoice_number"] = m.group(1).strip()

        # Invoice Date — e.g. "Friday, February 6, 2026"
        m = re.search(r"Invoice Date[:\s]+([A-Za-z]+,\s+[A-Za-z]+ \d+,\s+\d{4})", text)
        if m:
            raw = m.group(1).strip()
            try:
                data["invoice_date"] = datetime.strptime(raw, "%A, %B %d, %Y").strftime("%Y-%m-%d")
            except ValueError:
                data["invoice_date"] = raw

        # Total Charges — e.g. "Total Charges PHP 4,370.22"
        m = re.search(r"Total Charges\s+(?:PHP|₱|USD|\$)?\s*([\d,]+\.?\d*)", text)
        if m:
            amount_str = m.group(0).replace("Total Charges", "").strip()
            data["amount"], data["currency"] = parse_currency(amount_str)

        # Product description — e.g. "Roam - Unlimited (...)"
        m = re.search(r"(Roam\s*-\s*[^\n]+|Residential[^\n]+|Priority[^\n]+)", text)
        if m:
            data["product"] = m.group(1).strip()[:80]

    except Exception as e:
        console.print(f"[yellow]  PDF parse warning for {pdf_path.name}: {e}[/yellow]")

    return data
