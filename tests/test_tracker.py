"""Comprehensive unit tests for Flight Deal Tracker backend service."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta

from src.client import MockFlightClient, build_google_flights_url, build_skyscanner_url
from src.config import BENCHMARKS, DESTINATION_RULES
from src.models import CabinClass, FlightLeg, FlightOffer, FlightSegment
from src.notifier import (
    generate_deal_html_card,
    generate_digest_html,
    parse_recipients,
    send_deal_digest,
)
from src.tracker import (
    StateManager,
    calculate_deal_score,
    run_tracker,
    validate_flight_offer,
)


class TestValidationEngine(unittest.TestCase):
    """Tests quality filters, layover restrictions, mixed cabin, and duration rules."""

    def setUp(self):
        self.dep_time = datetime(2027, 5, 10, 10, 0)  # May is in peak season for NYC & TYO
        self.ret_time_nyc = self.dep_time + timedelta(days=8)  # 8 nights (valid for NYC: 7-10)
        self.ret_time_tyo = self.dep_time + timedelta(days=16)  # 16 nights (valid for TYO: 14-21)

    def _create_direct_offer(
        self,
        origin: str = "PRG",
        dest: str = "NYC",
        cabin: CabinClass = CabinClass.BUSINESS,
        dep_time: datetime | None = None,
        ret_time: datetime | None = None,
    ) -> FlightOffer:
        dt = dep_time or self.dep_time
        rt = ret_time or (dt + timedelta(days=8 if dest == "NYC" else 16))
        dest_airport = "JFK" if dest == "NYC" else ("NRT" if dest == "TYO" else "SCL")

        out_seg = [
            FlightSegment(origin, dest_airport, dt, dt + timedelta(hours=9), "DL", "Delta Air Lines", "DL211", cabin, 540)
        ]
        ret_seg = [
            FlightSegment(dest_airport, origin, rt, rt + timedelta(hours=9), "DL", "Delta Air Lines", "DL210", cabin, 540)
        ]
        return FlightOffer(
            id="TEST-DIRECT-OFFER",
            origin=origin,
            destination=dest,
            outbound_leg=FlightLeg(out_seg),
            return_leg=FlightLeg(ret_seg),
            price_czk=25000.0,
            cabin_class=cabin,
        )

    def test_nyc_direct_flight_passes(self):
        """Direct flight to NYC passes validation."""
        offer = self._create_direct_offer(origin="PRG", dest="NYC", cabin=CabinClass.BUSINESS)
        val = validate_flight_offer(offer)
        self.assertTrue(val.is_valid, f"Expected valid, got: {val.reason}")

    def test_nyc_layover_disqualified(self):
        """Any layover to NYC (max_stops = 0) must be disqualified."""
        dt = self.dep_time
        rt = self.ret_time_nyc
        # 1 stop outbound: PRG -> LHR -> JFK
        out_segs = [
            FlightSegment("PRG", "LHR", dt, dt + timedelta(hours=2), "BA", "British Airways", "BA857", CabinClass.ECONOMY, 120),
            FlightSegment("LHR", "JFK", dt + timedelta(hours=4), dt + timedelta(hours=12), "BA", "British Airways", "BA177", CabinClass.ECONOMY, 480),
        ]
        ret_segs = [
            FlightSegment("JFK", "PRG", rt, rt + timedelta(hours=9), "BA", "British Airways", "BA178", CabinClass.ECONOMY, 540)
        ]
        offer = FlightOffer(
            id="NYC-LAYOVER-OFFER",
            origin="PRG",
            destination="NYC",
            outbound_leg=FlightLeg(out_segs),
            return_leg=FlightLeg(ret_segs),
            price_czk=12000.0,
            cabin_class=CabinClass.ECONOMY,
        )
        val = validate_flight_offer(offer)
        self.assertFalse(val.is_valid)
        self.assertIn("Layover limit exceeded", val.reason)

    def test_tyo_permitted_one_stop(self):
        """Tokyo allows max 1 stop with valid connection time (75m - 6h)."""
        dt = self.dep_time
        rt = self.ret_time_tyo
        # 1 stop outbound with 2-hour layover (120 mins)
        out_segs = [
            FlightSegment("DUB", "FRA", dt, dt + timedelta(hours=2), "LH", "Lufthansa", "LH977", CabinClass.ECONOMY, 120),
            FlightSegment("FRA", "HND", dt + timedelta(hours=4), dt + timedelta(hours=15), "LH", "Lufthansa", "LH716", CabinClass.ECONOMY, 660),
        ]
        # Direct return
        ret_segs = [
            FlightSegment("HND", "FRA", rt, rt + timedelta(hours=12), "LH", "Lufthansa", "LH717", CabinClass.ECONOMY, 720),
            FlightSegment("FRA", "DUB", rt + timedelta(hours=14), rt + timedelta(hours=16), "LH", "Lufthansa", "LH980", CabinClass.ECONOMY, 120),
        ]
        offer = FlightOffer(
            id="TYO-1STOP-OFFER",
            origin="DUB",
            destination="TYO",
            outbound_leg=FlightLeg(out_segs),
            return_leg=FlightLeg(ret_segs),
            price_czk=14000.0,
            cabin_class=CabinClass.ECONOMY,
        )
        val = validate_flight_offer(offer)
        self.assertTrue(val.is_valid, f"Expected valid 1-stop, got: {val.reason}")

    def test_tyo_disqualified_two_stops(self):
        """Tokyo with 2 stops is disqualified (max_stops = 1)."""
        dt = self.dep_time
        rt = self.ret_time_tyo
        out_segs = [
            FlightSegment("PRG", "FRA", dt, dt + timedelta(hours=1), "LH", "Lufthansa", "LH1", CabinClass.ECONOMY, 60),
            FlightSegment("FRA", "MUC", dt + timedelta(hours=3), dt + timedelta(hours=4), "LH", "Lufthansa", "LH2", CabinClass.ECONOMY, 60),
            FlightSegment("MUC", "HND", dt + timedelta(hours=6), dt + timedelta(hours=17), "LH", "Lufthansa", "LH3", CabinClass.ECONOMY, 660),
        ]
        ret_segs = [
            FlightSegment("HND", "PRG", rt, rt + timedelta(hours=14), "LH", "Lufthansa", "LH4", CabinClass.ECONOMY, 840)
        ]
        offer = FlightOffer(
            id="TYO-2STOPS-OFFER",
            origin="PRG",
            destination="TYO",
            outbound_leg=FlightLeg(out_segs),
            return_leg=FlightLeg(ret_segs),
            price_czk=14000.0,
            cabin_class=CabinClass.ECONOMY,
        )
        val = validate_flight_offer(offer)
        self.assertFalse(val.is_valid)
        self.assertIn("Layover limit exceeded", val.reason)

    def test_connection_time_bounds(self):
        """Layover must be between 75m and 360m (6h)."""
        dt = self.dep_time
        rt = self.ret_time_tyo

        # Too short (50 minutes)
        short_out = [
            FlightSegment("PRG", "FRA", dt, dt + timedelta(hours=1), "LH", "Lufthansa", "LH1", CabinClass.ECONOMY, 60),
            FlightSegment("FRA", "HND", dt + timedelta(hours=1, minutes=50), dt + timedelta(hours=12), "LH", "Lufthansa", "LH2", CabinClass.ECONOMY, 600),
        ]
        ret = [FlightSegment("HND", "PRG", rt, rt + timedelta(hours=12), "LH", "Lufthansa", "LH3", CabinClass.ECONOMY, 720)]
        offer_short = FlightOffer("SHORT-LAYOVER", "PRG", "TYO", FlightLeg(short_out), FlightLeg(ret), 15000.0, CabinClass.ECONOMY)
        val_short = validate_flight_offer(offer_short)
        self.assertFalse(val_short.is_valid)
        self.assertIn("shorter than required minimum", val_short.reason)

        # Too long (7 hours = 420 mins)
        long_out = [
            FlightSegment("PRG", "FRA", dt, dt + timedelta(hours=1), "LH", "Lufthansa", "LH1", CabinClass.ECONOMY, 60),
            FlightSegment("FRA", "HND", dt + timedelta(hours=8), dt + timedelta(hours=19), "LH", "Lufthansa", "LH2", CabinClass.ECONOMY, 600),
        ]
        offer_long = FlightOffer("LONG-LAYOVER", "PRG", "TYO", FlightLeg(long_out), FlightLeg(ret), 15000.0, CabinClass.ECONOMY)
        val_long = validate_flight_offer(offer_long)
        self.assertFalse(val_long.is_valid)
        self.assertIn("exceeds maximum allowed limit", val_long.reason)

    def test_self_transfer_disqualified(self):
        """Unprotected self-transfer tickets must be disqualified."""
        offer = self._create_direct_offer(origin="PRG", dest="NYC", cabin=CabinClass.ECONOMY)
        offer.is_self_transfer = True
        val = validate_flight_offer(offer)
        self.assertFalse(val.is_valid)
        self.assertIn("Self-transfer", val.reason)

    def test_budget_airline_disqualified(self):
        """Low-cost/unbundled airlines (e.g. Norse, Play) must be disqualified."""
        dt = self.dep_time
        rt = self.ret_time_nyc
        out_seg = [FlightSegment("PRG", "JFK", dt, dt + timedelta(hours=9), "N0", "Norse Atlantic", "N01", CabinClass.ECONOMY, 540)]
        ret_seg = [FlightSegment("JFK", "PRG", rt, rt + timedelta(hours=9), "N0", "Norse Atlantic", "N02", CabinClass.ECONOMY, 540)]
        offer = FlightOffer("NORSE-OFFER", "PRG", "NYC", FlightLeg(out_seg), FlightLeg(ret_seg), 8000.0, CabinClass.ECONOMY)
        val = validate_flight_offer(offer)
        self.assertFalse(val.is_valid)
        self.assertIn("budget/unbundled carrier", val.reason)

    def test_mixed_cabin_business_disqualified(self):
        """Business itinerary with an Economy feeder flight must be disqualified."""
        dt = self.dep_time
        rt = self.ret_time_tyo
        # Outbound: PRG -> CDG in ECONOMY (feeder), CDG -> HND in BUSINESS
        out_segs = [
            FlightSegment("PRG", "CDG", dt, dt + timedelta(hours=2), "AF", "Air France", "AF1001", CabinClass.ECONOMY, 120),
            FlightSegment("CDG", "HND", dt + timedelta(hours=4), dt + timedelta(hours=15), "AF", "Air France", "AF274", CabinClass.BUSINESS, 660),
        ]
        ret_segs = [
            FlightSegment("HND", "CDG", rt, rt + timedelta(hours=12), "AF", "Air France", "AF275", CabinClass.BUSINESS, 720),
            FlightSegment("CDG", "PRG", rt + timedelta(hours=14), rt + timedelta(hours=16), "AF", "Air France", "AF1002", CabinClass.BUSINESS, 120),
        ]
        offer = FlightOffer(
            id="MIXED-CABIN-BIZ",
            origin="PRG",
            destination="TYO",
            outbound_leg=FlightLeg(out_segs),
            return_leg=FlightLeg(ret_segs),
            price_czk=36000.0,
            cabin_class=CabinClass.BUSINESS,
        )
        val = validate_flight_offer(offer)
        self.assertFalse(val.is_valid)
        self.assertIn("Mixed-cabin on BUSINESS itinerary", val.reason)

    def test_pure_business_itinerary_passes(self):
        """100% genuine Business itinerary passes anti-mixed cabin validation."""
        dt = self.dep_time
        rt = self.ret_time_tyo
        out_segs = [
            FlightSegment("PRG", "CDG", dt, dt + timedelta(hours=2), "AF", "Air France", "AF1001", CabinClass.BUSINESS, 120),
            FlightSegment("CDG", "HND", dt + timedelta(hours=4), dt + timedelta(hours=15), "AF", "Air France", "AF274", CabinClass.BUSINESS, 660),
        ]
        ret_segs = [
            FlightSegment("HND", "CDG", rt, rt + timedelta(hours=12), "AF", "Air France", "AF275", CabinClass.BUSINESS, 720),
            FlightSegment("CDG", "PRG", rt + timedelta(hours=14), rt + timedelta(hours=16), "AF", "Air France", "AF1002", CabinClass.BUSINESS, 120),
        ]
        offer = FlightOffer(
            id="PURE-BIZ-OFFER",
            origin="PRG",
            destination="TYO",
            outbound_leg=FlightLeg(out_segs),
            return_leg=FlightLeg(ret_segs),
            price_czk=37000.0,
            cabin_class=CabinClass.BUSINESS,
        )
        val = validate_flight_offer(offer)
        self.assertTrue(val.is_valid, f"Expected pure business to pass, got: {val.reason}")

    def test_economy_offer_with_economy_segments_passes(self):
        """Standard economy offer is completely valid and not disqualified."""
        offer = self._create_direct_offer(origin="PRG", dest="NYC", cabin=CabinClass.ECONOMY)
        val = validate_flight_offer(offer)
        self.assertTrue(val.is_valid, f"Expected economy to pass, got: {val.reason}")

    def test_stay_duration_nyc(self):
        """NYC stay duration must be 7 to 10 nights."""
        dt = self.dep_time
        # 6 nights -> Fail
        offer_6n = self._create_direct_offer(origin="PRG", dest="NYC", dep_time=dt, ret_time=dt + timedelta(days=6))
        self.assertFalse(validate_flight_offer(offer_6n).is_valid)

        # 7 nights -> Pass
        offer_7n = self._create_direct_offer(origin="PRG", dest="NYC", dep_time=dt, ret_time=dt + timedelta(days=7))
        self.assertTrue(validate_flight_offer(offer_7n).is_valid)

        # 10 nights -> Pass
        offer_10n = self._create_direct_offer(origin="PRG", dest="NYC", dep_time=dt, ret_time=dt + timedelta(days=10))
        self.assertTrue(validate_flight_offer(offer_10n).is_valid)

        # 11 nights -> Fail
        offer_11n = self._create_direct_offer(origin="PRG", dest="NYC", dep_time=dt, ret_time=dt + timedelta(days=11))
        self.assertFalse(validate_flight_offer(offer_11n).is_valid)

    def test_stay_duration_tyo_and_scl(self):
        """TYO and SCL stay duration must be 14 to 21 nights."""
        dt = self.dep_time
        # 13 nights -> Fail
        offer_13n = self._create_direct_offer(origin="PRG", dest="TYO", dep_time=dt, ret_time=dt + timedelta(days=13))
        self.assertFalse(validate_flight_offer(offer_13n).is_valid)

        # 14 nights -> Pass
        offer_14n = self._create_direct_offer(origin="PRG", dest="TYO", dep_time=dt, ret_time=dt + timedelta(days=14))
        self.assertTrue(validate_flight_offer(offer_14n).is_valid)

        # 21 nights -> Pass
        offer_21n = self._create_direct_offer(origin="PRG", dest="TYO", dep_time=dt, ret_time=dt + timedelta(days=21))
        self.assertTrue(validate_flight_offer(offer_21n).is_valid)

        # 22 nights -> Fail
        offer_22n = self._create_direct_offer(origin="PRG", dest="TYO", dep_time=dt, ret_time=dt + timedelta(days=22))
        self.assertFalse(validate_flight_offer(offer_22n).is_valid)

    def test_seasonal_window_filter(self):
        """Flights outside defined seasonal window are rejected."""
        # NYC peak is Apr-Jun (4-6), Sep-Oct (9-10). Month 8 (August) is off-peak.
        aug_dep = datetime(2027, 8, 10, 10, 0)
        offer_offpeak = self._create_direct_offer(origin="PRG", dest="NYC", dep_time=aug_dep, ret_time=aug_dep + timedelta(days=8))
        val = validate_flight_offer(offer_offpeak)
        self.assertFalse(val.is_valid)
        self.assertIn("outside seasonal window", val.reason)

    def test_scl_year_crossing_months(self):
        """SCL seasonal window (Nov-Feb: 11, 12, 1, 2) handles January correctly."""
        jan_dep = datetime(2027, 1, 15, 10, 0)
        dest_airport = "SCL"
        out_seg = [
            FlightSegment("PRG", "MAD", jan_dep, jan_dep + timedelta(hours=3), "IB", "Iberia", "IB3149", CabinClass.ECONOMY, 180),
            FlightSegment("MAD", dest_airport, jan_dep + timedelta(hours=5), jan_dep + timedelta(hours=18), "IB", "Iberia", "IB6833", CabinClass.ECONOMY, 780),
        ]
        ret_time = jan_dep + timedelta(days=16)
        ret_seg = [
            FlightSegment(dest_airport, "MAD", ret_time, ret_time + timedelta(hours=13), "IB", "Iberia", "IB6830", CabinClass.ECONOMY, 780),
            FlightSegment("MAD", "PRG", ret_time + timedelta(hours=15), ret_time + timedelta(hours=18), "IB", "Iberia", "IB3148", CabinClass.ECONOMY, 180),
        ]
        offer = FlightOffer("SCL-JAN-OFFER", "PRG", "SCL", FlightLeg(out_seg), FlightLeg(ret_seg), 22000.0, CabinClass.ECONOMY)
        val = validate_flight_offer(offer)
        self.assertTrue(val.is_valid, f"Expected January SCL flight to pass, got: {val.reason}")


class TestScoringEngine(unittest.TestCase):
    """Tests the exact mathematical deal scoring formula: (S_price * 0.40) + (S_savings * 0.30) + (S_timing * 0.30)."""

    def setUp(self):
        self.dep_time = datetime(2027, 5, 10, 10, 0)  # Peak month (May)
        self.ret_time = self.dep_time + timedelta(days=8)

    def _make_offer(self, price: float, origin: str = "PRG", dest: str = "NYC", cabin: CabinClass = CabinClass.BUSINESS, dep_time: datetime | None = None) -> FlightOffer:
        dt = dep_time or self.dep_time
        rt = dt + timedelta(days=8)
        out_seg = [FlightSegment(origin, "JFK", dt, dt + timedelta(hours=9), "DL", "Delta", "DL1", cabin, 540)]
        ret_seg = [FlightSegment("JFK", origin, rt, rt + timedelta(hours=9), "DL", "Delta", "DL2", cabin, 540)]
        return FlightOffer("TEST-SCORE", origin, dest, FlightLeg(out_seg), FlightLeg(ret_seg), price, cabin)

    def test_score_at_deal_min(self):
        """At price == deal_min (29k for PRG-NYC Business, avg 48k), S_price=100."""
        # PRG-NYC Business: avg=48000, deal_min=29000
        offer = self._make_offer(price=29000.0)
        score = calculate_deal_score(offer)
        self.assertEqual(score.s_price, 100.0)
        # S_savings = (48000 - 29000)/48000 * 200 = 19000/48000 * 200 = 79.17
        expected_savings = round((19000.0 / 48000.0) * 200.0, 2)
        self.assertEqual(score.s_savings, expected_savings)
        self.assertEqual(score.s_timing, 100.0)
        # Total = (100 * 0.40) + (79.17 * 0.30) + (100 * 0.30) = 40 + 23.75 + 30 = 93.75
        self.assertAlmostEqual(score.total_score, 93.75, places=1)
        self.assertTrue(score.is_deal)

    def test_score_at_baseline_avg(self):
        """At price == avg (48k), S_price=0, S_savings=0, S_timing=100 -> Total=30.0."""
        offer = self._make_offer(price=48000.0)
        score = calculate_deal_score(offer)
        self.assertEqual(score.s_price, 0.0)
        self.assertEqual(score.s_savings, 0.0)
        self.assertEqual(score.s_timing, 100.0)
        self.assertEqual(score.total_score, 30.0)
        self.assertFalse(score.is_deal)

    def test_score_below_deal_min_capped(self):
        """Price lower than deal_min is capped at 100 for S_price and S_savings."""
        offer = self._make_offer(price=15000.0)
        score = calculate_deal_score(offer)
        self.assertEqual(score.s_price, 100.0)
        self.assertEqual(score.s_savings, 100.0)
        self.assertEqual(score.s_timing, 100.0)
        self.assertEqual(score.total_score, 100.0)
        self.assertTrue(score.is_deal)

    def test_score_above_avg_clamped_to_zero(self):
        """Price higher than avg is clamped to 0 without negative scores."""
        offer = self._make_offer(price=60000.0)
        score = calculate_deal_score(offer)
        self.assertEqual(score.s_price, 0.0)
        self.assertEqual(score.s_savings, 0.0)
        self.assertEqual(score.s_timing, 100.0)
        self.assertEqual(score.total_score, 30.0)
        self.assertFalse(score.is_deal)

    def test_score_threshold_80_trigger(self):
        """Verify deal triggers when score >= 80.0 and does not trigger when < 80.0."""
        # For PRG-NYC Economy: avg=13500, deal_min=8500
        # Let's find price where score is slightly above 80
        offer_deal = self._make_offer(price=9200.0, cabin=CabinClass.ECONOMY)
        score_deal = calculate_deal_score(offer_deal)
        self.assertGreaterEqual(score_deal.total_score, 80.0)
        self.assertTrue(score_deal.is_deal)

        # Price where score is below 80
        offer_non_deal = self._make_offer(price=11500.0, cabin=CabinClass.ECONOMY)
        score_non_deal = calculate_deal_score(offer_non_deal)
        self.assertLess(score_non_deal.total_score, 80.0)
        self.assertFalse(score_non_deal.is_deal)


class TestStateManager(unittest.TestCase):
    """Tests 48-hour cooldown and price drop override logic."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.history_file = os.path.join(self.test_dir, "deal_history.json")
        self.state_mgr = StateManager(history_file=self.history_file)
        dep_time = datetime(2027, 5, 10, 10, 0)
        ret_time = dep_time + timedelta(days=8)
        out_seg = [FlightSegment("PRG", "JFK", dep_time, dep_time + timedelta(hours=9), "DL", "Delta", "DL211", CabinClass.BUSINESS, 540)]
        ret_seg = [FlightSegment("JFK", "PRG", ret_time, ret_time + timedelta(hours=9), "DL", "Delta", "DL210", CabinClass.BUSINESS, 540)]
        self.offer = FlightOffer("OFFER-1", "PRG", "NYC", FlightLeg(out_seg), FlightLeg(ret_seg), 27000.0, CabinClass.BUSINESS)
        self.score = calculate_deal_score(self.offer)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_new_deal_alerts_immediately(self):
        """First time seeing a deal -> should alert."""
        self.assertTrue(self.state_mgr.should_alert(self.offer, self.score))

    def test_duplicate_deal_within_cooldown_suppressed(self):
        """Identical deal within 48h cooldown -> suppressed."""
        self.assertTrue(self.state_mgr.should_alert(self.offer, self.score))
        # Second check immediately
        self.assertFalse(self.state_mgr.should_alert(self.offer, self.score))

    def test_price_drop_overrides_cooldown(self):
        """Price drop >= 3% overrides cooldown and triggers re-alert."""
        self.assertTrue(self.state_mgr.should_alert(self.offer, self.score))
        # Price drops from 27,000 to 25,500 (drop of 5.5% > 3%)
        cheaper_offer = FlightOffer(
            id=self.offer.id,
            origin=self.offer.origin,
            destination=self.offer.destination,
            outbound_leg=self.offer.outbound_leg,
            return_leg=self.offer.return_leg,
            price_czk=25500.0,
            cabin_class=self.offer.cabin_class,
        )
        cheaper_score = calculate_deal_score(cheaper_offer)
        self.assertTrue(self.state_mgr.should_alert(cheaper_offer, cheaper_score))


class TestNotifierAndDigest(unittest.TestCase):
    """Tests HTML email digest rendering, recipient parsing, and preview generation."""

    def setUp(self):
        dep_time = datetime(2027, 5, 10, 10, 0)
        ret_time = dep_time + timedelta(days=8)
        out_seg = [FlightSegment("PRG", "JFK", dep_time, dep_time + timedelta(hours=9), "DL", "Delta", "DL211", CabinClass.BUSINESS, 540)]
        ret_seg = [FlightSegment("JFK", "PRG", ret_time, ret_time + timedelta(hours=9), "DL", "Delta", "DL210", CabinClass.BUSINESS, 540)]
        self.offer = FlightOffer(
            id="OFFER-DIGEST",
            origin="PRG",
            destination="NYC",
            outbound_leg=FlightLeg(out_seg),
            return_leg=FlightLeg(ret_seg),
            price_czk=27500.0,
            cabin_class=CabinClass.BUSINESS,
            google_flights_url=build_google_flights_url("PRG", "NYC", dep_time.date(), ret_time.date(), CabinClass.BUSINESS, 0),
            skyscanner_url=build_skyscanner_url("PRG", "NYC", dep_time.date(), ret_time.date(), CabinClass.BUSINESS),
        )
        self.score = calculate_deal_score(self.offer)

    def test_digest_html_contains_required_elements(self):
        """HTML digest includes deal score, route, pricing, and both booking links."""
        deals = [(self.offer, self.score)]
        html = generate_digest_html(deals, date(2026, 10, 18))
        self.assertIn("Score:", html)
        self.assertIn("PRG &rarr; NYC", html)
        self.assertIn("27,500 CZK", html)
        self.assertIn("Search Google Flights", html)
        self.assertIn("Search Skyscanner", html)
        self.assertIn("Flight Deals Tracker - 18 Oct 2026", html)

    def test_dublin_deal_shows_dual_currency(self):
        """Dublin deals show both CZK and approximate EUR equivalent."""
        dep_time = datetime(2027, 4, 15, 10, 0)
        ret_time = dep_time + timedelta(days=16)
        out_seg = [FlightSegment("DUB", "NRT", dep_time, dep_time + timedelta(hours=14), "LH", "Lufthansa", "LH1", CabinClass.ECONOMY, 840)]
        ret_seg = [FlightSegment("NRT", "DUB", ret_time, ret_time + timedelta(hours=14), "LH", "Lufthansa", "LH2", CabinClass.ECONOMY, 840)]
        dub_offer = FlightOffer(
            id="DUB-DEAL",
            origin="DUB",
            destination="TYO",
            outbound_leg=FlightLeg(out_seg),
            return_leg=FlightLeg(ret_seg),
            price_czk=11200.0,
            original_price=445.0,
            original_currency="EUR",
            cabin_class=CabinClass.ECONOMY,
        )
        score = calculate_deal_score(dub_offer)
        card_html = generate_deal_html_card(dub_offer, score)
        self.assertIn("11,200 CZK", card_html)
        self.assertIn("&euro;445", card_html)

    def test_recipient_parsing(self):
        """Handles single, multiple comma-separated, and empty recipient strings."""
        self.assertEqual(parse_recipients("a@b.com", "default@b.com"), ["a@b.com"])
        self.assertEqual(parse_recipients("a@b.com, c@d.com ", "default@b.com"), ["a@b.com", "c@d.com"])
        self.assertEqual(parse_recipients("", "default@b.com"), ["default@b.com"])

    def test_dry_run_saves_preview_file(self):
        """Dry-run successfully saves preview HTML without throwing exceptions."""
        temp_dir = tempfile.mkdtemp()
        preview_path = os.path.join(temp_dir, "preview.html")
        try:
            res = send_deal_digest([(self.offer, self.score)], dry_run=True, preview_file=preview_path)
            self.assertTrue(res)
            self.assertTrue(os.path.exists(preview_path))
            with open(preview_path, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("Automated Flight Deal Alert", content)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestFullTrackerIntegration(unittest.TestCase):
    """End-to-end integration test with mock data."""

    def test_run_tracker_dry_run(self):
        """Tracker runs end-to-end with mock data in dry-run mode and detects deals."""
        temp_dir = tempfile.mkdtemp()
        preview_path = os.path.join(temp_dir, "email.html")
        history_path = os.path.join(temp_dir, "history.json")
        try:
            deals_found = run_tracker(
                dry_run=True,
                sample_data=True,
                output_html=preview_path,
                history_file=history_path,
            )
            self.assertGreater(deals_found, 0)
            self.assertTrue(os.path.exists(preview_path))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestGoogleFlightsClient(unittest.TestCase):
    """Tests for live GoogleFlightsClient and client resolution."""

    def test_get_flight_client_resolution(self):
        """get_flight_client returns GoogleFlightsClient or MockFlightClient based on env."""
        from src.client import GoogleFlightsClient, MockFlightClient, get_flight_client

        # FORCE_MOCK returns MockFlightClient
        os.environ["FORCE_MOCK"] = "1"
        client = get_flight_client()
        self.assertIsInstance(client, MockFlightClient)

        del os.environ["FORCE_MOCK"]
        client = get_flight_client()
        self.assertIsInstance(client, (GoogleFlightsClient, MockFlightClient))


if __name__ == "__main__":
    unittest.main()

