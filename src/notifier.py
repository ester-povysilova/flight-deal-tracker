"""HTML email notifier sending deal digests via Gmail SMTP."""

from __future__ import annotations

import os
import smtplib
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Tuple

from src.config import DEFAULT_EUR_TO_CZK
from src.models import FlightOffer, ScoringResult


def generate_deal_html_card(offer: FlightOffer, score: ScoringResult) -> str:
    """Render an individual deal card for the HTML digest."""
    # Price formatting: include EUR if origin is DUB or original currency is EUR
    if offer.origin == "DUB" or offer.original_currency == "EUR":
        eur_price = offer.original_price or round(offer.price_czk / DEFAULT_EUR_TO_CZK, 0)
        price_display = f"{offer.price_czk:,.0f} CZK <span style='font-size: 14px; font-weight: normal; color: #5f6368;'>(&euro;{eur_price:,.0f})</span>"
        baseline_eur = round(score.baseline_avg / DEFAULT_EUR_TO_CZK, 0)
        baseline_display = f"{score.baseline_avg:,.0f} CZK (&euro;{baseline_eur:,.0f})"
    else:
        price_display = f"{offer.price_czk:,.0f} CZK"
        baseline_display = f"{score.baseline_avg:,.0f} CZK"

    # Cabin badge color
    cabin_bg = "#e8f0fe"
    cabin_color = "#1a73e8"
    if offer.cabin_class.value == "BUSINESS":
        cabin_bg = "#fce8e6"
        cabin_color = "#c5221f"
    elif offer.cabin_class.value == "PREMIUM_ECONOMY":
        cabin_bg = "#fef7e0"
        cabin_color = "#b06000"

    # Stop description
    out_stops = offer.outbound_leg.stops
    ret_stops = offer.return_leg.stops
    stops_text = "Nonstop" if (out_stops == 0 and ret_stops == 0) else f"Out: {out_stops} stop, Ret: {ret_stops} stop"

    # Format flight segments
    out_segs_html = "<br>".join([f"&bull; {seg.summary}" for seg in offer.outbound_leg.segments])
    ret_segs_html = "<br>".join([f"&bull; {seg.summary}" for seg in offer.return_leg.segments])

    # Booking links
    gf_link = offer.google_flights_url or "#"
    sky_link = offer.skyscanner_url or "#"

    return f"""
    <div style="background-color: #ffffff; border: 1px solid #dadce0; border-radius: 8px; margin-bottom: 24px; padding: 20px; box-shadow: 0 1px 3px rgba(60,64,67,0.08);">
      <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px; border-bottom: 1px solid #f1f3f4; padding-bottom: 12px;">
        <div>
          <span style="font-size: 20px; font-weight: bold; color: #202124;">{offer.origin} &rarr; {offer.destination}</span>
          <span style="display: inline-block; background-color: {cabin_bg}; color: {cabin_color}; font-size: 11px; font-weight: bold; padding: 3px 8px; border-radius: 12px; margin-left: 8px; vertical-align: middle;">
            {offer.cabin_class.value.replace('_', ' ')}
          </span>
          <div style="color: #5f6368; font-size: 13px; margin-top: 4px;">
            {offer.departure_date.strftime('%d %b %Y')} &ndash; {offer.return_date.strftime('%d %b %Y')} ({offer.stay_nights} nights) &bull; {stops_text}
          </div>
        </div>
        <div style="text-align: right;">
          <div style="background-color: #e6f4ea; color: #137333; font-weight: bold; font-size: 16px; padding: 6px 12px; border-radius: 6px; display: inline-block;">
            Score: {score.total_score:.1f}/100
          </div>
        </div>
      </div>

      <div style="display: flex; margin-bottom: 16px; background-color: #f8f9fa; padding: 12px; border-radius: 6px;">
        <div style="flex: 1;">
          <div style="font-size: 11px; color: #5f6368; text-transform: uppercase; font-weight: bold;">Deal Price</div>
          <div style="font-size: 20px; font-weight: bold; color: #188038;">{price_display}</div>
        </div>
        <div style="flex: 1;">
          <div style="font-size: 11px; color: #5f6368; text-transform: uppercase; font-weight: bold;">Baseline Average</div>
          <div style="font-size: 16px; color: #5f6368; text-decoration: line-through; margin-top: 3px;">{baseline_display}</div>
        </div>
        <div style="flex: 1;">
          <div style="font-size: 11px; color: #5f6368; text-transform: uppercase; font-weight: bold;">Total Savings</div>
          <div style="font-size: 16px; font-weight: bold; color: #d93025; margin-top: 3px;">
            Save {score.savings_percent:.0f}% ({score.savings_czk:,.0f} CZK)
          </div>
        </div>
      </div>

      <div style="font-size: 13px; color: #3c4043; line-height: 1.6; margin-bottom: 16px;">
        <div style="font-weight: bold; color: #202124; margin-bottom: 4px;">Itinerary Details:</div>
        <div style="margin-left: 8px;">
          <strong>Outbound:</strong><br>{out_segs_html}
        </div>
        <div style="margin-top: 8px; margin-left: 8px;">
          <strong>Return:</strong><br>{ret_segs_html}
        </div>
      </div>

      <div style="display: flex; gap: 12px; margin-top: 16px; pt-2;">
        <a href="{gf_link}" target="_blank" style="background-color: #1a73e8; color: #ffffff; text-decoration: none; padding: 8px 16px; border-radius: 4px; font-size: 13px; font-weight: bold; display: inline-block;">
          Search Google Flights &rarr;
        </a>
        <a href="{sky_link}" target="_blank" style="background-color: #0770e3; color: #ffffff; text-decoration: none; padding: 8px 16px; border-radius: 4px; font-size: 13px; font-weight: bold; display: inline-block; margin-left: 10px;">
          Search Skyscanner &rarr;
        </a>
      </div>
    </div>
    """


def generate_digest_html(deals: List[Tuple[FlightOffer, ScoringResult]], scan_date: date) -> str:
    """Generate complete HTML email body containing all qualifying deals."""
    date_str = scan_date.strftime("%d %b %Y")
    deal_cards = "\n".join([generate_deal_html_card(offer, score) for offer, score in deals])

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Flight Deals Tracker - {date_str}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f3f4; margin: 0; padding: 24px; color: #202124;">
  <div style="max-width: 680px; margin: 0 auto;">
    <div style="background-color: #1a73e8; color: #ffffff; padding: 24px; border-radius: 8px 8px 0 0; text-align: left;">
      <h1 style="margin: 0; font-size: 22px; font-weight: bold;">✈️ Automated Flight Deal Alert</h1>
      <p style="margin: 6px 0 0 0; font-size: 14px; opacity: 0.9;">
        {len(deals)} exceptional flight deal{'s' if len(deals) != 1 else ''} found scoring &ge; 80 on {date_str}
      </p>
    </div>

    <div style="background-color: #ffffff; padding: 24px; border-radius: 0 0 8px 8px; border: 1px solid #dadce0; border-top: none;">
      <p style="color: #5f6368; font-size: 14px; margin-top: 0; margin-bottom: 20px;">
        The automated tracker scanned routes from <strong>Prague (PRG)</strong> and <strong>Dublin (DUB)</strong> to <strong>New York (NYC)</strong>, <strong>Tokyo (TYO)</strong>, and <strong>Santiago (SCL)</strong> across Economy, Premium Economy, and Business classes. All mixed cabins and layover violations have been strictly filtered out.
      </p>

      {deal_cards}

      <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #e8eaed; color: #80868b; font-size: 12px; text-align: center;">
        Automated Flight Deal Tracker &bull; PRG & DUB &rarr; NYC, TYO, SCL &bull; Runs every 6 hours
      </div>
    </div>
  </div>
</body>
</html>
"""


def generate_plain_text(deals: List[Tuple[FlightOffer, ScoringResult]], scan_date: date) -> str:
    """Generate fallback plain-text version of email."""
    date_str = scan_date.strftime("%d %b %Y")
    lines = [
        f"Flight Deals Tracker - {date_str}",
        f"Found {len(deals)} qualifying flight deals (Score >= 80):",
        "=" * 50,
    ]
    for offer, score in deals:
        lines.append(f"\nRoute: {offer.origin} -> {offer.destination} ({offer.cabin_class.value})")
        lines.append(f"Score: {score.total_score:.1f}/100")
        lines.append(f"Price: {offer.price_czk:,.0f} CZK (Baseline: {score.baseline_avg:,.0f} CZK, Save {score.savings_percent:.0f}%)")
        lines.append(f"Dates: {offer.departure_date} to {offer.return_date} ({offer.stay_nights} nights)")
        lines.append(f"Google Flights: {offer.google_flights_url}")
        lines.append(f"Skyscanner: {offer.skyscanner_url}")
    return "\n".join(lines)


def parse_recipients(recipient_env: str, default_user: str) -> List[str]:
    """Parse single or comma-separated recipients, falling back to default user."""
    raw = (recipient_env or "").strip()
    if not raw:
        return [default_user] if default_user else []
    return [r.strip() for r in raw.split(",") if r.strip()]


def send_deal_digest(
    deals: List[Tuple[FlightOffer, ScoringResult]],
    dry_run: bool = False,
    preview_file: str = "artifacts/email_preview.html",
) -> bool:
    """Send deals digest email via Gmail SMTP or save preview in dry-run mode."""
    if not deals:
        print("[Notifier] No deals to send.")
        return False

    today = date.today()
    subject = f"Flight Deals Tracker - {today.strftime('%d %b %Y')}"
    html_content = generate_digest_html(deals, today)
    text_content = generate_plain_text(deals, today)

    # Save preview file if path provided
    if preview_file:
        os.makedirs(os.path.dirname(preview_file) or ".", exist_ok=True)
        with open(preview_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        print(f"[Notifier] Saved HTML preview to {preview_file}")

    if dry_run:
        print(f"[Notifier] Dry-run active. Email not dispatched to SMTP. (Deals: {len(deals)})")
        return True

    gmail_user = os.getenv("GMAIL_USER", "").strip()
    gmail_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    recipient_env = os.getenv("RECIPIENT_EMAIL", "").strip()
    recipients = parse_recipients(recipient_env, gmail_user)

    if not gmail_user or not gmail_password:
        print("[Notifier] WARNING: GMAIL_USER or GMAIL_APP_PASSWORD not configured. Skipping SMTP dispatch.")
        return False

    if not recipients:
        print("[Notifier] WARNING: No recipients resolved. Skipping SMTP dispatch.")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Flight Deal Tracker <{gmail_user}>"
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(text_content, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))

    try:
        # Use SSL port 465 or TLS port 587
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=20) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, recipients, msg.as_string())
        print(f"[Notifier] Successfully dispatched email alert to: {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"[Notifier] ERROR sending SMTP email via port 465: {e}. Trying TLS port 587...")
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as server:
                server.starttls()
                server.login(gmail_user, gmail_password)
                server.sendmail(gmail_user, recipients, msg.as_string())
            print(f"[Notifier] Successfully dispatched email alert via port 587 to: {', '.join(recipients)}")
            return True
        except Exception as e2:
            print(f"[Notifier] ERROR sending SMTP email via port 587: {e2}")
            return False
