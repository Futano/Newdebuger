"""
ADB 工具模块
封装 ADB 命令用于移动端 GUI 自动化测试
支持 UIAutomator2 进行高级控件操作
"""

import subprocess
import time
import re
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# 尝试导入 uiautomator2，如果未安装则给出提示
try:
    import uiautomator2 as u2
    UIAUTOMATOR2_AVAILABLE = True
except ImportError:
    UIAUTOMATOR2_AVAILABLE = False
    print("[警告] uiautomator2 未安装，某些高级功能将不可用")
    print("[提示] 请运行: pip install uiautomator2")



class ADBController:
    """
    ADB 控制器类
    封装常用的 ADB 命令，用于与 Android 设备进行交互
    同时支持 UIAutomator2 进行高级控件操作（如 clear_text, send_keys）
    """

    # Launcher Activity 黑名单（桌面启动器）
    LAUNCHER_ACTIVITY_BLACKLIST = {
        'NexusLauncherActivity',
        'LauncherActivity',
        'Launcher',
        'HomeActivity',
    }

    # Launcher 包名黑名单
    LAUNCHER_PACKAGE_BLACKLIST = {
        'com.android.systemui',
        'com.android.launcher',
        'com.android.launcher3',
        'com.google.android.apps.nexuslauncher',
    }

    def __init__(self, device_id: Optional[str] = None):
        """
        初始化 ADB 控制器

        Args:
            device_id: 设备 ID，如果有多台设备连接时需要指定。
                       可通过 `adb devices` 命令查看
        """
        self.device_id = device_id
        self._u2_device = None  # UIAutomator2 设备实例 (类型: Optional[u2.Device])
        self.last_ui_dump_error = ""

    def _get_u2_device(self):  # -> Optional[u2.Device]
        """
        获取 UIAutomator2 设备实例（延迟初始化）

        Returns:
            UIAutomator2 Device 实例，如果不可用则返回 None
        """
        if not UIAUTOMATOR2_AVAILABLE:
            return None

        if self._u2_device is None:
            try:
                if self.device_id:
                    self._u2_device = u2.connect(self.device_id)
                else:
                    self._u2_device = u2.connect()
                print(f"[UIAutomator2] 成功连接到设备")
            except Exception as e:
                print(f"[UIAutomator2] 连接失败: {e}")
                self._u2_device = None

        return self._u2_device

    def _build_adb_command(self, cmd: str) -> list[str]:
        """
        构建 ADB shell 命令列表

        Args:
            cmd: ADB shell 命令字符串

        Returns:
            完整的命令列表，可直接传递给 subprocess
        """
        if self.device_id:
            return ["adb", "-s", self.device_id, "shell", cmd]
        return ["adb", "shell", cmd]

    def _execute_shell(self, cmd: str, timeout: int = 30) -> subprocess.CompletedProcess:
        """
        执行 ADB shell 命令

        Args:
            cmd: 要执行的 shell 命令
            timeout: 命令执行超时时间（秒）

        Returns:
            subprocess.CompletedProcess 对象，包含执行结果
        """
        full_cmd = self._build_adb_command(cmd)
        return subprocess.run(
            full_cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',  # 忽略无法解码的字符，防止 Windows GBK 编码崩溃
            timeout=timeout
        )

    def _execute_adb(self, args: list[str], timeout: int = 30) -> subprocess.CompletedProcess:
        """
        执行 ADB 命令（非 shell）

        Args:
            args: ADB 命令参数列表
            timeout: 命令执行超时时间（秒）

        Returns:
            subprocess.CompletedProcess 对象
        """
        if self.device_id:
            cmd = ["adb", "-s", self.device_id] + args
        else:
            cmd = ["adb"] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore',  # 忽略无法解码的字符，防止 Windows GBK 编码崩溃
            timeout=timeout
        )

    def click(self, x: int, y: int) -> bool:
        """
        在指定坐标执行点击操作

        Args:
            x: 点击位置的 X 坐标
            y: 点击位置的 Y 坐标

        Returns:
            True 表示命令执行成功，False 表示失败
        """
        try:
            result = self._execute_shell(f"input tap {x} {y}")
            if result.returncode == 0:
                print(f"[点击成功] 坐标: ({x}, {y})")
                return True
            else:
                print(f"[点击失败] 错误信息: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            print("[点击失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[点击失败] 异常: {e}")
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 300) -> bool:
        """
        执行滑动操作

        Args:
            x1: 起始点 X 坐标
            y1: 起始点 Y 坐标
            x2: 终点 X 坐标
            y2: 终点 Y 坐标
            duration: 滑动持续时间（毫秒），默认 300ms

        Returns:
            True 表示命令执行成功，False 表示失败
        """
        try:
            result = self._execute_shell(
                f"input swipe {x1} {y1} {x2} {y2} {duration}"
            )
            if result.returncode == 0:
                print(f"[滑动成功] 从 ({x1}, {y1}) 滑动到 ({x2}, {y2})")
                return True
            else:
                print(f"[滑动失败] 错误信息: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            print("[滑动失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[滑动失败] 异常: {e}")
            return False

    def go_back(self) -> bool:
        """
        按下系统返回键

        使用 ADB input keyevent 命令发送 KEYCODE_BACK (4)

        Returns:
            True 表示命令执行成功，False 表示失败
        """
        try:
            # KEYCODE_BACK = 4
            result = self._execute_shell("input keyevent 4")
            if result.returncode == 0:
                print("[返回键成功] 已按下系统返回键")
                return True
            else:
                print(f"[返回键失败] 错误信息: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            print("[返回键失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[返回键失败] 异常: {e}")
            return False

    def go_home(self) -> bool:
        """
        按下系统 Home 键

        使用 ADB input keyevent 命令发送 KEYCODE_HOME (3)

        Returns:
            True 表示命令执行成功，False 表示失败
        """
        try:
            # KEYCODE_HOME = 3
            result = self._execute_shell("input keyevent 3")
            if result.returncode == 0:
                print("[Home键成功] 已按下系统 Home 键，返回桌面")
                return True
            else:
                print(f"[Home键失败] 错误信息: {result.stderr}")
                return False
        except subprocess.TimeoutExpired:
            print("[Home键失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[Home键失败] 异常: {e}")
            return False

    def scroll_down(self) -> bool:
        """
        向下滚动屏幕（查看下方内容）

        手势：从屏幕下部向上滑动，使内容向下滚动

        Returns:
            True 表示命令执行成功，False 表示失败
        """
        try:
            # 获取屏幕分辨率
            width, height = self.get_screen_resolution()

            # 动态计算滚动坐标
            # 从屏幕 80% 高度滑动到 20% 高度
            start_y = int(height * 0.8)
            end_y = int(height * 0.2)
            center_x = width // 2

            # 优先尝试 UIAutomator2 滚动
            if UIAUTOMATOR2_AVAILABLE:
                try:
                    device = self._get_u2_device()
                    if device:
                        print(f"[滚动] 尝试 UIAutomator2 滚动...")
                        # 使用 UIAutomator2 的 fling 向上滑动（内容向下滚动）
                        device(scrollable=True).fling.forward()
                        print("[滚动成功] UIAutomator2 滚动完成")
                        return True
                except Exception as e:
                    print(f"[滚动] UIAutomator2 滚动失败: {e}，尝试 ADB 方式...")

            # 回退到 ADB input swipe
            swipe_cmd = f"input swipe {center_x} {start_y} {center_x} {end_y} 500"
            print(f"[滚动] 执行 ADB: {swipe_cmd}")
            print(f"[滚动] 屏幕尺寸: {width}x{height}, 滑动距离: {start_y - end_y}px")

            result = self._execute_shell(swipe_cmd)

            # 详细输出执行结果
            print(f"[滚动] 命令返回码: {result.returncode}")
            if result.stdout:
                print(f"[滚动] stdout: {result.stdout.strip()}")
            if result.stderr:
                print(f"[滚动] stderr: {result.stderr.strip()}")

            if result.returncode == 0:
                print("[滚动成功] 已向下滚动屏幕")
                return True
            else:
                print(f"[滚动失败] 返回码非零")
                return False
        except subprocess.TimeoutExpired:
            print("[滚动失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[滚动失败] 异常: {e}")
            return False

    def scroll_up(self) -> bool:
        """
        向上滚动屏幕（查看上方内容）

        手势：从屏幕上部向下滑动，使内容向上滚动

        Returns:
            True 表示命令执行成功，False 表示失败
        """
        try:
            # 获取屏幕分辨率
            width, height = self.get_screen_resolution()

            # 动态计算滚动坐标
            # 从屏幕 20% 高度滑动到 80% 高度
            start_y = int(height * 0.2)
            end_y = int(height * 0.8)
            center_x = width // 2

            # 优先尝试 UIAutomator2 滚动
            if UIAUTOMATOR2_AVAILABLE:
                try:
                    device = self._get_u2_device()
                    if device:
                        print(f"[滚动] 尝试 UIAutomator2 滚动...")
                        # 使用 UIAutomator2 的 fling 向下滑动（内容向上滚动）
                        device(scrollable=True).fling.backward()
                        print("[滚动成功] UIAutomator2 滚动完成")
                        return True
                except Exception as e:
                    print(f"[滚动] UIAutomator2 滚动失败: {e}，尝试 ADB 方式...")

            # 回退到 ADB input swipe
            swipe_cmd = f"input swipe {center_x} {start_y} {center_x} {end_y} 500"
            print(f"[滚动] 执行 ADB: {swipe_cmd}")
            print(f"[滚动] 屏幕尺寸: {width}x{height}, 滑动距离: {end_y - start_y}px")

            result = self._execute_shell(swipe_cmd)

            # 详细输出执行结果
            print(f"[滚动] 命令返回码: {result.returncode}")
            if result.stdout:
                print(f"[滚动] stdout: {result.stdout.strip()}")
            if result.stderr:
                print(f"[滚动] stderr: {result.stderr.strip()}")

            if result.returncode == 0:
                print("[滚动成功] 已向上滚动屏幕")
                return True
            else:
                print(f"[滚动失败] 返回码非零")
                return False
        except subprocess.TimeoutExpired:
            print("[滚动失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[滚动失败] 异常: {e}")
            return False

    def dump_ui(self, save_dir: str = "temp_data") -> Optional[Path]:
        """
        导出当前界面的 UI 层级结构

        执行流程：
        1. 优先使用 UIAutomator2 的 dump_hierarchy() 方法（如果可用）
        2. 否则使用 ADB uiautomator dump 命令

        Args:
            save_dir: 本地保存目录，默认为 temp_data

        Returns:
            成功时返回本地文件的 Path 对象，失败时返回 None
        """
        self.last_ui_dump_error = ""

        # 设备上的 dump 文件路径（ADB 方式使用）
        device_ui_path = "/sdcard/window_dump.xml"

        # 确保本地目录存在
        local_dir = Path(save_dir)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_output_path = local_dir / "current_ui.xml"

        # 优先尝试使用 UIAutomator2 的 dump_hierarchy()
        if UIAUTOMATOR2_AVAILABLE:
            try:
                print("[UI导出] 尝试使用 UIAutomator2 dump_hierarchy()...")
                device = self._get_u2_device()
                if device:
                    # 使用 UIAutomator2 获取 UI 层次结构
                    xml_content = device.dump_hierarchy()
                    if xml_content:
                        # 保存到本地文件
                        with open(local_output_path, 'w', encoding='utf-8') as f:
                            f.write(xml_content)
                        print(f"[UI导出成功] 使用 UIAutomator2，文件已保存到: {local_output_path}")
                        return local_output_path
                    self.last_ui_dump_error = "UIAutomator2 dump_hierarchy returned empty XML"
                else:
                    self.last_ui_dump_error = "UIAutomator2 device unavailable"
            except Exception as e:
                self.last_ui_dump_error = f"UIAutomator2 dump_hierarchy failed: {e}"
                print(f"[UIAutomator2] dump_hierarchy 失败: {e}，尝试 ADB 方式...")

        # 回退到 ADB uiautomator dump 方式
        try:
            # 步骤1: 在设备上执行 uiautomator dump
            print("[UI导出] 正在执行 uiautomator dump...")
            dump_result = self._execute_shell(
                f"uiautomator dump {device_ui_path}",
                timeout=60
            )

            if dump_result.returncode != 0:
                self.last_ui_dump_error = (
                    f"ADB uiautomator dump failed: {dump_result.stderr or dump_result.stdout}"
                )
                print(f"[UI导出失败] 错误信息: {dump_result.stderr}")
                return None

            # 步骤2: 等待 XML 文件生成完成
            print("[UI导出] 等待 XML 文件生成...")
            time.sleep(1.5)

            # 步骤3: 将文件从设备拉取到本地
            print(f"[UI导出] 正在拉取文件到本地: {local_output_path}")
            pull_result = self._execute_adb(["pull", device_ui_path, str(local_output_path)])

            if pull_result.returncode == 0 and local_output_path.exists():
                self.last_ui_dump_error = ""
                print(f"[UI导出成功] 文件已保存到: {local_output_path}")
                return local_output_path
            else:
                self.last_ui_dump_error = (
                    f"ADB pull failed: {pull_result.stderr or pull_result.stdout}"
                )
                print(f"[UI导出失败] 拉取文件失败: {pull_result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            self.last_ui_dump_error = "ADB uiautomator dump timed out"
            print("[UI导出失败] 命令执行超时")
            return None
        except Exception as e:
            self.last_ui_dump_error = f"ADB uiautomator dump exception: {e}"
            print(f"[UI导出失败] 异常: {e}")
            return None

    def get_current_activity(self) -> str:
        """
        获取当前处于焦点的应用包名和 Activity 名称

        采用多命令回退策略，依次尝试以下三条命令，直到成功为止：
        1. dumpsys activity activities | grep mResumedActivity  (推荐，Android 10+)
        2. dumpsys window windows | grep -E 'mCurrentFocus|mFocusedApp'
        3. dumpsys activity top | grep ACTIVITY (改进版：收集所有行，过滤 Launcher)
        4. UIAutomator2 device.app_current() 作为兜底

        Returns:
            Activity 名称字符串，格式示例：'Settings'
            如果获取失败或无法解析，返回 'UnknownActivity'
        """
        # 定义获取策略
        strategies = [
            {
                "name": "mResumedActivity",
                "cmd": "dumpsys activity activities",
                "keywords": ["mResumedActivity"],
                "description": "dumpsys activity activities (Android 10+)"
            },
            {
                "name": "mCurrentFocus/mFocusedApp",
                "cmd": "dumpsys window windows",
                "keywords": ["mCurrentFocus", "mFocusedApp"],
                "description": "dumpsys window windows"
            },
            {
                "name": "ACTIVITY",
                "cmd": "dumpsys activity top",
                "keywords": ["ACTIVITY"],
                "description": "dumpsys activity top (improved)"
            }
        ]

        # 依次尝试每种策略
        for strategy in strategies:
            try:
                print(f"[Activity获取] 尝试策略: {strategy['description']}")

                result = self._execute_shell(strategy["cmd"], timeout=10)

                if result.returncode != 0:
                    print(f"[Activity获取] 命令执行失败，尝试下一策略")
                    continue

                output = result.stdout

                # ========== 特殊处理：策略3 dumpsys activity top ==========
                # 该策略输出任务栈历史记录，需要收集所有 ACTIVITY 行并过滤 Launcher
                if strategy["name"] == "ACTIVITY":
                    # 收集所有 ACTIVITY 行
                    activity_lines = []
                    for line in output.split("\n"):
                        line_stripped = line.strip()
                        if "ACTIVITY" in line_stripped:
                            activity_lines.append(line_stripped)

                    if not activity_lines:
                        print(f"[Activity获取] 未找到 ACTIVITY 信息，尝试下一策略")
                        continue

                    print(f"[Activity获取] 收集到 {len(activity_lines)} 个 ACTIVITY 行")

                    # 从后往前查找（栈顶通常是最后一个）
                    for act_line in reversed(activity_lines):
                        print(f"[Activity获取] 检查 ACTIVITY 行: {act_line[:80]}...")
                        activity_name = self._extract_activity_from_line(act_line)

                        if activity_name:
                            # 过滤 Launcher Activity
                            if activity_name in self.LAUNCHER_ACTIVITY_BLACKLIST:
                                print(f"[Activity获取] 过滤 Launcher: {activity_name}，尝试下一行")
                                continue

                            print(f"[Activity获取成功] 当前 Activity: {activity_name}")
                            return activity_name

                    # 如果都被过滤了，继续尝试其他策略
                    print(f"[Activity获取] 所有 ACTIVITY 行均为 Launcher，尝试下一策略")
                    continue

                # ========== 常规策略处理 ==========
                matched_line = None
                matched_keyword = None

                for line in output.split("\n"):
                    line_stripped = line.strip()
                    for keyword in strategy["keywords"]:
                        if keyword in line_stripped:
                            matched_line = line_stripped
                            matched_keyword = keyword
                            break
                    if matched_line:
                        break

                if not matched_line:
                    print(f"[Activity获取] 未找到 {strategy['keywords']} 信息，尝试下一策略")
                    continue

                print(f"[Activity获取] 匹配到关键字 '{matched_keyword}': {matched_line}")

                # 提取 Activity 名称
                activity_name = self._extract_activity_from_line(matched_line)

                if activity_name:
                    # 过滤 Launcher Activity
                    if activity_name in self.LAUNCHER_ACTIVITY_BLACKLIST:
                        print(f"[Activity获取] 过滤 Launcher: {activity_name}，尝试下一策略")
                        continue

                    print(f"[Activity获取成功] 当前 Activity: {activity_name}")
                    return activity_name
                else:
                    print(f"[Activity解析失败] 无法从行中提取: {matched_line}")
                    continue

            except subprocess.TimeoutExpired:
                print(f"[Activity获取] 命令超时，尝试下一策略")
                continue
            except Exception as e:
                print(f"[Activity获取] 异常: {e}，尝试下一策略")
                continue

        # ========== 所有 ADB 策略都失败，尝试 UIAutomator2 作为兜底 ==========
        print("[Activity获取] 所有 ADB 策略失败，尝试 UIAutomator2...")

        u2_pkg, u2_activity = self.get_current_activity_u2()
        if u2_activity and u2_activity not in self.LAUNCHER_ACTIVITY_BLACKLIST:
            print(f"[Activity获取成功] UIAutomator2: {u2_activity}")
            return u2_activity

        print("[Activity获取失败] 所有方法均未成功")
        return "UnknownActivity"

    def get_current_package(self) -> str:
        """
        获取当前处于焦点的应用包名

        Returns:
            包名字符串，如 'com.android.settings'
            获取失败返回 'unknown.package'
        """
        # 多种策略，适应不同安卓版本
        strategies = [
            {
                "name": "mResumedActivity (dumpsys activity activities)",
                "cmd": "dumpsys activity activities",
                "keyword": "mResumedActivity"
            },
            {
                "name": "mCurrentFocus (dumpsys window windows)",
                "cmd": "dumpsys window windows",
                "keyword": "mCurrentFocus"
            },
            {
                "name": "top-activity (dumpsys activity top)",
                "cmd": "dumpsys activity top",
                "keyword": "ACTIVITY"  # 新格式: ACTIVITY com.xxx.xxx/...
            },
            {
                "name": "focused-app (dumpsys window)",
                "cmd": "dumpsys window",
                "keyword": "mCurrentFocus"
            }
        ]

        for strategy in strategies:
            try:
                print(f"[包名获取] 尝试策略: {strategy['name']}")
                result = self._execute_shell(strategy["cmd"], timeout=15)

                if result.returncode != 0:
                    print(f"[包名获取] 命令失败，返回码: {result.returncode}")
                    continue

                output = result.stdout

                # 在输出中搜索
                for line in output.split("\n"):
                    line_stripped = line.strip()

                    # 跳过空行
                    if not line_stripped:
                        continue

                    # 检查是否包含关键词
                    if strategy["keyword"] in line_stripped:
                        print(f"[包名获取] 匹配到行: {line_stripped[:100]}...")

                        # 尝试多种正则模式提取包名
                        patterns = [
                            # 格式1: com.example.app/xxx 或 com.example.app/.xxx
                            r'([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)/',
                            # 格式2: ACTIVITY com.example.app/xxx (Android 11+)
                            r'ACTIVITY\s+([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)/',
                            # 格式3: 包名直接出现在 Window{...} 中
                            r'Window\{[^}]*\s+([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)/',
                        ]

                        for pattern in patterns:
                            match = re.search(pattern, line_stripped)
                            if match:
                                package_name = match.group(1)
                                # 验证是否是合法的包名格式
                                if '.' in package_name and len(package_name) > 3:
                                    # 过滤掉 Launcher 和系统 UI
                                    if package_name not in self.LAUNCHER_PACKAGE_BLACKLIST:
                                        print(f"[包名获取成功] {package_name}")
                                        return package_name

            except subprocess.TimeoutExpired:
                print(f"[包名获取] 命令超时，尝试下一策略")
                continue
            except Exception as e:
                print(f"[包名获取] 异常: {e}，尝试下一策略")
                continue

        print("[包名获取失败] 所有策略均未成功")
        return "unknown.package"

    def get_input_focus_state(self) -> Dict[str, Any]:
        """
        Collect lightweight focus/IME facts for state-diff analysis.

        This is intentionally best-effort. ADB dumpsys output varies across
        Android versions, so callers should treat missing fields as unknown.
        """
        state: Dict[str, Any] = {
            "ime_visible": False,
            "current_focus": "",
            "focused_app": "",
            "input_method_target": "",
            "served_view": "",
            "errors": [],
        }

        try:
            result = self._execute_shell("dumpsys input_method", timeout=5)
            if result.returncode == 0:
                output = result.stdout or ""
                lowered = output.lower()
                state["ime_visible"] = any(
                    marker in lowered
                    for marker in (
                        "minputshown=true",
                        "misinputviewshown=true",
                        "inputshown=true",
                        "input view shown=true",
                    )
                ) or bool(re.search(r"mImeWindowVis=0x[1-9a-fA-F]", output))
                state["served_view"] = self._extract_dumpsys_value(
                    output,
                    ("mServedView", "mNextServedView", "servedView"),
                )
            else:
                state["errors"].append("dumpsys input_method failed")
        except Exception as exc:
            state["errors"].append(f"dumpsys input_method error: {exc}")

        try:
            result = self._execute_shell("dumpsys window windows", timeout=5)
            if result.returncode == 0:
                output = result.stdout or ""
                state["current_focus"] = self._extract_dumpsys_value(
                    output,
                    ("mCurrentFocus", "mFocusedWindow"),
                )
                state["focused_app"] = self._extract_dumpsys_value(
                    output,
                    ("mFocusedApp",),
                )
                state["input_method_target"] = self._extract_dumpsys_value(
                    output,
                    ("mInputMethodTarget", "mInputMethodWindow"),
                )
                if not state["ime_visible"]:
                    target = (state.get("input_method_target") or "").lower()
                    state["ime_visible"] = "inputmethod" in target or "ime" in target
            else:
                state["errors"].append("dumpsys window windows failed")
        except Exception as exc:
            state["errors"].append(f"dumpsys window windows error: {exc}")

        return state

    @staticmethod
    def _extract_dumpsys_value(output: str, keys: Tuple[str, ...]) -> str:
        for line in output.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            for key in keys:
                if key not in stripped:
                    continue
                if "=" in stripped:
                    value = stripped.split("=", 1)[1].strip()
                elif ":" in stripped:
                    value = stripped.split(":", 1)[1].strip()
                else:
                    value = stripped
                value = re.sub(r"\s+", " ", value)
                return value[:220]
        return ""

    def get_current_activity_u2(self) -> Tuple[str, str]:
        """
        使用 UIAutomator2 获取当前 Activity（辅助验证/兜底方案）

        Returns:
            元组 (package_name, activity_name)
            如果获取失败，返回 ("", "")
        """
        if not UIAUTOMATOR2_AVAILABLE:
            return "", ""

        device = self._get_u2_device()
        if not device:
            return "", ""

        try:
            # device.app_current() 返回当前前台应用信息
            app_info = device.app_current()
            package = app_info.get('package', '')
            activity = app_info.get('activity', '')

            if package and activity:
                # 提取 Activity 简短名称
                if '.' in activity:
                    activity_name = activity.split('.')[-1]
                else:
                    activity_name = activity

                print(f"[UIAutomator2] 当前应用: {package}/{activity}")
                return package, activity_name
        except Exception as e:
            print(f"[UIAutomator2] 获取失败: {e}")

        return "", ""

    def _extract_activity_from_line(self, line: str) -> Optional[str]:
        """
        从 dumpsys 输出行中提取 Activity 名称

        支持多种格式：
        1. mResumedActivity: ActivityRecord{... com.android.settings/.Settings}
        2. mCurrentFocus=Window{... com.android.settings/.Settings}
        3. mCurrentFocus=Window{... com.android.settings/com.android.settings.Settings}
        4. ACTIVITY com.android.settings/.Settings pid=1234
        5. mFocusedApp=AppWindowToken{... ActivityRecord{... com.example.app/.MainActivity}}

        Args:
            line: dumpsys 输出的一行内容

        Returns:
            提取的 Activity 名称（如 'Settings'），解析失败返回 None
        """
        if not line or "null" in line.lower():
            return None

        try:
            # ========== 策略1：匹配标准组件名格式 ==========
            # 格式：包名/.简短Activity名 或 包名/完整类名
            # 例如：com.android.settings/.Settings
            #      com.example.app/com.example.app.MainActivity

            # 匹配：包名/.Activity名（简写形式，如 .Settings）
            short_form_pattern = r'([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)/\.([A-Z][a-zA-Z0-9]*)'
            short_match = re.search(short_form_pattern, line)
            if short_match:
                activity_name = short_match.group(2)
                print(f"[解析成功] 短格式匹配: {activity_name}")
                return activity_name

            # 匹配：包名/完整类名（如 com.example.app/com.example.app.MainActivity）
            full_form_pattern = r'([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)/([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*\.[A-Z][a-zA-Z0-9]*)'
            full_match = re.search(full_form_pattern, line)
            if full_match:
                activity_full = full_match.group(2)
                # 提取最后一个 '.' 之后的部分
                activity_name = activity_full.split(".")[-1]
                print(f"[解析成功] 完整格式匹配: {activity_name}")
                return activity_name

            # ========== 策略2：匹配 Window{...} 中的内容 ==========
            # 格式：Window{hash state uid component}
            window_pattern = r'Window\{[^}]*\s+([^\s}]+)\s*\}'
            window_match = re.search(window_pattern, line)
            if window_match:
                component = window_match.group(1)
                activity_name = self._parse_component_name(component)
                if activity_name:
                    print(f"[解析成功] Window 格式匹配: {activity_name}")
                    return activity_name

            # ========== 策略3：匹配 ActivityRecord{...} 中的内容 ==========
            # 格式：ActivityRecord{... component}
            record_pattern = r'ActivityRecord\{[^}]*\s+([^\s}]+)\s*\}'
            record_match = re.search(record_pattern, line)
            if record_match:
                component = record_match.group(1)
                activity_name = self._parse_component_name(component)
                if activity_name:
                    print(f"[解析成功] ActivityRecord 格式匹配: {activity_name}")
                    return activity_name

            # ========== 策略4：直接查找可能的 Activity 名称 ==========
            # 作为最后的回退，查找以大写字母开头的类名
            # 匹配 .ActivityName 或 /ActivityName 模式
            fallback_pattern = r'[/.]([A-Z][a-zA-Z0-9]*(?:Activity|Fragment|Screen|Page|Dialog|View))?'
            fallback_matches = re.findall(fallback_pattern, line)
            for match in fallback_matches:
                if match:  # 非空匹配
                    print(f"[解析成功] 回退匹配: {match}")
                    return match

            # 如果以上都没有，尝试找任何以大写字母开头的单词
            word_pattern = r'\b([A-Z][a-zA-Z0-9]{2,})\b'
            word_matches = re.findall(word_pattern, line)
            # 过滤掉一些常见的非 Activity 关键字
            exclude_words = {'Window', 'ActivityRecord', 'AppWindowToken', 'null', 'Build', 'VERSION'}
            for word in word_matches:
                if word not in exclude_words:
                    print(f"[解析成功] 通用匹配: {word}")
                    return word

            return None

        except Exception as e:
            print(f"[Activity解析异常] {e}")
            return None

    def _parse_component_name(self, component: str) -> Optional[str]:
        """
        解析组件名，提取 Activity 名称

        支持格式：
        - com.example.app/.MainActivity -> MainActivity
        - com.example.app/com.example.app.MainActivity -> MainActivity
        - .Settings -> Settings
        - com.example.app.MainActivity -> MainActivity

        Args:
            component: 组件名字符串

        Returns:
            Activity 名称，解析失败返回 None
        """
        if not component:
            return None

        try:
            # 如果包含 '/'，取后面的部分
            if "/" in component:
                activity_part = component.split("/")[-1]
            else:
                activity_part = component

            # 如果以 '.' 开头（如 .Settings），去掉开头的点
            if activity_part.startswith("."):
                activity_part = activity_part[1:]

            # 如果包含 '.'，取最后一部分
            if "." in activity_part:
                activity_name = activity_part.split(".")[-1]
            else:
                activity_name = activity_part

            # 确保首字母是大写（Activity 名称约定）
            if activity_name and activity_name[0].isupper():
                return activity_name

            return None

        except Exception as e:
            print(f"[组件名解析异常] {e}")
            return None

    def clear_text_by_backspace(self, max_chars: int = 100) -> bool:
        """
        通过发送退格键清除文本（适用于 WebView 等场景）

        优化策略：
        1. 发送 KEYCODE_MOVE_END (123) 移动光标到末尾
        2. 发送 KEYCODE_SHIFT_LEFT (59) + KEYCODE_DPAD_LEFT (21) 全选（可选）
        3. 发送 KEYCODE_DEL (67) 删除

        Args:
            max_chars: 最多删除的字符数，默认 100

        Returns:
            True 表示成功，False 表示失败
        """
        try:
            # 移动光标到末尾
            self._execute_shell("input keyevent 123")
            time.sleep(0.05)

            # 方案A：尝试使用 Ctrl+A 全选（部分 WebView 支持）
            # KEYCODE_CTRL_LEFT = 113, KEYCODE_A = 29
            self._execute_shell("input keyevent 113 29")
            time.sleep(0.1)
            self._execute_shell("input keyevent 67")  # 删除选中内容
            time.sleep(0.1)

            # 方案B：发送多次退格键确保清除（批量发送，无延迟）
            # 使用 shell 脚本批量发送，避免 Python 循环延迟
            print(f"[WebView清除] 发送 {max_chars} 次退格键...")
            # 构建 shell 命令，一次发送多个 keyevent
            backspace_cmd = "input keyevent 67 " * max_chars
            backspace_cmd = backspace_cmd.strip()
            self._execute_shell(backspace_cmd)

            print("[WebView清除] 清除完成")
            return True
        except Exception as e:
            print(f"[WebView清除] 异常: {e}")
            return False

    def _hide_keyboard_by_keyevent(self) -> bool:
        """Dismiss the soft keyboard without sending ENTER into the focused field."""
        try:
            before = self.get_input_focus_state()
            if not before.get("ime_visible"):
                print("[hide_keyboard] IME is not visible; no keyevent needed")
                return True
            if not self._focus_state_has_editable_view(before):
                print("[hide_keyboard] IME visibility looks stale; no editable focus, skip keyevent")
                return True

            for keycode, name in ((111, "ESCAPE"), (4, "BACK")):
                print(f"[hide_keyboard] Sending {name} to dismiss IME")
                result = self._execute_shell(f"input keyevent {keycode}", timeout=5)
                time.sleep(0.25)

                if result.returncode != 0:
                    print(f"[hide_keyboard] {name} failed: {result.stderr}")
                    continue

                after = self.get_input_focus_state()
                if not after.get("ime_visible") or not self._focus_state_has_editable_view(after):
                    print(f"[hide_keyboard] IME dismissed by {name}")
                    return True

            print("[hide_keyboard] IME still visible after ESC/BACK")
            return False
        except Exception as e:
            print(f"[hide_keyboard] Safe dismiss failed: {e}")
            return False

    @staticmethod
    def _focus_state_has_editable_view(state: Dict[str, Any]) -> bool:
        """Return whether dumpsys focus facts point at an editable input view."""
        text = " ".join(
            str(state.get(key) or "")
            for key in ("current_focus", "served_view", "input_method_target")
        ).lower()
        return any(token in text for token in ("edittext", "textfield", "textinput"))

    def hide_keyboard(self) -> bool:
        """Dismiss the soft keyboard after text input without sending ENTER."""
        try:
            if UIAUTOMATOR2_AVAILABLE:
                device = self._get_u2_device()
                if device:
                    try:
                        focused_elem = device(focused=True)
                        if focused_elem.exists:
                            return self._hide_keyboard_by_keyevent()
                    except Exception as e:
                        print(f"[hide_keyboard] UIAutomator2 focus check failed: {e}")

            return self._hide_keyboard_by_keyevent()
        except Exception as e:
            print(f"[hide_keyboard] failed: {e}")
            return False

    def disable_soft_keyboard(self) -> bool:
        """
        禁用软键盘自动弹出

        使用 UIAutomator2 的快速输入法 (FastInputIME)，实现无键盘输入：
        - FastInputIME 是 u2 内置的轻量输入法，不会弹出软键盘界面
        - 输入通过 UIAutomator2 直接注入，不经过系统输入法框架

        如果 u2 不可用，则使用备用方法设置系统参数。

        Returns:
            True 表示设置成功
        """
        try:
            print("[禁用键盘] 正在设置...")

            # 方法1：使用 UIAutomator2 的 FastInputIME（推荐）
            u2_device = self._get_u2_device()
            if u2_device:
                try:
                    # 设置使用 FastInputIME（u2 内置的无界面输入法）
                    u2_device.set_fastinput_ime(True)
                    print("[禁用键盘] UIAutomator2 FastInputIME 已启用")
                    print("[禁用键盘] 输入将直接注入，不弹出软键盘")
                    time.sleep(0.5)
                    return True
                except Exception as e:
                    print(f"[禁用键盘] FastInputIME 设置失败: {e}")

            # 方法2：备用 - 设置系统参数（效果有限）
            print("[禁用键盘] 尝试备用方法...")
            self._execute_shell("settings put secure show_ime_with_hard_keyboard 0")
            self._execute_shell("settings put global window_animation_scale 0")
            self._execute_shell("settings put global transition_animation_scale 0")

            # 方法3：尝试关闭当前输入法（激进方式）
            # 获取当前默认输入法
            default_ime = self.get_default_ime()
            if default_ime:
                print(f"[禁用键盘] 当前默认输入法: {default_ime}")
                # 不直接禁用，因为这会影响用户正常使用
                # 只在测试期间临时使用 FastInputIME

            time.sleep(0.5)
            print("[禁用键盘] 设置完成（备用方法）")
            return True
        except Exception as e:
            print(f"[禁用键盘] 异常: {e}")
            return False

    def get_default_ime(self) -> str:
        """
        获取当前默认输入法

        Returns:
            默认输入法 ID，如 "com.google.android.inputmethod.latin/.LatinIME"
        """
        try:
            result = self._execute_shell("settings get secure default_input_method")
            ime = result.stdout.strip()
            print(f"[输入法] 当前默认: {ime}")
            return ime
        except Exception as e:
            print(f"[输入法] 获取失败: {e}")
            return ""

    def set_default_ime(self, ime_id: str) -> bool:
        """
        设置默认输入法

        Args:
            ime_id: 输入法 ID，如 "com.android.inputmethod.latin/.LatinIME"

        Returns:
            True 表示成功
        """
        try:
            self._execute_shell(f"settings put secure default_input_method {ime_id}")
            print(f"[输入法] 已设置为: {ime_id}")
            return True
        except Exception as e:
            print(f"[输入法] 设置失败: {e}")
            return False

    def input_text_by_coordinate(
        self,
        center_x: int,
        center_y: int,
        text: str,
        clear_first: bool = True,
        max_clear_chars: int = 100
    ) -> bool:
        """
        通过坐标定位输入框并输入文本（WebView 兜底方案）

        流程：
        1. 点击坐标获取焦点
        2. 使用退格键清除旧文本
        3. 输入新文本

        Args:
            center_x: 输入框中心的 X 坐标
            center_y: 输入框中心的 Y 坐标
            text: 要输入的文本
            clear_first: 是否先清除旧文本
            max_clear_chars: 清除时最多删除的字符数

        Returns:
            True 表示成功，False 表示失败
        """
        if not text:
            return False

        try:
            # 点击获取焦点
            print(f"[坐标输入] 点击 ({center_x}, {center_y})")
            self.click(center_x, center_y)
            time.sleep(0.3)

            # 清除旧文本
            if clear_first:
                self.clear_text_by_backspace(max_clear_chars)

            # 输入新文本
            escaped_text = text.replace(" ", "%s")
            escaped_text = escaped_text.replace("&", "\\&")
            escaped_text = escaped_text.replace("(", "\\(")
            escaped_text = escaped_text.replace(")", "\\)")
            result = self._execute_shell(f'input text "{escaped_text}"')

            if result.returncode == 0:
                print(f"[坐标输入] 成功输入: {text}")
                return True
            else:
                print(f"[坐标输入] 输入失败: {result.stderr}")
                return False
        except Exception as e:
            print(f"[坐标输入] 异常: {e}")
            return False

    def input_text(self, text: str, clear_first: bool = False) -> bool:
        """
        使用 ADB input text 命令输入文本

        注意：ADB 的 input text 命令不支持直接输入空格，
        需要将空格替换为 %s 才能正确输入。
        同时需要转义一些特殊字符如 &、(、) 等。

        Args:
            text: 要输入的文本字符串
            clear_first: 是否先清除输入框内容

        Returns:
            True 表示输入成功，False 表示失败
        """
        if not text:
            print("[输入失败] 文本为空")
            return False

        try:
            # 如果需要，先清除输入框
            if clear_first:
                print("[ADB输入] 先清除输入框内容...")
                # 发送 Ctrl+A 选择全部，然后 Del 删除
                # KEYCODE_CTRL_LEFT = 113, KEYCODE_A = 29, KEYCODE_DEL = 67
                self._execute_shell("input keyevent 113")  # CTRL
                time.sleep(0.05)
                self._execute_shell("input keyevent 29")   # A (全选)
                time.sleep(0.05)
                self._execute_shell("input keyevent 67")   # DEL (删除)
                time.sleep(0.1)
                # 再发送几次 DEL 确保清除
                for _ in range(3):
                    self._execute_shell("input keyevent 67")
                    time.sleep(0.05)
                print("[ADB输入] 清除完成")

            # 转义特殊字符
            escaped_text = text
            # 1. 空格替换为 %s（ADB input text 的特殊语法）
            escaped_text = escaped_text.replace(" ", "%s")
            # 2. 转义其他特殊字符
            escaped_text = escaped_text.replace("&", "\\&")
            escaped_text = escaped_text.replace("(", "\\(")
            escaped_text = escaped_text.replace(")", "\\)")

            print(f"[文本输入] 原始文本: '{text}'")
            print(f"[文本输入] 转义后: '{escaped_text}'")

            # 执行 input text 命令
            result = self._execute_shell(f'input text "{escaped_text}"')

            if result.returncode == 0:
                print(f"[输入成功] 已输入文本: {text}")
                return True
            else:
                print(f"[输入失败] 错误信息: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print("[输入失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[输入失败] 异常: {e}")
            return False

    def clear_and_input_text(self, widget_info: Dict[str, Any], text: str) -> bool:
        """
        使用多层策略清除输入框并输入文本

        三层策略：
        1. UIAutomator2 原生方式 - 使用 resource_id/text/className 选择器
        2. UIAutomator2 focused 方式 - 点击坐标后使用 focused=True 选择器
        3. ADB 坐标方式 - 点击坐标 + MOVE_END + 退格清除 + input text

        Args:
            widget_info: 控件信息字典，包含 text, resource_id, bounds, center_x, center_y 等
            text: 要输入的文本字符串

        Returns:
            True 表示输入成功，False 表示失败
        """
        if not text:
            print("[输入失败] 文本为空")
            return False

        device = self._get_u2_device()
        center_x = widget_info.get("center_x")
        center_y = widget_info.get("center_y")

        # 检查控件类型
        class_name = widget_info.get("class", "")
        is_edittext = class_name and "EditText" in class_name

        # 调试：打印控件信息
        print(f"[输入策略检查] class={class_name}, is_edittext={is_edittext}, center=({center_x},{center_y})")

        # ========== 策略选择 ==========
        # 关键判断：如果 class 不是 EditText，直接使用 ADB 坐标方式
        # 因为 UIAutomator2 的 send_keys() 对 TextView 静默失败（不报错但无效）
        # 即使 xml_parser 标记了 editable=True，也需要用 ADB 方式
        if not is_edittext:
            if center_x and center_y:
                print(f"[输入策略] 控件非 EditText (class={class_name})，使用 ADB 坐标方式")
                return self.input_text_by_coordinate(center_x, center_y, text)
            else:
                print(f"[输入策略] 控件非 EditText 但缺少坐标，尝试 UIAutomator2 方式")

        # ========== 第一层：UIAutomator2 原生方式 ==========
        # 仅对真正的 EditText 或可编辑控件使用
        if device is not None:
            selector = self._build_u2_selector(widget_info)
            if selector is not None:
                try:
                    element = device(**selector)
                    if element.exists:
                        print("[UIAutomator2-原生] 找到元素")
                        element.click()
                        time.sleep(0.2)
                        element.clear_text()
                        element.send_keys(text)
                        print("[UIAutomator2-原生] 输入成功")
                        return True
                except Exception as e:
                    print(f"[UIAutomator2-原生] 失败: {e}")

        # ========== 第二层：UIAutomator2 focused 方式 ==========
        if center_x and center_y and device is not None:
            print(f"[UIAutomator2-focused] 点击 ({center_x}, {center_y}) 获取焦点")
            self.click(center_x, center_y)
            time.sleep(0.3)

            try:
                element = device(focused=True)
                if element.exists:
                    print("[UIAutomator2-focused] 找到焦点元素")
                    element.clear_text()
                    element.send_keys(text)
                    print("[UIAutomator2-focused] 输入成功")
                    return True
            except Exception as e:
                print(f"[UIAutomator2-focused] 失败: {e}")

        # ========== 第三层：ADB 坐标方式（兜底） ==========
        if center_x and center_y:
            print("[ADB-坐标] 使用坐标输入方式")
            return self.input_text_by_coordinate(center_x, center_y, text)

        # 最后回退
        print("[ADB-回退] 使用基础 ADB 输入方式")
        return self.input_text(text, clear_first=True)

    def _build_u2_selector(self, widget_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        根据控件信息构建 UIAutomator2 选择器

        Args:
            widget_info: 控件信息字典

        Returns:
            UIAutomator2 选择器字典，如果无法构建则返回 None
        """
        if not widget_info:
            print("[UIAutomator2-选择器] widget_info 为空，无法构建选择器")
            return None

        selector = {}

        # 1. 优先添加 resource_id（不立即返回，允许组合其他条件）
        resource_id = widget_info.get("resource_id", "")
        if resource_id:
            # 提取 id 名称（兼容完整格式和截断格式）
            if ":id/" in resource_id:
                id_name = resource_id.split(":id/")[-1]
            elif "/" in resource_id:
                id_name = resource_id.split("/")[-1]
            else:
                id_name = resource_id

            # 使用 resourceIdMatches 支持正则匹配，兼容不同包名前缀
            # 例如：org.wikipedia:id/search_src_text 或 search_src_text 都能匹配
            selector["resourceIdMatches"] = f".*[:/]{id_name}$"
            print(f"[UIAutomator2-选择器] 使用 resourceIdMatches: .*[:/]{id_name}$")
            print(f"[UIAutomator2-选择器] 原始 resource_id: {resource_id}")

        # 2. 如果有 content_desc，添加为额外条件（复合选择器：resource_id AND content_desc）
        content_desc = widget_info.get("content_desc", "")
        if content_desc and content_desc.strip():
            selector["description"] = content_desc.strip()
            print(f"[UIAutomator2-选择器] 添加 description: {content_desc.strip()}")

        # 3. 如果已经有选择器条件，返回复合选择器
        if selector:
            if len(selector) > 1:
                print(f"[UIAutomator2-选择器] 使用复合选择器: {selector}")
            return selector

        # 4. 以下为兜底逻辑：单独使用 text
        text = widget_info.get("text", "")
        if text and text.strip():
            selector["text"] = text.strip()
            print(f"[UIAutomator2-选择器] 使用 text: {text.strip()}")
            return selector

        # 5. 兜底逻辑：class 和 clickable 组合
        class_name = widget_info.get("class", "")
        if class_name and "EditText" in class_name:
            selector["className"] = "android.widget.EditText"
            print(f"[UIAutomator2-选择器] 使用 className: android.widget.EditText")
            return selector

        # 6. 最后兜底：单独使用 description
        if content_desc:
            selector["description"] = content_desc
            print(f"[UIAutomator2-选择器] 使用 description: {content_desc}")
            return selector

        print(f"[UIAutomator2-选择器] 无法构建有效选择器，widget_info: {widget_info}")
        return None

    def clear_logcat(self) -> bool:
        """
        清空现有的系统日志缓冲区

        在每次测试开始前调用，确保后续的崩溃检测只会捕获当前测试期间产生的日志。

        Returns:
            True 表示清空成功，False 表示失败
        """
        try:
            # 执行 logcat -c 清空日志缓冲区
            result = self._execute_adb(["logcat", "-c"])

            if result.returncode == 0:
                print("[日志清空] logcat 缓冲区已清空")
                return True
            else:
                print(f"[日志清空失败] 错误信息: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print("[日志清空失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[日志清空失败] 异常: {e}")
            return False

    def check_for_crash(self, target_package: str = None) -> str:
        """
        检查系统日志中是否存在崩溃信息（工业级精准检测）

        执行 logcat -d 导出当前日志，检测是否包含真正的崩溃关键字：
        - FATAL EXCEPTION: 致命异常（Java 崩溃）
        - beginning of crash: Android 崩溃日志块的标准起始标志
        - CRASH: 原生崩溃标记
        - Force Close: 应用强制关闭
        - has died: 进程异常终止

        注意：不使用 "AndroidRuntime" 关键字，因为它在正常启动时也会出现。

        日志截取策略：一旦定位到崩溃关键字，只截取该位置前 5 行和后 100 行，
        避免写入大量无关日志。

        Args:
            target_package: 被测应用包名，用于过滤误报（如其他应用崩溃）

        Returns:
            崩溃日志字符串（精简后的核心堆栈信息），如果发现被测应用崩溃；
            如果没有检测到崩溃或崩溃来自其他应用，返回空字符串
        """
        try:
            # 执行 logcat -d 导出日志（非阻塞，只导出当前缓冲区内容）
            result = self._execute_adb(["logcat", "-d"], timeout=10)

            if result.returncode != 0:
                print(f"[崩溃检测] logcat 执行失败: {result.stderr}")
                return ""

            # 安全解码日志内容（处理可能的编码问题）
            log_content = result.stdout
            if not log_content:
                log_content = ""
                # 尝试从 stderr 获取
                if result.stderr:
                    log_content = result.stderr

            # 将日志分割成行列表，用于精准切片
            log_lines = log_content.split('\n')

            # 严格的崩溃关键字列表（工业级精准检测，避免误报）
            # 按优先级排序，最可靠的放在前面
            crash_keywords = [
                "FATAL EXCEPTION",      # Java 致命异常（最可靠）
                "beginning of crash",   # Android 崩溃日志块的标准起始标志
                "CRASH:",               # 原生崩溃标记（NDK）
                "Force Close",          # 应用强制关闭
                "has died",             # 进程异常终止
            ]

            # 查找崩溃关键字的位置
            crash_keyword_found = None
            crash_line_index = -1

            for i, line in enumerate(log_lines):
                for keyword in crash_keywords:
                    if keyword in line:
                        crash_keyword_found = keyword
                        crash_line_index = i
                        print(f"[崩溃检测] 匹配到关键字: '{keyword}'，位于第 {i+1} 行")
                        break
                if crash_keyword_found:
                    break

            # 如果找到崩溃关键字，执行精准切片
            if crash_keyword_found and crash_line_index >= 0:
                # 计算切片范围：前 5 行 + 后 100 行
                start_index = max(0, crash_line_index - 5)
                end_index = min(len(log_lines), crash_line_index + 101)  # +101 因为切片是左闭右开

                # 执行切片
                crash_slice = log_lines[start_index:end_index]
                crash_log = '\n'.join(crash_slice)

                # 如果指定了目标包名，验证崩溃是否来自被测应用
                if target_package:
                    if not self._is_target_app_crash(crash_log, target_package):
                        print(f"[崩溃检测] 崩溃非被测应用({target_package})，忽略")
                        return ""

                print(f"[崩溃检测] 发现真实崩溃！关键字: '{crash_keyword_found}'")
                print(f"[崩溃检测] 日志切片: 第 {start_index+1} 行到第 {end_index} 行，共 {len(crash_slice)} 行")
                print(f"[崩溃检测] 崩溃日志长度: {len(crash_log)} 字符（已精简）")

                return crash_log
            else:
                # 没有检测到崩溃
                return ""

        except subprocess.TimeoutExpired:
            print("[崩溃检测] logcat 命令执行超时")
            return ""
        except UnicodeDecodeError as e:
            # 处理编码错误，尝试安全解码
            print(f"[崩溃检测] 日志解码异常: {e}，尝试安全解码")
            try:
                # 重新执行，使用二进制模式读取
                if self.device_id:
                    cmd = ["adb", "-s", self.device_id, "logcat", "-d"]
                else:
                    cmd = ["adb", "logcat", "-d"]

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    encoding='utf-8',
                    errors='ignore',  # 显式指定编码，防止 GBK 崩溃
                    timeout=10
                )
                # 获取日志内容
                log_content = result.stdout if result.stdout else ""
                log_lines = log_content.split('\n')

                # 严格的崩溃关键字检测（带精准切片）
                crash_keywords = ["FATAL EXCEPTION", "beginning of crash", "CRASH:", "Force Close", "has died"]

                for i, line in enumerate(log_lines):
                    for keyword in crash_keywords:
                        if keyword in line:
                            print(f"[崩溃检测] 发现真实崩溃（安全解码模式），关键字: '{keyword}'")
                            # 精准切片：前 5 行 + 后 100 行
                            start_index = max(0, i - 5)
                            end_index = min(len(log_lines), i + 101)
                            crash_slice = log_lines[start_index:end_index]
                            crash_log = '\n'.join(crash_slice)

                            # 如果指定了目标包名，验证崩溃是否来自被测应用
                            if target_package:
                                if not self._is_target_app_crash(crash_log, target_package):
                                    print(f"[崩溃检测] 崩溃非被测应用({target_package})，忽略")
                                    return ""

                            return crash_log
                return ""
            except Exception:
                return ""
        except Exception as e:
            print(f"[崩溃检测] 异常: {e}")
            return ""

    def _is_target_app_crash(self, crash_log: str, target_package: str) -> bool:
        """
        判断崩溃日志是否来自被测应用

        检查策略：
        1. 检查日志中是否包含目标包名
        2. 检查 FATAL EXCEPTION 后的 Process 信息
        3. 检查 "pid.*包名" 格式

        Args:
            crash_log: 崩溃日志内容
            target_package: 被测应用包名

        Returns:
            True 如果崩溃来自被测应用，False 如果来自其他应用
        """
        if not crash_log or not target_package:
            return True  # 无目标包名时不过滤

        # 策略1：直接匹配包名
        if target_package in crash_log:
            return True

        # 策略2：匹配 Process 信息
        # 例如：FATAL EXCEPTION: main\nProcess: com.example.app, PID: 1234
        process_match = re.search(r'Process:\s*([^\s,]+)', crash_log)
        if process_match:
            process_name = process_match.group(1)
            if process_name == target_package:
                return True

        # 策略3：检查 "Kill" 相关日志（如 lowmemorykiller）
        # 格式：Kill 'package_name' (pid), uid xxx
        kill_match = re.search(r"Kill\s+['\"]([^'\"]+)['\"]", crash_log)
        if kill_match:
            killed_package = kill_match.group(1)
            if killed_package == target_package:
                return True
            else:
                # 明确是其他应用被杀，返回 False
                return False

        # 策略4：匹配包名前缀（部分日志可能只显示短名）
        package_short = target_package.split('.')[-1]
        if f".{package_short}" in crash_log or f"/.{package_short}" in crash_log:
            return True

        # 默认返回 False（严格模式：不确定时认为是其他应用）
        return False

    def launch_app(self, package_name: str, activity_name: Optional[str] = None) -> bool:
        """
        启动指定的应用

        Args:
            package_name: 应用包名，例如 "com.android.settings"
            activity_name: 可选的 Activity 名称，如果不指定则启动应用主 Activity

        Returns:
            True 表示启动成功，False 表示失败
        """
        try:
            if activity_name:
                # 启动指定的 Activity
                cmd = f"am start -n {package_name}/{activity_name}"
            else:
                # 使用 monkey 启动应用主 Activity
                cmd = f"monkey -p {package_name} -c android.intent.category.LAUNCHER 1"

            print(f"[应用启动] 正在启动: {package_name}")
            result = self._execute_shell(cmd, timeout=10)

            if result.returncode == 0:
                print(f"[应用启动成功] {package_name}")
                # 等待应用启动
                time.sleep(2)
                return True
            else:
                print(f"[应用启动失败] {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            print("[应用启动失败] 命令执行超时")
            return False
        except Exception as e:
            print(f"[应用启动失败] 异常: {e}")
            return False

    def launch_app_by_intent(self, action: str, data_uri: Optional[str] = None) -> bool:
        """
        通过 Intent 启动应用（支持搜索等特定功能）

        Args:
            action: Intent action，例如 "android.intent.action.SEARCH"
            data_uri: 可选的 Data URI

        Returns:
            True 表示启动成功，False 表示失败
        """
        try:
            cmd = f"am start -a {action}"
            if data_uri:
                cmd += f" -d {data_uri}"

            print(f"[Intent启动] action={action}")
            result = self._execute_shell(cmd, timeout=10)

            if result.returncode == 0:
                print(f"[Intent启动成功]")
                time.sleep(2)
                return True
            else:
                print(f"[Intent启动失败] {result.stderr}")
                return False

        except Exception as e:
            print(f"[Intent启动失败] 异常: {e}")
            return False

    def screenshot(self, save_path: Optional[str] = None) -> Optional[Path]:
        """
        截取当前屏幕并保存到本地

        执行流程：
        1. 优先使用 UIAutomator2 的 screenshot() 方法（如果可用）
        2. 否则使用 ADB screencap 命令

        Args:
            save_path: 本地保存路径，如果不指定则保存到 temp_data/screenshot_{timestamp}.png

        Returns:
            成功时返回本地文件的 Path 对象，失败时返回 None
        """
        from datetime import datetime

        # 确定保存路径
        if save_path:
            local_path = Path(save_path)
        else:
            # 默认保存到 temp_data 目录
            temp_dir = Path("temp_data")
            temp_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            local_path = temp_dir / f"screenshot_{timestamp}.png"

        # 优先尝试使用 UIAutomator2 的 screenshot()
        if UIAUTOMATOR2_AVAILABLE:
            try:
                print("[截图] 尝试使用 UIAutomator2 screenshot()...")
                device = self._get_u2_device()
                if device:
                    # 使用 UIAutomator2 截图
                    img = device.screenshot()
                    if img:
                        # 保存到本地
                        img.save(str(local_path))
                        print(f"[截图成功] 使用 UIAutomator2，文件已保存到: {local_path}")
                        return local_path
            except Exception as e:
                print(f"[UIAutomator2] screenshot 失败: {e}，尝试 ADB 方式...")

        # 回退到 ADB screencap 方式
        try:
            device_screenshot_path = "/sdcard/screenshot.png"

            # 步骤1: 在设备上执行截图
            print("[截图] 正在执行 screencap...")
            screencap_result = self._execute_shell(
                f"screencap -p {device_screenshot_path}",
                timeout=10
            )

            if screencap_result.returncode != 0:
                print(f"[截图失败] screencap 错误: {screencap_result.stderr}")
                return None

            # 步骤2: 等待截图生成
            time.sleep(0.5)

            # 步骤3: 拉取到本地
            print(f"[截图] 正在拉取文件到本地: {local_path}")
            pull_result = self._execute_adb(["pull", device_screenshot_path, str(local_path)])

            if pull_result.returncode == 0 and local_path.exists():
                print(f"[截图成功] 文件已保存到: {local_path}")
                return local_path
            else:
                print(f"[截图失败] 拉取文件失败: {pull_result.stderr}")
                return None

        except subprocess.TimeoutExpired:
            print("[截图失败] 命令执行超时")
            return None
        except Exception as e:
            print(f"[截图失败] 异常: {e}")
            return None

    def get_screen_resolution(self) -> Tuple[int, int]:
        """
        获取设备屏幕分辨率

        优先使用 UIAutomator2，回退到 ADB wm size 命令

        Returns:
            元组 (width, height)，失败返回 (1080, 1920) 作为默认值
        """
        # 优先尝试 UIAutomator2
        if UIAUTOMATOR2_AVAILABLE:
            try:
                device = self._get_u2_device()
                if device:
                    info = device.info
                    width = info.get('displayWidth', 0)
                    height = info.get('displayHeight', 0)
                    if width > 0 and height > 0:
                        print(f"[分辨率获取成功] UIAutomator2: {width}x{height}")
                        return (width, height)
            except Exception as e:
                print(f"[UIAutomator2] 获取分辨率失败: {e}，尝试 ADB 方式...")

        # 回退到 ADB wm size 命令
        try:
            result = self._execute_shell("wm size", timeout=5)

            if result.returncode == 0:
                output = result.stdout
                # 解析输出: "Physical size: 1080x1920" 或 "Override size: 1080x1920"
                match = re.search(r'(\d+)x(\d+)', output)
                if match:
                    width = int(match.group(1))
                    height = int(match.group(2))
                    print(f"[分辨率获取成功] ADB: {width}x{height}")
                    return (width, height)
        except Exception as e:
            print(f"[分辨率获取失败] 异常: {e}")

        # 返回默认值
        print("[分辨率获取失败] 使用默认值 1080x1920")
        return (1080, 1920)
