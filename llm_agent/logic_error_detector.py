"""
Logic Error Detector Module
Detects logic errors in Android apps through multimodal analysis

Detection types:
- Calculation errors (wrong numerical results)
- Data inconsistency (cross-page data mismatch)
- Function anomaly (feature not working as expected)
- UI state error (UI rendering or state issues)
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, TYPE_CHECKING

from .bug_analysis_engine import normalize_bug_category

if TYPE_CHECKING:
    from .multimodal_llm_client import MultimodalLLMClient
    from .screenshot_manager import ScreenshotData, ScreenshotManager


class LogicErrorType(Enum):
    """Types of logic errors that can be detected"""
    CALCULATION_ERROR = "calculation_error"      # 数值计算错误
    DATA_INCONSISTENCY = "data_inconsistency"    # 跨页面数据不一致
    FUNCTION_ANOMALY = "function_anomaly"        # 功能逻辑异常
    UI_STATE_ERROR = "ui_state_error"           # UI 状态错误


class LogicErrorSeverity(Enum):
    """Severity levels for logic errors"""
    CRITICAL = "Critical"    # 核心功能完全不可用
    ERROR = "Error"          # 功能异常但可恢复
    WARNING = "Warning"      # 轻微问题或潜在风险
    INFO = "Info"            # 信息提示


@dataclass
class LogicErrorReport:
    """
    Report of a detected logic error

    Attributes:
        error_type: Type of logic error
        severity: Severity level
        description: Human-readable description
        location: Where the error was detected (activity, widget)
        expected: Expected behavior/value
        actual: Actual behavior/value
        evidence: Supporting evidence (logs, screenshots)
        suggestions: Suggested fixes
        timestamp: When the error was detected
    """
    error_type: LogicErrorType
    severity: LogicErrorSeverity
    description: str
    location: str = ""
    expected: str = ""
    actual: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        bug_category = normalize_bug_category(self.error_type)
        return {
            "error_type": self.error_type.value,
            "bug_category": bug_category.value,
            "severity": self.severity.value,
            "description": self.description,
            "location": self.location,
            "expected": self.expected,
            "actual": self.actual,
            "evidence": self.evidence,
            "suggestions": self.suggestions,
            "timestamp": self.timestamp.isoformat()
        }


class LogicErrorDetector:
    """
    Logic Error Detector

    Detects various types of logic errors in Android apps:
    1. Calculation errors - Wrong numerical results
    2. Data inconsistency - Cross-page data mismatch
    3. Function anomaly - Feature not working as expected
    4. UI state error - UI rendering or state issues
    """

    def __init__(
        self,
        llm_client: Optional["MultimodalLLMClient"] = None,
        screenshot_manager: Optional["ScreenshotManager"] = None
    ):
        """
        Initialize Logic Error Detector

        Args:
            llm_client: MultimodalLLMClient for AI-powered analysis
            screenshot_manager: ScreenshotManager for visual evidence
        """
        self.llm_client = llm_client
        self.screenshot_manager = screenshot_manager

        # Detected errors history
        self._detected_errors: List[LogicErrorReport] = []

        # Calculation rules for validation
        self._calculation_rules: Dict[str, Dict[str, Any]] = {}

        print("[LogicErrorDetector] 初始化完成")

    def set_llm_client(self, llm_client: "MultimodalLLMClient") -> None:
        """Set the LLM client"""
        self.llm_client = llm_client

    def set_screenshot_manager(self, screenshot_manager: "ScreenshotManager") -> None:
        """Set the screenshot manager"""
        self.screenshot_manager = screenshot_manager

    # ==================== Calculation Error Detection ====================

    def register_calculation_rule(
        self,
        rule_id: str,
        input_widgets: List[str],
        output_widget: str,
        operation: str,
        tolerance: float = 0.01
    ) -> None:
        """
        Register a calculation validation rule

        Args:
            rule_id: Unique identifier for this rule
            input_widgets: List of widget IDs providing input values
            output_widget: Widget ID where the result should appear
            operation: Operation type (sum, multiply, average, custom)
            tolerance: Acceptable difference between expected and actual
        """
        self._calculation_rules[rule_id] = {
            "input_widgets": input_widgets,
            "output_widget": output_widget,
            "operation": operation,
            "tolerance": tolerance
        }
        print(f"[LogicErrorDetector] 注册计算规则: {rule_id}")

    def validate_calculation(
        self,
        rule_id: str,
        current_values: Dict[str, float]
    ) -> Optional[LogicErrorReport]:
        """
        Validate a calculation against registered rules

        Args:
            rule_id: Rule to validate against
            current_values: Current widget values (widget_id -> value)

        Returns:
            LogicErrorReport if error detected, None otherwise
        """
        if rule_id not in self._calculation_rules:
            print(f"[LogicErrorDetector] 未知的计算规则: {rule_id}")
            return None

        rule = self._calculation_rules[rule_id]
        input_widgets = rule["input_widgets"]
        output_widget = rule["output_widget"]
        operation = rule["operation"]
        tolerance = rule["tolerance"]

        # Get input values
        input_values = []
        for widget_id in input_widgets:
            value = current_values.get(widget_id)
            if value is None:
                print(f"[LogicErrorDetector] 缺少输入值: {widget_id}")
                return None
            input_values.append(value)

        # Get output value
        actual_output = current_values.get(output_widget)
        if actual_output is None:
            print(f"[LogicErrorDetector] 缺少输出值: {output_widget}")
            return None

        # Calculate expected output
        expected_output = self._calculate_expected(input_values, operation)

        # Compare with tolerance
        difference = abs(expected_output - actual_output)
        if difference > tolerance:
            return LogicErrorReport(
                error_type=LogicErrorType.CALCULATION_ERROR,
                severity=LogicErrorSeverity.ERROR,
                description=f"计算结果错误: {operation} 操作",
                location=output_widget,
                expected=f"{expected_output:.2f}",
                actual=f"{actual_output:.2f}",
                evidence={
                    "input_values": {w: current_values.get(w) for w in input_widgets},
                    "difference": difference,
                    "tolerance": tolerance
                },
                suggestions=[
                    f"检查 {output_widget} 的计算逻辑",
                    f"预期值: {expected_output:.2f}, 实际值: {actual_output:.2f}"
                ]
            )

        return None

    def _calculate_expected(self, values: List[float], operation: str) -> float:
        """Calculate expected result based on operation"""
        if operation == "sum":
            return sum(values)
        elif operation == "multiply":
            result = 1
            for v in values:
                result *= v
            return result
        elif operation == "average":
            return sum(values) / len(values) if values else 0
        elif operation == "subtract":
            return values[0] - sum(values[1:]) if len(values) > 1 else values[0]
        elif operation == "divide":
            return values[0] / values[1] if len(values) > 1 and values[1] != 0 else 0
        else:
            print(f"[LogicErrorDetector] 未知的操作类型: {operation}")
            return 0

    # ==================== Function Anomaly Detection ====================

    def detect_function_anomaly(
        self,
        function_name: str,
        expected_behavior: str,
        actual_behavior: str,
        activity_name: str = "",
        use_visual_analysis: bool = True
    ) -> Optional[LogicErrorReport]:
        """
        Detect function anomalies using LLM analysis

        Args:
            function_name: Name of the function being tested
            expected_behavior: Expected behavior description
            actual_behavior: Actual behavior description
            activity_name: Current activity
            use_visual_analysis: Whether to use visual analysis

        Returns:
            LogicErrorReport if anomaly detected, None otherwise
        """
        if not self.llm_client:
            # Simple text comparison without LLM
            if expected_behavior.lower() != actual_behavior.lower():
                return LogicErrorReport(
                    error_type=LogicErrorType.FUNCTION_ANOMALY,
                    severity=LogicErrorSeverity.ERROR,
                    description=f"功能异常: {function_name}",
                    location=activity_name,
                    expected=expected_behavior,
                    actual=actual_behavior,
                    suggestions=["检查功能的实现逻辑"]
                )
            return None

        # Use LLM for intelligent analysis
        try:
            from .multimodal_llm_client import BugContext
            from .prompt_templates import MultimodalPromptTemplate

            bug_context = BugContext(
                bug_type="function_anomaly",
                description=f"功能 '{function_name}' 行为异常",
                activity_name=activity_name
            )

            prompt = MultimodalPromptTemplate.logic_error_detection_prompt(
                error_type="function_anomaly",
                expected_value=expected_behavior,
                actual_value=actual_behavior,
                context=f"Function: {function_name}, Activity: {activity_name}"
            )

            screenshots = []
            if use_visual_analysis and self.screenshot_manager:
                screenshots = self.screenshot_manager.get_history(limit=2)

            result = self.llm_client.analyze_bug(bug_context, screenshots, prompt)

            if result.severity in ["Critical", "Error"]:
                # 使用映射字典进行类型转换（避免类型检查器警告）
                severity_map = {
                    "Critical": LogicErrorSeverity.CRITICAL,
                    "Error": LogicErrorSeverity.ERROR,
                    "Warning": LogicErrorSeverity.WARNING,
                    "Info": LogicErrorSeverity.INFO
                }
                return LogicErrorReport(
                    error_type=LogicErrorType.FUNCTION_ANOMALY,
                    severity=severity_map.get(result.severity, LogicErrorSeverity.ERROR),
                    description=result.root_cause,
                    location=activity_name,
                    expected=expected_behavior,
                    actual=actual_behavior,
                    suggestions=[result.fix_suggestion] if result.fix_suggestion else []
                )

        except Exception as e:
            print(f"[LogicErrorDetector] LLM 分析失败: {e}")

        return None

    # ==================== UI State Error Detection ====================

    def detect_ui_state_error(
        self,
        widget_id: str,
        expected_state: str,
        actual_state: str,
        activity_name: str = ""
    ) -> Optional[LogicErrorReport]:
        """
        Detect UI state errors

        Args:
            widget_id: Widget identifier
            expected_state: Expected state (enabled, visible, checked, etc.)
            actual_state: Actual state
            activity_name: Current activity

        Returns:
            LogicErrorReport if error detected, None otherwise
        """
        # Normalize states
        expected = expected_state.lower().strip()
        actual = actual_state.lower().strip()

        if expected != actual:
            # Determine severity based on state type
            severity = LogicErrorSeverity.ERROR
            if expected in ["visible", "hidden"]:
                severity = LogicErrorSeverity.WARNING

            return LogicErrorReport(
                error_type=LogicErrorType.UI_STATE_ERROR,
                severity=severity,
                description=f"UI状态错误: {widget_id}",
                location=activity_name,
                expected=expected_state,
                actual=actual_state,
                evidence={"widget_id": widget_id},
                suggestions=[
                    f"检查 {widget_id} 的状态管理逻辑",
                    f"预期状态: {expected_state}, 实际状态: {actual_state}"
                ]
            )

        return None

    def detect_visual_anomaly(
        self,
        activity_name: str = ""
    ) -> Optional[LogicErrorReport]:
        """
        Detect visual anomalies using LLM analysis

        Args:
            activity_name: Current activity

        Returns:
            LogicErrorReport if anomaly detected, None otherwise
        """
        if not self.llm_client or not self.screenshot_manager:
            return None

        try:
            from .prompt_templates import MultimodalPromptTemplate

            screenshots = self.screenshot_manager.get_history(limit=1)
            if not screenshots:
                return None

            prompt = MultimodalPromptTemplate.visual_anomaly_prompt()

            response = self.llm_client.get_decision(
                prompt=prompt,
                screenshots=screenshots
            )

            # Parse response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                data = json.loads(json_match.group(0))

                if data.get("issues_found"):
                    anomalies = data.get("anomalies", [])
                    if anomalies:
                        first_anomaly = anomalies[0]
                        severity_map = {
                            "Critical": LogicErrorSeverity.CRITICAL,
                            "Error": LogicErrorSeverity.ERROR,
                            "Warning": LogicErrorSeverity.WARNING,
                            "Info": LogicErrorSeverity.INFO
                        }
                        return LogicErrorReport(
                            error_type=LogicErrorType.UI_STATE_ERROR,
                            severity=severity_map.get(
                                first_anomaly.get("severity", "Error"),
                                LogicErrorSeverity.ERROR
                            ),
                            description=first_anomaly.get("description", "视觉异常"),
                            location=first_anomaly.get("location", activity_name),
                            evidence={"all_anomalies": anomalies},
                            suggestions=["检查相关UI组件的实现"]
                        )

        except Exception as e:
            print(f"[LogicErrorDetector] 视觉异常检测失败: {e}")

        return None

    # ==================== General Methods ====================

    def get_detected_errors(self) -> List[LogicErrorReport]:
        """Get all detected errors"""
        return self._detected_errors.copy()

    def clear_errors(self) -> None:
        """Clear detected errors history"""
        self._detected_errors.clear()

    def add_error(self, error: LogicErrorReport) -> None:
        """Add an error to the detected errors list"""
        self._detected_errors.append(error)

    def run_full_check(
        self,
        activity_name: str,
        widgets: List[Dict[str, Any]],
        current_values: Optional[Dict[str, float]] = None
    ) -> List[LogicErrorReport]:
        """
        Run all available checks

        Args:
            activity_name: Current activity
            widgets: Current widgets list
            current_values: Current numeric values for calculation validation

        Returns:
            List of detected errors
        """
        errors = []

        # 1. Check calculation rules
        if current_values:
            for rule_id in self._calculation_rules:
                error = self.validate_calculation(rule_id, current_values)
                if error:
                    errors.append(error)

        # 2. Detect visual anomalies
        visual_error = self.detect_visual_anomaly(activity_name)
        if visual_error:
            errors.append(visual_error)

        # 3. Add to history
        self._detected_errors.extend(errors)

        return errors

    def get_statistics(self) -> Dict[str, Any]:
        """Get detection statistics"""
        by_type = {}
        by_severity = {}

        for error in self._detected_errors:
            # Count by type
            type_name = error.error_type.value
            by_type[type_name] = by_type.get(type_name, 0) + 1

            # Count by severity
            severity_name = error.severity.value
            by_severity[severity_name] = by_severity.get(severity_name, 0) + 1

        return {
            "total_errors": len(self._detected_errors),
            "by_type": by_type,
            "by_severity": by_severity,
            "calculation_rules": len(self._calculation_rules)
        }


# Test entry point
if __name__ == "__main__":
    print("=" * 60)
    print("LogicErrorDetector 测试")
    print("=" * 60)

    # Create detector
    detector = LogicErrorDetector()

    # Test calculation validation
    print("\n[测试计算验证]")
    detector.register_calculation_rule(
        "test_sum",
        input_widgets=["input1", "input2", "input3"],
        output_widget="total",
        operation="sum"
    )

    # Correct calculation
    values = {"input1": 10, "input2": 20, "input3": 30, "total": 60}
    error = detector.validate_calculation("test_sum", values)
    print(f"正确计算: {error}")

    # Wrong calculation
    values = {"input1": 10, "input2": 20, "input3": 30, "total": 50}
    error = detector.validate_calculation("test_sum", values)
    if error:
        print(f"错误计算: {error.description}")
        print(f"预期: {error.expected}, 实际: {error.actual}")

    # Test UI state detection
    print("\n[测试UI状态检测]")
    error = detector.detect_ui_state_error(
        "submit_button",
        "enabled",
        "disabled",
        "MainActivity"
    )
    if error:
        print(f"检测到错误: {error.description}")

    # Get statistics
    print("\n[统计信息]")
    stats = detector.get_statistics()
    print(stats)
