"""
探索缓存模块
用于记录已探索的 Activity-Widget 组合，避免重复测试
"""

from typing import Dict, Set, Tuple
from pathlib import Path
import json


class ExplorationCache:
    """
    探索缓存类

    记录已探索的 Activity-Widget 组合，避免在同一测试会话中重复测试相同的控件。
    """

    def __init__(self, cache_file: Path = None):
        """
        初始化探索缓存

        Args:
            cache_file: 缓存文件路径（可选）
        """
        self._cache: Dict[str, Set[str]] = {}  # activity -> set of widgets
        self._cache_file = cache_file or Path("temp_data/exploration_cache.json")
        self._total_explorations = 0

    def record_exploration(self, activity: str, widget: str) -> bool:
        """
        记录探索操作

        Args:
            activity: Activity 名称
            widget: Widget 名称

        Returns:
            True 如果是首次探索此组合，False 如果已探索过
        """
        if activity not in self._cache:
            self._cache[activity] = set()

        if widget in self._cache[activity]:
            # 已探索过
            return False

        # 新探索
        self._cache[activity].add(widget)
        self._total_explorations += 1
        return True

    def has_explored(self, activity: str, widget: str) -> bool:
        """
        检查是否已探索过某组合

        Args:
            activity: Activity 名称
            widget: Widget 名称

        Returns:
            True 如果已探索过，False 如果未探索过
        """
        return activity in self._cache and widget in self._cache[activity]

    def get_explored_widgets(self, activity: str) -> Set[str]:
        """
        获取某 Activity 已探索过的 Widget 集合

        Args:
            activity: Activity 名称

        Returns:
            已探索的 Widget 集合
        """
        return self._cache.get(activity, set())

    def get_total_explorations(self) -> int:
        """
        获取总探索次数

        Returns:
            总探索次数
        """
        return self._total_explorations

    def clear_cache(self) -> None:
        """
        清空缓存
        """
        self._cache.clear()
        self._total_explorations = 0
        print("[探索缓存] 已清空")

    def save_cache(self) -> None:
        """
        保存缓存到文件
        """
        try:
            # 转换 set 为 list 以便 JSON 序列化
            cache_data = {
                activity: list(widgets)
                for activity, widgets in self._cache.items()
            }
            cache_data["_total"] = self._total_explorations

            with open(self._cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)

            print(f"[探索缓存] 已保存到 {self._cache_file}")
        except Exception as e:
            print(f"[探索缓存] 保存失败: {e}")

    def load_cache(self) -> bool:
        """
        从文件加载缓存

        Returns:
            True 如果加载成功，False 如果失败
        """
        try:
            if not self._cache_file.exists():
                return False

            with open(self._cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)

            # 转换 list 回 set
            self._cache = {
                activity: set(widgets)
                for activity, widgets in cache_data.items()
                if activity != "_total"
            }
            self._total_explorations = cache_data.get("_total", 0)

            print(f"[探索缓存] 已加载，共 {self._total_explorations} 条记录")
            return True
        except Exception as e:
            print(f"[探索缓存] 加载失败: {e}")
            return False

    def get_statistics(self) -> Dict:
        """
        获取缓存统计信息

        Returns:
            统计信息字典
        """
        return {
            "total_activities": len(self._cache),
            "total_explorations": self._total_explorations,
            "activities_detail": {
                activity: len(widgets)
                for activity, widgets in self._cache.items()
            }
        }


# 测试入口
if __name__ == "__main__":
    print("=" * 60)
    print("ExplorationCache 测试")
    print("=" * 60)

    cache = ExplorationCache()

    # 测试记录探索
    print("\n[测试] 记录探索:")
    print(f"  MainActivity + Button1: {cache.record_exploration('MainActivity', 'Button1')}")
    print(f"  MainActivity + Button2: {cache.record_exploration('MainActivity', 'Button2')}")
    print(f"  MainActivity + Button1 (重复): {cache.record_exploration('MainActivity', 'Button1')}")

    # 测试查询
    print("\n[测试] 查询探索状态:")
    print(f"  MainActivity + Button1 已探索: {cache.has_explored('MainActivity', 'Button1')}")
    print(f"  MainActivity + Button3 已探索: {cache.has_explored('MainActivity', 'Button3')}")

    # 测试统计
    print("\n[测试] 统计信息:")
    print(cache.get_statistics())