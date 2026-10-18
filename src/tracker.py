"""Validation engine, scoring engine, state manager, and tracker runner."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from src.client import BaseFlightClient, MockFlightClient, get_flight_client
from src.config import (
    BENCHMARKS,
    DEAL_COOLDOWN_HOURS,
    DEAL_SCORE_THRESHOLD,
    DESTINATIONS,
    DESTINATION_RULES,
    DISALLOWED_AIRLINES,
    ORIGINS,
    PRICE_DROP_OVERRIDE_PERCENT,
    WEIGHT_PRICE,
    WEIGHT_SAVINGS,
    WEIGHT_TIMING,
)
from src.models import CabinClass, FlightOffer, ScoringResult, ValidationResult
from src.notifier import send_deal_digest


def validate_flight_offer(offer: FlightOffer) -> ValidationResult:
    """Validate flight offer against quality, layover, cabin, and seasonal rules."""
    rule = DESTINATION_RULES.get(offer.destination)
    if not rule:
        return ValidationResult(False, f"Unknown destination '{offer.destination}'")

    # 1. Seasonal Window Check
    dep_month = offer.departure_date.month
    if dep_month not in rule.seasonal_months:
        return ValidationResult(
            False,
            f"Departure month ({dep_month}) is outside seasonal window {sorted(list(rule.seasonal_months))}",
        )

    # 2. Transfer / Layover Rule Check (NYC: 0 stops; TYO/SCL: max 1 stop)
    out_stops = offer.outbound_leg.stops
    ret_stops = offer.return_leg.stops
    if out_stops > rule.max_stops or ret_stops > rule.max_stops:
        return ValidationResult(
            False,
            f"Layover limit exceeded for {offer.destination} (max {rule.max_stops}): outbound has {out_stops} stops, return has {ret_stops} stops",
        )

    # 3. Connection / Layover Duration Bounds (for 1-stop flights)
    for leg_name, leg in [("outbound", offer.outbound_leg), ("return", offer.return_leg)]:
        if leg.stops > 0:
            for layover in leg.layover_minutes:
                if layover < rule.min_layover_minutes:
                    return ValidationResult(
                        False,
                        f"Layover of {layover}m on {leg_name} leg is shorter than required minimum of {rule.min_layover_minutes}m",
                    )
                if layover > rule.max_layover_minutes:
                    return ValidationResult(
                        False,
                        f"Layover of {layover}m on {leg_name} leg exceeds maximum allowed limit of {rule.max_layover_minutes}m",
                    )

    # 4. Protected Connection / Self-Transfer Check
    if offer.is_self_transfer:
        return ValidationResult(
            False,
            "Disqualified: Self-transfer / uncoordinated ticket (protected single-ticket required)",
        )

    # 5. Airline Quality Filter (Full-service / Alliance carriers only)
    for seg in offer.all_segments:
        carrier_name = (seg.airline_name or "").upper()
        carrier_code = (seg.airline_code or "").upper()
        if carrier_code in DISALLOWED_AIRLINES or carrier_name in DISALLOWED_AIRLINES:
            return ValidationResult(
                False,
                f"Disqualified: Airline '{seg.airline_name or seg.airline_code}' is a budget/unbundled carrier",
            )

    # 6. Cabin Strictness Rule (Anti-Mixed Cabin)
    # Strictly for BUSINESS and PREMIUM_ECONOMY: 100% of segments must match target cabin.
    # For ECONOMY: standard economy segments are completely valid.
    if offer.cabin_class in {CabinClass.BUSINESS, CabinClass.PREMIUM_ECONOMY}:
        for seg in offer.all_segments:
            if seg.cabin_class != offer.cabin_class:
                return ValidationResult(
                    False,
                    f"Disqualified: Mixed-cabin on {offer.cabin_class.value} itinerary (segment {seg.departure_airport}->{seg.arrival_airport} is {seg.cabin_class.value})",
                )

    # 7. Stay Duration Check
    stay = offer.stay_nights
    if stay < rule.min_stay_nights or stay > rule.max_stay_nights:
        return ValidationResult(
            False,
            f"Stay duration of {stay} nights outside permitted range of {rule.min_stay_nights}–{rule.max_stay_nights} nights for {offer.destination}",
        )

    return ValidationResult(True, "All validation rules passed")


def calculate_deal_score(offer: FlightOffer) -> ScoringResult:
    """Calculate multi-factor deal score (0 to 100) based on benchmark pricing and timing."""
    key = (offer.origin, offer.destination, offer.cabin_class)
    benchmark = BENCHMARKS.get(key)
    if not benchmark:
        # Fallback if benchmark key not found
        return ScoringResult(0.0, 0.0, 0.0, 0.0, False, 0.0, 0.0, 0.0, 0.0)

    avg = benchmark.baseline_avg
    deal_min = benchmark.deal_min
    price = offer.price_czk

    # 1. S_price (40%): <= deal_min -> 100; >= avg -> 0; linear interpolation between
    if price <= deal_min:
        s_price = 100.0
    elif price >= avg:
        s_price = 0.0
    else:
        s_price = ((avg - price) / (avg - deal_min)) * 100.0
    s_price = max(0.0, min(100.0, s_price))

    # 2. S_savings (30%): (avg - price) / avg * 200 (capped at 100 pts)
    if price >= avg:
        s_savings = 0.0
    else:
        s_savings = ((avg - price) / avg) * 200.0
    s_savings = max(0.0, min(100.0, s_savings))

    # 3. S_timing (30%): 100 pts if departure in peak seasonal months, else 40 pts
    rule = DESTINATION_RULES.get(offer.destination)
    if rule and offer.departure_date.month in rule.seasonal_months:
        s_timing = 100.0
    else:
        s_timing = 40.0

    # Total Score
    total_score = (s_price * WEIGHT_PRICE) + (s_savings * WEIGHT_SAVINGS) + (s_timing * WEIGHT_TIMING)
    is_deal = total_score >= DEAL_SCORE_THRESHOLD

    savings_czk = max(0.0, avg - price)
    savings_percent = max(0.0, ((avg - price) / avg) * 100.0)

    return ScoringResult(
        s_price=round(s_price, 2),
        s_savings=round(s_savings, 2),
        s_timing=round(s_timing, 2),
        total_score=round(total_score, 2),
        is_deal=is_deal,
        baseline_avg=avg,
        deal_min=deal_min,
        savings_czk=round(savings_czk, 2),
        savings_percent=round(savings_percent, 2),
    )


class StateManager:
    """Manages deal persistence and 48-hour cooldown to avoid email spam."""

    def __init__(self, history_file: str = "data/deal_history.json"):
        self.history_file = history_file
        self.state: Dict[str, dict] = self._load()

    def _load(self) -> Dict[str, dict]:
        if os.path.exists(self.history_file):
            try:
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[StateManager] Warning: Could not read history file: {e}")
        return {}

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.history_file) or ".", exist_ok=True)
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            print(f"[StateManager] Warning: Could not save history file: {e}")

    def get_deal_key(self, offer: FlightOffer) -> str:
        """Construct canonical fingerprint for an offer."""
        airline = offer.operating_airlines[0] if offer.operating_airlines else "UNKNOWN"
        return f"{offer.origin}_{offer.destination}_{offer.cabin_class.value}_{offer.departure_date}_{offer.return_date}_{airline}"

    def should_alert(self, offer: FlightOffer, score: ScoringResult) -> bool:
        """Determine whether to alert based on 48h cooldown and price drop overrides."""
        key = self.get_deal_key(offer)
        now_ts = datetime.now(timezone.utc).timestamp()

        if key not in self.state:
            # Brand new deal -> Alert
            self.state[key] = {
                "price_czk": offer.price_czk,
                "score": score.total_score,
                "first_seen": now_ts,
                "last_alerted": now_ts,
            }
            self._save()
            return True

        record = self.state[key]
        last_price = record.get("price_czk", offer.price_czk)
        last_alerted = record.get("last_alerted", 0.0)

        # 1. Price drop override: If price dropped by >= 3%
        if (last_price - offer.price_czk) / last_price >= PRICE_DROP_OVERRIDE_PERCENT:
            record["price_czk"] = offer.price_czk
            record["score"] = score.total_score
            record["last_alerted"] = now_ts
            self._save()
            return True

        # 2. Cooldown check: Has 48 hours elapsed?
        hours_elapsed = (now_ts - last_alerted) / 3600.0
        if hours_elapsed >= DEAL_COOLDOWN_HOURS:
            record["price_czk"] = offer.price_czk
            record["score"] = score.total_score
            record["last_alerted"] = now_ts
            self._save()
            return True

        # Within cooldown and no price drop -> suppress duplicate alert
        return False


def generate_github_step_summary(
    scanned_count: int,
    disqualified_count: int,
    deals: List[Tuple[FlightOffer, ScoringResult]],
    disqualified_reasons: Dict[str, int],
) -> None:
    """Generate Markdown summary table in GitHub Actions runner tab."""
    summary_path = os.getenv("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"## ✈️ Flight Deal Tracker Run Summary ({today_str})",
        "",
        f"- **Offers Scanned:** {scanned_count}",
        f"- **Disqualified:** {disqualified_count}",
        f"- **Alertable Deals (Score &ge; 80):** {len(deals)}",
        "",
    ]

    if deals:
        lines.extend([
            "### 🎯 Top Scoring Deals",
            "| Route | Cabin | Dates | Price | Baseline | Score | Booking |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
        ])
        for offer, score in deals:
            dates = f"{offer.departure_date} to {offer.return_date}"
            price_str = f"**{offer.price_czk:,.0f} CZK**"
            if offer.origin == "DUB":
                price_str += " (~€" + str(int(offer.price_czk / 25.2)) + ")"
            base_str = f"{score.baseline_avg:,.0f} CZK"
            score_str = f"**{score.total_score:.1f}**"
            links = f"[Google Flights]({offer.google_flights_url}) \\| [Skyscanner]({offer.skyscanner_url})"
            lines.append(f"| {offer.origin} &rarr; {offer.destination} | {offer.cabin_class.value} | {dates} | {price_str} | {base_str} | {score_str} | {links} |")
        lines.append("")

    if disqualified_reasons:
        lines.extend([
            "### 🛑 Disqualification Breakdown",
            "| Reason Category | Count |",
            "| :--- | :--- |",
        ])
        for reason, count in sorted(disqualified_reasons.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"| {reason} | {count} |")
        lines.append("")

    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception as e:
        print(f"[Tracker] Notice: Could not write GitHub step summary: {e}")


def run_tracker(
    client: Optional[BaseFlightClient] = None,
    dry_run: bool = False,
    force_email: bool = False,
    sample_data: bool = False,
    output_html: str = "artifacts/email_preview.html",
    history_file: str = "data/deal_history.json",
) -> int:
    """Execute complete flight scan, evaluation, de-duplication, and alert dispatch."""
    if sample_data or client is None:
        client = MockFlightClient() if sample_data else get_flight_client()

    print(f"[Tracker] Initiating flight deal scan (Client: {client.__class__.__name__})...")

    state_mgr = StateManager(history_file=history_file)
    scanned_count = 0
    disqualified_count = 0
    disqualified_reasons: Dict[str, int] = {}
    alertable_deals: List[Tuple[FlightOffer, ScoringResult]] = []

    # Scan all origin x destination x cabin class combinations
    for origin in sorted(ORIGINS):
        for dest in sorted(DESTINATIONS):
            for cabin in [CabinClass.ECONOMY, CabinClass.PREMIUM_ECONOMY, CabinClass.BUSINESS]:
                offers = client.fetch_offers(origin, dest, cabin)
                for offer in offers:
                    scanned_count += 1
                    validation = validate_flight_offer(offer)
                    if not validation.is_valid:
                        disqualified_count += 1
                        short_reason = validation.reason.split(":")[0].strip()
                        disqualified_reasons[short_reason] = disqualified_reasons.get(short_reason, 0) + 1
                        continue

                    # Score valid offer
                    score = calculate_deal_score(offer)
                    if score.is_deal:
                        print(f"[Tracker] 🔥 DEAL DETECTED: {offer.origin}->{offer.destination} ({offer.cabin_class.value}) | Price: {offer.price_czk:,.0f} CZK | Score: {score.total_score:.1f}")
                        if force_email or state_mgr.should_alert(offer, score):
                            alertable_deals.append((offer, score))
                        else:
                            print(f"[Tracker] Deal suppressed by 48h cooldown: {offer.origin}->{offer.destination}")

    # Sort deals by score descending
    alertable_deals.sort(key=lambda x: x[1].total_score, reverse=True)

    print(f"\n[Tracker] Scan Complete.")
    print(f"Total Scanned: {scanned_count} | Disqualified: {disqualified_count} | Alertable Deals: {len(alertable_deals)}")

    # Send consolidated digest if deals found
    if alertable_deals:
        send_deal_digest(alertable_deals, dry_run=dry_run, preview_file=output_html)
    else:
        print("[Tracker] No new alertable deals found in this scan.")

    # Write GHA summary if inside GitHub Actions
    generate_github_step_summary(scanned_count, disqualified_count, alertable_deals, disqualified_reasons)

    return len(alertable_deals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Flight Deal Tracker backend service")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending SMTP emails (saves preview HTML)")
    parser.add_argument("--force-email", action="store_true", help="Bypass 48-hour cooldown and dispatch email")
    parser.add_argument("--sample-data", action="store_true", help="Force use of realistic mock fixtures")
    parser.add_argument("--output-html", default="artifacts/email_preview.html", help="Path to save preview HTML")
    parser.add_argument("--history-file", default="data/deal_history.json", help="Path to state tracking file")
    args = parser.parse_args()

    run_tracker(
        dry_run=args.dry_run,
        force_email=args.force_email,
        sample_data=args.sample_data,
        output_html=args.output_html,
        history_file=args.history_file,
    )


if __name__ == "__main__":
    main()
