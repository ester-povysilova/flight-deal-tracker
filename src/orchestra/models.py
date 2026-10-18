"""Data models for Multi-Model AI Orchestra framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ClaimType(str, Enum):
    NUMERIC_PRICE = "NUMERIC_PRICE"
    STOPS_COUNT = "STOPS_COUNT"
    CABIN_CLASS = "CABIN_CLASS"
    DATE_VALUE = "DATE_VALUE"
    FORMULA_MATH = "FORMULA_MATH"
    AIRLINE_CODE = "AIRLINE_CODE"


class QCStatus(str, Enum):
    APPROVED = "APPROVED"
    REVISE = "REVISE"
    REJECTED = "REJECTED"


@dataclass
class TaskDefinition:
    """Atomic task definition dispatched to a Flash worker."""

    task_id: str
    title: str
    role: str
    instruction: str
    context_data: Dict[str, Any]
    required_keys: List[str] = field(default_factory=list)


@dataclass
class TaskResult:
    """Output produced by a worker execution unit."""

    task_id: str
    status: TaskStatus
    output: Dict[str, Any]
    evidence_citations: List[Dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0
    error_message: Optional[str] = None


@dataclass
class GroundedClaim:
    """An individual assertion extracted from model outputs and audited against ground truth."""

    claim_type: ClaimType
    statement: str
    claimed_value: Any
    ground_truth_value: Any
    source_reference: str
    is_verified: bool
    discrepancy_details: str = ""


@dataclass
class HallucinationReport:
    """Result of the deterministic zero-hallucination gatekeeper."""

    total_claims_checked: int
    verified_claims: List[GroundedClaim]
    violations: List[GroundedClaim]
    grounding_ratio: float

    @property
    def has_hallucinations(self) -> bool:
        return len(self.violations) > 0

    @property
    def summary(self) -> str:
        if not self.has_hallucinations:
            return f"PASSED: 100% Grounded ({self.total_claims_checked} claims verified against raw evidence)."
        return f"FAILED: {len(self.violations)} hallucination violations out of {self.total_claims_checked} claims."


@dataclass
class QCAuditResult:
    """Audit report produced by the QC Critic model."""

    status: QCStatus
    overall_score: float  # 0 to 100
    rubric_scores: Dict[str, float]  # category -> score
    strengths: List[str]
    violations: List[str]
    corrective_instructions: List[str]
    audit_timestamp: str

    @property
    def is_certified(self) -> bool:
        return self.status == QCStatus.APPROVED and self.overall_score >= 90.0


@dataclass
class OrchestraRunResult:
    """End-to-end telemetry and artifact produced by an Orchestra execution."""

    run_id: str
    user_goal: str
    plan_steps: List[Dict[str, Any]]
    worker_results: List[TaskResult]
    synthesized_output: Dict[str, Any]
    hallucination_report: HallucinationReport
    qc_audit: QCAuditResult
    revision_count: int
    final_approved: bool
    total_duration_ms: float
    audit_trail: List[str] = field(default_factory=list)
