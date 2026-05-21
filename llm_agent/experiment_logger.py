"""
Structured experiment logging.

This module writes machine-readable artifacts for later evaluation while the
existing TestLogger remains the human-readable progress log.
"""

import hashlib
import json
import os
import re
import shutil
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def _safe_name(value: str, fallback: str = "unknown") -> str:
    value = value or fallback
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    value = value.strip("._-")
    return value or fallback


def _jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    return value


def _hash_parts(parts: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(part.encode("utf-8", errors="ignore"))
        digest.update(b"\n")
    return digest.hexdigest()


def summarize_widgets(widgets: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Keep widget data compact but sufficient for replay and analysis."""
    if not widgets:
        return []

    fields = (
        "text",
        "resource_id",
        "class",
        "bounds",
        "clickable",
        "enabled",
        "content_desc",
        "package",
    )
    summarized = []
    for widget in widgets:
        summarized.append({field: widget.get(field) for field in fields if field in widget})
    return summarized


def compute_structure_fingerprint(widgets: Optional[List[Dict[str, Any]]]) -> str:
    """Fingerprint layout structure without volatile visible text."""
    if not widgets:
        return ""

    parts = []
    for widget in widgets:
        parts.append("|".join([
            str(widget.get("class", "") or ""),
            str(widget.get("resource_id", "") or ""),
            str(widget.get("bounds", "") or ""),
            str(widget.get("clickable", "") or ""),
            str(widget.get("enabled", "") or ""),
        ]))
    return _hash_parts(sorted(parts))


def compute_content_fingerprint(widgets: Optional[List[Dict[str, Any]]]) -> str:
    """Fingerprint visible content and identifiers."""
    if not widgets:
        return ""

    parts = []
    for widget in widgets:
        parts.append("|".join([
            str(widget.get("text", "") or ""),
            str(widget.get("content_desc", "") or ""),
            str(widget.get("resource_id", "") or ""),
            str(widget.get("bounds", "") or ""),
        ]))
    return _hash_parts(sorted(parts))


def summarize_ui_observation(activity: str, widgets: Optional[List[Dict[str, Any]]], limit: int = 30) -> str:
    texts = []
    for widget in widgets or []:
        text = (widget.get("text") or widget.get("content_desc") or "").strip()
        if text:
            texts.append(text)
        if len(texts) >= limit:
            break
    visible = "; ".join(texts) if texts else "no visible widget text"
    return f"Activity={activity}; visible={visible}"


def parsed_action_to_dict(action: Any) -> Optional[Dict[str, Any]]:
    if action is None:
        return None

    return {
        "operation": getattr(action, "operation", None),
        "widget": getattr(action, "widget", None),
        "widget_type": getattr(action, "widget_type", None),
        "operation_widget": getattr(action, "operation_widget", None),
        "operation_widget_type": getattr(action, "operation_widget_type", None),
        "input_text": getattr(action, "input_text", None),
        "input_sequence": getattr(action, "input_sequence", None),
        "target_x": getattr(action, "target_x", None),
        "target_y": getattr(action, "target_y", None),
        "function_name": getattr(action, "function_name", None),
        "function_status": getattr(action, "function_status", None),
        "page_description": getattr(action, "page_description", None),
        "behavior_narrative": getattr(action, "behavior_narrative", None),
        "step_narrative": getattr(action, "step_narrative", None),
        "case_story_update": getattr(action, "case_story_update", None),
        "function_phase": getattr(action, "function_phase", None),
        "function_end": getattr(action, "function_end", False),
        "verification_target": getattr(action, "verification_target", None),
        "harness_events": getattr(action, "harness_events", []),
        "thought": getattr(action, "thought", None),
        "bug_detected": getattr(action, "bug_detected", False),
        "bug_description": getattr(action, "bug_description", None),
        "external_redirect": getattr(action, "external_redirect", False),
        "redirect_package": getattr(action, "redirect_package", None),
    }


class ExperimentLogger:
    """Writes run metadata, step records, event records, and bug records."""

    def __init__(
        self,
        app_name: str = "",
        package_name: str = "",
        root_dir: Path | str = Path("experiment_results"),
    ) -> None:
        self.started_at = datetime.now()
        self.app_name = app_name or "unknown_app"
        self.package_name = package_name or "unknown.package"
        suffix = _safe_name(self.package_name or self.app_name)
        self.run_id = f"run_{self.started_at.strftime('%Y%m%d_%H%M%S')}_{suffix}"
        self.run_dir = Path(root_dir) / self.run_id

        self.prompts_dir = self.run_dir / "prompts"
        self.xml_dir = self.run_dir / "xml"
        self.screenshots_dir = self.run_dir / "screenshots"
        self.reports_dir = self.run_dir / "reports"

        for directory in (
            self.run_dir,
            self.prompts_dir,
            self.xml_dir,
            self.screenshots_dir,
            self.reports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        self.meta_path = self.run_dir / "run_meta.json"
        self.steps_path = self.run_dir / "steps.jsonl"
        self.events_path = self.run_dir / "events.jsonl"
        self.bugs_path = self.run_dir / "bugs.jsonl"
        self.function_traces_path = self.run_dir / "function_traces.jsonl"

        self._steps_file = open(self.steps_path, "a", encoding="utf-8")
        self._events_file = open(self.events_path, "a", encoding="utf-8")
        self._bugs_file = open(self.bugs_path, "a", encoding="utf-8")
        self._function_traces_file = open(self.function_traces_path, "a", encoding="utf-8")
        self._meta: Dict[str, Any] = {}

        self.log_event("run_started", {
            "run_id": self.run_id,
            "app_name": self.app_name,
            "package_name": self.package_name,
            "run_dir": self.run_dir,
        })

    def write_run_meta(self, meta: Dict[str, Any]) -> None:
        self._meta.update(meta)
        self._meta.setdefault("run_id", self.run_id)
        self._meta.setdefault("started_at", self.started_at.isoformat())
        self._meta.setdefault("run_dir", str(self.run_dir.resolve()))
        self._write_json(self.meta_path, self._meta)

    def update_run_meta(self, updates: Dict[str, Any]) -> None:
        self._meta.update(updates)
        self._write_json(self.meta_path, self._meta)

    def log_step(self, record: Dict[str, Any]) -> None:
        self._write_jsonl(self._steps_file, record)

    def log_event(self, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self._write_jsonl(self._events_file, {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "payload": payload or {},
        })

    def log_bug(self, record: Dict[str, Any]) -> None:
        self._write_jsonl(self._bugs_file, {
            "timestamp": datetime.now().isoformat(),
            **record,
        })

    def log_function_trace(self, record: Dict[str, Any]) -> None:
        self._write_jsonl(self._function_traces_file, {
            "timestamp": datetime.now().isoformat(),
            **(record or {}),
        })

    def save_text_artifact(self, subdir: str, filename: str, content: str) -> str:
        directory = self.run_dir / subdir
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / _safe_name(filename, "artifact.txt")
        path.write_text(content or "", encoding="utf-8")
        return str(path.resolve())

    def copy_artifact(self, source: Any, subdir: str, filename: str) -> Optional[str]:
        if source is None:
            return None
        source_path = Path(source)
        if not source_path.exists():
            return None

        directory = self.run_dir / subdir
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / _safe_name(filename, source_path.name)
        shutil.copy2(source_path, destination)
        return str(destination.resolve())

    def close(self, summary: Optional[Dict[str, Any]] = None) -> None:
        if summary:
            self.update_run_meta({
                "ended_at": datetime.now().isoformat(),
                "summary": summary,
            })
        else:
            self.update_run_meta({"ended_at": datetime.now().isoformat()})

        self.log_event("run_finished", {"summary": summary or {}})

        for handle in (
            self._steps_file,
            self._events_file,
            self._bugs_file,
            self._function_traces_file,
        ):
            if not handle.closed:
                handle.flush()
                handle.close()

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, Any]) -> None:
        path.write_text(
            json.dumps(_jsonable(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _write_jsonl(handle, payload: Dict[str, Any]) -> None:
        handle.write(json.dumps(_jsonable(payload), ensure_ascii=False) + "\n")
        handle.flush()


def get_model_runtime_info(llm_client: Any = None) -> Dict[str, Any]:
    """Collect model configuration without leaking API keys."""
    return {
        "openai_base_url": os.environ.get("OPENAI_BASE_URL", ""),
        "openai_model": os.environ.get("OPENAI_MODEL", ""),
        "api_key_configured": bool(os.environ.get("OPENAI_API_KEY")),
        "llm_mock_mode": llm_client.is_mock_mode() if hasattr(llm_client, "is_mock_mode") else None,
    }
