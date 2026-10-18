"""LLM Client interfaces for Thinking, Flash, and QC models with mock and live options."""

from __future__ import annotations

import abc
import json
import os
from typing import Any, Dict, List, Optional

from src.orchestra.models import TaskDefinition


class BaseLLMClient(abc.ABC):
    """Abstract interface for multi-model interactions."""

    @abc.abstractmethod
    def generate_plan(self, goal: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Thinking model decomposes a goal into structured subtasks."""
        raise NotImplementedError

    @abc.abstractmethod
    def execute_worker_subtask(self, task: TaskDefinition) -> Dict[str, Any]:
        """Flash model executes an atomic subtask with evidence citations."""
        raise NotImplementedError

    @abc.abstractmethod
    def synthesize_results(
        self, goal: str, plan: List[Dict[str, Any]], worker_outputs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Thinking model synthesizes all worker findings into candidate output."""
        raise NotImplementedError

    @abc.abstractmethod
    def audit_quality(
        self, candidate: Dict[str, Any], context: Dict[str, Any], violations: List[str]
    ) -> Dict[str, Any]:
        """QC Critic model performs rubric audit and issues approval or feedback."""
        raise NotImplementedError

    @abc.abstractmethod
    def revise_synthesis(
        self, candidate: Dict[str, Any], feedback: List[str], ground_truth: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Thinking model repairs candidate output based on QC/Hallucination feedback."""
        raise NotImplementedError


class MockOrchestraClient(BaseLLMClient):
    """Deterministic, high-fidelity mock client simulating Thinking, Flash, and QC models."""

    def generate_plan(self, goal: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            {
                "task_id": "T1-ROUTING",
                "title": "Validate Transfer & Layover Rules",
                "role": "RoutingSpecialist",
                "instruction": "Assert destination stops constraints (NYC max 0, TYO/SCL max 1) and connection bounds (75m-6h).",
                "required_keys": ["route_valid", "stops_count", "layover_minutes", "transfer_type"],
            },
            {
                "task_id": "T2-CABIN",
                "title": "Audit Segment Cabin Strictness",
                "role": "CabinAuditor",
                "instruction": "Enforce anti-mixed cabin rule: every segment must match advertised Business/Premium class.",
                "required_keys": ["cabin_pure", "target_cabin", "segment_cabins", "feeder_disqualified"],
            },
            {
                "task_id": "T3-PRICING",
                "title": "Evaluate Pricing & Savings",
                "role": "PricingAnalyst",
                "instruction": "Compare price against baseline average and deal minimum; compute exact savings percentage.",
                "required_keys": ["price_czk", "baseline_avg", "deal_min", "savings_percent", "savings_czk"],
            },
            {
                "task_id": "T4-CALENDAR",
                "title": "Verify Seasonality & Stay Duration",
                "role": "CalendarAuditor",
                "instruction": "Check departure month against destination seasonal window and check stay duration.",
                "required_keys": ["is_peak_season", "stay_nights", "min_nights", "max_nights", "duration_valid"],
            },
        ]

    def execute_worker_subtask(self, task: TaskDefinition) -> Dict[str, Any]:
        ctx = task.context_data
        role = task.role

        if role == "RoutingSpecialist":
            out_stops = ctx.get("outbound_stops", 0)
            ret_stops = ctx.get("return_stops", 0)
            max_allowed = ctx.get("max_stops_allowed", 0)
            layovers = ctx.get("layover_minutes", [])
            is_valid = (out_stops <= max_allowed and ret_stops <= max_allowed)
            return {
                "route_valid": is_valid,
                "stops_count": {"outbound": out_stops, "return": ret_stops},
                "layover_minutes": layovers,
                "transfer_type": "PROTECTED_SINGLE_TICKET" if not ctx.get("is_self_transfer") else "SELF_TRANSFER",
                "_evidence": [
                    {"claim": f"outbound stops = {out_stops}", "source": "outbound_stops", "value": out_stops},
                    {"claim": f"max allowed = {max_allowed}", "source": "max_stops_allowed", "value": max_allowed},
                ],
            }

        elif role == "CabinAuditor":
            target = ctx.get("cabin_class", "ECONOMY")
            segments = ctx.get("segments_cabins", [target])
            is_pure = all(s == target for s in segments)
            disqualified = (target in {"BUSINESS", "PREMIUM_ECONOMY"} and not is_pure)
            return {
                "cabin_pure": is_pure,
                "target_cabin": target,
                "segment_cabins": segments,
                "feeder_disqualified": disqualified,
                "_evidence": [
                    {"claim": f"target cabin is {target}", "source": "cabin_class", "value": target},
                    {"claim": f"all segments match: {is_pure}", "source": "segments_cabins", "value": segments},
                ],
            }

        elif role == "PricingAnalyst":
            price = float(ctx.get("price_czk", 0.0))
            avg = float(ctx.get("baseline_avg", 0.0))
            deal_min = float(ctx.get("deal_min", 0.0))
            savings_czk = max(0.0, avg - price)
            savings_pct = (savings_czk / avg * 100.0) if avg > 0 else 0.0
            return {
                "price_czk": price,
                "baseline_avg": avg,
                "deal_min": deal_min,
                "savings_czk": round(savings_czk, 2),
                "savings_percent": round(savings_pct, 2),
                "_evidence": [
                    {"claim": f"price is {price}", "source": "price_czk", "value": price},
                    {"claim": f"baseline avg is {avg}", "source": "baseline_avg", "value": avg},
                    {"claim": f"deal minimum is {deal_min}", "source": "deal_min", "value": deal_min},
                ],
            }

        elif role == "CalendarAuditor":
            dep_month = ctx.get("departure_month", 5)
            peak_months = ctx.get("peak_months", [4, 5, 6, 9, 10])
            stay = ctx.get("stay_nights", 8)
            min_stay = ctx.get("min_stay_nights", 7)
            max_stay = ctx.get("max_stay_nights", 10)
            is_peak = dep_month in peak_months
            dur_valid = min_stay <= stay <= max_stay
            return {
                "is_peak_season": is_peak,
                "stay_nights": stay,
                "min_nights": min_stay,
                "max_nights": max_stay,
                "duration_valid": dur_valid,
                "_evidence": [
                    {"claim": f"departure month {dep_month}", "source": "departure_month", "value": dep_month},
                    {"claim": f"stay nights {stay}", "source": "stay_nights", "value": stay},
                ],
            }

        return {"status": "UNKNOWN_ROLE"}

    def synthesize_results(
        self, goal: str, plan: List[Dict[str, Any]], worker_outputs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for w in worker_outputs:
            for k, v in w.items():
                if k != "_evidence":
                    merged[k] = v

        # Calculate exact formula
        price = merged.get("price_czk", 0.0)
        avg = merged.get("baseline_avg", 0.0)
        deal_min = merged.get("deal_min", 0.0)
        is_peak = merged.get("is_peak_season", True)

        if price <= deal_min:
            s_price = 100.0
        elif price >= avg or avg <= deal_min:
            s_price = 0.0
        else:
            s_price = ((avg - price) / (avg - deal_min)) * 100.0
        s_price = max(0.0, min(100.0, s_price))

        s_savings = ((avg - price) / avg * 200.0) if avg > 0 else 0.0
        s_savings = max(0.0, min(100.0, s_savings))

        s_timing = 100.0 if is_peak else 40.0
        total_score = (s_price * 0.40) + (s_savings * 0.30) + (s_timing * 0.30)

        all_rules_passed = (
            merged.get("route_valid", False)
            and not merged.get("feeder_disqualified", False)
            and merged.get("duration_valid", False)
        )

        return {
            "summary": f"Orchestrated Deal Evaluation: Score {total_score:.1f}/100",
            "is_certified_deal": total_score >= 80.0 and all_rules_passed,
            "overall_score": round(total_score, 2),
            "score_breakdown": {
                "s_price": round(s_price, 2),
                "s_savings": round(s_savings, 2),
                "s_timing": round(s_timing, 2),
            },
            "factual_data": {
                "price_czk": price,
                "baseline_avg": avg,
                "deal_min": deal_min,
                "savings_czk": round(merged.get("savings_czk", 0.0), 2),
                "savings_percent": round(merged.get("savings_percent", 0.0), 2),
                "stay_nights": merged.get("stay_nights", 0),
                "target_cabin": merged.get("target_cabin", "ECONOMY"),
            },
            "constraint_checks": {
                "route_valid": merged.get("route_valid", False),
                "cabin_pure": merged.get("cabin_pure", True),
                "duration_valid": merged.get("duration_valid", False),
            },
        }

    def audit_quality(
        self, candidate: Dict[str, Any], context: Dict[str, Any], violations: List[str]
    ) -> Dict[str, Any]:
        if violations:
            return {
                "status": "REJECTED",
                "overall_score": 45.0,
                "rubric_scores": {
                    "zero_hallucination": 0.0,
                    "constraint_adherence": 60.0,
                    "completeness": 70.0,
                    "actionability": 50.0,
                },
                "strengths": ["Structured schema provided"],
                "violations": violations,
                "corrective_instructions": [f"Fix hallucination: {v}" for v in violations],
            }

        # Check constraint satisfaction
        checks = candidate.get("constraint_checks", {})
        if not all(checks.values()):
            failed_keys = [k for k, v in checks.items() if not v]
            return {
                "status": "REVISE",
                "overall_score": 75.0,
                "rubric_scores": {
                    "zero_hallucination": 100.0,
                    "constraint_adherence": 50.0,
                    "completeness": 80.0,
                    "actionability": 70.0,
                },
                "strengths": ["Zero hallucination violations detected"],
                "violations": [f"Constraint check failed: {k}" for k in failed_keys],
                "corrective_instructions": [f"Adjust offer evaluation to respect {failed_keys}"],
            }

        return {
            "status": "APPROVED",
            "overall_score": 98.0,
            "rubric_scores": {
                "zero_hallucination": 100.0,
                "constraint_adherence": 100.0,
                "completeness": 95.0,
                "actionability": 95.0,
            },
            "strengths": [
                "Zero hallucination violations detected; 100% ground-truth grounded.",
                "Strict anti-mixed cabin and transfer rules fully verified.",
                "Scoring engine formula mathematically exact.",
            ],
            "violations": [],
            "corrective_instructions": [],
        }

    def revise_synthesis(
        self, candidate: Dict[str, Any], feedback: List[str], ground_truth: Dict[str, Any]
    ) -> Dict[str, Any]:
        revised = dict(candidate)
        facts = revised.setdefault("factual_data", {})

        # Fix any specific ground truth discrepancies identified in feedback
        for k, v in ground_truth.items():
            if k in facts:
                facts[k] = v

        # Recalculate score with corrected ground truth
        price = facts.get("price_czk", 0.0)
        avg = facts.get("baseline_avg", 0.0)
        deal_min = facts.get("deal_min", 0.0)

        facts["savings_czk"] = round(max(0.0, avg - price), 2)
        facts["savings_percent"] = round((facts["savings_czk"] / avg * 100.0), 2) if avg > 0 else 0.0

        if price <= deal_min:
            s_price = 100.0
        elif price >= avg:
            s_price = 0.0
        else:
            s_price = ((avg - price) / (avg - deal_min)) * 100.0
        s_price = max(0.0, min(100.0, s_price))

        s_savings = max(0.0, min(100.0, (facts["savings_czk"] / avg * 200.0))) if avg > 0 else 0.0
        s_timing = 100.0
        total_score = (s_price * 0.40) + (s_savings * 0.30) + (s_timing * 0.30)

        revised["overall_score"] = round(total_score, 2)
        revised["score_breakdown"] = {
            "s_price": round(s_price, 2),
            "s_savings": round(s_savings, 2),
            "s_timing": round(s_timing, 2),
        }
        revised["summary"] = f"Orchestrated Deal Evaluation (Repaired): Score {total_score:.1f}/100"
        return revised


class GeminiLiveClient(BaseLLMClient):
    """Live Google Gemini API client utilizing Thinking and Flash models."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        self.thinking_model = "gemini-2.0-flash-thinking-exp-01-21"
        self.flash_model = "gemini-2.0-flash"

    def _call_gemini(self, model: str, prompt: str, system_instruction: str = "") -> str:
        # Standard urllib implementation calling Google Generative Language API
        import urllib.request
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def generate_plan(self, goal: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        sys_prompt = "You are a master lead orchestrator. Decompose the flight deal tracking goal into atomic tasks for Flash workers. Output JSON list."
        prompt = f"Goal: {goal}\nContext: {json.dumps(context)}"
        resp = self._call_gemini(self.thinking_model, prompt, sys_prompt)
        return json.loads(resp)

    def execute_worker_subtask(self, task: TaskDefinition) -> Dict[str, Any]:
        sys_prompt = f"You are a specialized Flash worker ({task.role}). Execute the task with strict zero-hallucination. Cite every claim in _evidence. Output JSON."
        prompt = f"Instruction: {task.instruction}\nContext: {json.dumps(task.context_data)}"
        resp = self._call_gemini(self.flash_model, prompt, sys_prompt)
        return json.loads(resp)

    def synthesize_results(
        self, goal: str, plan: List[Dict[str, Any]], worker_outputs: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        sys_prompt = "You are the Lead Thinking Orchestrator. Synthesize worker findings into a final candidate response. Output JSON."
        prompt = f"Goal: {goal}\nPlan: {json.dumps(plan)}\nWorker Outputs: {json.dumps(worker_outputs)}"
        resp = self._call_gemini(self.thinking_model, prompt, sys_prompt)
        return json.loads(resp)

    def audit_quality(
        self, candidate: Dict[str, Any], context: Dict[str, Any], violations: List[str]
    ) -> Dict[str, Any]:
        sys_prompt = "You are the QC Auditor. Evaluate candidate against zero-hallucination policy and quality rubric. Output JSON with status, overall_score (0-100), rubric_scores, violations, corrective_instructions."
        prompt = f"Candidate: {json.dumps(candidate)}\nContext: {json.dumps(context)}\nViolations: {json.dumps(violations)}"
        resp = self._call_gemini(self.thinking_model, prompt, sys_prompt)
        return json.loads(resp)

    def revise_synthesis(
        self, candidate: Dict[str, Any], feedback: List[str], ground_truth: Dict[str, Any]
    ) -> Dict[str, Any]:
        sys_prompt = "You are the Lead Thinking Orchestrator. Repair the candidate output according to the QC feedback and ground truth. Output JSON."
        prompt = f"Candidate: {json.dumps(candidate)}\nFeedback: {json.dumps(feedback)}\nGround Truth: {json.dumps(ground_truth)}"
        resp = self._call_gemini(self.thinking_model, prompt, sys_prompt)
        return json.loads(resp)


def get_orchestra_client() -> BaseLLMClient:
    """Return live Gemini client if API key configured, otherwise high-fidelity Mock client."""
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if key and key.strip():
        return GeminiLiveClient(api_key=key.strip())
    return MockOrchestraClient()
