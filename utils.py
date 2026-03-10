import re
from datetime import datetime, date
from rich.console import Console
from rich.prompt import Prompt, IntPrompt
from config import OUTPUT_DIR, INVOICES_DIR, MONTH_NAMES

console = Console()


def ensure_dirs():
    OUTPUT_DIR.mkdir(exist_ok=True)
    INVOICES_DIR.mkdir(exist_ok=True)


def parse_currency(amount_str: str) -> tuple[float, str]:
    """Return (amount_float, currency_code) from a string like '₱4,370.22'."""
    amount_str = amount_str.strip()
    if amount_str.startswith("₱") or amount_str.upper().startswith("PHP"):
        cleaned = re.sub(r"[₱PHPphp,\s]", "", amount_str)
        return float(cleaned), "PHP"
    if amount_str.startswith("$") or amount_str.upper().startswith("USD"):
        cleaned = re.sub(r"[$USDusd,\s]", "", amount_str)
        return float(cleaned), "USD"
    # Generic fallback
    letters  = re.sub(r"[^A-Za-z]", "", amount_str).upper()
    numbers  = re.sub(r"[^0-9.\-]", "", amount_str)
    currency = letters if letters else "UNKNOWN"
    try:
        return float(numbers), currency
    except ValueError:
        return 0.0, currency


def parse_row_date(date_str: str) -> date | None:
    """Try multiple date formats and return a date object, or None."""
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y",
                "%A, %B %d, %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def fmt_date(d) -> str:
    """Format a date or date string consistently as YYYY-MM-DD."""
    if not d:
        return ""
    if isinstance(d, str):
        parsed = parse_row_date(d)
        return parsed.strftime("%Y-%m-%d") if parsed else d
    try:
        return d.strftime("%Y-%m-%d")
    except Exception:
        return str(d)


def build_record(row: dict, pdf_path, acc_id: str) -> dict:
    """
    Merge scraped billing row data with extracted PDF data.
    PDF data takes priority; scraped data is the fallback.
    Shared by both CLI (main.py) and Web UI (app.py).
    """
    from pdf_parser import extract_pdf_data

    if pdf_path and pdf_path.exists():
        pdf = extract_pdf_data(pdf_path)
        return {
            "customer_account": pdf["customer_account"] or acc_id,
            "invoice_number":   pdf["invoice_number"]   or row["invoice_number"],
            "invoice_date":     fmt_date(pdf["invoice_date"] or row.get("invoice_date") or row["date"]),
            "payment_date":     fmt_date(row["date"]),
            "amount":           pdf["amount"]            or parse_currency(row["amount_str"])[0],
            "currency":         pdf["currency"]          or parse_currency(row["amount_str"])[1],
            "product":          pdf["product"],
            "pdf_file":         pdf_path.name,
        }
    else:
        amt, cur = parse_currency(row["amount_str"])
        return {
            "customer_account": acc_id,
            "invoice_number":   row["invoice_number"],
            "invoice_date":     fmt_date(row.get("invoice_date") or row["date"]),
            "payment_date":     fmt_date(row["date"]),
            "amount":           amt,
            "currency":         cur,
            "product":          "",
            "pdf_file":         "(not downloaded)",
        }


def ask_month_filter() -> date | None:
    """
    Prompt the user to choose between full history or a single month.
    Returns date(year, month, 1) for single month, or None for full history.
    """
    console.print("\n[bold]Fetch mode:[/bold]")
    console.print("  [cyan]1[/cyan] - All invoices  (scrolls back to your very first payment)")
    console.print("  [cyan]2[/cyan] - Single month  (you provide month + year)")

    choice = Prompt.ask("Select", choices=["1", "2"], default="1")
    if choice == "1":
        return None

    now = datetime.now()
    while True:
        year  = IntPrompt.ask("  Year  (e.g. 2025)", default=now.year)
        month = IntPrompt.ask("  Month (1-12)",       default=now.month)
        if 1 <= month <= 12 and year >= 2019:
            break
        console.print("[red]  Invalid year or month, please try again.[/red]")

    console.print(f"  [green]→ Fetching: {MONTH_NAMES[month]} {year}[/green]")
    return date(year, month, 1)
