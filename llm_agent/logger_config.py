"""
统一日志配置模块
提供模块专用日志器和统一分隔符打印
"""

import logging
from pathlib import Path
from typing import Optional


# 标准分隔符宽度
SEPARATOR_WIDTH = 70


def setup_logger(name: str, log_file: Optional[Path] = None) -> logging.Logger:
    """
    配置统一日志器

    Args:
        name: 日志器名称
        log_file: 可选的日志文件路径

    Returns:
        配置好的日志器实例
    """
    logger = logging.getLogger(name)

    # 避免重复配置
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    # 格式: [模块][级别] 消息
    formatter = logging.Formatter('[%(name)s][%(levelname)s] %(message)s')

    # 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    # 文件输出 (可选)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# 模块专用日志器
llm_logger = setup_logger('LLM')
action_logger = setup_logger('ACTION')
memory_logger = setup_logger('MEMORY')
bug_logger = setup_logger('BUG')
system_logger = setup_logger('SYSTEM')


def print_separator(char: str = "=", width: int = SEPARATOR_WIDTH) -> None:
    """
    统一分隔符打印

    Args:
        char: 分隔符字符
        width: 分隔符宽度
    """
    print(char * width)


def safe_print(msg: str) -> None:
    """
    安全打印函数，解决 Windows 终端 UnicodeEncodeError 问题

    Args:
        msg: 要打印的消息
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        # 如果 UTF-8 打印失败，尝试用 ASCII 替换不可编码字符
        safe_msg = msg.encode('ascii', 'replace').decode('ascii')
        print(safe_msg)