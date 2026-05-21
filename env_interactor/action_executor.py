"""
鍔ㄤ綔鎵ц鍣ㄦā鍧?
瑙ｆ瀽 LLM 鍝嶅簲骞舵墽琛岀浉搴旂殑 GUI 鎿嶄綔
闆嗘垚宕╂簝妫€娴嬫満鍒讹紝瀹炵幇 GPTDroid 璁烘枃鐨?Bug Oracle 鍔熻兘
鏀寔澶氭ā鎬?Bug 鍒嗘瀽寮曟搸锛堝穿婧?+ 閫昏緫閿欒锛?

鏀寔 ReAct JSON 鏍煎紡瑙ｆ瀽锛屾彁楂?LLM 鍐崇瓥鏅哄晢
"""

import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

# 瀵煎叆 ADB 鎺у埗鍣?
from env_interactor.adb_utils import ADBController

# 绫诲瀷妫€鏌ユ椂瀵煎叆锛岄伩鍏嶅惊鐜緷璧?
if TYPE_CHECKING:
    from llm_agent.memory_manager import TestingSequenceMemorizer
    from llm_agent.bug_analysis_engine import BugAnalysisEngine, BugReport
    from llm_agent.screenshot_manager import ScreenshotManager


# Bug 鎶ュ憡淇濆瓨鐩綍
BUG_REPORTS_DIR = Path("bug_reports")


# 瑙ｆ瀽缁撴灉鏁版嵁绫?
class ParsedAction:
    """
    瑙ｆ瀽鍚庣殑鍔ㄤ綔鏁版嵁缁撴瀯

    鏀寔 ReAct JSON 鏍煎紡锛屽寘鍚帹鐞嗗拰鍔ㄤ綔淇℃伅
    鏀寔鍔熻兘鏌ヨ鍝嶅簲瑙ｆ瀽锛團unctionName + Status锛?
    鏀寔澶氳緭鍏ユ搷浣滐紙澶氫釜 Widget/Input 瀵癸級
    鏀寔杈撳叆鍚庢搷浣滐紙OperationWidget锛?
    鏀寔棰勬湡缁撴灉鍜?Bug 妫€娴?

    JSON 鏍煎紡绀轰緥:
    - 闈炶緭鍏ユ搷浣?
    - 杈撳叆鎿嶄綔:
    - Bug 妫€娴?
    """
    def __init__(
        self,
        operation: Optional[str] = None,
        widget: Optional[str] = None,
        input_text: Optional[str] = None,
        thought: Optional[str] = None,
        page_description: Optional[str] = None,  # NEW: 椤甸潰鎻忚堪
        status: Optional[str] = None,
        function_name: Optional[str] = None,
        function_status: Optional[str] = None,
        input_sequence: Optional[List[Tuple[str, str, Optional[str]]]] = None,  # 涓夊厓缁勶細(widget, input_text, content_desc)
        operation_widget: Optional[str] = None,
        external_redirect: bool = False,
        redirect_package: Optional[str] = None,
        bug_detected: bool = False,
        bug_description: Optional[Dict] = None,
        widget_type: Optional[str] = None,
        operation_widget_type: Optional[str] = None,
        widget_content_desc: Optional[str] = None,  # 鏂板锛氱敤浜庡尯鍒嗗悓 resource-id 鐨勫瓧娈?
        target_x: Optional[int] = None,  # NEW: Target center X coordinate for visual positioning
        target_y: Optional[int] = None,  # NEW: Target center Y coordinate for visual positioning
        behavior_narrative: Optional[Dict] = None,
        step_narrative: Optional[Dict] = None,
        case_story_update: Optional[Dict] = None,
        function_phase: Optional[str] = None,
        function_end: bool = False,
        verification_target: Optional[str] = None
    ):
        self.operation = operation
        self.widget = widget
        self.input_text = input_text
        self.thought = thought  # ReAct: 鎺ㄧ悊杩囩▼
        self.page_description = page_description  # NEW: 椤甸潰鎻忚堪锛堟潵鑷?LLM 鐨?Page_Description 瀛楁锛?
        self.status = status    # ReAct: 鐘舵€佷俊鎭?
        self.function_name = function_name  # Function Query: 鍔熻兘鍚嶇О
        self.function_status = function_status  # Function Query: 鍔熻兘鐘舵€?(tested/testing)
        self.input_sequence = input_sequence  # 澶氳緭鍏ュ簭鍒? [(widget, input_text, content_desc), ...]
        self.operation_widget = operation_widget  # 杈撳叆鍚庣殑鎿嶄綔鐩爣鎺т欢锛堝 Submit 鎸夐挳锛?
        self.external_redirect = external_redirect  # 鏄惁瑙﹀彂浜嗗閮ㄥ簲鐢ㄨ烦杞?
        self.redirect_package = redirect_package  # 璺宠浆鍒扮殑澶栭儴搴旂敤鍖呭悕
        self.bug_detected = bug_detected  # 鏄惁妫€娴嬪埌 Bug
        self.bug_description = bug_description  # Bug 鎻忚堪 {"type": "...", "severity": "...", "description": "..."}
        self.widget_type = widget_type  # 鎺т欢绫诲瀷 (TextView, EditText, Button, etc.)
        self.operation_widget_type = operation_widget_type  # 鎿嶄綔鐩爣鎺т欢绫诲瀷
        self.widget_content_desc = widget_content_desc  # 鐢ㄤ簬鍖哄垎鍚?resource-id 鐨勫瓧娈碉紙濡?Front/Back锛?
        self.target_x = target_x  # NEW: 鐩爣鎺т欢涓績 X 鍧愭爣锛堢敤浜庤瑙夊畾浣嶏級
        self.target_y = target_y  # NEW: 鐩爣鎺т欢涓績 Y 鍧愭爣锛堢敤浜庤瑙夊畾浣嶏級
        self.behavior_narrative = behavior_narrative or {}
        self.step_narrative = step_narrative or {}
        self.case_story_update = case_story_update or {}
        self.function_phase = function_phase
        self.function_end = bool(function_end)
        self.verification_target = verification_target
        self.harness_events = []

    def is_valid(self) -> bool:
        """妫€鏌ユ槸鍚︿负鏈夋晥鐨勫姩浣?"""
        # 蹇呴』鏈夋搷浣滅被鍨?
        if not self.operation:
            return False

        # 绯荤粺绾у姩浣滐紙back, scroll_down, scroll_up锛変笉闇€瑕?widget
        system_actions = {"back", "scroll_down", "scroll_up"}
        if self.operation in system_actions:
            return True

        # 鏅€氭粴鍔ㄦ搷浣滀篃涓嶉渶瑕?widget
        if self.operation == "scroll":
            return True

        # click 绫绘搷浣滐細濡傛灉鎻愪緵浜嗚瑙夊畾浣嶅潗鏍?(TargetX, TargetY)锛屽垯涓嶉渶瑕?widget
        if self.target_x is not None and self.target_y is not None:
            return True

        # 鍏朵粬 click 绫绘搷浣滃繀椤绘湁 widget
        if not self.widget:
            return False

        return True

    def __repr__(self) -> str:
        parts = [f"operation='{self.operation}'"]
        if self.widget:
            parts.append(f"widget='{self.widget}'")
        if self.widget_type:
            parts.append(f"widget_type='{self.widget_type}'")
        if self.widget_content_desc:
            parts.append(f"content_desc='{self.widget_content_desc}'")
        if self.target_x and self.target_y:
            parts.append(f"target=({self.target_x},{self.target_y})")
        if self.input_text:
            parts.append(f"input='{self.input_text[:30]}...'" if len(self.input_text) > 30 else f"input='{self.input_text}'")
        if self.operation_widget:
            parts.append(f"op_widget='{self.operation_widget}'")
        if self.operation_widget_type:
            parts.append(f"op_widget_type='{self.operation_widget_type}'")
        if self.input_sequence:
            parts.append(f"inputs={len(self.input_sequence)}")
        if self.thought:
            parts.append(f"thought='{self.thought[:50]}...'" if len(self.thought or '') > 50 else f"thought='{self.thought}'")
        if self.function_name:
            parts.append(f"function='{self.function_name}'")
            if self.function_status:
                parts.append(f"status='{self.function_status}'")
        if self.step_narrative:
            parts.append("step_narrative=True")
        if self.case_story_update:
            parts.append("case_story_update=True")
        if self.function_phase:
            parts.append(f"phase='{self.function_phase}'")
        if self.function_end:
            parts.append("function_end=True")
        if self.verification_target:
            parts.append(f"verify='{self.verification_target[:30]}...'" if len(self.verification_target) > 30 else f"verify='{self.verification_target}'")
        if self.bug_detected:
            parts.append(f"BUG_DETECTED=True")
        return f"ParsedAction({', '.join(parts)})"

    def has_function_info(self) -> bool:
        """Check if parsed action contains function information"""
        return self.function_name is not None and self.function_status is not None

    def has_multiple_inputs(self) -> bool:
        """Check if parsed action has multiple input operations"""
        return self.input_sequence is not None and len(self.input_sequence) > 0

    def has_input_with_operation(self) -> bool:
        """Check if this is an input operation followed by another operation (e.g., click submit)"""
        operation = (self.operation or "").lower()
        return (
            self.input_text is not None
            and self.operation_widget is not None
            and operation not in {"input", "type"}
        )


class ActionExecutor:
    """
    鍔ㄤ綔鎵ц鍣ㄧ被
    瑙ｆ瀽 LLM 鐨勫喅绛栧搷搴旓紝鎵惧埌鐩爣鎺т欢骞舵墽琛岀浉搴旂殑鎿嶄綔
    闆嗘垚宕╂簝妫€娴嬫満鍒讹紙Bug Oracle锛?

    鏀寔鍏ㄥ眬绯荤粺绾у姩浣滐紙System-level Navigation锛夛細
    - back: 杩斿洖閿?
    - scroll_down: 鍚戜笅婊氬姩灞忓箷
    - scroll_up: 鍚戜笂婊氬姩灞忓箷
    """

    # 鏀寔鐨勬搷浣滅被鍨?
    VALID_OPERATIONS = {
        # 鎺т欢鎿嶄綔
        "click", "double-click", "double click",
        "long press", "longpress", "scroll",
        "input", "type",
        # 鍏ㄥ眬绯荤粺绾у姩浣滐紙鏃犻渶鎸囧畾 Widget锛?
        "back", "scroll_down", "scroll_up",
    }

    # 绯荤粺绾у姩浣滃垪琛紙涓嶉渶瑕?Widget锛?
    SYSTEM_LEVEL_ACTIONS = {"back", "scroll_down", "scroll_up"}

    def __init__(
        self,
        bug_analysis_engine: Optional["BugAnalysisEngine"] = None,
        screenshot_manager: Optional["ScreenshotManager"] = None,
        auto_hide_keyboard_after_input: bool = True
    ):
        """
        鍒濆鍖栧姩浣滄墽琛屽櫒

        Args:
            bug_analysis_engine: Bug 鍒嗘瀽寮曟搸锛堝彲閫夛紝鐢ㄤ簬澧炲己 Bug 妫€娴嬶級
            screenshot_manager: 鎴浘绠＄悊鍣紙鍙€夛紝鐢ㄤ簬 Bug 鎶ュ憡锛?
        """
        # Bug 鍒嗘瀽寮曟搸锛堝妯℃€佸寮猴級
        self.bug_analysis_engine = bug_analysis_engine
        self.screenshot_manager = screenshot_manager
        self.auto_hide_keyboard_after_input = auto_hide_keyboard_after_input

        # 鏈€鍚庝竴娆″穿婧冩娴嬬粨鏋滐紙渚涘閮ㄦ煡璇級
        self.last_crash_detected: bool = False
        self.last_crash_log: str = ""

        # 鏈€鍚庝竴娆?Bug 鎶ュ憡锛堟潵鑷?BugAnalysisEngine锛?
        self.last_bug_report: Optional["BugReport"] = None

    def _dismiss_keyboard_after_input(
        self,
        adb_controller: ADBController,
        action: ParsedAction,
        reason: str,
    ) -> None:
        """Optionally dismiss the keyboard and record it as test-harness evidence."""
        if not self.auto_hide_keyboard_after_input:
            action.harness_events.append({
                "type": "keyboard_dismissal",
                "source": "test_harness",
                "reason": reason,
                "performed": False,
                "note": "auto_hide_keyboard_after_input is disabled",
            })
            return

        before = adb_controller.get_input_focus_state()
        dismissed = adb_controller.hide_keyboard()
        after = adb_controller.get_input_focus_state()
        action.harness_events.append({
            "type": "keyboard_dismissal",
            "source": "test_harness",
            "reason": reason,
            "performed": True,
            "success": bool(dismissed),
            "raw_ime_visible_before": bool(before.get("ime_visible")),
            "raw_ime_visible_after": bool(after.get("ime_visible")),
            "served_view_before": before.get("served_view") or "",
            "served_view_after": after.get("served_view") or "",
        })

    def set_bug_analysis_engine(self, engine: "BugAnalysisEngine") -> None:
        """璁剧疆 Bug 鍒嗘瀽寮曟搸"""
        self.bug_analysis_engine = engine

    def set_screenshot_manager(self, manager: "ScreenshotManager") -> None:
        """璁剧疆鎴浘绠＄悊鍣?"""
        self.screenshot_manager = manager

    @staticmethod
    def _json_bool(value) -> bool:
        """Parse booleans robustly when models emit strings."""
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        return str(value).strip().lower() in {"true", "yes", "1"}

    @staticmethod
    def _normalize_case_story_update(value) -> Dict:
        """Keep only the v3 cumulative story fields; ignore legacy side channels."""
        if not isinstance(value, dict):
            return {}
        allowed_fields = {
            "case_story_so_far",
            "story_so_far",
            "new_event",
            "verified_facts",
            "hypotheses",
            "contradiction_candidates",
        }
        return {key: val for key, val in value.items() if key in allowed_fields}

    def execute_action(
        self,
        llm_response: str,
        parsed_widgets: List[Dict],
        adb_controller: ADBController,
        memory_manager: Optional["TestingSequenceMemorizer"] = None,
        activity_name: str = "UnknownActivity",
        target_package: Optional[str] = None
    ) -> Tuple[bool, Optional[ParsedAction]]:
        """
        鎵ц LLM 鍐崇瓥鐨勫姩浣滐紝骞跺湪鎵ц鍚庢娴嬪穿婧冨拰澶栭儴璺宠浆

        瀹屾暣娴佺▼锛?
        1. 瑙ｆ瀽 LLM 鍝嶅簲锛屾彁鍙栨搷浣滅被鍨嬨€佺洰鏍囨帶浠跺悕鍜岃緭鍏ユ枃鏈?
        2. 鍦ㄦ帶浠跺垪琛ㄤ腑鏌ユ壘鍖归厤鐨勬帶浠?
        3. 璁＄畻鐩爣鎺т欢鐨勪腑蹇冨潗鏍?
        4. 璋冪敤 ADB 鎵ц鐩稿簲鐨勬搷浣?
        5. 妫€娴嬫槸鍚﹀彂鐢熷穿婧冿紝濡傛湁宕╂簝鍒欎繚瀛?Bug 鎶ュ憡
        6. 妫€娴嬫槸鍚﹀彂鐢熷閮ㄥ簲鐢ㄨ烦杞紝濡傛湁璺宠浆鍒欒繑鍥炵洰鏍囧簲鐢?

        Args:
            llm_response: LLM 鐨勫搷搴斿瓧绗︿覆
            parsed_widgets: 瑙ｆ瀽鍚庣殑鎺т欢鍒楄〃
            adb_controller: ADB 鎺у埗鍣ㄥ疄渚?
            memory_manager: 璁板繂绠＄悊鍣ㄥ疄渚嬶紝鐢ㄤ簬鐢熸垚澶嶇幇璺緞
            activity_name: 褰撳墠 Activity 鍚嶇О锛岀敤浜?Bug 鎶ュ憡
            target_package: 鐩爣搴旂敤鐨勫寘鍚嶏紝鐢ㄤ簬妫€娴嬪閮ㄨ烦杞?

        Returns:
            鍏冪粍 (success, action):
            - success: True 琛ㄧず鎵ц鎴愬姛锛孎alse 琛ㄧず鎵ц澶辫触
            - action: 瑙ｆ瀽鍚庣殑 ParsedAction 瀵硅薄锛岃В鏋愬け璐ユ椂涓?None
              - action.external_redirect: True 琛ㄧず瑙﹀彂浜嗗閮ㄥ簲鐢ㄨ烦杞?
              - action.redirect_package: 璺宠浆鍒扮殑澶栭儴搴旂敤鍖呭悕

        娉ㄦ剰锛氬穿婧冩娴嬬粨鏋滃瓨鍌ㄥ湪 self.last_crash_detected 鍜?self.last_crash_log 涓?
        """
        print("\n" + "=" * 50)
        print("鍔ㄤ綔鎵ц灞?- 鎵ц LLM 鍐崇瓥")
        print("=" * 50)

        # 閲嶇疆宕╂簝妫€娴嬬姸鎬?
        self.last_crash_detected = False
        self.last_crash_log = ""

        # 姝ラ1锛氳В鏋?LLM 鍝嶅簲
        action = self._parse_llm_response(llm_response)

        if not action.is_valid():
            print(f"[鎵ц澶辫触] 鏃犳硶瑙ｆ瀽 LLM 鍝嶅簲: {llm_response[:100]}...")
            return False, None

        print(f"[瑙ｆ瀽缁撴灉] {action}")

        # ========== 澶勭悊绯荤粺绾у姩浣滐紙鏃犻渶鍖归厤鎺т欢锛?=========
        # 澶勭悊 back 鎿嶄綔锛堢墿鐞嗚繑鍥為敭锛?
        if action.operation == "back":
            print("[绯荤粺鍔ㄤ綔] 鎸変笅绯荤粺杩斿洖閿?")
            success = adb_controller.go_back()
            time.sleep(1)  # 绛夊緟椤甸潰鍒囨崲

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            return success, action

        # 澶勭悊 scroll_down 鎿嶄綔锛堝悜涓嬫粴鍔ㄥ睆骞曪級
        if action.operation == "scroll_down":
            print("[绯荤粺鍔ㄤ綔] 鍚戜笅婊氬姩灞忓箷锛堟煡鐪嬩笅鏂瑰唴瀹癸級")
            success = adb_controller.scroll_down()
            time.sleep(1)  # 绛夊緟婊氬姩瀹屾垚

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            return success, action

        # 澶勭悊 scroll_up 鎿嶄綔锛堝悜涓婃粴鍔ㄥ睆骞曪級
        if action.operation == "scroll_up":
            print("[绯荤粺鍔ㄤ綔] 鍚戜笂婊氬姩灞忓箷锛堟煡鐪嬩笂鏂瑰唴瀹癸級")
            success = adb_controller.scroll_up()
            time.sleep(1)  # 绛夊緟婊氬姩瀹屾垚

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            return success, action

        # ========== 澶勭悊鎺т欢绾ф搷浣滐紙闇€瑕佸尮閰嶆帶浠讹級==========

        # 澶勭悊澶氳緭鍏ユ搷浣滐紙澶氫釜 Widget/Input 瀵癸級
        if action.has_multiple_inputs():
            success = self._execute_multiple_inputs_action(action, parsed_widgets, adb_controller)

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            # 妫€娴嬪閮ㄨ烦杞?
            self._check_external_redirect(adb_controller, target_package, action)

            return success, action

        # 澶勭悊杈撳叆+鎿嶄綔缁勫悎锛圵idget + Input + Operation + OperationWidget锛?
        # 渚嬪锛氳緭鍏ユ枃鏈埌杈撳叆妗嗭紝鐒跺悗鐐瑰嚮 Submit 鎸夐挳
        if action.has_input_with_operation():
            success = self._execute_input_then_operation(action, parsed_widgets, adb_controller)

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            # 妫€娴嬪閮ㄨ烦杞?
            self._check_external_redirect(adb_controller, target_package, action)

            return success, action

        # 澶勭悊杈撳叆鎿嶄綔锛坥peration == 'input' 鎴栨湁 input_text锛?
        if action.operation == "input" or (action.input_text and action.widget):
            success = self._execute_input_action(action, parsed_widgets, adb_controller)

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            # 妫€娴嬪閮ㄨ烦杞?
            self._check_external_redirect(adb_controller, target_package, action)

            return success, action

        # 澶勭悊婊氬姩鎿嶄綔锛堟敮鎸佹柟鍚戯細up/down锛?
        if action.operation == "scroll":
            # 瑙ｆ瀽婊氬姩鏂瑰悜
            scroll_direction = "down"  # 榛樿鍚戜笅婊氬姩
            if action.widget:
                widget_lower = action.widget.lower().strip()
                if widget_lower in ("up", "down", "upward", "downward"):
                    scroll_direction = "up" if "up" in widget_lower else "down"

            success = self._execute_scroll_action(parsed_widgets, adb_controller, direction=scroll_direction)

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            return success, action

        # ========== NEW: 瑙嗚瀹氫綅鍧愭爣鐩存帴鐐瑰嚮锛堟棤 widget 鍚嶇О鏃讹級==========
        # 濡傛灉鎻愪緵浜?TargetX/TargetY 浣嗘病鏈?widget 鍚嶇О锛岀洿鎺ヤ娇鐢ㄥ潗鏍囩偣鍑?
        if action.target_x is not None and action.target_y is not None and not action.widget:
            print(f"[瑙嗚瀹氫綅] 鐩存帴浣跨敤鍧愭爣鐐瑰嚮: ({action.target_x}, {action.target_y})")

            # 鍦ㄦ帶浠跺垪琛ㄤ腑鏌ユ壘鏈€鎺ヨ繎璇ュ潗鏍囩殑鎺т欢锛堢敤浜庢棩蹇楄褰曪級
            closest_widget = None
            min_distance = float('inf')
            for widget in parsed_widgets:
                cx, cy = self._calculate_center(widget)
                if cx is not None and cy is not None:
                    distance = abs(cx - action.target_x) + abs(cy - action.target_y)
                    if distance < min_distance:
                        min_distance = distance
                        closest_widget = widget

            if closest_widget:
                rid = closest_widget.get("resource_id", "")
                print(f"[瑙嗚瀹氫綅] 鏈€杩戞帶浠? {rid}, 璺濈: {min_distance}px")

            # 鎵ц鐐瑰嚮
            success = self._perform_operation(
                action.operation, action.target_x, action.target_y, adb_controller
            )

            # 鎵ц鍚庢娴嬪穿婧?
            self._check_crash_after_action(
                adb_controller, memory_manager, activity_name, action,
                widgets=parsed_widgets, target_package=target_package
            )

            # 妫€娴嬪閮ㄨ烦杞?
            self._check_external_redirect(adb_controller, target_package, action)

            return success, action

        # 姝ラ2锛氭煡鎵惧尮閰嶇殑鎺т欢
        target_widget = self._find_target_widget(
            action.widget, parsed_widgets,
            widget_type=action.widget_type
        )
        if not target_widget and action.target_x is not None and action.target_y is not None:
            print("[瑙嗚瀹氫綅] Widget 鍚嶇О鍖归厤澶辫触锛岄檷绾т娇鐢?LLM 鍧愭爣鍏滃簳")
            target_widget = self._find_target_widget(
                None, parsed_widgets,
                target_x=action.target_x,
                target_y=action.target_y
            )
        if not target_widget:
            print(f"[鎵ц澶辫触] 鏈壘鍒板悕涓?'{action.widget}' 鐨勬帶浠?")
            return False, action

        print(f"[鎵惧埌鎺т欢] ID: {target_widget.get('resource_id', 'N/A')}")
        print(f"[鎺т欢鍧愭爣] bounds: {target_widget.get('bounds', 'N/A')}")
        if action.target_x is not None and action.target_y is not None:
            if self._point_inside_widget(action.target_x, action.target_y, target_widget):
                print(f"[瑙嗚瀹氫綅] LLM 鍧愭爣鍦ㄧ洰鏍囨帶浠跺唴: ({action.target_x}, {action.target_y})")
            else:
                print(
                    f"[瑙嗚瀹氫綅璀﹀憡] LLM 鍧愭爣 ({action.target_x}, {action.target_y}) "
                    f"涓嶅湪鐩爣鎺т欢 bounds={target_widget.get('bounds', 'N/A')} 鍐咃紝"
                    "蹇界暐璇ュ潗鏍囧苟浣跨敤 XML 涓績鐐?"
                )

        # 姝ラ3锛氳绠椾腑蹇冨潗鏍?
        center_x, center_y = self._calculate_center(target_widget)
        if center_x is None or center_y is None:
            print("[鎵ц澶辫触] 鏃犳硶璁＄畻鎺т欢涓績鍧愭爣")
            return False, action

        print(f"[璁＄畻鍧愭爣] 涓績鐐? ({center_x}, {center_y})")

        # 姝ラ4锛氭墽琛屾搷浣?
        success = self._perform_operation(
            action.operation, center_x, center_y, adb_controller
        )

        # 鎵ц鍚庢娴嬪穿婧?
        self._check_crash_after_action(
            adb_controller, memory_manager, activity_name, action,
            widgets=parsed_widgets, target_package=target_package
        )

        # 妫€娴嬪閮ㄨ烦杞?
        self._check_external_redirect(adb_controller, target_package, action)

        return success, action

    def _check_external_redirect(
        self,
        adb_controller: ADBController,
        target_package: Optional[str],
        action: ParsedAction
    ) -> None:
        """
        妫€娴嬪苟澶勭悊澶栭儴搴旂敤璺宠浆

        褰撴搷浣滆Е鍙戜簡澶栭儴搴旂敤璺宠浆鏃讹細
        1. 鏍囪 action.external_redirect = True
        2. 璁板綍璺宠浆鍒扮殑鍖呭悕 action.redirect_package
        3. 鎸?back 杩斿洖鐩爣搴旂敤

        Args:
            adb_controller: ADB 鎺у埗鍣ㄥ疄渚?
            target_package: 鐩爣搴旂敤鍖呭悕
            action: 褰撳墠鎵ц鐨勫姩浣滃璞?
        """
        if not target_package:
            return

        # 鑾峰彇褰撳墠鐒︾偣搴旂敤鍖呭悕
        current_package = adb_controller.get_current_package()

        if current_package != target_package:
            print(f"\n[澶栭儴璺宠浆妫€娴媇 妫€娴嬪埌搴旂敤璺宠浆!")
            print(f"  - 鐩爣搴旂敤: {target_package}")
            print(f"  - 璺宠浆鍒? {current_package}")

            # 鏍囪璺宠浆淇℃伅
            action.external_redirect = True
            action.redirect_package = current_package

            # 鎸?back 杩斿洖鐩爣搴旂敤
            print(f"[澶栭儴璺宠浆澶勭悊] 鎸変笅 back 閿繑鍥炵洰鏍囧簲鐢?..")
            adb_controller.go_back()
            time.sleep(1)

            # 楠岃瘉鏄惁杩斿洖鎴愬姛
            new_package = adb_controller.get_current_package()
            if new_package == target_package:
                print(f"[澶栭儴璺宠浆澶勭悊] 鎴愬姛杩斿洖鐩爣搴旂敤: {target_package}")
            else:
                print(f"[澶栭儴璺宠浆澶勭悊] 璀﹀憡: 褰撳墠鍖呭悕 {new_package}锛屽彲鑳介渶瑕佸啀娆℃寜 back")

    def _check_crash_after_action(
        self,
        adb_controller: ADBController,
        memory_manager: Optional["TestingSequenceMemorizer"],
        activity_name: str,
        action: ParsedAction,
        widgets: Optional[List[Dict]] = None,
        target_package: Optional[str] = None
    ) -> None:
        """
        鍦ㄦ墽琛屽姩浣滃悗妫€娴嬪穿婧冿紝骞朵繚瀛?Bug 鎶ュ憡

        鏅鸿兘宕╂簝妫€娴嬫祦绋嬶紙浼樺寲鐗堬級锛?
        1. 蹇€熸鏌ワ紙0.5绉掑悗锛? 澶у鏁板穿婧冧細绔嬪嵆鍙戠敓
        2. 寮傛杞妫€娴嬶紙鏈€闀?2 绉掞紝鍙戠幇宕╂簝绔嬪嵆杩斿洖锛?
        3. 濡傛灉閰嶇疆浜?BugAnalysisEngine锛屼娇鐢ㄥ妯℃€佸垎鏋愬寮?

        娉ㄦ剰锛歭ogcat 缂撳瓨娓呯┖搴斿湪鍔ㄤ綔鎵ц鍓嶅畬鎴愶紙鐢辫皟鐢ㄦ柟璐熻矗锛?

        妫€娴嬬粨鏋滃瓨鍌ㄥ湪 self.last_crash_detected 鍜?self.last_crash_log 涓?

        Args:
            adb_controller: ADB 鎺у埗鍣ㄥ疄渚?
            memory_manager: 璁板繂绠＄悊鍣ㄥ疄渚?
            activity_name: 褰撳墠 Activity 鍚嶇О
            action: 鍒氭墽琛岀殑鍔ㄤ綔
            widgets: 褰撳墠鎺т欢鍒楄〃锛堢敤浜庨€昏緫閿欒妫€娴嬶級
            target_package: 琚祴搴旂敤鍖呭悕锛岀敤浜庤繃婊よ鎶?
        """
        print("\n[Bug Oracle] 姝ｅ湪妫€娴?Bug...")

        # 閲嶇疆 Bug 鎶ュ憡
        self.last_bug_report = None

        # ========== 鏅鸿兘宕╂簝妫€娴嬶紙浼樺寲锛氬紓姝ヨ疆璇級==========
        # 绛栫暐锛氬厛蹇€熸鏌ワ紝鐒跺悗杞锛屾渶闀跨瓑寰?2 绉?
        # 澶у鏁板穿婧冧細鍦?0.5 绉掑唴鍙戠敓锛屼紭鍖栧悗骞冲潎妫€娴嬫椂闂翠粠 2 绉掗檷鑷?0.5-1 绉?

        max_wait_time = 2.0  # 鏈€闀跨瓑寰呮椂闂?
        check_interval = 0.25  # 妫€鏌ラ棿闅?
        elapsed = 0.0
        crash_detected = False

        print("[Bug Oracle] 鏅鸿兘妫€娴嬩腑锛堟渶闀?2 绉掞紝鍙戠幇宕╂簝绔嬪嵆杩斿洖锛?..")

        while elapsed < max_wait_time:
            # 蹇€熸鏌ュ穿婧冿紙甯﹀寘鍚嶈繃婊わ級
            crash_log = adb_controller.check_for_crash(target_package=target_package)

            if crash_log:
                crash_detected = True
                print(f"[Bug Oracle] 妫€娴嬪埌宕╂簝锛侊紙鑰楁椂: {elapsed:.2f}绉掞級")
                break

            # 鏈娴嬪埌宕╂簝锛岀户缁瓑寰?
            time.sleep(check_interval)
            elapsed += check_interval

        # ========== 澶勭悊妫€娴嬬粨鏋?==========
        if crash_detected:
            print("=" * 60)
            print("馃毃 [宕╂簝妫€娴媇 鍙戠幇搴旂敤宕╂簝锛?")
            print("=" * 60)

            # 鏇存柊宕╂簝鐘舵€?
            self.last_crash_detected = True
            self.last_crash_log = crash_log

            # 浣跨敤 BugAnalysisEngine 澧炲己鍒嗘瀽锛堝鏋滃彲鐢級
            if self.bug_analysis_engine:
                try:
                    self.bug_analysis_engine.set_adb_controller(adb_controller)
                    if self.screenshot_manager:
                        self.bug_analysis_engine.set_screenshot_manager(self.screenshot_manager)

                    # 鑾峰彇鎿嶄綔鍘嗗彶
                    operation_history = []
                    if memory_manager:
                        operation_history = list(memory_manager.operation_history)

                    bug_report = self.bug_analysis_engine.create_crash_report(
                        activity_name=activity_name,
                        operation=action.operation or "unknown",
                        widget=action.widget or "",
                        operation_history=operation_history,
                        target_package=target_package
                    )

                    if bug_report:
                        print(f"   涓ラ噸绋嬪害: {bug_report.severity.value}")
                        print(f"   鎻忚堪: {bug_report.title}")
                        self.last_bug_report = bug_report
                        return

                except Exception as e:
                    print(f"[BugAnalysisEngine] 鍒嗘瀽澶辫触: {e}")

            # 淇濆瓨 Bug 鎶ュ憡
            self._save_bug_report(
                memory_manager=memory_manager,
                activity_name=activity_name,
                action=action,
                crash_log=crash_log
            )
        else:
            self.last_crash_detected = False
            self.last_crash_log = ""
            print(f"[Bug Oracle] 鏈娴嬪埌 Bug锛岀户缁祴璇?..锛堟娴嬭€楁椂: {elapsed:.2f}绉掞級")

    def _save_bug_report(
        self,
        memory_manager: Optional["TestingSequenceMemorizer"],
        activity_name: str,
        action: ParsedAction,
        crash_log: str
    ) -> None:
        """
        淇濆瓨 Bug 鎶ュ憡鍒版枃浠?

        鎶ュ憡鍐呭鍖呮嫭锛?
        1. 宕╂簝鏃堕棿鎴?
        2. 娴嬭瘯鍘嗗彶锛坢emory prompt锛?
        3. 瑙﹀彂宕╂簝鐨勬搷浣?
        4. 瀹屾暣鐨勫穿婧冨爢鏍?

        Args:
            memory_manager: 璁板繂绠＄悊鍣ㄥ疄渚?
            activity_name: 褰撳墠 Activity 鍚嶇О
            action: 瑙﹀彂宕╂簝鐨勫姩浣?
            crash_log: 宕╂簝鏃ュ織
        """
        # 纭繚鎶ュ憡鐩綍瀛樺湪
        BUG_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        # 鐢熸垚鎶ュ憡鏂囦欢鍚嶏紙甯︽椂闂存埑锛?
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = BUG_REPORTS_DIR / f"crash_report_{timestamp}.txt"

        try:
            # 鏋勫缓鎶ュ憡鍐呭
            report_lines = [
                "=" * 70,
                "GPTDroid Bug Report - 搴旂敤宕╂簝鎶ュ憡",
                "=" * 70,
                "",
                f"馃搮 宕╂簝鏃堕棿: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"馃搷 鎵€鍦ㄩ〉闈? {activity_name}",
                f"鈿?瑙﹀彂鎿嶄綔: {action.operation} on '{action.widget}'",
                "",
                "-" * 70,
                "馃搵 娴嬭瘯鍘嗗彶锛堝鐜拌矾寰勶級",
                "-" * 70,
            ]

            # 娣诲姞璁板繂鎻愮ず璇嶏紙濡傛灉鏈夛級
            if memory_manager:
                memory_prompt = memory_manager.get_memory_prompt()
                report_lines.append(memory_prompt)
            else:
                report_lines.append("[鏃犳祴璇曞巻鍙茶褰昡")

            report_lines.extend([
                "",
                "-" * 70,
                "馃挜 宕╂簝鍫嗘爤",
                "-" * 70,
                crash_log,
                "",
                "=" * 70,
                "鎶ュ憡鐢熸垚瀹屾瘯 - 璇峰皢姝ゆ姤鍛婃彁渚涚粰寮€鍙戝洟闃?",
                "=" * 70,
            ])

            # 鍐欏叆鏂囦欢
            report_content = '\n'.join(report_lines)
            report_file.write_text(report_content, encoding='utf-8')

            print(f"[Bug鎶ュ憡] 宸蹭繚瀛樺埌: {report_file}")
            print(f"[Bug鎶ュ憡] 寮€鍙戣€呭彲鏍规嵁姝ゆ姤鍛婂鐜板拰淇闂")

        except Exception as e:
            print(f"[Bug鎶ュ憡] 淇濆瓨澶辫触: {e}")

    def _parse_llm_response(self, llm_response: str) -> ParsedAction:
        """
        瑙ｆ瀽 LLM 鍝嶅簲锛屼紭鍏堜娇鐢?ReAct JSON 鏍煎紡锛屽洖閫€鍏煎鏃ф牸寮?

        瑙ｆ瀽绛栫暐锛?
        1. 灏濊瘯鎻愬彇 JSON 浠ｇ爜鍧楋紙```json ... ```锛?
        2. 灏濊瘯鐩存帴瑙ｆ瀽 JSON 瀵硅薄
        3. 鍥為€€鍒版鍒欒〃杈惧紡瑙ｆ瀽鏃ф牸寮?

        Args:
            llm_response: LLM 鍝嶅簲瀛楃涓?

        Returns:
            ParsedAction 瀵硅薄锛屽寘鍚В鏋愬嚭鐨勬搷浣溿€佹帶浠跺拰杈撳叆鏂囨湰
        """
        action = ParsedAction()

        if not llm_response:
            return action

        # ========== 浼樺厛灏濊瘯 JSON 瑙ｆ瀽锛圧eAct 鏍煎紡锛?=========
        json_action = self._parse_json_response(llm_response)
        if json_action and json_action.is_valid():
            print(f"[JSON瑙ｆ瀽鎴愬姛] {json_action}")
            return json_action

        # ========== 鍥為€€鍒版鍒欒〃杈惧紡瑙ｆ瀽锛堟棫鏍煎紡鍏煎锛?=========
        print("[JSON瑙ｆ瀽澶辫触] 鍥為€€鍒版鍒欒〃杈惧紡瑙ｆ瀽...")
        return self._parse_regex_response(llm_response)

    def parse_action_only(self, llm_response: str) -> Optional[ParsedAction]:
        """
        浠呰В鏋?LLM 鍝嶅簲锛屼笉鎵ц鍔ㄤ綔

        鐢ㄤ簬鍦ㄦ墽琛屽姩浣滀箣鍓嶆鏌?Bug 鏂█锛岀‘淇濈洃绠¤€呭鏌ヤ娇鐢ㄦ纭殑涓婁笅鏂囧揩鐓с€?

        Args:
            llm_response: LLM 鍝嶅簲瀛楃涓?

        Returns:
            ParsedAction 瀵硅薄锛岃В鏋愬け璐ユ椂涓?None
        """
        action = self._parse_llm_response(llm_response)
        if action and action.is_valid():
            return action
        return None

    def _parse_json_response(self, llm_response: str) -> Optional[ParsedAction]:
        """
        瑙ｆ瀽 ReAct JSON 鏍煎紡鐨?LLM 鍝嶅簲

        鏀寔鏍煎紡锛?
        1. Markdown 浠ｇ爜鍧? ```json\n{...}\n```
        2. 绾?JSON 瀵硅薄: {...}

        JSON 瀛楁鏄犲皠锛?
        - Thought -> action.thought
        - Action_Type -> action.operation
        - Target_Widget -> action.widget
        - Input_Content -> action.input_text
        - Status -> action.status

        Args:
            llm_response: LLM 鍝嶅簲瀛楃涓?

        Returns:
            ParsedAction 瀵硅薄锛岃В鏋愬け璐ヨ繑鍥?None
        """
        try:
            json_str = None

            # 绛栫暐1锛氭彁鍙?Markdown JSON 浠ｇ爜鍧?
            json_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
            match = re.search(json_block_pattern, llm_response, re.IGNORECASE)
            if match:
                json_str = match.group(1).strip()
                print(f"[JSON鎻愬彇] 浠庝唬鐮佸潡鎻愬彇: {json_str[:100]}...")

            # 绛栫暐2锛氱洿鎺ユ煡鎵?JSON 瀵硅薄锛堝鏋滄病鏈変唬鐮佸潡锛?
            if not json_str:
                # 鏌ユ壘绗竴涓?{ 鍜屾渶鍚庝竴涓?}
                start_idx = llm_response.find('{')
                end_idx = llm_response.rfind('}')
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    json_str = llm_response[start_idx:end_idx + 1]
                    print(f"[JSON鎻愬彇] 鐩存帴鎻愬彇瀵硅薄: {json_str[:100]}...")

            if not json_str:
                return None

            # 瑙ｆ瀽 JSON
            data = json.loads(json_str)

            # 鏋勫缓 ParsedAction
            action = ParsedAction()

            # 鎻愬彇 Thought
            action.thought = data.get('Thought') or data.get('thought') or data.get('reasoning')

            # ========== NEW: 鎻愬彇 Page_Description ==========
            page_description = data.get('Page_Description') or data.get('page_description')
            if page_description and str(page_description).lower() not in ('null', 'none', ''):
                action.page_description = str(page_description).strip()
                print(f"[JSON瑙ｆ瀽] Page_Description: {action.page_description[:80]}...")

            # ========== 鎻愬彇璇佹嵁鍙欎簨瀛楁 ==========
            step_narrative = (
                data.get('Step_Narrative')
                or data.get('step_narrative')
                or data.get('StepNarrative')
            )
            if isinstance(step_narrative, dict):
                action.step_narrative = step_narrative
            elif step_narrative and str(step_narrative).lower() not in ('null', 'none', ''):
                action.step_narrative = {"narrative": str(step_narrative).strip()}

            case_story_update = (
                data.get('Case_Story_Update')
                or data.get('case_story_update')
                or data.get('CaseStoryUpdate')
            )
            if isinstance(case_story_update, dict):
                action.case_story_update = self._normalize_case_story_update(case_story_update)
            elif case_story_update and str(case_story_update).lower() not in ('null', 'none', ''):
                action.case_story_update = {"case_story_so_far": str(case_story_update).strip()}

            # Backward compatibility: older prompts used Behavior_Narrative.
            behavior_narrative = (
                data.get('Behavior_Narrative')
                or data.get('behavior_narrative')
                or data.get('BehaviorNarrative')
            )
            if isinstance(behavior_narrative, dict):
                action.behavior_narrative = behavior_narrative
            elif behavior_narrative and str(behavior_narrative).lower() not in ('null', 'none', ''):
                action.behavior_narrative = {"narrative": str(behavior_narrative).strip()}

            if action.step_narrative and not action.behavior_narrative:
                action.behavior_narrative = dict(action.step_narrative)

            function_phase = data.get('Function_Phase') or data.get('function_phase') or data.get('FunctionPhase')
            if function_phase and str(function_phase).lower() not in ('null', 'none', ''):
                action.function_phase = str(function_phase).strip().lower().replace("-", "_").replace(" ", "_")

            function_end = data.get('Function_End')
            if function_end is None:
                function_end = data.get('function_end')
            if function_end is None:
                function_end = data.get('FunctionEnd')
            action.function_end = self._json_bool(function_end)

            verification_target = (
                data.get('Verification_Target')
                or data.get('verification_target')
                or data.get('VerificationTarget')
            )
            if verification_target and str(verification_target).lower() not in ('null', 'none', ''):
                action.verification_target = str(verification_target).strip()

            # ========== 鎻愬彇 Function 淇℃伅 ==========
            function_name = data.get('Function') or data.get('function')
            if function_name and str(function_name).lower() not in ('null', 'none', ''):
                action.function_name = str(function_name).strip()

                # Status: Yes = new function (testing), No = continue existing (tested)
                status_val = data.get('Status') or data.get('status')
                if status_val:
                    status_str = str(status_val).strip().lower()
                    if status_str == 'yes':
                        action.function_status = 'testing'
                    elif status_str == 'no':
                        action.function_status = 'tested'
                    else:
                        action.function_status = status_str
                else:
                    action.function_status = 'testing'

            # ========== 鎻愬彇 Operation ==========
            # 鏂版牸寮? Operation 瀛楁
            # 鏃ф牸寮? Action_Type 瀛楁
            operation_val = data.get('Operation') or data.get('operation') or \
                           data.get('Action_Type') or data.get('action_type') or data.get('ActionType')
            if operation_val:
                action.operation = self._normalize_operation(str(operation_val).lower().strip())

            # ========== 鎻愬彇 Widget ==========
            # 鏂版牸寮? Widget 瀛楁锛堣緭鍏ユ鎴栨搷浣滅洰鏍囷級
            # 鏃ф牸寮? Target_Widget 瀛楁
            widget_val = data.get('Widget') or data.get('widget') or \
                        data.get('Target_Widget') or data.get('target_widget') or data.get('TargetWidget')
            if widget_val and str(widget_val).lower() not in ('null', 'none', ''):
                action.widget = str(widget_val).strip()

            # ========== 鎻愬彇 WidgetType ==========
            # 鎺т欢绫诲瀷锛歍extView, EditText, Button, ImageView 绛?
            widget_type_val = data.get('WidgetType') or data.get('widget_type')
            if widget_type_val and str(widget_type_val).lower() not in ('null', 'none', ''):
                action.widget_type = str(widget_type_val).strip()

            # ========== 鎻愬彇 Input ==========
            # 鏂版牸寮? Inputs 鏁扮粍 (澶氳緭鍏ユ敮鎸?
            # 鏃ф牸寮? Input 瀛楁 (鍗曡緭鍏?
            # 鏇存棫鏍煎紡: Input_Content 瀛楁
            inputs_array = data.get('Inputs') or data.get('inputs')
            if inputs_array and isinstance(inputs_array, list):
                # 澶勭悊澶氳緭鍏ユ暟缁勬牸寮忥紙鏀寔 ContentDesc 瀛楁锛?
                input_sequence = []
                for item in inputs_array:
                    if isinstance(item, dict):
                        widget_name = item.get('Widget') or item.get('widget')
                        input_text = item.get('Input') or item.get('input')
                        # 鏂板锛氭彁鍙?ContentDesc 鐢ㄤ簬鍖哄垎鍚?resource-id 鐨勫瓧娈?
                        content_desc = item.get('ContentDesc') or item.get('content_desc')
                        if widget_name and input_text:
                            # 涓夊厓缁勶細(widget_name, input_text, content_desc)
                            input_sequence.append((str(widget_name).strip(), str(input_text).strip(), content_desc))
                if input_sequence:
                    action.input_sequence = input_sequence
                    # 璁剧疆绗竴涓緭鍏ヤ綔涓轰富 widget 鍜?input_text锛堝悜鍚庡吋瀹癸級
                    action.widget = input_sequence[0][0]
                    action.input_text = input_sequence[0][1]
                    # 鏂板锛氳缃涓€涓緭鍏ョ殑 content_desc
                    if input_sequence[0][2]:
                        action.widget_content_desc = str(input_sequence[0][2]).strip()
                    print(f"[JSON瑙ｆ瀽] 澶氳緭鍏ュ簭鍒? {input_sequence}")
            else:
                # 鍗曡緭鍏ユ牸寮?
                input_val = data.get('Input') or data.get('input') or \
                           data.get('Input_Content') or data.get('input_content') or data.get('InputContent')
                if input_val and str(input_val).lower() not in ('null', 'none', ''):
                    action.input_text = str(input_val).strip()

            # ========== 鎻愬彇 OperationWidget ==========
            # 鏂版牸寮忎笓鐢細杈撳叆鎿嶄綔鍚庣殑鐩爣鎺т欢锛堝 Submit 鎸夐挳锛?
            operation_widget = data.get('OperationWidget') or data.get('operation_widget')
            if operation_widget and str(operation_widget).lower() not in ('null', 'none', ''):
                action.operation_widget = str(operation_widget).strip()

            # ========== 鎻愬彇 OperationWidgetType ==========
            # 鎿嶄綔鐩爣鎺т欢绫诲瀷
            operation_widget_type = data.get('OperationWidgetType') or data.get('operation_widget_type')
            if operation_widget_type and str(operation_widget_type).lower() not in ('null', 'none', ''):
                action.operation_widget_type = str(operation_widget_type).strip()

            # ========== 鎻愬彇 Bug_Detected 鍜?Bug_Description ==========
            bug_detected = data.get('Bug_Detected')
            if bug_detected is None:
                bug_detected = data.get('bug_detected')
            action.bug_detected = self._json_bool(bug_detected)
            if action.bug_detected:
                bug_desc = data.get('Bug_Description') or data.get('bug_description')
                if bug_desc and isinstance(bug_desc, dict):
                    action.bug_description = bug_desc
                    print(f"[JSON瑙ｆ瀽] Bug妫€娴? type={bug_desc.get('type')}, severity={bug_desc.get('severity')}")
                elif bug_desc:
                    action.bug_description = {"description": str(bug_desc)}

            # ========== NEW: 鎻愬彇 TargetX 鍜?TargetY (瑙嗚瀹氫綅鍧愭爣) ==========
            target_x = data.get('TargetX') or data.get('target_x') or data.get('targetx')
            target_y = data.get('TargetY') or data.get('target_y') or data.get('targety')
            if target_x is not None and target_y is not None:
                try:
                    action.target_x = int(target_x)
                    action.target_y = int(target_y)
                    print(f"[JSON瑙ｆ瀽] 瑙嗚瀹氫綅鍧愭爣: TargetX={action.target_x}, TargetY={action.target_y}")
                except (ValueError, TypeError) as e:
                    print(f"[JSON瑙ｆ瀽璀﹀憡] TargetX/TargetY 杞崲澶辫触: {e}")

            # ========== 鍚庡鐞?==========
            # 濡傛灉鏈?Input 浣嗘病鏈?Operation锛岄粯璁や负 input 鎿嶄綔
            if action.input_text and not action.operation:
                action.operation = "input"

            # 鎵撳嵃瑙ｆ瀽缁撴灉
            print(f"[JSON瑙ｆ瀽] Thought: {action.thought[:50] if action.thought else 'N/A'}...")
            print(f"[JSON瑙ｆ瀽] Operation: {action.operation}, Widget: {action.widget}, WidgetType: {action.widget_type}, Input: {action.input_text}")
            if action.operation_widget:
                print(f"[JSON瑙ｆ瀽] OperationWidget: {action.operation_widget}, OperationWidgetType: {action.operation_widget_type}")
            if action.function_name:
                print(f"[JSON瑙ｆ瀽] Function: {action.function_name} ({action.function_status})")

            return action

        except json.JSONDecodeError as e:
            print(f"[JSON瑙ｆ瀽閿欒] JSON 鏍煎紡鏃犳晥: {e}")
            return None
        except Exception as e:
            print(f"[JSON瑙ｆ瀽寮傚父] {type(e).__name__}: {e}")
            return None

    def _parse_regex_response(self, llm_response: str) -> ParsedAction:
        """
        浣跨敤姝ｅ垯琛ㄨ揪寮忚В鏋愭棫鏍煎紡鐨?LLM 鍝嶅簲锛堝悜鍚庡吋瀹癸級

        鏀寔澶氱鏍煎紡锛岃兘浠庡寘鍚簾璇濈殑闀挎枃鏈腑绮惧噯鎻愬彇锛?
        - Function: "Add income". Status: Yes. Operation: "Click". Widget: "ADD INCOME".
        - Function: "Add income". Status: No. Widget: "Price". Input: "3500". Operation: "Click". Widget: "Submit".
        - Operation: "click" Widget: "Search"
        - Widget: "SearchBox" Input: "test query"

        Args:
            llm_response: LLM 鍝嶅簲瀛楃涓?

        Returns:
            ParsedAction 瀵硅薄
        """
        action = ParsedAction()

        if not llm_response:
            return action

        try:
            # ========== 鎻愬彇 Function ==========
            # 鏍煎紡: Function: "Add income". 鎴?Function: "Add income"
            function_match = re.search(r'[Ff]unction:\s*"([^"]+)"', llm_response)
            if function_match:
                action.function_name = function_match.group(1).strip()
                print(f"[瑙ｆ瀽] Function: {action.function_name}")

            # ========== 鎻愬彇 Status ==========
            # 鏍煎紡: Status: Yes. 鎴?Status: No.
            # Yes = new function (testing), No = continue existing (tested)
            status_match = re.search(r'[Ss]tatus:\s*(Yes|No)', llm_response, re.IGNORECASE)
            if status_match:
                status_value = status_match.group(1).strip().lower()
                # Yes = new function being tested, No = continuing existing function
                action.function_status = "testing" if status_value == "yes" else "tested"
                print(f"[瑙ｆ瀽] Function Status: {action.function_status}")
            phase_match = re.search(
                r'(?:Function_Phase|Function Phase|FunctionPhase):\s*"?([A-Za-z_ -]+)"?',
                llm_response,
                re.IGNORECASE
            )
            if phase_match:
                action.function_phase = phase_match.group(1).strip().lower().replace("-", "_").replace(" ", "_")

            end_match = re.search(
                r'(?:Function_End|Function End|FunctionEnd):\s*(true|false|yes|no|1|0)',
                llm_response,
                re.IGNORECASE
            )
            if end_match:
                action.function_end = self._json_bool(end_match.group(1))

            target_match = re.search(
                r'(?:Verification_Target|Verification Target|VerificationTarget):\s*"?(.+?)"?(?=\n|$)',
                llm_response,
                re.IGNORECASE
            )
            if target_match:
                action.verification_target = target_match.group(1).strip().strip('"')

            story_match = re.search(
                r'(?:Case_Story_Update|Case Story Update|CaseStoryUpdate):\s*"?(.+?)"?(?=\n|$)',
                llm_response,
                re.IGNORECASE
            )
            if story_match:
                action.case_story_update = {"case_story_so_far": story_match.group(1).strip().strip('"')}

            # ========== 鎻愬彇 Operation ==========
            # 浼樺厛鍖归厤甯﹀弻寮曞彿鐨勬牸寮忥紝鍥為€€鍏煎涓嶅甫寮曞彿鐨勬牸寮?
            # 鏀寔鏍煎紡锛?
            # - Operation: "click"
            # - Operation: "long press"
            # - operation: click锛堟棤寮曞彿锛?
            operation_patterns = [
                # 浼樺厛锛氬甫鍙屽紩鍙风殑鏍煎紡 Operation: "value"
                r'[Oo]peration:\s*"([^"]+)"',
                # 鍥為€€锛氫笉甯﹀紩鍙风殑鏍煎紡 Operation: value锛堝彇鍒拌灏炬垨涓嬩竴涓叧閿瓧锛?
                r'[Oo]peration:\s*([a-zA-Z]+(?:\s+[a-zA-Z]+)?)(?=\s*(?:[Ww]idget|[Ii]nput|$|\n|\.))',
            ]

            for pattern in operation_patterns:
                match = re.search(pattern, llm_response, re.DOTALL | re.IGNORECASE)
                if match:
                    action.operation = match.group(1).strip().lower()
                    break

            # ========== 鎻愬彇 Widget ==========
            # 鏀寔澶氫釜 Widget/Input 瀵癸紙杈撳叆鍦烘櫙锛?
            # 鏍煎紡: Widget: "Price". Input: "3500". Widget: "Title". Input: "salary".
            # 鍙栨渶鍚庝竴涓?Widget 浣滀负鐩爣鎺т欢锛屾垨鑰?Operation 鍚庨潰鐨?Widget
            widget_matches = list(re.finditer(r'[Ww]idget:\s*"([^"]+)"', llm_response))
            if widget_matches:
                # 濡傛灉鏈?Operation锛屾壘 Operation 鍚庨潰鐨?Widget
                if action.operation:
                    op_match = re.search(r'[Oo]peration:', llm_response, re.IGNORECASE)
                    if op_match:
                        op_pos = op_match.end()
                        for wm in widget_matches:
                            if wm.start() > op_pos:
                                action.widget = wm.group(1).strip()
                                break
                        # 濡傛灉娌℃壘鍒帮紝鍙栨渶鍚庝竴涓?Widget
                        if not action.widget:
                            action.widget = widget_matches[-1].group(1).strip()
                    else:
                        action.widget = widget_matches[-1].group(1).strip()
                else:
                    action.widget = widget_matches[-1].group(1).strip()

                # 杩囨护鎺変竴浜涙棤鏁堝€?
                if action.widget and action.widget.lower() in ('none', 'null', '', 'widget'):
                    action.widget = None

            # ========== 鎻愬彇 Input 鏂囨湰 ==========
            # 鏀寔澶氫釜 Input锛屾敹闆嗘墍鏈夎緭鍏ユ枃鏈?
            # 鏍煎紡: Widget: "Price". Input: "3500". Widget: "Title". Input: "salary".
            input_matches = list(re.finditer(r'[Ii]nput:\s*"([^"]+)"', llm_response))
            widget_matches_for_input = list(re.finditer(r'[Ww]idget:\s*"([^"]+)"', llm_response))

            if input_matches:
                # 鏀堕泦鎵€鏈夎緭鍏ワ紝鐢?|| 鍒嗛殧
                inputs = [m.group(1).strip() for m in input_matches]
                action.input_text = " || ".join(inputs)
                print(f"[瑙ｆ瀽] Input texts: {action.input_text}")

                # 鏋勫缓 input_sequence锛圵idget/Input 閰嶅锛?
                # 鎵惧埌姣忎釜 Input 鍓嶉潰鏈€杩戠殑 Widget
                input_sequence = []
                for input_match in input_matches:
                    input_pos = input_match.start()
                    input_val = input_match.group(1).strip()
                    # 鎵炬渶杩戠殑 Widget
                    closest_widget = None
                    for wm in widget_matches_for_input:
                        if wm.start() < input_pos:
                            closest_widget = wm.group(1).strip()
                        else:
                            break
                    if closest_widget:
                        input_sequence.append((closest_widget, input_val, None))  # 涓夊厓缁勶紝content_desc 涓?None

                if input_sequence:
                    action.input_sequence = input_sequence
                    print(f"[瑙ｆ瀽] Input sequence: {input_sequence}")

            # ========== 鍚庡鐞嗗拰楠岃瘉 ==========

            # 濡傛灉鍖归厤鍒颁簡 Input 鏂囨湰浣嗘病鏈夊尮閰嶅埌 Operation锛岃嚜鍔ㄨˉ鍏ㄤ负 input 鎿嶄綔
            if action.input_text and not action.operation:
                action.operation = "input"
                print("[瑙ｆ瀽鎺ㄦ柇] 妫€娴嬪埌 Input 鏂囨湰浣嗘棤 Operation锛岃嚜鍔ㄨ缃负 'input'")

            # 鏍囧噯鍖栨搷浣滃悕绉?
            if action.operation:
                action.operation = self._normalize_operation(action.operation)

            # 娓呯悊 widget 鍚嶇О锛堢Щ闄ら灏惧紩鍙峰拰绌虹櫧锛?
            if action.widget:
                action.widget = action.widget.strip('"\'').strip()

            print(f"[瑙ｆ瀽璇︽儏] operation={action.operation}, widget={action.widget}, input={action.input_text}")

            return action

        except Exception as e:
            print(f"[瑙ｆ瀽寮傚父] {e}")
            return action

    def _normalize_operation(self, operation: str) -> str:
        """
        鏍囧噯鍖栨搷浣滃悕绉?

        Args:
            operation: 鍘熷鎿嶄綔鍚嶇О

        Returns:
            鏍囧噯鍖栧悗鐨勬搷浣滃悕绉?
        """
        operation = operation.lower().strip().replace("-", " ").replace("_", " ")

        # 鍚屼箟璇嶆槧灏?
        operation_map = {
            # 鎺т欢鎿嶄綔鍚屼箟璇?
            "tap": "click",
            "press": "click",
            "double tap": "double click",
            "doubleclick": "double click",
            "longpress": "long press",
            "long click": "long press",
            "swipe": "scroll",
            "type": "input",
            # 绯荤粺绾у姩浣滃悓涔夎瘝
            "go back": "back",
            "press back": "back",
            "back button": "back",
            "go home": "home",
            "press home": "home",
            "home button": "home",
            "scroll down": "scroll_down",
            "scroll screen down": "scroll_down",
            "page down": "scroll_down",
            "scroll up": "scroll_up",
            "scroll screen up": "scroll_up",
            "page up": "scroll_up",
        }

        return operation_map.get(operation, operation)

    def parse_function_query_response(self, llm_response: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Parse function query response from LLM

        Extracts FunctionName + Status from the LLM response to the function query.

        Expected formats:
        - JSON: {"Function": "Login", "Status": "testing"}
        - Text: Login + testing
        - Text with parentheses: (Login + testing)
        - Text: We are testing the Login function. (Login + testing)

        Args:
            llm_response: LLM response string

        Returns:
            Tuple of (function_name, function_status), or (None, None) if parsing fails
        """
        if not llm_response:
            return None, None

        print("\n[Function Query Parser] Parsing LLM response...")

        # Strategy 1: Try JSON parsing
        json_result = self._parse_function_from_json(llm_response)
        if json_result[0]:
            print(f"[Function Query Parser] JSON parsed: {json_result[0]} + {json_result[1]}")
            return json_result

        # Strategy 2: Try pattern matching (FunctionName + Status)
        pattern_result = self._parse_function_from_pattern(llm_response)
        if pattern_result[0]:
            print(f"[Function Query Parser] Pattern matched: {pattern_result[0]} + {pattern_result[1]}")
            return pattern_result

        print("[Function Query Parser] Failed to parse function info")
        return None, None

    def _parse_function_from_json(self, llm_response: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Try to parse function info from JSON format

        Args:
            llm_response: LLM response string

        Returns:
            Tuple of (function_name, function_status)
        """
        try:
            # Try to extract JSON from code block
            json_block_pattern = r'```(?:json)?\s*([\s\S]*?)```'
            match = re.search(json_block_pattern, llm_response, re.IGNORECASE)
            if match:
                json_str = match.group(1).strip()
                data = json.loads(json_str)

                function_name = data.get('Function') or data.get('function') or data.get('FunctionName') or data.get('function_name')
                function_status = data.get('Status') or data.get('status') or data.get('FunctionStatus') or data.get('function_status')

                if function_name:
                    return str(function_name).strip(), str(function_status or "testing").strip()

            # Try to find JSON object directly
            start_idx = llm_response.find('{')
            end_idx = llm_response.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = llm_response[start_idx:end_idx + 1]
                data = json.loads(json_str)

                function_name = data.get('Function') or data.get('function') or data.get('FunctionName') or data.get('function_name')
                function_status = data.get('Status') or data.get('status') or data.get('FunctionStatus') or data.get('function_status')

                if function_name:
                    return str(function_name).strip(), str(function_status or "testing").strip()

        except (json.JSONDecodeError, Exception) as e:
            print(f"[Function JSON Parse] Failed: {e}")

        return None, None

    def _parse_function_from_pattern(self, llm_response: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Try to parse function info from text pattern

        Patterns:
        - FunctionName + Status (e.g., "Login + testing")
        - (FunctionName + Status)

        Args:
            llm_response: LLM response string

        Returns:
            Tuple of (function_name, function_status)
        """
        # Pattern 0 (NEW): Function: "xxx". Status: Yes/No.
        pattern0 = r'[Ff]unction:\s*"([^"]+)"[^.]*\.\s*[Ss]tatus:\s*(Yes|No)'
        match = re.search(pattern0, llm_response, re.IGNORECASE)
        if match:
            func_name = match.group(1).strip()
            status_val = match.group(2).strip().lower()
            # Yes = new function (testing), No = continue existing (tested)
            func_status = 'testing' if status_val == 'yes' else 'tested'
            return func_name, func_status

        # Pattern 1: (FunctionName + Status) with parentheses
        pattern1 = r'\(([A-Za-z_][A-Za-z0-9_\s]*)\s*\+\s*(tested|testing|new)\)'
        match = re.search(pattern1, llm_response, re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).lower()

        # Pattern 2: FunctionName + Status without parentheses
        pattern2 = r'([A-Za-z_][A-Za-z0-9_\s]*)\s*\+\s*(tested|testing|new)'
        match = re.search(pattern2, llm_response, re.IGNORECASE)
        if match:
            return match.group(1).strip(), match.group(2).lower()

        # Pattern 3: "testing FunctionName" or "tested FunctionName"
        pattern3 = r'(testing|tested)\s+(?:the\s+)?([A-Za-z_][A-Za-z0-9_\s]*?)(?:\s+function|\s*$|\.)'
        match = re.search(pattern3, llm_response, re.IGNORECASE)
        if match:
            status = match.group(1).lower()
            func_name = match.group(2).strip()
            return func_name, status

        # Pattern 4: "FunctionName function" with status elsewhere
        pattern4 = r'([A-Za-z_][A-Za-z0-9_\s]*?)\s+function'
        match = re.search(pattern4, llm_response, re.IGNORECASE)
        if match:
            function_name = match.group(1).strip()
            # Check for status in the response
            if 'tested' in llm_response.lower():
                return function_name, 'tested'
            elif 'testing' in llm_response.lower():
                return function_name, 'testing'
            elif 'new' in llm_response.lower():
                return function_name, 'testing'
            return function_name, 'testing'

        return None, None

    def _execute_multiple_inputs_action(
        self,
        action: ParsedAction,
        parsed_widgets: List[Dict],
        adb_controller: ADBController
    ) -> bool:
        """
        鎵ц澶氳緭鍏ユ搷浣滐細渚濇鐐瑰嚮姣忎釜杈撳叆妗嗗苟杈撳叆鏂囨湰

        鏀寔涓夊厓缁?(widget_name, input_text, content_desc)锛岀敤浜庡尯鍒嗗悓鍚嶆帶浠?

        Args:
            action: 瑙ｆ瀽鍚庣殑鍔ㄤ綔锛屽寘鍚?input_sequence
            parsed_widgets: 鎺т欢鍒楄〃
            adb_controller: ADB 鎺у埗鍣?

        Returns:
            鏄惁鎵ц鎴愬姛
        """
        print(f"[澶氳緭鍏ユ搷浣淽 鍏?{len(action.input_sequence)} 涓緭鍏?")

        for i, input_item in enumerate(action.input_sequence, 1):
            # 鏀寔涓夊厓缁?(widget_name, input_text, content_desc) 鎴栦簩鍏冪粍 (widget_name, input_text)
            if len(input_item) == 3:
                widget_name, input_text, content_desc = input_item
            else:
                widget_name, input_text = input_item
                content_desc = None

            print(f"\n[杈撳叆 {i}/{len(action.input_sequence)}] 鎺т欢: {widget_name}, 鏂囨湰: {input_text}")
            if content_desc:
                print(f"  [ContentDesc 鎻愮ず] '{content_desc}'")

            # 鏌ユ壘杈撳叆妗嗘帶浠讹紙浼犻€?content_desc_hint锛?
            target_widget = self._find_target_widget(
                widget_name,
                parsed_widgets,
                widget_type="EditText",
                content_desc_hint=content_desc
            )
            if not target_widget:
                print(f"[鎵ц澶辫触] 鏈壘鍒拌緭鍏ユ: {widget_name}")
                return False

            # 璁＄畻鍧愭爣
            center_x, center_y = self._calculate_center(target_widget)
            if center_x is None or center_y is None:
                print("[鎵ц澶辫触] 鏃犳硶璁＄畻鎺т欢鍧愭爣")
                return False

            # 鐐瑰嚮杈撳叆妗嗚幏鍙栫劍鐐?
            print(f"[鐐瑰嚮] 杈撳叆妗?{widget_name} ({center_x}, {center_y})")
            if not adb_controller.click(center_x, center_y):
                print(f"[鎵ц澶辫触] 鏃犳硶鐐瑰嚮杈撳叆妗? {widget_name}")
                return False

            # 绛夊緟鐒︾偣
            time.sleep(0.5)

            # 浣跨敤 UIAutomator2 娓呴櫎鏃ф枃鏈苟杈撳叆鏂版枃鏈?
            print(f"[娓呴櫎+杈撳叆] 浣跨敤 UIAutomator2 澶勭悊杈撳叆妗?{widget_name}")
            # 灏嗗潗鏍囦俊鎭紶閫掔粰 clear_and_input_text
            target_widget["center_x"] = center_x
            target_widget["center_y"] = center_y
            if not adb_controller.clear_and_input_text(target_widget, input_text):
                print(f"[鎵ц澶辫触] 鏂囨湰杈撳叆澶辫触: {input_text}")
                return False

            # 鏀惰捣閿洏
            self._dismiss_keyboard_after_input(
                adb_controller,
                action,
                "after each field in multi-input action",
            )

            # 鐭殏绛夊緟
            time.sleep(0.3)

        print(f"\n[澶氳緭鍏ユ垚鍔焆 宸插畬鎴?{len(action.input_sequence)} 涓緭鍏?")

        if action.operation_widget and action.operation:
            operation = (action.operation or "").lower()
            if operation in {"input", "type"}:
                print("[澶氳緭鍏ュ悗鎿嶄綔] Operation 鏄?input/type锛岃緭鍏ュ凡瀹屾垚锛岃烦杩囬澶栨帶浠跺姩浣?")
                return True

            print(f"[澶氳緭鍏ュ悗鎿嶄綔] {action.operation} -> {action.operation_widget}")
            target_widget = self._find_target_widget(
                action.operation_widget,
                parsed_widgets,
                widget_type=action.operation_widget_type
            )
            if not target_widget:
                print(f"[鎵ц澶辫触] 鏈壘鍒版搷浣滅洰鏍囨帶浠? {action.operation_widget}")
                return False

            target_x, target_y = self._calculate_center(target_widget)
            if target_x is None or target_y is None:
                print("[鎵ц澶辫触] 鏃犳硶璁＄畻鎿嶄綔鐩爣鎺т欢鍧愭爣")
                return False

            return self._perform_operation(action.operation, target_x, target_y, adb_controller)

        return True

    def _execute_input_then_operation(
        self,
        action: ParsedAction,
        parsed_widgets: List[Dict],
        adb_controller: ADBController
    ) -> bool:
        """
        鎵ц杈撳叆+鎿嶄綔缁勫悎锛氬厛杈撳叆鏂囨湰锛岀劧鍚庢墽琛屾搷浣滐紙濡傜偣鍑?Submit锛?

        鏀寔閫氳繃 widget_content_desc 鍖哄垎鍚?resource-id 鐨勫涓緭鍏ユ

        JSON 鏍煎紡绀轰緥:
        {"Widget": "InputField", "ContentDesc": "Back", "Input": "text", "Operation": "click", "OperationWidget": "Submit"}

        Args:
            action: 瑙ｆ瀽鍚庣殑鍔ㄤ綔锛屽寘鍚?widget, input_text, operation, operation_widget
            parsed_widgets: 鎺т欢鍒楄〃
            adb_controller: ADB 鎺у埗鍣?

        Returns:
            鏄惁鎵ц鎴愬姛
        """
        print(f"[杈撳叆+鎿嶄綔] 杈撳叆妗? {action.widget}, 鏂囨湰: {action.input_text}")
        if action.widget_content_desc:
            print(f"  [ContentDesc 鎻愮ず] '{action.widget_content_desc}'")
        print(f"[杈撳叆+鎿嶄綔] 鍚庣画鎿嶄綔: {action.operation} -> {action.operation_widget}")

        # 姝ラ1锛氳緭鍏ユ枃鏈?
        # 鏌ユ壘杈撳叆妗嗘帶浠讹紙浼犻€?content_desc_hint锛?
        input_widget = self._find_target_widget(
            action.widget,
            parsed_widgets,
            widget_type=action.widget_type,
            content_desc_hint=action.widget_content_desc
        )
        if not input_widget:
            print(f"[鎵ц澶辫触] 鏈壘鍒拌緭鍏ユ: {action.widget}")
            return False

        # 璁＄畻杈撳叆妗嗗潗鏍?
        input_x, input_y = self._calculate_center(input_widget)
        if input_x is None or input_y is None:
            print("[鎵ц澶辫触] 鏃犳硶璁＄畻杈撳叆妗嗗潗鏍?")
            return False

        # 鐐瑰嚮杈撳叆妗嗚幏鍙栫劍鐐?
        print(f"[姝ラ1] 鐐瑰嚮杈撳叆妗?({input_x}, {input_y})")
        if not adb_controller.click(input_x, input_y):
            print("[鎵ц澶辫触] 鏃犳硶鐐瑰嚮杈撳叆妗?")
            return False

        # 绛夊緟閿洏寮瑰嚭
        time.sleep(0.5)

        # 姝ラ2锛氫娇鐢?UIAutomator2 娓呴櫎鏃ф枃鏈苟杈撳叆鏂版枃鏈?
        print(f"[姝ラ2] 浣跨敤 UIAutomator2 娓呴櫎鏃ф枃鏈苟杈撳叆: {action.input_text}")
        # 灏嗗潗鏍囦俊鎭紶閫掔粰 clear_and_input_text
        input_widget["center_x"] = input_x
        input_widget["center_y"] = input_y
        if not adb_controller.clear_and_input_text(input_widget, action.input_text):
            print("[鎵ц澶辫触] 鏂囨湰杈撳叆澶辫触")
            return False

        # 鏀惰捣閿洏锛堣緭鍏ュ畬鎴愬悗鏀惰捣锛岄伩鍏嶉伄鎸″悗缁搷浣滐級
        self._dismiss_keyboard_after_input(
            adb_controller,
            action,
            "before executing follow-up operation",
        )

        # 鐭殏绛夊緟
        time.sleep(0.3)

        # 姝ラ3锛氭墽琛屽悗缁搷浣?
        print(f"[姝ラ3] 鎵ц鎿嶄綔: {action.operation} -> {action.operation_widget}")

        # 鏌ユ壘鎿嶄綔鐩爣鎺т欢
        target_widget = self._find_target_widget(action.operation_widget, parsed_widgets, widget_type=action.operation_widget_type)
        if not target_widget:
            print(f"[鎵ц澶辫触] 鏈壘鍒版搷浣滅洰鏍囨帶浠? {action.operation_widget}")
            return False

        # 璁＄畻鐩爣鍧愭爣
        target_x, target_y = self._calculate_center(target_widget)
        if target_x is None or target_y is None:
            print("[鎵ц澶辫触] 鏃犳硶璁＄畻鐩爣鎺т欢鍧愭爣")
            return False

        # 鎵ц鎿嶄綔
        success = self._perform_operation(action.operation, target_x, target_y, adb_controller)

        if success:
            print(f"[杈撳叆+鎿嶄綔鎴愬姛] 宸茶緭鍏ユ枃鏈苟鎵ц {action.operation}")

        return success

    def _execute_input_action(
        self,
        action: ParsedAction,
        parsed_widgets: List[Dict],
        adb_controller: ADBController
    ) -> bool:
        """
        鎵ц杈撳叆鎿嶄綔锛氬厛瀹氫綅骞剁偣鍑昏緭鍏ユ鑾峰彇鐒︾偣锛岀瓑寰?1 绉掑悗杈撳叆鏂囨湰

        鏀寔閫氳繃 widget_content_desc 鍖哄垎鍚?resource-id 鐨勫涓緭鍏ユ

        Args:
            action: 瑙ｆ瀽鍚庣殑鍔ㄤ綔
            parsed_widgets: 鎺т欢鍒楄〃
            adb_controller: ADB 鎺у埗鍣?

        Returns:
            鏄惁鎵ц鎴愬姛
        """
        print(f"[杈撳叆鎿嶄綔] 鐩爣鎺т欢: {action.widget}, 杈撳叆鏂囨湰: {action.input_text}")
        if action.widget_content_desc:
            print(f"  [ContentDesc 鎻愮ず] '{action.widget_content_desc}'")

        # 鏌ユ壘杈撳叆妗嗘帶浠讹紙浼犻€?content_desc_hint锛?
        target_widget = self._find_target_widget(
            action.widget,
            parsed_widgets,
            widget_type=action.widget_type,
            content_desc_hint=action.widget_content_desc
        )
        if not target_widget:
            print(f"[鎵ц澶辫触] 鏈壘鍒拌緭鍏ユ: {action.widget}")
            return False

        # 璁＄畻鍧愭爣
        center_x, center_y = self._calculate_center(target_widget)
        if center_x is None or center_y is None:
            print("[鎵ц澶辫触] 鏃犳硶璁＄畻鎺т欢鍧愭爣")
            return False

        # 姝ラ1锛氱偣鍑昏緭鍏ユ鑾峰彇鐒︾偣锛堣緭鍏ュ墠蹇呴』鍏堢偣鍑昏杈撳叆妗嗚幏寰楃劍鐐癸級
        print(f"[姝ラ1] 鐐瑰嚮杈撳叆妗嗚幏鍙栫劍鐐?({center_x}, {center_y})")
        if not adb_controller.click(center_x, center_y):
            print("[鎵ц澶辫触] 鏃犳硶鐐瑰嚮杈撳叆妗?")
            return False

        # 姝ラ2锛氱瓑寰?0.5 绉掕杈撳叆妗嗚幏寰楃劍鐐?
        print("[姝ラ2] 绛夊緟杈撳叆妗嗚幏寰楃劍鐐?..")
        time.sleep(0.5)

        # 姝ラ3锛氫娇鐢?UIAutomator2 娓呴櫎鏃ф枃鏈苟杈撳叆鏂版枃鏈?
        print("[姝ラ3] 浣跨敤 UIAutomator2 娓呴櫎鏃ф枃鏈苟杈撳叆鏂版枃鏈?..")
        # 灏嗗潗鏍囦俊鎭紶閫掔粰 clear_and_input_text
        target_widget["center_x"] = center_x
        target_widget["center_y"] = center_y
        if not adb_controller.clear_and_input_text(target_widget, action.input_text):
            print("[鎵ц澶辫触] 鏂囨湰杈撳叆澶辫触")
            return False

        # 鏀惰捣閿洏
        self._dismiss_keyboard_after_input(
            adb_controller,
            action,
            "after input action",
        )

        print("[杈撳叆鎴愬姛] 鏂囨湰宸茶緭鍏ュ畬鎴?")
        return True

    def _execute_scroll_action(
        self,
        parsed_widgets: List[Dict],
        adb_controller: ADBController,
        direction: str = "down"
    ) -> bool:
        """
        鎵ц婊氬姩鎿嶄綔

        Args:
            parsed_widgets: 鎺т欢鍒楄〃锛堢敤浜庣‘瀹氭粴鍔ㄥ尯鍩燂級
            adb_controller: ADB 鎺у埗鍣?
            direction: 婊氬姩鏂瑰悜锛?down"锛堝悜涓嬫粴鍔紝鏌ョ湅涓嬫柟鍐呭锛夋垨 "up"锛堝悜涓婃粴鍔紝鏌ョ湅涓婃柟鍐呭锛?

        Returns:
            鏄惁鎵ц鎴愬姛
        """
        # 鏍囧噯鍖栨柟鍚?
        direction = direction.lower().strip()
        if direction not in ("up", "down", "upward", "downward"):
            direction = "down"

        is_scroll_down = direction in ("down", "downward")

        if is_scroll_down:
            print("[婊氬姩鎿嶄綔] 鍚戜笅婊氬姩灞忓箷锛堟煡鐪嬩笅鏂瑰唴瀹癸級")
        else:
            print("[婊氬姩鎿嶄綔] 鍚戜笂婊氬姩灞忓箷锛堟煡鐪嬩笂鏂瑰唴瀹癸級")

        # 璁＄畻灞忓箷涓績浣嶇疆浣滀负婊氬姩璧风偣
        # 榛樿灞忓箷鍙傛暟
        screen_center_x = 540
        screen_height = 1920
        scroll_distance = 500  # 婊氬姩璺濈

        # 濡傛灉鏈夋帶浠朵俊鎭紝浣跨敤鎺т欢鍖哄煙鐨勪腑蹇?
        if parsed_widgets:
            max_y = 0
            min_y = screen_height

            for widget in parsed_widgets:
                cy = widget.get('center_y', 0)
                if cy:
                    max_y = max(max_y, cy)
                    min_y = min(min_y, cy)

            if max_y > 0:
                scroll_start_y = max_y - 100  # 浠庡簳閮ㄥ尯鍩熷紑濮?
            else:
                scroll_start_y = 1400

            if min_y < screen_height:
                scroll_end_y = min_y + 100  # 婊氬姩鍒伴《閮ㄥ尯鍩?
            else:
                scroll_end_y = 400
        else:
            scroll_start_y = 1400
            scroll_end_y = 400

        # 鏍规嵁鏂瑰悜纭畾婊氬姩鍙傛暟
        if is_scroll_down:
            # 鍚戜笅婊氬姩锛氫粠涓嬪線涓婃粦鍔紙鎵嬫寚浠庝笅寰€涓婂垝锛屽唴瀹瑰線涓嬭蛋锛?
            start_y = scroll_start_y
            end_y = scroll_start_y - scroll_distance
        else:
            # 鍚戜笂婊氬姩锛氫粠涓婂線涓嬫粦鍔紙鎵嬫寚浠庝笂寰€涓嬪垝锛屽唴瀹瑰線涓婅蛋锛?
            start_y = scroll_end_y
            end_y = scroll_end_y + scroll_distance

        print(f"[婊氬姩鍙傛暟] 璧风偣: ({screen_center_x}, {start_y}), 缁堢偣: ({screen_center_x}, {end_y})")

        # 鎵ц婊戝姩
        return adb_controller.swipe(screen_center_x, start_y, screen_center_x, end_y, duration=500)

    def _find_target_widget(
        self,
        widget_name: str,
        parsed_widgets: List[Dict],
        widget_type: Optional[str] = None,
        content_desc_hint: Optional[str] = None,  # 鏂板鍙傛暟锛氱敤浜庡尯鍒嗗悓 resource-id 鐨勫瓧娈?
        target_x: Optional[int] = None,  # NEW: 鐩爣涓績 X 鍧愭爣锛堣瑙夊畾浣嶏級
        target_y: Optional[int] = None   # NEW: 鐩爣涓績 Y 鍧愭爣锛堣瑙夊畾浣嶏級
    ) -> Optional[Dict]:
        """
        鍦ㄦ帶浠跺垪琛ㄤ腑鏌ユ壘鍚嶇О鍖归厤鐨勬帶浠?

        鍖归厤绛栫暐锛堟寜浼樺厛绾ф帓搴忥級锛?
        0B. 濡傛灉鎻愪緵浜?target_x/target_y锛岄€氳繃鍧愭爣璺濈鍖归厤锛堟渶楂樹紭鍏堢骇 - 瑙嗚瀹氫綅锛?
        0. 濡傛灉鎻愪緵浜?widget_type锛岄€氳繃 text + class 缁勫悎绮剧‘鍖归厤
        1. 绮剧‘鍖归厤 text 瀛楁
        2A. resource-id + content_desc 缁勫悎鍖归厤锛堢敤浜庡尯鍒嗗悓 resource-id 鐨勫瓧娈碉級
        2. 绮剧‘鍖归厤 resource-id 鐨勬渶鍚庝竴閮ㄥ垎锛堝鏈夊涓尮閰嶏紝浼氬彂鍑鸿鍛婏級
        3. 绾尮閰?content-desc
        4. 妯＄硦鍖归厤锛堝寘鍚叧绯伙級
        5. 璇箟鍏抽敭璇嶅尮閰?

        缁堟瀬娓呮礂锛氱Щ闄ゆ墍鏈夌┖鐧藉瓧绗﹀悗鍐嶅尮閰?

        Args:
            widget_name: 鐩爣鎺т欢鍚嶇О
            parsed_widgets: 鎺т欢鍒楄〃
            widget_type: 鎺т欢绫诲瀷锛圱extView, EditText, Button 绛夛級
            content_desc_hint: content_desc 鎻愮ず锛堢敤浜庡尯鍒嗗悓 resource-id 鐨勫瓧娈碉級
            target_x: 鐩爣涓績 X 鍧愭爣锛堣瑙夊畾浣嶏級
            target_y: 鐩爣涓績 Y 鍧愭爣锛堣瑙夊畾浣嶏級

        Returns:
            鎵惧埌鐨勬帶浠跺瓧鍏革紝鏈壘鍒拌繑鍥?None
        """
        if not parsed_widgets:
            return None

        # ========== 绛栫暐0B锛氬潗鏍囧尮閰嶏紙NEW - 鏈€楂樹紭鍏堢骇 - 瑙嗚瀹氫綅锛?=========
        if target_x is not None and target_y is not None and not widget_name:
            print(f"[鍖归厤绛栫暐0B] 浣跨敤 LLM 鎻愪緵鐨勮瑙夊畾浣嶅潗鏍? ({target_x}, {target_y})")

            closest_widget = None
            min_distance = float('inf')
            tolerance = 100  # 瀹瑰樊 100px

            for widget in parsed_widgets:
                cx, cy = self._calculate_center(widget)
                if cx is not None and cy is not None:
                    distance = abs(cx - target_x) + abs(cy - target_y)
                    widget_name_temp = widget.get("text", "") or widget.get("resource_id", "")
                    if "/" in widget_name_temp:
                        widget_name_temp = widget_name_temp.split("/")[-1]
                    print(f"  [璺濈璁＄畻] '{widget_name_temp}' center=({cx},{cy}), distance={distance}px")

                    if distance < min_distance and distance < tolerance:
                        min_distance = distance
                        closest_widget = widget

            if closest_widget:
                closest_name = closest_widget.get("text", "") or closest_widget.get("resource_id", "")
                if "/" in closest_name:
                    closest_name = closest_name.split("/")[-1]
                print(f"[鍖归厤鎴愬姛] 閫氳繃瑙嗚瀹氫綅鍧愭爣鎵惧埌鏈€杩戞帶浠? '{closest_name}', distance={min_distance}px")
                return closest_widget
            else:
                print(f"[鍖归厤璀﹀憡] 瑙嗚瀹氫綅鍧愭爣 ({target_x}, {target_y}) 鏈壘鍒板宸寖鍥村唴鐨勬帶浠讹紝缁х画浣跨敤鍚嶇О鍖归厤...")

        if not widget_name:
            return None

        # ========== 缁堟瀬瀛楃涓叉竻娲楄緟鍔╁嚱鏁?==========
        def clean_text(text: str) -> str:
            """绉婚櫎鎵€鏈夌┖鐧藉瓧绗︼紝杞皬鍐?"""
            if not text:
                return ""
            return re.sub(r'\s+', '', text.lower())

        widget_name_clean = clean_text(widget_name)
        widget_name_lower = widget_name.lower().strip('"\'')

        # Stable aliases generated by PromptGenerator for EditText controls.
        # Example: "Text Input 1" should match the first EditText on the page,
        # regardless of the field's current text value.
        alias_match = re.match(r'^(?:textinput|inputfield|edittext)(\d+)?$', widget_name_clean)
        wants_edittext = (not widget_type) or ("edittext" in widget_type.lower())
        if alias_match and wants_edittext:
            edittext_widgets = [
                widget for widget in parsed_widgets
                if "edittext" in widget.get("class", "").lower()
            ]
            alias_index = int(alias_match.group(1) or "1")
            if 1 <= alias_index <= len(edittext_widgets):
                print(f"[鍖归厤鎴愬姛] 閫氳繃绋冲畾杈撳叆妗嗗埆鍚嶅尮閰? {widget_name} -> EditText #{alias_index}")
                return edittext_widgets[alias_index - 1]
            print(f"[鍖归厤璀﹀憡] 杈撳叆妗嗗埆鍚?{widget_name} 瓒呭嚭鑼冨洿锛屽綋鍓?EditText 鏁伴噺: {len(edittext_widgets)}")

        print(f"[鍖归厤璋冭瘯] 鐩爣鎺т欢鍚? '{widget_name}' (clean: '{widget_name_clean}')")
        print(f"[鍖归厤璋冭瘯] 鎺т欢鍒楄〃鏁伴噺: {len(parsed_widgets)}")
        if widget_type:
            print(f"[鍖归厤璋冭瘯] 鐩爣鎺т欢绫诲瀷: '{widget_type}'")

        # 鎵撳嵃鎵€鏈夋帶浠剁殑鏍囪瘑淇℃伅锛堢敤浜庤皟璇曪級- 鏄剧ず鎵€鏈夋帶浠?
        print("[鍖归厤璋冭瘯] 鎺т欢鍒楄〃璇︽儏:")
        for i, w in enumerate(parsed_widgets):
            text = w.get("text", "")
            rid = w.get("resource_id", "")
            cd = w.get("content_desc", "")
            cls = w.get("class", "")
            # 鎻愬彇绠€鍗曠被鍚?
            simple_class = cls.split(".")[-1] if cls else ""
            # 鏄剧ず娓呮礂鍓嶅悗瀵规瘮
            text_clean = clean_text(text)
            print(f"  [{i}] text='{text}' (clean: '{text_clean}'), class='{simple_class}', id='{rid}', content_desc='{cd}'")

        # ========== 绛栫暐0锛歵ext + class 缁勫悎绮剧‘鍖归厤锛堟渶楂樹紭鍏堢骇锛?=========
        if widget_type:
            print(f"[鍖归厤绛栫暐0] 灏濊瘯 text + class 缁勫悎鍖归厤...")
            for widget in parsed_widgets:
                text = widget.get("text", "")
                class_name = widget.get("class", "")

                # 鎻愬彇绠€鍗曠被鍚?
                simple_class = class_name.split(".")[-1] if class_name else ""

                # 娓呮礂鍚庡尮閰?text
                text_clean = clean_text(text)
                if text_clean == widget_name_clean:
                    # 妫€鏌?class 鏄惁鍖归厤
                    if widget_type.lower() in simple_class.lower():
                        print(f"[鍖归厤鎴愬姛] 閫氳繃 text+class 缁勫悎绮剧‘鍖归厤: text='{text}', class='{simple_class}' (target: {widget_type})")
                        return widget
                    else:
                        print(f"  [璺宠繃] text 鍖归厤浣?class 涓嶅尮閰? text='{text}', class='{simple_class}' (target: {widget_type})")

        # 绛栫暐1锛氱簿纭尮閰?text锛堝寘鎷?original_text锛?
        for widget in parsed_widgets:
            text = widget.get("text", "")
            original_text = widget.get("original_text", "")
            # 鍚屾椂妫€鏌?text 鍜?original_text
            for txt in [text, original_text]:
                if txt and txt.strip():
                    # 娓呮礂鍚庣簿纭尮閰?
                    txt_clean = clean_text(txt)
                    if txt_clean == widget_name_clean:
                        print(f"[鍖归厤鎴愬姛] 閫氳繃 text 娓呮礂鍚庣簿纭尮閰? '{txt}' -> '{txt_clean}'")
                        return widget

        # ========== 绛栫暐2A锛歳esource-id + content_desc 缁勫悎鍖归厤锛堟柊澧烇級==========
        # 鐢ㄤ簬鍖哄垎鍚?resource-id 鐨勫涓帶浠讹紙濡?AnkiDroid 涓殑 Front/Back 瀛楁锛?
        if content_desc_hint:
            print(f"[鍖归厤绛栫暐2A] 灏濊瘯 resource-id + content_desc 缁勫悎鍖归厤锛宧int='{content_desc_hint}'...")
            for widget in parsed_widgets:
                resource_id = widget.get("resource_id", "")
                widget_cd = widget.get("content_desc", "")

                if resource_id:
                    id_name = resource_id.split("/")[-1] if "/" in resource_id else resource_id
                    id_clean = clean_text(id_name)

                    if id_clean == widget_name_clean:
                        # 鍖归厤 content_desc
                        cd_clean = clean_text(widget_cd)
                        hint_clean = clean_text(content_desc_hint)

                        if cd_clean == hint_clean or hint_clean in cd_clean:
                            print(f"[鍖归厤鎴愬姛] resource-id + content_desc 缁勫悎鍖归厤: id='{id_name}', cd='{widget_cd}'")
                            return widget
                        else:
                            print(f"  [璺宠繃] resource-id 鍖归厤浣?content_desc 涓嶅尮閰? id='{id_name}', cd='{widget_cd}' (鏈熸湜: '{content_desc_hint}')")

        # ========== 绛栫暐2锛氱簿纭尮閰?resource-id 鏈€鍚庝竴閮ㄥ垎锛堟敼杩涳細璀﹀憡澶氬尮閰嶏級==========
        matching_widgets = []
        for widget in parsed_widgets:
            resource_id = widget.get("resource_id", "")
            if resource_id:
                id_name = resource_id.split("/")[-1] if "/" in resource_id else resource_id
                id_clean = clean_text(id_name)
                if id_clean == widget_name_clean:
                    matching_widgets.append(widget)

        if len(matching_widgets) == 1:
            widget = matching_widgets[0]
            rid = widget.get("resource_id", "")
            cd = widget.get("content_desc", "")
            print(f"[鍖归厤鎴愬姛] 閫氳繃 resource-id 绮剧‘鍖归厤: '{rid.split('/')[-1]}' (content_desc='{cd}')")
            return widget

        # 濡傛灉鏈夊涓尮閰嶇殑鎺т欢锛屽彂鍑鸿鍛婂苟杩斿洖绗竴涓紙寤鸿浣跨敤 content_desc锛?
        if len(matching_widgets) > 1:
            print(f"[鍖归厤璀﹀憡] 鍙戠幇 {len(matching_widgets)} 涓悓鍚嶆帶浠?resource-id='{widget_name}'锛?")
            for i, w in enumerate(matching_widgets):
                cd = w.get("content_desc", "")
                text = w.get("text", "")
                print(f"  [{i}] content_desc='{cd}', text='{text[:30] if text else ''}'")
            print(f"[鍖归厤寤鸿] 璇峰湪 JSON 涓娇鐢?ContentDesc 瀛楁鎸囧畾鐩爣鎺т欢锛堝 'Front' 鎴?'Back'锛?")
            # 杩斿洖绗竴涓紙榛樿琛屼负锛屼絾鍙兘涓嶅噯纭級
            print(f"[鍖归厤缁撴灉] 杩斿洖绗竴涓悓鍚嶆帶浠讹紙鍙兘涓嶅噯纭級")
            return matching_widgets[0]

        # 绛栫暐3锛氱簿纭尮閰?content-desc
        for widget in parsed_widgets:
            content_desc = widget.get("content_desc", "")
            if content_desc and content_desc.strip():
                cd_clean = clean_text(content_desc)
                if cd_clean == widget_name_clean:
                    print(f"[鍖归厤鎴愬姛] 閫氳繃 content-desc 绮剧‘鍖归厤: {content_desc}")
                    return widget

        # 绛栫暐4锛氭ā绯婂尮閰嶏紙鍖呭惈鍏崇郴锛? 涔熶娇鐢ㄦ竻娲楀悗鐨勫瓧绗︿覆
        for widget in parsed_widgets:
            text = widget.get("text", "")
            original_text = widget.get("original_text", "")
            resource_id = widget.get("resource_id", "")
            content_desc = widget.get("content_desc", "")

            # 鏀堕泦鎵€鏈夊彲鑳界殑鏂囨湰鏍囪瘑骞舵竻娲?
            all_texts = [text, original_text, content_desc]

            for txt in all_texts:
                if txt and txt.strip():
                    txt_clean = clean_text(txt)
                    # 娓呮礂鍚庢ā绯婂尮閰嶏紙鍖呭惈鍏崇郴锛?
                    if widget_name_clean in txt_clean or txt_clean in widget_name_clean:
                        print(f"[鍖归厤鎴愬姛] 閫氳繃娓呮礂鍚庢ā绯婂尮閰? '{txt}' -> '{txt_clean}'")
                        return widget

            # 妫€鏌?resource-id 鏄惁鍖呭惈 widget_name
            if resource_id:
                id_name = resource_id.split("/")[-1] if "/" in resource_id else resource_id
                id_clean = clean_text(id_name)
                if widget_name_clean in id_clean or id_clean in widget_name_clean:
                    print(f"[鍖归厤鎴愬姛] 閫氳繃 resource-id 妯＄硦鍖归厤: {id_name}")
                    return widget

        # 绛栫暐5锛氳涔夊叧閿瘝鍖归厤锛堝鐞?LLM 杩斿洖璇箟鎻忚堪鐨勬儏鍐碉級
        semantic_match = self._semantic_keyword_match(widget_name, widget_name_clean, parsed_widgets, widget_type)
        if semantic_match:
            return semantic_match

        print(f"[鍖归厤澶辫触] 鏈壘鍒板尮閰嶆帶浠? '{widget_name}' (clean: '{widget_name_clean}')")
        return None

    def _semantic_keyword_match(
        self,
        widget_name: str,
        widget_name_clean: str,
        parsed_widgets: List[Dict],
        widget_type: Optional[str] = None
    ) -> Optional[Dict]:
        """
        璇箟鍏抽敭璇嶅尮閰?

        澶勭悊 LLM 杩斿洖璇箟鎻忚堪鐨勬儏鍐碉紝渚嬪锛?
        - "鐢ㄦ埛鍚嶈緭鍏ユ" -> 鍖归厤 resource_id="username" 鎴?text="璇疯緭鍏ョ敤鎴峰悕"
        - "鐧诲綍鎸夐挳" -> 鍖归厤 resource_id="login" 鎴?text="鐧诲綍"
        - "瀵嗙爜" -> 鍖归厤 resource_id="password"

        Args:
            widget_name: 鍘熷鎺т欢鍚嶇О
            widget_name_clean: 娓呮礂鍚庣殑鎺т欢鍚嶇О
            parsed_widgets: 鎺т欢鍒楄〃
            widget_type: 鎺т欢绫诲瀷

        Returns:
            鍖归厤鍒扮殑鎺т欢锛屾湭鎵惧埌杩斿洖 None
        """
        # 璁＄畻灏忓啓鐗堟湰
        widget_name_lower = widget_name.lower().strip('"\'')

        # 璇箟鍏抽敭璇嶆槧灏勮〃
        SEMANTIC_KEYWORDS = {
            # 鐧诲綍鐩稿叧
            "鐧诲綍": ["login", "signin", "log_in", "sign_in"],
            "娉ㄥ唽": ["register", "signup", "sign_up", "create"],
            "鎻愪氦": ["submit", "confirm", "ok", "done"],
            "鍙栨秷": ["cancel", "close", "dismiss"],

            # 鐢ㄦ埛鐩稿叧
            "鐢ㄦ埛鍚?": ["username", "user", "account", "loginname", "name"],
            "瀵嗙爜": ["password", "pwd", "pass"],
            "閭": ["email", "mail"],
            "鎵嬫満": ["phone", "mobile", "tel"],
            "楠岃瘉鐮?": ["code", "captcha", "verify"],

            # 鎿嶄綔鐩稿叧
            "鎼滅储": ["search", "find", "query"],
            "鍙戦€?": ["send", "submit", "post"],
            "淇濆瓨": ["save", "store"],
            "鍒犻櫎": ["delete", "remove", "clear"],
            "缂栬緫": ["edit", "modify", "change"],
            "璁剧疆": ["setting", "config", "preference"],

            # 瀵艰埅鐩稿叧
            "杩斿洖": ["back", "return", "prev"],
            "涓嬩竴姝?": ["next", "forward", "continue"],
            "瀹屾垚": ["finish", "done", "complete"],

            # 鑻辨枃鍏抽敭璇?
            "username": ["username", "user", "account", "loginname", "鐢ㄦ埛鍚?"],
            "password": ["password", "pwd", "瀵嗙爜"],
            "login": ["login", "signin", "鐧诲綍"],
            "submit": ["submit", "confirm", "鎻愪氦", "纭畾"],
            "cancel": ["cancel", "鍙栨秷"],
            "search": ["search", "鎼滅储", "鏌ユ壘"],
        }

        # 鎵╁睍鍏抽敭璇嶏細鎻愬彇 widget_name 涓殑鍏抽敭璇?
        expanded_keywords = []
        for key, synonyms in SEMANTIC_KEYWORDS.items():
            if key in widget_name_lower or key in widget_name_clean:
                expanded_keywords.extend(synonyms)

        if not expanded_keywords:
            return None

        print(f"[璇箟鍖归厤] 鎵╁睍鍏抽敭璇? {expanded_keywords}")

        # 鍦ㄦ帶浠朵腑鎼滅储鍖归厤
        for widget in parsed_widgets:
            text = widget.get("text", "").lower()
            original_text = widget.get("original_text", "").lower()
            resource_id = widget.get("resource_id", "").lower()
            content_desc = widget.get("content_desc", "").lower()
            class_name = widget.get("class", "")

            # 鎻愬彇 resource-id 鐨勬渶鍚庝竴閮ㄥ垎
            id_name = resource_id.split("/")[-1] if "/" in resource_id else resource_id

            # 鏀堕泦鎵€鏈夋枃鏈?
            all_texts = [text, original_text, content_desc, id_name]

            # 妫€鏌ユ槸鍚﹀尮閰嶄换浣曟墿灞曞叧閿瘝
            for keyword in expanded_keywords:
                keyword_clean = re.sub(r'\s+', '', keyword.lower())
                for txt in all_texts:
                    txt_clean = re.sub(r'\s+', '', txt)
                    if keyword_clean in txt_clean:
                        # 濡傛灉鎸囧畾浜?widget_type锛屾鏌?class 鏄惁鍖归厤
                        if widget_type:
                            simple_class = class_name.split(".")[-1] if class_name else ""
                            if widget_type.lower() not in simple_class.lower():
                                continue
                        print(f"[鍖归厤鎴愬姛] 閫氳繃璇箟鍏抽敭璇嶅尮閰? '{keyword}' -> '{txt}'")
                        return widget

        return None

    def _parse_bounds(self, widget: Dict) -> Optional[Tuple[int, int, int, int]]:
        """Parse Android bounds string like [x1,y1][x2,y2]."""
        bounds = widget.get("bounds", "") if widget else ""
        if not bounds:
            return None

        match = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds)
        if not match:
            return None

        return tuple(map(int, match.groups()))

    def _point_inside_widget(self, x: int, y: int, widget: Dict) -> bool:
        """Return True when a point is inside the widget bounds."""
        parsed_bounds = self._parse_bounds(widget)
        if not parsed_bounds:
            return False

        x1, y1, x2, y2 = parsed_bounds
        return x1 <= x <= x2 and y1 <= y <= y2

    def _calculate_center(self, widget: Dict) -> Tuple[Optional[int], Optional[int]]:
        """
        璁＄畻鎺т欢鐨勪腑蹇冨潗鏍?

        浼樺厛浣跨敤宸茶绠楀ソ鐨?center_x/center_y锛屽惁鍒欎粠 bounds 瑙ｆ瀽

        Args:
            widget: 鎺т欢淇℃伅瀛楀吀

        Returns:
            鍏冪粍 (center_x, center_y)锛岃В鏋愬け璐ヨ繑鍥?(None, None)
        """
        # 浼樺厛浣跨敤宸茶绠楀ソ鐨勫潗鏍?
        if widget.get("center_x") and widget.get("center_y"):
            return widget["center_x"], widget["center_y"]

        # 浠?bounds 瑙ｆ瀽
        bounds = widget.get("bounds", "")
        if not bounds:
            return None, None

        try:
            pattern = r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]'
            match = re.match(pattern, bounds)

            if not match:
                return None, None

            x1, y1, x2, y2 = map(int, match.groups())
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2

            return center_x, center_y

        except Exception as e:
            print(f"[鍧愭爣璁＄畻寮傚父] {e}")
            return None, None

    def _perform_operation(
        self,
        operation: str,
        x: int,
        y: int,
        adb_controller: ADBController
    ) -> bool:
        """
        鎵ц鍏蜂綋鐨勬搷浣?

        鏍规嵁鎿嶄綔绫诲瀷璋冪敤鐩稿簲鐨?ADB 鍛戒护

        Args:
            operation: 鎿嶄綔绫诲瀷
            x: X 鍧愭爣
            y: Y 鍧愭爣
            adb_controller: ADB 鎺у埗鍣ㄥ疄渚?

        Returns:
            True 琛ㄧず鎵ц鎴愬姛锛孎alse 琛ㄧず澶辫触
        """
        # 鏍囧噯鍖栨搷浣滃悕绉?
        operation = operation.lower().replace("-", " ").strip()

        if operation == "click":
            print(f"[鎵ц鎿嶄綔] 鐐瑰嚮鍧愭爣 ({x}, {y})")
            return adb_controller.click(x, y)

        elif operation == "double click":
            print(f"[鎵ц鎿嶄綔] 鍙屽嚮鍧愭爣 ({x}, {y})")
            success1 = adb_controller.click(x, y)
            time.sleep(0.1)
            success2 = adb_controller.click(x, y)
            return success1 and success2

        elif operation == "long press":
            print(f"[鎵ц鎿嶄綔] 闀挎寜鍧愭爣 ({x}, {y})")
            return adb_controller.swipe(x, y, x, y, duration=1000)

        elif operation == "scroll":
            print(f"[鎵ц鎿嶄綔] 浠?({x}, {y}) 鍚戜笂婊戝姩")
            return adb_controller.swipe(x, y + 200, x, y - 200, duration=500)

        else:
            print(f"[鎵ц澶辫触] 涓嶆敮鎸佺殑鎿嶄綔绫诲瀷: {operation}")
            return False


# 娴嬭瘯鍏ュ彛
if __name__ == "__main__":
    executor = ActionExecutor()

    # ========== 娴嬭瘯 ReAct JSON 鏍煎紡瑙ｆ瀽 ==========
    json_test_responses = [
        # 鏍囧噯 JSON 鏍煎紡锛堝甫浠ｇ爜鍧楋級
        '''```json
{
  "Thought": "The Login button is visible and not yet explored. I should click it to navigate to the login page.",
  "Action_Type": "click",
  "Target_Widget": "Login",
  "Input_Content": null,
  "Status": "Testing login flow"
}
```''',
        # 绾?JSON 瀵硅薄锛堟棤浠ｇ爜鍧楋級
        '{"Thought": "There is a search input field.", "Action_Type": "input", "Target_Widget": "SearchBox", "Input_Content": "test query", "Status": "Testing search"}',
        # back 鎿嶄綔
        '''```json
{
  "Thought": "I have explored all widgets on this page.",
  "Action_Type": "back",
  "Target_Widget": null,
  "Input_Content": null,
  "Status": "Navigating back"
}
```''',
        # scroll_down 鎿嶄綔
        '''```json
{
  "Thought": "There might be more content below.",
  "Action_Type": "scroll_down",
  "Target_Widget": null,
  "Input_Content": null,
  "Status": "Exploring hidden content"
}
```''',
        # 灏忓啓瀛楁鍚嶆祴璇?
        '{"thought": "test", "action_type": "click", "target_widget": "Settings", "input_content": null}',
    ]

    print("=" * 60)
    print("ReAct JSON 鏍煎紡瑙ｆ瀽娴嬭瘯")
    print("=" * 60)

    for response in json_test_responses:
        print(f"\n杈撳叆: {response[:80]}...")
        action = executor._parse_llm_response(response)
        print(f"杈撳嚭: {action}")
        print(f"鏈夋晥: {action.is_valid()}")
        if action.thought:
            print(f"Thought: {action.thought}")

    # ========== 娴嬭瘯鏃ф牸寮忚В鏋愶紙鍚戝悗鍏煎锛?=========
    legacy_test_responses = [
        'Operation: "click" Widget: "Search"',
        'Sure! Based on the current page, I suggest you to:\nOperation: "click" Widget: "Login"',
        'Widget: "SearchBox" Input: "hello world"',
        'Widget: "search_src_text" Input: "test query"',
        'operation: long press widget: SubmitButton',
        'Operation: "back"',
        'Operation: "scroll_down"',
        'Operation: "go back"',  # 鍚屼箟璇嶆祴璇?
    ]

    print("\n" + "=" * 60)
    print("鏃ф牸寮忚В鏋愭祴璇曪紙鍚戝悗鍏煎锛?")
    print("=" * 60)

    for response in legacy_test_responses:
        print(f"\n杈撳叆: {response[:60]}...")
        action = executor._parse_llm_response(response)
        print(f"杈撳嚭: {action}")
        print(f"鏈夋晥: {action.is_valid()}")

    print("\n" + "=" * 60)
    print("宕╂簝妫€娴嬪姛鑳芥祴璇?")
    print("=" * 60)
    print("鎻愮ず: 瀹為檯宕╂簝妫€娴嬮渶瑕佽繛鎺ョ湡瀹炶澶?")
    print("execute_action 鏂规硶杩斿洖: (success, action)")
    print("宕╂簝妫€娴嬬粨鏋滃瓨鍌ㄥ湪: executor.last_crash_detected, executor.last_crash_log")
