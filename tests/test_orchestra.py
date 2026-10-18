"""Comprehensive tests for the Multi-Model AI Orchestra framework."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from src.orchestra.llm_client import MockOrchestraClient
from src.orchestra.models import (
    ClaimType,
    HallucinationReport,
    QCStatus,
    TaskDefinition,
    TaskStatus,
)
from src.orchestra.orchestrator import ThinkingOrchestrator
from src.orchestra.qc_auditor import QCAuditor
from src.orchestra.worker import FlashWorker, execute_tasks_parallel
from src.orchestra.zero_hallucination import ZeroHallucinationValidator


class TestOrchestraComponents(unittest.TestCase):
    """Unit tests for individual components of the orchestra."""

    def setUp(self):
        self.client = MockOrchestraClient()
        self.sample_context = {
            "origin": "PRG",
            "destination": "NYC",
            "cabin_class": "BUSINESS",
            "price_czk": 27500.0,
            "baseline_avg": 48000.0,
            "deal_min": 29000.0,
            "outbound_stops": 0,
            "return_stops": 0,
            "max_stops_allowed": 0,
            "segments_cabins": ["BUSINESS", "BUSINESS"],
            "departure_month": 5,
            "peak_months": [4, 5, 6, 9, 10],
            "stay_nights": 8,
            "min_stay_nights": 7,
            "max_stay_nights": 10,
            "is_self_transfer": False,
        }

    def test_thinking_orchestrator_planning(self):
        """Thinking model creates multi-step task decomposition."""
        plan = self.client.generate_plan("Evaluate NYC flight", self.sample_context)
        self.assertIsInstance(plan, list)
        self.assertGreaterEqual(len(plan), 3)
        task_roles = [p["role"] for p in plan]
        self.assertIn("RoutingSpecialist", task_roles)
        self.assertIn("CabinAuditor", task_roles)
        self.assertIn("PricingAnalyst", task_roles)

    def test_flash_worker_parallel_execution(self):
        """Flash workers execute tasks concurrently and attach evidence citations."""
        tasks = [
            TaskDefinition("T1", "Stops Check", "RoutingSpecialist", "Check stops", self.sample_context, ["route_valid"]),
            TaskDefinition("T2", "Cabin Check", "CabinAuditor", "Check cabin", self.sample_context, ["cabin_pure"]),
            TaskDefinition("T3", "Pricing Check", "PricingAnalyst", "Check pricing", self.sample_context, ["price_czk"]),
        ]
        results = execute_tasks_parallel(tasks, self.client)
        self.assertEqual(len(results), 3)
        for res in results:
            self.assertEqual(res.status, TaskStatus.SUCCESS)
            self.assertGreater(len(res.evidence_citations), 0)
            self.assertGreaterEqual(res.duration_ms, 0.0)


class TestZeroHallucinationValidator(unittest.TestCase):
    """Tests the strict factual grounding and deterministic math verifier."""

    def setUp(self):
        self.validator = ZeroHallucinationValidator()
        self.ground_truth = {
            "price_czk": 27500.0,
            "baseline_avg": 48000.0,
            "deal_min": 29000.0,
            "stay_nights": 8,
            "cabin_class": "BUSINESS",
            "departure_month": 5,
            "peak_months": [4, 5, 6, 9, 10],
        }

    def test_fully_grounded_output_passes(self):
        """Output with exact ground-truth values and correct math has 0 violations."""
        # Calculate correct math
        # price=27500 <= deal_min=29000 -> S_price=100.0
        # savings = 48000 - 27500 = 20500 CZK (42.71%)
        # S_savings = (20500/48000)*200 = 85.42
        # S_timing = 100.0
        # Total = 100*0.4 + 85.42*0.3 + 100*0.3 = 40 + 25.625 + 30 = 95.625
        valid_candidate = {
            "overall_score": 95.63,
            "factual_data": {
                "price_czk": 27500.0,
                "baseline_avg": 48000.0,
                "deal_min": 29000.0,
                "stay_nights": 8,
                "target_cabin": "BUSINESS",
                "savings_czk": 20500.0,
                "savings_percent": 42.71,
            },
        }
        report = self.validator.audit(valid_candidate, self.ground_truth)
        self.assertFalse(report.has_hallucinations)
        self.assertEqual(len(report.violations), 0)
        self.assertEqual(report.grounding_ratio, 1.0)

    def test_catches_fabricated_price(self):
        """Detects if model hallucinates a lower fake price."""
        fake_candidate = {
            "overall_score": 95.0,
            "factual_data": {
                "price_czk": 18000.0,  # Fabricated! Actual is 27500
                "baseline_avg": 48000.0,
                "deal_min": 29000.0,
                "stay_nights": 8,
                "target_cabin": "BUSINESS",
            },
        }
        report = self.validator.audit(fake_candidate, self.ground_truth)
        self.assertTrue(report.has_hallucinations)
        price_violations = [v for v in report.violations if v.claim_type == ClaimType.NUMERIC_PRICE]
        self.assertGreater(len(price_violations), 0)
        self.assertIn("does not match raw offer price", price_violations[0].discrepancy_details)

    def test_catches_math_hallucination(self):
        """Detects if model calculates wrong savings percentage or overall score."""
        wrong_math_candidate = {
            "overall_score": 80.0,  # Wrong math! Expected is ~95.6
            "factual_data": {
                "price_czk": 27500.0,
                "baseline_avg": 48000.0,
                "deal_min": 29000.0,
                "stay_nights": 8,
                "target_cabin": "BUSINESS",
                "savings_czk": 35000.0,  # Wrong math! 48000 - 27500 != 35000
                "savings_percent": 80.0,  # Wrong math!
            },
        }
        report = self.validator.audit(wrong_math_candidate, self.ground_truth)
        self.assertTrue(report.has_hallucinations)
        math_violations = [v for v in report.violations if v.claim_type == ClaimType.FORMULA_MATH]
        self.assertGreaterEqual(len(math_violations), 2)

    def test_catches_cabin_and_stay_duration_mismatch(self):
        """Detects cabin class or duration falsification."""
        mismatched_candidate = {
            "factual_data": {
                "price_czk": 27500.0,
                "baseline_avg": 48000.0,
                "deal_min": 29000.0,
                "stay_nights": 14,  # Actual is 8
                "target_cabin": "ECONOMY",  # Actual is BUSINESS
            }
        }
        report = self.validator.audit(mismatched_candidate, self.ground_truth)
        self.assertTrue(report.has_hallucinations)
        viol_types = [v.claim_type for v in report.violations]
        self.assertIn(ClaimType.CABIN_CLASS, viol_types)
        self.assertIn(ClaimType.DATE_VALUE, viol_types)


class TestQCAuditorAndSelfHealing(unittest.TestCase):
    """Tests QC Critic evaluation and orchestrator self-healing feedback loop."""

    def setUp(self):
        self.client = MockOrchestraClient()
        self.auditor = QCAuditor(self.client)
        self.validator = ZeroHallucinationValidator()
        self.context = {
            "origin": "PRG",
            "destination": "NYC",
            "cabin_class": "BUSINESS",
            "price_czk": 27500.0,
            "baseline_avg": 48000.0,
            "deal_min": 29000.0,
            "outbound_stops": 0,
            "return_stops": 0,
            "max_stops_allowed": 0,
            "segments_cabins": ["BUSINESS", "BUSINESS"],
            "departure_month": 5,
            "peak_months": [4, 5, 6, 9, 10],
            "stay_nights": 8,
            "min_stay_nights": 7,
            "max_stay_nights": 10,
            "is_self_transfer": False,
        }

    def test_qc_rejects_hallucinations(self):
        """QC Critic immediately rejects output with hallucination violations."""
        bad_candidate = {
            "factual_data": {"price_czk": 99999.0, "baseline_avg": 48000.0},
            "constraint_checks": {"route_valid": True, "cabin_pure": True, "duration_valid": True},
        }
        report = self.validator.audit(bad_candidate, self.context)
        qc_result = self.auditor.audit(bad_candidate, self.context, report)
        self.assertEqual(qc_result.status, QCStatus.REJECTED)
        self.assertFalse(qc_result.is_certified)
        self.assertEqual(qc_result.rubric_scores["zero_hallucination"], 0.0)

    def test_qc_certifies_compliant_output(self):
        """QC Critic certifies output meeting all criteria with score >= 90."""
        good_candidate = {
            "overall_score": 95.63,
            "factual_data": {
                "price_czk": 27500.0,
                "baseline_avg": 48000.0,
                "deal_min": 29000.0,
                "stay_nights": 8,
                "target_cabin": "BUSINESS",
            },
            "constraint_checks": {
                "route_valid": True,
                "cabin_pure": True,
                "duration_valid": True,
            },
        }
        report = self.validator.audit(good_candidate, self.context)
        qc_result = self.auditor.audit(good_candidate, self.context, report)
        self.assertEqual(qc_result.status, QCStatus.APPROVED)
        self.assertTrue(qc_result.is_certified)
        self.assertGreaterEqual(qc_result.overall_score, 90.0)

    def test_end_to_end_orchestrator_execution(self):
        """End-to-end run passes planning, parallel workers, verification, and QC certification."""
        orchestrator = ThinkingOrchestrator(client=self.client)
        result = orchestrator.run("Evaluate PRG-NYC Business deal", self.context)

        self.assertTrue(result.final_approved)
        self.assertEqual(result.qc_audit.status, QCStatus.APPROVED)
        self.assertFalse(result.hallucination_report.has_hallucinations)
        self.assertEqual(len(result.worker_results), 4)
        self.assertGreater(result.total_duration_ms, 0.0)
        self.assertIn("Phase 1", result.audit_trail[1])


if __name__ == "__main__":
    unittest.main()
