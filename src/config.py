"""Configuration constants, benchmark thresholds, and route quality rules."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set, Tuple

from src.models import CabinClass


def load_env_file() -> None:
    """Lightweight zero-dependency .env loader."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'").strip('"')
                            if k not in os.environ:
                                os.environ[k] = v
                break
            except Exception:
                pass


load_env_file()


@dataclass(frozen=True)
class BenchmarkThreshold:
    """Baseline average price and deal minimum in CZK."""

    baseline_avg: float
    deal_min: float


@dataclass(frozen=True)
class DestinationRule:
    """Quality and routing constraints for a specific destination."""

    destination_code: str
    airport_codes: Set[str]
    seasonal_months: Set[int]
    min_stay_nights: int
    max_stay_nights: int
    max_stops: int
    min_layover_minutes: int = 75
    max_layover_minutes: int = 360  # 6 hours
    require_protected_ticket: bool = True


# Airport resolutions
ORIGINS: Set[str] = {"PRG", "DUB"}
DESTINATIONS: Set[str] = {"NYC", "TYO", "SCL"}

DESTINATION_RULES: Dict[str, DestinationRule] = {
    "NYC": DestinationRule(
        destination_code="NYC",
        airport_codes={"JFK", "EWR"},
        seasonal_months={4, 5, 6, 9, 10},  # April-June, September-October
        min_stay_nights=7,
        max_stay_nights=10,
        max_stops=0,  # DIRECT FLIGHTS ONLY
        min_layover_minutes=0,
        max_layover_minutes=0,
        require_protected_ticket=True,
    ),
    "TYO": DestinationRule(
        destination_code="TYO",
        airport_codes={"NRT", "HND"},
        seasonal_months={3, 4, 5, 10, 11, 12, 1},  # March-May, October-January
        min_stay_nights=14,
        max_stay_nights=21,
        max_stops=1,  # Max 1 stop
        min_layover_minutes=75,
        max_layover_minutes=360,
        require_protected_ticket=True,
    ),
    "SCL": DestinationRule(
        destination_code="SCL",
        airport_codes={"SCL"},
        seasonal_months={11, 12, 1, 2},  # November-February
        min_stay_nights=14,
        max_stay_nights=21,
        max_stops=1,  # Max 1 stop
        min_layover_minutes=75,
        max_layover_minutes=360,
        require_protected_ticket=True,
    ),
}

# Fixed benchmark price thresholds in CZK: (baseline_avg, deal_min)
# Format: BENCHMARKS[(origin, destination, cabin_class)]
BENCHMARKS: Dict[Tuple[str, str, CabinClass], BenchmarkThreshold] = {
    # NYC
    ("PRG", "NYC", CabinClass.ECONOMY): BenchmarkThreshold(13500.0, 8500.0),
    ("PRG", "NYC", CabinClass.PREMIUM_ECONOMY): BenchmarkThreshold(23000.0, 15000.0),
    ("PRG", "NYC", CabinClass.BUSINESS): BenchmarkThreshold(48000.0, 29000.0),
    ("DUB", "NYC", CabinClass.ECONOMY): BenchmarkThreshold(10500.0, 6500.0),
    ("DUB", "NYC", CabinClass.PREMIUM_ECONOMY): BenchmarkThreshold(19000.0, 12500.0),
    ("DUB", "NYC", CabinClass.BUSINESS): BenchmarkThreshold(42000.0, 26000.0),

    # TYO
    ("PRG", "TYO", CabinClass.ECONOMY): BenchmarkThreshold(19500.0, 12500.0),
    ("PRG", "TYO", CabinClass.PREMIUM_ECONOMY): BenchmarkThreshold(32000.0, 21000.0),
    ("PRG", "TYO", CabinClass.BUSINESS): BenchmarkThreshold(62000.0, 38000.0),
    ("DUB", "TYO", CabinClass.ECONOMY): BenchmarkThreshold(18500.0, 12000.0),
    ("DUB", "TYO", CabinClass.PREMIUM_ECONOMY): BenchmarkThreshold(31000.0, 20000.0),
    ("DUB", "TYO", CabinClass.BUSINESS): BenchmarkThreshold(59000.0, 36000.0),

    # SCL
    ("PRG", "SCL", CabinClass.ECONOMY): BenchmarkThreshold(24000.0, 15500.0),
    ("PRG", "SCL", CabinClass.PREMIUM_ECONOMY): BenchmarkThreshold(38000.0, 26000.0),
    ("PRG", "SCL", CabinClass.BUSINESS): BenchmarkThreshold(75000.0, 46000.0),
    ("DUB", "SCL", CabinClass.ECONOMY): BenchmarkThreshold(22500.0, 14500.0),
    ("DUB", "SCL", CabinClass.PREMIUM_ECONOMY): BenchmarkThreshold(36000.0, 25000.0),
    ("DUB", "SCL", CabinClass.BUSINESS): BenchmarkThreshold(71000.0, 44000.0),
}

# Scoring weights & thresholds
WEIGHT_PRICE = 0.40
WEIGHT_SAVINGS = 0.30
WEIGHT_TIMING = 0.30
DEAL_SCORE_THRESHOLD = 80.0

# Disallowed low-cost / budget carriers (full-service carriers only)
DISALLOWED_AIRLINES: Set[str] = {
    "N0", "NORSE", "NORSE ATLANTIC",
    "OG", "PLAY",
    "BF", "FRENCH BEE",
    "LV", "LEVEL",
    "TR", "SCOOT",
    "FR", "RYANAIR",
    "W6", "WIZZ", "WIZZ AIR",
    "U2", "EASYJET",
}

# Operational defaults
SEARCH_HORIZON_DAYS = 300
DEAL_COOLDOWN_HOURS = 48
PRICE_DROP_OVERRIDE_PERCENT = 0.03  # 3% price drop overrides cooldown
DEFAULT_EUR_TO_CZK = 25.20
