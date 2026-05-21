"""
Evidence-grounded behavior dossier management.

The dossier is a compact, auditable reconstruction of the current functional
flow. Explorer writes the narrative layer; this manager binds it to raw
execution evidence so the Supervisor can review the whole behavior chain.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


FUNCTION_PHASES = {
    "start",
    "exploring",
    "inputting",
    "committing",
    "verifying",
    "completed",
    "blocked",
}

COMMIT_TERMS = (
    "save", "submit", "confirm", "book", "place order", "checkout", "add",
    "create", "send", "apply", "done", "finish", "reserve", "pay",
)

VERIFY_TERMS = (
    "success", "confirmation", "confirmed", "result", "summary", "details",
    "history", "list", "my", "order", "orders", "appointment",
    "appointments", "trip", "trips",
)

def _compact_text(value: Any, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def normalize_phase(value: Any) -> str:
    phase = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return phase if phase in FUNCTION_PHASES else "exploring"


def normalize_behavior_narrative(value: Any) -> Dict[str, Any]:
    """Normalize Explorer narrative into a predictable dictionary."""
    if isinstance(value, dict):
        return dict(value)
    if value in (None, "", "null", "None"):
        return {}
    return {"narrative": str(value)}


def normalize_step_narrative(value: Any) -> Dict[str, Any]:
    """Normalize the v2 per-step narrative schema."""
    return normalize_behavior_narrative(value)


def normalize_case_story_update(value: Any) -> Dict[str, Any]:
    """Normalize Explorer's cumulative story update."""
    if isinstance(value, dict):
        allowed_fields = {
            "case_story_so_far",
            "story_so_far",
            "new_event",
            "verified_facts",
            "hypotheses",
            "contradiction_candidates",
        }
        return {str(key): val for key, val in value.items() if key in allowed_fields}
    if value in (None, "", "null", "None"):
        return {}
    return {"case_story_so_far": str(value)}


def _as_list(value: Any) -> List[Any]:
    if value in (None, "", "null", "None"):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _compact_list(value: Any, item_limit: int = 180, max_items: int = 12) -> List[str]:
    return [_compact_text(item, item_limit) for item in _as_list(value)[:max_items] if _compact_text(item, item_limit)]


def _append_unique(values: List[Any], value: Any) -> None:
    if value in (None, "", "null", "None"):
        return
    text = str(value)
    if text not in values:
        values.append(text)


def _narrative_text(narrative: Dict[str, Any]) -> str:
    if not narrative:
        return ""
    parts: List[str] = []
    for key in (
        "current_scene",
        "visible_evidence",
        "past_context_used",
        "current_goal",
        "decision_rationale",
        "chosen_action",
        "action_purpose",
        "uncertainty",
        "narrative",
    ):
        value = narrative.get(key)
        if isinstance(value, list):
            value = "; ".join(str(item) for item in value)
        if value:
            parts.append(f"{key}: {value}")
    return " | ".join(parts)


@dataclass
class TriggerEvaluation:
    should_review: bool
    score: int
    reasons: List[str] = field(default_factory=list)
    phase_signal: bool = False
    cooldown_ok: bool = True
    min_steps_ok: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "should_review": self.should_review,
            "score": self.score,
            "reasons": self.reasons,
            "phase_signal": self.phase_signal,
            "cooldown_ok": self.cooldown_ok,
            "min_steps_ok": self.min_steps_ok,
        }


class BehaviorDossierManager:
    """Maintain an active evidence-grounded behavior dossier."""

    def __init__(
        self,
        min_trace_steps: int = 2,
        min_review_gap: int = 2,
        trigger_threshold: int = 4,
    ) -> None:
        self.min_trace_steps = min_trace_steps
        self.min_review_gap = min_review_gap
        self.trigger_threshold = trigger_threshold
        self._trace_counter = 0
        self.active_trace: Optional[Dict[str, Any]] = None
        self.archived_traces: List[Dict[str, Any]] = []
        self.last_trigger_evaluation: Optional[TriggerEvaluation] = None

    def set_pending_verification(self, text: str, target: str = "") -> None:
        if not self.active_trace:
            return
        self.active_trace["pending_verification"] = {
            "text": _compact_text(text, 360),
            "target": _compact_text(target, 160),
            "timestamp": datetime.now().isoformat(),
        }

    def format_for_prompt(self) -> str:
        """Render the active dossier as a concise continuation prompt."""
        if not self.active_trace or not self.active_trace.get("steps"):
            return (
                "## Behavior Dossier\n"
                "No active dossier yet. Start Case story so far as a numbered Step 1 paragraph "
                "for the current user-facing function, with detailed visible UI evidence, "
                "decision rationale summary, chosen action, predicted observable result, "
                "and any remaining verification need."
            )

        trace = self.active_trace
        global_story = trace.get("global_story") or {}
        lines = [
            "## Behavior Dossier",
            "Continue this evidence-grounded behavior dossier. Rewrite Case story so far as numbered Step N paragraphs from the beginning of this function flow through the current step; do not merely append a short sentence.",
            "Each Step paragraph must include the Activity/screen, detailed visible UI state, key fields/lists/buttons/overlays/dialogs/empty/error/loading states, evidence used, decision rationale summary, chosen action, predicted observable result, and remaining verification need when relevant.",
            f"- Trace: {trace.get('trace_id')} | Goal: {_compact_text(trace.get('function_goal'), 140) or 'unknown'} | Phase: {trace.get('phase', 'exploring')}",
        ]

        story = _compact_text(global_story.get("case_story_so_far"), 2400)
        if story:
            lines.append(f"- Case story so far: {story}")

        labels_seen = _compact_list(trace.get("function_labels_seen"), 120, 10)
        if labels_seen:
            lines.append("- Function labels seen: " + " | ".join(labels_seen))

        activities_seen = _compact_list(trace.get("activities_seen"), 120, 10)
        if activities_seen:
            lines.append("- Activities seen as evidence: " + " | ".join(activities_seen))

        verified_facts = _compact_list(global_story.get("verified_facts"), 160, 8)
        if verified_facts:
            lines.append("- Verified facts: " + " | ".join(verified_facts))

        hypotheses = _compact_list(global_story.get("hypotheses"), 160, 6)
        if hypotheses:
            lines.append("- Hypotheses: " + " | ".join(hypotheses))

        contradictions = _compact_list(global_story.get("contradiction_candidates"), 160, 6)
        if contradictions:
            lines.append("- Contradiction candidates: " + " | ".join(contradictions))

        pending = trace.get("pending_verification") or {}
        if pending:
            target = pending.get("target") or "related result/history/list page"
            lines.append(f"- Pending verification: {_compact_text(pending.get('text'), 220)} Target: {_compact_text(target, 120)}")

        lines.append("- Recent dossier events:")
        for step in trace.get("steps", [])[-5:]:
            narrative = step.get("step_narrative") or step.get("behavior_narrative") or {}
            scene = _compact_text(narrative.get("current_scene") or narrative.get("scene") or narrative.get("narrative"), 220)
            rationale = _compact_text(narrative.get("decision_rationale"), 140)
            action = step.get("action") or {}
            target = action.get("operation_widget") or action.get("widget") or step.get("target_widget") or "N/A"
            lines.append(
                f"- Step {step.get('step_index')}: {action.get('operation') or 'unknown'} -> {target}; "
                f"phase={step.get('function_phase')}; scene={scene or 'not stated'}; "
                f"rationale={rationale or 'not stated'}"
            )

        lines.append(
            "For your next JSON response, produce Step_Narrative and Case_Story_Update. current_scene must be detailed and evidence-only. case_story_so_far must preserve the numbered Step N paragraph format and include entity details inside the prose. Separate verified_facts from hypotheses."
        )
        return "\n".join(lines)

    def append_step(
        self,
        step_index: int,
        action: Any,
        activity_before: str,
        activity_after: str = "",
        step_record: Optional[Dict[str, Any]] = None,
        widgets_before: Optional[List[Dict[str, Any]]] = None,
        widgets_after: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        step_record = step_record or {}
        action_dict = self._action_to_dict(action)
        step_narrative = normalize_step_narrative(
            action_dict.get("step_narrative") or action_dict.get("behavior_narrative")
        )
        narrative = step_narrative
        case_story_update = normalize_case_story_update(action_dict.get("case_story_update"))
        phase = normalize_phase(action_dict.get("function_phase") or step_record.get("action_phase"))
        candidate_goal = (
            step_narrative.get("current_goal")
            or case_story_update.get("current_goal")
            or action_dict.get("function_name")
            or (self.active_trace or {}).get("function_goal")
            or activity_before
        )

        if self._should_start_new_trace(phase):
            self._start_trace(function_goal=candidate_goal, function_name=action_dict.get("function_name"))
        elif not self.active_trace:
            self._start_trace(function_goal=candidate_goal, function_name=action_dict.get("function_name"))

        trace = self.active_trace
        if trace.get("start_step") is None:
            trace["start_step"] = step_index
        trace["phase"] = phase
        if not trace.get("function_goal"):
            trace["function_goal"] = _compact_text(candidate_goal, 240)
        if not trace.get("function_name"):
            trace["function_name"] = action_dict.get("function_name")
        _append_unique(trace.setdefault("function_labels_seen", []), action_dict.get("function_name"))
        _append_unique(trace.setdefault("activities_seen", []), activity_before)
        _append_unique(trace.setdefault("activities_seen", []), activity_after)
        trace["end_step"] = step_index
        if action_dict.get("verification_target"):
            trace["verification_target"] = action_dict.get("verification_target")
        self._update_global_story(case_story_update, step_narrative)

        step_entry = {
            "step_index": step_index,
            "timestamp": datetime.now().isoformat(),
            "activity_before": activity_before,
            "activity_after": activity_after,
            "step_narrative": step_narrative,
            "case_story_update": case_story_update,
            "behavior_narrative": narrative,
            "function_phase": phase,
            "function_end": bool(action_dict.get("function_end")),
            "verification_target": action_dict.get("verification_target"),
            "page_description": action_dict.get("page_description"),
            "function_label": action_dict.get("function_name"),
            "action": action_dict,
            "target_widget": action_dict.get("operation_widget") or action_dict.get("widget"),
            "ui_changed": bool(step_record.get("ui_changed")),
            "activity_changed": bool(step_record.get("activity_changed")),
            "structure_fingerprint_before": step_record.get("structure_fingerprint_before"),
            "structure_fingerprint_after": step_record.get("structure_fingerprint_after"),
            "content_fingerprint_before": step_record.get("content_fingerprint_before"),
            "content_fingerprint_after": step_record.get("content_fingerprint_after"),
            "actual_observation": step_record.get("actual_observation"),
            "xml_before_path": step_record.get("xml_before_path"),
            "xml_after_path": step_record.get("xml_after_path"),
            "screenshot_before_path": step_record.get("screenshot_before_path"),
            "screenshot_after_path": step_record.get("screenshot_after_path"),
            "widgets_before": widgets_before or step_record.get("widgets_before") or [],
            "widgets_after": widgets_after or step_record.get("widgets_after") or [],
            "action_phase": step_record.get("action_phase"),
            "transient_transition": step_record.get("transient_transition"),
            "back_effect": step_record.get("back_effect"),
        }
        trace["steps"].append(_jsonable(step_entry))
        trace["last_updated_at"] = datetime.now().isoformat()

        if action_dict.get("verification_target") or phase in {"verifying", "completed", "blocked"}:
            self.set_pending_verification(
                action_dict.get("verification_target") or "",
            )

        self.last_trigger_evaluation = self.evaluate_trigger()
        trace["last_trigger_evaluation"] = self.last_trigger_evaluation.to_dict()
        return step_entry

    def evaluate_trigger(self) -> TriggerEvaluation:
        if not self.active_trace or not self.active_trace.get("steps"):
            return TriggerEvaluation(False, 0, min_steps_ok=False)

        trace = self.active_trace
        steps = trace.get("steps", [])
        latest = steps[-1]
        action = latest.get("action") or {}
        text_parts = [
            action.get("operation"),
            action.get("widget"),
            action.get("operation_widget"),
            latest.get("actual_observation"),
            latest.get("activity_before"),
            latest.get("activity_after"),
            latest.get("verification_target"),
            _narrative_text(latest.get("step_narrative") or latest.get("behavior_narrative") or {}),
            (trace.get("global_story") or {}).get("case_story_so_far"),
        ]
        text = _norm(" ".join(str(part or "") for part in text_parts))

        score = 0
        reasons: List[str] = []

        commit_signal = any(term in text for term in COMMIT_TERMS)
        verification_signal = any(term in text for term in VERIFY_TERMS)

        if commit_signal:
            score += 2
            reasons.append("commit_action_signal")
        if verification_signal:
            score += 2
            reasons.append("verification_page_signal")

        phase = latest.get("function_phase")
        function_end = bool(latest.get("function_end"))
        llm_phase_signal = phase in {"verifying", "completed", "blocked"} or function_end
        phase_signal = llm_phase_signal
        if llm_phase_signal:
            score += 2
            reasons.append("llm_phase_or_end_signal")
        elif commit_signal and verification_signal:
            phase_signal = True
            score += 2
            reasons.append("commit_reached_verification_page_signal")

        if latest.get("ui_changed") or latest.get("activity_changed"):
            score += 1
            reasons.append("state_changed")

        if phase == "blocked" or self._recent_repeated_no_change():
            score += 2
            reasons.append("blocked_or_repeated_no_change")

        min_steps_ok = len(steps) >= self.min_trace_steps
        last_review_step = trace.get("last_review_step")
        cooldown_ok = last_review_step is None or (
            latest.get("step_index", 0) - int(last_review_step)
        ) >= self.min_review_gap
        should_review = (
            min_steps_ok
            and cooldown_ok
            and score >= self.trigger_threshold
            and phase_signal
        )
        return TriggerEvaluation(should_review, score, reasons, phase_signal, cooldown_ok, min_steps_ok)

    def build_review_context(self) -> Dict[str, Any]:
        trace = self.active_trace or {}
        evaluation = self.last_trigger_evaluation or self.evaluate_trigger()
        return {
            "active_trace": self.to_dict(),
            "trace_id": trace.get("trace_id"),
            "function_goal": trace.get("function_goal"),
            "phase": trace.get("phase"),
            "global_story": trace.get("global_story"),
            "verification_target": trace.get("verification_target"),
            "pending_verification": trace.get("pending_verification"),
            "trigger_evaluation": evaluation.to_dict(),
            "behavior_chain_summary": self.format_for_review(),
        }

    def format_for_review(self) -> str:
        if not self.active_trace:
            return "No active behavior dossier."
        trace = self.active_trace
        lines = [
            f"Trace {trace.get('trace_id')} goal: {trace.get('function_goal') or 'unknown'}",
            f"Current phase: {trace.get('phase') or 'unknown'}",
        ]
        global_story = trace.get("global_story") or {}
        if global_story.get("case_story_so_far"):
            lines.append(f"Case story so far: {_compact_text(global_story.get('case_story_so_far'), 3000)}")
        labels_seen = _compact_list(trace.get("function_labels_seen"), 120, 20)
        if labels_seen:
            lines.append("Function labels seen: " + " | ".join(labels_seen))
        activities_seen = _compact_list(trace.get("activities_seen"), 120, 20)
        if activities_seen:
            lines.append("Activities seen as evidence: " + " | ".join(activities_seen))
        for label, key in (
            ("Verified facts", "verified_facts"),
            ("Hypotheses", "hypotheses"),
            ("Contradiction candidates", "contradiction_candidates"),
        ):
            values = _compact_list(global_story.get(key), 220, 12)
            if values:
                lines.append(f"{label}: " + " | ".join(values))
        pending = trace.get("pending_verification") or {}
        if pending:
            lines.append(f"Pending verification: {pending.get('text') or ''} Target: {pending.get('target') or ''}")
        for step in trace.get("steps", []):
            action = step.get("action") or {}
            narrative = step.get("step_narrative") or step.get("behavior_narrative") or {}
            lines.append(
                "\n".join([
                    f"Step {step.get('step_index')} [{step.get('activity_before')} -> {step.get('activity_after') or step.get('activity_before')}]",
                    f"- Action: {action.get('operation') or 'unknown'} -> {action.get('operation_widget') or action.get('widget') or 'N/A'}",
                    f"- Phase: {step.get('function_phase')} end={step.get('function_end')}",
                    f"- Scene: {_compact_text(narrative.get('current_scene') or narrative.get('scene') or narrative.get('narrative'), 360)}",
                    f"- Visible evidence claimed: {_compact_text(narrative.get('visible_evidence'), 260)}",
                    f"- Past context used: {_compact_text(narrative.get('past_context_used'), 220)}",
                    f"- Rationale/action purpose: {_compact_text(narrative.get('decision_rationale'), 220)} / {_compact_text(narrative.get('action_purpose') or narrative.get('chosen_action'), 220)}",
                    f"- Actual observation: {_compact_text(step.get('actual_observation'), 220)}",
                    f"- Evidence paths: screenshot_before={step.get('screenshot_before_path')}; screenshot_after={step.get('screenshot_after_path')}; xml_after={step.get('xml_after_path')}",
                ])
            )
        return "\n".join(lines)

    def apply_review_result(self, review_result: Dict[str, Any], step_index: int) -> None:
        if not self.active_trace:
            return
        verdict = str(review_result.get("verdict") or "").strip().lower()
        review = {
            "step_index": step_index,
            "timestamp": datetime.now().isoformat(),
            **_jsonable(review_result),
        }
        self.active_trace.setdefault("reviews", []).append(review)
        self.active_trace["last_review_step"] = step_index
        if verdict == "needs_more_verification":
            self.set_pending_verification(
                review_result.get("reason") or "More verification is needed.",
                review_result.get("verification_target") or self.active_trace.get("verification_target") or "",
            )
            return
        if verdict in {"bug", "no_bug"} and self._latest_step_is_terminal():
            self.active_trace["completed"] = True

    def archive_if_completed(self) -> None:
        if self.active_trace and self.active_trace.get("completed"):
            self.archived_traces.append(self.active_trace)
            self.active_trace = None

    def to_dict(self) -> Dict[str, Any]:
        return _jsonable(self.active_trace or {})

    def _start_trace(self, function_goal: str, function_name: Optional[str] = None) -> None:
        self._trace_counter += 1
        self.active_trace = {
            "trace_id": f"trace_{self._trace_counter:03d}",
            "function_goal": _compact_text(function_goal, 240),
            "function_name": function_name,
            "function_labels_seen": _compact_list([function_name], 240, 20),
            "activities_seen": [],
            "phase": "start",
            "start_step": None,
            "end_step": None,
            "steps": [],
            "reviews": [],
            "global_story": {
                "case_story_so_far": "",
                "verified_facts": [],
                "hypotheses": [],
                "contradiction_candidates": [],
                "last_new_event": "",
            },
            "pending_verification": {},
            "verification_target": "",
            "last_review_step": None,
            "completed": False,
            "created_at": datetime.now().isoformat(),
        }

    def _should_start_new_trace(self, phase: str) -> bool:
        if not self.active_trace:
            return True
        if self.active_trace.get("completed"):
            return True
        return False

    def _latest_step_is_terminal(self) -> bool:
        steps = (self.active_trace or {}).get("steps", [])
        if not steps:
            return False
        latest = steps[-1]
        return bool(latest.get("function_end")) or latest.get("function_phase") in {"completed", "blocked"}

    def _recent_repeated_no_change(self) -> bool:
        steps = (self.active_trace or {}).get("steps", [])
        if len(steps) < 3:
            return False
        recent = steps[-3:]
        return all(not step.get("ui_changed") and not step.get("activity_changed") for step in recent)

    def _update_global_story(
        self,
        case_story_update: Dict[str, Any],
        step_narrative: Dict[str, Any],
    ) -> None:
        """Apply Explorer's latest cumulative story."""
        if not self.active_trace:
            return

        trace = self.active_trace
        story = trace.setdefault("global_story", {
            "case_story_so_far": "",
            "verified_facts": [],
            "hypotheses": [],
            "contradiction_candidates": [],
            "last_new_event": "",
        })

        if not case_story_update:
            scene = step_narrative.get("current_scene") or step_narrative.get("scene") or step_narrative.get("narrative")
            if scene and not story.get("case_story_so_far"):
                story["case_story_so_far"] = _compact_text(scene, 2400)
            return

        case_story = case_story_update.get("case_story_so_far") or case_story_update.get("story_so_far")
        if case_story not in (None, "", "null", "None"):
            story["case_story_so_far"] = _compact_text(case_story, 6000)

        new_event = case_story_update.get("new_event")
        if new_event not in (None, "", "null", "None"):
            story["last_new_event"] = _compact_text(new_event, 800)

        # These lists represent Explorer's current cumulative story state. When
        # present, replace the old value so stale hypotheses can be cleared.
        for key in (
            "verified_facts",
            "hypotheses",
            "contradiction_candidates",
        ):
            if key in case_story_update:
                story[key] = _jsonable(_as_list(case_story_update.get(key)))

    @staticmethod
    def _action_to_dict(action: Any) -> Dict[str, Any]:
        if action is None:
            return {}
        if isinstance(action, dict):
            return dict(action)
        return {
            "operation": getattr(action, "operation", None),
            "widget": getattr(action, "widget", None),
            "operation_widget": getattr(action, "operation_widget", None),
            "input_text": getattr(action, "input_text", None),
            "function_name": getattr(action, "function_name", None),
            "function_status": getattr(action, "function_status", None),
            "page_description": getattr(action, "page_description", None),
            "behavior_narrative": getattr(action, "behavior_narrative", None),
            "step_narrative": getattr(action, "step_narrative", None),
            "case_story_update": getattr(action, "case_story_update", None),
            "function_phase": getattr(action, "function_phase", None),
            "function_end": getattr(action, "function_end", False),
            "verification_target": getattr(action, "verification_target", None),
            "bug_detected": getattr(action, "bug_detected", False),
            "bug_description": getattr(action, "bug_description", None),
        }
