"""
Prompt Builder Module
Generates structured prompts for LLM-based Android GUI testing
Supports three-phase prompt building: Initial, Test, and Feedback

依赖 TestingSequenceMemorizer 作为唯一数据源
"""

from typing import List, Dict, Optional, TYPE_CHECKING

# Handle both relative and absolute imports
try:
    from .prompt_templates import (
        GUIContextTemplate,
        FunctionMemoryTemplate,
        TestHistoryTemplate,
        SystemPromptTemplate,
        UserContext  # NEW: 用户上下文
    )
    from .memory_manager import TestingSequenceMemorizer
except ImportError:
    from prompt_templates import (
        GUIContextTemplate,
        FunctionMemoryTemplate,
        TestHistoryTemplate,
        SystemPromptTemplate,
        UserContext  # NEW: 用户上下文
    )
    from memory_manager import TestingSequenceMemorizer


class PromptGenerator:
    """
    Prompt Generator for Android GUI Testing

    使用 TestingSequenceMemorizer 作为唯一数据源
    生成结构化提示词，遵循新的模板系统：
    - GUIContext[1,2,3,4,5,6]: App, Page, Widget, Operation Questions, Feedback
    - FunctionMemory[1,2,3,4]: Explored Function, Covered Activities, History, Function Query

    支持三阶段提示词构建：
    - Initial phase: GUIContext[1,2,3,4,5] + FunctionMemory[1,2,3,4]
    - Test phase (success): Success message + GUIContext[2,3,4,5] + FunctionMemory[1,2,3,4]
    - Feedback phase (failure): GUIContext[6] + GUIContext[3,4,5] + FunctionMemory[3,4]
    """

    def __init__(
        self,
        memory_manager: Optional[TestingSequenceMemorizer] = None
    ):
        """
        初始化 Prompt Generator

        Args:
            memory_manager: 记忆管理器实例（唯一数据源）
        """
        # 使用传入的 memory_manager 或创建新的
        self.memory = memory_manager or TestingSequenceMemorizer()
        # 用户上下文信息（测试目标、已知功能等）
        self.user_context: Optional[UserContext] = None
        # 当前页面的结构化 UI 状态事实（临时层/下拉框/弹窗/键盘等）
        self.ui_state_section: str = ""
        # 当前功能案卷摘要，供 Explorer 续写行为链
        self.behavior_dossier_section: str = ""

    # ==================== 配置方法 ====================

    def set_app_name(self, app_name: str) -> None:
        """设置应用名称"""
        self.memory.set_app_name(app_name)

    def set_user_context(self, user_context: UserContext) -> None:
        """
        设置用户上下文信息

        Args:
            user_context: 用户输入的测试上下文（目标、功能、注意事项）
        """
        self.user_context = user_context
        # 同步应用名称
        if user_context.app_name:
            self.memory.set_app_name(user_context.app_name)
        print(f"[提示词] 已设置用户上下文: {user_context.app_name}")

    def set_ui_state_section(self, section: str) -> None:
        """设置当前页面的结构化 UI 状态说明。"""
        self.ui_state_section = section or ""

    def set_behavior_dossier_section(self, section: str) -> None:
        """设置当前功能案卷摘要。"""
        self.behavior_dossier_section = section or ""

    def register_activity(self, activity_name: str, status: str = "unvisited") -> None:
        """注册 Activity"""
        self.memory.register_activity(activity_name, status)

    # ==================== 委托到 memory_manager 的方法 ====================

    def record_activity_visit(self, activity_name: str) -> None:
        """记录 Activity 访问"""
        self.memory.record_activity_visit(activity_name)

    def record_widget_visit(self, activity_name: str, widget_identifier: str) -> None:
        """记录 Widget 访问"""
        self.memory.record_widget_visit(activity_name, widget_identifier)

    def record_operation(
        self,
        activity_name: str,
        widgets_tested: List[Dict],
        operation: str,
        target_widget: str,
        success: bool = True
    ) -> None:
        """记录操作"""
        self.memory.record_operation(activity_name, widgets_tested, operation, target_widget, success)

    def update_function(self, function_name: str, status: str = "testing") -> None:
        """更新功能状态"""
        self.memory.update_function(function_name, status)

    def set_current_function(self, function_name: str, status: str = "testing") -> None:
        """设置当前测试功能"""
        self.memory.set_current_function(function_name, status)

    # ==================== Widget 处理 ====================

    @staticmethod
    def _clip_text(text: str, limit: int = 220) -> str:
        """Compact long prompt fragments without changing widget identity."""
        if text is None:
            return ""
        compact = " ".join(str(text).split())
        if len(compact) <= limit:
            return compact
        return compact[: max(0, limit - 3)].rstrip() + "..."

    def _get_widget_identifier(self, widget: Dict, edittext_index: Optional[int] = None) -> Optional[str]:
        """获取 Widget 标识符"""
        class_name = widget.get("class", "")

        # For EditText controls, never use text as the identity. It is usually the
        # current input value, so using it creates a new "widget" after every edit.
        if "EditText" in class_name:
            content_desc = widget.get("content_desc", "")
            if content_desc and content_desc.strip():
                return content_desc.strip()

            resource_id = widget.get("resource_id", "")
            if resource_id:
                return resource_id.split("/")[-1] if "/" in resource_id else resource_id

            if edittext_index:
                return f"Text Input {edittext_index}"
            return "Text Input"

        # For other widgets, prioritize text (more readable/stable for Buttons, TextViews, etc.)
        text = widget.get("text", "")
        if text and text.strip():
            return text.strip()

        resource_id = widget.get("resource_id", "")
        if resource_id:
            return resource_id.split("/")[-1] if "/" in resource_id else resource_id

        return None

    def _process_widgets_for_template(self, widgets: List[Dict]) -> List[Dict]:
        """
        处理 Widgets 用于模板渲染

        改进：对于缺乏唯一标识的控件（如 CheckBox/Switch/RadioButton），
        使用 nearby_label 提取附近文本标签帮助 LLM 区分
        """
        if not widgets:
            return []

        processed = []
        edittext_index = 0
        for widget in widgets:
            class_name = widget.get("class", "")
            if "EditText" in class_name:
                edittext_index += 1

            widget_id = self._get_widget_identifier(widget, edittext_index if "EditText" in class_name else None)
            if not widget_id:
                continue

            category = class_name.split(".")[-1] if class_name else "Widget"

            processed_widget = {
                "text": widget_id,
                "resource_id": widget.get("resource_id", ""),
                "category": category,
                "activity": widget.get("activity", "")
            }

            # For EditText, include the original text (hint or current content)
            if "EditText" in class_name:
                original_text = widget.get("text", "")
                if original_text and original_text.strip():
                    processed_widget["original_text"] = self._clip_text(original_text, 120)
                # 新增：包含 content_desc 用于区分同 resource-id 的字段
                # 例如 AnkiDroid NoteEditorActivity 中 Front/Back 字段有相同的 edit_text resource-id
                content_desc = widget.get("content_desc", "")
                if content_desc and content_desc.strip():
                    processed_widget["content_desc"] = content_desc.strip()

            # ========== 新增：为 CheckBox/Switch 等控件添加 nearby_label ==========
            # 这些控件通常没有自己的文本标识，需要用相邻的 TextView 作为标签
            if category in ["CheckBox", "Switch", "RadioButton", "ToggleButton"]:
                nearby_label = self._extract_nearby_label(widget)
                if nearby_label:
                    processed_widget["nearby_label"] = nearby_label

            # ========== NEW: 添加 bounds 位置信息（用于视觉定位）==========
            bounds = widget.get("bounds", "")
            if bounds:
                processed_widget["bounds"] = bounds

            processed.append(processed_widget)

        return processed

    def _extract_nearby_label(self, widget: Dict) -> str:
        """
        从控件的兄弟节点中提取文本标签

        CheckBox/Switch 通常旁边有一个 TextView 描述其功能
        例如：
          - TextView: "Enable photos for places"
          - CheckBox: (checked)

        Args:
            widget: 控件信息，包含 siblings 数据

        Returns:
            找到的标签文本，未找到返回空字符串
        """
        siblings = widget.get("siblings", [])
        if not siblings:
            # 尝试从 parent 获取信息
            parent = widget.get("parent", {})
            if parent:
                parent_text = parent.get("text", "")
                if parent_text and len(parent_text) > 3:
                    return parent_text
            return ""

        # 优先查找前面的兄弟节点（标签通常在控件前面）
        for sibling in siblings:
            if sibling.get("position") == "before":
                sib_text = sibling.get("text", "")
                sib_class = sibling.get("class", "")
                # 标签通常是 TextView 且有较长的文本
                if sib_text and len(sib_text) > 3 and sib_class in ["TextView", ""]:
                    return sib_text

        # 如果前面没有，查找后面的兄弟节点
        for sibling in siblings:
            if sibling.get("position") == "after":
                sib_text = sibling.get("text", "")
                sib_class = sibling.get("class", "")
                if sib_text and len(sib_text) > 3 and sib_class in ["TextView", ""]:
                    return sib_text

        return ""

    # ==================== 提示词构建 ====================

    def _build_revisit_guidance(self, activity_name: str) -> str:
        """Warn the model when it is spending too many steps on one Activity."""
        visits = self.memory.activity_info.get(activity_name, {}).get("visits", 0)
        if visits < 8:
            return ""
        return (
            f"Exploration note: {activity_name} has already been visited {visits} times. "
            "If the visible controls are already covered, prefer completing the main flow, "
            "opening another page, or using back instead of repeating input validation."
        )

    def build_system_prompt(self) -> str:
        """构建系统提示词（包含用户上下文信息）"""
        return SystemPromptTemplate.get_system_prompt(
            app_name=self.memory.app_name,
            user_context=self.user_context,
            reported_bugs=self.memory.get_reported_bugs()
        )

    def build_test_prompt(
        self,
        activity_or_widgets,
        widgets_or_activity=None,
        memorizer=None,
        screen_width: int = 1080,  # NEW: 屏幕宽度
        screen_height: int = 1920  # NEW: 屏幕高度
    ) -> str:
        """
        构建 Test Prompt - 支持新旧签名

        新签名: build_test_prompt(widgets, activity_name, screen_width, screen_height)
        旧签名: build_test_prompt(activity_name, widgets, memorizer)
        """
        if isinstance(activity_or_widgets, str):
            # 旧签名
            activity_name = activity_or_widgets
            widgets = widgets_or_activity
            return self._build_initial_prompt_internal(widgets, activity_name, screen_width, screen_height)
        else:
            # 新签名
            widgets = activity_or_widgets
            activity_name = widgets_or_activity
            return self._build_test_prompt_internal(widgets, activity_name, screen_width, screen_height)

    def build_initial_prompt(
        self,
        widgets: List[Dict],
        activity_name: str,
        app_name: Optional[str] = None,
        screen_width: int = 1080,  # NEW: 屏幕宽度
        screen_height: int = 1920  # NEW: 屏幕高度
    ) -> str:
        """
        构建初始阶段提示词

        组合: GUIContext[1,2,3,4,5] + FunctionMemory[1,2,3,4]
        """
        if app_name:
            self.memory.set_app_name(app_name)
        return self._build_initial_prompt_internal(widgets, activity_name, screen_width, screen_height)

    def _build_initial_prompt_internal(self, widgets: List[Dict], activity_name: str, screen_width: int = 1080, screen_height: int = 1920) -> str:
        """内部: 构建初始阶段提示词"""
        self.memory.register_activity(activity_name)

        processed_widgets = self._process_widgets_for_template(widgets)

        # 渐进式披露：首次访问不显示 widget_visits
        is_first_visit = self.memory.is_first_activity_visit(activity_name)
        if is_first_visit:
            widget_visits = {}  # 首次访问：传入空字典
        else:
            widget_visits = self.memory.get_widget_visits(activity_name)  # 返回访问：显示历史

        parts = [
            # GUIContext[1,2,3]
            GUIContextTemplate.app_info(self.memory.app_name, self.memory.get_activities_info()),
            GUIContextTemplate.page_info(activity_name),
            self.ui_state_section,
            self.behavior_dossier_section,
            GUIContextTemplate.widget_info(processed_widgets, widget_visits, screen_width, screen_height, is_first_visit),  # 渐进式披露
            # GUIContext[4,5]
            GUIContextTemplate.action_operation_question(),
            GUIContextTemplate.input_operation_question(),
            # FunctionMemory[1,2,3,4]
            FunctionMemoryTemplate.explored_function(self.memory.get_explored_functions()),
            FunctionMemoryTemplate.covered_activities(self.memory.get_covered_activities()),
        ]

        revisit_guidance = self._build_revisit_guidance(activity_name)
        if revisit_guidance:
            parts.insert(1, revisit_guidance)

        return "\n\n".join(parts)

    def _build_test_prompt_internal(self, widgets: List[Dict], activity_name: str, screen_width: int = 1080, screen_height: int = 1920) -> str:
        """内部: 构建测试阶段提示词（成功后）"""
        self.memory.register_activity(activity_name)

        processed_widgets = self._process_widgets_for_template(widgets)

        # 渐进式披露：首次访问不显示 widget_visits
        is_first_visit = self.memory.is_first_activity_visit(activity_name)
        if is_first_visit:
            widget_visits = {}  # 首次访问：传入空字典
        else:
            widget_visits = self.memory.get_widget_visits(activity_name)  # 返回访问：显示历史

        parts = [
            "We successfully did the above operation.",
            # GUIContext[2,3]
            GUIContextTemplate.page_info(activity_name),
            self.ui_state_section,
            self.behavior_dossier_section,
            GUIContextTemplate.widget_info(processed_widgets, widget_visits, screen_width, screen_height, is_first_visit),  # 渐进式披露
            # GUIContext[4,5]
            GUIContextTemplate.action_operation_question(),
            GUIContextTemplate.input_operation_question(),
            # FunctionMemory[1,2,3,4]
            FunctionMemoryTemplate.explored_function(self.memory.get_explored_functions()),
            FunctionMemoryTemplate.covered_activities(self.memory.get_covered_activities()),
        ]

        revisit_guidance = self._build_revisit_guidance(activity_name)
        if revisit_guidance:
            parts.insert(1, revisit_guidance)

        return "\n\n".join(parts)

    def build_feedback_prompt(
        self,
        widgets: List[Dict],
        activity_name: str,
        failed_widget: str,
        screen_width: int = 1080,  # NEW: 屏幕宽度
        screen_height: int = 1920  # NEW: 屏幕高度
    ) -> str:
        """
        构建反馈阶段提示词（失败后）

        组合: GUIContext[6] + GUIContext[3,4,5] + FunctionMemory[3,4]
        """
        self.memory.register_activity(activity_name)

        processed_widgets = self._process_widgets_for_template(widgets)

        # 渐进式披露：首次访问不显示 widget_visits
        is_first_visit = self.memory.is_first_activity_visit(activity_name)
        if is_first_visit:
            widget_visits = {}  # 首次访问：传入空字典
        else:
            widget_visits = self.memory.get_widget_visits(activity_name)  # 返回访问：显示历史

        parts = [
            # GUIContext[6]
            GUIContextTemplate.testing_feedback(failed_widget),
            self.ui_state_section,
            self.behavior_dossier_section,
            # GUIContext[3]
            GUIContextTemplate.widget_info(processed_widgets, widget_visits, screen_width, screen_height, is_first_visit),  # 渐进式披露
            # GUIContext[4,5]
            GUIContextTemplate.action_operation_question(),
            GUIContextTemplate.input_operation_question(),
            # FunctionMemory[3,4]
        ]

        revisit_guidance = self._build_revisit_guidance(activity_name)
        if revisit_guidance:
            parts.insert(1, revisit_guidance)

        return "\n\n".join(parts)

    def build_external_redirect_prompt(
        self,
        widgets: List[Dict],
        activity_name: str,
        redirect_package: str,
        screen_width: int = 1080,  # NEW: 屏幕宽度
        screen_height: int = 1920  # NEW: 屏幕高度
    ) -> str:
        """
        构建外部跳转反馈提示词

        当操作触发了外部应用跳转时，告知 LLM 并引导其继续测试目标应用。

        Args:
            widgets: 当前控件列表
            activity_name: 当前 Activity 名称
            redirect_package: 跳转到的外部应用包名

        Returns:
            外部跳转反馈提示词
        """
        self.memory.register_activity(activity_name)

        processed_widgets = self._process_widgets_for_template(widgets)

        # 渐进式披露：首次访问不显示 widget_visits
        is_first_visit = self.memory.is_first_activity_visit(activity_name)
        if is_first_visit:
            widget_visits = {}  # 首次访问：传入空字典
        else:
            widget_visits = self.memory.get_widget_visits(activity_name)  # 返回访问：显示历史

        redirect_feedback = f"""**External Redirect Detected!**

The previous operation triggered an external app redirect:
- Redirected to: `{redirect_package}`
- Action taken: Automatically pressed back to return to the target app.

**Note**: This widget may open external apps (browser, app store, etc.).
Please continue testing other features within the target app.
"""

        parts = [
            redirect_feedback,
            GUIContextTemplate.page_info(activity_name),
            self.ui_state_section,
            self.behavior_dossier_section,
            GUIContextTemplate.widget_info(processed_widgets, widget_visits, screen_width, screen_height, is_first_visit),  # 渐进式披露
            GUIContextTemplate.action_operation_question(),
            GUIContextTemplate.input_operation_question(),
        ]

        revisit_guidance = self._build_revisit_guidance(activity_name)
        if revisit_guidance:
            parts.insert(1, revisit_guidance)

        return "\n\n".join(parts)

    
    # ==================== 工具方法 ====================

    def clear_history(self) -> None:
        """清空历史"""
        self.memory.clear_memory()
        print("[PromptGenerator] History cleared")

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return self.memory.get_stats()

    # ==================== 属性访问（向后兼容）====================

    @property
    def app_name(self) -> str:
        return self.memory.app_name

    @property
    def activity_info(self) -> Dict[str, Dict]:
        return self.memory.activity_info

    @property
    def widget_visits(self) -> Dict[str, Dict[str, int]]:
        return self.memory.widget_visits

    @property
    def explored_functions(self) -> Dict[str, Dict]:
        return self.memory.explored_functions

    @property
    def current_function(self) -> Optional[str]:
        return self.memory.current_function

    @property
    def current_function_status(self) -> Optional[str]:
        return self.memory.current_function_status


# 测试入口
if __name__ == "__main__":
    # 创建共享的 memory_manager
    memory = TestingSequenceMemorizer()

    # 创建 generator，传入 memory_manager
    generator = PromptGenerator(memory_manager=memory)
    generator.set_app_name("Wikipedia")

    # 更新功能
    memory.update_function("Login", "tested")
    memory.update_function("Search", "testing")

    # 记录操作
    memory.record_operation("MainActivity", [{"name": "Search", "visits": 1}], "Click", "Search")

    # Mock widgets
    mock_widgets = [
        {"text": "SearchBox", "class": "android.widget.EditText", "resource_id": "com.app:id/search_box"},
        {"text": "Search", "class": "android.widget.Button", "resource_id": "com.app:id/search"}
    ]

    print("=" * 60)
    print("Initial Prompt:")
    print("=" * 60)
    print(generator.build_initial_prompt(mock_widgets, "SearchActivity"))

    print("\n" + "=" * 60)
    print("Stats:")
    print("=" * 60)
    print(generator.get_stats())
