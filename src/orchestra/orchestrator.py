"""Thinking Orchestrator: Master planning, task delegation, synthesis, and self-healing repair loop."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from src.orchestra.llm_client import BaseLLMClient, get_orchestra_client
from src.orchestra.models import (
    HallucinationReport,
    OrchestraRunResult,
    QCAuditResult,
    QCStatus,
    TaskDefinition,
    TaskResult,
)
from src.orchestra.qc_auditor import QCAuditor
from src.orchestra.worker import execute_tasks_parallel
from src.orchestra.zero_hallucination import ZeroHallucinationValidator


class ThinkingOrchestrator:
    """Master Orchestrator powered by a Thinking model to plan, coordinate Flash workers, and enforce quality."""

    def __init__(
        self,
        client: Optional[BaseLLMClient] = None,
        max_revisions: int = 3,
    ):
        self.client = client or get_orchestra_client()
        self.max_revisions = max_revisions
        self.validator = ZeroHallucinationValidator()
        self.auditor = QCAuditor(self.client)

    def run(self, user_goal: str, context_data: Dict[str, Any]) -> OrchestraRunResult:
        run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
        start_time = time.perf_counter()
        audit_trail: List[str] = [f"[{run_id}] Initiated run with goal: '{user_goal}'"]

        # Phase 1: Thinking Model Plan Formulation
        audit_trail.append("[Phase 1] Thinking Orchestrator formulating execution plan...")
        raw_plan = self.client.generate_plan(user_goal, context_data)
        tasks = [
            TaskDefinition(
                task_id=p["task_id"],
                title=p["title"],
                role=p["role"],
                instruction=p["instruction"],
                context_data=context_data,
                required_keys=p.get("required_keys", []),
            )
            for p in raw_plan
        ]
        audit_trail.append(f"[Phase 1] Plan generated: {len(tasks)} atomic subtasks.")

        # Phase 2: Parallel Flash Worker Execution
        audit_trail.append(f"[Phase 2] Dispatching {len(tasks)} subtasks to parallel Flash workers...")
        worker_results = execute_tasks_parallel(tasks, self.client)
        successful_workers = sum(1 for w in worker_results if w.status.value == "SUCCESS")
        audit_trail.append(f"[Phase 2] Completed Flash worker execution: {successful_workers}/{len(tasks)} succeeded.")

        # Phase 3: Synthesis by Thinking Orchestrator
        audit_trail.append("[Phase 3] Thinking Orchestrator synthesizing worker findings into candidate output...")
        worker_outputs = [w.output for w in worker_results]
        candidate = self.client.synthesize_results(user_goal, raw_plan, worker_outputs)

        # Phase 4 & 5: Zero-Hallucination Gate & QC Audit Loop
        revisions = 0
        hallucination_report: HallucinationReport = self.validator.audit(candidate, context_data)
        qc_audit: QCAuditResult = self.auditor.audit(candidate, context_data, hallucination_report)

        audit_trail.append(f"[Phase 4] Zero-Hallucination Audit: {hallucination_report.summary}")
        audit_trail.append(f"[Phase 5] Initial QC Audit: {qc_audit.status.value} (Score: {qc_audit.overall_score}/100)")

        # Self-Healing Revision Loop if rejected or revisions required
        while not qc_audit.is_certified and revisions < self.max_revisions:
            revisions += 1
            feedback = qc_audit.violations + qc_audit.corrective_instructions
            audit_trail.append(
                f"[Self-Healing Loop {revisions}/{self.max_revisions}] Applying corrective feedback: {feedback}"
            )
            candidate = self.client.revise_synthesis(candidate, feedback, context_data)

            # Re-verify
            hallucination_report = self.validator.audit(candidate, context_data)
            qc_audit = self.auditor.audit(candidate, context_data, hallucination_report)
            audit_trail.append(
                f"[Self-Healing Loop {revisions}] New QC Result: {qc_audit.status.value} (Score: {qc_audit.overall_score}/100)"
            )

        duration_ms = (time.perf_counter() - start_time) * 1000.0
        final_approved = qc_audit.is_certified

        audit_trail.append(
            f"[Completion] Final Status: {'APPROVED & CERTIFIED' if final_approved else 'REJECTED'} in {duration_ms:.1f}ms."
        )

        return OrchestraRunResult(
            run_id=run_id,
            user_goal=user_goal,
            plan_steps=raw_plan,
            worker_results=worker_results,
            synthesized_output=candidate,
            hallucination_report=hallucination_report,
            qc_audit=qc_audit,
            revision_count=revisions,
            final_approved=final_approved,
            total_duration_ms=round(duration_ms, 2),
            audit_trail=audit_trail,
        )
