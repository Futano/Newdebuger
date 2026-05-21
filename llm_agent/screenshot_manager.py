"""
Screenshot Manager Module
Manages screenshot capture, storage, and encoding for multimodal LLM analysis
"""

import base64
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from env_interactor.adb_utils import ADBController


@dataclass
class ScreenshotData:
    """
    Screenshot data container with metadata

    Attributes:
        path: Local file path of the screenshot
        timestamp: When the screenshot was captured
        activity_name: Current activity when screenshot was taken
        base64_data: Base64 encoded image data (lazy loaded)
        width: Image width in pixels
        height: Image height in pixels
    """
    path: Path
    timestamp: datetime = field(default_factory=datetime.now)
    activity_name: str = ""
    base64_data: Optional[str] = None
    width: int = 0
    height: int = 0

    def get_base64(self) -> Optional[str]:
        """
        Get base64 encoded image data (lazy loading)

        Returns:
            Base64 encoded string of the image, or None if encoding fails
        """
        if self.base64_data is not None:
            return self.base64_data

        if not self.path.exists():
            print(f"[ScreenshotData] 文件不存在: {self.path}")
            return None

        try:
            with open(self.path, "rb") as f:
                image_data = f.read()
            self.base64_data = base64.b64encode(image_data).decode('utf-8')
            return self.base64_data
        except Exception as e:
            print(f"[ScreenshotData] Base64 编码失败: {e}")
            return None

    def get_data_uri(self) -> Optional[str]:
        """
        Get data URI format for multimodal API

        Returns:
            Data URI string (data:image/png;base64,...), or None if encoding fails
        """
        b64_data = self.get_base64()
        if b64_data:
            return f"data:image/png;base64,{b64_data}"
        return None


class ScreenshotManager:
    """
    Screenshot Manager

    Handles screenshot capture, local storage, and encoding for multimodal LLM analysis.
    Maintains a history of recent screenshots with automatic cleanup.
    """

    def __init__(
        self,
        adb_controller: Optional["ADBController"] = None,
        save_dir: str = "temp_data/screenshots",
        max_history: int = 20,
        auto_cleanup: bool = True
    ):
        """
        Initialize ScreenshotManager

        Args:
            adb_controller: ADBController instance for device interaction
            save_dir: Directory to save screenshots
            max_history: Maximum number of screenshots to keep in history
            auto_cleanup: Whether to automatically cleanup old screenshots
        """
        self.adb_controller = adb_controller
        self.save_dir = Path(save_dir)
        self.max_history = max_history
        self.auto_cleanup = auto_cleanup

        # Screenshot history
        self._history: List[ScreenshotData] = []

        # Ensure save directory exists
        self.save_dir.mkdir(parents=True, exist_ok=True)
        print(f"[ScreenshotManager] 初始化完成，保存目录: {self.save_dir}")

    def set_adb_controller(self, adb_controller: "ADBController") -> None:
        """
        Set the ADB controller instance

        Args:
            adb_controller: ADBController instance
        """
        self.adb_controller = adb_controller

    def capture(
        self,
        activity_name: str = "",
        filename: Optional[str] = None
    ) -> Optional[ScreenshotData]:
        """
        Capture a screenshot from the device

        Args:
            activity_name: Current activity name for metadata
            filename: Optional custom filename (without extension)

        Returns:
            ScreenshotData object if successful, None otherwise
        """
        if not self.adb_controller:
            print("[ScreenshotManager] 错误: ADBController 未设置")
            return None

        try:
            # Generate filename if not provided
            if filename:
                save_path = self.save_dir / f"{filename}.png"
            else:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                save_path = self.save_dir / f"screenshot_{timestamp}.png"

            # Capture screenshot
            result_path = self.adb_controller.screenshot(str(save_path))

            if result_path and result_path.exists():
                # Get screen resolution
                width, height = self.adb_controller.get_screen_resolution()

                # Create ScreenshotData object
                screenshot_data = ScreenshotData(
                    path=result_path,
                    timestamp=datetime.now(),
                    activity_name=activity_name,
                    width=width,
                    height=height
                )

                # Add to history
                self._history.append(screenshot_data)

                # Cleanup if needed
                if self.auto_cleanup and len(self._history) > self.max_history:
                    self._cleanup_old_screenshots()

                print(f"[ScreenshotManager] 截图成功: {result_path}")
                return screenshot_data
            else:
                print("[ScreenshotManager] 截图失败")
                return None

        except Exception as e:
            print(f"[ScreenshotManager] 截图异常: {e}")
            return None

    def get_latest(self) -> Optional[ScreenshotData]:
        """
        Get the most recent screenshot

        Returns:
            ScreenshotData object of the latest screenshot, or None if history is empty
        """
        if self._history:
            return self._history[-1]
        return None

    def get_history(self, limit: int = 5) -> List[ScreenshotData]:
        """
        Get recent screenshot history

        Args:
            limit: Maximum number of screenshots to return

        Returns:
            List of ScreenshotData objects (most recent first)
        """
        if limit <= 0:
            return []

        # Return most recent screenshots first
        return list(reversed(self._history[-limit:]))

    def get_by_activity(self, activity_name: str) -> List[ScreenshotData]:
        """
        Get screenshots for a specific activity

        Args:
            activity_name: Activity name to filter by

        Returns:
            List of ScreenshotData objects matching the activity
        """
        return [
            s for s in self._history
            if s.activity_name == activity_name
        ]

    def cleanup_old_screenshots(self) -> int:
        """
        Manually cleanup old screenshots beyond max_history

        Returns:
            Number of screenshots removed
        """
        return self._cleanup_old_screenshots()

    def _cleanup_old_screenshots(self) -> int:
        """
        Internal method to cleanup old screenshots

        Removes both from history and from disk.

        Returns:
            Number of screenshots removed
        """
        if len(self._history) <= self.max_history:
            return 0

        # Calculate how many to remove
        to_remove = len(self._history) - self.max_history
        removed_count = 0

        # Remove oldest screenshots
        for i in range(to_remove):
            old_screenshot = self._history[i]

            # Delete from disk
            try:
                if old_screenshot.path.exists():
                    old_screenshot.path.unlink()
                    print(f"[ScreenshotManager] 已删除旧截图: {old_screenshot.path}")
            except Exception as e:
                print(f"[ScreenshotManager] 删除截图失败: {e}")

            removed_count += 1

        # Update history
        self._history = self._history[to_remove:]

        return removed_count

    def clear_all(self) -> int:
        """
        Clear all screenshots from history and disk

        Returns:
            Number of screenshots cleared
        """
        count = len(self._history)

        for screenshot in self._history:
            try:
                if screenshot.path.exists():
                    screenshot.path.unlink()
            except Exception:
                pass

        self._history.clear()
        print(f"[ScreenshotManager] 已清除所有截图: {count} 个")
        return count

    def get_stats(self) -> dict:
        """
        Get statistics about the screenshot manager

        Returns:
            Dictionary with statistics
        """
        total_size = 0
        for screenshot in self._history:
            try:
                if screenshot.path.exists():
                    total_size += screenshot.path.stat().st_size
            except Exception:
                pass

        return {
            "total_count": len(self._history),
            "max_history": self.max_history,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "save_dir": str(self.save_dir)
        }


# Module-level convenience functions
_screenshot_manager: Optional[ScreenshotManager] = None


def get_screenshot_manager() -> ScreenshotManager:
    """
    Get the global ScreenshotManager instance

    Returns:
        ScreenshotManager instance (creates one if not exists)
    """
    global _screenshot_manager
    if _screenshot_manager is None:
        _screenshot_manager = ScreenshotManager()
    return _screenshot_manager


def init_screenshot_manager(
    adb_controller: Optional["ADBController"] = None,
    save_dir: str = "temp_data/screenshots",
    max_history: int = 20
) -> ScreenshotManager:
    """
    Initialize the global ScreenshotManager instance

    Args:
        adb_controller: ADBController instance
        save_dir: Directory to save screenshots
        max_history: Maximum number of screenshots to keep

    Returns:
        Initialized ScreenshotManager instance
    """
    global _screenshot_manager
    _screenshot_manager = ScreenshotManager(
        adb_controller=adb_controller,
        save_dir=save_dir,
        max_history=max_history
    )
    return _screenshot_manager


# Test entry point
if __name__ == "__main__":
    print("=" * 60)
    print("ScreenshotManager 测试")
    print("=" * 60)

    # Create manager without ADB controller (for testing)
    manager = ScreenshotManager(adb_controller=None, max_history=5)

    # Print stats
    stats = manager.get_stats()
    print(f"\n统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\n[提示] 需要 ADBController 连接设备才能进行实际截图测试")