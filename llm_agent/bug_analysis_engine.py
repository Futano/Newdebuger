"""
Bug Analysis Engine Module
Crash detection and bug report generation
Simplified version - only crash detection (logic errors detected via prompt engineering)
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from env_interactor.adb_utils import ADBController
    from .screenshot_manager import ScreenshotManager


class BugSeverity(Enum):
    """Bug severity levels"""
    CRITICAL = "Critical"    # App crash, data loss, security issue
    ERROR = "Error"          # Feature malfunction, incorrect behavior
    WARNING = "Warning"      # UX issue, minor problem
    INFO = "Info"            # Suggestion, optimization


class BugCategory(Enum):
    """Bug category classification"""
    CRASH = "crash"                           # Application crash
    CALCULATION_ERROR = "calculation_error"   # Wrong calculation result
    DATA_INCONSISTENCY = "data_inconsistency" # Cross-page data mismatch
    FUNCTION_ANOMALY = "function_anomaly"     # Feature not working
    UI_STATE_ERROR = "ui_state_error"         # UI state/rendering/overlay issue
    UNKNOWN = "unknown"                       # Uncategorized


LOGIC_ERROR_TYPE_TO_BUG_CATEGORY = {
    "calculation_error": BugCategory.CALCULATION_ERROR,
    "data_inconsistency": BugCategory.DATA_INCONSISTENCY,
    "function_anomaly": BugCategory.FUNCTION_ANOMALY,
    "ui_state_error": BugCategory.UI_STATE_ERROR,
}


BUG_CATEGORY_ALIASES = {
    "crash": BugCategory.CRASH,
    "calculation_error": BugCategory.CALCULATION_ERROR,
    "calc_error": BugCategory.CALCULATION_ERROR,
    "wrong_calculation": BugCategory.CALCULATION_ERROR,
    "data_inconsistency": BugCategory.DATA_INCONSISTENCY,
    "data_mismatch": BugCategory.DATA_INCONSISTENCY,
    "state_mismatch": BugCategory.DATA_INCONSISTENCY,
    "function_anomaly": BugCategory.FUNCTION_ANOMALY,
    "functional_anomaly": BugCategory.FUNCTION_ANOMALY,
    "logic_error": BugCategory.FUNCTION_ANOMALY,
    "ui_error": BugCategory.UI_STATE_ERROR,
    "ui_state_error": BugCategory.UI_STATE_ERROR,
    "visual_anomaly": BugCategory.UI_STATE_ERROR,
    "layout_error": BugCategory.UI_STATE_ERROR,
    "rendering_error": BugCategory.UI_STATE_ERROR,
    "unknown": BugCategory.UNKNOWN,
}


def normalize_bug_category(value: Any) -> BugCategory:
    """Normalize any detector/model category into the canonical BugCategory."""
    if isinstance(value, BugCategory):
        return value

    if hasattr(value, "value"):
        value = value.value

    key = str(value or "").strip().lower()
    key = "".join(ch if ch.isalnum() else "_" for ch in key).strip("_")
    if key in LOGIC_ERROR_TYPE_TO_BUG_CATEGORY:
        return LOGIC_ERROR_TYPE_TO_BUG_CATEGORY[key]
    return BUG_CATEGORY_ALIASES.get(key, BugCategory.UNKNOWN)


@dataclass
class BugReport:
    """
    Comprehensive bug report

    Attributes:
        bug_id: Unique identifier
        timestamp: When the bug was detected
        severity: Bug severity level
        category: Bug category
        title: Short description
        description: Detailed description
        activity: Current activity
        operation: Operation that triggered the bug
        widget: Widget involved
        crash_log: Crash log if applicable
        screenshot_paths: Paths to screenshot evidence
        screenshot_base64: Base64 encoded screenshots (for embedding in reports)
        root_cause: Analysis of root cause
        fix_suggestion: Suggested fix
        reproduction_steps: Steps to reproduce
        confidence: Confidence level of analysis
        additional_info: Additional metadata
        operation_history: List of recent operations for reproduction
    """
    bug_id: str
    timestamp: datetime
    severity: BugSeverity
    category: BugCategory
    title: str
    description: str = ""
    activity: str = ""
    operation: str = ""
    widget: str = ""
    crash_log: str = ""
    screenshot_paths: List[str] = field(default_factory=list)
    screenshot_base64: List[str] = field(default_factory=list)  # Base64 encoded images
    root_cause: str = ""
    fix_suggestion: str = ""
    reproduction_steps: List[str] = field(default_factory=list)
    confidence: float = 0.0
    additional_info: Dict[str, Any] = field(default_factory=dict)
    operation_history: List[Dict] = field(default_factory=list)

    def load_screenshots_as_base64(self) -> None:
        """
        Load screenshots from paths and convert to base64

        This should be called before saving the report to embed images.
        """
        import base64

        self.screenshot_base64 = []
        for path in self.screenshot_paths:
            try:
                img_path = Path(path)
                if img_path.exists():
                    with open(img_path, 'rb') as f:
                        img_data = f.read()
                    b64_data = base64.b64encode(img_data).decode('utf-8')
                    self.screenshot_base64.append(b64_data)
                    print(f"[BugReport] 已加载截图: {img_path.name}")
            except Exception as e:
                print(f"[BugReport] 加载截图失败 {path}: {e}")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        # Convert screenshot paths to absolute paths
        abs_screenshot_paths = []
        for p in self.screenshot_paths:
            path = Path(p)
            abs_screenshot_paths.append(str(path.resolve()) if path.exists() else str(p))

        return {
            "bug_id": self.bug_id,
            "timestamp": self.timestamp.isoformat(),
            "severity": self.severity.value,
            "category": self.category.value,
            "title": self.title,
            "description": self.description,
            "activity": self.activity,
            "operation": self.operation,
            "widget": self.widget,
            "crash_log": self.crash_log[:500] if self.crash_log else "",  # Truncate
            "screenshot_paths": abs_screenshot_paths,
            "screenshot_base64": self.screenshot_base64,  # Embedded images
            "root_cause": self.root_cause,
            "fix_suggestion": self.fix_suggestion,
            "reproduction_steps": self.reproduction_steps,
            "confidence": self.confidence,
            "additional_info": self.additional_info,
            "operation_history": self.operation_history
        }

    def to_markdown(self) -> str:
        """Convert to markdown format for reporting"""
        lines = [
            f"# Bug Report: {self.bug_id}",
            "",
            f"**Timestamp**: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Severity**: {self.severity.value}",
            f"**Category**: {self.category.value}",
            "",
            "---",
            "",
            "## Summary",
            f"**{self.title}**",
            ""
        ]

        # 添加 LLM 推理过程（如果有）
        llm_thought = self.additional_info.get("llm_thought", "")
        if llm_thought:
            lines.extend([
                "## LLM Analysis (Thought Process)",
                "> " + llm_thought.replace("\n", "\n> "),
                ""
            ])

        lines.extend([
            "## Bug Details",
            f"- **Activity**: `{self.activity}`",
            f"- **Operation**: `{self.operation}`",
            f"- **Widget**: `{self.widget}`",
            ""
        ])

        # 添加额外信息
        if self.additional_info:
            target_coords = self.additional_info.get("target_coordinates")
            if target_coords:
                lines.append(f"- **Target Coordinates**: {target_coords}")

            step_num = self.additional_info.get("step_number")
            if step_num:
                lines.append(f"- **Detected at Step**: {step_num}")

            widget_type = self.additional_info.get("widget_type")
            if widget_type:
                lines.append(f"- **Widget Type**: {widget_type}")

            function_name = self.additional_info.get("function_name")
            if function_name:
                lines.append(f"- **Testing Function**: {function_name}")

            lines.append("")

        if self.description:
            lines.extend([
                "## Full Description",
                self.description,
                ""
            ])

        if self.reproduction_steps:
            lines.extend([
                "## Reproduction Steps",
                "",
                "```",
                *[f"{step}" for step in self.reproduction_steps],
                "```",
                ""
            ])

        if self.crash_log:
            lines.extend([
                "## Crash Log",
                "```",
                self.crash_log[:2000],  # Truncate for readability
                "```",
                ""
            ])

        if self.screenshot_paths or self.screenshot_base64:
            lines.extend([
                "## Screenshots",
                ""
            ])
            # 如果有 base64 图片，直接嵌入
            if self.screenshot_base64:
                for i, b64_data in enumerate(self.screenshot_base64, 1):
                    lines.append(f"### Screenshot {i}")
                    lines.append("")
                    # 使用 HTML img 标签嵌入 base64 图片（Markdown 兼容）
                    lines.append(f'<img src="data:image/png;base64,{b64_data}" alt="Screenshot {i}" style="max-width: 100%; height: auto;">')
                    lines.append("")
            # 否则显示路径（向后兼容）
            elif self.screenshot_paths:
                for i, p in enumerate(self.screenshot_paths, 1):
                    path = Path(p)
                    if path.exists():
                        abs_path = str(path.resolve())
                        lines.append(f"### Screenshot {i}")
                        lines.append(f"- Path: `{abs_path}`")
                        lines.append("")
                    else:
                        lines.append(f"### Screenshot {i}")
                        lines.append(f"- Path: `{p}` (not found)")
                        lines.append("")

        if self.root_cause and self.root_cause != llm_thought:
            lines.extend([
                "## Root Cause Analysis",
                self.root_cause,
                ""
            ])

        if self.fix_suggestion:
            lines.extend([
                "## Fix Suggestion",
                self.fix_suggestion,
                ""
            ])

        if self.operation_history:
            history = self._operation_history_chronological()
            total_steps = len(history)
            lines.extend([
                "---",
                "",
                f"## Operation History (All {total_steps} Steps)",
                "",
                "| Step | Status | Activity | Operation | Widget |",
                "|------|--------|----------|-----------|--------|"
            ])
            # 显示所有历史操作（不再限制为最后 10 条）
            for i, op in enumerate(history, 1):
                step_index = op.get("step_index", i)
                activity = op.get("activity_name", "Unknown")
                operation = op.get("operation", "unknown")
                widget = op.get("target_widget", "")
                success = "✅" if op.get("success", True) else "❌"
                lines.append(f"| {step_index} | {success} | {activity[:30]} | {operation} | {widget[:20]} |")
            lines.append("")

        # 添加元数据
        lines.extend([
            "---",
            "",
            "## Metadata",
            f"- **Confidence**: {self.confidence}",
            f"- **Report Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ""
        ])

        return "\n".join(lines)

    def _operation_history_chronological(self) -> List[Dict]:
        """Return operation history in real execution order for reports."""
        history = list(self.operation_history or [])
        indexed = [op for op in history if isinstance(op, dict) and op.get("step_index") is not None]
        if len(indexed) == len(history):
            return sorted(history, key=lambda op: op.get("step_index", 0))
        return list(reversed(history))


class CrashDetector:
    """
    Simple crash detector wrapper

    Wraps ADB crash detection with severity classification
    """

    def __init__(self, adb_controller: Optional["ADBController"] = None):
        self.adb_controller = adb_controller

    def set_adb_controller(self, adb_controller: "ADBController") -> None:
        """Set the ADB controller"""
        self.adb_controller = adb_controller

    def check_for_crash(self, target_package: str = None) -> tuple:
        """
        Check for application crash

        Args:
            target_package: Target app package for filtering false positives

        Returns:
            Tuple (crash_detected: bool, crash_log: str)
        """
        if not self.adb_controller:
            return False, ""

        crash_log = self.adb_controller.check_for_crash(target_package=target_package)
        return bool(crash_log), crash_log

    def classify_crash_severity(self, crash_log: str) -> BugSeverity:
        """
        Classify crash severity based on log content

        Args:
            crash_log: The crash log

        Returns:
            BugSeverity level
        """
        if not crash_log:
            return BugSeverity.INFO

        crash_lower = crash_log.lower()

        # Critical: Native crash, ANR, or fatal exception
        if any(keyword in crash_lower for keyword in ["fatal exception", "native crash", "anr", "signal 11"]):
            return BugSeverity.CRITICAL

        # Error: Regular Java exceptions
        if any(keyword in crash_lower for keyword in ["exception", "error", "crash"]):
            return BugSeverity.ERROR

        return BugSeverity.WARNING


class BugAnalysisEngine:
    """
    Bug Analysis Engine

    Simplified version - only crash detection
    Logic errors are detected via evidence-grounded prompt review.

    Features:
    - CrashDetector: For application crash detection
    - Severity classification (Critical/Error/Warning/Info)
    - Bug report generation
    """

    def __init__(
        self,
        adb_controller: Optional["ADBController"] = None,
        screenshot_manager: Optional["ScreenshotManager"] = None,
        report_dir: str = "bug_reports"
    ):
        """
        Initialize Bug Analysis Engine

        Args:
            adb_controller: ADB controller for crash detection
            screenshot_manager: Screenshot manager for visual evidence
            report_dir: Directory to save bug reports
        """
        self.adb_controller = adb_controller
        self.screenshot_manager = screenshot_manager
        self.report_dir = Path(report_dir)

        # Initialize crash detector
        self.crash_detector = CrashDetector(adb_controller)

        # Bug tracking
        self._bug_counter = 0
        self._bug_history: List[BugReport] = []

        # Ensure report directory exists
        self.report_dir.mkdir(parents=True, exist_ok=True)

        print(f"[BugAnalysisEngine] 初始化完成，报告目录: {self.report_dir}")

    def set_adb_controller(self, adb_controller: "ADBController") -> None:
        """Set ADB controller"""
        self.adb_controller = adb_controller
        self.crash_detector.set_adb_controller(adb_controller)

    def set_screenshot_manager(self, screenshot_manager: "ScreenshotManager") -> None:
        """Set screenshot manager"""
        self.screenshot_manager = screenshot_manager

    def check_for_crash(self, target_package: str = None) -> bool:
        """
        Check for application crash

        Args:
            target_package: Target app package for filtering false positives

        Returns:
            True if crash detected, False otherwise
        """
        crash_detected, _ = self.crash_detector.check_for_crash(target_package=target_package)
        return crash_detected

    def create_crash_report(
        self,
        activity_name: str,
        operation: str,
        widget: str = "",
        operation_history: List[Dict] = None,
        target_package: str = None
    ) -> Optional[BugReport]:
        """
        Create a crash bug report

        Args:
            activity_name: Current activity
            operation: Operation that triggered the crash
            widget: Widget that was operated on
            operation_history: List of recent operations for reproduction
            target_package: Target app package for filtering false positives

        Returns:
            BugReport if crash detected, None otherwise
        """
        crash_detected, crash_log = self.crash_detector.check_for_crash(target_package=target_package)

        if not crash_detected:
            return None

        self._bug_counter += 1
        bug_id = f"BUG-{datetime.now().strftime('%Y%m%d')}-{self._bug_counter:04d}"

        # Classify severity
        severity = self.crash_detector.classify_crash_severity(crash_log)

        # Get screenshots
        screenshot_paths = []
        if self.screenshot_manager:
            latest = self.screenshot_manager.get_latest()
            if latest:
                screenshot_paths.append(str(latest.path))

        # Create report
        report = BugReport(
            bug_id=bug_id,
            timestamp=datetime.now(),
            severity=severity,
            category=BugCategory.CRASH,
            title=f"Application crash during {operation}",
            description=f"Application crashed after {operation} on {widget}",
            activity=activity_name,
            operation=operation,
            widget=widget,
            crash_log=crash_log,
            screenshot_paths=screenshot_paths,
            additional_info={
                "detected_by": "crash_detector",
                "source": "crash_oracle",
                "target_package": target_package,
            },
            operation_history=operation_history or []
        )

        # Save report and add to history
        self.save_report(report)

        return report

    def save_report(self, report: BugReport, add_to_history: bool = True) -> None:
        """Save any BugReport immediately and optionally keep it in engine history."""
        self._save_report(report)
        if add_to_history and all(existing.bug_id != report.bug_id for existing in self._bug_history):
            self._bug_history.append(report)

    def _save_report(self, report: BugReport) -> None:
        """Save bug report to file immediately"""
        try:
            # Ensure directory exists
            self.report_dir.mkdir(parents=True, exist_ok=True)

            # Load screenshots as base64 before saving
            report.load_screenshots_as_base64()

            # Save as JSON
            json_path = self.report_dir / f"{report.bug_id}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

            # Save as Markdown
            md_path = self.report_dir / f"{report.bug_id}.md"
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(report.to_markdown())

            # 打印保存确认
            print(f"[BugAnalysisEngine] ✅ Bug报告已实时保存:")
            print(f"  - JSON: {json_path}")
            print(f"  - Markdown: {md_path}")

        except Exception as e:
            print(f"[BugAnalysisEngine] ❌ 保存报告失败: {e}")
            import traceback
            traceback.print_exc()

    def get_bug_history(self) -> List[BugReport]:
        """Get all bug reports"""
        return self._bug_history.copy()

    def get_bugs_by_severity(self, severity: BugSeverity) -> List[BugReport]:
        """Get bugs by severity level"""
        return [b for b in self._bug_history if b.severity == severity]

    def get_bugs_by_category(self, category: BugCategory) -> List[BugReport]:
        """Get bugs by category"""
        return [b for b in self._bug_history if b.category == category]

    def get_statistics(self) -> Dict[str, Any]:
        """Get bug statistics"""
        by_severity = {}
        by_category = {}

        for bug in self._bug_history:
            # Count by severity
            sev_name = bug.severity.value
            by_severity[sev_name] = by_severity.get(sev_name, 0) + 1

            # Count by category
            cat_name = bug.category.value
            by_category[cat_name] = by_category.get(cat_name, 0) + 1

        return {
            "total_bugs": len(self._bug_history),
            "by_severity": by_severity,
            "by_category": by_category,
            "report_dir": str(self.report_dir)
        }

    def clear_history(self) -> None:
        """Clear bug history"""
        self._bug_history.clear()
        self._bug_counter = 0


# Test entry point
if __name__ == "__main__":
    print("=" * 60)
    print("BugAnalysisEngine 测试")
    print("=" * 60)

    # Create engine
    engine = BugAnalysisEngine()

    # Create a test bug report
    test_report = BugReport(
        bug_id="BUG-20260326-0001",
        timestamp=datetime.now(),
        severity=BugSeverity.ERROR,
        category=BugCategory.CRASH,
        title="Test crash",
        description="Application crashed during testing",
        activity="MainActivity",
        operation="click",
        widget="submitButton",
        crash_log="FATAL EXCEPTION: NullPointerException\n\tat com.example.MainActivity.onClick(MainActivity.java:42)"
    )

    print("\n[测试报告]")
    print(test_report.to_markdown())

    # Get statistics
    print("\n[统计信息]")
    engine._bug_history.append(test_report)
    stats = engine.get_statistics()
    print(stats)
