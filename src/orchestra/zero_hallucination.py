"""Strict Zero-Hallucination Gatekeeper and deterministic factual verifier."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from src.orchestra.models import ClaimType, GroundedClaim, HallucinationReport


class ZeroHallucinationValidator:
    """Enforces strict zero-hallucination policy via deterministic evidence verification."""

    def __init__(self, math_tolerance: float = 0.05):
        self.math_tolerance = math_tolerance

    def audit(
        self, candidate_output: Dict[str, Any], ground_truth: Dict[str, Any]
    ) -> HallucinationReport:
        """Extract all factual assertions from candidate output and cross-verify with ground truth."""
        verified: List[GroundedClaim] = []
        violations: List[GroundedClaim] = []

        facts = candidate_output.get("factual_data", {})
        score_breakdown = candidate_output.get("score_breakdown", {})
        claimed_overall = candidate_output.get("overall_score")

        # 1. Price verification
        if "price_czk" in facts and "price_czk" in ground_truth:
            claimed_price = float(facts["price_czk"])
            actual_price = float(ground_truth["price_czk"])
            if math.isclose(claimed_price, actual_price, abs_tol=0.01):
                verified.append(
                    GroundedClaim(
                        ClaimType.NUMERIC_PRICE,
                        "Offer Price Verification",
                        claimed_price,
                        actual_price,
                        "raw_offer.price_czk",
                        True,
                    )
                )
            else:
                violations.append(
                    GroundedClaim(
                        ClaimType.NUMERIC_PRICE,
                        "Offer Price Mismatch",
                        claimed_price,
                        actual_price,
                        "raw_offer.price_czk",
                        False,
                        f"Claimed price {claimed_price} does not match raw offer price {actual_price}",
                    )
                )

        # 2. Benchmark Baseline Average verification
        if "baseline_avg" in facts and "baseline_avg" in ground_truth:
            claimed_avg = float(facts["baseline_avg"])
            actual_avg = float(ground_truth["baseline_avg"])
            if math.isclose(claimed_avg, actual_avg, abs_tol=0.01):
                verified.append(
                    GroundedClaim(
                        ClaimType.NUMERIC_PRICE,
                        "Baseline Average Verification",
                        claimed_avg,
                        actual_avg,
                        "benchmark.baseline_avg",
                        True,
                    )
                )
            else:
                violations.append(
                    GroundedClaim(
                        ClaimType.NUMERIC_PRICE,
                        "Baseline Average Mismatch",
                        claimed_avg,
                        actual_avg,
                        "benchmark.baseline_avg",
                        False,
                        f"Claimed baseline avg {claimed_avg} does not match configured benchmark {actual_avg}",
                    )
                )

        # 3. Benchmark Deal Minimum verification
        if "deal_min" in facts and "deal_min" in ground_truth:
            claimed_min = float(facts["deal_min"])
            actual_min = float(ground_truth["deal_min"])
            if math.isclose(claimed_min, actual_min, abs_tol=0.01):
                verified.append(
                    GroundedClaim(
                        ClaimType.NUMERIC_PRICE,
                        "Deal Minimum Verification",
                        claimed_min,
                        actual_min,
                        "benchmark.deal_min",
                        True,
                    )
                )
            else:
                violations.append(
                    GroundedClaim(
                        ClaimType.NUMERIC_PRICE,
                        "Deal Minimum Mismatch",
                        claimed_min,
                        actual_min,
                        "benchmark.deal_min",
                        False,
                        f"Claimed deal minimum {claimed_min} does not match configured benchmark {actual_min}",
                    )
                )

        # 4. Stay Nights verification
        if "stay_nights" in facts and "stay_nights" in ground_truth:
            claimed_stay = int(facts["stay_nights"])
            actual_stay = int(ground_truth["stay_nights"])
            if claimed_stay == actual_stay:
                verified.append(
                    GroundedClaim(
                        ClaimType.DATE_VALUE,
                        "Stay Duration Verification",
                        claimed_stay,
                        actual_stay,
                        "raw_offer.stay_nights",
                        True,
                    )
                )
            else:
                violations.append(
                    GroundedClaim(
                        ClaimType.DATE_VALUE,
                        "Stay Duration Mismatch",
                        claimed_stay,
                        actual_stay,
                        "raw_offer.stay_nights",
                        False,
                        f"Claimed stay of {claimed_stay} nights does not match flight dates ({actual_stay} nights)",
                    )
                )

        # 5. Cabin Class verification
        if "target_cabin" in facts and "cabin_class" in ground_truth:
            claimed_cabin = str(facts["target_cabin"]).upper()
            actual_cabin = str(ground_truth["cabin_class"]).upper()
            if claimed_cabin == actual_cabin:
                verified.append(
                    GroundedClaim(
                        ClaimType.CABIN_CLASS,
                        "Cabin Class Verification",
                        claimed_cabin,
                        actual_cabin,
                        "raw_offer.cabin_class",
                        True,
                    )
                )
            else:
                violations.append(
                    GroundedClaim(
                        ClaimType.CABIN_CLASS,
                        "Cabin Class Mismatch",
                        claimed_cabin,
                        actual_cabin,
                        "raw_offer.cabin_class",
                        False,
                        f"Claimed cabin '{claimed_cabin}' does not match advertised cabin '{actual_cabin}'",
                    )
                )

        # 6. Mathematical Verification: Savings Amount & Percentage
        if "price_czk" in ground_truth and "baseline_avg" in ground_truth:
            p = float(ground_truth["price_czk"])
            avg = float(ground_truth["baseline_avg"])
            min_p = float(ground_truth.get("deal_min", 0.0))

            expected_savings_czk = max(0.0, avg - p)
            expected_savings_pct = (expected_savings_czk / avg * 100.0) if avg > 0 else 0.0

            if "savings_czk" in facts:
                claimed_sav_czk = float(facts["savings_czk"])
                if math.isclose(claimed_sav_czk, expected_savings_czk, abs_tol=1.0):
                    verified.append(
                        GroundedClaim(
                            ClaimType.FORMULA_MATH,
                            "Savings (CZK) Formula Math",
                            claimed_sav_czk,
                            expected_savings_czk,
                            "(baseline_avg - price_czk)",
                            True,
                        )
                    )
                else:
                    violations.append(
                        GroundedClaim(
                            ClaimType.FORMULA_MATH,
                            "Savings (CZK) Math Error",
                            claimed_sav_czk,
                            expected_savings_czk,
                            "(baseline_avg - price_czk)",
                            False,
                            f"Math error: claimed savings {claimed_sav_czk} CZK != expected {expected_savings_czk} CZK",
                        )
                    )

            if "savings_percent" in facts:
                claimed_sav_pct = float(facts["savings_percent"])
                if math.isclose(claimed_sav_pct, expected_savings_pct, abs_tol=1.0):
                    verified.append(
                        GroundedClaim(
                            ClaimType.FORMULA_MATH,
                            "Savings (%) Formula Math",
                            claimed_sav_pct,
                            expected_savings_pct,
                            "(savings / baseline_avg * 100)",
                            True,
                        )
                    )
                else:
                    violations.append(
                        GroundedClaim(
                            ClaimType.FORMULA_MATH,
                            "Savings (%) Math Error",
                            claimed_sav_pct,
                            expected_savings_pct,
                            "(savings / baseline_avg * 100)",
                            False,
                            f"Math error: claimed savings {claimed_sav_pct}% != expected {expected_savings_pct:.1f}%",
                        )
                    )

            # 7. Mathematical Verification: S_price, S_savings, S_timing & Overall Score
            if p <= min_p:
                exp_s_price = 100.0
            elif p >= avg or avg <= min_p:
                exp_s_price = 0.0
            else:
                exp_s_price = ((avg - p) / (avg - min_p)) * 100.0
            exp_s_price = max(0.0, min(100.0, exp_s_price))

            exp_s_savings = ((avg - p) / avg * 200.0) if avg > 0 else 0.0
            exp_s_savings = max(0.0, min(100.0, exp_s_savings))

            dep_month = ground_truth.get("departure_month", 5)
            peak_months = ground_truth.get("peak_months", [4, 5, 6, 9, 10])
            exp_s_timing = 100.0 if dep_month in peak_months else 40.0

            exp_total = (exp_s_price * 0.40) + (exp_s_savings * 0.30) + (exp_s_timing * 0.30)

            if claimed_overall is not None:
                claimed_tot = float(claimed_overall)
                if math.isclose(claimed_tot, exp_total, abs_tol=self.math_tolerance):
                    verified.append(
                        GroundedClaim(
                            ClaimType.FORMULA_MATH,
                            "Overall Score Formula Math",
                            claimed_tot,
                            round(exp_total, 2),
                            "(S_price*0.4 + S_savings*0.3 + S_timing*0.3)",
                            True,
                        )
                    )
                else:
                    violations.append(
                        GroundedClaim(
                            ClaimType.FORMULA_MATH,
                            "Overall Score Math Discrepancy",
                            claimed_tot,
                            round(exp_total, 2),
                            "(S_price*0.4 + S_savings*0.3 + S_timing*0.3)",
                            False,
                            f"Math hallucination: claimed score {claimed_tot} != expected formula result {exp_total:.2f}",
                        )
                    )

        total_checked = len(verified) + len(violations)
        ratio = (len(verified) / total_checked) if total_checked > 0 else 1.0

        return HallucinationReport(
            total_claims_checked=total_checked,
            verified_claims=verified,
            violations=violations,
            grounding_ratio=round(ratio, 4),
        )
