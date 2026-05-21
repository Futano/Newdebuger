"""
GPTDroid 娴嬭瘯鍏ュ彛 - Outer Loop 涓荤▼搴?
瀹炵幇 LLM 鍏ㄨ嚜涓婚┍鍔ㄧ殑鑷姩鍖栨祴璇曟帰绱?

瀹屾暣娴佺▼锛?
1. 娓呯┖鏃ュ織缂撳啿鍖猴紝鍑嗗宕╂簝妫€娴?
2. 寰幆鎵ц鎺㈢储姝ラ锛屾瘡姝ョ敱 LLM 瀹屽叏鑷富鍐崇瓥锛?
   a. ADB 鐜浜や簰灞?- 鎶撳彇 UI 甯冨眬
   b. GUI 涓婁笅鏂囨彁鍙栧眰 - 瑙ｆ瀽 UI 鎺т欢
   c. 鑾峰彇褰撳墠 Activity 鍚嶇О
   d. 澶фā鍨嬫彁绀鸿瘝鏋勫缓灞?- 鐢熸垚 Test Prompt锛堝惈璁板繂锛?
   e. 澶фā鍨嬩氦浜掑眰 - 鑾峰彇 LLM 鍐崇瓥
   f. 鍔ㄤ綔鎵ц灞?- 鎵ц鎿嶄綔骞舵娴嬪穿婧?
   g. 鐘舵€佸樊鍒嗘娴?- 楠岃瘉鍔ㄤ綔鏄惁鏈夋晥
   h. 璁板繂鏇存柊 - 璁板綍娴嬭瘯鍘嗗彶锛堝惈鏁堟灉鍙嶉锛?
3. 杈撳嚭娴嬭瘯鎬荤粨鎶ュ憡
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Dict, Optional, Tuple
from pathlib import Path


def _load_env_file(path: str = ".env", override: bool = True) -> None:
    """Load simple KEY=VALUE pairs from .env before clients read env vars."""
    env_path = Path(path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value


_load_env_file()

from env_interactor import ADBController, ActionExecutor
from gui_extractor import (
    GUIAnalyzer,
    ManifestParser,
    analyze_ui_state,
    classify_back_effect,
    classify_action_phase,
    format_ui_state_for_prompt,
    transient_transition,
)
from llm_agent import BehaviorDossierManager, PromptGenerator, TestingSequenceMemorizer, UserContext  # NEW: UserContext
from llm_agent.supervisor import SupervisorModel
from llm_agent.bug_analysis_engine import (
    BugAnalysisEngine,
    BugReport,
    BugSeverity,
    BugCategory,
    normalize_bug_category,
)  # NEW: Bug 鎶ュ憡绫诲瀷
from llm_agent.multimodal_llm_client import MultimodalLLMClient  # NEW: 澶氭ā鎬?LLM
from llm_agent.screenshot_manager import ScreenshotManager, ScreenshotData  # NEW: 鎴浘绠＄悊
from llm_agent.exploration_cache import ExplorationCache
from llm_agent.test_logger import get_logger, reset_logger
from llm_agent.experiment_logger import (
    ExperimentLogger,
    compute_content_fingerprint,
    compute_structure_fingerprint,
    get_model_runtime_info,
    parsed_action_to_dict,
    summarize_ui_observation,
    summarize_widgets,
)


# ==================== 閰嶇疆鍙傛暟 ====================
MAX_STEPS = 300           # 鏈€澶ф帰绱㈡鏁?
STEP_WAIT_TIME = 1   # 姣忔鎿嶄綔鍚庣殑绛夊緟鏃堕棿锛堢锛?
UI_DUMP_RETRY_ATTEMPTS = 5
UI_DUMP_RETRY_INITIAL_DELAY = 0.5
UI_DUMP_RETRY_DELAY_STEP = 0.5
AUTO_HIDE_KEYBOARD_AFTER_INPUT = (
    os.getenv("AUTO_HIDE_KEYBOARD_AFTER_INPUT", "1").strip().lower()
    not in {"0", "false", "no", "off"}
)


def _safe_git_commit() -> str:
    """Return current git commit if available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _safe_adb_shell(adb_controller: ADBController, command: str) -> str:
    """Run a simple adb shell command and return stdout."""
    try:
        result = adb_controller._execute_shell(command, timeout=5)
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _collect_device_info(adb_controller: ADBController) -> Dict:
    return {
        "device_id": adb_controller.device_id or "default",
        "android_version": _safe_adb_shell(adb_controller, "getprop ro.build.version.release"),
        "sdk": _safe_adb_shell(adb_controller, "getprop ro.build.version.sdk"),
        "model": _safe_adb_shell(adb_controller, "getprop ro.product.model"),
        "manufacturer": _safe_adb_shell(adb_controller, "getprop ro.product.manufacturer"),
    }


def _collect_package_info(adb_controller: ADBController, package_name: str) -> Dict:
    apk_path = ""
    if package_name:
        apk_path = _safe_adb_shell(adb_controller, f"pm path {package_name}")
    return {
        "package_name": package_name,
        "device_apk_path": apk_path,
    }


def _finish_experiment_step(
    experiment_logger: ExperimentLogger,
    step_record: Dict,
    status: str,
    error: str = None,
) -> None:
    """Finalize a step record exactly once."""
    if not experiment_logger or step_record.get("_logged"):
        return

    step_record["status"] = status
    step_record["ended_at"] = datetime.now().isoformat()
    if error:
        step_record["error"] = error
    step_record.pop("_logged", None)
    experiment_logger.log_step(step_record)
    step_record["_logged"] = True


def _copy_bug_report_paths(bug_id: str, experiment_logger: ExperimentLogger) -> Dict:
    copied = {}
    if not bug_id or not experiment_logger:
        return copied

    for suffix, key in ((".json", "report_json_path"), (".md", "report_md_path")):
        source = Path("bug_reports") / f"{bug_id}{suffix}"
        copied_path = experiment_logger.copy_artifact(source, "reports", source.name)
        if copied_path:
            copied[key] = copied_path
    return copied


def _save_supervisor_artifacts(
    experiment_logger: ExperimentLogger,
    supervisor: SupervisorModel,
    step_index: int,
    label: str
) -> Dict:
    """Persist the latest Supervisor system prompt, review prompt, and response."""
    if not experiment_logger or not supervisor:
        return {}

    artifacts = supervisor.get_last_review_artifacts()
    if not artifacts:
        return {}

    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", label or artifacts.get("review_type", "review"))
    prefix = f"step_{step_index:03d}_supervisor_{safe_label}"
    paths = {
        "supervisor_system_prompt_path": experiment_logger.save_text_artifact(
            "prompts",
            f"{prefix}_system_prompt.txt",
            artifacts.get("system_prompt", ""),
        ),
        "supervisor_prompt_path": experiment_logger.save_text_artifact(
            "prompts",
            f"{prefix}_prompt.txt",
            artifacts.get("prompt", ""),
        ),
        "supervisor_response_path": experiment_logger.save_text_artifact(
            "prompts",
            f"{prefix}_response.txt",
            artifacts.get("response", ""),
        ),
    }
    paths["supervisor_review_index"] = artifacts.get("review_index")
    paths["supervisor_review_type"] = artifacts.get("review_type")
    return paths


def _map_bug_severity(value: str) -> BugSeverity:
    value = str(value or "").strip().lower()
    severity_map = {
        "critical": BugSeverity.CRITICAL,
        "error": BugSeverity.ERROR,
        "warning": BugSeverity.WARNING,
        "info": BugSeverity.INFO,
    }
    return severity_map.get(value, BugSeverity.ERROR)


def _map_bug_category(value: str) -> BugCategory:
    return normalize_bug_category(value)


def _normalize_for_policy(value: str) -> str:
    """Normalize text used by deterministic bug severity policy."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _history_text_for_policy(operation_history: list, max_items: int = 8) -> str:
    """Flatten recent operation history into a compact text signal."""
    if not operation_history:
        return ""

    parts = []
    for entry in operation_history[-max_items:]:
        parts.extend([
            entry.get("activity_name", ""),
            entry.get("operation", ""),
            entry.get("target_widget", ""),
            entry.get("action_phase", ""),
        ])
    return _normalize_for_policy(" ".join(str(part or "") for part in parts))


def _has_committed_user_data(history_text: str, current_text: str) -> bool:
    commit_terms = (
        "book", "booking", "booked", "reserve", "reservation", "reserved",
        "place order", "placed order", "order placed", "confirm", "confirmed",
        "checkout", "submit", "submitted", "save", "saved", "pay", "payment",
        "purchase", "complete", "completed",
    )
    combined = f"{history_text} {current_text}"
    return any(term in combined for term in commit_terms)


def _looks_like_missing_committed_record(history_text: str, current_text: str) -> bool:
    domain_terms = (
        "order", "orders", "history", "trip", "trips", "flight", "booking",
        "reservation", "cart", "checkout", "list",
    )
    missing_terms = (
        "missing", "not appear", "not appearing", "does not appear",
        "not displayed", "not shown", "empty", "no orders", "no order",
        "no upcoming", "no trips", "no records", "not listed", "lost",
        "data loss",
    )
    combined = f"{history_text} {current_text}"
    return (
        any(term in combined for term in domain_terms)
        and any(term in combined for term in missing_terms)
        and _has_committed_user_data(history_text, current_text)
    )


def _normalize_bug_severity(
    raw_severity: str,
    category: BugCategory,
    description: str = "",
    activity: str = "",
    operation: str = "",
    widget: str = "",
    operation_history: list = None,
    action_phase: str = "",
    evidence: str = "",
) -> BugSeverity:
    """
    Convert model-proposed severity into a deterministic experiment severity.

    The model may still propose a severity, but experiment statistics should not
    depend on wording drift across runs.
    """
    raw = _map_bug_severity(raw_severity)
    current_text = _normalize_for_policy(
        " ".join([
            description,
            activity,
            operation,
            widget,
            action_phase,
            evidence,
        ])
    )
    history_text = _history_text_for_policy(operation_history or [])

    if category == BugCategory.CRASH:
        return BugSeverity.CRITICAL

    if category == BugCategory.DATA_INCONSISTENCY:
        if _looks_like_missing_committed_record(history_text, current_text):
            return BugSeverity.CRITICAL
        if "data loss" in current_text or "lost" in current_text:
            return BugSeverity.CRITICAL
        if any(term in current_text for term in ("might", "possible", "potential", "needs verification")):
            return BugSeverity.WARNING
        return BugSeverity.ERROR

    if category == BugCategory.CALCULATION_ERROR:
        return BugSeverity.ERROR

    if category == BugCategory.FUNCTION_ANOMALY:
        if any(term in current_text for term in ("blocked", "cannot proceed", "unusable", "no response", "nothing happened")):
            return BugSeverity.ERROR
        return BugSeverity.ERROR

    if category == BugCategory.UI_STATE_ERROR:
        if any(term in current_text for term in ("blocked", "cannot proceed", "unusable", "obscured", "covered", "not clickable")):
            return BugSeverity.ERROR
        if any(term in current_text for term in ("layout", "overlap", "toast", "dropdown", "keyboard", "focus", "visible", "hidden", "disabled", "enabled", "z index", "zindex")):
            return BugSeverity.WARNING
        return BugSeverity.WARNING

    return raw


def _make_bug_id(source: str = "") -> str:
    suffix = re.sub(r"[^A-Za-z0-9]+", "", source or "")
    base = datetime.now().strftime("BUG-%Y%m%d-%H%M%S-%f")[:-3]
    return f"{base}-{suffix}" if suffix else base


def _find_duplicate_reported_bug(
    memory_manager,
    category: str,
    activity: str,
    description: str,
    operation: str = "",
    widget: str = "",
) -> str:
    """Return an existing bug id when the new report is likely the same issue."""
    def normalize(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()

    def bug_id_candidates(bug_id: str) -> list:
        bug_id = str(bug_id or "").strip()
        if not bug_id:
            return []

        candidates = [bug_id]
        parts = bug_id.split("-")
        # Internal ids append the source suffix (for example, "-explorer").
        # The model often refers only to the stable BUG-yyyyMMdd-HHmmss-ms prefix.
        if len(parts) > 1 and not parts[-1].isdigit():
            candidates.append("-".join(parts[:-1]))
        return candidates

    new_text = normalize(description)
    if not new_text:
        return ""

    new_tokens = set(new_text.split())
    for bug in memory_manager.get_reported_bugs(50):
        bug_id = bug.get("bug_id", "")
        for candidate in bug_id_candidates(bug_id):
            raw_candidate = str(candidate).lower()
            normalized_candidate = normalize(candidate)
            if raw_candidate and raw_candidate in str(description or "").lower():
                return bug_id
            if normalized_candidate and normalized_candidate in new_text:
                return bug_id

        old_text = normalize(bug.get("description", ""))
        if not old_text:
            continue

        same_category = not category or not bug.get("category") or category == bug.get("category")
        same_activity = not activity or not bug.get("activity") or activity == bug.get("activity")
        same_operation = not operation or not bug.get("operation") or operation == bug.get("operation")
        same_widget = not widget or not bug.get("widget") or normalize(widget) == normalize(bug.get("widget", ""))

        if new_text in old_text or old_text in new_text:
            if same_category or same_activity:
                return bug_id

        old_tokens = set(old_text.split())
        if new_tokens and old_tokens:
            overlap = len(new_tokens & old_tokens) / max(len(new_tokens), len(old_tokens))
            if same_category and same_activity and overlap >= 0.65:
                return bug_id
            if same_activity and same_widget and overlap >= 0.45:
                return bug_id
            if same_activity and same_operation and overlap >= 0.55:
                return bug_id

    return ""


def _short_text(value, limit: int = 120) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def _dump_ui_with_retry(
    adb_controller: ADBController,
    *,
    context: str,
    logger=None,
    attempts: int = UI_DUMP_RETRY_ATTEMPTS,
    initial_delay: float = UI_DUMP_RETRY_INITIAL_DELAY,
    delay_step: float = UI_DUMP_RETRY_DELAY_STEP,
) -> Tuple[Optional[Path], int]:
    """Dump UI with short in-step retries to absorb transient UIAutomator failures."""
    attempts = max(1, int(attempts))

    for attempt in range(1, attempts + 1):
        ui_file = adb_controller.dump_ui()
        if ui_file:
            if attempt > 1:
                message = f"UI dump recovered on attempt {attempt}/{attempts} ({context})"
                print(f"[UI dump retry] {message}")
                if logger:
                    logger.log(message, "INFO")
            return ui_file, attempt

        if attempt < attempts:
            delay = initial_delay + delay_step * (attempt - 1)
            reason = _short_text(getattr(adb_controller, "last_ui_dump_error", ""), 180)
            message = (
                f"UI dump failed on attempt {attempt}/{attempts} ({context}); "
                f"retrying in {delay:.1f}s"
                f"{' | reason: ' + reason if reason else ''}"
            )
            print(f"[UI dump retry] {message}")
            if logger:
                logger.log(message, "WARN")
            time.sleep(delay)

    reason = _short_text(getattr(adb_controller, "last_ui_dump_error", ""), 180)
    message = (
        f"UI dump failed after {attempts} attempts ({context})"
        f"{' | reason: ' + reason if reason else ''}"
    )
    print(f"[UI dump retry] {message}")
    if logger:
        logger.log(message, "WARN")
    return None, attempts


def _format_action_summary(action) -> str:
    if not action:
        return "parse failed"

    operation = action.operation or "unknown"
    widget = _action_history_target(action) or "N/A"
    function_name = action.function_name or "unknown_function"
    return f"{function_name} | {operation} -> {widget}"


def _action_history_target(action) -> str:
    """Return the user-visible target that best represents the completed action."""
    if not action:
        return ""

    operation_widget = getattr(action, "operation_widget", None)
    has_input = bool(getattr(action, "input_sequence", None) or getattr(action, "input_text", None))
    if operation_widget and has_input:
        return operation_widget

    return getattr(action, "widget", None) or operation_widget or ""


def _safe_log_name(value: str) -> str:
    name = (value or "unknown_app").strip()
    name = re.sub(r'[<>:"/\\|?*\s]+', "_", name)
    name = re.sub(r"[\x00-\x1f]+", "", name)
    return name.strip("._") or "unknown_app"


def _make_run_log_path(app_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = Path("temp_data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{_safe_log_name(app_name)}_{timestamp}.log"


def _append_unique_widget(widgets_tested: list, widget_name: str, current_activity: str, memory_manager) -> None:
    """Append a widget visit record once, preserving prompt/debug readability."""
    if not widget_name:
        return
    if any(item.get("name") == widget_name for item in widgets_tested):
        return
    widgets_tested.append({
        "name": widget_name,
        "visits": memory_manager.get_widget_visits(current_activity).get(widget_name, 0)
    })


def _elapsed_seconds(run_started_perf: float) -> float:
    """Return elapsed seconds from the autonomous testing timer."""
    if not run_started_perf:
        return 0.0
    return round(max(0.0, time.perf_counter() - run_started_perf), 3)


def _build_bug_timing_record(
    run_started_perf: float,
    step_index: int,
    bug_id: str,
    detected_by: str,
    source: str,
    supervisor_verdict: str,
    is_false_positive: bool,
    category: str,
    severity: str,
    activity: str,
    operation: str,
    widget: str,
    description: str,
    confidence=None,
    asserted_elapsed_seconds=None,
) -> Dict:
    elapsed = _elapsed_seconds(run_started_perf)
    asserted_elapsed = elapsed if asserted_elapsed_seconds is None else round(float(asserted_elapsed_seconds), 3)
    return {
        "detected_at": datetime.now().isoformat(),
        "elapsed_seconds": elapsed,
        "elapsed_minutes": round(elapsed / 60, 3),
        "asserted_elapsed_seconds": asserted_elapsed,
        "asserted_elapsed_minutes": round(asserted_elapsed / 60, 3),
        "step_index": step_index,
        "step_count_to_detection": step_index,
        "bug_id": bug_id,
        "detected_by": detected_by,
        "source": source,
        "supervisor_verdict": supervisor_verdict,
        "is_true_positive": not bool(is_false_positive),
        "is_false_positive": bool(is_false_positive),
        "category": category,
        "severity": severity,
        "activity": activity,
        "operation": operation,
        "widget": widget,
        "description": _short_text(description, 240),
        "confidence": confidence,
    }


def _record_bug_metric(
    results: Dict,
    experiment_logger: ExperimentLogger,
    timing_record: Dict,
) -> None:
    """Store time-to-bug metrics in memory and the structured event log."""
    if not timing_record:
        return

    results.setdefault("bug_timeline", []).append(timing_record)
    detection_elapsed = timing_record.get("asserted_elapsed_seconds", timing_record.get("elapsed_seconds"))
    results["last_bug_elapsed_seconds"] = detection_elapsed
    results["last_bug_step"] = timing_record.get("step_index")

    if results.get("first_bug_elapsed_seconds") is None:
        results["first_bug_elapsed_seconds"] = detection_elapsed
        results["first_bug_step"] = timing_record.get("step_index")
        results["first_bug_id"] = timing_record.get("bug_id")
        results["first_bug_is_true_positive"] = timing_record.get("is_true_positive")

    if timing_record.get("is_true_positive"):
        results["true_positive_count"] = results.get("true_positive_count", 0) + 1
        if results.get("first_true_bug_elapsed_seconds") is None:
            results["first_true_bug_elapsed_seconds"] = detection_elapsed
            results["first_true_bug_step"] = timing_record.get("step_index")
            results["first_true_bug_id"] = timing_record.get("bug_id")
    else:
        results["false_positive_count"] = results.get("false_positive_count", 0) + 1
        if results.get("first_false_positive_elapsed_seconds") is None:
            results["first_false_positive_elapsed_seconds"] = detection_elapsed
            results["first_false_positive_step"] = timing_record.get("step_index")
            results["first_false_positive_id"] = timing_record.get("bug_id")

    if experiment_logger:
        experiment_logger.log_event("bug_detection_metric", timing_record)


def _is_non_terminating_visual_state_bug(
    category: str,
    severity: str,
    description: str = "",
    evidence: str = "",
    current_widgets: list = None,
) -> bool:
    """Return True for non-blocking visual-state mismatch reports."""
    if (category or "").lower() != BugCategory.UI_STATE_ERROR.value:
        return False
    if (severity or "").lower() == BugSeverity.CRITICAL.value.lower():
        return False

    text = f"{description or ''} {evidence or ''}".lower()
    visual_terms = (
        "visual", "style", "looks disabled", "look disabled", "appears disabled",
        "grey", "gray", "greyed", "grayed", "low contrast", "disabled-looking",
        "misleading", "state mismatch", "visual-state",
    )
    disabled_terms = ("disabled", "enablement", "enabled", "clickable", "button")
    if not any(term in text for term in visual_terms):
        return False
    if not any(term in text for term in disabled_terms):
        return False

    widgets = current_widgets or []
    if not widgets:
        return True

    for widget in widgets:
        class_name = (widget.get("class") or "").lower()
        if "button" not in class_name:
            continue
        if widget.get("enabled") is True and widget.get("clickable") is True:
            return True

    return False


# ==================== 浜や簰寮忚緭鍏ュ嚱鏁?====================

def get_user_input(default_app_name: str = "") -> UserContext:
    """
    鑾峰彇鐢ㄦ埛杈撳叆鐨勬祴璇曚笂涓嬫枃淇℃伅

    Args:
        default_app_name: 榛樿搴旂敤鍚嶇О锛堜粠 Manifest 瑙ｆ瀽锛?

    Returns:
        UserContext: 鐢ㄦ埛杈撳叆鐨勪笂涓嬫枃淇℃伅
    """
    print("\n" + "=" * 60)
    print("  娴嬭瘯閰嶇疆")
    print("=" * 60)

    # 1. 搴旂敤鍚嶇О
    default_display = default_app_name or "鏈煡搴旂敤"
    app_name_input = input(f"搴旂敤鍚嶇О [{default_display}]: ").strip()
    app_name = app_name_input if app_name_input else default_app_name

    # 2. 鐢ㄦ埛鑷畾涔夎鏄庯紙涓€鍙ヨ瘽锛?
    print("\n璇疯緭鍏ユ祴璇曡鏄庯紙鍙€夛紝鐩存帴鍥炶溅璺宠繃锛?")
    print("渚嬪: 閲嶇偣娴嬭瘯鐧诲綍鍜屾敮浠樺姛鑳?")
    user_note = input("> ").strip()

    # 鏋勫缓骞惰繑鍥炵敤鎴蜂笂涓嬫枃
    user_context = UserContext(
        app_name=app_name,
        user_note=user_note
    )

    # 鏄剧ず閰嶇疆鎽樿
    print("\n" + "-" * 60)
    print(f"搴旂敤: {user_context.app_name}")
    if user_context.user_note:
        print(f"璇存槑: {user_context.user_note}")
    print("-" * 60)

    return user_context


def _handle_llm_bug_report(
    components,
    parsed_action,
    current_activity: str,
    screenshot_data,
    step_result: Dict,
    results: Dict,
    supervisor,
    memory_manager,
    experiment_logger: ExperimentLogger = None,
    bug_analysis_engine: BugAnalysisEngine = None,
    step_index: int = 0,
    ui_state: Dict = None,
    ui_state_prompt: str = "",
    current_widgets: list = None,
    run_started_perf: float = 0.0,
) -> bool:
    """
    澶勭悊 LLM 鎶ュ憡鐨?Bug锛堥泦鎴愮洃绠¤€呭鏌ワ級

    褰?parsed_action.bug_detected == True 鏃惰Е鍙戯紝鏆傚仠娴嬭瘯寰幆锛?
    鐢辩洃绠¤€呭鏌?Bug 鐨勭湡瀹炴€с€?

    Args:
        components: 娴嬭瘯缁勪欢闆嗗悎锛堝寘鍚?bug_analysis_engine 绛夛級
        parsed_action: 瑙ｆ瀽鍚庣殑鍔ㄤ綔锛屽寘鍚?bug_description
        current_activity: 褰撳墠 Activity
        screenshot_data: 褰撳墠鎴浘鏁版嵁
        step_result: 姝ラ缁撴灉瀛楀吀
        results: 娴嬭瘯缁撴灉姹囨€诲瓧鍏?
        supervisor: 鐩戠鑰呮ā鍨嬪疄渚?
        memory_manager: 璁板繂绠＄悊鍣ㄥ疄渚?

    Returns:
        bool: True 琛ㄧず搴旂粓姝㈡祴璇曪紝False 琛ㄧず缁х画娴嬭瘯
    """
    from datetime import datetime as dt

    bug_desc = parsed_action.bug_description or {}
    bug_type = bug_desc.get("type", "unknown")
    bug_severity = bug_desc.get("severity", "Error")
    bug_message = bug_desc.get("description", "Bug detected by LLM")

    print(f"\n{'!' * 60}")
    print(f"[Bug妫€娴媇 LLM 鍙戠幇 Bug!")
    print(f"   绫诲瀷: {bug_type}, 涓ラ噸绋嬪害: {bug_severity}")
    print(f"   鎻忚堪: {bug_message[:80]}...")

    mapped_category = _map_bug_category(bug_type)
    all_operation_history = memory_manager.get_operation_history_chronological()
    bug_widget = _action_history_target(parsed_action)
    mapped_severity = _normalize_bug_severity(
        raw_severity=bug_severity,
        category=mapped_category,
        description=bug_message,
        activity=current_activity,
        operation=parsed_action.operation or "",
        widget=bug_widget,
        operation_history=all_operation_history,
    )
    non_terminating_visual_bug = _is_non_terminating_visual_state_bug(
        category=mapped_category.value,
        severity=mapped_severity.value,
        description=bug_message,
        evidence=bug_desc.get("evidence", ""),
        current_widgets=current_widgets,
    )
    termination_policy = (
        "continue_after_report"
        if non_terminating_visual_bug
        else "terminate_on_confirmed_bug"
    )

    duplicate_bug_id = _find_duplicate_reported_bug(
        memory_manager,
        mapped_category.value,
        current_activity,
        bug_message,
        parsed_action.operation or "",
        bug_widget,
    )
    if duplicate_bug_id:
        print(f"[Bug鍘婚噸] 璺宠繃閲嶅 Bug锛屽凡瀛樺湪: {duplicate_bug_id}")
        step_result["duplicate_bug_suppressed"] = True
        step_result["duplicate_bug_id"] = duplicate_bug_id
        step_result["duplicate_bug_description"] = bug_message
        if experiment_logger:
            experiment_logger.log_event("duplicate_bug_suppressed", {
                "step_index": step_index,
                "elapsed_seconds": _elapsed_seconds(run_started_perf),
                "duplicate_bug_id": duplicate_bug_id,
                "activity": current_activity,
                "category": mapped_category.value,
                "operation": parsed_action.operation or "",
                "widget": bug_widget,
                "description": bug_message,
            })
        return False

    # 鏋勫缓 BugReport
    # 鍖呭惈鎵€鏈夊巻鍙叉搷浣滆褰曪紙鐢ㄤ簬瀹屾暣澶嶇幇璺緞锛?
    bug_report = BugReport(
        bug_id=_make_bug_id("explorer"),
        timestamp=dt.now(),
        severity=mapped_severity,
        category=mapped_category,
        title=bug_message[:100],
        description=bug_message,
        activity=current_activity,
        operation=parsed_action.operation or "",
        widget=bug_widget,
        screenshot_paths=[str(screenshot_data.path)] if screenshot_data else [],
        additional_info={
            "detected_by": "explorer_llm",
            "source": "explorer_bug_assertion",
            "page_description": parsed_action.page_description,
            "llm_thought": parsed_action.thought,
            "function_name": parsed_action.function_name,
            "ui_state": ui_state or {},
            "ui_state_summary": ui_state_prompt or "",
            "model_severity": bug_severity,
            "normalized_severity": mapped_severity.value,
            "severity_source": "deterministic_policy",
            "non_terminating": non_terminating_visual_bug,
            "termination_policy": termination_policy,
        },
        operation_history=all_operation_history,  # Include all completed operations.
    )
    bug_asserted_elapsed_seconds = _elapsed_seconds(run_started_perf)

    # ==================== 鐩戠鑰呭鏌?====================
    print("\n[鐩戠鑰匽 鏆傚仠娴嬭瘯锛岃皟鐢ㄧ洃绠¤€呭鏌?Bug 鎶ュ憡...")

    context = {
        'operation_history': memory_manager.get_operation_history_chronological(),
        # Bug 鏂█鍙戠敓鍦ㄦ墽琛屽姩浣滀箣鍓嶏紝姝ゆ椂褰撳墠 LLM 鍝嶅簲杩樻病杩涘叆 memory銆?
        'page_description': parsed_action.page_description,
        'current_activity': current_activity,
        'reported_bugs': memory_manager.get_reported_bugs(),
        'ui_state': ui_state or {},
        'ui_state_prompt': ui_state_prompt or "",
        'current_widgets': current_widgets or [],
        'asserted_action': parsed_action_to_dict(parsed_action),
        'latest_completed_operation': memory_manager.get_latest_operation(),
    }

    review_result = supervisor.check_false_positive(
        bug_report=bug_report,
        context=context,
        screenshots=[screenshot_data] if screenshot_data else None
    )
    supervisor_artifact_paths = _save_supervisor_artifacts(
        experiment_logger,
        supervisor,
        step_index or memory_manager.get_step_count(),
        "false_positive_check",
    )

    if not review_result.accepted:
        print(f"[Supervisor] Review not accepted: {review_result.rejection_reason}")
        print("[Supervisor] Explorer bug assertion is left inconclusive; continue testing.")
        if experiment_logger:
            experiment_logger.log_event("supervisor_review_inconclusive", {
                "review_type": review_result.review_type,
                "source": "explorer_bug_assertion",
                "bug_id": bug_report.bug_id,
                "confidence": review_result.confidence,
                "min_confidence": supervisor.min_confidence,
                "requires_more_verification": review_result.requires_more_verification,
                "rejection_reason": review_result.rejection_reason,
                "supervisor_reasoning": review_result.reasoning,
                **supervisor_artifact_paths,
            })
        return False

    if review_result.is_false_positive:
        print(f"[鐩戠鑰匽 鍒ゅ畾涓哄亣闃虫€э細{review_result.false_positive_reason}")
        print("[鐩戠鑰匽 璺宠繃姝?Bug 鎶ュ憡锛岀户缁祴璇?")

        timing_record = _build_bug_timing_record(
            run_started_perf=run_started_perf,
            step_index=step_index,
            bug_id=bug_report.bug_id,
            detected_by="explorer_llm",
            source="explorer_bug_assertion",
            supervisor_verdict="false_positive",
            is_false_positive=True,
            category=mapped_category.value,
            severity=mapped_severity.value,
            activity=current_activity,
            operation=parsed_action.operation or "",
            widget=bug_widget,
            description=bug_message,
            confidence=review_result.confidence,
            asserted_elapsed_seconds=bug_asserted_elapsed_seconds,
        )
        _record_bug_metric(results, experiment_logger, timing_record)

        if experiment_logger:
            bug_record = bug_report.to_dict()
            bug_record.update({
                "detected_by": "explorer_llm",
                "source": "explorer_bug_assertion",
                "supervisor_reviewed": True,
                "supervisor_verdict": "false_positive",
                "is_false_positive": True,
                "is_true_positive": False,
                "detection_metrics": timing_record,
                "time_to_detection_seconds": timing_record.get("asserted_elapsed_seconds"),
                "time_to_verdict_seconds": timing_record.get("elapsed_seconds"),
                "step_count_to_detection": timing_record.get("step_count_to_detection"),
                "confidence": review_result.confidence,
                "false_positive_reason": review_result.false_positive_reason,
                "requires_more_verification": review_result.requires_more_verification,
                "supervisor_reasoning": review_result.reasoning,
                **supervisor_artifact_paths,
            })
            experiment_logger.log_bug(bug_record)

        # 璁板綍鍋囬槼鎬ф渚嬩緵瀛︿範
        memory_manager.record_false_positive_case(
            bug_description=bug_message,
            reason=review_result.false_positive_reason,
            confidence=review_result.confidence
        )

        return False  # 涓嶇粓姝㈡祴璇?

    print(f"[鐩戠鑰匽 纭鐪熷疄 Bug: {review_result.reasoning}")

    # ========== 绔嬪嵆淇濆瓨鐪熷疄 Bug 鎶ュ憡锛堝寘鍚墍鏈夊巻鍙叉搷浣滐級==========
    print(f"\n[Bug鎶ュ憡] 绔嬪嵆淇濆瓨鐪熷疄 Bug 鎶ュ憡...")
    print(f"[Bug鎶ュ憡] 鍖呭惈 {len(all_operation_history)} 鏉″巻鍙叉搷浣滆褰?")
    bug_report.confidence = review_result.confidence
    timing_record = _build_bug_timing_record(
        run_started_perf=run_started_perf,
        step_index=step_index,
        bug_id=bug_report.bug_id,
        detected_by="explorer_llm",
        source="explorer_bug_assertion",
        supervisor_verdict="true_bug",
        is_false_positive=False,
        category=mapped_category.value,
        severity=mapped_severity.value,
        activity=current_activity,
        operation=parsed_action.operation or "",
        widget=bug_widget,
        description=bug_message,
        confidence=review_result.confidence,
        asserted_elapsed_seconds=bug_asserted_elapsed_seconds,
    )
    timing_record["non_terminating"] = non_terminating_visual_bug
    timing_record["termination_policy"] = termination_policy
    _record_bug_metric(results, experiment_logger, timing_record)
    bug_report.additional_info.update({
        "detection_metrics": timing_record,
        "supervisor_reasoning": review_result.reasoning,
        "supervisor_confidence": review_result.confidence,
        "requires_more_verification": review_result.requires_more_verification,
        "non_terminating": non_terminating_visual_bug,
        "termination_policy": termination_policy,
    })

    if bug_analysis_engine:
        bug_analysis_engine.save_report(bug_report)
    else:
        report_dir = Path("bug_reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        bug_report.load_screenshots_as_base64()
        with open(report_dir / f"{bug_report.bug_id}.md", 'w', encoding='utf-8') as f:
            f.write(bug_report.to_markdown())
        with open(report_dir / f"{bug_report.bug_id}.json", 'w', encoding='utf-8') as json_file:
            json.dump(bug_report.to_dict(), json_file, ensure_ascii=False, indent=2)

    if experiment_logger:
        bug_record = bug_report.to_dict()
        bug_record.update({
            "detected_by": "explorer_llm",
            "source": "explorer_bug_assertion",
            "supervisor_reviewed": True,
            "supervisor_verdict": "true_bug",
            "is_false_positive": False,
            "is_true_positive": True,
            "detection_metrics": timing_record,
            "time_to_detection_seconds": timing_record.get("asserted_elapsed_seconds"),
            "time_to_verdict_seconds": timing_record.get("elapsed_seconds"),
            "step_count_to_detection": timing_record.get("step_count_to_detection"),
            "confidence": review_result.confidence,
            "requires_more_verification": review_result.requires_more_verification,
            "supervisor_reasoning": review_result.reasoning,
            "non_terminating": non_terminating_visual_bug,
            "termination_policy": termination_policy,
            **_copy_bug_report_paths(bug_report.bug_id, experiment_logger),
            **supervisor_artifact_paths,
        })
        experiment_logger.log_bug(bug_record)

    memory_manager.record_reported_bug(
        bug_id=bug_report.bug_id,
        source="explorer_llm",
        category=mapped_category.value,
        severity=mapped_severity.value,
        description=bug_report.description,
        activity=bug_report.activity,
        operation=bug_report.operation,
        widget=bug_report.widget,
        confidence=review_result.confidence,
    )

    # 璁板綍鍒版祴璇曟棩蹇?
    from llm_agent.test_logger import get_logger
    bug_logger = get_logger()
    bug_logger.log(f"鐪熷疄 Bug 宸蹭繚瀛? {bug_report.bug_id}", "ERROR")
    bug_logger.log(f"  绫诲瀷: {mapped_category.value}, 涓ラ噸绋嬪害: {mapped_severity.value}", "ERROR")
    bug_logger.log(f"  浣嶇疆: {current_activity} - {parsed_action.operation}", "ERROR")
    bug_logger.log(f"  鎻忚堪: {bug_message[:100]}...", "ERROR")

    results["bug_count"] = results.get("bug_count", 0) + 1

    if non_terminating_visual_bug:
        print("[Bug妫€娴媇 宸蹭繚瀛橀潪闃诲瑙嗚鐘舵€?Bug锛岀户缁祴璇?")
        bug_logger.log(f"闈為樆濉炶瑙夌姸鎬?Bug 宸蹭繚瀛橈紝缁х画娴嬭瘯: {bug_report.bug_id}", "WARNING")
        return False

    print("[Bug妫€娴媇 宸茬‘璁ょ湡瀹?Bug锛岀粓姝㈡湰杞祴璇?")
    return True


def _handle_behavior_chain_review(
    behavior_dossier: BehaviorDossierManager,
    supervisor: SupervisorModel,
    memory_manager: TestingSequenceMemorizer,
    experiment_logger: ExperimentLogger,
    bug_analysis_engine: BugAnalysisEngine,
    screenshot_manager: ScreenshotManager,
    step_index: int,
    current_activity: str,
    activity_after: str,
    parsed_action,
    operation: str,
    history_target_widget: str,
    widget_name: str,
    step_record: Dict,
    step_result: Dict,
    results: Dict,
    ui_state: Dict,
    ui_state_prompt: str,
    current_widgets_for_review: list,
    run_started_perf: float,
    logger=None,
) -> bool:
    """Run sequence-level behavior dossier review when trigger conditions match."""
    trigger_evaluation = behavior_dossier.last_trigger_evaluation or behavior_dossier.evaluate_trigger()
    trigger_dict = trigger_evaluation.to_dict()
    step_record["behavior_review_trigger"] = trigger_dict

    if experiment_logger:
        experiment_logger.log_function_trace({
            "event_type": "step_appended",
            "step_index": step_index,
            "trace_id": (behavior_dossier.to_dict() or {}).get("trace_id"),
            "trigger_evaluation": trigger_dict,
            "active_trace": behavior_dossier.to_dict(),
        })

    if not trigger_evaluation.should_review:
        return False

    review_activity = activity_after or current_activity
    current_step = memory_manager.get_step_count()
    print(f"\n[琛屼负妗堝嵎] 瑙﹀彂搴忓垪绾у鏌?(姝ラ {current_step}, score={trigger_evaluation.score})")
    if logger:
        logger.log(
            f"琛屼负妗堝嵎瀹℃煡瑙﹀彂 | step={current_step} score={trigger_evaluation.score} "
            f"reasons={trigger_evaluation.reasons}",
            "INFO",
        )

    review_screenshot = screenshot_manager.capture(activity_name=review_activity)
    review_screenshot_path = None
    if review_screenshot:
        review_screenshot_path = experiment_logger.copy_artifact(
            review_screenshot.path,
            "screenshots",
            f"step_{step_index:03d}_behavior_chain_review.png",
        )

    review_context = behavior_dossier.build_review_context()
    review_context.update({
        "current_activity": review_activity,
        "operation_history": memory_manager.get_operation_history_chronological(),
        "reported_bugs": memory_manager.get_reported_bugs(),
        "ui_state": ui_state or {},
        "ui_state_prompt": ui_state_prompt or "",
        "current_widgets": current_widgets_for_review or [],
    })

    review_result = supervisor.check_behavior_chain(
        context=review_context,
        screenshots=[review_screenshot] if review_screenshot else None,
    )
    supervisor_artifact_paths = _save_supervisor_artifacts(
        experiment_logger,
        supervisor,
        step_index,
        "behavior_chain_review",
    )

    review_record = review_result.to_dict()
    review_record.update({
        "screenshot_path": review_screenshot_path,
        "trigger_evaluation": trigger_dict,
        **supervisor_artifact_paths,
    })
    step_record["behavior_chain_review"] = review_record
    behavior_dossier.apply_review_result(review_result.to_dict(), current_step)

    if experiment_logger:
        experiment_logger.log_function_trace({
            "event_type": "behavior_chain_review",
            "step_index": step_index,
            "trace_id": (behavior_dossier.to_dict() or {}).get("trace_id"),
            "trigger_evaluation": trigger_dict,
            "review": review_record,
            "active_trace": behavior_dossier.to_dict(),
        })

    if not review_result.accepted:
        print(f"[琛屼负妗堝嵎] 瀹℃煡鏈噰绾? {review_result.rejection_reason}")
        if experiment_logger:
            experiment_logger.log_event("behavior_chain_review_inconclusive", {
                "step_index": step_index,
                "review": review_record,
            })
        return False

    if review_result.verdict == "needs_more_verification":
        print("[琛屼负妗堝嵎] 闇€瑕佹洿澶氶獙璇侊紝宸插啓鍥炴鍗蜂緵 Explorer 涓嬩竴姝ヤ紭鍏堝鐞?")
        if logger:
            logger.log(f"琛屼负妗堝嵎闇€瑕佹洿澶氶獙璇? {review_result.reason[:160]}", "INFO")
        return False

    if review_result.verdict == "no_bug":
        if (behavior_dossier.to_dict() or {}).get("completed"):
            print("[琛屼负妗堝嵎] 缁堝眬瀹℃煡鏈彂鐜?Bug锛屽綊妗ｆ鍗?")
            behavior_dossier.archive_if_completed()
        else:
            print("[琛屼负妗堝嵎] 涓棿瀹℃煡鏈彂鐜?Bug锛屼繚鐣欏綋鍓嶆鍗风户缁獙璇?")
        return False

    if review_result.verdict != "bug":
        return False

    bug_description = review_result.reason or "Behavior chain review detected a functional bug."
    mapped_category = _map_bug_category(review_result.bug_type or "function_anomaly")
    all_operation_history = memory_manager.get_operation_history_chronological()
    bug_widget = history_target_widget or widget_name or ""
    mapped_severity = _normalize_bug_severity(
        raw_severity=review_result.severity or "Error",
        category=mapped_category,
        description=bug_description,
        activity=review_activity,
        operation=operation or "",
        widget=bug_widget,
        operation_history=all_operation_history,
        action_phase=(step_record or {}).get("action_phase"),
        evidence="; ".join(review_result.missing_evidence or []),
    )
    non_terminating_visual_bug = _is_non_terminating_visual_state_bug(
        category=mapped_category.value,
        severity=mapped_severity.value,
        description=bug_description,
        evidence="; ".join(review_result.unsupported_claims or []),
        current_widgets=current_widgets_for_review,
    )
    termination_policy = (
        "continue_after_report"
        if non_terminating_visual_bug
        else "terminate_on_confirmed_bug"
    )

    duplicate_bug_id = _find_duplicate_reported_bug(
        memory_manager,
        mapped_category.value,
        review_activity,
        bug_description,
        operation or "",
        bug_widget,
    )
    if duplicate_bug_id:
        print(f"[琛屼负妗堝嵎] 璺宠繃閲嶅 Bug锛屽凡瀛樺湪: {duplicate_bug_id}")
        if experiment_logger:
            experiment_logger.log_event("duplicate_behavior_chain_bug_suppressed", {
                "step_index": step_index,
                "duplicate_bug_id": duplicate_bug_id,
                "review": review_record,
            })
        behavior_dossier.archive_if_completed()
        return False

    trace_snapshot = behavior_dossier.to_dict()
    behavior_bug_report = BugReport(
        bug_id=_make_bug_id(f"behavior{current_step:04d}"),
        timestamp=datetime.now(),
        severity=mapped_severity,
        category=mapped_category,
        title=bug_description[:100],
        description=bug_description,
        activity=review_activity,
        operation=operation or "",
        widget=bug_widget,
        screenshot_paths=[str(review_screenshot.path)] if review_screenshot else [],
        confidence=review_result.confidence,
        additional_info={
            "detected_by": "supervisor",
            "source": "behavior_chain_review",
            "behavior_review": review_result.to_dict(),
            "behavior_dossier": trace_snapshot,
            "trigger_evaluation": trigger_dict,
            "ui_state": ui_state or {},
            "ui_state_summary": ui_state_prompt or "",
            "model_severity": review_result.severity,
            "normalized_severity": mapped_severity.value,
            "severity_source": "deterministic_policy",
            "non_terminating": non_terminating_visual_bug,
            "termination_policy": termination_policy,
            **supervisor_artifact_paths,
        },
        operation_history=all_operation_history,
    )

    timing_record = _build_bug_timing_record(
        run_started_perf=run_started_perf,
        step_index=step_index,
        bug_id=behavior_bug_report.bug_id,
        detected_by="supervisor",
        source="behavior_chain_review",
        supervisor_verdict="behavior_chain_bug",
        is_false_positive=False,
        category=mapped_category.value,
        severity=mapped_severity.value,
        activity=behavior_bug_report.activity,
        operation=behavior_bug_report.operation,
        widget=behavior_bug_report.widget,
        description=behavior_bug_report.description,
        confidence=review_result.confidence,
    )
    timing_record["non_terminating"] = non_terminating_visual_bug
    timing_record["termination_policy"] = termination_policy
    behavior_bug_report.additional_info["detection_metrics"] = timing_record
    _record_bug_metric(results, experiment_logger, timing_record)
    bug_analysis_engine.save_report(behavior_bug_report)

    report_paths = _copy_bug_report_paths(behavior_bug_report.bug_id, experiment_logger)
    bug_record = behavior_bug_report.to_dict()
    bug_record.update({
        "detected_by": "supervisor",
        "source": "behavior_chain_review",
        "supervisor_reviewed": True,
        "supervisor_verdict": "behavior_chain_bug",
        "is_false_positive": False,
        "is_true_positive": True,
        "detection_metrics": timing_record,
        "time_to_detection_seconds": timing_record.get("asserted_elapsed_seconds"),
        "time_to_verdict_seconds": timing_record.get("elapsed_seconds"),
        "step_count_to_detection": timing_record.get("step_count_to_detection"),
        "evidence_screenshot_path": review_screenshot_path,
        "non_terminating": non_terminating_visual_bug,
        "termination_policy": termination_policy,
        **report_paths,
        **supervisor_artifact_paths,
    })
    experiment_logger.log_bug(bug_record)

    memory_manager.record_reported_bug(
        bug_id=behavior_bug_report.bug_id,
        source="behavior_chain_review",
        category=mapped_category.value,
        severity=mapped_severity.value,
        description=behavior_bug_report.description,
        activity=behavior_bug_report.activity,
        operation=behavior_bug_report.operation,
        widget=behavior_bug_report.widget,
        confidence=review_result.confidence,
    )
    results["bug_count"] = results.get("bug_count", 0) + 1
    results["behavior_chain_bug_count"] = results.get("behavior_chain_bug_count", 0) + 1
    behavior_dossier.archive_if_completed()

    if logger:
        logger.log(
            f"琛屼负閾?Bug 宸蹭繚瀛? {behavior_bug_report.bug_id} "
            f"[{mapped_severity.value}] {mapped_category.value}",
            "WARNING",
        )

    if non_terminating_visual_bug:
        print(f"[琛屼负妗堝嵎] 宸蹭繚瀛橀潪闃诲 Bug锛岀户缁祴璇? {behavior_bug_report.bug_id}")
        return False

    print(f"[琛屼负妗堝嵎] 宸茬‘璁ょ湡瀹?Bug锛岀粓姝㈡湰杞祴璇? {behavior_bug_report.bug_id}")
    step_result["status"] = "bug_terminated"
    step_result["error"] = "Confirmed bug detected by behavior-chain review"
    return True


def print_substep_header(substep_name: str) -> None:
    """鎵撳嵃瀛愭楠ゆ爣棰?"""
    print(f"\n>>> {substep_name}")
    print("-" * 50)


def compute_ui_state_fingerprint(widgets: list) -> str:
    """
    璁＄畻 UI 鐘舵€佹寚绾?

    鍩轰簬鎺т欢鍒楄〃鐢熸垚鍞竴鐨勫瓧绗︿覆鏍囪瘑锛岀敤浜庣姸鎬佸樊鍒嗘瘮杈?

    Args:
        widgets: 鎺т欢鍒楄〃

    Returns:
        UI 鐘舵€佹寚绾瑰瓧绗︿覆
    """
    if not widgets:
        return ""

    # 鎻愬彇姣忎釜鎺т欢鐨勫叧閿睘鎬у苟鎺掑簭锛岀‘淇濋『搴忎竴鑷?
    fingerprints = []
    for w in widgets:
        text = w.get("text", "") or ""
        rid = w.get("resource_id", "") or ""
        bounds = w.get("bounds", "") or ""
        # 缁勫悎鍏抽敭灞炴€?
        fp = f"{text}|{rid}|{bounds}"
        fingerprints.append(fp)

    # 鎺掑簭鍚庢嫾鎺?
    fingerprints.sort()
    return "||".join(fingerprints)


def run_outer_loop() -> Dict:
    """
    鎵ц瀹屾暣鐨勬祴璇?Outer Loop

    Returns:
        娴嬭瘯缁撴灉姹囨€诲瓧鍏?
    """
    adb_controller = ADBController()
    gui_analyzer = GUIAnalyzer()

    adb_controller = ADBController()
    gui_analyzer = GUIAnalyzer()

    # 鍒濆鍖栧叏灞€鎺㈢储缂撳瓨锛堟瘡娆″惎鍔ㄦ竻绌猴級
    exploration_cache = ExplorationCache()
    exploration_cache.clear_cache()

    # 鍒濆鍖栬蹇嗙鐞嗗櫒锛堝敮涓€鏁版嵁婧愶級
    memory_manager = TestingSequenceMemorizer()
    behavior_dossier = BehaviorDossierManager()

    # 灏嗚蹇嗙鐞嗗櫒浼犻€掔粰 PromptGenerator
    prompt_generator = PromptGenerator(
        memory_manager=memory_manager
    )

    llm_client = MultimodalLLMClient(use_multimodal_thinking_env=False)

    # 鍒濆鍖栨埅鍥剧鐞嗗櫒
    screenshot_manager = ScreenshotManager(adb_controller=adb_controller)

    # 缁熶竴 Bug 鎶ュ憡寮曟搸锛氬穿婧冨拰閫昏緫 Bug 閮戒娇鐢?BugReport 鐨?JSON/Markdown 缁撴瀯
    bug_analysis_engine = BugAnalysisEngine(
        adb_controller=adb_controller,
        screenshot_manager=screenshot_manager
    )

    # 鍔ㄤ綔鎵ц鍣ㄦ敞鍏?BugAnalysisEngine锛岄伩鍏嶅穿婧冩椂鍙敓鎴愭棫鐗?TXT 鎶ュ憡
    action_executor = ActionExecutor(
        bug_analysis_engine=bug_analysis_engine,
        screenshot_manager=screenshot_manager,
        auto_hide_keyboard_after_input=AUTO_HIDE_KEYBOARD_AFTER_INPUT,
    )

    # ========== NEW: 鍒濆鍖栫洃绠¤€呯粍浠?==========
    # 鍒濆鍖栧妯℃€?LLM 瀹㈡埛绔紙鐩戠鑰呬娇鐢級
    multimodal_llm = MultimodalLLMClient()

    # 鍒濆鍖栫洃绠¤€呮ā鍨?
    supervisor = SupervisorModel(
        multimodal_llm=multimodal_llm,
        screenshot_manager=screenshot_manager,
        review_interval=0,
        min_confidence=0.7
    )
    print("[鐩戠鑰匽 Supervisor 鍒濆鍖栧畬鎴?")

    # 鑾峰彇褰撳墠搴旂敤淇℃伅
    print("\n[搴旂敤淇℃伅] 姝ｅ湪鑾峰彇褰撳墠搴旂敤...")
    current_package = adb_controller.get_current_package()
    target_package = current_package if current_package and current_package != "unknown.package" else ""
    manifest_parser = ManifestParser()
    app_info = manifest_parser.get_or_parse(current_package)

    # 鑾峰彇榛樿搴旂敤鍚嶇О
    default_app_name = app_info.app_name if app_info else current_package.split('.')[-1]

    # ========== 鑾峰彇鐢ㄦ埛杈撳叆鐨勬祴璇曢厤缃?==========
    user_context = get_user_input(default_app_name=default_app_name)
    prompt_generator.set_user_context(user_context)

    # ========== 鍒濆鍖栨湰娆¤繍琛岀殑浜虹被鍙鏃ュ織 ==========
    run_log_path = _make_run_log_path(user_context.app_name)
    reset_logger()
    logger = get_logger(log_file=run_log_path)
    logger.section(f"{user_context.app_name} 娴嬭瘯寮€濮?")
    logger.subsection("缁勪欢鍒濆鍖?")

    experiment_logger = ExperimentLogger(
        app_name=user_context.app_name,
        package_name=current_package
    )
    activity_names = []

    if app_info:
        print(f"[搴旂敤淇℃伅] 鍖呭悕: {app_info.package_name}")
        print(f"[搴旂敤淇℃伅] Activity 鏁伴噺: {len(app_info.activities)}")

        # 娉ㄥ唽鎵€鏈?Activities 鍒?memory_manager锛堟彁鍙?name 灞炴€э級
        activity_names = [a.name for a in app_info.activities]
        memory_manager.register_activities(activity_names)
        print(f"[搴旂敤淇℃伅] 宸叉敞鍐?{len(activity_names)} 涓?Activities")
    else:
        print(f"[搴旂敤淇℃伅] 鏃犳硶瑙ｆ瀽 Manifest")

    experiment_logger.write_run_meta({
        "app": {
            "name": user_context.app_name,
            "user_note": user_context.user_note,
            "package": current_package,
            "target_package": target_package,
            "activities": activity_names,
        },
        "package": _collect_package_info(adb_controller, current_package),
        "device": _collect_device_info(adb_controller),
        "model_runtime": get_model_runtime_info(llm_client),
        "config": {
            "max_steps": MAX_STEPS,
            "step_wait_time": STEP_WAIT_TIME,
            "auto_hide_keyboard_after_input": AUTO_HIDE_KEYBOARD_AFTER_INPUT,
        },
        "logs": {
            "human_log_path": str(run_log_path.resolve()),
        },
        "code": {
            "git_commit": _safe_git_commit(),
            "cwd": str(Path.cwd()),
        },
    })
    logger.log(f"缁撴瀯鍖栧疄楠岀粨鏋滅洰褰? {experiment_logger.run_dir}", "INFO")

    print("[鍒濆鍖朷 缁勪欢鍒濆鍖栧畬鎴?")

    # 娓呯┖鏃ュ織缂撳啿鍖猴紙鍑嗗宕╂簝妫€娴嬶級
    print("\n[鏃ュ織绠＄悊] 娓呯┖ logcat 缂撳啿鍖?..")
    adb_controller.clear_logcat()



    # ========== 涓诲惊鐜?==========
    print("\n" + "=" * 70)
    print(f"  寮€濮嬫墽琛?LLM 鑷富鎺㈢储 (鏈€澶ф鏁? {MAX_STEPS})")
    print("=" * 70)

    # 娴嬭瘯缁撴灉缁熻
    run_started_at = datetime.now()
    run_started_perf = time.perf_counter()
    experiment_logger.update_run_meta({
        "timing": {
            "test_started_at": run_started_at.isoformat(),
            "timer_scope": "autonomous_exploration_loop",
            "timer_clock": "time.perf_counter",
        }
    })

    results = {
        "total_steps": MAX_STEPS,
        "test_started_at": run_started_at.isoformat(),
        "timer_scope": "autonomous_exploration_loop",
        "successful_steps": 0,
        "failed_steps": 0,
        "skipped_steps": 0,
        "crashed": False,
        "bug_count": 0,
        "missed_bug_count": 0,
        "behavior_chain_bug_count": 0,
        "true_positive_count": 0,
        "false_positive_count": 0,
        "first_bug_elapsed_seconds": None,
        "first_bug_step": None,
        "first_bug_id": None,
        "first_bug_is_true_positive": None,
        "first_true_bug_elapsed_seconds": None,
        "first_true_bug_step": None,
        "first_true_bug_id": None,
        "first_false_positive_elapsed_seconds": None,
        "first_false_positive_step": None,
        "first_false_positive_id": None,
        "bug_timeline": [],
        "step_details": []
    }

    # 璁板綍鏄惁涓虹涓€姝?
    is_first_step = True

    for step in range(1, MAX_STEPS + 1):
        step_result = {
            "step_index": step,
            "status": "pending",
            "activity": "unknown",
            "operation": None,
            "widget": None,
            "error": None
        }
        step_record = {
            "step_index": step,
            "started_at": datetime.now().isoformat(),
            "started_elapsed_seconds": _elapsed_seconds(run_started_perf),
            "target_package": target_package,
            "status": "pending",
        }

        # 鎵撳嵃褰撳墠鎺㈢储姝ラ
        step_header = f"绗?{step} 姝?"
        print("\n" + "=" * 70)
        print(f"  褰撳墠鎺㈢储姝ラ: {step_header}")
        print("=" * 70)

        try:
            # ---------- a. 鎶撳彇 UI 甯冨眬 ----------
            print_substep_header("a. 鎶撳彇 UI 甯冨眬")

            ui_file, dump_attempts = _dump_ui_with_retry(
                adb_controller,
                context=f"step {step:03d} before",
                logger=logger,
            )
            step_record["ui_dump_attempts_before"] = dump_attempts

            if not ui_file:
                error_message = f"UI dump failed after {dump_attempts} attempts"
                print(f"[璀﹀憡] UI 甯冨眬鎶撳彇澶辫触锛岃烦杩囧綋鍓嶆楠?({error_message})")
                step_result["status"] = "skipped"
                step_result["error"] = error_message
                results["skipped_steps"] += 1
                results["step_details"].append(step_result)
                logger.log(f"Step {step:03d} skipped | {error_message}", "SKIP")
                _finish_experiment_step(experiment_logger, step_record, "skipped", error_message)
                continue

            print(f"[鎴愬姛] UI 甯冨眬宸蹭繚瀛? {ui_file}")
            step_record["xml_before_path"] = experiment_logger.copy_artifact(
                ui_file, "xml", f"step_{step:03d}_before.xml"
            )
            device_focus_before = adb_controller.get_input_focus_state()
            ui_state_before = analyze_ui_state(
                ui_file,
                target_package=target_package,
                device_state=device_focus_before,
            )
            ui_state_before_prompt = format_ui_state_for_prompt(ui_state_before)
            step_record["ui_state_before"] = ui_state_before
            step_record["ui_state_before_summary"] = ui_state_before_prompt

            foreground_package = adb_controller.get_current_package()
            step_record["package_before"] = foreground_package
            if target_package and foreground_package and foreground_package != target_package:
                outside_target_message = f"Target app not foreground: {foreground_package}"
                if behavior_dossier.active_trace is None and behavior_dossier.archived_traces:
                    print(f"[瀹屾垚] {outside_target_message}; behavior dossier already archived")
                    step_result["status"] = "completed"
                    step_result["error"] = outside_target_message
                    results["step_details"].append(step_result)
                    logger.log(
                        f"Step {step:03d} completed | target app left foreground after completed dossier: {foreground_package}",
                        "INFO",
                    )
                    step_record["external_app_detected"] = True
                    step_record["detected_package"] = foreground_package
                    _finish_experiment_step(
                        experiment_logger,
                        step_record,
                        "completed",
                        outside_target_message,
                    )
                    break

                print(f"[澶栭儴椤甸潰] 褰撳墠鍓嶅彴鍖呬笉鏄洰鏍囧簲鐢? {foreground_package}")
                print("[澶栭儴椤甸潰] 鎸?Back 灏濊瘯杩斿洖鐩爣搴旂敤锛屼笅涓€姝ョ户缁帰绱?")
                adb_controller.go_back()
                time.sleep(STEP_WAIT_TIME)
                step_result["status"] = "skipped"
                step_result["error"] = outside_target_message
                results["skipped_steps"] += 1
                results["step_details"].append(step_result)
                logger.log(
                    f"Step {step:03d} skipped | target app not foreground: {foreground_package}",
                    "SKIP",
                )
                step_record["external_app_detected"] = True
                step_record["detected_package"] = foreground_package
                _finish_experiment_step(
                    experiment_logger,
                    step_record,
                    "skipped",
                    outside_target_message,
                )
                continue

            # ---------- b. 瑙ｆ瀽 UI 鎺т欢 ----------
            print_substep_header("b. 瑙ｆ瀽 UI 鎺т欢")

            widgets = gui_analyzer.parse_xml(ui_file, target_package=target_package)

            if not widgets:
                if gui_analyzer.is_system_page_detected():
                    detected_package = gui_analyzer.get_detected_package() or "unknown"
                    print(f"[澶栭儴椤甸潰] 妫€娴嬪埌宸茶烦杞埌闈炵洰鏍囬〉闈? {detected_package}")
                    print("[澶栭儴椤甸潰] 鎸?Back 杩斿洖琚祴搴旂敤锛屼笅涓€姝ョ户缁帰绱?")
                    adb_controller.go_back()
                    time.sleep(STEP_WAIT_TIME)
                    step_result["status"] = "skipped"
                    step_result["error"] = f"External/system page detected: {detected_package}"
                    results["skipped_steps"] += 1
                    results["step_details"].append(step_result)
                    logger.log(
                        f"Step {step:03d} skipped | external page: {detected_package}",
                        "SKIP",
                    )
                    step_record["external_app_detected"] = True
                    step_record["detected_package"] = detected_package
                    _finish_experiment_step(
                        experiment_logger,
                        step_record,
                        "skipped",
                        f"External/system page detected: {detected_package}",
                    )
                    continue

                print("[璀﹀憡] 鏈彁鍙栧埌鏈夋晥鎺т欢锛岃烦杩囧綋鍓嶆楠?")
                step_result["status"] = "skipped"
                step_result["error"] = "No widgets found"
                results["skipped_steps"] += 1
                results["step_details"].append(step_result)
                logger.log(f"Step {step:03d} skipped | no widgets found", "SKIP")
                step_record["widget_count_before"] = 0
                _finish_experiment_step(experiment_logger, step_record, "skipped", "No widgets found")
                continue

            print(f"[鎴愬姛] 鎻愬彇鍒?{len(widgets)} 涓湁鏁堟帶浠?")
            step_record["widget_count_before"] = len(widgets)
            step_record["widgets_before"] = summarize_widgets(widgets)
            step_record["structure_fingerprint_before"] = compute_structure_fingerprint(widgets)
            step_record["content_fingerprint_before"] = compute_content_fingerprint(widgets)

            # 鎵撳嵃鍓?3 涓帶浠舵瑙?
            print("[鎺т欢姒傝] 鍓?3 涓帶浠?")
            for j, widget in enumerate(widgets[:3], 1):
                text = widget.get("text", "(鏃犳枃鏈?")
                rid = widget.get("resource_id", "(鏃營D)")
                print(f"  {j}. 鏂囨湰: {text}, ID: {rid}")

            # ---------- c. 鑾峰彇褰撳墠 Activity ----------
            print_substep_header("c. 鑾峰彇褰撳墠 Activity")

            current_activity = adb_controller.get_current_activity()
            step_result["activity"] = current_activity
            step_record["activity_before"] = current_activity
            step_record["package_before"] = foreground_package

            print(f"[鎴愬姛] 褰撳墠 Activity: {current_activity}")

            screenshot_before = screenshot_manager.capture(activity_name=current_activity)
            if screenshot_before:
                step_record["screenshot_before_path"] = experiment_logger.copy_artifact(
                    screenshot_before.path,
                    "screenshots",
                    f"step_{step:03d}_before.png",
                )

            # ---------- d. 鐢熸垚 Prompt锛堟牴鎹樁娈甸€夋嫨锛?---------
            print_substep_header("d. 鐢熸垚 Prompt")
            prompt_generator.set_ui_state_section(ui_state_before_prompt)
            prompt_generator.set_behavior_dossier_section(behavior_dossier.format_for_prompt())

            if is_first_step:
                # 绗竴姝ワ細浣跨敤鍒濆鎻愮ず璇嶏紙瀹屾暣涓婁笅鏂囷級
                print("[鎻愮ず璇峕 浣跨敤鍒濆鎻愮ず璇嶏紙绗竴姝ワ級")
                test_prompt = prompt_generator.build_initial_prompt(
                    widgets, current_activity
                )
                is_first_step = False
            else:
                # 鍚庣画姝ラ锛氫娇鐢ㄦ祴璇曟彁绀鸿瘝锛堝寘鍚垚鍔熶俊鎭級
                print("[鎻愮ず璇峕 浣跨敤娴嬭瘯鎻愮ず璇嶏紙鍚庣画姝ラ锛?")
                test_prompt = prompt_generator.build_test_prompt(
                    widgets, current_activity
                )

            print("[鎴愬姛] Prompt 宸茬敓鎴?")
            step_record["prompt_path"] = experiment_logger.save_text_artifact(
                "prompts",
                f"step_{step:03d}_prompt.txt",
                test_prompt,
            )

            # ---------- e. 鑾峰彇 LLM 鍐崇瓥 ----------
            print_substep_header("e. 鑾峰彇 LLM 鍐崇瓥")

            # 鑾峰彇绯荤粺鎻愮ず璇?
            system_prompt = prompt_generator.build_system_prompt()
            step_record["system_prompt_path"] = experiment_logger.save_text_artifact(
                "prompts",
                f"step_{step:03d}_system_prompt.txt",
                system_prompt,
            )

            explorer_screenshots = [screenshot_before] if screenshot_before else None
            step_record["explorer_client"] = llm_client.__class__.__name__
            step_record["explorer_screenshot_count"] = len(explorer_screenshots or [])

            llm_response = llm_client.get_decision(
                test_prompt,
                system_prompt,
                screenshots=explorer_screenshots,
            )
            llm_call_info = (
                llm_client.get_last_call_info()
                if hasattr(llm_client, "get_last_call_info")
                else {}
            )
            step_record["llm_call_info"] = llm_call_info
            step_record["response_path"] = experiment_logger.save_text_artifact(
                "prompts",
                f"step_{step:03d}_response.txt",
                llm_response,
            )

            print(f"[鎴愬姛] LLM 鍝嶅簲: {llm_response}")

            # ========== NEW: 鍏堣В鏋?LLM 鍝嶅簲妫€鏌?Bug锛堜笉鎵ц鍔ㄤ綔锛?=========
            # Bug 鏂█瀹℃煡蹇呴』鍩轰簬瑙﹀彂鏂█鏃剁殑涓婁笅鏂囧揩鐓э紝鑰屼笉鏄墽琛屽悗缁姩浣滃悗鐨勬柊鐘舵€?
            parsed_action_preview = action_executor.parse_action_only(llm_response)
            parsed_action_preview = action_executor.parse_action_only(llm_response)
            if llm_call_info.get("fallback"):
                fallback_reason = llm_call_info.get("fallback_reason", "unknown")
                print(f"[LLM fallback] API returned no usable action; skipping step: {fallback_reason}")
                logger.log(
                    f"Step {step:03d} skipped | LLM API fallback: {fallback_reason}",
                    "SKIP",
                )
                step_record["llm_api_fallback"] = True
                step_record["parse_success"] = False
                step_record["parsed_action_preview"] = None
                step_result["status"] = "skipped"
                step_result["error"] = f"LLM API fallback: {fallback_reason}"
                results["skipped_steps"] += 1
                results["step_details"].append(step_result)
                _finish_experiment_step(
                    experiment_logger,
                    step_record,
                    "skipped",
                    f"LLM API fallback: {fallback_reason}",
                )
                continue

            step_record["parse_success"] = parsed_action_preview is not None
            step_record["parsed_action_preview"] = parsed_action_to_dict(parsed_action_preview)
            logger.log(
                f"Step {step:03d} plan | {current_activity} | {_format_action_summary(parsed_action_preview)}",
                "PLAN",
            )

            if parsed_action_preview and parsed_action_preview.bug_detected:
                # Bug 妫€娴嬶細绔嬪嵆鍦ㄥ綋鍓嶇姸鎬佹埅鍥撅紙瑙﹀彂鏂█鏃剁殑涓婁笅鏂囧揩鐓э級
                print(f"\n{'!' * 60}")
                print(f"[Bug妫€娴媇 LLM 鍙戠幇 Bug!锛堝湪鎵ц鍔ㄤ綔涔嬪墠锛?")
                print(f"   绫诲瀷: {parsed_action_preview.bug_description.get('type', 'unknown')}")
                print(f"   鎻忚堪: {parsed_action_preview.bug_description.get('description', 'N/A')[:80]}...")
                logger.log(f"LLM 鎶ュ憡 Bug锛堝鏌ュ墠锛? {parsed_action_preview.bug_description}", "WARNING")

                # 鍦ㄥ綋鍓嶇姸鎬佹埅鍥撅紙瑙﹀彂鏂█鏃剁殑涓婁笅鏂囧揩鐓э紝鑰岄潪鎵ц鍔ㄤ綔鍚庣殑鏂扮姸鎬侊級
                context_snapshot = screenshot_manager.capture(activity_name=current_activity)
                print(f"[鐩戠鑰匽 浣跨敤褰撳墠鐘舵€佹埅鍥捐繘琛屽鏌ワ紙瑙﹀彂鏂█鏃剁殑涓婁笅鏂囷級")

                # 璋冪敤鐩戠鑰呭鏌?
                should_terminate = _handle_llm_bug_report(
                    components=None,
                    parsed_action=parsed_action_preview,
                    current_activity=current_activity,
                    screenshot_data=context_snapshot,
                    step_result=step_result,
                    results=results,
                    supervisor=supervisor,
                    memory_manager=memory_manager,
                    experiment_logger=experiment_logger,
                    bug_analysis_engine=bug_analysis_engine,
                    step_index=step,
                    ui_state=ui_state_before,
                    ui_state_prompt=ui_state_before_prompt,
                    current_widgets=summarize_widgets(widgets),
                    run_started_perf=run_started_perf,
                )

                if should_terminate:
                    step_result["status"] = "bug_terminated"
                    step_result["error"] = "Confirmed bug detected, test terminated"
                    results["step_details"].append(step_result)
                    _finish_experiment_step(
                        experiment_logger,
                        step_record,
                        "bug_terminated",
                        "Confirmed bug detected, test terminated",
                    )
                    break

                # 濡傛灉鐩戠鑰呭垽瀹氫负鍋囬槼鎬э紝璁板綍鍚庣户缁墽琛屽姩浣?
                # 濡傛灉鐩戠鑰呭垽瀹氫负鐪熷疄 Bug锛屽凡璁板綍锛岀户缁墽琛屽姩浣?

            # ---------- f. 鎵ц鍔ㄤ綔 ----------
            print_substep_header("f. 鎵ц鍔ㄤ綔")

            # ========== 宸ヤ笟绾у穿婧冩娴嬶細姣忔鎿嶄綔鍓嶆竻绌?logcat 缂撳瓨 ==========
            # 纭繚鍙崟鑾峰綋鍓嶅姩浣滀骇鐢熺殑澧為噺鏃ュ織锛屼粠婧愬ご鍑忓皯鏃ュ織鍒嗘瀽璐熸媴
            print("[鏃ュ織绠＄悊] 娓呯┖ logcat 缂撳啿鍖猴紝鍑嗗鎹曡幏澧為噺鏃ュ織...")
            adb_controller.clear_logcat()

            # ========== 璁板綍鍓嶇疆鐘舵€侊紙鐘舵€佸樊鍒嗙涓€姝ワ級==========
            state_before = compute_ui_state_fingerprint(widgets)
            activity_before = current_activity

            try:
                # 瀹夊叏鎺ユ敹杩斿洖鍊?
                execute_result = action_executor.execute_action(
                    llm_response, widgets, adb_controller,
                    memory_manager=memory_manager,
                    activity_name=current_activity,
                    target_package=target_package
                )

                # 瀹夊叏鍙栧€?
                success = execute_result[0] if execute_result else False
                parsed_action = execute_result[1] if len(execute_result) > 1 else None
                step_record["execution_success"] = bool(success)
                step_record["parsed_action"] = parsed_action_to_dict(parsed_action)

                # 璁板綍瑙ｆ瀽缁撴灉
                if parsed_action:
                    step_result["operation"] = parsed_action.operation
                    step_result["widget"] = _action_history_target(parsed_action)

                if not success:
                    print("[璀﹀憡] 鍔ㄤ綔鎵ц澶辫触")
                    step_result["status"] = "failed"
                    step_result["error"] = "Action execution failed"
                    results["failed_steps"] += 1

                    # 妫€鏌ユ槸鍚︿负"鎺т欢鏈壘鍒?閿欒锛屽鏋滄槸鍒欎娇鐢ㄥ弽棣堟彁绀鸿瘝閲嶈瘯
                    failed_widget = _action_history_target(parsed_action) if parsed_action else None

                    # 璁板綍澶辫触鎿嶄綔
                    memory_manager.update_step(
                        activity_name=current_activity,
                        operation=parsed_action.operation if parsed_action else "unknown",
                        widget_name=failed_widget or "unknown",
                        success=False
                    )
                    print(f"[璁板繂鏇存柊] 宸茶褰曞け璐ユ搷浣? {failed_widget}")

                    # 濡傛灉鏄帶浠舵湭鎵惧埌锛屽皾璇曚娇鐢ㄥ弽棣堟彁绀鸿瘝璁?LLM 閲嶉€?
                    if failed_widget:
                        print("[閲嶈瘯] 鎺т欢鏈壘鍒帮紝浣跨敤鍙嶉鎻愮ず璇嶈 LLM 閲嶆柊閫夋嫨...")
                        feedback_prompt = prompt_generator.build_feedback_prompt(
                            widgets, current_activity, failed_widget
                        )
                        step_record["retry_prompt_path"] = experiment_logger.save_text_artifact(
                            "prompts",
                            f"step_{step:03d}_retry_prompt.txt",
                            feedback_prompt,
                        )

                        # 鑾峰彇 LLM 閲嶆柊鍐崇瓥锛堜娇鐢ㄧ浉鍚岀殑绯荤粺鎻愮ず璇嶏級
                        retry_response = llm_client.get_decision(
                            feedback_prompt,
                            system_prompt,
                            screenshots=explorer_screenshots,
                        )
                        step_record["retry_response_path"] = experiment_logger.save_text_artifact(
                            "prompts",
                            f"step_{step:03d}_retry_response.txt",
                            retry_response,
                        )
                        print(f"[閲嶈瘯] LLM 鍝嶅簲: {retry_response}")

                        # 灏濊瘯鎵ц閲嶈瘯鍐崇瓥
                        retry_result = action_executor.execute_action(
                            retry_response, widgets, adb_controller,
                            memory_manager=memory_manager,
                            activity_name=current_activity,
                            target_package=target_package
                        )

                        retry_success = retry_result[0] if retry_result else False
                        retry_action = retry_result[1] if retry_result and len(retry_result) > 1 else None

                        if retry_success:
                            print("[閲嶈瘯鎴愬姛] LLM 閲嶆柊閫夋嫨鐨勬搷浣滄墽琛屾垚鍔?")
                            # 浣跨敤閲嶈瘯鐨勬搷浣滀俊鎭?
                            parsed_action = retry_action
                            success = True
                            step_record["execution_success"] = True
                            step_record["retry_success"] = True
                            step_record["parsed_action"] = parsed_action_to_dict(parsed_action)
                            step_result["status"] = "success"
                            results["successful_steps"] += 1
                            results["failed_steps"] -= 1  # 鎭㈠璁℃暟
                        else:
                            print("[閲嶈瘯澶辫触] LLM 閲嶆柊閫夋嫨浠嶇劧澶辫触锛岃烦杩囨姝ラ")
                            step_record["retry_success"] = False

                    if not success:
                        results["step_details"].append(step_result)
                        logger.log(
                            f"Step {step:03d} failed | action execution failed",
                            "FAIL",
                        )
                        _finish_experiment_step(
                            experiment_logger,
                            step_record,
                            "failed",
                            "Action execution failed",
                        )
                        continue

                print("[鎴愬姛] 鍔ㄤ綔鎵ц瀹屾垚")

                # 璁板綍鍒版棩蹇?
                if parsed_action:
                    logger.log(
                        f"Step {step:03d} exec | {parsed_action.operation} -> {_action_history_target(parsed_action) or 'N/A'} | ok",
                        "OK",
                    )

                # 妫€娴嬫槸鍚﹀彂鐢熷穿婧?
                if action_executor.last_crash_detected:
                    print("[宕╂簝妫€娴媇 鍙戠幇搴旂敤宕╂簝锛佺粓姝㈡祴璇曞惊鐜?")
                    logger.log("搴旂敤宕╂簝锛佺粓姝㈡祴璇曞惊鐜?", "ERROR")
                    step_result["status"] = "crashed"
                    step_result["error"] = "Application crashed"
                    results["failed_steps"] += 1
                    results["crashed"] = True
                    results["step_details"].append(step_result)
                    crash_report = action_executor.last_bug_report
                    crash_timing_record = None
                    if crash_report:
                        crash_timing_record = _build_bug_timing_record(
                            run_started_perf=run_started_perf,
                            step_index=step,
                            bug_id=crash_report.bug_id,
                            detected_by="crash_oracle",
                            source="crash_oracle",
                            supervisor_verdict="crash",
                            is_false_positive=False,
                            category=crash_report.category.value,
                            severity=crash_report.severity.value,
                            activity=crash_report.activity,
                            operation=crash_report.operation,
                            widget=crash_report.widget,
                            description=crash_report.description or crash_report.title,
                            confidence=crash_report.confidence,
                        )
                        if hasattr(crash_report, "additional_info") and crash_report.additional_info is not None:
                            crash_report.additional_info["detection_metrics"] = crash_timing_record
                        _record_bug_metric(results, experiment_logger, crash_timing_record)
                        results["bug_count"] = results.get("bug_count", 0) + 1
                    if experiment_logger and crash_report:
                        bug_record = crash_report.to_dict()
                        bug_record.update({
                            "detected_by": "crash_oracle",
                            "source": "crash_oracle",
                            "supervisor_reviewed": False,
                            "supervisor_verdict": "crash",
                            "is_false_positive": False,
                            "is_true_positive": True,
                            "detection_metrics": crash_timing_record,
                            "time_to_detection_seconds": crash_timing_record.get("asserted_elapsed_seconds") if crash_timing_record else None,
                            "time_to_verdict_seconds": crash_timing_record.get("elapsed_seconds") if crash_timing_record else None,
                            "step_count_to_detection": crash_timing_record.get("step_count_to_detection") if crash_timing_record else step,
                            **_copy_bug_report_paths(crash_report.bug_id, experiment_logger),
                        })
                        experiment_logger.log_bug(bug_record)
                    if crash_report:
                        memory_manager.record_reported_bug(
                            bug_id=crash_report.bug_id,
                            source="crash_oracle",
                            category=crash_report.category.value,
                            severity=crash_report.severity.value,
                            description=crash_report.description or crash_report.title,
                            activity=crash_report.activity,
                            operation=crash_report.operation,
                            widget=crash_report.widget,
                            confidence=crash_report.confidence,
                        )
                    _finish_experiment_step(
                        experiment_logger,
                        step_record,
                        "crashed",
                        "Application crashed",
                    )
                    break

                # 鑾峰彇瑙ｆ瀽缁撴灉鐢ㄤ簬璁板繂鏇存柊
                operation = parsed_action.operation if parsed_action else None
                widget_name = parsed_action.widget if parsed_action else None

                # 鏇存柊 LLM 杩斿洖鐨勫姛鑳戒俊鎭紙濡傛灉鏈夛級
                print(f"[DEBUG] parsed_action: {parsed_action}")
                if parsed_action:
                    print(f"[DEBUG] parsed_action.function_name: {parsed_action.function_name}")

                is_fallback_function = (
                    parsed_action is not None
                    and (parsed_action.function_name or "").strip().lower() == "fallback"
                )

                if parsed_action and parsed_action.function_name and not is_fallback_function:
                    # 浠?LLM 鍝嶅簲涓幏鍙栧姛鑳戒俊鎭?
                    print(f"[DEBUG] 浠?LLM 鑾峰彇鍔熻兘: {parsed_action.function_name}")
                    memory_manager.update_function(
                        parsed_action.function_name,
                        parsed_action.function_status or "testing"
                    )
                elif is_fallback_function:
                    print("[DEBUG] Ignored fallback function in function memory")
                    logger.log("Ignored fallback function in function memory", "WARN")
                else:
                    # 鍚庡鏈哄埗锛氫粠 Activity 鍚嶇О鎺ㄦ柇鍔熻兘
                    print(f"[DEBUG] 浠?Activity 鎺ㄦ柇鍔熻兘: {current_activity}")
                    inferred_function = memory_manager.infer_function_from_activity(current_activity)
                    print(f"[DEBUG] 鎺ㄦ柇缁撴灉: {inferred_function}")
                    memory_manager.update_function(inferred_function, "testing")

                print(f"[DEBUG] explored_functions: {memory_manager.explored_functions}")

            except Exception as action_error:
                print(f"[寮傚父] 鍔ㄤ綔鎵ц灞傚彂鐢熼敊璇? {action_error}")
                import traceback
                traceback.print_exc()

                step_result["status"] = "failed"
                step_result["error"] = f"Action execution error: {action_error}"
                results["failed_steps"] += 1
                results["step_details"].append(step_result)
                _finish_experiment_step(
                    experiment_logger,
                    step_record,
                    "failed",
                    f"Action execution error: {action_error}",
                )
                continue

            # ---------- g. 鐘舵€佸樊鍒嗘娴?----------
            print_substep_header("g. 鐘舵€佸樊鍒嗘娴?")
            ui_state_after = {}
            ui_state_after_prompt = ""
            widgets_after = []
            action_phase = "unknown"
            transient_change = "unknown"
            back_effect = ""

            # 绛夊緟 UI 鍝嶅簲
            print(f"[鐘舵€佹娴媇 绛夊緟 {STEP_WAIT_TIME} 绉掕 UI 鍝嶅簲...")
            time.sleep(STEP_WAIT_TIME)

            # 闈欓粯鎶撳彇鍚庣疆 UI 鐘舵€?
            try:
                ui_file_after, dump_attempts_after = _dump_ui_with_retry(
                    adb_controller,
                    context=f"step {step:03d} after",
                    logger=logger,
                )
                step_record["ui_dump_attempts_after"] = dump_attempts_after
                if ui_file_after:
                    step_record["xml_after_path"] = experiment_logger.copy_artifact(
                        ui_file_after,
                        "xml",
                        f"step_{step:03d}_after.xml",
                    )
                    activity_after = adb_controller.get_current_activity()
                    package_after = adb_controller.get_current_package()
                    if target_package and package_after and package_after != target_package:
                        widgets_after = []
                        step_record["external_app_after"] = True
                        step_record["detected_package_after"] = package_after
                    else:
                        widgets_after = gui_analyzer.parse_xml(ui_file_after, target_package=target_package)
                    device_focus_after = adb_controller.get_input_focus_state()
                    ui_state_after = analyze_ui_state(
                        ui_file_after,
                        target_package=target_package,
                        device_state=device_focus_after,
                    )
                    ui_state_after_prompt = format_ui_state_for_prompt(ui_state_after)
                    action_phase = classify_action_phase(parsed_action, ui_state_before, ui_state_after)
                    transient_change = transient_transition(ui_state_before, ui_state_after)

                    state_after = compute_ui_state_fingerprint(widgets_after)
                    step_record["activity_after"] = activity_after
                    step_record["package_after"] = package_after
                    step_record["widget_count_after"] = len(widgets_after)
                    step_record["widgets_after"] = summarize_widgets(widgets_after)
                    step_record["structure_fingerprint_after"] = compute_structure_fingerprint(widgets_after)
                    step_record["content_fingerprint_after"] = compute_content_fingerprint(widgets_after)
                    step_record["ui_state_fingerprint_before"] = state_before
                    step_record["ui_state_fingerprint_after"] = state_after
                    step_record["ui_changed"] = state_before != state_after
                    step_record["activity_changed"] = activity_before != activity_after
                    back_effect = classify_back_effect(
                        parsed_action,
                        ui_state_before,
                        ui_state_after,
                        activity_changed=step_record["activity_changed"],
                        ui_changed=step_record["ui_changed"],
                    )
                    step_record["actual_observation"] = summarize_ui_observation(activity_after, widgets_after)
                    step_record["ui_state_after"] = ui_state_after
                    step_record["ui_state_after_summary"] = ui_state_after_prompt
                    step_record["action_phase"] = action_phase
                    step_record["transient_transition"] = transient_change
                    step_record["back_effect"] = back_effect

                    screenshot_after = screenshot_manager.capture(activity_name=activity_after)
                    if screenshot_after:
                        step_record["screenshot_after_path"] = experiment_logger.copy_artifact(
                            screenshot_after.path,
                            "screenshots",
                            f"step_{step:03d}_after.png",
                        )

                    # 鐘舵€佸樊鍒嗘瘮杈?
                    if state_before == state_after and activity_before == activity_after:
                        print(f"[鐘舵€佸樊鍒哴 鈿狅笍 UI 鐘舵€佹湭鍙戠敓鍙樺寲")
                    else:
                        print(f"[鐘舵€佸樊鍒哴 鉁?鎿嶄綔鏈夋晥锛歎I 鐘舵€佸凡鏀瑰彉")
                        if activity_before != activity_after:
                            print(f"[鐘舵€佸樊鍒哴 Activity 鍒囨崲: {activity_before} -> {activity_after}")
                    logger.log(
                        f"Step {step:03d} state | {activity_before} -> {activity_after} | "
                        f"ui_changed={step_record['ui_changed']} | widgets={len(widgets)}->{len(widgets_after)} | "
                        f"phase={action_phase} | transient={transient_change}"
                        f"{' | back=' + back_effect if back_effect else ''}",
                        "STATE",
                    )
                else:
                    error_message = f"Unable to dump UI after action after {dump_attempts_after} attempts"
                    print(f"[鐘舵€佹娴媇 鏃犳硶鑾峰彇鍚庣疆 UI锛岃烦杩囩姸鎬佸樊鍒?({error_message})")
                    step_record["state_diff_error"] = error_message
                    logger.log(f"Step {step:03d} state | {error_message}", "WARN")
            except Exception as diff_error:
                print(f"[鐘舵€佹娴媇 宸垎妫€娴嬪紓甯? {diff_error}")
                step_record["state_diff_error"] = str(diff_error)
                logger.log(f"Step {step:03d} state | diff error: {_short_text(diff_error)}", "WARN")

            # ---------- h. 鏇存柊璁板繂 ----------
            print_substep_header("h. 鏇存柊璁板繂")

            # 鏋勫缓褰撳墠鎿嶄綔娴嬭瘯鐨?Widgets 鍒楄〃
            # 鍙寘鍚綋鍓嶆搷浣滅殑鐩爣 widget锛岃€屼笉鏄墍鏈夊巻鍙?widgets
            widgets_tested = []
            history_target_widget = _action_history_target(parsed_action) if parsed_action else widget_name
            if parsed_action and parsed_action.widget:
                _append_unique_widget(widgets_tested, parsed_action.widget, current_activity, memory_manager)

            # 濡傛灉鏄杈撳叆鎿嶄綔锛屾坊鍔犳墍鏈夎緭鍏ョ殑 widgets
            if parsed_action and parsed_action.input_sequence:
                for item in parsed_action.input_sequence:
                    # input_sequence 鏄笁鍏冪粍: (widget_name, input_text, content_desc)
                    input_widget_name = item[0] if isinstance(item, tuple) else item
                    _append_unique_widget(widgets_tested, input_widget_name, current_activity, memory_manager)

            if parsed_action and parsed_action.operation_widget:
                _append_unique_widget(widgets_tested, parsed_action.operation_widget, current_activity, memory_manager)

            # 璁板綍鎿嶄綔鍘嗗彶
            memory_manager.record_operation(
                activity_name=current_activity,
                widgets_tested=widgets_tested,
                operation=operation,
                target_widget=history_target_widget,
                success=True,
                page_description=parsed_action.page_description if parsed_action else None,
                ui_state_before=ui_state_before,
                ui_state_after=ui_state_after,
                action_phase=action_phase,
                transient_transition=transient_change,
                back_effect=back_effect,
                function_phase=parsed_action.function_phase if parsed_action else "",
                function_end=parsed_action.function_end if parsed_action else False,
                verification_target=parsed_action.verification_target if parsed_action else ""
            )

            # 璁板綍鍒版帰绱㈢紦瀛?
            if operation and history_target_widget:
                exploration_cache.record_exploration(current_activity, history_target_widget)

            print(f"[鎴愬姛] 璁板繂宸叉洿鏂帮紝褰撳墠姝ラ鏁? {memory_manager.get_step_count()}")

            # ---------- i. 鏇存柊璇佹嵁鍙欎簨妗堝嵎骞舵寜闇€瑙﹀彂搴忓垪绾у鏌?----------
            print_substep_header("i. 鏇存柊璇佹嵁鍙欎簨妗堝嵎")
            activity_after_for_dossier = step_record.get("activity_after") or current_activity
            if step_record.get("external_app_after"):
                current_widgets_for_review = []
            else:
                current_widgets_for_review = summarize_widgets(widgets_after if widgets_after else widgets)
            behavior_step_entry = behavior_dossier.append_step(
                step_index=step,
                action=parsed_action,
                activity_before=current_activity,
                activity_after=activity_after_for_dossier,
                step_record=step_record,
                widgets_before=summarize_widgets(widgets),
                widgets_after=current_widgets_for_review,
            )
            step_record["behavior_dossier_step"] = {
                "trace_id": (behavior_dossier.to_dict() or {}).get("trace_id"),
                "step_index": behavior_step_entry.get("step_index"),
                "function_phase": behavior_step_entry.get("function_phase"),
                "function_end": behavior_step_entry.get("function_end"),
                "verification_target": behavior_step_entry.get("verification_target"),
            }
            print(
                f"[琛屼负妗堝嵎] Trace={(behavior_dossier.to_dict() or {}).get('trace_id')} "
                f"phase={behavior_step_entry.get('function_phase')} "
                f"end={behavior_step_entry.get('function_end')}"
            )

            should_terminate_by_behavior_review = _handle_behavior_chain_review(
                behavior_dossier=behavior_dossier,
                supervisor=supervisor,
                memory_manager=memory_manager,
                experiment_logger=experiment_logger,
                bug_analysis_engine=bug_analysis_engine,
                screenshot_manager=screenshot_manager,
                step_index=step,
                current_activity=current_activity,
                activity_after=activity_after_for_dossier,
                parsed_action=parsed_action,
                operation=operation or "",
                history_target_widget=history_target_widget,
                widget_name=widget_name or "",
                step_record=step_record,
                step_result=step_result,
                results=results,
                ui_state=ui_state_after or ui_state_before,
                ui_state_prompt=ui_state_after_prompt or ui_state_before_prompt,
                current_widgets_for_review=current_widgets_for_review,
                run_started_perf=run_started_perf,
                logger=logger,
            )
            if should_terminate_by_behavior_review:
                results["step_details"].append(step_result)
                _finish_experiment_step(
                    experiment_logger,
                    step_record,
                    "bug_terminated",
                    step_result.get("error") or "Confirmed bug detected by behavior-chain review",
                )
                break

            # ========== NEW: 瀹氭湡鐩戠鑰呮紡妫€妫€娴?==========
            current_step = memory_manager.get_step_count()
            if supervisor.should_trigger_review(current_step):
                print(f"\n[鐩戠鑰匽 瑙﹀彂瀹氭湡瀹℃煡 (姝ラ {current_step})")

                # 鎴彇褰撳墠鎴浘
                review_screenshot = screenshot_manager.capture(activity_name=current_activity)
                review_screenshot_path = None
                if review_screenshot:
                    review_screenshot_path = experiment_logger.copy_artifact(
                        review_screenshot.path,
                        "screenshots",
                        f"step_{step:03d}_supervisor_review.png",
                    )

                if step_record.get("external_app_after"):
                    current_widgets_for_review = []
                else:
                    current_widgets_for_review = summarize_widgets(widgets_after if widgets_after else widgets)

                review_context = {
                    'current_activity': current_activity,
                    'operation_history': memory_manager.get_operation_history_chronological(),
                    'reported_bugs': memory_manager.get_reported_bugs(),
                    'ui_state': ui_state_after or ui_state_before,
                    'ui_state_prompt': ui_state_after_prompt or ui_state_before_prompt,
                    'current_widgets': current_widgets_for_review,
                }

                review_result = supervisor.check_missed_bugs(
                    context=review_context,
                    screenshots=[review_screenshot] if review_screenshot else None
                )
                supervisor_artifact_paths = _save_supervisor_artifacts(
                    experiment_logger,
                    supervisor,
                    step,
                    "missed_bug_check",
                )

                step_record["supervisor_review"] = {
                    "review_type": review_result.review_type,
                    "confidence": review_result.confidence,
                    "accepted": review_result.accepted,
                    "rejection_reason": review_result.rejection_reason,
                    "requires_more_verification": review_result.requires_more_verification,
                    "missed_bug_count": len(review_result.missed_bugs or []),
                    "suggestions": review_result.suggestions,
                    "screenshot_path": review_screenshot_path,
                    **supervisor_artifact_paths,
                }

                # 澶勭悊鍙戠幇鐨勬紡妫€ Bug
                if review_result.accepted and review_result.missed_bugs:
                    print(f"[鐩戠鑰匽 鍙戠幇 {len(review_result.missed_bugs)} 涓紡妫€ Bug")
                    saved_missed_count = 0
                    terminating_missed_count = 0

                    # 鐩戠鑰呯‘璁ょ殑婕忔 Bug 绔嬪嵆鐢熸垚鏍囧噯 BugReport
                    for i, bug in enumerate(review_result.missed_bugs, 1):
                        raw_category = bug.get("type", "unknown")
                        raw_severity = bug.get("severity", "Error")
                        bug_description = bug.get("description", "")
                        mapped_category = _map_bug_category(raw_category)
                        all_operation_history = memory_manager.get_operation_history_chronological()
                        missed_bug_widget = history_target_widget or widget_name or ""
                        mapped_severity = _normalize_bug_severity(
                            raw_severity=raw_severity,
                            category=mapped_category,
                            description=bug_description,
                            activity=current_activity,
                            operation=operation or "",
                            widget=missed_bug_widget,
                            operation_history=all_operation_history,
                            action_phase=action_phase,
                            evidence=bug.get("evidence", ""),
                        )
                        non_terminating_visual_bug = _is_non_terminating_visual_state_bug(
                            category=mapped_category.value,
                            severity=mapped_severity.value,
                            description=bug_description,
                            evidence=bug.get("evidence", ""),
                            current_widgets=current_widgets_for_review,
                        )
                        termination_policy = (
                            "continue_after_report"
                            if non_terminating_visual_bug
                            else "terminate_on_confirmed_bug"
                        )
                        duplicate_bug_id = _find_duplicate_reported_bug(
                            memory_manager,
                            mapped_category.value,
                            current_activity,
                            bug_description,
                            operation or "",
                            missed_bug_widget,
                        )
                        if duplicate_bug_id:
                            print(f"[鐩戠鑰匽 璺宠繃閲嶅婕忔 Bug锛屽凡瀛樺湪: {duplicate_bug_id}")
                            logger.log(f"璺宠繃閲嶅婕忔 Bug: {duplicate_bug_id}", "INFO")
                            continue

                        logger.log(
                            f"婕忔 Bug: [{mapped_severity.value}] {mapped_category.value} - {bug_description}",
                            "WARNING",
                        )

                        supervisor_bug_report = BugReport(
                            bug_id=bug.get("bug_id") or _make_bug_id(f"supervisor{current_step:04d}{i:02d}"),
                            timestamp=datetime.now(),
                            severity=mapped_severity,
                            category=mapped_category,
                            title=(bug_description or bug.get("evidence", "Supervisor detected missed bug"))[:100],
                            description=bug_description,
                            activity=current_activity,
                            operation=operation or "",
                            widget=missed_bug_widget,
                            screenshot_paths=[str(review_screenshot.path)] if review_screenshot else [],
                            confidence=review_result.confidence,
                            additional_info={
                                "detected_by": "supervisor",
                                "source": "missed_bug_check",
                                "evidence": bug.get("evidence", ""),
                                "supervisor_reasoning": review_result.reasoning,
                                "supervisor_confidence": review_result.confidence,
                                "ui_state": ui_state_after or ui_state_before,
                                "ui_state_summary": ui_state_after_prompt or ui_state_before_prompt,
                                "action_phase": action_phase,
                                "transient_transition": transient_change,
                                "model_severity": raw_severity,
                                "normalized_severity": mapped_severity.value,
                                "severity_source": "deterministic_policy",
                                "non_terminating": non_terminating_visual_bug,
                                "termination_policy": termination_policy,
                            },
                            operation_history=all_operation_history,
                        )
                        timing_record = _build_bug_timing_record(
                            run_started_perf=run_started_perf,
                            step_index=step,
                            bug_id=supervisor_bug_report.bug_id,
                            detected_by="supervisor",
                            source="missed_bug_check",
                            supervisor_verdict="missed_bug",
                            is_false_positive=False,
                            category=mapped_category.value,
                            severity=mapped_severity.value,
                            activity=supervisor_bug_report.activity,
                            operation=supervisor_bug_report.operation,
                            widget=supervisor_bug_report.widget,
                            description=supervisor_bug_report.description,
                            confidence=review_result.confidence,
                        )
                        timing_record["non_terminating"] = non_terminating_visual_bug
                        timing_record["termination_policy"] = termination_policy
                        supervisor_bug_report.additional_info["detection_metrics"] = timing_record
                        _record_bug_metric(results, experiment_logger, timing_record)
                        bug_analysis_engine.save_report(supervisor_bug_report)

                        report_paths = _copy_bug_report_paths(supervisor_bug_report.bug_id, experiment_logger)
                        bug_record = supervisor_bug_report.to_dict()
                        bug_record.update({
                            "detected_by": "supervisor",
                            "source": "missed_bug_check",
                            "supervisor_reviewed": True,
                            "supervisor_verdict": "missed_bug",
                            "is_false_positive": False,
                            "is_true_positive": True,
                            "detection_metrics": timing_record,
                            "time_to_detection_seconds": timing_record.get("asserted_elapsed_seconds"),
                            "time_to_verdict_seconds": timing_record.get("elapsed_seconds"),
                            "step_count_to_detection": timing_record.get("step_count_to_detection"),
                            "evidence_screenshot_path": review_screenshot_path,
                            "non_terminating": non_terminating_visual_bug,
                            "termination_policy": termination_policy,
                            **report_paths,
                            **supervisor_artifact_paths,
                        })
                        experiment_logger.log_bug(bug_record)

                        memory_manager.record_reported_bug(
                            bug_id=supervisor_bug_report.bug_id,
                            source="supervisor",
                            category=mapped_category.value,
                            severity=mapped_severity.value,
                            description=supervisor_bug_report.description,
                            activity=supervisor_bug_report.activity,
                            operation=supervisor_bug_report.operation,
                            widget=supervisor_bug_report.widget,
                            confidence=review_result.confidence,
                        )
                        results["bug_count"] = results.get("bug_count", 0) + 1
                        saved_missed_count += 1
                        if non_terminating_visual_bug:
                            logger.log(
                                f"闈為樆濉炶瑙夌姸鎬?Bug 宸蹭繚瀛橈紝缁х画娴嬭瘯: {supervisor_bug_report.bug_id}",
                                "WARNING",
                            )
                        else:
                            terminating_missed_count += 1

                    results["missed_bug_count"] = results.get("missed_bug_count", 0) + saved_missed_count
                    if terminating_missed_count > 0:
                        step_result["status"] = "bug_terminated"
                        step_result["error"] = "Confirmed bug detected by supervisor, test terminated"
                        results["step_details"].append(step_result)
                        _finish_experiment_step(
                            experiment_logger,
                            step_record,
                            "bug_terminated",
                            "Confirmed bug detected by supervisor, test terminated",
                        )
                        break
                elif not review_result.accepted:
                    print(f"[Supervisor] Missed-bug review not accepted: {review_result.rejection_reason}")
                    if experiment_logger:
                        experiment_logger.log_event("supervisor_missed_bug_review_inconclusive", {
                            "review_type": review_result.review_type,
                            "confidence": review_result.confidence,
                            "min_confidence": supervisor.min_confidence,
                            "requires_more_verification": review_result.requires_more_verification,
                            "rejection_reason": review_result.rejection_reason,
                            "missed_bug_count": len(review_result.missed_bugs or []),
                            **supervisor_artifact_paths,
                        })
                else:
                    print("[鐩戠鑰匽 鏈彂鐜版紡妫€ Bug")

            # 鏍囪姝ラ鎴愬姛
            step_result["status"] = "success"
            results["successful_steps"] += 1
            results["step_details"].append(step_result)
            _finish_experiment_step(experiment_logger, step_record, "success")

        except Exception as e:
            print(f"[寮傚父] 姝ラ {step} 鍙戠敓鏈崟鑾风殑寮傚父: {e}")
            import traceback
            traceback.print_exc()

            step_result["status"] = "failed"
            step_result["error"] = str(e)
            results["failed_steps"] += 1
            results["step_details"].append(step_result)
            logger.log(f"Step {step:03d} failed | {_short_text(e)}", "FAIL")
            _finish_experiment_step(experiment_logger, step_record, "failed", str(e))

            print("[鎭㈠] 缁х画鎵ц涓嬩竴涓楠?..")
            continue

    # ========== 娴嬭瘯鎬荤粨 ==========
    print("\n" + "=" * 70)
    print("  娴嬭瘯瀹屾垚 - 缁撴灉姹囨€?")
    print("=" * 70)

    results["total_elapsed_seconds"] = _elapsed_seconds(run_started_perf)
    results["total_elapsed_minutes"] = round(results["total_elapsed_seconds"] / 60, 3)
    actual_steps = results['successful_steps'] + results['failed_steps'] + results['skipped_steps']
    success_rate = results['successful_steps'] / actual_steps * 100 if actual_steps > 0 else 0

    # 璁板綍鍒版棩蹇?
    logger.section("娴嬭瘯瀹屾垚")
    logger.log(
        f"summary | executed={actual_steps}/{results['total_steps']} | "
        f"success={results['successful_steps']} | failed={results['failed_steps']} | "
        f"skipped={results['skipped_steps']} | crashed={'yes' if results['crashed'] else 'no'} | "
        f"success_rate={success_rate:.1f}% | elapsed={results['total_elapsed_seconds']}s | "
        f"first_true_bug={results.get('first_true_bug_elapsed_seconds')}s@step{results.get('first_true_bug_step')}",
        "INFO",
    )

    print(f"\n  鎬绘楠ゆ暟:   {results['total_steps']}")
    print(f"  鎴愬姛姝ラ:   {results['successful_steps']}")
    print(f"  澶辫触姝ラ:   {results['failed_steps']}")
    print(f"  璺宠繃姝ラ:   {results['skipped_steps']}")
    print(f"  鏄惁宕╂簝:   {'鏄?' if results['crashed'] else '鍚?'}")

    print(f"  鎴愬姛鐜?     {success_rate:.1f}%")

    print(f"  first_bug: {results.get('first_bug_elapsed_seconds')}s @ step {results.get('first_bug_step')} "
          f"(true_positive={results.get('first_bug_is_true_positive')})")
    print(f"  first_true_bug: {results.get('first_true_bug_elapsed_seconds')}s @ step {results.get('first_true_bug_step')}")
    print(f"  TP/FP:      {results.get('true_positive_count', 0)} / {results.get('false_positive_count', 0)}")
    print(f"  behavior_chain_bugs: {results.get('behavior_chain_bug_count', 0)}")
    print(f"  elapsed:    {results.get('total_elapsed_seconds')}s")

    print("\n" + "-" * 70)
    print("  鍚勬楠よ鎯?")
    print("-" * 70)

    for detail in results["step_details"]:
        status_icon = {
            "success": "[OK]",
            "failed": "[FAIL]",
            "skipped": "[SKIP]",
            "crashed": "[CRASH]"
        }.get(detail["status"], "[?]")

        print(f"  姝ラ {detail['step_index']}: {status_icon} "
              f"Activity={detail['activity']}, "
              f"鎿嶄綔={detail['operation'] or 'N/A'}, "
              f"鎺т欢={detail['widget'] or 'N/A'}")

        if detail["error"]:
            print(f"           閿欒: {detail['error']}")

    print("\n" + "=" * 70)
    print("  GPTDroid LLM 鑷富鎺㈢储娴嬭瘯瀹屾垚")
    print("=" * 70)

    # 杈撳嚭鏃ュ織鏂囦欢璺緞
    log_path = logger.get_log_path()
    print(f"\n[鏃ュ織鏂囦欢] 娴嬭瘯鍘嗗彶宸蹭繚瀛樺埌: {log_path}")
    print(f"[缁撴瀯鍖栫粨鏋淽 瀹為獙鏁版嵁宸蹭繚瀛樺埌: {experiment_logger.run_dir}")
    print(f"[鏃ュ織鍒嗙被] 鏃ュ織鏂囦欢鎸?App 鍚嶇О鍜屽紑濮嬫椂闂村綊妗ｅ埌: {log_path.parent}")

    experiment_logger.close(summary={
        "total_steps": results["total_steps"],
        "successful_steps": results["successful_steps"],
        "failed_steps": results["failed_steps"],
        "skipped_steps": results["skipped_steps"],
        "crashed": results["crashed"],
        "bug_count": results.get("bug_count", 0),
        "missed_bug_count": results.get("missed_bug_count", 0),
        "behavior_chain_bug_count": results.get("behavior_chain_bug_count", 0),
        "true_positive_count": results.get("true_positive_count", 0),
        "false_positive_count": results.get("false_positive_count", 0),
        "first_bug_elapsed_seconds": results.get("first_bug_elapsed_seconds"),
        "first_bug_step": results.get("first_bug_step"),
        "first_bug_id": results.get("first_bug_id"),
        "first_bug_is_true_positive": results.get("first_bug_is_true_positive"),
        "first_true_bug_elapsed_seconds": results.get("first_true_bug_elapsed_seconds"),
        "first_true_bug_step": results.get("first_true_bug_step"),
        "first_true_bug_id": results.get("first_true_bug_id"),
        "first_false_positive_elapsed_seconds": results.get("first_false_positive_elapsed_seconds"),
        "first_false_positive_step": results.get("first_false_positive_step"),
        "first_false_positive_id": results.get("first_false_positive_id"),
        "total_elapsed_seconds": results.get("total_elapsed_seconds"),
        "total_elapsed_minutes": results.get("total_elapsed_minutes"),
        "bug_timeline": results.get("bug_timeline", []),
        "success_rate": success_rate,
    })

    # 鍏抽棴鏃ュ織
    logger.close()

    return results


def main():
    """涓诲嚱鏁板叆鍙?"""
    try:
        run_outer_loop()
    except KeyboardInterrupt:
        print("\n[涓柇] 鐢ㄦ埛鎵嬪姩缁堟娴嬭瘯")
    except Exception as e:
        print(f"\n[鑷村懡閿欒] {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
