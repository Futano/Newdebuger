"""
大模型交互客户端模块
封装 LLM API 调用，用于获取测试决策
支持 OpenAI 兼容的 API（包括 OpenAI、DeepSeek 等）
"""

import os
import re
import sys
import time
from typing import Optional, Tuple

# 导入统一日志配置
from .logger_config import llm_logger, safe_print, print_separator, SEPARATOR_WIDTH

# 导入 Token 监控器
try:
    from .token_monitor import TokenMonitor, get_token_monitor
except ImportError:
    from token_monitor import TokenMonitor, get_token_monitor

# ============================================================
# 解决 Windows 编码问题（必须在导入 openai 之前执行）
# ============================================================

# 1. 强制设置 stdout/stderr 为 UTF-8
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 2. 设置 Python 编码环境变量
os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
os.environ.setdefault('PYTHONUTF8', '1')

# 3. 清理代理环境变量中可能导致编码错误的非 ASCII 字符
# 必须在导入 openai 之前执行，因为 openai 内部会读取这些变量
_proxy_vars = [
    'HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy',
    'ALL_PROXY', 'all_proxy', 'NO_PROXY', 'no_proxy'
]
for _var in _proxy_vars:
    _value = os.environ.get(_var, '')
    if _value:
        try:
            _value.encode('ascii')
        except UnicodeEncodeError:
            # 直接删除，不用 safe_print（此时函数还未定义）
            os.environ.pop(_var, None)

# 尝试导入 OpenAI 库（可选依赖）
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


def clean_env_var(value: Optional[str]) -> str:
    """
    清理环境变量中的非法字符

    Args:
        value: 原始环境变量值

    Returns:
        清理后的字符串，去除首尾空白和不可见字符
    """
    if not value:
        return ""
    # 去除首尾空白字符
    cleaned = value.strip()
    # 去除可能存在的不可见字符（如零宽字符、BOM 等）
    cleaned = ''.join(char for char in cleaned if char.isprintable())
    return cleaned


def env_bool(name: str, default: bool = False) -> bool:
    """Read a boolean environment variable with common true/false spellings."""
    value = clean_env_var(os.environ.get(name))
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    """Read an integer environment variable with a safe fallback."""
    value = clean_env_var(os.environ.get(name))
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


class LLMClient:
    """
    大模型客户端类
    封装与 LLM 的交互逻辑，支持 OpenAI 兼容 API 和模拟模式
    """

    # 默认安全动作：当 API 调用失败时返回（ReAct JSON 格式）
    SAFE_FALLBACK_ACTION = '''```json
{
  "Function": "fallback",
  "Status": "No",
  "Operation": "back",
  "Widget": null,
  "Input_Content": null,
  "Bug_Detected": false
}
```'''

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] =None,
    ):
        """
        初始化 LLM 客户端

        配置优先级：参数 > 环境变量 > 默认值

        Args:
            api_key: API Key，如果不提供则从环境变量 OPENAI_API_KEY 读取
            base_url: API 基础 URL，支持切换 OpenAI/DeepSeek 等不同服务
                      如果不提供则从环境变量 OPENAI_BASE_URL 读取
            model: 使用的模型名称，默认从环境变量读取或使用 gpt-3.5-turbo
        """

        # 从环境变量或参数读取配置，并清理非法字符
        self.api_key = clean_env_var(api_key or os.environ.get("OPENAI_API_KEY"))
        self.base_url = clean_env_var(base_url or os.environ.get("OPENAI_BASE_URL"))
        self.model = clean_env_var(model or os.environ.get("OPENAI_MODEL"))
        self.enable_thinking = env_bool("OPENAI_ENABLE_THINKING", True)
        self.print_reasoning = env_bool("OPENAI_PRINT_REASONING", False)
        self.retry_without_thinking = env_bool("OPENAI_RETRY_WITHOUT_THINKING", True)
        self.max_tokens = env_int(
            "OPENAI_MAX_TOKENS",
            2000 if self.enable_thinking else 1000
        )
        self.last_call_info = {
            "fallback": False,
            "fallback_reason": "",
            "attempts": 0,
            "retry_without_thinking": False,
            "reasoning_chars": 0,
        }

        self.client = None
        self._is_mock_mode = True

        # 检查 OpenAI 库是否可用
        if not OPENAI_AVAILABLE:
            safe_print("[LLM客户端] 警告: openai 库未安装，将使用模拟模式")
            safe_print("[LLM客户端] 提示: 请运行 'pip install openai' 安装依赖")
            return

        # 检查 API Key
        if not self.api_key:
            safe_print("[LLM客户端] 警告: 未检测到 OPENAI_API_KEY，将使用模拟模式")
            safe_print("[LLM客户端] 提示: 请设置环境变量 OPENAI_API_KEY")
            return

        # 初始化 OpenAI 客户端
        try:
            # 如果提供了 base_url，则使用自定义端点（支持 DeepSeek 等）
            if self.base_url:
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
                safe_print(f"[LLM客户端] 使用自定义 API 端点: {self.base_url}")
            else:
                self.client = OpenAI(api_key=self.api_key)

            self._is_mock_mode = False

            safe_print(f"[LLM客户端] 初始化成功")
            safe_print(f"[LLM客户端] 模型: {self.model}")
            safe_print(f"[LLM客户端] Thinking: {'开启' if self.enable_thinking else '关闭'}")
            safe_print(f"[LLM客户端] Max tokens: {self.max_tokens}")
            safe_print(f"[LLM客户端] 模式: {'模拟模式' if self._is_mock_mode else '真实 API 模式'}")

        except Exception as e:
            self._mark_fallback("api_exception", 0)
            safe_print(f"[LLM客户端] 初始化失败: {e}")
            safe_print("[LLM客户端] 将使用模拟模式")
            self.client = None
            self._is_mock_mode = True

    def get_decision(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        根据提示词获取 LLM 的测试决策

        Args:
            prompt: 构建好的测试提示词，包含 GUI 上下文和测试历史
            system_prompt: 系统提示词，定义 LLM 角色和行为规范

        Returns:
            LLM 的响应字符串，格式示例：
            - 'Operation: "click" Widget: "Search"'
            - 'Widget: "SearchBox" Input: "test"'
        """
        self.last_call_info = {
            "fallback": False,
            "fallback_reason": "",
            "attempts": 0,
            "retry_without_thinking": False,
            "reasoning_chars": 0,
        }

        if self._is_mock_mode or not self.client:
            return self._get_mock_response(prompt)

        return self._call_llm_api(prompt, system_prompt)

    def get_last_call_info(self) -> dict:
        """Return metadata for the most recent LLM API call."""
        return dict(self.last_call_info)

    def _mark_fallback(self, reason: str, reasoning_chars: int = 0) -> None:
        self.last_call_info["fallback"] = True
        self.last_call_info["fallback_reason"] = reason
        self.last_call_info["reasoning_chars"] = reasoning_chars

    def _call_llm_api(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        allow_retry: bool = True
    ) -> str:
        """
        调用 LLM API 获取真实响应

        包含完善的异常处理，确保在任何错误情况下都返回安全的默认动作

        Args:
            prompt: 测试提示词
            system_prompt: 系统提示词，可选

        Returns:
            LLM 响应字符串，失败时返回安全默认动作
        """
        # 获取 Token 监控器
        monitor = get_token_monitor()
        monitor.start_request()
        self.last_call_info["attempts"] = self.last_call_info.get("attempts", 0) + 1

        try:
            # ========== 打印发送给模型的提示词 ==========
            safe_print("\n" + "=" * 70)
            safe_print("[LLM客户端] 用户提示词:")
            safe_print("-" * 70)
            safe_print(prompt)
            safe_print("=" * 70 + "\n")

            safe_print("[LLM客户端] 正在调用 API...")
            request_start_time = time.time()

            # 安全编码 Prompt：强制 UTF-8 转换，确保所有字符都能被网络库接受
            # 使用 'ignore' 忽略无法编码的字符，避免 UnicodeEncodeError
            safe_prompt = prompt.encode('utf-8', 'ignore').decode('utf-8')

            # 构建消息列表
            messages = []
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            messages.append({
                "role": "user",
                "content": safe_prompt
            })

            # 使用流式响应来监控首token延迟
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,  # 降低随机性，提高决策一致性
                max_tokens=self.max_tokens,  # thinking 模式下需要更多输出预算
                stream=True,     # 启用流式响应以监控首token延迟
                extra_body = {
                    "top_k": 20,
                    "enable_thinking": self.enable_thinking,
                }
            )

            # 提取响应内容（流式）- 分别处理思考过程和最终回复
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

                # 记录首token时间
                if not first_token_received:
                    monitor.record_first_token()
                    first_token_latency = (time.time() - request_start_time) * 1000
                    safe_print(f"[Token监控] 首Token延迟: {first_token_latency:.0f} ms")
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
                safe_print(f"[LLM客户端] Thinking 内容已接收: {len(reasoning_content)} 字符")
                if self.print_reasoning:
                    print("\n" + "=" * 20 + "完整回复" + "=" * 20 + "\n")

            # 计算生成时间
            total_time = time.time() - request_start_time

            # 估算Token数量（OpenAI API可能不返回usage信息在流式模式下）
            prompt_tokens = monitor.estimate_prompt_tokens(system_prompt or "") + monitor.estimate_prompt_tokens(prompt)
            completion_tokens = monitor.estimate_prompt_tokens(result)

            # 记录监控数据
            metric = monitor.end_request(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                prompt_text=prompt
            )

            # ========== 打印 Token 监控数据 ==========
            safe_print("\n" + "-" * 70)
            safe_print("[Token监控] 本次请求统计:")
            safe_print(f"  提示词Token: {metric.prompt_tokens}")
            safe_print(f"  生成Token: {metric.completion_tokens}")
            safe_print(f"  总Token: {metric.total_tokens}")
            safe_print(f"  首Token延迟: {metric.first_token_latency_ms:.0f} ms")
            safe_print(f"  总延迟: {metric.total_latency_ms:.0f} ms")
            safe_print(f"  生成速度: {metric.tokens_per_second:.1f} tokens/s")
            safe_print("-" * 70 + "\n")

            # ========== 打印模型的完整回答 ==========
            if result:
                safe_print("\n" + "=" * 70)
                safe_print("[LLM客户端] 模型的回答:")
                safe_print("=" * 70)
                safe_print(result)
                safe_print("=" * 70 + "\n")

                return result
            else:
                safe_print("[LLM客户端] API 返回空响应，使用安全默认动作")
                if reasoning_content:
                    safe_print("[LLM客户端] 提示: 已收到 thinking 但没有最终 JSON；可增大 OPENAI_MAX_TOKENS 或临时设置 OPENAI_ENABLE_THINKING=false")
                    if self.enable_thinking and self.retry_without_thinking and allow_retry:
                        safe_print("[LLMClient] thinking produced no final JSON; retrying once with thinking disabled...")
                        original_enable_thinking = self.enable_thinking
                        original_max_tokens = self.max_tokens
                        self.last_call_info["retry_without_thinking"] = True
                        try:
                            self.enable_thinking = False
                            self.max_tokens = max(original_max_tokens, 1000)
                            return self._call_llm_api(prompt, system_prompt, allow_retry=False)
                        finally:
                            self.enable_thinking = original_enable_thinking
                            self.max_tokens = original_max_tokens
                    self._mark_fallback("empty_content_after_thinking", len(reasoning_content))
                else:
                    self._mark_fallback("empty_response", 0)
                return self.SAFE_FALLBACK_ACTION

        except Exception as e:
            # 记录失败的请求
            try:
                monitor.end_request(prompt_tokens=0, completion_tokens=0, prompt_text="")
            except:
                pass

            # 详细的错误处理
            error_type = type(e).__name__
            self._mark_fallback(f"api_exception:{error_type}", 0)
            safe_print(f"[LLM客户端] API 调用失败 [{error_type}]: {e}")

            # 根据错误类型提供更具体的提示
            if "UnicodeEncodeError" in error_type or "unicode" in str(e).lower():
                safe_print("[LLM客户端] 提示: 编码错误，已尝试安全编码但仍失败，请检查 Prompt 内容")
            elif "authentication" in str(e).lower() or "api_key" in str(e).lower():
                safe_print("[LLM客户端] 提示: 请检查 API Key 是否正确")
            elif "rate" in str(e).lower() or "limit" in str(e).lower():
                safe_print("[LLM客户端] 提示: 请求频率超限，请稍后重试")
            elif "timeout" in str(e).lower():
                safe_print("[LLM客户端] 提示: 请求超时，请检查网络连接")
            elif "connection" in str(e).lower():
                safe_print("[LLM客户端] 提示: 网络连接失败，请检查网络设置")

            # 返回安全的默认动作，防止程序崩溃
            safe_print(f"[LLM客户端] 使用安全默认动作: {self.SAFE_FALLBACK_ACTION}")
            return self.SAFE_FALLBACK_ACTION

    def _get_mock_response(self, prompt: str) -> str:
        """
        生成模拟的 LLM 响应（用于测试和离线模式）

        模拟策略：分析 prompt 中的控件信息，返回第一个可点击控件

        Args:
            prompt: 测试提示词

        Returns:
            模拟的响应字符串
        """
        # ========== 打印发送给模型的提示词 ==========
        safe_print("\n" + "=" * 70)
        safe_print("[LLM客户端 - 模拟模式] 发送给模型的提示词:")
        safe_print("=" * 70)
        safe_print(prompt)
        safe_print("=" * 70 + "\n")

        safe_print("[LLM客户端] 使用模拟模式返回测试决策")

        # 尝试从 prompt 中提取控件名称

        # 提取 "The widgets which can be operated are" 后面的控件列表
        widgets_match = re.search(
            r'The widgets which can be operated are ([^.]+)\.',
            prompt
        )

        if widgets_match:
            widgets_str = widgets_match.group(1)
            # 提取第一个控件名（去除探索标记）
            widgets = []
            for w in widgets_str.split(','):
                w = w.strip()
                if w:
                    # 移除 [ALREADY EXPLORED] 等标记
                    if '[' in w:
                        w = w.split('[')[0].strip()
                    if w:
                        widgets.append(w)

            if widgets:
                first_widget = widgets[0]
                # 返回 ReAct JSON 格式
                mock_response = f'''```json
{{
  "Function": "mock_test",
  "Status": "No",
  "Operation": "click",
  "Widget": "{first_widget}",
  "Input_Content": null,
  "Bug_Detected": false
}}
```'''

                # ========== 打印模型的回答 ==========
                safe_print("\n" + "=" * 70)
                safe_print("[LLM客户端 - 模拟模式] 模型的回答:")
                safe_print("=" * 70)
                safe_print(mock_response)
                safe_print("=" * 70 + "\n")

                return mock_response

        # 默认模拟响应（ReAct JSON 格式）
        mock_response = '''```json
{
  "Function": "mock_default",
  "Status": "No",
  "Operation": "click",
  "Widget": "Search",
  "Input_Content": null,
  "Bug_Detected": false
}
```'''

        # ========== 打印模型的回答 ==========
        safe_print("\n" + "=" * 70)
        safe_print("[LLM客户端 - 模拟模式] 模型的回答:")
        safe_print("=" * 70)
        safe_print(mock_response)
        safe_print("=" * 70 + "\n")

        return mock_response

    def is_mock_mode(self) -> bool:
        """
        检查是否处于模拟模式

        Returns:
            True 表示模拟模式，False 表示真实 API 模式
        """
        return self._is_mock_mode

    def test_connection(self) -> Tuple[bool, str]:
        """
        测试 API 连接是否正常

        Returns:
            元组 (是否成功, 状态消息)
        """
        if self._is_mock_mode:
            return False, "模拟模式，未配置 API"

        try:
            # 发送一个简单的测试请求（使用安全编码）
            test_content = "Say 'OK' if you can hear me.".encode('utf-8', 'ignore').decode('utf-8')
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": test_content}
                ],
                max_tokens=10
            )

            if response.choices:
                return True, f"API 连接正常，模型: {self.model}"
            else:
                return False, "API 返回异常响应"

        except Exception as e:
            return False, f"API 连接失败: {e}"


# 测试入口
if __name__ == "__main__":
    safe_print("=" * 60)
    safe_print("LLM 客户端测试")
    safe_print("=" * 60)

    # 创建客户端
    client = LLMClient()

    # 测试连接
    safe_print("\n[测试连接]")
    success, message = client.test_connection()
    safe_print(f"状态: {message}")

    # 测试决策
    safe_print("\n[测试决策]")
    test_prompt = """The current page is MainActivity, it has Search, Login, Register.
The upper part of the app is Search, the lower part is Login, Register.
The widgets which can be operated are Search, Login, Register.
What operation is required? (<Operation>[click/double-click/long press/scroll]+<Widget Name>)"""

    response = client.get_decision(test_prompt)
    safe_print(f"\n最终响应: {response}")
