"""
report.py — Account status report.

Scrapes billing page (Balance Due, Billing Cycle) and subscriptions page
(Service Plan, Ocean Mode, Device Status, Serial No, Uptime, Software, Wifi).
"""

import re
from rich.console import Console
from config import BILLING_URL, SUBSCRIPTIONS_URL
from scraper import safe_goto
from utils import wait_for, wait_for_grid

console = Console()


def _get_text_by_labels(page, labels: list[str]) -> str:
    """
    Find a visible text on the page that follows one of the given labels.
    Tries multiple strategies: sibling elements, parent containers, aria-labels.
    """
    for label in labels:
        # Strategy 1: find element containing label text, get next sibling / value
        try:
            els = page.query_selector_all(f'text="{label}"')
            for el in els:
                if not el.is_visible():
                    continue
                # Check sibling or parent for the value
                parent = el.evaluate_handle("el => el.parentElement")
                parent_text = parent.inner_text() if parent else ""
                if parent_text and label in parent_text:
                    # Strip the label from parent text to get the value
                    value = parent_text.replace(label, "").strip().strip(":").strip()
                    if value:
                        return value
        except Exception:
            pass

        # Strategy 2: XPath-based — find text node then next element
        try:
            el = page.query_selector(f'//*[contains(text(), "{label}")]')
            if el and el.is_visible():
                parent = el.evaluate_handle("el => el.parentElement")
                full = parent.inner_text() if parent else el.inner_text()
                value = full.replace(label, "").strip().strip(":").strip()
                if value:
                    return value
        except Exception:
            pass

    return ""


def _get_page_text(page) -> str:
    """Get full visible text from the page body."""
    try:
        return page.inner_text("body") or ""
    except Exception:
        return ""


def _scrape_billing_info(page) -> dict:
    """Scrape Balance Due and Billing Cycle from the billing page."""
    safe_goto(page, BILLING_URL)
    wait_for_grid(page, timeout=15000)

    full_text = _get_page_text(page)

    # Balance Due — look for currency amount near "Balance Due" or "Amount Due"
    balance_due = ""
    for pattern in [
        r"(?:Balance Due|Amount Due|Current Balance)[:\s]*([₱$][\d,]+\.?\d*)",
        r"(?:Balance Due|Amount Due|Current Balance)[:\s]*([\d,]+\.?\d*\s*(?:PHP|USD))",
    ]:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            balance_due = m.group(1).strip()
            break

    if not balance_due:
        balance_due = _get_text_by_labels(page, ["Balance Due", "Amount Due", "Current Balance"])

    # Billing Cycle — look for date range pattern
    billing_cycle = ""
    for pattern in [
        r"(?:Billing Cycle|Billing Period|Service Period)[:\s]*(.+?)(?:\n|$)",
        r"(\w+ \d{1,2},?\s*\d{4}\s*[-–—to]+\s*\w+ \d{1,2},?\s*\d{4})",
    ]:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            billing_cycle = m.group(1).strip()
            break

    if not billing_cycle:
        billing_cycle = _get_text_by_labels(page, ["Billing Cycle", "Billing Period", "Service Period"])

    console.print(f"  [dim]Balance Due: {balance_due or '(not found)'}[/dim]")
    console.print(f"  [dim]Billing Cycle: {billing_cycle or '(not found)'}[/dim]")

    return {
        "balance_due": balance_due,
        "billing_cycle": billing_cycle,
    }


def _scrape_subscription_info(page) -> dict:
    """Scrape subscription and device status from the subscriptions page."""
    safe_goto(page, SUBSCRIPTIONS_URL)
    # Wait for page content to load
    wait_for(page, 'main, [class*="subscription"], [class*="Subscription"]', timeout=15000)

    full_text = _get_page_text(page)

    # Subscription Status — often a warning/info banner
    sub_status = ""
    # Look for restriction/warning messages
    for pattern in [
        r"(Your Starlink.+?(?:\.|\n))",
        r"(No active service.+?(?:\.|\n))",
        r"(Service is (?:restricted|suspended|paused).+?(?:\.|\n))",
    ]:
        m = re.search(pattern, full_text, re.IGNORECASE)
        if m:
            sub_status = m.group(1).strip()
            break

    if not sub_status:
        sub_status = _get_text_by_labels(page, ["Subscription Status", "Service Status"])
        if not sub_status:
            # Check for alert/warning banners
            for sel in ['[class*="alert"]', '[class*="warning"]', '[class*="banner"]', '[role="alert"]']:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    sub_status = (el.inner_text() or "").strip()[:200]
                    if sub_status:
                        break

    # Service Plan Status — Active/Inactive
    plan_status = ""
    if re.search(r"\bActive\b", full_text):
        plan_status = "Active"
    elif re.search(r"\bInactive\b", full_text):
        plan_status = "Inactive"
    elif re.search(r"\bPaused\b", full_text, re.IGNORECASE):
        plan_status = "Paused"
    if not plan_status:
        plan_status = _get_text_by_labels(page, ["Service Plan", "Plan Status"])

    # Ocean Mode — On/Off
    ocean_mode = ""
    m = re.search(r"Ocean\s*Mode[:\s]*(On|Off|Enabled|Disabled)", full_text, re.IGNORECASE)
    if m:
        val = m.group(1).strip().lower()
        ocean_mode = "On" if val in ("on", "enabled") else "Off"
    if not ocean_mode:
        ocean_mode = _get_text_by_labels(page, ["Ocean Mode"])
        if ocean_mode.lower() in ("on", "enabled"):
            ocean_mode = "On"
        elif ocean_mode.lower() in ("off", "disabled"):
            ocean_mode = "Off"

    # Device Status — check for color indicators
    device_status = ""
    # Look for device status indicators (colored dots or text)
    for sel in ['[class*="device-status"]', '[class*="DeviceStatus"]', '[class*="status-indicator"]']:
        el = page.query_selector(sel)
        if el and el.is_visible():
            text = (el.inner_text() or "").strip()
            # Check color via computed style
            try:
                color = el.evaluate("el => getComputedStyle(el).color")
                if "255, 0, 0" in color or "red" in color.lower():
                    device_status = "No Internet"
                elif "128, 128, 128" in color or "gray" in color.lower() or "grey" in color.lower():
                    device_status = "Disconnected"
                elif "0, 128, 0" in color or "green" in color.lower():
                    device_status = "Online"
            except Exception:
                pass
            if not device_status and text:
                device_status = text
            if device_status:
                break

    if not device_status:
        # Fallback: look for Online/Offline/No Internet text
        if re.search(r"\bNo Internet\b", full_text, re.IGNORECASE):
            device_status = "No Internet"
        elif re.search(r"\bOffline\b", full_text, re.IGNORECASE):
            device_status = "Offline"
        elif re.search(r"\bOnline\b", full_text, re.IGNORECASE):
            device_status = "Online"
        elif re.search(r"\bDisconnected\b", full_text, re.IGNORECASE):
            device_status = "Disconnected"

    # Serial Number
    serial_no = ""
    m = re.search(r"(?:Serial\s*(?:No|Number|#)?)[:\s]*([A-Z0-9]{6,})", full_text, re.IGNORECASE)
    if m:
        serial_no = m.group(1).strip()
    if not serial_no:
        serial_no = _get_text_by_labels(page, ["Serial Number", "Serial No", "Serial #"])

    # Uptime
    uptime = ""
    m = re.search(r"(?:Uptime|Up Time)[:\s]*(.+?)(?:\n|$)", full_text, re.IGNORECASE)
    if m:
        uptime = m.group(1).strip()
    if not uptime:
        uptime = _get_text_by_labels(page, ["Uptime", "Up Time"])

    # Software Version
    sw_version = ""
    m = re.search(r"(?:Software\s*(?:Version)?|Firmware)[:\s]*([a-f0-9.\-]+)", full_text, re.IGNORECASE)
    if m:
        sw_version = m.group(1).strip()
    if not sw_version:
        sw_version = _get_text_by_labels(page, ["Software Version", "Firmware", "Software"])

    # Wifi Status
    wifi_status = ""
    m = re.search(r"Wi-?Fi\s*(?:Status)?[:\s]*(On|Off|Connected|Disconnected)", full_text, re.IGNORECASE)
    if m:
        val = m.group(1).strip().lower()
        wifi_status = "On" if val in ("on", "connected") else "Off"
    if not wifi_status:
        wifi_status = _get_text_by_labels(page, ["Wifi Status", "WiFi", "Wi-Fi"])
        # Also check for "No active service" banner
        if not wifi_status and re.search(r"No active service", full_text, re.IGNORECASE):
            wifi_status = "No active service"

    console.print(f"  [dim]Plan: {plan_status or '?'} | Ocean: {ocean_mode or '?'} | Device: {device_status or '?'}[/dim]")
    console.print(f"  [dim]Serial: {serial_no or '?'} | SW: {sw_version or '?'} | Wifi: {wifi_status or '?'}[/dim]")

    return {
        "subscription_status": sub_status,
        "service_plan_status": plan_status,
        "ocean_mode":          ocean_mode,
        "device_status":       device_status,
        "serial_no":           serial_no,
        "uptime":              uptime,
        "software_version":    sw_version,
        "wifi_status":         wifi_status,
    }


def collect_account_report(page, acc_name: str, acc_id: str) -> dict:
    """Collect full status report for a single account."""
    console.print(f"  [dim]Scraping billing info...[/dim]")
    billing = _scrape_billing_info(page)

    console.print(f"  [dim]Scraping subscription info...[/dim]")
    subs = _scrape_subscription_info(page)

    return {
        "account":             acc_name,
        "account_id":          acc_id,
        "balance_due":         billing["balance_due"],
        "billing_cycle":       billing["billing_cycle"],
        "subscription_status": subs["subscription_status"],
        "service_plan_status": subs["service_plan_status"],
        "ocean_mode":          subs["ocean_mode"],
        "device_status":       subs["device_status"],
        "serial_no":           subs["serial_no"],
        "uptime":              subs["uptime"],
        "software_version":    subs["software_version"],
        "wifi_status":         subs["wifi_status"],
    }
