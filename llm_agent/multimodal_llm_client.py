"""
Multimodal LLM Client Module
Extended LLM client supporting both text-only and multimodal (image + text) interactions
Used for enhanced UI understanding and bug analysis
"""

import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

# Import existing LLM client for base functionality
from .llm_client import LLMClient, safe_print, clean_env_var, env_bool, env_int, OPENAI_AVAILABLE

# Import screenshot types
from .screenshot_manager import ScreenshotData

if OPENAI_AVAILABLE:
    from openai import OpenAI


@dataclass
class BugContext:
    """
    Context information for bug analysis

    Attributes:
        bug_type: Type of bug (crash, logic_error, ui_state_error, etc.)
        description: Human-readable description of the bug
        activity_name: Current activity when bug was detected
        crash_log: Crash log if applicable
        operation: Operation that triggered the bug
        widget: Widget involved in the bug
        state_before: UI state before the operation
        state_after: UI state after the operation
        additional_info: Any additional context information
    """
    bug_type: str
    description: str
    activity_name: str = ""
    crash_log: str = ""
    operation: str = ""
    widget: str = ""
    state_before: Dict[str, Any] = field(default_factory=dict)
    state_after: Dict[str, Any] = field(default_factory=dict)
    additional_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BugAnalysisResult:
    """
    Result of bug analysis by LLM

    Attributes:
        root_cause: LLM's analysis of the root cause
        severity: Bug severity level (Critical/Error/Warning/Info)
        category: Bug category (crash, calculation_error, data_inconsistency, etc.)
        fix_suggestion: Suggested fix from LLM
        reproduction_steps: Steps to reproduce the bug
        confidence: Confidence level of the analysis (0-1)
    """
    root_cause: str
    severity: str = "Error"
    category: str = "unknown"
    fix_suggestion: str = ""
    reproduction_steps: List[str] = field(default_factory=list)
    confidence: float = 0.8


class MultimodalLLMClient(LLMClient):
    """
    Multimodal LLM Client

    Extends LLMClient to support multimodal interactions (image + text).
    Uses the same API configuration as the base client (OPENAI_API_KEY, etc.)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        use_multimodal_thinking_env: bool = True,
    ):
        """
        Initialize Multimodal LLM Client

        Uses the same configuration as LLMClient:
        - OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_MODEL environment variables
        - Or parameters passed directly

        Args:
            api_key: API key (defaults to OPENAI_API_KEY env var)
            base_url: API base URL (defaults to OPENAI_BASE_URL env var)
            model: Model name (defaults to OPENAI_MODEL env var, or gpt-4o)
            use_multimodal_thinking_env: When true, read OPENAI_MULTIMODAL_* thinking
                settings. When false, keep the base Explorer OPENAI_* settings.
        """
        # Initialize base LLM client
        super().__init__(api_key, base_url, model)

        # Supervisor/Bug Analysis can use separate thinking settings. Explorer
        # can keep the base OPENAI_* settings by passing use_multimodal_thinking_env=False.
        if use_multimodal_thinking_env:
            self.enable_thinking = env_bool("OPENAI_MULTIMODAL_ENABLE_THINKING", False)
            self.max_tokens = env_int(
                "OPENAI_MULTIMODAL_MAX_TOKENS",
                2000 if self.enable_thinking else 1000
            )

        # Use the same client and configuration as base class
        # No separate multimodal configuration needed
        self._is_multimodal_mode = self._is_mock_mode == False and self.client is not None

        if self._is_multimodal_mode:
            safe_print(f"[MultimodalLLM] 多模态模式已启用")
            safe_print(f"[MultimodalLLM] 模型: {self.model}")
            safe_print(f"[MultimodalLLM] Thinking: {'开启' if self.enable_thinking else '关闭'}")
        else:
            safe_print(f"[MultimodalLLM] 多模态模式未启用（API未配置或模拟模式）")

    def get_decision(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        screenshots: Optional[List[ScreenshotData]] = None
    ) -> str:
        """
        Get LLM decision with optional multimodal support

        Args:
            prompt: Text prompt for the LLM
            system_prompt: System prompt defining LLM behavior
            screenshots: Optional list of screenshots for multimodal analysis

        Returns:
            LLM response string
        """
        # If screenshots provided and client is available, use multimodal mode
        if screenshots and self._is_multimodal_mode and self.client:
            return self._get_multimodal_decision(prompt, system_prompt, screenshots)

        # Fall back to text-only mode
        return super().get_decision(prompt, system_prompt)

    def _get_multimodal_decision(
        self,
        prompt: str,
        system_prompt: Optional[str],
        screenshots: List[ScreenshotData]
    ) -> str:
        """
        Get decision using multimodal API (image + text)

        Args:
            prompt: Text prompt
            system_prompt: System prompt
            screenshots: List of screenshots to include

        Returns:
            LLM response string
        """
        try:
            safe_print("\n" + "=" * 70)
            safe_print("[MultimodalLLM] 发送多模态请求...")
            safe_print(f"[MultimodalLLM] 包含 {len(screenshots)} 张截图")
            safe_print("=" * 70)

            request_start_time = time.time()

            # Build message content
            content = []

            # Add text prompt first
            content.append({
                "type": "text",
                "text": prompt
            })

            # Add screenshots
            for i, screenshot in enumerate(screenshots[:5]):  # Limit to 5 screenshots
                data_uri = screenshot.get_data_uri()
                if data_uri:
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": data_uri
                        }
                    })
                    safe_print(f"[MultimodalLLM] 截图 {i+1}: {screenshot.path.name}")

            # Build messages
            messages = []
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            messages.append({
                "role": "user",
                "content": content
            })

            # Call API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=1,
                max_tokens=self.max_tokens,
                stream=True,
                extra_body = {"enable_thinking": self.enable_thinking}
            )

            # Extract response (streaming) - 分别处理思考过程和最终回复
            reasoning_chunks = []  # 思考过程 (reasoning_content)
            result_chunks = []     # 最终回复 (content)
            first_token_received = False

            for chunk in response:
                choices = getattr(chunk, "choices", None)
                if not choices:
                    continue

                delta = getattr(choices[0], "delta", None)
                if delta is None:
                    continue

                if not first_token_received:
                    first_token_latency = (time.time() - request_start_time) * 1000
                    safe_print(f"[MultimodalLLM] 首Token延迟: {first_token_latency:.0f} ms")
                    first_token_received = True

                # 收集思考内容 (原生 thinking 输出)
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    reasoning_chunks.append(delta.reasoning_content)
                    if self.print_reasoning:
                        print(delta.reasoning_content, end="", flush=True)

                # 收集最终回复内容
                if hasattr(delta, 'content') and delta.content:
                    result_chunks.append(delta.content)

            reasoning_content = ''.join(reasoning_chunks)
            result = ''.join(result_chunks).strip()

            if reasoning_content:
                safe_print(f"[MultimodalLLM] Thinking 内容已接收: {len(reasoning_content)} 字符")
                if self.print_reasoning:
                    print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")

            total_time = time.time() - request_start_time

            safe_print(f"\n[MultimodalLLM] 响应时间: {total_time:.2f}s")
            safe_print("=" * 70)

            if result:
                safe_print("\n[多模态LLM响应]:")
                safe_print(result)
                return result
            else:
                safe_print("[MultimodalLLM] API 返回空响应")
                return self.SAFE_FALLBACK_ACTION

        except Exception as e:
            error_type = type(e).__name__
            safe_print(f"[MultimodalLLM] API 调用失败 [{error_type}]: {e}")
            safe_print("[MultimodalLLM] 回退到纯文本模式")

            # Fall back to text-only mode
            return super().get_decision(prompt, system_prompt)

    def analyze_bug(
        self,
        bug_context: BugContext,
        screenshots: List[ScreenshotData],
        additional_context: Optional[str] = None
    ) -> BugAnalysisResult:
        """
        Analyze a bug using multimodal LLM

        Args:
            bug_context: Context information about the bug
            screenshots: Screenshots for visual analysis
            additional_context: Additional text context

        Returns:
            BugAnalysisResult with LLM's analysis
        """
        # Build bug analysis prompt
        analysis_prompt = self._build_bug_analysis_prompt(bug_context, additional_context)

        # Get LLM analysis
        try:
            response = self.get_decision(
                prompt=analysis_prompt,
                system_prompt=self._get_bug_analysis_system_prompt(),
                screenshots=screenshots if self._is_multimodal_mode else None
            )

            # Parse response
            return self._parse_bug_analysis_response(response, bug_context)

        except Exception as e:
            safe_print(f"[MultimodalLLM] Bug分析失败: {e}")
            return BugAnalysisResult(
                root_cause=f"分析失败: {e}",
                severity="Unknown",
                category=bug_context.bug_type
            )

    def _build_bug_analysis_prompt(
        self,
        bug_context: BugContext,
        additional_context: Optional[str] = None
    ) -> str:
        """Build prompt for bug analysis"""
        parts = [
            "# Bug Analysis Request",
            "",
            "## Bug Information",
            f"- **Type**: {bug_context.bug_type}",
            f"- **Description**: {bug_context.description}",
            f"- **Activity**: {bug_context.activity_name}",
            f"- **Trigger Operation**: {bug_context.operation}",
            f"- **Widget Involved**: {bug_context.widget}",
        ]

        if bug_context.crash_log:
            # Truncate crash log if too long
            crash_log = bug_context.crash_log[:2000] if len(bug_context.crash_log) > 2000 else bug_context.crash_log
            parts.append(f"\n## Crash Log\n```\n{crash_log}\n```")

        if additional_context:
            parts.append(f"\n## Additional Context\n{additional_context}")

        parts.append("""
## Analysis Required

Please analyze this bug and provide:
1. **Root Cause**: What is the underlying cause of this bug?
2. **Severity**: Critical / Error / Warning / Info
3. **Category**: crash / calculation_error / data_inconsistency / function_anomaly / ui_state_error
4. **Fix Suggestion**: How should this bug be fixed?
5. **Reproduction Steps**: Clear steps to reproduce

Output your analysis in JSON format:
```json
{
  "root_cause": "Your analysis here",
  "severity": "Critical|Error|Warning|Info",
  "category": "bug_category",
  "fix_suggestion": "Suggested fix",
  "reproduction_steps": ["step1", "step2", ...],
  "confidence": 0.8
}
```
""")
        return "\n".join(parts)

    def _get_bug_analysis_system_prompt(self) -> str:
        """Get system prompt for bug analysis"""
        return """You are an expert Android app debugging assistant. Your task is to analyze bugs and provide detailed insights.

Your analysis should be:
1. **Technical and precise**: Focus on the actual technical cause
2. **Actionable**: Provide clear fix suggestions
3. **Structured**: Follow the JSON output format exactly

Bug Severity Guidelines:
- **Critical**: App crash, data loss, security vulnerability
- **Error**: Feature not working, incorrect behavior
- **Warning**: Suboptimal UX, potential issues
- **Info**: Minor issues, suggestions for improvement

Always output valid JSON in the specified format."""

    def _parse_bug_analysis_response(
        self,
        response: str,
        bug_context: BugContext
    ) -> BugAnalysisResult:
        """Parse LLM response into BugAnalysisResult"""
        import json
        import re

        # Default result
        default_result = BugAnalysisResult(
            root_cause=response,
            severity="Error",
            category=bug_context.bug_type
        )

        try:
            # Extract JSON from response
            json_match = re.search(r'```json\s*([\s\S]*?)\s*```', response)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r'\{[\s\S]*\}', response)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    return default_result

            # Parse JSON
            data = json.loads(json_str)

            return BugAnalysisResult(
                root_cause=data.get("root_cause", response),
                severity=data.get("severity", "Error"),
                category=data.get("category", bug_context.bug_type),
                fix_suggestion=data.get("fix_suggestion", ""),
                reproduction_steps=data.get("reproduction_steps", []),
                confidence=data.get("confidence", 0.8)
            )

        except Exception as e:
            safe_print(f"[MultimodalLLM] 解析分析结果失败: {e}")
            return default_result

    def is_multimodal_available(self) -> bool:
        """Check if multimodal mode is available"""
        return self._is_multimodal_mode

    def test_multimodal_connection(self) -> tuple:
        """
        Test multimodal API connection

        Returns:
            Tuple (success: bool, message: str)
        """
        if not self._is_multimodal_mode:
            return False, "Multimodal mode not available"

        try:
            # Create a simple test with a minimal image
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": "Say 'Multimodal OK' if you can receive this message."
                    }
                ],
                max_tokens=20
            )

            if response.choices:
                return True, f"API 连接正常，模型: {self.model}"
            else:
                return False, "API 返回异常响应"

        except Exception as e:
            return False, f"API 连接失败: {e}"


# Test entry point
if __name__ == "__main__":
    safe_print("=" * 60)
    safe_print("MultimodalLLMClient 测试")
    safe_print("=" * 60)

    # Create client
    client = MultimodalLLMClient()

    # Test multimodal connection
    safe_print("\n[测试多模态连接]")
    success, message = client.test_multimodal_connection()
    safe_print(f"状态: {message}")

    # Test regular connection
    safe_print("\n[测试常规连接]")
    success, message = client.test_connection()
    safe_print(f"状态: {message}")

    safe_print(f"\n多模态可用: {client.is_multimodal_available()}")
