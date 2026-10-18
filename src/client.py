"""Flight data clients: Base, Mock fixture generator, and Kiwi live API client."""

from __future__ import annotations

import abc
import os
import urllib.parse
from datetime import date, datetime, timedelta
from typing import List, Optional

from src.config import DEFAULT_EUR_TO_CZK, DESTINATION_RULES
from src.models import CabinClass, FlightLeg, FlightOffer, FlightSegment


def build_google_flights_url(
    origin: str,
    destination: str,
    dep_date: date,
    ret_date: date,
    cabin: CabinClass,
    max_stops: Optional[int] = None,
) -> str:
    """Generate a direct pre-filled Google Flights search URL."""
    cabin_map = {
        CabinClass.ECONOMY: "economy",
        CabinClass.PREMIUM_ECONOMY: "premium-economy",
        CabinClass.BUSINESS: "business",
    }
    cabin_param = cabin_map.get(cabin, "economy")
    query = (
        f"Flights from {origin} to {destination} on "
        f"{dep_date.strftime('%Y-%m-%d')} through {ret_date.strftime('%Y-%m-%d')}"
    )
    if max_stops == 0:
        query += " nonstop"
    encoded_query = urllib.parse.quote(query)
    return f"https://www.google.com/travel/flights?q={encoded_query}&cabin={cabin_param}"


def build_skyscanner_url(
    origin: str,
    destination: str,
    dep_date: date,
    ret_date: date,
    cabin: CabinClass,
) -> str:
    """Generate a direct pre-filled Skyscanner search URL."""
    cabin_map = {
        CabinClass.ECONOMY: "economy",
        CabinClass.PREMIUM_ECONOMY: "premiumeconomy",
        CabinClass.BUSINESS: "business",
    }
    cabin_slug = cabin_map.get(cabin, "economy")
    dep_str = dep_date.strftime("%y%m%d")
    ret_str = ret_date.strftime("%y%m%d")
    return (
        f"https://www.skyscanner.net/transport/flights/{origin.lower()}/"
        f"{destination.lower()}/{dep_str}/{ret_str}/?cabinclass={cabin_slug}&preferdirects=true"
    )


def convert_to_czk(price: float, currency: str, eur_rate: float = DEFAULT_EUR_TO_CZK) -> float:
    """Convert price to CZK if given in EUR or USD."""
    curr = (currency or "CZK").upper()
    if curr == "CZK":
        return round(price, 2)
    if curr == "EUR":
        return round(price * eur_rate, 2)
    if curr == "USD":
        # Approximate USD/CZK based on EUR rate (~23.5)
        return round(price * (eur_rate * 0.93), 2)
    return round(price, 2)


class BaseFlightClient(abc.ABC):
    """Abstract base client for fetching flight offers."""

    @abc.abstractmethod
    def fetch_offers(
        self,
        origin: str,
        destination: str,
        cabin: CabinClass,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[FlightOffer]:
        """Fetch flight offers for an origin-destination-cabin pair."""
        raise NotImplementedError


class MockFlightClient(BaseFlightClient):
    """High-fidelity mock flight client producing realistic scenario test offers."""

    def __init__(self, eur_rate: float = DEFAULT_EUR_TO_CZK):
        self.eur_rate = eur_rate

    def fetch_offers(
        self,
        origin: str,
        destination: str,
        cabin: CabinClass,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[FlightOffer]:
        offers: List[FlightOffer] = []
        rule = DESTINATION_RULES.get(destination)
        if not rule:
            return offers

        today = date.today()
        # Find next occurrence of a seasonal month
        target_year = today.year
        valid_months = sorted(list(rule.seasonal_months))

        # Generate a sample departure date in a seasonal month
        dep_month = valid_months[0]
        # If the month is earlier in the year, check if next year makes sense
        if dep_month < today.month:
            target_year += 1
        dep_date = date(target_year, dep_month, 10)

        # Stay duration matching rule
        stay_nights = rule.min_stay_nights + 1  # 8 nights for NYC, 15 nights for TYO/SCL
        ret_date = dep_date + timedelta(days=stay_nights)

        # Destination primary airport
        dest_airport = sorted(list(rule.airport_codes))[0]

        # 1. Exceptional High-Scoring Deal (>= 80 score)
        if origin == "PRG" and destination == "NYC" and cabin == CabinClass.BUSINESS:
            # PRG -> JFK direct (Delta), price = 28,000 CZK (deal_min 29k, avg 48k)
            out_seg = [
                FlightSegment("PRG", "JFK", datetime.combine(dep_date, datetime.min.time()).replace(hour=12),
                              datetime.combine(dep_date, datetime.min.time()).replace(hour=16),
                              "DL", "Delta Air Lines", "DL211", CabinClass.BUSINESS, 540)
            ]
            ret_seg = [
                FlightSegment("JFK", "PRG", datetime.combine(ret_date, datetime.min.time()).replace(hour=19),
                              datetime.combine(ret_date + timedelta(days=1), datetime.min.time()).replace(hour=10),
                              "DL", "Delta Air Lines", "DL210", CabinClass.BUSINESS, 540)
            ]
            offers.append(FlightOffer(
                id="OFFER-PRG-NYC-BIZ-DEAL",
                origin=origin,
                destination=destination,
                outbound_leg=FlightLeg(out_seg),
                return_leg=FlightLeg(ret_seg),
                price_czk=27500.0,
                cabin_class=CabinClass.BUSINESS,
                google_flights_url=build_google_flights_url(origin, destination, dep_date, ret_date, cabin, 0),
                skyscanner_url=build_skyscanner_url(origin, destination, dep_date, ret_date, cabin),
            ))

        elif origin == "DUB" and destination == "TYO" and cabin == CabinClass.ECONOMY:
            # DUB -> NRT 1 stop in FRA (Lufthansa), price = 11,500 CZK (deal_min 12k, avg 18.5k)
            # Layover: 2 hours (120 mins)
            out_seg = [
                FlightSegment("DUB", "FRA", datetime.combine(dep_date, datetime.min.time()).replace(hour=7),
                              datetime.combine(dep_date, datetime.min.time()).replace(hour=10),
                              "LH", "Lufthansa", "LH977", CabinClass.ECONOMY, 120),
                FlightSegment("FRA", "HND", datetime.combine(dep_date, datetime.min.time()).replace(hour=12),
                              datetime.combine(dep_date + timedelta(days=1), datetime.min.time()).replace(hour=7),
                              "LH", "Lufthansa", "LH716", CabinClass.ECONOMY, 660),
            ]
            ret_seg = [
                FlightSegment("HND", "FRA", datetime.combine(ret_date, datetime.min.time()).replace(hour=11),
                              datetime.combine(ret_date, datetime.min.time()).replace(hour=18),
                              "LH", "Lufthansa", "LH717", CabinClass.ECONOMY, 720),
                FlightSegment("FRA", "DUB", datetime.combine(ret_date, datetime.min.time()).replace(hour=20),
                              datetime.combine(ret_date, datetime.min.time()).replace(hour=21),
                              "LH", "Lufthansa", "LH980", CabinClass.ECONOMY, 120),
            ]
            offers.append(FlightOffer(
                id="OFFER-DUB-TYO-ECO-DEAL",
                origin=origin,
                destination=destination,
                outbound_leg=FlightLeg(out_seg),
                return_leg=FlightLeg(ret_seg),
                price_czk=11200.0,
                original_price=445.0,
                original_currency="EUR",
                cabin_class=CabinClass.ECONOMY,
                google_flights_url=build_google_flights_url(origin, destination, dep_date, ret_date, cabin, 1),
                skyscanner_url=build_skyscanner_url(origin, destination, dep_date, ret_date, cabin),
            ))

        elif origin == "PRG" and destination == "SCL" and cabin == CabinClass.PREMIUM_ECONOMY:
            # PRG -> SCL 1 stop in MAD (Iberia), price = 24,500 CZK (deal_min 26k, avg 38k)
            # Layover: 2h 30m (150 mins)
            out_seg = [
                FlightSegment("PRG", "MAD", datetime.combine(dep_date, datetime.min.time()).replace(hour=11),
                              datetime.combine(dep_date, datetime.min.time()).replace(hour=14),
                              "IB", "Iberia", "IB3149", CabinClass.PREMIUM_ECONOMY, 180),
                FlightSegment("MAD", "SCL", datetime.combine(dep_date, datetime.min.time()).replace(hour=16, minute=30),
                              datetime.combine(dep_date + timedelta(days=1), datetime.min.time()).replace(hour=5),
                              "IB", "Iberia", "IB6833", CabinClass.PREMIUM_ECONOMY, 810),
            ]
            ret_seg = [
                FlightSegment("SCL", "MAD", datetime.combine(ret_date, datetime.min.time()).replace(hour=13),
                              datetime.combine(ret_date + timedelta(days=1), datetime.min.time()).replace(hour=6),
                              "IB", "Iberia", "IB6830", CabinClass.PREMIUM_ECONOMY, 780),
                FlightSegment("MAD", "PRG", datetime.combine(ret_date + timedelta(days=1), datetime.min.time()).replace(hour=8, minute=30),
                              datetime.combine(ret_date + timedelta(days=1), datetime.min.time()).replace(hour=11, minute=20),
                              "IB", "Iberia", "IB3148", CabinClass.PREMIUM_ECONOMY, 170),
            ]
            offers.append(FlightOffer(
                id="OFFER-PRG-SCL-PREM-DEAL",
                origin=origin,
                destination=destination,
                outbound_leg=FlightLeg(out_seg),
                return_leg=FlightLeg(ret_seg),
                price_czk=24000.0,
                cabin_class=CabinClass.PREMIUM_ECONOMY,
                google_flights_url=build_google_flights_url(origin, destination, dep_date, ret_date, cabin, 1),
                skyscanner_url=build_skyscanner_url(origin, destination, dep_date, ret_date, cabin),
            ))

        # 2. General mock fallback offer for any remaining combination
        if not offers:
            # Generate a valid baseline offer
            is_direct = (rule.max_stops == 0)
            if is_direct:
                out_seg = [
                    FlightSegment(origin, dest_airport,
                                  datetime.combine(dep_date, datetime.min.time()).replace(hour=10),
                                  datetime.combine(dep_date, datetime.min.time()).replace(hour=15),
                                  "AF", "Air France", "AF100", cabin, 480)
                ]
                ret_seg = [
                    FlightSegment(dest_airport, origin,
                                  datetime.combine(ret_date, datetime.min.time()).replace(hour=18),
                                  datetime.combine(ret_date + timedelta(days=1), datetime.min.time()).replace(hour=9),
                                  "AF", "Air France", "AF101", cabin, 480)
                ]
            else:
                out_seg = [
                    FlightSegment(origin, "CDG",
                                  datetime.combine(dep_date, datetime.min.time()).replace(hour=7),
                                  datetime.combine(dep_date, datetime.min.time()).replace(hour=9),
                                  "AF", "Air France", "AF1001", cabin, 120),
                    FlightSegment("CDG", dest_airport,
                                  datetime.combine(dep_date, datetime.min.time()).replace(hour=11),
                                  datetime.combine(dep_date + timedelta(days=1), datetime.min.time()).replace(hour=6),
                                  "AF", "Air France", "AF274", cabin, 720),
                ]
                ret_seg = [
                    FlightSegment(dest_airport, "CDG",
                                  datetime.combine(ret_date, datetime.min.time()).replace(hour=10),
                                  datetime.combine(ret_date, datetime.min.time()).replace(hour=17),
                                  "AF", "Air France", "AF275", cabin, 720),
                    FlightSegment("CDG", origin,
                                  datetime.combine(ret_date, datetime.min.time()).replace(hour=19),
                                  datetime.combine(ret_date, datetime.min.time()).replace(hour=21),
                                  "AF", "Air France", "AF1002", cabin, 120),
                ]

            # Moderate pricing (scoring ~60-70, not trigger deal)
            offers.append(FlightOffer(
                id=f"OFFER-{origin}-{destination}-{cabin.value}-NORM",
                origin=origin,
                destination=destination,
                outbound_leg=FlightLeg(out_seg),
                return_leg=FlightLeg(ret_seg),
                price_czk=15000.0,
                cabin_class=cabin,
                google_flights_url=build_google_flights_url(origin, destination, dep_date, ret_date, cabin),
                skyscanner_url=build_skyscanner_url(origin, destination, dep_date, ret_date, cabin),
            ))

        return offers


class KiwiFlightClient(BaseFlightClient):
    """Client for Kiwi / Tequila Flight Search API (https://tequila.kiwi.com)."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("KIWI_API_KEY", "")

    def fetch_offers(
        self,
        origin: str,
        destination: str,
        cabin: CabinClass,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[FlightOffer]:
        if not self.api_key:
            return []

        # When api_key is present, queries Kiwi API via urllib
        import json
        import urllib.request

        rule = DESTINATION_RULES.get(destination)
        if not rule:
            return []

        url = "https://api.tequila.kiwi.com/v2/search"
        headers = {"apikey": self.api_key}

        # Map cabin class to Kiwi cabin param: M (economy), W (premium economy), C (business)
        cabin_param = "M"
        if cabin == CabinClass.PREMIUM_ECONOMY:
            cabin_param = "W"
        elif cabin == CabinClass.BUSINESS:
            cabin_param = "C"

        start_str = (start_date or date.today()).strftime("%d/%m/%Y")
        end_str = (end_date or (date.today() + timedelta(days=300))).strftime("%d/%m/%Y")

        params = {
            "fly_from": origin,
            "fly_to": destination,
            "date_from": start_str,
            "date_to": end_str,
            "nights_in_dst_from": rule.min_stay_nights,
            "nights_in_dst_to": rule.max_stay_nights,
            "selected_cabins": cabin_param,
            "max_stopovers": rule.max_stops,
            "curr": "CZK",
            "limit": 30,
        }
        query_string = urllib.parse.urlencode(params)
        req = urllib.request.Request(f"{url}?{query_string}", headers=headers)

        offers: List[FlightOffer] = []
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                for item in data.get("data", []):
                    # Parse routes into outbound and return segments
                    out_segs: List[FlightSegment] = []
                    ret_segs: List[FlightSegment] = []
                    for seg in item.get("route", []):
                        dep_time = datetime.fromisoformat(seg["local_departure"].replace("Z", "+00:00"))
                        arr_time = datetime.fromisoformat(seg["local_arrival"].replace("Z", "+00:00"))
                        flight_seg = FlightSegment(
                            departure_airport=seg["flyFrom"],
                            arrival_airport=seg["flyTo"],
                            departure_time=dep_time,
                            arrival_time=arr_time,
                            airline_code=seg.get("airline", ""),
                            airline_name=seg.get("airline", ""),
                            flight_number=str(seg.get("flight_no", "")),
                            cabin_class=CabinClass.from_string(seg.get("fare_category", cabin.value)),
                        )
                        if seg.get("return") == 1:
                            ret_segs.append(flight_seg)
                        else:
                            out_segs.append(flight_seg)

                    if out_segs and ret_segs:
                        offers.append(FlightOffer(
                            id=item.get("id", ""),
                            origin=origin,
                            destination=destination,
                            outbound_leg=FlightLeg(out_segs),
                            return_leg=FlightLeg(ret_segs),
                            price_czk=float(item.get("price", 0.0)),
                            cabin_class=cabin,
                            is_self_transfer=item.get("has_airport_change", False) or item.get("virtual_interlining", False),
                            google_flights_url=build_google_flights_url(origin, destination, out_segs[0].departure_time.date(), ret_segs[0].departure_time.date(), cabin, rule.max_stops),
                            skyscanner_url=build_skyscanner_url(origin, destination, out_segs[0].departure_time.date(), ret_segs[0].departure_time.date(), cabin),
                            booking_url=item.get("deep_link", ""),
                        ))
        except Exception:
            # Fallback gracefully
            return []

        return offers


def get_flight_client() -> BaseFlightClient:
    """Return live Kiwi client if API key configured, otherwise high-fidelity Mock client."""
    kiwi_key = os.getenv("KIWI_API_KEY")
    if kiwi_key and kiwi_key.strip():
        return KiwiFlightClient(api_key=kiwi_key.strip())
    return MockFlightClient()
