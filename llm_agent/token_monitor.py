"""
Token使用监控模块
跟踪和分析LLM Token消耗、延迟和速度指标
"""

import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime
from collections import deque
import json
from pathlib import Path


@dataclass
class TokenMetrics:
    """单次请求的Token指标"""
    timestamp: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    first_token_latency_ms: float = 0.0  # 首token延迟
    total_latency_ms: float = 0.0  # 总延迟
    tokens_per_second: float = 0.0  # 生成速度
    prompt_length_chars: int = 0  # 提示词字符数（估算用）

    def to_dict(self) -> Dict:
        return {
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "first_token_latency_ms": round(self.first_token_latency_ms, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
            "tokens_per_second": round(self.tokens_per_second, 2),
            "prompt_length_chars": self.prompt_length_chars
        }


class TokenMonitor:
    """
    Token使用监控器

    跟踪指标：
    1. Token用量（输入/输出/总计）
    2. 首Token延迟（TTFT - Time To First Token）
    3. 生成速度（Tokens/Second）
    4. 总延迟
    """

    def __init__(self, history_size: int = 100, log_file: Optional[Path] = None):
        """
        初始化监控器

        Args:
            history_size: 保留的历史记录数量
            log_file: 日志文件路径（可选）
        """
        self.metrics_history: deque = deque(maxlen=history_size)
        self.current_request_start: Optional[float] = None
        self.current_first_token_time: Optional[float] = None
        self.log_file = log_file or Path("temp_data/token_metrics.jsonl")

        # 统计累计值
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_requests = 0

    def start_request(self):
        """开始记录一个新请求"""
        self.current_request_start = time.time()
        self.current_first_token_time = None

    def record_first_token(self):
        """记录收到第一个Token的时间"""
        if self.current_request_start and not self.current_first_token_time:
            self.current_first_token_time = time.time()

    def end_request(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        prompt_text: str = ""
    ) -> TokenMetrics:
        """
        结束记录请求，计算指标

        Args:
            prompt_tokens: 提示词Token数（如果API返回）
            completion_tokens: 输出Token数
            prompt_text: 提示词文本（用于估算字符数）

        Returns:
            TokenMetrics 对象
        """
        end_time = time.time()

        # 计算延迟
        total_latency_ms = (end_time - self.current_request_start) * 1000 if self.current_request_start else 0
        first_token_latency_ms = (self.current_first_token_time - self.current_request_start) * 1000 if self.current_first_token_time and self.current_request_start else total_latency_ms

        # 计算生成速度
        generation_time_sec = (end_time - (self.current_first_token_time or self.current_request_start)) if self.current_request_start else 0
        tokens_per_second = completion_tokens / generation_time_sec if generation_time_sec > 0 else 0

        # 创建指标对象
        metric = TokenMetrics(
            timestamp=time.time(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            first_token_latency_ms=first_token_latency_ms,
            total_latency_ms=total_latency_ms,
            tokens_per_second=tokens_per_second,
            prompt_length_chars=len(prompt_text)
        )

        # 保存到历史
        self.metrics_history.append(metric)

        # 更新累计统计
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_requests += 1

        # 写入日志文件
        self._log_metric(metric)

        # 重置当前请求状态
        self.current_request_start = None
        self.current_first_token_time = None

        return metric

    def _log_metric(self, metric: TokenMetrics):
        """将指标写入日志文件"""
        try:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(metric.to_dict(), ensure_ascii=False) + '\n')
        except Exception as e:
            print(f"[TokenMonitor] 日志写入失败: {e}")

    def get_statistics(self) -> Dict:
        """
        获取统计摘要

        Returns:
            包含各项统计指标的字典
        """
        if not self.metrics_history:
            return {
                "total_requests": 0,
                "message": "暂无数据"
            }

        # 计算平均值
        avg_first_token_latency = sum(m.first_token_latency_ms for m in self.metrics_history) / len(self.metrics_history)
        avg_total_latency = sum(m.total_latency_ms for m in self.metrics_history) / len(self.metrics_history)
        avg_tokens_per_second = sum(m.tokens_per_second for m in self.metrics_history) / len(self.metrics_history)
        avg_prompt_tokens = sum(m.prompt_tokens for m in self.metrics_history) / len(self.metrics_history)
        avg_completion_tokens = sum(m.completion_tokens for m in self.metrics_history) / len(self.metrics_history)

        return {
            "total_requests": self.total_requests,
            "history_records": len(self.metrics_history),
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "averages": {
                "first_token_latency_ms": round(avg_first_token_latency, 2),
                "total_latency_ms": round(avg_total_latency, 2),
                "tokens_per_second": round(avg_tokens_per_second, 2),
                "prompt_tokens": round(avg_prompt_tokens, 2),
                "completion_tokens": round(avg_completion_tokens, 2)
            },
            "latest_request": self.metrics_history[-1].to_dict() if self.metrics_history else None
        }

    def print_report(self):
        """打印监控报告"""
        stats = self.get_statistics()

        print("\n" + "="*60)
        print("Token 使用监控报告")
        print("="*60)

        if stats.get("total_requests") == 0:
            print("暂无数据")
            return

        print(f"\n【请求统计】")
        print(f"  总请求数: {stats['total_requests']}")
        print(f"  历史记录数: {stats['history_records']}")

        print(f"\n【Token用量】")
        print(f"  提示词总计: {stats['total_prompt_tokens']:,} tokens")
        print(f"  生成内容总计: {stats['total_completion_tokens']:,} tokens")
        print(f"  总计: {stats['total_tokens']:,} tokens")

        avg = stats['averages']
        print(f"\n【平均值】")
        print(f"  首Token延迟: {avg['first_token_latency_ms']:.0f} ms")
        print(f"  总延迟: {avg['total_latency_ms']:.0f} ms")
        print(f"  生成速度: {avg['tokens_per_second']:.1f} tokens/s")
        print(f"  提示词长度: {avg['prompt_tokens']:.0f} tokens")
        print(f"  生成长度: {avg['completion_tokens']:.0f} tokens")

        if stats.get('latest_request'):
            latest = stats['latest_request']
            print(f"\n【最近请求】")
            print(f"  时间: {latest['timestamp']}")
            print(f"  总Token: {latest['total_tokens']}")
            print(f"  延迟: {latest['total_latency_ms']:.0f} ms")
            print(f"  速度: {latest['tokens_per_second']:.1f} tokens/s")

        print("="*60 + "\n")

    def estimate_prompt_tokens(self, text: str) -> int:
        """
        估算提示词的Token数量（粗略估算）

        中文约1.5字符/token，英文约4字符/token
        这里使用保守估算：平均 3 字符/token

        Args:
            text: 提示词文本

        Returns:
            估算的Token数量
        """
        return len(text) // 3


# 全局监控器实例（单例模式）
_token_monitor: Optional[TokenMonitor] = None


def get_token_monitor() -> TokenMonitor:
    """获取全局Token监控器实例"""
    global _token_monitor
    if _token_monitor is None:
        _token_monitor = TokenMonitor()
    return _token_monitor


def reset_token_monitor():
    """重置全局监控器"""
    global _token_monitor
    _token_monitor = TokenMonitor()


# 测试入口
if __name__ == "__main__":
    monitor = TokenMonitor()

    # 模拟几个请求
    for i in range(3):
        monitor.start_request()
        time.sleep(0.1)  # 模拟首token延迟
        monitor.record_first_token()
        time.sleep(0.3)  # 模拟生成时间

        metric = monitor.end_request(
            prompt_tokens=500 + i * 100,
            completion_tokens=150 + i * 50,
            prompt_text="This is a test prompt " * 50
        )
        print(f"Request {i+1}: {metric.tokens_per_second:.1f} tokens/s")

    # 打印报告
    monitor.print_report()
