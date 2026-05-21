"""
XML 解析模块 - 有效动作空间剪枝版
用于解析 Android UI 层级 XML 文件，提取真正可交互的 GUI 控件信息

核心优化：
1. 基础物理过滤 - 剔除无效 bounds 占位符
2. 交互属性判定 - clickable/scrollable/checkable/long-clickable 及交互组件标识
3. 父级事件冒泡 - 向上穿透算法，捕获被父容器代理的交互
4. 布局容器剔除 - 拒绝无意义的空白 Layout
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, List, Dict, Set, Tuple
import re


class GUIAnalyzer:
    """
    GUI 分析器类
    解析 Android UI XML 文件，实施严格的有效动作空间剪枝
    """

    # 屏幕高度常量，用于判断控件位置（遵循 GPTDroid 论文设定）
    SCREEN_HEIGHT = 1920
    SCREEN_MIDLINE = SCREEN_HEIGHT // 2  # 960

    # 无意义的布局类名集合（幽灵控件黑名单）
    # 这些是纯排版容器，本身不具备交互语义
    GHOST_WIDGET_BLACKLIST: Set[str] = {
        'LinearLayout', 'FrameLayout', 'RelativeLayout',
        'ViewGroup', 'ScrollView', 'HorizontalScrollView',
        'ConstraintLayout', 'CoordinatorLayout', 'DrawerLayout',
        'AppBarLayout', 'NestedScrollView', 'RecyclerView',
        'GridLayout', 'TableLayout', 'TabLayout',
        'android.widget.LinearLayout', 'android.widget.FrameLayout',
        'android.widget.RelativeLayout', 'android.view.ViewGroup',
        'android.view.View', 'android.widget.ScrollView',
        'android.widget.GridLayout', 'android.widget.TableLayout',
    }

    # System package blacklist - filter out system UI and input methods
    SYSTEM_PACKAGE_BLACKLIST: Set[str] = {
        'com.android.systemui',           # Navigation bar, status bar
        'com.android.inputmethod.latin',  # AOSP Keyboard
        'com.google.android.inputmethod.latin',  # Gboard
        'com.android.launcher',           # Home launcher
        'com.android.settings',           # Settings overlay
    }

    # Input method package keywords (partial match)
    IME_PACKAGE_KEYWORDS: Set[str] = {
        'inputmethod', 'keyboard', 'ime', 'honeyboard', 'swiftkey'
    }

    # 明确的交互组件标识符（出现在 class 名称中）
    # 包含这些关键词的控件直接判定为可交互
    INTERACTIVE_CLASS_KEYWORDS: Set[str] = {
        'Button', 'EditText', 'CheckBox', 'Switch', 'Toggle',
        'RadioButton', 'RadioGroup', 'Spinner', 'SeekBar',
        'ImageButton', 'CompoundButton', 'CheckedTextView',
        'AutoCompleteTextView', 'MultiAutoCompleteTextView',
        'SearchView', 'RatingBar', 'Chronometer', 'DatePicker',
        'TimePicker', 'NumberPicker', 'CalendarView', 'ZoomButton',
        'QuickContactBadge', 'VideoView',
        # 'ImageView',  # ImageView 可能是可点击的图标
        # 'TextView',  # TextView 可能承载父级的点击事件
    }

    # WebView 输入控件标识符（用于识别 WebView 内的输入框）
    WEBVIEW_INPUT_KEYWORDS: Set[str] = {
        'input', 'field', 'edit', 'text', 'search', 'username',
        'password', 'email', 'phone', 'login', 'name', 'title',
        'content', 'message', 'comment', 'query'
    }

    # 交互属性列表 - 具有这些属性之一即为潜在可交互
    INTERACTION_ATTRIBUTES: Set[str] = {
        'clickable', 'scrollable', 'checkable', 'long-clickable',
        'focusable', 'editable'
    }

    # 降级模式的最小控件数量阈值
    # 低于此阈值时触发降级解析
    FALLBACK_THRESHOLD = 2

    def __init__(self):
        """初始化 GUI 分析器"""
        self.nodes: List[Dict] = []  # 存储解析后的控件列表
        self._seen_bounds: Set[str] = set()  # 用于去重的 bounds 集合
        self._fallback_mode: bool = False  # 当前是否处于降级模式
        self._target_package: str = ""  # 目标应用包名（用于过滤系统控件）
        self._system_page_detected: bool = False  # 系统页面跳转检测标志
        self._detected_package: str = ""  # 检测到的跳转包名

    def is_system_page_detected(self) -> bool:
        """返回最近一次解析是否检测到系统/外部页面跳转。"""
        return self._system_page_detected

    def get_detected_package(self) -> str:
        """返回最近一次解析检测到的非目标包名。"""
        return self._detected_package

    def parse_xml(self, xml_path: str | Path, target_package: str = "") -> List[Dict]:
        """
        解析 UI XML 文件，提取有效控件信息

        实施严格的有效动作空间剪枝，并支持优雅降级：
        1. 物理坐标有效性验证
        2. 交互属性判定
        3. 父级事件冒泡处理
        4. 无意义布局容器过滤
        5. 降级解析模式 - 当严格过滤导致控件过少时自动放宽标准
        6. 系统控件过滤 - 过滤掉系统UI和输入法控件

        Args:
            xml_path: XML 文件路径
            target_package: 目标应用包名（过滤系统控件）

        Returns:
            包含所有有效控件信息的字典列表
        """
        self.nodes = []
        self._seen_bounds = set()  # 重置去重集合
        self._fallback_mode = False  # 重置降级模式标记
        self._target_package = target_package  # 设置目标包名
        self._system_page_detected = False  # 重置系统页面跳转标志
        self._detected_package = ""  # 重置检测到的包名
        xml_path = Path(xml_path)

        try:
            # 解析 XML 文件
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # ========== 新增：检测主要包名，判断系统页面跳转 ==========
            if target_package:
                primary_package = self._detect_primary_package(root)

                # 如果主要包名与目标包名不匹配，可能是系统页面跳转
                if primary_package and primary_package != target_package:
                    # 检查是否是系统设置页面
                    if primary_package == "com.android.settings":
                        print(f"[XML解析] 检测到系统设置页面跳转: {primary_package}")
                        print(f"[XML解析] 目标应用: {target_package}，建议按 back 返回")
                        # 设置标志，让调用方知道发生了系统页面跳转
                        self._system_page_detected = True
                        self._detected_package = primary_package
                        return []  # 返回空列表，让主循环处理

            # ========== 第一轮：严格模式遍历 ==========
            self._traverse_node(root, parent_chain=[])

            print(f"[XML解析] 严格模式提取到 {len(self.nodes)} 个有效控件")

            # ========== 优雅降级检测 ==========
            # 如果控件数量低于阈值，触发降级模式重新解析
            if len(self.nodes) < self.FALLBACK_THRESHOLD:
                print(f"[XML解析] 控件数量不足（<{self.FALLBACK_THRESHOLD}），触发降级模式...")

                # 重置状态，准备降级解析
                self.nodes = []
                self._seen_bounds = set()
                self._fallback_mode = True

                # 第二轮：降级模式遍历（放宽标准）
                self._traverse_node_lenient(root)

                print(f"[XML解析] 降级模式提取到 {len(self.nodes)} 个控件")

            return self.nodes

        except ET.ParseError as e:
            print(f"[XML解析失败] XML 解析错误: {e}")
            return []
        except FileNotFoundError:
            print(f"[XML解析失败] 文件不存在: {xml_path}")
            return []
        except Exception as e:
            print(f"[XML解析失败] 异常: {e}")
            return []

    def _traverse_node(
        self,
        node: ET.Element,
        parent_chain: List[ET.Element],
        max_bubble_depth: int = 3
    ) -> None:
        """
        递归遍历 XML 节点树，实施有效动作空间剪枝

        Args:
            node: 当前 XML 元素节点
            parent_chain: 从根节点到当前节点的父节点链（用于事件冒泡）
            max_bubble_depth: 向上冒泡的最大深度（默认 3 层：父、爷、祖）
        """
        # 获取父节点和兄弟节点
        parent_node = parent_chain[-1] if parent_chain else None
        sibling_nodes = list(parent_node) if parent_node else []

        # 提取节点属性（包含 NearbyWidget 信息）
        node_info = self._extract_node_info(node, parent_node, sibling_nodes)

        # ========== 第一道防线：物理坐标有效性验证 ==========
        if not self._is_valid_bounds(node_info.get("bounds", "")):
            # 仍然遍历子节点（父节点无效不代表子节点无效）
            new_chain = parent_chain + [node]
            for child in node:
                self._traverse_node(child, new_chain, max_bubble_depth)
            return

        # ========== 控件包名过滤 ==========
        # 过滤系统 UI 和输入法控件
        node_package = node.get("package", "")

        # 检查是否在系统包名黑名单中
        if node_package in self.SYSTEM_PACKAGE_BLACKLIST:
            # 继续遍历子节点（系统容器可能包含 app 内容）
            new_chain = parent_chain + [node]
            for child in node:
                self._traverse_node(child, new_chain, max_bubble_depth)
            return

        # 检查是否包含输入法关键词（部分匹配）
        if node_package:
            for keyword in self.IME_PACKAGE_KEYWORDS:
                if keyword.lower() in node_package.lower():
                    # 继续遍历子节点
                    new_chain = parent_chain + [node]
                    for child in node:
                        self._traverse_node(child, new_chain, max_bubble_depth)
                    return

        # 如果指定了目标包名，只保留该包名的控件
        if self._target_package and node_package and node_package != self._target_package:
            # 继续遍历子节点（父容器可能是系统的，但子控件可能是 app 的）
            new_chain = parent_chain + [node]
            for child in node:
                self._traverse_node(child, new_chain, max_bubble_depth)
            return

        # ========== 第二道防线：布局容器判断 ==========
        class_name = node_info.get("class", "")
        is_ghost_container = self._is_ghost_container(class_name)

        # ========== 第三道防线：交互属性判定 ==========
        has_interaction_attr = self._has_interaction_attributes(node)
        has_interactive_class = self._has_interactive_class_keyword(class_name)

        # ========== 第三道防线扩展：WebView 输入控件检测 ==========
        is_webview_input = self._is_webview_input_widget(node_info)

        # ========== 第四道防线：父级事件冒泡 ==========
        # 如果当前节点有文本但没有交互属性，尝试向上查找
        has_text = bool(node_info.get("original_text", "").strip() or
                       node_info.get("content_desc", "").strip())
        bubble_result = None

        if has_text and not has_interaction_attr and not has_interactive_class and not is_webview_input:
            bubble_result = self._bubble_find_interactive_parent(
                node, parent_chain, max_bubble_depth
            )

        # ========== 第四道防线扩展：大区域输入控件检测 ==========
        # 检测大区域的文本控件（可能是输入框，如报告详情区域）
        is_large_input_area = self._is_large_input_area(node_info)

        # ========== 综合判定：是否为有效交互节点 ==========
        is_valid_node = False
        validation_reason = ""

        # 情况1：有交互属性且不是幽灵容器
        if has_interaction_attr and not is_ghost_container:
            is_valid_node = True
            validation_reason = "交互属性"

        # 情况2：类名包含明确的交互组件标识
        elif has_interactive_class and not is_ghost_container:
            is_valid_node = True
            validation_reason = "交互类名"

        # 情况2.5：WebView 输入控件（如 id='van-field-1-input'）
        elif is_webview_input and not is_ghost_container:
            is_valid_node = True
            validation_reason = "WebView输入控件"
            # 标记为可点击和可编辑
            node_info["clickable"] = True
            node_info["editable"] = True
            node_info["focusable"] = True

        # 情况3：有文本内容，且（自身有交互 或 父级有交互 或 大区域输入）
        elif has_text:
            if has_interaction_attr or has_interactive_class:
                is_valid_node = True
                validation_reason = "有文本+交互属性"
            elif bubble_result:
                is_valid_node = True
                validation_reason = f"事件冒泡(深度{bubble_result['depth']})"
                # 使用冒泡找到的父节点的交互属性
                node_info["clickable"] = True
                node_info["bubble_parent"] = bubble_result["parent_class"]
            elif is_large_input_area and not is_ghost_container:
                # 大区域输入控件（如报告详情输入框）
                is_valid_node = True
                validation_reason = "大区域输入控件"
                node_info["clickable"] = True
                node_info["editable"] = True
                node_info["focusable"] = True

        # 情况3.5：无文本的大区域输入控件
        elif is_large_input_area and not is_ghost_container:
            is_valid_node = True
            validation_reason = "大区域输入控件(无文本)"
            # 标记为可点击和可编辑
            node_info["clickable"] = True
            node_info["editable"] = True
            node_info["focusable"] = True

        # # 情况4：有有意义的 resource-id
        # elif self._has_meaningful_resource_id(node_info.get("resource_id", "")):
        #     if not is_ghost_container:
        #         is_valid_node = True
        #         validation_reason = "有意义的resource-id"

        # ========== 去重处理（智能去重） ==========
        # 改进：相同 bounds 但有不同重要属性的控件应该保留
        if is_valid_node:
            bounds = node_info.get("bounds", "")
            resource_id = node_info.get("resource_id", "")
            text = node_info.get("text", "") or node_info.get("original_text", "")

            # 构建复合去重键：bounds + resource_id + text 的组合
            # 如果 bounds 相同但 resource_id 或 text 不同，仍然保留
            dedup_key = bounds
            has_unique_identity = bool(resource_id or text)

            if has_unique_identity:
                # 有唯一标识（resource_id 或 text），使用复合键
                dedup_key = f"{bounds}|{resource_id}|{text}"

            if dedup_key in self._seen_bounds:
                # 如果是纯 bounds 重复（没有唯一标识），才跳过
                if not has_unique_identity:
                    is_valid_node = False
                    validation_reason = "去重跳过(bounds重复)"
                # 如果有唯一标识但 dedup_key 重复，说明是完全相同的控件，跳过
                else:
                    is_valid_node = False
                    validation_reason = "去重跳过(完全相同)"
            else:
                self._seen_bounds.add(dedup_key)

        # ========== 最终判定 ==========
        if is_valid_node:
            # 记录验证原因（用于调试）
            node_info["_validation_reason"] = validation_reason
            self.nodes.append(node_info)

        # 递归遍历子节点
        new_chain = parent_chain + [node]
        for child in node:
            self._traverse_node(child, new_chain, max_bubble_depth)

    def _traverse_node_lenient(
        self,
        node: ET.Element,
        parent_node: Optional[ET.Element] = None
    ) -> None:
        """
        降级模式遍历 XML 节点树（放宽标准）

        降级模式判定规则：
        1. bounds 必须有效（物理坐标仍需验证）
        2. 只要节点有 text 或 content-desc，且不是幽灵布局容器，就视为有效
        3. 或有有意义的 resource-id

        此方法用于在严格模式提取控件不足时的兜底救援，防止 LLM 陷入死循环。

        Args:
            node: 当前 XML 元素节点
            parent_node: 父节点（用于 NearbyWidget）
        """
        # 获取兄弟节点
        sibling_nodes = list(parent_node) if parent_node else []

        # 提取节点属性（包含 NearbyWidget 信息）
        node_info = self._extract_node_info(node, parent_node, sibling_nodes)

        # 物理坐标有效性验证（降级模式仍需验证）
        if not self._is_valid_bounds(node_info.get("bounds", "")):
            # 仍然遍历子节点
            for child in node:
                self._traverse_node_lenient(child, node)
            return

        # ========== 控件包名过滤（降级模式同样过滤系统控件）==========
        node_package = node.get("package", "")

        # 检查是否在系统包名黑名单中
        if node_package in self.SYSTEM_PACKAGE_BLACKLIST:
            for child in node:
                self._traverse_node_lenient(child, node)
            return

        # 检查是否包含输入法关键词（部分匹配）
        if node_package:
            for keyword in self.IME_PACKAGE_KEYWORDS:
                if keyword.lower() in node_package.lower():
                    for child in node:
                        self._traverse_node_lenient(child, node)
                    return

        # 如果指定了目标包名，只保留该包名的控件
        if self._target_package and node_package and node_package != self._target_package:
            for child in node:
                self._traverse_node_lenient(child, node)
            return

        # 布局容器判断
        class_name = node_info.get("class", "")
        is_ghost_container = self._is_ghost_container(class_name)

        # 文本内容检查
        has_text = bool(node_info.get("original_text", "").strip() or
                       node_info.get("content_desc", "").strip())

        # resource-id 检查
        has_resource_id = self._has_meaningful_resource_id(node_info.get("resource_id", ""))

        # 降级模式判定：有文本或有 resource-id，且不是幽灵容器
        is_valid_node = False
        validation_reason = ""

        if not is_ghost_container:
            if has_text:
                is_valid_node = True
                validation_reason = "Fallback Mode: 有文本内容"
            elif has_resource_id:
                is_valid_node = True
                validation_reason = "Fallback Mode: 有resource-id"

        # 去重处理
        if is_valid_node:
            bounds = node_info.get("bounds", "")
            if bounds in self._seen_bounds:
                is_valid_node = False
            else:
                self._seen_bounds.add(bounds)

        # 添加到控件列表
        if is_valid_node:
            node_info["_validation_reason"] = validation_reason
            node_info["_fallback_mode"] = True  # 标记为降级模式提取
            self.nodes.append(node_info)

        # 递归遍历子节点
        for child in node:
            self._traverse_node_lenient(child, node)

    def _extract_node_info(
        self,
        node: ET.Element,
        parent_node: Optional[ET.Element] = None,
        sibling_nodes: Optional[List[ET.Element]] = None
    ) -> Dict:
        """
        提取节点的关键属性信息

        Args:
            node: XML 元素节点
            parent_node: 父节点（用于提取 NearbyWidget）
            sibling_nodes: 兄弟节点列表（用于提取 NearbyWidget）

        Returns:
            包含节点信息的字典
        """
        # 获取各类属性
        class_name = node.get("class", "")
        text = node.get("text", "")
        content_desc = node.get("content-desc", "")
        resource_id = node.get("resource-id", "")
        bounds = node.get("bounds", "")
        package = node.get("package", "")  # 提取 package 属性

        # 交互属性
        clickable = node.get("clickable", "false") == "true"
        scrollable = node.get("scrollable", "false") == "true"
        checkable = node.get("checkable", "false") == "true"
        long_clickable = node.get("long-clickable", "false") == "true"
        focusable = node.get("focusable", "false") == "true"
        editable = node.get("editable", "false") == "true"
        enabled = node.get("enabled", "true") == "true"  # 默认为 true

        # 解析 bounds 坐标
        center_x, center_y, position = self._parse_bounds(bounds)

        # 如果 text 为空，则使用 content-desc 作为显示文本
        display_text = text if text else content_desc

        # 提取 NearbyWidget 信息
        nearby_widget = self._extract_nearby_widget(node, parent_node, sibling_nodes)

        node_info = {
            "class": class_name,
            "text": display_text,  # text 为空时取 content-desc
            "original_text": text,  # 保留原始 text
            "content_desc": content_desc,
            "resource_id": resource_id,
            "bounds": bounds,
            "package": package,  # 添加 package 属性
            "center_x": center_x,
            "center_y": center_y,
            "position": position,  # "upper" 或 "lower"
            "clickable": clickable,
            "scrollable": scrollable,
            "checkable": checkable,
            "long_clickable": long_clickable,
            "focusable": focusable,
            "editable": editable,
            "enabled": enabled,
            # NearbyWidget: 父节点和兄弟节点信息
            "parent": nearby_widget["parent"],
            "siblings": nearby_widget["siblings"],
        }
        self._apply_label_value_identity(node_info, node)
        return node_info

    def _apply_label_value_identity(self, node_info: Dict, node: ET.Element) -> None:
        """
        Give standard form controls a stable business identity.

        Android forms often expose a TextView label immediately above a real
        interactive control such as Spinner. The label itself is not clickable,
        but users and LLMs naturally refer to the field by that label. For these
        controls, use "Label: Current value" as the widget name while preserving
        the target control's own bounds.
        """
        class_name = node_info.get("class", "")
        simple_class = self._get_simple_class_name(class_name)
        if simple_class not in {"Spinner"}:
            return

        label = self._find_nearby_field_label(node_info)
        value = self._extract_text_from_container(node, max_depth=2)
        if not label:
            return

        label = self._clean_inline_text(label)
        value = self._clean_inline_text(value)
        if not label:
            return

        node_info["field_label"] = label
        if value:
            node_info["current_value"] = value
            node_info["text"] = f"{label}: {value}"
        else:
            node_info["text"] = label

    def _find_nearby_field_label(self, node_info: Dict) -> str:
        siblings = node_info.get("siblings", [])
        if not siblings:
            return ""

        # Prefer the nearest preceding TextView. In a vertical form this is the
        # standard label position: Label [y1,y2] followed by Spinner [y2,y3].
        for sibling in reversed(siblings):
            if sibling.get("position") != "before":
                continue
            sib_class = sibling.get("class", "")
            sib_text = self._clean_inline_text(sibling.get("text", ""))
            if sib_text and sib_class in {"TextView", ""}:
                return sib_text
        return ""

    @staticmethod
    def _clean_inline_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _extract_nearby_widget(
        self,
        node: ET.Element,
        parent_node: Optional[ET.Element],
        sibling_nodes: Optional[List[ET.Element]]
    ) -> Dict:
        """
        提取周围控件信息（父节点 + 兄弟节点）

        Args:
            node: 当前节点
            parent_node: 父节点
            sibling_nodes: 兄弟节点列表

        Returns:
            {"parent": {...}, "siblings": [...]}
        """
        result = {
            "parent": None,
            "siblings": []
        }

        # 提取父节点信息
        if parent_node is not None:
            parent_class = parent_node.get("class", "")
            parent_text = parent_node.get("text", "") or parent_node.get("content-desc", "")
            parent_id = parent_node.get("resource-id", "")

            result["parent"] = {
                "class": self._get_simple_class_name(parent_class),
                "text": parent_text,
                "resource_id": parent_id
            }

        # 提取兄弟节点信息
        if sibling_nodes:
            # 获取当前节点在兄弟列表中的索引
            current_index = -1
            for i, sibling in enumerate(sibling_nodes):
                if sibling is node:
                    current_index = i
                    break

            if current_index >= 0:
                # 收集前后各最多3个兄弟节点
                siblings_info = []

                # 前面的兄弟节点（最多3个）
                prev_siblings = sibling_nodes[max(0, current_index - 3):current_index]
                for sib in prev_siblings:
                    sib_info = self._get_sibling_info(sib, "before")
                    if sib_info:
                        siblings_info.append(sib_info)

                # 后面的兄弟节点（最多3个）
                next_siblings = sibling_nodes[current_index + 1:current_index + 4]
                for sib in next_siblings:
                    sib_info = self._get_sibling_info(sib, "after")
                    if sib_info:
                        siblings_info.append(sib_info)

                result["siblings"] = siblings_info

        return result

    def _get_sibling_info(self, sibling: ET.Element, position: str) -> Optional[Dict]:
        """
        获取兄弟节点的基本信息

        改进：对于布局容器（LinearLayout等），穿透查找内部的文本内容

        Args:
            sibling: 兄弟节点
            position: 相对位置 ("before" 或 "after")

        Returns:
            兄弟节点信息字典，无效节点返回 None
        """
        sib_class = sibling.get("class", "")
        sib_text = sibling.get("text", "") or sibling.get("content-desc", "")

        # 获取简单类名
        simple_class = self._get_simple_class_name(sib_class)

        # 如果是布局容器，尝试从子节点中提取文本
        if simple_class in self.GHOST_WIDGET_BLACKLIST:
            # 递归查找容器内的文本内容
            nested_text = self._extract_text_from_container(sibling)
            if nested_text:
                # 返回一个虚拟的 TextView 信息，包含提取的文本
                return {
                    "class": "TextView",
                    "text": nested_text,
                    "position": position
                }
            return None

        # 至少要有类名或文本才有意义
        if not simple_class and not sib_text:
            return None

        return {
            "class": simple_class,
            "text": sib_text,
            "position": position
        }

    def _extract_text_from_container(self, container: ET.Element, max_depth: int = 3) -> str:
        """
        从布局容器中递归提取文本内容

        用于穿透 LinearLayout、FrameLayout 等容器，获取内部的 TextView 文本。
        这对于 CheckBox/Switch 等控件获取相邻标签非常重要。

        Args:
            container: 布局容器节点
            max_depth: 最大递归深度（避免无限递归）

        Returns:
            提取到的文本内容，多个文本用空格连接
        """
        if max_depth <= 0:
            return ""

        texts = []

        # 先检查当前节点自身是否有文本
        node_text = container.get("text", "") or container.get("content-desc", "")
        if node_text and len(node_text) > 2:
            texts.append(node_text)

        # 递归遍历子节点
        for child in container:
            child_class = child.get("class", "")
            simple_class = self._get_simple_class_name(child_class)

            # 如果子节点也是布局容器，继续递归
            if simple_class in self.GHOST_WIDGET_BLACKLIST:
                nested_text = self._extract_text_from_container(child, max_depth - 1)
                if nested_text:
                    texts.append(nested_text)
            else:
                # 非 Ghost 容器，直接提取文本
                child_text = child.get("text", "") or child.get("content-desc", "")
                if child_text and len(child_text) > 2:
                    texts.append(child_text)

        # 返回最长的文本（通常是设置标签）
        if texts:
            return max(texts, key=len)

        return ""

    def _get_simple_class_name(self, full_class_name: str) -> str:
        """
        获取简单类名（去掉包名前缀）

        Args:
            full_class_name: 完整类名，如 "android.widget.Button"

        Returns:
            简单类名，如 "Button"
        """
        if not full_class_name:
            return ""
        if '.' in full_class_name:
            return full_class_name.split('.')[-1]
        return full_class_name

    def _parse_bounds(self, bounds: str) -> Tuple[Optional[int], Optional[int], str]:
        """
        解析 bounds 字符串，计算中心点坐标并判断位置

        bounds 格式示例: "[0,100][1080,200]"
        解析为左上角 (0, 100) 和右下角 (1080, 200)

        Args:
            bounds: bounds 属性字符串

        Returns:
            元组 (center_x, center_y, position)
            position 为 "upper" 或 "lower"
        """
        if not bounds:
            return None, None, "unknown"

        try:
            # 使用正则提取坐标值
            # 格式: [x1,y1][x2,y2]
            pattern = r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]'
            match = re.match(pattern, bounds)

            if not match:
                return None, None, "unknown"

            x1, y1, x2, y2 = map(int, match.groups())

            # 计算中心点坐标
            center_x = (x1 + x2) // 2
            center_y = (y1 + y2) // 2

            # 判断位置：y < 960 为 upper，否则为 lower
            if center_y < self.SCREEN_MIDLINE:
                position = "upper"
            else:
                position = "lower"

            return center_x, center_y, position

        except Exception as e:
            print(f"[bounds解析失败] bounds={bounds}, 错误: {e}")
            return None, None, "unknown"

    def _is_valid_bounds(self, bounds: str) -> bool:
        """
        验证 bounds 是否有效

        无效条件：
        1. bounds 为空
        2. bounds 格式无法解析
        3. 宽度 <= 0 或高度 <= 0
        4. x1 == 0 且 y1 == 0 且 x2 == 0 且 y2 == 0（完全无坐标的幽灵占位符）

        Args:
            bounds: bounds 属性字符串，格式如 "[0,100][1080,200]"

        Returns:
            True 表示有效，False 表示无效
        """
        if not bounds:
            return False

        try:
            pattern = r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]'
            match = re.match(pattern, bounds)

            if not match:
                return False

            x1, y1, x2, y2 = map(int, match.groups())

            # 检查完全无坐标的幽灵占位符
            if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
                return False

            # 检查宽高是否有效
            width = x2 - x1
            height = y2 - y1

            if width <= 0 or height <= 0:
                return False

            return True

        except Exception:
            return False

    def _is_ghost_container(self, class_name: str) -> bool:
        """
        判断类名是否为幽灵布局容器

        Args:
            class_name: 类名字符串

        Returns:
            True 表示是幽灵容器，False 表示不是
        """
        if not class_name:
            return True  # 没有类名的节点也视为容器

        # 精确匹配
        if class_name in self.GHOST_WIDGET_BLACKLIST:
            return True

        # 后缀匹配（处理 android.widget.xxx 格式）
        simple_name = class_name.split('.')[-1] if '.' in class_name else class_name
        if simple_name in self.GHOST_WIDGET_BLACKLIST:
            return True

        return False

    def _has_interaction_attributes(self, node: ET.Element) -> bool:
        """
        检查节点是否具有交互属性

        检查的属性：clickable, scrollable, checkable, long-clickable

        Args:
            node: XML 元素节点

        Returns:
            True 表示具有交互属性
        """
        for attr in ['clickable', 'scrollable', 'checkable', 'long-clickable']:
            if node.get(attr, "false") == "true":
                return True
        return False

    def _has_interactive_class_keyword(self, class_name: str) -> bool:
        """
        检查类名是否包含交互组件标识

        Args:
            class_name: 类名字符串

        Returns:
            True 表示包含交互关键词
        """
        if not class_name:
            return False

        # 获取简单类名（去掉包名前缀）
        simple_name = class_name.split('.')[-1] if '.' in class_name else class_name

        # 检查是否在交互关键词集合中
        for keyword in self.INTERACTIVE_CLASS_KEYWORDS:
            if keyword in simple_name:
                return True

        return False

    def _is_webview_input_widget(self, node_info: Dict) -> bool:
        """
        检查是否为 WebView 输入控件

        WebView 内的输入框通常有以下特征：
        1. class 为 "android.widget.EditText" 或类似的输入类
        2. resource-id 包含 'input', 'field', 'edit' 等关键词
        3. 即使 clickable=false，也应该被识别为可交互

        Args:
            node_info: 控件信息字典

        Returns:
            True 表示是 WebView 输入控件
        """
        class_name = node_info.get("class", "")
        resource_id = node_info.get("resource_id", "").lower()
        if resource_id.startswith("android:id/"):
            return False

        # 检查是否为 EditText 类
        is_edittext = "EditText" in class_name if class_name else False

        # 检查 resource-id 是否包含输入相关关键词
        has_input_id = False
        if resource_id:
            for keyword in self.WEBVIEW_INPUT_KEYWORDS:
                if keyword in resource_id:
                    has_input_id = True
                    break

        # 必须是 EditText 且有输入相关的 resource-id
        if is_edittext and has_input_id:
            return True

        # 或者：有输入相关的 resource-id 且是可聚焦的文本类控件
        # 这处理了 WebView 中 class 可能不是 EditText 的情况
        is_text_widget = class_name and ("TextView" in class_name or "EditText" in class_name)
        if has_input_id and is_text_widget:
            return True

        return False

    def _is_large_input_area(self, node_info: Dict) -> bool:
        """
        检查是否为大区域输入控件

        有些应用使用 TextView 来实现输入区域（如报告详情、评论框等），
        这些控件通常：
        1. 面积较大（高度超过阈值）
        2. 可能包含提示文本（hint）或描述性文本
        3. 即使 clickable=false，也应该被识别为可交互

        Args:
            node_info: 控件信息字典

        Returns:
            True 表示是大区域输入控件
        """
        bounds = node_info.get("bounds", "")
        class_name = node_info.get("class", "")
        text = node_info.get("text", "") or node_info.get("original_text", "")

        # 只处理 TextView 类型的控件
        if not class_name or "TextView" not in class_name:
            return False

        # 解析 bounds 获取高度
        try:
            import re
            pattern = r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]'
            match = re.match(pattern, bounds)
            if not match:
                return False

            x1, y1, x2, y2 = map(int, match.groups())
            width = x2 - x1
            height = y2 - y1

            # 大区域判定条件：
            # 1. 高度超过 300 像素（可能是多行输入框）
            # 2. 宽度超过 200 像素（排除细长条）
            if height >= 300 and width >= 200:
                print(f"[大区域检测] 发现大区域输入控件: bounds={bounds}, height={height}, text='{text[:30]}...'")
                return True

            # 或者：高度超过 200 且文本包含输入提示关键词
            input_hint_keywords = ["details", "详情", "描述", "说明", "输入", "填写", "内容", "comment", "message", "report"]
            if height >= 200:
                text_lower = text.lower()
                for keyword in input_hint_keywords:
                    if keyword in text_lower:
                        print(f"[大区域检测] 发现带提示的大区域控件: height={height}, keyword='{keyword}'")
                        return True

        except Exception as e:
            pass

        return False

    def _detect_primary_package(self, root: ET.Element) -> Optional[str]:
        """
        检测 XML 中的主要包名（非系统包名）

        通过统计各个包名的控件数量，返回数量最多的非系统包名。
        用于检测是否发生了系统页面跳转。

        Returns:
            主要包名，如果无法确定则返回 None
        """
        package_counts: Dict[str, int] = {}

        for node in root.iter():
            pkg = node.get("package", "")
            if pkg and pkg not in self.SYSTEM_PACKAGE_BLACKLIST:
                package_counts[pkg] = package_counts.get(pkg, 0) + 1

        if not package_counts:
            return None

        # 返回数量最多的包名
        return max(package_counts, key=package_counts.get)

    def _has_meaningful_resource_id(self, resource_id: str) -> bool:
        """
        检查 resource-id 是否有意义

        有意义的 resource-id 包含 "/"，说明是开发者定义的 ID
        例如: "com.example.app:id/btn_submit"

        Args:
            resource_id: resource-id 属性值

        Returns:
            True 表示有意义的 resource-id
        """
        if not resource_id:
            return False

        # 必须包含 "/" 才是开发者定义的 ID
        return "/" in resource_id

    def _bubble_find_interactive_parent(
        self,
        node: ET.Element,
        parent_chain: List[ET.Element],
        max_depth: int
    ) -> Optional[Dict]:
        """
        向上冒泡查找具有交互属性的父节点

        算法说明：
        很多时候，文本节点本身 clickable="false"，但它的父节点（或爷爷节点）是
        clickable="true"。这种情况下，用户点击文本实际上触发的是父级的点击事件。

        本方法向上遍历父节点链，找到第一个具有交互属性的长辈节点。

        Args:
            node: 当前 XML 元素节点
            parent_chain: 父节点链（从根节点到当前节点的直接父节点）
            max_depth: 最大向上查找深度

        Returns:
            找到的交互父节点信息，包含 depth 和 parent_class；
            未找到返回 None
        """
        # parent_chain 是从根节点到当前节点的父节点链
        # 我们需要从最近的父节点开始向上查找
        if not parent_chain:
            return None

        # 反转父节点链，从最近的父节点开始
        reversed_chain = list(reversed(parent_chain))

        for depth, parent in enumerate(reversed_chain[:max_depth], start=1):
            parent_class = parent.get("class", "unknown")
            parent_simple_class = self._get_simple_class_name(parent_class)

            # Spinner already receives a merged "Label: value" identity and
            # keeps the correct tappable bounds. Do not expose its child
            # TextView value as a separate duplicate widget.
            if depth == 1 and parent_simple_class in {"Spinner"}:
                return None

            # 检查父节点是否有交互属性
            clickable = parent.get("clickable", "false") == "true"
            scrollable = parent.get("scrollable", "false") == "true"
            checkable = parent.get("checkable", "false") == "true"
            long_clickable = parent.get("long-clickable", "false") == "true"

            # Do not treat a scrollable parent as a click delegate. A ScrollView
            # makes its children scrollable, not individually clickable. Using
            # scrollable here promoted plain TextView labels such as "Cabin" to
            # fake clickable widgets, causing taps to land on labels instead of
            # their adjacent Spinner controls.
            if clickable or checkable or long_clickable:
                return {
                    "depth": depth,
                    "parent_class": parent_class,
                    "clickable": clickable,
                    "scrollable": scrollable,
                }

        return None

    def get_nodes_by_position(self, position: str) -> List[Dict]:
        """
        根据位置筛选控件

        Args:
            position: "upper" 或 "lower"

        Returns:
            符合条件的控件列表
        """
        return [node for node in self.nodes if node.get("position") == position]

    def get_clickable_nodes(self) -> List[Dict]:
        """
        获取所有可点击的控件

        Returns:
            可点击控件列表
        """
        return [node for node in self.nodes if node.get("clickable")]

    def get_nodes_with_text(self) -> List[Dict]:
        """
        获取所有有文本内容的控件

        Returns:
            有文本内容的控件列表
        """
        return [node for node in self.nodes if node.get("text", "").strip()]

    def get_interactive_summary(self) -> Dict:
        """
        获取控件交互属性统计摘要

        Returns:
            统计信息字典
        """
        total = len(self.nodes)
        if total == 0:
            return {"total": 0, "fallback_mode": self._fallback_mode}

        clickable = sum(1 for n in self.nodes if n.get("clickable"))
        scrollable = sum(1 for n in self.nodes if n.get("scrollable"))
        checkable = sum(1 for n in self.nodes if n.get("checkable"))
        long_clickable = sum(1 for n in self.nodes if n.get("long_clickable"))
        with_text = sum(1 for n in self.nodes if n.get("text", "").strip())
        with_bubble = sum(1 for n in self.nodes if n.get("bubble_parent"))
        fallback_count = sum(1 for n in self.nodes if n.get("_fallback_mode"))

        return {
            "total": total,
            "clickable": clickable,
            "scrollable": scrollable,
            "checkable": checkable,
            "long_clickable": long_clickable,
            "with_text": with_text,
            "bubble_parent": with_bubble,
            "fallback_mode": self._fallback_mode,
            "fallback_count": fallback_count,
        }


# 测试入口
if __name__ == "__main__":
    import sys

    # 获取测试文件路径
    test_file = sys.argv[1] if len(sys.argv) > 1 else "temp_data/current_ui.xml"

    print("=" * 60)
    print("XML 解析测试 - 有效动作空间剪枝 + NearbyWidget")
    print("=" * 60)

    analyzer = GUIAnalyzer()
    nodes = analyzer.parse_xml(test_file)

    # 打印统计摘要
    summary = analyzer.get_interactive_summary()
    print("\n--- 控件统计摘要 ---")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    # 打印前 5 个有效控件（显示完整信息）
    print(f"\n--- 前 5 个有效控件 ---")
    for i, node in enumerate(nodes[:5]):
        print(f"\n[控件 {i + 1}]")
        print(f"  类别: {node['class']}")
        print(f"  文本: {node['text']}")
        print(f"  ID: {node['resource_id']}")
        print(f"  位置: {node['position']}")
        print(f"  坐标: ({node['center_x']}, {node['center_y']})")
        print(f"  交互属性: clickable={node['clickable']}, scrollable={node['scrollable']}")
        print(f"  验证原因: {node.get('_validation_reason', 'N/A')}")

        # NearbyWidget 信息
        parent = node.get("parent")
        if parent:
            print(f"  父节点: {parent.get('class', 'N/A')} | text: '{parent.get('text', '')}'")

        siblings = node.get("siblings", [])
        if siblings:
            print(f"  兄弟节点 ({len(siblings)} 个):")
            for sib in siblings:
                print(f"    - [{sib.get('position', '?')}] {sib.get('class', 'N/A')}: '{sib.get('text', '')}'")

        if node.get("bubble_parent"):
            print(f"  冒泡父级: {node['bubble_parent']}")
        if node.get("_fallback_mode"):
            print(f"  [降级模式提取]")
