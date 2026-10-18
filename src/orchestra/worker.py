"""Flash Worker execution units designed for fast, parallel execution."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from src.orchestra.llm_client import BaseLLMClient
from src.orchestra.models import TaskDefinition, TaskResult, TaskStatus


class FlashWorker:
    """Specialized Flash worker agent executing atomic subtasks with evidence tracking."""

    def __init__(self, worker_id: str, client: BaseLLMClient):
        self.worker_id = worker_id
        self.client = client

    def execute(self, task: TaskDefinition) -> TaskResult:
        start_time = time.perf_counter()
        try:
            raw_output = self.client.execute_worker_subtask(task)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            # Extract evidence citations
            citations = raw_output.pop("_evidence", [])

            # Check that required keys are present
            missing = [k for k in task.required_keys if k not in raw_output]
            if missing:
                return TaskResult(
                    task_id=task.task_id,
                    status=TaskStatus.FAILED,
                    output=raw_output,
                    evidence_citations=citations,
                    duration_ms=round(duration_ms, 2),
                    error_message=f"Worker missing required output keys: {missing}",
                )

            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.SUCCESS,
                output=raw_output,
                evidence_citations=citations,
                duration_ms=round(duration_ms, 2),
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return TaskResult(
                task_id=task.task_id,
                status=TaskStatus.FAILED,
                output={},
                evidence_citations=[],
                duration_ms=round(duration_ms, 2),
                error_message=str(e),
            )


def execute_tasks_parallel(
    tasks: List[TaskDefinition], client: BaseLLMClient, max_workers: int = 4
) -> List[TaskResult]:
    """Execute multiple Flash worker tasks concurrently."""
    results: List[TaskResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_task = {
            executor.submit(FlashWorker(task.role, client).execute, task): task
            for task in tasks
        }
        for future in as_completed(future_to_task):
            task = future_to_task[future]
            try:
                res = future.result()
                results.append(res)
            except Exception as e:
                results.append(
                    TaskResult(
                        task_id=task.task_id,
                        status=TaskStatus.FAILED,
                        output={},
                        evidence_citations=[],
                        error_message=str(e),
                    )
                )

    # Return in original task order
    task_order = {t.task_id: idx for idx, t in enumerate(tasks)}
    results.sort(key=lambda r: task_order.get(r.task_id, 0))
    return results
