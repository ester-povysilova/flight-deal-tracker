"""CLI Demonstration runner for the Multi-Model AI Orchestra."""

from __future__ import annotations

import argparse
import json
import sys

from src.orchestra.orchestrator import ThinkingOrchestrator


def run_orchestra_demo() -> None:
    print("\n" + "=" * 70)
    print("🎻  STARTING THE MULTI-MODEL AI ORCHESTRA DEMO")
    print("=" * 70)

    # Sample realistic context: PRG -> NYC Business Deal
    sample_context = {
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

    user_goal = "Evaluate Prague to New York Delta Business class flight deal for May 2027"

    orchestrator = ThinkingOrchestrator()
    print(f"\n[Goal] {user_goal}")
    print("[Orchestrator] Model: Thinking / Pro (Deep Planning & Synthesis)")
    print("[Workers]      Model: Flash (Fast Parallel Execution)")
    print("[Guardrail]    Engine: Deterministic Zero-Hallucination Gatekeeper")
    print("[QC Auditor]   Model: Critic (Rubric-based Certification)")
    print("-" * 70)

    result = orchestrator.run(user_goal, sample_context)

    print("\n📋 EXECUTION TRACE:")
    for step in result.audit_trail:
        print(f"  {step}")

    print("\n⚡ PARALLEL FLASH WORKER OUTPUTS:")
    for w in result.worker_results:
        print(f"  • [{w.task_id}] Status: {w.status.value} ({w.duration_ms:.1f}ms)")
        for cit in w.evidence_citations:
            print(f"      Citation: {cit['claim']} (from {cit['source']})")

    print("\n🛡️ ZERO-HALLUCINATION AUDIT REPORT:")
    print(f"  Total Claims Verified: {result.hallucination_report.total_claims_checked}")
    print(f"  Grounding Ratio:       {result.hallucination_report.grounding_ratio * 100:.1f}%")
    print(f"  Hallucinations Found:  {len(result.hallucination_report.violations)}")
    print(f"  Status Summary:        {result.hallucination_report.summary}")

    print("\n🔍 QUALITY CONTROL (QC) SCORECARD:")
    print(f"  QC Decision:   {result.qc_audit.status.value}")
    print(f"  Quality Score: {result.qc_audit.overall_score}/100")
    print("  Rubric Breakdown:")
    for rubric, val in result.qc_audit.rubric_scores.items():
        print(f"    - {rubric.replace('_', ' ').title()}: {val:.1f} pts")

    print("\n🏆 FINAL SYNTHESIZED RESULT:")
    print(json.dumps(result.synthesized_output, indent=2))

    status_str = "CERTIFIED & APPROVED ✅" if result.final_approved else "REJECTED ❌"
    print(f"\nFinal Verdict: {status_str} (Completed in {result.total_duration_ms:.1f}ms)")
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Multi-Model AI Orchestra Runner")
    parser.add_argument("--demo", action="store_true", help="Run simulated end-to-end demonstration")
    args = parser.parse_args()

    run_orchestra_demo()


if __name__ == "__main__":
    main()
