"""
Transient UI state analysis for Android UI hierarchy dumps.

This module extracts structured facts about temporary UI layers such as
dropdowns, popup menus, dialogs, pickers, and IME overlays. It intentionally
keeps the detection generic so higher-level verification does not need to
hard-code app-specific expected results.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


Bounds = Tuple[int, int, int, int]


def analyze_ui_state(
    xml_path: str | Path,
    target_package: str = "",
    device_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Analyze a raw UI hierarchy XML file and return structured UI state."""
    xml_path = Path(xml_path)
    try:
        root = ET.parse(xml_path).getroot()
    except Exception as exc:
        return {
            "transient_layer": {"active": False},
            "focused": {},
            "indicators": [],
            "error": f"ui_state_parse_failed: {exc}",
        }

    nodes = _collect_nodes(root)
    app_nodes = [
        node for node in nodes
        if not target_package or not node["package"] or node["package"] == target_package
    ]

    focused_node = _find_focused_node(nodes)
    input_method = _normalize_input_method_state(device_state or {})
    input_method_xml_layer = _detect_ime_layer(nodes)
    _classify_input_method_visibility(input_method, input_method_xml_layer)

    layer = (
        input_method_xml_layer
        or _detect_picker_layer(app_nodes)
        or _detect_list_popup_layer(app_nodes)
        or _detect_dialog_like_layer(app_nodes)
        or {"active": False}
    )

    return {
        "transient_layer": layer,
        "focused": focused_node,
        "input_method": input_method,
        "indicators": _collect_indicators(layer, focused_node, input_method),
    }


def format_ui_state_for_prompt(ui_state: Optional[Dict[str, Any]]) -> str:
    """Format structured UI state facts for Explorer/Supervisor prompts."""
    if not ui_state:
        return ""

    layer = ui_state.get("transient_layer") or {}
    lines = ["## Structured UI State"]
    if layer.get("active"):
        confidence = float(layer.get("confidence", 0) or 0)
        lines.append(
            f"Transient Layer: active {layer.get('type', 'unknown')} "
            f"(confidence={confidence:.2f})"
        )
    else:
        lines.append("Transient Layer: inactive")

    if layer.get("active"):
        bounds = layer.get("bounds")
        if bounds:
            lines.append(f"- Bounds: {bounds}")

        owner = layer.get("owner")
        if owner:
            lines.append(f"- Owner/Anchor: {owner}")

        selected = layer.get("selected_option")
        if selected:
            lines.append(f"- Selected option: {selected}")

        options = layer.get("options") or []
        if options:
            option_parts = []
            for option in options[:8]:
                text = option.get("text", "")
                if not text:
                    continue
                suffix = " [selected]" if option.get("selected") else ""
                option_parts.append(f"{text}{suffix}")
            if option_parts:
                lines.append(f"- Options: {', '.join(option_parts)}")

        reason = layer.get("reason")
        if reason:
            lines.append(f"- Detection basis: {reason}")

    focused = ui_state.get("focused") or {}
    if focused:
        lines.append(f"- Focus: {_format_focused_node(focused)}")

    input_method = ui_state.get("input_method") or {}
    if input_method:
        raw_visible = bool(input_method.get("raw_ime_visible"))
        reliable_visible = bool(input_method.get("ime_visible"))
        if reliable_visible:
            ime_state = "visible"
        elif raw_visible:
            ime_state = "reported visible (weak/stale; not treated as active keyboard)"
        else:
            ime_state = "hidden"
        details = []
        if input_method.get("visibility_basis"):
            details.append(f"basis={input_method.get('visibility_basis')}")
        if input_method.get("current_focus"):
            details.append(f"current_focus={input_method.get('current_focus')}")
        if input_method.get("input_method_target"):
            details.append(f"ime_target={input_method.get('input_method_target')}")
        if input_method.get("served_view"):
            details.append(f"served_view={input_method.get('served_view')}")
        suffix = "; " + "; ".join(details[:2]) if details else ""
        lines.append(f"- Input Method: {ime_state}{suffix}")

    return "\n".join(lines)


def classify_action_phase(
    action: Any,
    ui_state_before: Optional[Dict[str, Any]],
    ui_state_after: Optional[Dict[str, Any]],
) -> str:
    """Classify the operation against transient UI state transitions."""
    if action is None:
        return "unknown"

    before_layer = (ui_state_before or {}).get("transient_layer") or {}
    after_layer = (ui_state_after or {}).get("transient_layer") or {}
    before_active = bool(before_layer.get("active"))
    after_active = bool(after_layer.get("active"))

    operation = (getattr(action, "operation", "") or "").lower()
    target = (
        getattr(action, "widget", None)
        or getattr(action, "operation_widget", None)
        or ""
    )
    target_norm = _norm_text(target)
    back_like = _is_back_action(action)

    if back_like and before_active and not after_active:
        return "dismiss_transient"

    if back_like:
        if _ime_visible(ui_state_before) or _focused_edit_text((ui_state_before or {}).get("focused") or {}):
            return "back_with_input_focus"
        return "back_navigation"

    if not before_active and after_active:
        return "open_transient"

    if before_active:
        option_texts = {
            _norm_text(option.get("text", ""))
            for option in before_layer.get("options", [])
            if option.get("text")
        }
        if target_norm and target_norm in option_texts:
            return "select_transient" if not after_active else "select_transient_still_open"
        if operation in {"click", "double-click", "long press"}:
            return "interact_while_transient_active"

    if operation == "input":
        return "input"

    if operation in {"scroll_down", "scroll_up"}:
        return "scroll"

    submit_keywords = ("search", "submit", "save", "book", "confirm", "add", "create", "done", "ok")
    if operation == "click" and any(keyword in target_norm for keyword in submit_keywords):
        return "submit_or_commit"

    return "normal_interaction"


def classify_back_effect(
    action: Any,
    ui_state_before: Optional[Dict[str, Any]],
    ui_state_after: Optional[Dict[str, Any]],
    activity_changed: bool,
    ui_changed: bool,
) -> str:
    """Explain what a Back action actually did."""
    if not _is_back_action(action):
        return ""

    before_layer = (ui_state_before or {}).get("transient_layer") or {}
    after_layer = (ui_state_after or {}).get("transient_layer") or {}
    before_focus = (ui_state_before or {}).get("focused") or {}
    after_focus = (ui_state_after or {}).get("focused") or {}

    if activity_changed:
        return "navigated"

    if before_layer.get("active") and not after_layer.get("active"):
        layer_type = before_layer.get("type") or "transient_layer"
        return f"dismissed_{layer_type}"

    if _ime_visible(ui_state_before) and not _ime_visible(ui_state_after):
        return "dismissed_keyboard"

    if _focused_edit_text(before_focus):
        if not after_focus or not _same_focused_node(before_focus, after_focus):
            return "cleared_input_focus"
        return "possibly_consumed_by_input_focus"

    if ui_changed:
        return "changed_ui_same_activity"

    return "no_effect"


def _is_back_action(action: Any) -> bool:
    if action is None:
        return False
    operation = (getattr(action, "operation", "") or "").lower()
    target = (
        getattr(action, "widget", None)
        or getattr(action, "operation_widget", None)
        or ""
    )
    target_norm = _norm_text(target)
    return operation == "back" or (
        operation in {"click", "double-click", "long press"}
        and "back" in target_norm
    )


def transient_transition(ui_state_before: Optional[Dict[str, Any]], ui_state_after: Optional[Dict[str, Any]]) -> str:
    """Summarize how transient state changed across a step."""
    before_active = bool(((ui_state_before or {}).get("transient_layer") or {}).get("active"))
    after_active = bool(((ui_state_after or {}).get("transient_layer") or {}).get("active"))
    if not before_active and after_active:
        return "transient_opened"
    if before_active and not after_active:
        return "transient_closed"
    if before_active and after_active:
        return "transient_still_active"
    return "no_transient"


def _collect_nodes(root: ET.Element) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []

    def visit(node: ET.Element, parent: Optional[Dict[str, Any]], depth: int) -> None:
        item = {
            "element": node,
            "parent": parent,
            "depth": depth,
            "class": node.get("class", ""),
            "text": node.get("text", ""),
            "resource_id": node.get("resource-id", ""),
            "package": node.get("package", ""),
            "content_desc": node.get("content-desc", ""),
            "bounds": node.get("bounds", ""),
            "bounds_tuple": _parse_bounds(node.get("bounds", "")),
            "clickable": node.get("clickable", "false") == "true",
            "checkable": node.get("checkable", "false") == "true",
            "checked": node.get("checked", "false") == "true",
            "focusable": node.get("focusable", "false") == "true",
            "focused": node.get("focused", "false") == "true",
            "scrollable": node.get("scrollable", "false") == "true",
            "enabled": node.get("enabled", "false") == "true",
            "children": [],
        }
        if parent is not None:
            parent["children"].append(item)
        nodes.append(item)
        for child in list(node):
            visit(child, item, depth + 1)

    visit(root, None, 0)
    return nodes


def _detect_list_popup_layer(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    list_nodes = [
        node for node in nodes
        if _class_endswith(node, ("ListView", "RecyclerView"))
        and node.get("bounds_tuple")
    ]
    if not list_nodes:
        return None

    # Prefer focused popups and small overlay lists over in-page lists.
    list_nodes.sort(key=lambda n: (
        not n.get("focused"),
        _area(n.get("bounds_tuple")) if n.get("bounds_tuple") else 10**12,
    ))

    for list_node in list_nodes:
        item_nodes = [
            node for node in _descendants(list_node)
            if _visible_text(node)
            and (
                _class_endswith(node, ("CheckedTextView", "TextView", "Button"))
                or node.get("clickable")
                or node.get("checkable")
            )
        ]
        if len(item_nodes) < 2:
            continue

        options = [
            {
                "text": _visible_text(node),
                "selected": bool(node.get("checked") or node.get("focused")),
                "bounds": node.get("bounds"),
            }
            for node in item_nodes[:12]
        ]
        owner = _find_anchor_for_popup(list_node, nodes)
        selected = next((option["text"] for option in options if option.get("selected")), "")
        checked_like = any(node.get("checkable") or _class_endswith(node, ("CheckedTextView",)) for node in item_nodes)
        # Be conservative: ordinary in-page lists also use ListView/RecyclerView.
        # Treat it as a transient layer only when Android exposes popup-like
        # signals: focus on the list, checkable/dropdown rows near an anchor, or
        # a compact overlay-shaped list.
        compact_overlay = _looks_like_compact_overlay(list_node, nodes)
        if not (list_node.get("focused") or owner or (checked_like and compact_overlay)):
            continue

        layer_type = "dropdown" if checked_like or owner else "popup_menu"
        return {
            "active": True,
            "type": layer_type,
            "confidence": _list_popup_confidence(list_node, checked_like, owner, compact_overlay),
            "bounds": list_node.get("bounds"),
            "owner": owner,
            "options": options,
            "selected_option": selected,
            "reason": "focused ListView/RecyclerView overlay with selectable text items",
        }
    return None


def _list_popup_confidence(
    list_node: Dict[str, Any],
    checked_like: bool,
    owner: str,
    compact_overlay: bool,
) -> float:
    if list_node.get("focused") and checked_like:
        return 0.95
    if owner and checked_like:
        return 0.90
    if list_node.get("focused") or owner:
        return 0.85
    if checked_like and compact_overlay:
        return 0.75
    return 0.65


def _looks_like_compact_overlay(list_node: Dict[str, Any], nodes: List[Dict[str, Any]]) -> bool:
    bounds = list_node.get("bounds_tuple")
    screen = _screen_bounds(nodes)
    if not bounds or not screen:
        return False

    x1, y1, x2, y2 = bounds
    sx1, sy1, sx2, sy2 = screen
    screen_area = _area(screen)
    if screen_area <= 0:
        return False

    width_ratio = (x2 - x1) / max(1, sx2 - sx1)
    height_ratio = (y2 - y1) / max(1, sy2 - sy1)
    area_ratio = _area(bounds) / screen_area
    touches_top_or_bottom = y1 <= sy1 + 4 or y2 >= sy2 - 4

    return (
        area_ratio <= 0.45
        and height_ratio <= 0.65
        and width_ratio <= 0.95
        and not touches_top_or_bottom
    )


def _detect_picker_layer(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    picker_nodes = [
        node for node in nodes
        if _class_endswith(node, ("DatePicker", "TimePicker", "NumberPicker", "CalendarView"))
        and node.get("bounds_tuple")
    ]
    if not picker_nodes:
        return None
    picker = picker_nodes[0]
    return {
        "active": True,
        "type": "picker",
        "confidence": 0.90,
        "bounds": picker.get("bounds"),
        "owner": _visible_text(picker) or _class_suffix(picker.get("class")),
        "options": [],
        "selected_option": "",
        "reason": f"visible {_class_suffix(picker.get('class'))} widget",
    }


def _detect_dialog_like_layer(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    candidates = []
    for node in nodes:
        bounds = node.get("bounds_tuple")
        if not bounds:
            continue
        if _area(bounds) <= 0 or _is_fullscreen(bounds):
            continue
        desc = _descendants(node)
        button_count = sum(1 for child in desc if _class_endswith(child, ("Button",)) and _visible_text(child))
        text_count = sum(1 for child in desc if _class_endswith(child, ("TextView",)) and _visible_text(child))
        if button_count >= 1 and text_count >= 1 and node.get("depth", 0) <= 4:
            candidates.append(node)

    if not candidates:
        return None

    candidates.sort(key=lambda n: _area(n.get("bounds_tuple")))
    dialog = candidates[0]
    return {
        "active": True,
        "type": "dialog",
        "confidence": 0.70,
        "bounds": dialog.get("bounds"),
        "owner": "",
        "options": [
            {"text": _visible_text(node), "selected": False, "bounds": node.get("bounds")}
            for node in _descendants(dialog)
            if _class_endswith(node, ("Button",)) and _visible_text(node)
        ],
        "selected_option": "",
        "reason": "non-fullscreen container with text and action buttons",
    }


def _detect_ime_layer(nodes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    ime_nodes = [
        node for node in nodes
        if node.get("package") and any(key in node["package"].lower() for key in ("inputmethod", "keyboard", "ime"))
        and node.get("bounds_tuple")
    ]
    if not ime_nodes:
        return None
    bounds = _union_bounds([node["bounds_tuple"] for node in ime_nodes if node.get("bounds_tuple")])
    return {
        "active": True,
        "type": "keyboard",
        "confidence": 0.90,
        "bounds": _format_bounds(bounds) if bounds else "",
        "owner": "",
        "options": [],
        "selected_option": "",
        "reason": "input method package nodes visible",
    }


def _find_anchor_for_popup(list_node: Dict[str, Any], nodes: List[Dict[str, Any]]) -> str:
    popup_bounds = list_node.get("bounds_tuple")
    if not popup_bounds:
        return ""

    spinner_nodes = [
        node for node in nodes
        if _class_endswith(node, ("Spinner", "AutoCompleteTextView", "EditText"))
        and node.get("bounds_tuple")
    ]
    if not spinner_nodes:
        return ""

    px1, py1, px2, _ = popup_bounds
    best = None
    best_score = 10**9
    for spinner in spinner_nodes:
        sx1, sy1, sx2, sy2 = spinner["bounds_tuple"]
        overlap = max(0, min(px2, sx2) - max(px1, sx1))
        if overlap <= 0:
            continue
        vertical_gap = abs(py1 - sy1) if sy1 <= py1 <= sy2 else abs(py1 - sy2)
        score = vertical_gap - overlap / 1000
        if score < best_score:
            best = spinner
            best_score = score

    if not best:
        return ""

    label = _nearest_label_above(best, nodes)
    value = _first_text_descendant(best)
    class_name = _class_suffix(best.get("class"))
    if label and value:
        return f"{label} ({class_name}, current value: {value})"
    if value:
        return f"{class_name}, current value: {value}"
    if label:
        return f"{label} ({class_name})"
    return class_name


def _nearest_label_above(anchor: Dict[str, Any], nodes: List[Dict[str, Any]]) -> str:
    bounds = anchor.get("bounds_tuple")
    if not bounds:
        return ""
    ax1, ay1, ax2, _ = bounds
    labels = []
    for node in nodes:
        if not _class_endswith(node, ("TextView",)):
            continue
        text = _visible_text(node)
        nb = node.get("bounds_tuple")
        if not text or not nb:
            continue
        nx1, _, nx2, ny2 = nb
        if ny2 > ay1:
            continue
        overlap = max(0, min(ax2, nx2) - max(ax1, nx1))
        if overlap <= 0:
            continue
        labels.append((ay1 - ny2, text))
    labels.sort(key=lambda item: item[0])
    return labels[0][1] if labels else ""


def _first_text_descendant(node: Dict[str, Any]) -> str:
    for child in _descendants(node):
        text = _visible_text(child)
        if text:
            return text
    return _visible_text(node)


def _find_focused_node(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    for node in nodes:
        if node.get("focused"):
            return {
                "class": node.get("class", ""),
                "text": _visible_text(node),
                "bounds": node.get("bounds", ""),
                "package": node.get("package", ""),
            }
    return {}


def _collect_indicators(
    layer: Dict[str, Any],
    focused_node: Optional[Dict[str, Any]] = None,
    input_method: Optional[Dict[str, Any]] = None,
) -> List[str]:
    indicators = []
    if layer and layer.get("active"):
        indicators.append(f"active_{layer.get('type', 'transient')}")
    if layer.get("selected_option"):
        indicators.append("has_selected_option")
    if layer.get("options"):
        indicators.append("has_options")
    if _focused_edit_text(focused_node or {}):
        indicators.append("focused_edittext")
    if (input_method or {}).get("ime_visible"):
        indicators.append("ime_visible")
    elif (input_method or {}).get("raw_ime_visible"):
        indicators.append("weak_ime_visible")
    return indicators


def _normalize_input_method_state(device_state: Dict[str, Any]) -> Dict[str, Any]:
    if not device_state:
        return {}

    raw_ime_visible = bool(device_state.get("ime_visible"))
    return {
        "raw_ime_visible": raw_ime_visible,
        "ime_visible": raw_ime_visible,
        "current_focus": device_state.get("current_focus") or "",
        "focused_app": device_state.get("focused_app") or "",
        "input_method_target": device_state.get("input_method_target") or "",
        "served_view": device_state.get("served_view") or "",
        "visibility_reliable": False,
        "visibility_basis": "",
    }


def _classify_input_method_visibility(
    input_method: Dict[str, Any],
    xml_ime_layer: Optional[Dict[str, Any]],
) -> None:
    """Separate reliable keyboard evidence from stale dumpsys IME state."""
    if not input_method:
        return

    raw_visible = bool(input_method.get("raw_ime_visible"))
    if xml_ime_layer and xml_ime_layer.get("active"):
        input_method["ime_visible"] = True
        input_method["visibility_reliable"] = True
        input_method["visibility_basis"] = "input method package nodes visible in XML"
        return

    if raw_visible:
        input_method["ime_visible"] = False
        input_method["visibility_reliable"] = False
        input_method["visibility_basis"] = (
            "dumpsys reported IME visible, but no keyboard/IME nodes were present in the UI hierarchy"
        )
        return

    input_method["ime_visible"] = False
    input_method["visibility_reliable"] = True
    input_method["visibility_basis"] = "dumpsys reported IME hidden"


def _ime_visible(ui_state: Optional[Dict[str, Any]]) -> bool:
    if not ui_state:
        return False
    input_method = ui_state.get("input_method") or {}
    if input_method.get("ime_visible"):
        return True
    layer = ui_state.get("transient_layer") or {}
    return bool(layer.get("active") and layer.get("type") == "keyboard")


def _focused_edit_text(node: Dict[str, Any]) -> bool:
    return (node.get("class") or "").endswith("EditText")


def _same_focused_node(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return (
        (left.get("class") or "") == (right.get("class") or "")
        and (left.get("bounds") or "") == (right.get("bounds") or "")
        and (left.get("package") or "") == (right.get("package") or "")
    )


def _format_focused_node(node: Dict[str, Any]) -> str:
    class_name = _class_suffix(node.get("class") or "")
    text = (node.get("text") or "").replace("\n", " ").strip()
    if len(text) > 60:
        text = text[:57] + "..."
    bounds = node.get("bounds") or ""
    parts = [part for part in [class_name, f'text="{text}"' if text else "", bounds] if part]
    return " ".join(parts)


def _descendants(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = []
    stack = list(node.get("children", []))
    while stack:
        child = stack.pop(0)
        result.append(child)
        stack[0:0] = child.get("children", [])
    return result


def _visible_text(node: Dict[str, Any]) -> str:
    return (node.get("text") or node.get("content_desc") or "").strip()


def _class_suffix(class_name: str) -> str:
    return (class_name or "").split(".")[-1]


def _class_endswith(node: Dict[str, Any], suffixes: Tuple[str, ...]) -> bool:
    class_name = node.get("class", "")
    return any(class_name.endswith(suffix) for suffix in suffixes)


def _parse_bounds(bounds: str) -> Optional[Bounds]:
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    return tuple(map(int, match.groups()))  # type: ignore[return-value]


def _format_bounds(bounds: Optional[Bounds]) -> str:
    if not bounds:
        return ""
    x1, y1, x2, y2 = bounds
    return f"[{x1},{y1}][{x2},{y2}]"


def _area(bounds: Optional[Bounds]) -> int:
    if not bounds:
        return 0
    x1, y1, x2, y2 = bounds
    return max(0, x2 - x1) * max(0, y2 - y1)


def _screen_bounds(nodes: List[Dict[str, Any]]) -> Optional[Bounds]:
    bounds = [node.get("bounds_tuple") for node in nodes if node.get("bounds_tuple")]
    return _union_bounds(bounds)


def _is_fullscreen(bounds: Bounds, width: int = 1080, height: int = 1920) -> bool:
    x1, y1, x2, y2 = bounds
    return x1 <= 5 and y1 <= 70 and x2 >= width - 5 and y2 >= height - 150


def _union_bounds(bounds_list: List[Bounds]) -> Optional[Bounds]:
    if not bounds_list:
        return None
    return (
        min(b[0] for b in bounds_list),
        min(b[1] for b in bounds_list),
        max(b[2] for b in bounds_list),
        max(b[3] for b in bounds_list),
    )


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())
