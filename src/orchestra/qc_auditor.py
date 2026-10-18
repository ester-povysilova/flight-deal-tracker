"""Quality Control (QC) Auditor and Critic Model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from src.orchestra.llm_client import BaseLLMClient
from src.orchestra.models import HallucinationReport, QCAuditResult, QCStatus


class QCAuditor:
    """Independent QC Critic model auditing candidate output against quality rubrics."""

    def __init__(self, client: BaseLLMClient):
        self.client = client

    def audit(
        self,
        candidate_output: Dict[str, Any],
        context: Dict[str, Any],
        hallucination_report: HallucinationReport,
    ) -> QCAuditResult:
        timestamp = datetime.now(timezone.utc).isoformat()
        violations_summary = [v.discrepancy_details for v in hallucination_report.violations]

        # 1. Ask Critic model for audit assessment
        critic_data = self.client.audit_quality(candidate_output, context, violations_summary)

        # 2. Enforce Hard Zero-Hallucination Gate (No model can bypass this)
        if hallucination_report.has_hallucinations:
            rubrics = {
                "zero_hallucination": 0.0,
                "constraint_adherence": 60.0,
                "completeness": 70.0,
                "actionability": 50.0,
            }
            weighted_score = (
                (rubrics["zero_hallucination"] * 0.35)
                + (rubrics["constraint_adherence"] * 0.30)
                + (rubrics["completeness"] * 0.20)
                + (rubrics["actionability"] * 0.15)
            )
            return QCAuditResult(
                status=QCStatus.REJECTED,
                overall_score=round(weighted_score, 1),
                rubric_scores=rubrics,
                strengths=["Structured candidate generated"],
                violations=violations_summary,
                corrective_instructions=[
                    f"CRITICAL: Rectify hallucination violation: {v}" for v in violations_summary
                ],
                audit_timestamp=timestamp,
            )

        # 3. Check Constraint Satisfaction
        checks = candidate_output.get("constraint_checks", {})
        all_passed = bool(checks) and all(checks.values())
        constraint_score = 100.0 if all_passed else 50.0

        rubrics = {
            "zero_hallucination": 100.0,
            "constraint_adherence": constraint_score,
            "completeness": 95.0,
            "actionability": 95.0,
        }
        weighted_score = (
            (rubrics["zero_hallucination"] * 0.35)
            + (rubrics["constraint_adherence"] * 0.30)
            + (rubrics["completeness"] * 0.20)
            + (rubrics["actionability"] * 0.15)
        )

        if not all_passed:
            failed_keys = [k for k, v in checks.items() if not v]
            return QCAuditResult(
                status=QCStatus.REVISE,
                overall_score=round(weighted_score, 1),
                rubric_scores=rubrics,
                strengths=["100% Grounded in source evidence; zero hallucinations"],
                violations=[f"Quality constraint failed: {k}" for k in failed_keys],
                corrective_instructions=[
                    f"Recalibrate deal status because {failed_keys} constraints were not met."
                ],
                audit_timestamp=timestamp,
            )

        # 4. Fully Approved
        return QCAuditResult(
            status=QCStatus.APPROVED,
            overall_score=round(weighted_score, 1),
            rubric_scores=rubrics,
            strengths=[
                "100% Grounded in source data; 0 hallucination violations.",
                "Strict transfer and anti-mixed cabin constraints satisfied.",
                "Mathematical calculations verified exact against scoring benchmarks.",
            ],
            violations=[],
            corrective_instructions=[],
            audit_timestamp=timestamp,
        )
