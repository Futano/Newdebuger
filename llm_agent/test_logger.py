"""
测试历史日志管理模块
实时记录测试过程到文件，支持 Claude Code 监控
"""

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, TextIO
import threading


class TestLogger:
    """
    测试日志管理器

    功能：
    1. 将测试输出同时打印到控制台和写入文件
    2. 支持实时文件监控
    3. 自动添加时间戳
    4. 支持日志轮转
    """

    def __init__(
        self,
        log_file: Optional[Path] = None,
        enable_console: bool = True,
        enable_file: bool = True
    ):
        """
        初始化日志管理器

        Args:
            log_file: 日志文件路径，默认 temp_data/test_history.log
            enable_console: 是否输出到控制台
            enable_file: 是否输出到文件
        """
        self.enable_console = enable_console
        self.enable_file = enable_file
        self.log_file = log_file or Path("temp_data/test_history.log")
        self.file_handle: Optional[TextIO] = None
        self._lock = threading.Lock()

        # 确保目录存在
        if self.enable_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self.file_handle = open(self.log_file, 'w', encoding='utf-8')

        # 写入日志头
        self._write_header()

    def _write_header(self):
        """写入日志文件头"""
        header = f"# 测试历史日志 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        self._write_raw(header)

    def _write_raw(self, message: str):
        """原始写入（不加时间戳）"""
        with self._lock:
            if self.enable_console:
                print(message, end='')
            if self.enable_file and self.file_handle:
                self.file_handle.write(message)
                self.file_handle.flush()

    def log(self, message: str, level: str = "INFO"):
        """
        记录日志

        Args:
            message: 日志消息
            level: 日志级别 (DEBUG, INFO, WARN, ERROR)
        """
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        formatted = f"[{timestamp}] [{level}] {message}\n"
        self._write_raw(formatted)

    def section(self, title: str):
        """记录章节标题"""
        self._write_raw(f"\n## {title}\n")

    def subsection(self, title: str):
        """记录子章节标题"""
        self._write_raw(f"- {title}\n")

    def separator(self):
        """分隔线"""
        self._write_raw("\n" + "-" * 70 + "\n")

    def log_widgets(self, widgets: list, title: str = "控件列表"):
        """
        记录控件列表详情

        Args:
            widgets: 控件列表
            title: 标题
        """
        self.subsection(title)
        if not widgets:
            self._write_raw("  [无控件]\n")
            return

        self._write_raw(f"  共 {len(widgets)} 个控件:\n\n")
        for i, w in enumerate(widgets, 1):
            text = w.get('text', '') or '(无文本)'
            rid = w.get('resource_id', '') or '(无ID)'
            cls = w.get('class', '') or '(无类名)'
            bounds = w.get('bounds', '') or '(无边界)'
            clickable = '✓' if w.get('clickable') else '✗'
            self._write_raw(f"  [{i}] {text}\n")
            self._write_raw(f"      ID: {rid}\n")
            self._write_raw(f"      Class: {cls}\n")
            self._write_raw(f"      Bounds: {bounds}\n")
            self._write_raw(f"      Clickable: {clickable}\n\n")

    def log_ui_hierarchy(self, ui_file: Path, title: str = "UI布局文件"):
        """
        记录UI布局文件内容

        Args:
            ui_file: UI布局文件路径
            title: 标题
        """
        self.subsection(title)
        try:
            if ui_file.exists():
                content = ui_file.read_text(encoding='utf-8')
                # 只记录前5000字符避免日志过大
                max_len = 5000
                if len(content) > max_len:
                    self._write_raw(f"[UI布局 - 前{max_len}字符]\n")
                    self._write_raw(content[:max_len])
                    self._write_raw(f"\n... [截断，共{len(content)}字符]\n")
                else:
                    self._write_raw("[UI布局完整内容]\n")
                    self._write_raw(content)
                self._write_raw("\n")
            else:
                self._write_raw(f"[UI布局文件不存在: {ui_file}]\n")
        except Exception as e:
            self._write_raw(f"[读取UI布局失败: {e}]\n")

    def log_prompt(self, prompt: str, title: str = "LLM Prompt"):
        """
        记录Prompt内容

        Args:
            prompt: Prompt文本
            title: 标题
        """
        self.subsection(title)
        self._write_raw("[Prompt内容]\n")
        self._write_raw(prompt)
        self._write_raw("\n")

    def log_llm_response(self, response: str, title: str = "LLM响应"):
        """
        记录LLM响应

        Args:
            response: 响应文本
            title: 标题
        """
        self.subsection(title)
        self._write_raw("[LLM响应内容]\n")
        self._write_raw(response)
        self._write_raw("\n")

    def log_action_result(self, success: bool, operation: str, widget: str, error: str = None):
        """
        记录动作执行结果

        Args:
            success: 是否成功
            operation: 操作类型
            widget: 目标控件
            error: 错误信息
        """
        status = "成功" if success else "失败"
        self.log(f"动作执行{status}: {operation} -> {widget}", "SUCCESS" if success else "ERROR")
        if error:
            self.log(f"错误详情: {error}", "ERROR")

    def get_log_path(self) -> Path:
        """获取日志文件路径"""
        return self.log_file

    def get_recent_lines(self, n: int = 50) -> str:
        """获取最近的 n 行日志"""
        if not self.log_file.exists():
            return "[日志文件不存在]"

        try:
            with open(self.log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                return ''.join(lines[-n:])
        except Exception as e:
            return f"[读取日志失败: {e}]"

    def close(self, write_footer: bool = True):
        """关闭日志文件"""
        handle = self.file_handle
        if not handle:
            return

        if getattr(handle, "closed", False):
            self.file_handle = None
            return

        if write_footer and sys.meta_path is not None:
            try:
                self.log(f"测试日志关闭: {self.log_file}", "INFO")
            except Exception:
                # Interpreter shutdown can partially tear down stdlib state.
                pass

        try:
            handle.close()
        finally:
            self.file_handle = None

    def __del__(self):
        """析构时关闭文件"""
        try:
            self.close(write_footer=False)
        except Exception:
            pass


# 全局日志器实例
_logger: Optional[TestLogger] = None


def get_logger(
    log_file: Optional[Path] = None,
    enable_console: bool = True,
    enable_file: bool = True
) -> TestLogger:
    """获取全局日志器实例（单例）"""
    global _logger
    if _logger is None:
        _logger = TestLogger(log_file, enable_console, enable_file)
    return _logger


def reset_logger():
    """重置日志器"""
    global _logger
    if _logger:
        _logger.close()
    _logger = None


def log(message: str, level: str = "INFO"):
    """快捷记录日志"""
    get_logger().log(message, level)


def section(title: str):
    """快捷记录章节"""
    get_logger().section(title)


def subsection(title: str):
    """快捷记录子章节"""
    get_logger().subsection(title)


# 测试入口
if __name__ == "__main__":
    logger = TestLogger()

    # 测试各种日志类型
    logger.section("测试开始")
    logger.log("这是一个普通信息")
    logger.log("这是一个警告", "WARN")
    logger.subsection("子步骤")
    logger.log("执行操作 1")
    logger.log("执行操作 2")
    logger.separator()
    logger.log("测试完成")

    print(f"\n日志文件位置: {logger.get_log_path()}")
    print(f"\n最近 10 行日志:\n{logger.get_recent_lines(10)}")

    logger.close()
