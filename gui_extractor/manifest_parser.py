"""
Android Manifest 解析模块
从已安装的 APP 中提取 AndroidManifest 信息，包括 Activity 列表
支持持久化存储到本地文件
"""

import json
import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List


@dataclass
class ActivityInfo:
    """
    Activity 信息数据结构
    """
    name: str                      # 简短名称，如 "MainActivity"
    full_name: str                 # 完整类名，如 "com.example.app.MainActivity"
    exported: bool = False         # 是否可被外部调用
    is_main: bool = False          # 是否是 LAUNCHER Activity（主入口）

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ActivityInfo":
        return cls(**data)


@dataclass
class AppInfo:
    """
    APP 元信息数据结构
    """
    # 基本信息
    package_name: str              # 包名，如 "com.example.app"
    app_name: str = ""             # 应用名称（可能为空）
    version_name: str = ""         # 版本名，如 "1.0.0"
    version_code: int = 0          # 版本号

    # Activity 信息
    activities: List[ActivityInfo] = field(default_factory=list)
    main_activity: str = ""        # 主入口 Activity 名称

    def to_dict(self) -> dict:
        """转换为字典，用于 JSON 序列化"""
        return {
            "package_name": self.package_name,
            "app_name": self.app_name,
            "version_name": self.version_name,
            "version_code": self.version_code,
            "activities": [a.to_dict() for a in self.activities],
            "main_activity": self.main_activity
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AppInfo":
        """从字典创建实例，用于 JSON 反序列化"""
        activities = [ActivityInfo.from_dict(a) for a in data.get("activities", [])]
        return cls(
            package_name=data.get("package_name", ""),
            app_name=data.get("app_name", ""),
            version_name=data.get("version_name", ""),
            version_code=data.get("version_code", 0),
            activities=activities,
            main_activity=data.get("main_activity", "")
        )

    def get_activity_names(self) -> List[str]:
        """获取所有 Activity 简短名称列表"""
        return [a.name for a in self.activities]

    def get_unvisited_activities(self, visited: List[str]) -> List[str]:
        """获取未访问的 Activity 列表"""
        all_names = set(self.get_activity_names())
        visited_set = set(visited)
        return list(all_names - visited_set)


class ManifestParser:
    """
    Android Manifest 解析器

    从已安装的 Android APP 中提取 Manifest 信息
    使用 adb shell dumpsys package 命令获取数据
    """

    # 数据存储根目录
    DATA_DIR = Path("app_data")

    def __init__(self, device_id: Optional[str] = None):
        """
        初始化解析器

        Args:
            device_id: 设备 ID，多设备时需要指定
        """
        self.device_id = device_id

    def _build_adb_command(self, cmd: str) -> List[str]:
        """构建 ADB shell 命令"""
        if self.device_id:
            return ["adb", "-s", self.device_id, "shell", cmd]
        return ["adb", "shell", cmd]

    def _execute_shell(self, cmd: str, timeout: int = 30) -> str:
        """
        执行 ADB shell 命令并返回输出

        Args:
            cmd: shell 命令
            timeout: 超时时间

        Returns:
            命令输出字符串
        """
        full_cmd = self._build_adb_command(cmd)
        try:
            result = subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='ignore',
                timeout=timeout
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            print(f"[Manifest解析] 命令超时: {cmd}")
            return ""
        except Exception as e:
            print(f"[Manifest解析] 命令执行异常: {e}")
            return ""

    def parse_from_device(self, package_name: str) -> Optional[AppInfo]:
        """
        从设备上解析指定 APP 的 Manifest 信息

        Args:
            package_name: APP 包名

        Returns:
            AppInfo 对象，解析失败返回 None
        """
        print(f"[Manifest解析] 正在解析: {package_name}")

        # 获取 dumpsys package 输出
        dump_output = self._execute_shell(f"dumpsys package {package_name}", timeout=60)

        if not dump_output:
            print(f"[Manifest解析] 无法获取 package 信息: {package_name}")
            return None

        # 解析基本信息
        app_info = AppInfo(package_name=package_name)
        app_info.app_name = self._extract_app_name(dump_output, package_name)
        app_info.version_name = self._extract_version_name(dump_output)
        app_info.version_code = self._extract_version_code(dump_output)

        # 解析 Activity 列表
        activities = self._extract_activities(dump_output, package_name)
        app_info.activities = activities

        # 找出主 Activity
        for activity in activities:
            if activity.is_main:
                app_info.main_activity = activity.name
                break

        # 如果没有找到主 Activity，取第一个
        if not app_info.main_activity and activities:
            app_info.main_activity = activities[0].name

        print(f"[Manifest解析] 成功! 找到 {len(activities)} 个 Activity")
        print(f"[Manifest解析] 主入口: {app_info.main_activity}")

        return app_info

    def _extract_app_name(self, dump_output: str, package_name: str) -> str:
        """
        从 dumpsys 输出中提取应用名称

        尝试多种方式获取应用名称：
        1. 从 resources 中获取 label
        2. 从 ApplicationInfo 中获取
        3. 使用包名作为默认值
        """
        # 方法1: 匹配 labelRes 或 nonLocalizedLabel
        # 格式: labelRes=0x7f0b0012 或 nonLocalizedLabel="App Name"
        label_pattern = r'nonLocalizedLabel="?([^"\n]+)"?'
        match = re.search(label_pattern, dump_output)
        if match:
            app_name = match.group(1).strip()
            if app_name and app_name != "null":
                return app_name

        # 方法2: 从 ApplicationInfo 中获取 name
        # 格式: ApplicationInfo{xxx com.example.app}
        app_info_pattern = r'ApplicationInfo\{[^\}]*\}'
        match = re.search(app_info_pattern, dump_output)
        if match:
            # 尝试从字符串资源获取
            str_res_pattern = r'string/([^,\s]+)'
            str_match = re.search(str_res_pattern, match.group(0))
            if str_match:
                # 常见的应用名称资源ID
                return str_match.group(1).replace('_', ' ').title()

        # 方法3: 使用包名最后一段作为应用名称
        parts = package_name.split('.')
        if len(parts) > 2:
            return parts[-1].title()

        return package_name

    def _extract_version_name(self, dump_output: str) -> str:
        """从 dumpsys 输出中提取版本名"""
        # 匹配: versionName=1.0.0
        pattern = r'versionName=([^\s]+)'
        match = re.search(pattern, dump_output)
        if match:
            return match.group(1)
        return ""

    def _extract_version_code(self, dump_output: str) -> int:
        """从 dumpsys 输出中提取版本号"""
        # 匹配: versionCode=123 minSdk=...
        pattern = r'versionCode=(\d+)'
        match = re.search(pattern, dump_output)
        if match:
            return int(match.group(1))
        return 0

    def _extract_activities(self, dump_output: str, package_name: str) -> List[ActivityInfo]:
        """
        从 dumpsys 输出中提取 Activity 列表

        dumpsys package 输出格式示例:
        Activity Resolver Table:
            Non-Data Actions:
                android.intent.action.MAIN:
                    xxx.xxx.MainActivity:
                        ...

        或者:
        Activity: ActivityInfo{xxx com.example.app/.MainActivity}
        """
        activities = []
        seen_names = set()  # 避免重复

        # 方法1：从 Activity Resolver Table 解析（获取 LAUNCHER Activity）
        # 格式: 包名/.ActivityName 或 包名/完整类名
        launcher_pattern = rf'{re.escape(package_name)}/\.?([A-Za-z_][A-Za-z0-9_]*)'
        for match in re.finditer(launcher_pattern, dump_output):
            activity_name = match.group(1)
            if activity_name not in seen_names:
                seen_names.add(activity_name)
                full_name = f"{package_name}.{activity_name}"
                # 检查是否在 MAIN/LAUNCHER 区域
                is_main = self._is_launcher_activity(dump_output, package_name, activity_name)
                activities.append(ActivityInfo(
                    name=activity_name,
                    full_name=full_name,
                    exported=True,  # LAUNCHER Activity 默认 exported
                    is_main=is_main
                ))

        # 方法2：从 Activity: 行解析
        # 格式: Activity: ActivityInfo{xxx com.example.app/.MainActivity}
        activity_line_pattern = r'Activity:\s*ActivityInfo\{[^}]*\s+' + re.escape(package_name) + r'/\.?([A-Za-z_][A-Za-z0-9_]*)'
        for match in re.finditer(activity_line_pattern, dump_output):
            activity_name = match.group(1)
            if activity_name not in seen_names:
                seen_names.add(activity_name)
                full_name = f"{package_name}.{activity_name}"
                activities.append(ActivityInfo(
                    name=activity_name,
                    full_name=full_name,
                    exported=False,  # 非 LAUNCHER 默认非 exported
                    is_main=False
                ))

        # 方法3：从 android.intent.action.MAIN 区域解析
        main_section = self._extract_main_section(dump_output)
        if main_section:
            for match in re.finditer(launcher_pattern, main_section):
                activity_name = match.group(1)
                # 更新为 is_main=True
                for act in activities:
                    if act.name == activity_name:
                        act.is_main = True
                        act.exported = True
                        break

        return activities

    def _is_launcher_activity(self, dump_output: str, package_name: str, activity_name: str) -> bool:
        """检查是否是 LAUNCHER Activity"""
        # 查找 MAIN/LAUNCHER 区域
        launcher_pattern = r'android\.intent\.category\.LAUNCHER[^}]*' + re.escape(package_name) + r'/\.?' + re.escape(activity_name)
        return bool(re.search(launcher_pattern, dump_output, re.DOTALL))

    def _extract_main_section(self, dump_output: str) -> str:
        """提取 android.intent.action.MAIN 区域内容"""
        # 查找 MAIN action 区域
        pattern = r'android\.intent\.action\.MAIN:.*?(?=\n\s{0,8}[A-Za-z]|\n\s{0,8}$)'
        match = re.search(pattern, dump_output, re.DOTALL)
        if match:
            return match.group(0)
        return ""

    def save_to_file(self, app_info: AppInfo) -> Path:
        """
        将 APP 信息保存到本地文件

        保存路径: app_data/<package_name>/manifest.json

        Args:
            app_info: APP 信息对象

        Returns:
            保存的文件路径
        """
        # 构建保存路径
        save_dir = self.DATA_DIR / app_info.package_name
        save_dir.mkdir(parents=True, exist_ok=True)

        save_path = save_dir / "manifest.json"

        # 写入 JSON 文件
        with open(save_path, 'w', encoding='utf-8') as f:
            json.dump(app_info.to_dict(), f, ensure_ascii=False, indent=2)

        print(f"[Manifest保存] 已保存到: {save_path}")
        return save_path

    def load_from_file(self, package_name: str) -> Optional[AppInfo]:
        """
        从本地文件加载 APP 信息

        Args:
            package_name: 包名

        Returns:
            AppInfo 对象，文件不存在返回 None
        """
        load_path = self.DATA_DIR / package_name / "manifest.json"

        if not load_path.exists():
            print(f"[Manifest加载] 文件不存在: {load_path}")
            return None

        try:
            with open(load_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            app_info = AppInfo.from_dict(data)
            print(f"[Manifest加载] 成功加载: {package_name}")
            return app_info

        except Exception as e:
            print(f"[Manifest加载] 加载失败: {e}")
            return None

    def get_or_parse(self, package_name: str, force_refresh: bool = False) -> Optional[AppInfo]:
        """
        获取 APP 信息（优先从缓存加载，否则从设备解析）

        Args:
            package_name: 包名
            force_refresh: 是否强制从设备重新解析

        Returns:
            AppInfo 对象
        """
        # 尝试从缓存加载
        if not force_refresh:
            cached = self.load_from_file(package_name)
            if cached:
                print(f"[Manifest] 使用缓存数据: {package_name}")
                return cached

        # 从设备解析
        app_info = self.parse_from_device(package_name)
        if app_info:
            # 保存到缓存
            self.save_to_file(app_info)

        return app_info


# 测试入口
if __name__ == "__main__":
    parser = ManifestParser()

    # 测试：解析设置应用
    test_package = "com.android.settings"

    print("=" * 60)
    print(f"测试解析: {test_package}")
    print("=" * 60)

    app_info = parser.get_or_parse(test_package, force_refresh=True)

    if app_info:
        print(f"\n包名: {app_info.package_name}")
        print(f"版本: {app_info.version_name} ({app_info.version_code})")
        print(f"主 Activity: {app_info.main_activity}")
        print(f"\nActivity 列表 ({len(app_info.activities)} 个):")
        for act in app_info.activities:
            flags = []
            if act.is_main:
                flags.append("MAIN")
            if act.exported:
                flags.append("EXPORTED")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            print(f"  - {act.name}{flag_str}")
    else:
        print("解析失败")