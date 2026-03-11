import time
from pathlib import Path
from rich.console import Console
from playwright.sync_api import TimeoutError as PWTimeout
from config import INVOICES_DIR

console = Console()


def download_invoice_pdf(page, invoice_number: str, account_id: str,
                         row_el=None, pdf_dir: Path = None) -> Path | None:
    """
    Download the PDF by clicking the appliedInvoices cell in the payment table row.
    Saves into pdf_dir using the browser's suggested filename (as downloaded).
    """
    if pdf_dir is None:
        pdf_dir = INVOICES_DIR
    pdf_dir.mkdir(parents=True, exist_ok=True)

    if row_el is None:
        console.print(f"  [yellow]No row element for {invoice_number}[/yellow]")
        return None

    # Find the clickable cell — appliedInvoices is the download trigger
    click_target = (
        row_el.query_selector('.MuiDataGrid-cell[data-field="appliedInvoices"]') or
        row_el.query_selector('.MuiDataGrid-cell[data-field="download"]') or
        row_el.query_selector('.MuiDataGrid-cell[data-field="invoiceNumber"]')
    )

    if click_target is None:
        console.print(f"  [yellow]No download cell found for {invoice_number}[/yellow]")
        return None

    # Strategy 1: direct browser download — retry up to 3 times on 429
    for attempt in range(3):
        try:
            with page.expect_download(timeout=20000) as dl_info:
                click_target.click()
            dl       = dl_info.value
            filename = dl.suggested_filename or f"{invoice_number}.pdf"
            pdf_path = pdf_dir / filename

            if pdf_path.exists():
                console.print(f"  [dim]Already exists: {filename}[/dim]")
                dl.cancel()
                return pdf_path

            dl.save_as(str(pdf_path))

            # Check if what was saved is actually an error page (e.g. 429 HTML)
            content = pdf_path.read_bytes()
            if content[:4] != b"%PDF" and b"429" in content[:500]:
                pdf_path.unlink(missing_ok=True)
                wait = 20 * (attempt + 1)
                console.print(f"  [yellow]429 rate limit on attempt {attempt+1} — waiting {wait}s...[/yellow]")
                time.sleep(wait)
                continue

            console.print(f"  [green]✓ Downloaded: {filename}[/green]")
            # Polite delay between downloads to avoid rate limiting
            time.sleep(5)
            return pdf_path

        except PWTimeout:
            break

    # Strategy 2: new tab opened with PDF — also with retry
    for attempt in range(3):
        try:
            with page.context.expect_page(timeout=8000) as new_page_info:
                click_target.click()
            new_tab = new_page_info.value
            new_tab.wait_for_load_state()
            url = new_tab.url
            if url and url != "about:blank":
                url_name = url.split("/")[-1].split("?")[0]
                filename = url_name if url_name.endswith(".pdf") else f"{invoice_number}.pdf"
                pdf_path = pdf_dir / filename
                response = page.request.get(url)
                if response.status == 429:
                    new_tab.close()
                    wait = 20 * (attempt + 1)
                    console.print(f"  [yellow]429 rate limit (tab) attempt {attempt+1} — waiting {wait}s...[/yellow]")
                    time.sleep(wait)
                    continue
                pdf_path.write_bytes(response.body())
                new_tab.close()
                console.print(f"  [green]✓ Downloaded via tab: {filename}[/green]")
                time.sleep(5)
                return pdf_path
            new_tab.close()
            break
        except Exception:
            break

    console.print(f"  [yellow]Could not download PDF for {invoice_number}[/yellow]")
    return None
