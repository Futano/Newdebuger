"""
鍔熻兘鎰熺煡璁板繂绠＄悊妯″潡
瀹炵幇 GPTDroid 璁烘枃涓殑 Functionality-aware Memory 鏈哄埗
鐢ㄤ簬璁板綍娴嬭瘯鍘嗗彶骞剁敓鎴愯蹇嗙浉鍏崇殑鎻愮ず璇?

鏁版嵁缁撴瀯锛?
- Activities: 闈欐€佹暟鎹紝浠?Manifest 璇诲彇
- Functions: LLM 閫氳繃 Function Query 鎬荤粨寰楀埌鐨勮涔夊寲鍔熻兘
- Operation History: 杩愯鏃惰褰曠殑娴嬭瘯鎿嶄綔鍘嗗彶
"""

from typing import List, Dict, Optional
from collections import deque
from datetime import datetime
from .logger_config import memory_logger


class TestingSequenceMemorizer:
    """
    娴嬭瘯搴忓垪璁板繂鍣?

    缁熶竴绠＄悊娴嬭瘯杩囩▼涓殑鎵€鏈夎蹇嗘暟鎹細
    1. Activity 杩借釜锛堜粠 Manifest锛?
    2. Widget 杩借釜锛堣繍琛屾椂璁板綍锛?
    3. Function 杩借釜锛圠LM 鎬荤粨锛?
    4. 鎿嶄綔鍘嗗彶锛堟渶杩?姝ワ級

    閬靛惊 GPTDroid 璁烘枃鐨勮蹇嗘満鍒惰璁?
    """

    MAX_HISTORY_STEPS = 10

    def __init__(self):
        """鍒濆鍖栨祴璇曞簭鍒楄蹇嗗櫒"""
        # App 淇℃伅
        self.app_name: str = ""

        # Activity 杩借釜: {activity_name: {visits: int, status: str}}
        self.activity_info: Dict[str, Dict] = {}

        # Widget 杩借釜: {activity_name: {widget_id: visits}}
        self.widget_visits: Dict[str, Dict[str, int]] = {}

        # Function 杩借釜锛圠LM 鎬荤粨锛? {function_name: {visits: int, status: str}}
        self.explored_functions: Dict[str, Dict] = {}

        # 鎿嶄綔鍘嗗彶锛堟渶杩?姝ワ級
        self.operation_history: deque = deque(maxlen=self.MAX_HISTORY_STEPS)

        # 褰撳墠娴嬭瘯鍔熻兘
        self.current_function: Optional[str] = None
        self.current_function_status: Optional[str] = None

        # 姝ラ璁℃暟鍣?
        self.step_counter: int = 0

        # 涓婁竴姝ユ搷浣滅殑棰勬湡缁撴灉锛堢敤浜?Bug 妫€娴嬶級
        self.last_actual_result: Optional[str] = None

        # 褰撳墠椤甸潰鎻忚堪锛堢敤浜庤褰曟搷浣滃墠鐨勯〉闈㈢姸鎬侊級
        self.current_page_description: Optional[str] = None

        # 宸茬‘璁ゅ苟鐢熸垚鎶ュ憡鐨?Bug銆傚彧鐢ㄤ簬鍚庣画鍘婚噸锛屼笉鐢ㄤ簬娉勬紡鏈彂鐜?Bug銆?
        self.reported_bugs: List[Dict] = []

    # ==================== 閰嶇疆鏂规硶 ====================

    def set_app_name(self, app_name: str) -> None:
        """璁剧疆搴旂敤鍚嶇О"""
        self.app_name = app_name

    def register_activity(self, activity_name: str, status: str = "unvisited") -> None:
        """娉ㄥ唽 Activity锛堜粠 Manifest锛?"""
        if activity_name not in self.activity_info:
            self.activity_info[activity_name] = {"visits": 0, "status": status}

    def register_activities(self, activities: List[str]) -> None:
        """鎵归噺娉ㄥ唽 Activities"""
        for activity in activities:
            self.register_activity(activity)

    # ==================== 璁板綍鏂规硶 ====================

    def record_activity_visit(self, activity_name: str) -> None:
        """璁板綍 Activity 璁块棶"""
        memory_logger.info(f"Activity璁块棶: {activity_name}")
        self.register_activity(activity_name)
        self.activity_info[activity_name]["visits"] += 1
        self.activity_info[activity_name]["status"] = "visited"

    def record_widget_visit(self, activity_name: str, widget_identifier: str) -> None:
        """璁板綍 Widget 璁块棶"""
        memory_logger.debug(f"Widget璁块棶: {widget_identifier} @ {activity_name}")
        if activity_name not in self.widget_visits:
            self.widget_visits[activity_name] = {}
        self.widget_visits[activity_name][widget_identifier] = \
            self.widget_visits[activity_name].get(widget_identifier, 0) + 1

    def record_operation(
        self,
        activity_name: str,
        widgets_tested: List[Dict] = None,
        operation: str = None,
        target_widget: str = None,
        success: bool = True,
        page_description: str = None,
        visual_description: str = None,
        ui_state_before: Dict = None,
        ui_state_after: Dict = None,
        action_phase: str = None,
        transient_transition: str = None,
        back_effect: str = None,
        function_phase: str = None,
        function_end: bool = False,
        verification_target: str = None
    ) -> None:
        """
        璁板綍鎿嶄綔鍘嗗彶

        Args:
            activity_name: Activity 鍚嶇О
            widgets_tested: 宸叉祴璇曠殑鎺т欢鍒楄〃 [{name, visits}]锛堝彲閫夛級
            operation: 鎿嶄綔绫诲瀷
            target_widget: 鐩爣鎺т欢
            success: 鏄惁鎴愬姛
            page_description: 椤甸潰鎻忚堪锛堟潵鑷?LLM 鐨?Page_Description 瀛楁锛?
            visual_description: 瑙嗚鎻忚堪锛堝吋瀹规棫瀛楁锛?
            ui_state_before: 鎿嶄綔鍓嶇粨鏋勫寲 UI 鐘舵€?
            ui_state_after: 鎿嶄綔鍚庣粨鏋勫寲 UI 鐘舵€?
            action_phase: 鎿嶄綔璇箟闃舵锛堝 open_transient/select_transient锛?
            transient_transition: 涓存椂 UI 灞傚彉鍖栵紙濡?transient_opened锛?
            function_phase: 褰撳墠鍔熻兘娈甸樁娈?
            function_end: Explorer 鏄惁璁や负褰撳墠鍔熻兘娈靛凡缁撴潫
            verification_target: 鍚庣画搴旈獙璇佺殑缁撴灉椤?鍒楄〃椤?璇︽儏椤电洰鏍?
        """
        self.step_counter += 1

        # 濡傛灉娌℃湁鎻愪緵 widgets_tested锛岃嚜鍔ㄦ瀯寤?
        if widgets_tested is None:
            widgets_tested = self.get_widgets_tested(activity_name)

        # 浼樺厛浣跨敤 page_description锛屽惁鍒欎娇鐢?visual_description
        description = page_description or visual_description or self.current_page_description

        # 娣诲姞鍒版搷浣滃巻鍙?
        self.operation_history.appendleft({
            "step_index": self.step_counter,
            "activity_name": activity_name,
            "function_name": self.current_function,
            "function_status": self.current_function_status,
            "widgets_tested": widgets_tested or [],
            "operation": operation or "unknown",
            "target_widget": target_widget or "unknown",
            "success": success,
            "page_description": description,
            "visual_description": description,  # 淇濇寔鍏煎鎬?
            "ui_state_before": ui_state_before or {},
            "ui_state_after": ui_state_after or {},
            "action_phase": action_phase or "",
            "transient_transition": transient_transition or "",
            "back_effect": back_effect or "",
            "function_phase": function_phase or "",
            "function_end": bool(function_end),
            "verification_target": verification_target or ""
        })

        # 閲嶇疆褰撳墠椤甸潰鎻忚堪锛堝凡琚娇鐢級
        self.current_page_description = None

        # 鍚屾椂鏇存柊 Activity 鍜?Widget 璁块棶
        if activity_name:
            self.record_activity_visit(activity_name)
        visited_widget_names = set()
        if target_widget:
            visited_widget_names.add(target_widget)
        for widget in widgets_tested or []:
            if isinstance(widget, dict) and widget.get("name"):
                visited_widget_names.add(widget.get("name"))

        for visited_widget_name in visited_widget_names:
            self.record_widget_visit(activity_name, visited_widget_name)

        status_str = "鎴愬姛" if success else "澶辫触"
        print(f"[璁板繂鏇存柊] 姝ラ {self.step_counter}: {operation} '{target_widget}' @ {activity_name} [{status_str}]")

    # 鍏煎鏃ф柟娉曞悕
    def update_step(
        self,
        activity_name: str,
        operation: str,
        widget_name: str,
        target_function: Optional[str] = None,
        success: bool = True
    ) -> None:
        """
        鏇存柊娴嬭瘯姝ラ璁板綍锛堝吋瀹规棫鎺ュ彛锛?

        Args:
            activity_name: 褰撳墠 Activity 鍚嶇О
            operation: 鎵ц鐨勬搷浣滅被鍨?
            widget_name: 鎿嶄綔鐨勭洰鏍囨帶浠跺悕绉?
            target_function: 璇ユ搷浣滃搴旂殑鍔熻兘鍚嶇О锛堝彲閫夛級
            success: 鎿嶄綔鏄惁鎴愬姛
        """
        self.record_operation(
            activity_name=activity_name,
            operation=operation,
            target_widget=widget_name,
            success=success
        )

        # 鏇存柊褰撳墠鍔熻兘
        if target_function:
            self.update_function(target_function, "testing")

    def update_function(self, function_name: str, status: str = "testing") -> None:
        """
        鏇存柊鎴栨坊鍔犲姛鑳斤紙鏉ヨ嚜 LLM 鎬荤粨锛?

        Args:
            function_name: 鍔熻兘鍚嶇О
            status: 鐘舵€?("testing" 鎴?"tested")
        """
        memory_logger.info(f"鍔熻兘鐘舵€佹洿鏂? {function_name} -> {status}")
        if function_name not in self.explored_functions:
            self.explored_functions[function_name] = {"visits": 0, "status": status}

        self.explored_functions[function_name]["visits"] += 1
        self.explored_functions[function_name]["status"] = status

        # 鏇存柊褰撳墠鍔熻兘
        self.current_function = function_name
        self.current_function_status = status

    def infer_function_from_activity(self, activity_name: str) -> Optional[str]:
        """
        浠?Activity 鍚嶇О鎺ㄦ柇鍔熻兘锛堝綋 LLM 鏈繑鍥炴椂鐨勫悗澶囨満鍒讹級

        Args:
            activity_name: Activity 鍚嶇О

        Returns:
            鎺ㄦ柇鐨勫姛鑳藉悕绉?
        """
        # Activity 鍚嶇О鍒板姛鑳界殑鏄犲皠瑙勫垯
        activity_to_function = {
            "login": "Login",
            "signin": "Login",
            "sign_in": "Login",
            "register": "Register",
            "signup": "Register",
            "sign_up": "Register",
            "search": "Search",
            "settings": "Settings",
            "profile": "Profile",
            "home": "Home",
            "main": "Main",
            "splash": "Splash",
            "menu": "Menu",
            "detail": "View Details",
            "result": "View Results",
            "list": "List View",
            "add": "Add Item",
            "edit": "Edit Item",
            "delete": "Delete Item",
            "save": "Save",
            "submit": "Submit",
            "cancel": "Cancel",
            "back": "Navigation",
        }

        # 杞崲涓哄皬鍐欒繘琛屽尮閰?
        activity_lower = activity_name.lower()

        # 绮剧‘鍖归厤
        if activity_lower in activity_to_function:
            return activity_to_function[activity_lower]

        # 閮ㄥ垎鍖归厤
        for key, value in activity_to_function.items():
            if key in activity_lower:
                return value

        # 榛樿杩斿洖 Activity 鍚嶇О浣滀负鍔熻兘
        return activity_name

    def set_current_function(self, function_name: str, status: str = "testing") -> None:
        """璁剧疆褰撳墠娴嬭瘯鍔熻兘"""
        self.current_function = function_name
        self.current_function_status = status

    def set_current_page_description(self, description: str) -> None:
        """
        璁剧疆褰撳墠椤甸潰鎻忚堪锛堟搷浣滃墠璋冪敤锛?

        Args:
            description: 椤甸潰鎻忚堪锛堟潵鑷?LLM 鐨?Thought 鎴栨帶浠舵憳瑕侊級
        """
        self.current_page_description = description

    def generate_page_summary(self, activity_name: str, widgets: List[Dict] = None) -> str:
        """
        鏍规嵁褰撳墠椤甸潰淇℃伅鐢熸垚椤甸潰鎽樿

        Args:
            activity_name: 褰撳墠 Activity 鍚嶇О
            widgets: 褰撳墠椤甸潰鐨勬帶浠跺垪琛紙鍙€夛級

        Returns:
            椤甸潰鎽樿瀛楃涓?
        """
        parts = [f"椤甸潰: {activity_name}"]

        if widgets:
            # 缁熻鎺т欢绫诲瀷
            type_counts = {}
            key_widgets = []
            for widget in widgets:
                category = widget.get("category", "Unknown")
                type_counts[category] = type_counts.get(category, 0) + 1

                # 璁板綍鍏抽敭鎺т欢锛堝彲浜や簰鐨勶級
                if category in ["Button", "EditText"]:
                    text = widget.get("text", "")
                    if text and len(text) < 20:
                        key_widgets.append(f"{text}({category})")

            # 娣诲姞鎺т欢缁熻
            type_str = ", ".join([f"{k}:{v}" for k, v in type_counts.items()])
            parts.append(f"鎺т欢: {type_str}")

            # 娣诲姞鍏抽敭鎺т欢锛堟渶澶?涓級
            if key_widgets:
                parts.append(f"鍏抽敭鎺т欢: {', '.join(key_widgets[:5])}")

        return " | ".join(parts)

    # ==================== 棰勬湡缁撴灉绠＄悊锛圔ug 妫€娴嬶級====================

    def update_actual_result(self, actual_result: str) -> None:
        """
        鏇存柊瀹為檯缁撴灉锛堢敤浜庝笌棰勬湡缁撴灉瀵规瘮锛?

        Args:
            actual_result: 瀹為檯鐨勬搷浣滅粨鏋滄弿杩?
        """
        self.last_actual_result = actual_result
        print(f"[瀹為檯缁撴灉] 鏇存柊: {actual_result}")

    def get_actual_result(self) -> Optional[str]:
        """鑾峰彇涓婁竴姝ユ搷浣滅殑瀹為檯缁撴灉"""
        return self.last_actual_result

    def has_pending_verification(self) -> bool:
        """Return whether there is a pending verification target."""
        return False

    def clear_verification_state(self) -> None:
        """Clear result tracking state."""
        self.last_actual_result = None

    # ==================== 鍋囬槼鎬ф渚嬭褰曪紙鐩戠鑰呭姛鑳斤級====================

    def record_false_positive_case(
        self,
        bug_description: str,
        reason: str,
        confidence: float
    ) -> None:
        """
        璁板綍鍋囬槼鎬ф渚嬩緵瀛︿範

        褰撶洃绠¤€呭垽瀹?LLM 鎶ュ憡鐨?Bug 涓哄亣闃虫€ф椂锛岃褰曟妗堜緥浠ヤ緵鍚庣画鍒嗘瀽銆?

        Args:
            bug_description: 鍘?Bug 鎻忚堪
            reason: 鍋囬槼鎬у垽瀹氬師鍥?
            confidence: 鐩戠鑰呭垽瀹氱疆淇″害
        """
        if not hasattr(self, 'false_positive_cases'):
            self.false_positive_cases = []

        self.false_positive_cases.append({
            'step': self.get_step_count(),
            'bug_description': bug_description,
            'reason': reason,
            'confidence': confidence,
            'timestamp': datetime.now().timestamp()
        })

        memory_logger.info(f"鍋囬槼鎬ф渚嬪凡璁板綍锛?{bug_description[:50]}...")
        print(f"[鍋囬槼鎬ц褰昡 姝ラ {self.get_step_count()}: {bug_description[:50]}...")

    def get_false_positive_cases(self) -> List[Dict]:
        """鑾峰彇鎵€鏈夊亣闃虫€ф渚?"""
        return getattr(self, 'false_positive_cases', [])

    # ==================== 宸叉姤鍛?Bug 鍘婚噸璁板綍 ====================

    def record_reported_bug(
        self,
        bug_id: str,
        source: str,
        category: str,
        severity: str,
        description: str,
        activity: str = "",
        operation: str = "",
        widget: str = "",
        confidence: Optional[float] = None
    ) -> None:
        """璁板綍宸茬粡纭骞朵繚瀛樻姤鍛婄殑 Bug锛岀敤浜庡悗缁彁绀鸿瘝鍘婚噸銆?"""
        if not bug_id:
            return

        if any(item.get("bug_id") == bug_id for item in self.reported_bugs):
            return

        self.reported_bugs.append({
            "bug_id": bug_id,
            "source": source or "unknown",
            "category": category or "unknown",
            "severity": severity or "Unknown",
            "description": description or "",
            "activity": activity or "",
            "operation": operation or "",
            "widget": widget or "",
            "confidence": confidence,
            "step": self.get_step_count(),
            "timestamp": datetime.now().isoformat(),
        })

        memory_logger.info(f"宸叉姤鍛夿ug璁板綍: {bug_id} [{severity}] {description[:60]}...")
        print(f"[Bug鍘婚噸] 宸茶褰曟姤鍛? {bug_id} [{severity}]")

    def get_reported_bugs(self, limit: int = 8) -> List[Dict]:
        """鑾峰彇鏈€杩戝凡鎶ュ憡 Bug 鎽樿锛屼緵鎻愮ず璇嶉伩鍏嶉噸澶嶆姤鍛娿€?"""
        if limit <= 0:
            return []
        return list(self.reported_bugs[-limit:])

    # ==================== 鏁版嵁鑾峰彇鏂规硶 ====================

    def get_activities_info(self) -> List[Dict]:
        """鑾峰彇 Activities 淇℃伅鍒楄〃"""
        return [
            {"name": name, "visit_time": info.get("visits", 0), "status": info.get("status", "unvisited")}
            for name, info in self.activity_info.items()
        ]

    def get_covered_activities(self) -> List[Dict]:
        """鑾峰彇鎵€鏈?Activities 淇℃伅锛堝寘鍚湭璁块棶鐨勶級

        娉ㄦ剰锛氭鏂规硶杩斿洖鎵€鏈夋敞鍐岀殑 Activity锛屼笉浠呬粎鏄凡璁块棶鐨勩€?
        鐢ㄤ簬鍦ㄦ彁绀鸿瘝涓樉绀哄畬鏁寸殑 Activity 瑕嗙洊鎯呭喌銆?
        """
        return [
            {"name": name, "visit_time": info.get("visits", 0), "status": info.get("status", "unvisited")}
            for name, info in self.activity_info.items()
        ]

    def get_explored_functions(self) -> Dict[str, Dict]:
        """鑾峰彇宸叉帰绱㈢殑鍔熻兘"""
        return self.explored_functions.copy()

    def get_operation_history(self, newest_first: bool = True) -> List[Dict]:
        """鑾峰彇鎿嶄綔鍘嗗彶鍒楄〃銆?

        Args:
            newest_first: True 杩斿洖鏈€鏂版搷浣滃湪鍓嶏紱False 杩斿洖鐪熷疄鏃堕棿椤哄簭銆?
        """
        history = list(self.operation_history)
        return history if newest_first else list(reversed(history))

    def get_operation_history_chronological(self) -> List[Dict]:
        """鑾峰彇鎸夌湡瀹炴墽琛屾椂闂存帓搴忕殑鎿嶄綔鍘嗗彶銆?"""
        return self.get_operation_history(newest_first=False)

    def get_latest_operation(self) -> Optional[Dict]:
        """鑾峰彇鏈€杩戜竴娆℃搷浣溿€?"""
        return self.operation_history[0] if self.operation_history else None

    def get_widget_visits(self, activity_name: str) -> Dict[str, int]:
        """鑾峰彇鎸囧畾 Activity 鐨?Widget 璁块棶璁板綍"""
        return self.widget_visits.get(activity_name, {})

    def get_widgets_tested(self, activity_name: str) -> List[Dict]:
        """鑾峰彇鎸囧畾 Activity 宸叉祴璇曠殑 Widgets"""
        widget_visits = self.get_widget_visits(activity_name)
        return [{"name": name, "visits": visits} for name, visits in widget_visits.items()]

    def is_first_activity_visit(self, activity_name: str) -> bool:
        """
        鍒ゆ柇 Activity 鏄惁棣栨璁块棶

        鐢ㄤ簬娓愯繘寮忔姭闇茬瓥鐣ワ細棣栨璁块棶鏃朵笉鏄剧ず widget 鍘嗗彶璁块棶淇℃伅

        Args:
            activity_name: Activity 鍚嶇О

        Returns:
            True: 棣栨璁块棶锛坴isits == 0锛?
            False: 杩斿洖璁块棶锛坴isits > 0锛?
        """
        if activity_name not in self.activity_info:
            return True  # 鏈敞鍐岀殑 Activity 瑙嗕负棣栨
        return self.activity_info[activity_name].get("visits", 0) == 0

    # ==================== 缁熻鏂规硶 ====================

    def get_step_count(self) -> int:
        """鑾峰彇娴嬭瘯姝ラ鏁?"""
        return self.step_counter

    def get_current_function(self) -> Optional[str]:
        """鑾峰彇褰撳墠娴嬭瘯鍔熻兘"""
        return self.current_function

    def get_stats(self) -> Dict:
        """鑾峰彇缁熻淇℃伅"""
        return {
            "app_name": self.app_name,
            "total_activities": len(self.activity_info),
            "visited_activities": sum(1 for a in self.activity_info.values() if a.get("status") == "visited"),
            "total_functions": len(self.explored_functions),
            "tested_functions": sum(1 for f in self.explored_functions.values() if f.get("status") == "tested"),
            "total_steps": self.step_counter,
            "current_function": self.current_function
        }

    def get_memory_prompt(self) -> str:
        """
        鐢熸垚璁板繂鎻愮ず璇嶏紙鐢ㄤ簬 Bug 鎶ュ憡锛?

        Returns:
            鏍煎紡鍖栫殑娴嬭瘯鍘嗗彶瀛楃涓?
        """
        lines = ["娴嬭瘯鍘嗗彶璁板綍:", ""]

        # 娣诲姞宸叉帰绱㈠姛鑳?
        if self.explored_functions:
            lines.append("宸叉帰绱㈠姛鑳?")
            for name, info in self.explored_functions.items():
                visits = info.get("visits", 0)
                status = info.get("status", "unknown")
                lines.append(f"  - {name}: {visits}娆¤闂? 鐘舵€? {status}")
            lines.append("")

        # 娣诲姞鎿嶄綔鍘嗗彶
        if self.operation_history:
            lines.append("鏈€杩戞搷浣滃巻鍙?")
            for i, entry in enumerate(self.get_operation_history_chronological(), 1):
                activity = entry.get("activity_name", "Unknown")
                operation = entry.get("operation", "Unknown")
                target = entry.get("target_widget", "Unknown")
                lines.append(f"  {i}. [{activity}] {operation} -> {target}")
            lines.append("")

        # 娣诲姞 Activity 璁块棶鎯呭喌
        if self.activity_info:
            lines.append("Activity璁块棶鎯呭喌:")
            for name, info in self.activity_info.items():
                visits = info.get("visits", 0)
                status = info.get("status", "unvisited")
                lines.append(f"  - {name}: {visits}娆¤闂? 鐘舵€? {status}")

        return "\n".join(lines) if lines else "[鏃犳祴璇曞巻鍙茶褰昡"

    # ==================== 娓呯悊鏂规硶 ====================

    def clear_memory(self) -> None:
        """娓呯┖鎵€鏈夎蹇嗚褰?"""
        self.activity_info.clear()
        self.widget_visits.clear()
        self.explored_functions.clear()
        self.operation_history.clear()
        self.current_function = None
        self.current_function_status = None
        self.step_counter = 0
        self.last_actual_result = None
        self.current_page_description = None
        self.reported_bugs.clear()
        print("[璁板繂娓呯┖] 鎵€鏈夋祴璇曞巻鍙插凡娓呴櫎")

    def clear_memory(self) -> None:
        """娓呯┖鎵€鏈夎蹇嗚褰?"""
        self.activity_info.clear()
        self.widget_visits.clear()
        self.explored_functions.clear()
        self.operation_history.clear()
        self.current_function = None
        self.current_function_status = None
        self.step_counter = 0
        self.last_actual_result = None
        self.current_page_description = None
        self.reported_bugs.clear()
        print("[璁板繂娓呯┖] 鎵€鏈夋祴璇曞巻鍙插凡娓呴櫎")


# 娴嬭瘯鍏ュ彛
if __name__ == "__main__":
    memory = TestingSequenceMemorizer()

    # 璁剧疆 App
    memory.set_app_name("TestApp")

    # 娉ㄥ唽 Activities
    memory.register_activities(["MainActivity", "SearchActivity", "SettingsActivity"])

    # 鏇存柊鍔熻兘
    memory.update_function("Login", "tested")
    memory.update_function("Search", "testing")

    # 璁板綍鎿嶄綔
    memory.record_operation("MainActivity", [{"name": "Search", "visits": 1}], "Click", "Search")
    memory.record_operation("SearchActivity", [{"name": "SearchBox", "visits": 1}], "Input", "SearchBox")

    # 鎵撳嵃缁熻
    print("\n" + "=" * 60)
    print("缁熻淇℃伅:")
    print("=" * 60)
    print(memory.get_stats())

    print("\nActivities Info:")
    print(memory.get_activities_info())

    print("\nCovered Activities:")
    print(memory.get_covered_activities())

    print("\nExplored Functions:")
    print(memory.get_explored_functions())

    print("\nOperation History:")
    for op in memory.get_operation_history():
        print(f"  {op}")
