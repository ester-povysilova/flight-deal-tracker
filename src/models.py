"""Data models for the Flight Deal Tracker backend service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any


class CabinClass(str, Enum):
    """Supported cabin classes."""

    ECONOMY = "ECONOMY"
    PREMIUM_ECONOMY = "PREMIUM_ECONOMY"
    BUSINESS = "BUSINESS"

    @classmethod
    def from_string(cls, value: str) -> CabinClass:
        """Normalize string to CabinClass enum."""
        v = (value or "").strip().upper().replace(" ", "_").replace("-", "_")
        if v in {"ECONOMY", "ECO", "Y", "COACH"}:
            return cls.ECONOMY
        if v in {"PREMIUM_ECONOMY", "PREMIUM", "PREM_ECO", "W"}:
            return cls.PREMIUM_ECONOMY
        if v in {"BUSINESS", "BIZ", "C", "J"}:
            return cls.BUSINESS
        # Default fallback
        try:
            return cls(v)
        except ValueError:
            return cls.ECONOMY


@dataclass
class FlightSegment:
    """A single flight leg segment (e.g. PRG -> LHR)."""

    departure_airport: str
    arrival_airport: str
    departure_time: datetime
    arrival_time: datetime
    airline_code: str
    airline_name: str
    flight_number: str
    cabin_class: CabinClass
    duration_minutes: int = 0

    @property
    def summary(self) -> str:
        dep_str = self.departure_time.strftime("%H:%M")
        arr_str = self.arrival_time.strftime("%H:%M")
        return f"{self.airline_code}{self.flight_number}: {self.departure_airport} ({dep_str}) → {self.arrival_airport} ({arr_str}) [{self.cabin_class.value}]"


@dataclass
class FlightLeg:
    """A collection of segments representing one journey direction (outbound or return)."""

    segments: list[FlightSegment]

    @property
    def departure_time(self) -> datetime:
        return self.segments[0].departure_time

    @property
    def arrival_time(self) -> datetime:
        return self.segments[-1].arrival_time

    @property
    def stops(self) -> int:
        """Number of stops/layovers."""
        return max(0, len(self.segments) - 1)

    @property
    def layover_minutes(self) -> list[int]:
        """Calculates layover duration in minutes between successive segments."""
        durations: list[int] = []
        for i in range(len(self.segments) - 1):
            curr_arr = self.segments[i].arrival_time
            next_dep = self.segments[i + 1].departure_time
            diff = int((next_dep - curr_arr).total_seconds() // 60)
            durations.append(diff)
        return durations

    @property
    def total_duration_minutes(self) -> int:
        return int((self.arrival_time - self.departure_time).total_seconds() // 60)


@dataclass
class FlightOffer:
    """Full round-trip flight offer evaluated by the system."""

    id: str
    origin: str
    destination: str
    outbound_leg: FlightLeg
    return_leg: FlightLeg
    price_czk: float
    cabin_class: CabinClass
    currency: str = "CZK"
    original_price: float | None = None
    original_currency: str | None = None
    is_self_transfer: bool = False
    google_flights_url: str = ""
    skyscanner_url: str = ""
    booking_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def departure_date(self) -> date:
        return self.outbound_leg.departure_time.date()

    @property
    def return_date(self) -> date:
        return self.return_leg.departure_time.date()

    @property
    def stay_nights(self) -> int:
        """Number of nights between departure and return departure."""
        return (self.return_date - self.departure_date).days

    @property
    def all_segments(self) -> list[FlightSegment]:
        return self.outbound_leg.segments + self.return_leg.segments

    @property
    def operating_airlines(self) -> list[str]:
        seen = set()
        result = []
        for seg in self.all_segments:
            name = seg.airline_name or seg.airline_code
            if name not in seen:
                seen.add(name)
                result.append(name)
        return result


@dataclass
class ValidationResult:
    """Outcome of validating a flight offer against destination quality rules."""

    is_valid: bool
    reason: str = ""


@dataclass
class ScoringResult:
    """Outcome of multi-factor deal scoring for an offer."""

    s_price: float
    s_savings: float
    s_timing: float
    total_score: float
    is_deal: bool
    baseline_avg: float
    deal_min: float
    savings_czk: float
    savings_percent: float

    @property
    def score_summary(self) -> str:
        status = "DEAL" if self.is_deal else "REGULAR"
        return f"[{status}] Score: {self.total_score:.1f}/100 (Price: {self.s_price:.1f}, Savings: {self.s_savings:.1f}, Timing: {self.s_timing:.1f})"
