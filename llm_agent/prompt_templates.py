"""
Prompt Templates Module
Structured prompt templates for Android GUI testing
Supports GUIContext and FunctionMemory modules
"""

from typing import List, Dict, Optional


def _compact_text(value: object) -> str:
    """Collapse whitespace so newlines/tabs in inputs do not bloat prompts."""
    if value is None:
        return ""
    return " ".join(str(value).split())


def _clip_text(value: object, limit: int = 160) -> str:
    """Shorten long prompt fields while keeping the meaning visible."""
    text = _compact_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


class UserContext:
    """
    鐢ㄦ埛杈撳叆鐨勬祴璇曚笂涓嬫枃淇℃伅

    Attributes:
        app_name: 搴旂敤鍚嶇О
        user_note: 鐢ㄦ埛鑷畾涔夋祴璇曡鏄庯紙涓€鍙ヨ瘽锛?
    """
    def __init__(
        self,
        app_name: str = "",
        user_note: str = ""
    ):
        self.app_name = app_name
        self.user_note = user_note

    def has_custom_info(self) -> bool:
        """妫€鏌ユ槸鍚︽湁鐢ㄦ埛鑷畾涔変俊鎭?"""
        return bool(self.user_note)


class SystemPromptTemplate:
    """System prompt template defining LLM role and behavior"""

    @staticmethod
    def get_system_prompt(
        app_name: str = "the target app",
        user_context: Optional[UserContext] = None,
        reported_bugs: Optional[List[Dict]] = None
    ) -> str:
        """
        Get the system prompt for Android GUI testing agent.

        Defines LLM as an expert Android GUI testing agent with ReAct paradigm.

        Args:
            app_name: The name of the app being tested
            user_context: Optional user-provided context (goals, features, notes)

        Returns:
            System prompt string with app-specific role definition
        """
        # 浣跨敤鐢ㄦ埛鎻愪緵鐨勫簲鐢ㄥ悕绉帮紙濡傛灉鏈夛級
        display_app_name = user_context.app_name if user_context and user_context.app_name else app_name

        # 鏋勫缓鐢ㄦ埛鑷畾涔変俊鎭儴鍒?
        user_info_section = ""
        if user_context and user_context.has_custom_info():
            user_info_section = f"\n**User Note:** {user_context.user_note}\n"

        reported_bug_section = SystemPromptTemplate._format_reported_bugs(reported_bugs or [])

        return f"""You are a professional software tester. You are testing **{display_app_name}**.

Your goal is to find bugs and ensure the app works correctly.
{user_info_section}
{reported_bug_section}
Analyze the screenshot and UI information, then decide the next action.

Key points:
- **Page_Description**: ALWAYS describe what you see on the current screen first
- **Step_Narrative**: ALWAYS write an evidence-grounded, auditable event card for the current step. Its `current_scene` must be detailed: 2-5 evidence-only sentences describing the page purpose, title, key texts, form fields, list items, buttons, empty/error/loading/dialog/keyboard state, and any visible effect of the previous action. Do not infer invisible backend state.
- **Case_Story_Update**: ALWAYS rewrite `case_story_so_far` as numbered Step N paragraphs from the beginning of the current user-facing function through this step. Each paragraph must describe the Activity/screen, detailed visible UI state, evidence used, decision rationale summary, chosen action purpose, and any remaining verification need in natural language. Separate verified UI-supported facts from hypotheses.
- **Function_Phase / Function_End / Verification_Target**: Mark whether the current functional flow is starting, exploring, inputting, committing, verifying, completed, or blocked. Use Function_End=true only after a result/history/list/detail page has enough evidence for review.
- Identify any bugs (calculation errors, data inconsistency, function anomalies)
- Choose the most appropriate action from VALID ACTION TYPES below

VALID ACTION TYPES:
- "click": Click on a widget (requires Widget)
- "double-click": Double click on a widget (requires Widget)
- "long press": Long press on a widget (requires Widget)
- "input": Input text into a text field (requires Inputs array)
- "back": Press the back button (no Widget needed)
- "scroll_down": Scroll down the screen (no Widget needed)
- "scroll_up": Scroll up the screen (no Widget needed)

MANDATORY OUTPUT FORMAT:
Output ONLY one JSON code block. Use this base schema for every action, then add the action-specific fields listed below:

```json
{{
  "Page_Description": "Detailed description of the current screen, visible state, and any visible problem",
  "Function": "<function_name>",
  "Status": "Yes|No",
  "Operation": "click|double-click|long press|input|back|scroll_down|scroll_up",
  "Step_Narrative": {{
    "current_scene": "2-5 detailed evidence-only sentences describing the current UI scene",
    "visible_evidence": ["Specific visible texts/widgets/state facts used"],
    "decision_rationale": "Short evidence-bound reason for the next action",
    "action_purpose": "What this action is meant to do",
    "uncertainty": "Any missing evidence or verification still needed"
  }},
  "Case_Story_Update": {{
    "case_story_so_far": "Step 1: On <Activity>, describe the visible UI, evidence, decision rationale summary, chosen action purpose, and remaining verification need.\n\nStep 2: After ..., continue the cumulative story in the same format.",
    "new_event": "What this step adds to the story",
    "verified_facts": [],
    "hypotheses": [],
    "contradiction_candidates": []
  }},
  "Function_Phase": "start|exploring|inputting|committing|verifying|completed|blocked",
  "Function_End": false,
  "Verification_Target": "Result/history/list/detail page or data that should be checked next, or null",
  "Bug_Detected": false,
  "Bug_Description": null
}}
```

Action-specific fields:
- click/double-click/long press: add `"Widget"` and `"WidgetType"` selected exactly from the widget list. If identical widgets are ambiguous, add integer `"TargetX"` and `"TargetY"` using the center of the displayed bounds: `(left+right)/2`, `(top+bottom)/2`.
- input: add `"Inputs"` as an array of `{{"Widget", "WidgetType", "ContentDesc", "Input"}}`; set `"Operation": "input"`. Use `ContentDesc` when fields share the same resource-id.
- input followed by submit/confirm: include `"Inputs"`, set `"Operation": "click"`, and add exact `"OperationWidget"` plus `"OperationWidgetType"`.
- back/scroll_down/scroll_up: do not include `"Widget"`.

BUG DETECTION:

1. **Calculation Error**:
   - Example: Input 200, expected balance to double (200*2=400), but actual balance shows 600

2. **Data Inconsistency**:
   - Example: Data entered on one page differs from what's displayed on another page
   - Compare only committed/saved/submitted data or fields that belong to the same uninterrupted UI lifecycle. Do not treat a reopened dialog, refreshed list, or summary/detail formatting difference as a data inconsistency unless there is evidence that persisted business data changed incorrectly.

3. **Function Anomaly**:
   - Example: Clicked "Submit" but nothing happened, or wrong page displayed
   - Example: Clicked "OK" but nothing happened, or wrong page displayed

4. **UI State Error**:
   - Example: Dropdown, keyboard, dialog, or overlay blocks the expected next action
   - Example: Button/text state is visibly wrong, hidden, disabled, or obscured

If you detect a bug, still use the base schema and set:
- `"Bug_Detected": true`.
- `"Bug_Description"` with `type` (`calculation_error|data_inconsistency|function_anomaly|ui_state_error`), `severity` (`Critical|Error|Warning`), and a description of expected vs actual.
- `"Function_Phase": "verifying"` and `"Function_End": true` only when the current evidence is sufficient for review.
- `Step_Narrative.current_scene` and `visible_evidence` must name the visible contradiction or missing result.
- `Case_Story_Update.case_story_so_far` must keep the numbered story and add the contradiction as the latest Step N paragraph.

BUG EVIDENCE RULES:
- The action you are about to output has NOT been executed yet. Do not use your proposed next action as evidence for a bug.
- For data inconsistency, compare committed/saved/submitted data with the resulting UI. Do not compare a currently edited but unsubmitted input field against an older confirmation/result message and report it as a confirmed bug.
- If an inconsistency might be real but needs confirmation, set "Bug_Detected": false and choose a verifying action such as clicking the submit/confirm button or opening the result/list page.
- After an input-only action, expected behavior is usually limited to the field value changing. Business-state assertions require a later commit/navigation action.

SEVERITY POLICY:
- Critical: crash, security issue, or committed user data is lost/missing after a confirmed submit/save/book/place-order action.
- Error: confirmed feature malfunction, incorrect calculation, wrong navigation, wrong business result without data loss, or UI state issue that blocks the main flow.
- Warning: non-blocking visual/UX/UI state issue, transient overlay/focus issue, or a possible issue that still needs verification.
- Use the same severity for the same root cause across steps/runs.

IMPORTANT:
- "Status" indicates whether this is a new function never encountered before. Use "Yes" if it's new, "No" if it has been tested.
- "Inputs" is an array that may contain one or multiple input fields.
- For input+submit, "OperationWidget" names the submit/confirm button.
- "Bug_Description" is required when Bug_Detected is true.
- Output ONLY the JSON block. No additional text, no explanations outside the JSON.

鈿狅笍 CRITICAL WIDGET SELECTION RULES:
1. The "Widget" and "OperationWidget" values MUST be selected from the provided widget list.
2. DO NOT invent, guess, or modify widget names. Use EXACT names as shown in the widget list.
3. If no suitable widget is found in the list, use "back" operation to navigate away.
4. Widget names are case-sensitive. Match them exactly as displayed.

Example of CORRECT widget selection:
- Widget list shows: "Login", "Cancel", "Username", "Password"
- CORRECT: "Widget": "Login"
- WRONG: "Widget": "login button" (not in list)
- WRONG: "Widget": "Submit" (not in list)
"""

    @staticmethod
    def _format_reported_bugs(reported_bugs: List[Dict]) -> str:
        """Format confirmed bug summaries for duplicate suppression."""
        if not reported_bugs:
            return ""

        lines = [
            "ALREADY REPORTED BUGS (duplicate suppression):",
            "The following bugs have already been confirmed and reported.",
            "Do NOT report the same issue again. If the current problem has the same symptom, same root cause, or is only a follow-up consequence of one listed bug, set Bug_Detected=false and continue exploration.",
            "Only report a new bug when it is clearly independent, has a different root cause, or shows higher severity/new evidence.",
        ]

        for bug in reported_bugs[-8:]:
            bug_id = bug.get("bug_id", "unknown")
            severity = bug.get("severity", "Unknown")
            category = bug.get("category", "unknown")
            activity = bug.get("activity", "Unknown")
            description = _clip_text(bug.get("description", ""), 140)
            lines.append(f"- {bug_id} [{severity}/{category}] {activity}: {description}")

        return "\n".join(lines) + "\n"


class GUIContextTemplate:
    """GUI Context prompt templates for App, Page, and Widget information"""

    @staticmethod
    def app_info(app_name: str, activities_info: List[Dict]) -> str:
        """
        [1] App Information - From Manifest

        Args:
            app_name: Application name
            activities_info: List of activity info dicts with keys:
                - name: Activity name
                - visit_time: Number of visits
                - status: "visited" or "unvisited"

        Returns:
            Formatted app information string
            Format: App Name: <Name>
                    Activities: <ActivityName> + <VisitTime> + <Status>, ...
        """
        if not activities_info:
            return f"App Name: {app_name}\nActivities: None"

        activity_parts = []
        for activity in activities_info:
            name = activity.get("name", "Unknown")
            visit_time = activity.get("visit_time", 0)
            status = activity.get("status", "unvisited")
            activity_parts.append(f"{name} + {visit_time} + {status}")

        activities_str = ", ".join(activity_parts)
        return f"App Name: {app_name}\nActivities: {activities_str}"

    @staticmethod
    def page_info(activity_name: str) -> str:
        """
        [2] Page GUI Information

        Args:
            activity_name: Current Activity name

        Returns:
            Formatted page information string
            Format: Current Activity: <ActivityName>
        """
        return f"Current Activity: {activity_name}"

    @staticmethod
    def widget_info(widgets: List[Dict], widget_visits: Optional[Dict[str, int]] = None, screen_width: int = 1080, screen_height: int = 1920, is_first_visit: bool = True) -> str:
        """
        [3] Widget Information - 鏀寔娓愯繘寮忔姭闇?

        Args:
            widgets: List of widget dicts with keys:
                - text or resource_id: Widget identifier
                - category: Widget type (Button, EditText, etc.)
                - original_text: For EditText, the current/hint text content
                - nearby_label: For CheckBox/Switch, the associated text label
                - bounds: Widget position bounds (e.g., "[901,1058][1038,1184]")
            widget_visits: Optional dict mapping widget_identifier to visit count
            screen_width: Screen width in pixels (default 1080)
            screen_height: Screen height in pixels (default 1920)
            is_first_visit: 鏄惁棣栨璁块棶璇?Activity
                - True: 涓嶆樉绀?Visits 淇℃伅锛屽紩瀵艰嚜鐢辨帰绱?
                - False: 鏄剧ず宸叉祴璇?Widget 淇℃伅锛屽紩瀵兼帰绱㈡湭娴嬭瘯鎺т欢

        Returns:
            Formatted widget information string with progressive disclosure
        """
        if not widgets:
            return "The widgets which can be operated are: none"

        lines = [f"Screen Size: {screen_width} x {screen_height}",
                 "All coordinates are based on this resolution.",
                 ""]

        widget_names = []
        for widget in widgets:
            widget_id = widget.get("text", "") or widget.get("resource_id", "")
            if "/" in widget_id:
                widget_id = widget_id.split("/")[-1]
            widget_names.append(widget_id)
        widget_name_set = set(widget_names)

        # 娓愯繘寮忔姭闇诧細鏍规嵁棣栨璁块棶閫夋嫨涓嶅悓鐨勬爣棰樺拰寮曞璇?
        if is_first_visit:
            lines.append("The widgets which can be operated are:")
        else:
            # 杩斿洖璁块棶锛氭坊鍔犲紩瀵艰
            tested_widgets = [
                _clip_text(k, 60)
                for k, v in widget_visits.items()
                if v > 0 and k in widget_name_set
            ] if widget_visits else []
            if tested_widgets:
                lines.append(f"You have already tested these widgets: {', '.join(tested_widgets[:5])}")
                lines.append("Please explore other untested widgets on this page.")
                lines.append("")
            lines.append("All widgets on this page:")

        for widget in widgets:
            # Get widget identifier (prefer text, then resource_id)
            widget_id = widget.get("text", "") or widget.get("resource_id", "")
            if "/" in widget_id:
                widget_id = widget_id.split("/")[-1]
            # Get category
            category = widget.get("category", "Widget")

            # Get original_text for EditText content display
            original_text = widget.get("original_text", "")

            # Get nearby_label for CheckBox/Switch
            nearby_label = widget.get("nearby_label", "")

            # Get bounds position info (NEW: for visual positioning)
            bounds = widget.get("bounds", "")
            position_info = ""
            if bounds:
                # Simplify: show bounds directly for LLM visual positioning
                position_info = f', Position: {bounds}'

            # Build field part for EditText (using content_desc for field differentiation)
            # 渚嬪 AnkiDroid 涓?Front/Back 瀛楁鏈夌浉鍚?resource-id锛岄€氳繃 content_desc 鍖哄垎
            field_part = ""
            content_desc = widget.get("content_desc", "")
            if category == "EditText" and content_desc and content_desc.strip():
                field_part = f', Field: "{_clip_text(content_desc, 80)}"'

            # Build content part for EditText
            content_part = ""
            if category == "EditText" and original_text:
                content_part = f', Current Input: "{_clip_text(original_text, 80)}"'

            # Build label part for CheckBox/Switch/RadioButton
            label_part = ""
            if nearby_label and category in ["CheckBox", "Switch", "RadioButton", "ToggleButton"]:
                label_part = f', Label: "{_clip_text(nearby_label, 80)}"'

            # 娓愯繘寮忔姭闇诧細棣栨璁块棶涓嶆樉绀?Visits
            if is_first_visit:
                visits_info = ""  # 棣栨璁块棶锛氫笉鏄剧ず
            else:
                visits = widget_visits.get(widget_id, 0) if widget_visits else 0
                visits_info = f', Visits: {visits}'

            # Format line (order: category -> field -> label -> content -> position -> visits)
            lines.append(f"  - {widget_id} ({category}{field_part}{label_part}{content_part}{position_info}{visits_info})")

        # 娣诲姞绾︽潫鎻愮ず
        lines.append("")
        lines.append("鈿狅笍 IMPORTANT: You MUST select Widget/OperationWidget names from the list above.")
        lines.append("DO NOT invent or guess widget names. Use EXACT names as shown above.")
        lines.append(f"Available widgets: {', '.join(widget_names[:10])}{'...' if len(widget_names) > 10 else ''}")

        return "\n".join(lines)

    @staticmethod
    def action_operation_question() -> str:
        """
        [4] Action Operation Question - Non-input operations

        Returns:
            Operation question string
        """
        return "What operation is required? (Operation [click/double-click/long press/scroll] + <Widget Name>)\n鈿狅笍 Widget Name MUST be from the widget list above."

    @staticmethod
    def input_operation_question() -> str:
        """
        [5] Input Operation Question

        Returns:
            Input operation question string
        """
        return "Please generate the input text in sequence, and the operation after input. (<Widget name> + <Input Content>, ...)\n鈿狅笍 Widget Name MUST be from the widget list above."

    @staticmethod
    def testing_feedback(widget_identifier: str) -> str:
        """
        [6] Testing Feedback - Widget Not Found

        Args:
            widget_identifier: The widget that was not found

        Returns:
            Widget not found feedback string
        """
        return (
            f"鉂?ERROR: Widget '{widget_identifier}' was NOT FOUND on the current page.\n"
            "This usually means you used a widget name that is NOT in the widget list.\n"
            "You MUST select a widget name from the provided list above.\n"
            "Please reselect a valid widget from the list."
        )

    @staticmethod
    def operation_questions() -> str:
        """
        Combined operation questions ([4] and [5])

        Returns:
            Combined operation questions string
        """
        return (
            "What operation is required? (Operation [click/double-click/long press/scroll] + <Widget Name>)\n"
            "鈿狅笍 Widget Name MUST be from the widget list above.\n\n"
            "Please generate the input text in sequence, and the operation after input. (<Widget name> + <Input Content>, ...)\n"
            "鈿狅笍 Widget Name MUST be from the widget list above."
        )


class FunctionMemoryTemplate:
    """Function Memory prompt templates for Explored Functions, Covered Activities, History, and Function Query"""

    @staticmethod
    def _relative_history_label(offset: int) -> str:
        """Return a relative label for history entries shown newest-first."""
        if offset == 1:
            return "Last step"
        return f"{offset} steps ago"

    @staticmethod
    def explored_function(function_visits: Dict[str, Dict]) -> str:
        """
        [1] Explored Function - From LLM summarization

        Args:
            function_visits: Dict mapping function_name to {visits: int, status: str}
                status can be "tested" or "testing"

        Returns:
            Formatted explored function string
            Format: List of tested functions: "Function: <FunctionName>. Visits: <Visits>. Status: <Status>", ...
        """
        if not function_visits:
            return 'List of tested functions: None'

        parts = []
        for name, info in function_visits.items():
            visits = info.get("visits", 0)
            status = info.get("status", "unvisited")
            # Format: "Function: <Name>. Visits: <Visits>. Status: <Status>"
            parts.append(f'"Function: {name}. Visits: {visits}. Status: {status}"')

        functions_str = ", ".join(parts)
        return f"List of tested functions: {functions_str}"

    @staticmethod
    def covered_activities(activities: List[Dict]) -> str:
        """
        [2] Activity List - From Manifest (ALL activities with visits)

        Args:
            activities: List of activity dicts with:
                - name: Activity name
                - visit_time: Number of visits (0 = unvisited)
                - status: "visited" or "unvisited"

        Returns:
            Formatted activity list string
            Format: Activity List (try to cover ALL activities):
                    "Activity: <ActivityName>. Visits: <VisitTime>", ...
        """
        if not activities:
            return 'Activity List: None'

        parts = []
        for activity in activities:
            name = activity.get("name", "Unknown")
            visit_time = activity.get("visit_time", 0)
            status = activity.get("status", "unvisited")

            # 鏍囪鏈闂殑 Activity
            # 鍙渶瑕佹鏌?status锛屽洜涓?visit_time > 0 鏃?status 蹇呯劧鏄?"visited"
            if status == "unvisited":
                parts.append(f'"Activity: {name}. Visits: {visit_time} (UNVISITED)"')
            else:
                parts.append(f'"Activity: {name}. Visits: {visit_time}"')

        activities_str = ", ".join(parts)

        return f'''Activity List (Try to cover ALL activities):
{activities_str}.'''

    @staticmethod
    def latest_tested_history(history: List[Dict]) -> str:
        """
        [3] History of Latest Tested Pages and Operations

        Args:
            history: List of history entries (most recent first), each with:
                - activity_name: The Activity tested
                - operation: The operation performed (e.g., "Click")
                - target_widget: The widget operated on
                - page_description: Description of the page before operation
                - visual_description: Visual description (legacy, for compatibility)

        Returns:
            Formatted history string for LLM to judge operation effectiveness
        """
        if not history:
            return "History: None"

        lines = [
            "## Recent Test History",
            "",
            "",
        ]

        for i, entry in enumerate(history[:10], 1):
            activity_name = entry.get("activity_name", "Unknown")
            operation = entry.get("operation", "click")
            target_widget = _clip_text(entry.get("target_widget", ""), 80) or "N/A"
            page_description = _clip_text(
                entry.get("page_description", "") or entry.get("visual_description", ""),
                180
            )
            function_phase = _clip_text(entry.get("function_phase", ""), 60)
            verification_target = _clip_text(entry.get("verification_target", ""), 140)
            success = entry.get("success", True)

            status_str = "success" if success else "failed"
            relative_label = FunctionMemoryTemplate._relative_history_label(i)
            lines.append(f"### {relative_label} [{status_str}]")
            lines.append(f"**Activity**: {activity_name}")
            lines.append(f"**Action**: {operation} 鈫?{target_widget}")
            if function_phase:
                lines.append(
                    f"**Function Phase**: {function_phase}; "
                    f"Function_End={bool(entry.get('function_end'))}"
                )
            if verification_target:
                lines.append(f"**Verification Target**: {verification_target}")

            # Page description - important for context
            if page_description:
                lines.append(f"**Page Before**: {page_description}")


            lines.append("")  # Separator between steps

        return "\n".join(lines)

    @staticmethod
    def function_query(current_function: Optional[str] = None, current_status: Optional[str] = None) -> str:
        """
        [4] Function Query - Ask LLM to summarize current function

        Args:
            current_function: Currently testing function name (optional)
            current_status: Current function status (optional)

        Returns:
            Formatted function query string (JSON format defined in System Prompt)
        """
        current_info = ""
        if current_function and current_status:
            current_info = f" (Current: {current_function}, Status: {current_status})"

        return (
            f"What is the function currently being tested? Are we testing a new function?{current_info}\n"
            "Output the JSON action following the MANDATORY OUTPUT FORMAT defined in the system prompt."
        )

class MultimodalPromptTemplate:
    """Multimodal prompt templates for visual context and bug analysis"""

    @staticmethod
    def visual_context_intro() -> str:
        """
        Introduction for multimodal visual context

        Returns:
            Visual context introduction string
        """
        return """## Visual Context

I have attached screenshot(s) of the current Android app screen. Please use both the visual information from the screenshot(s) and the textual UI structure information below to make your decision.

When analyzing the screenshot:
1. Identify visible UI elements (buttons, text fields, icons, etc.)
2. Note any visual cues (colors, icons, layouts)
3. Compare visual state with the textual widget information
4. Look for any visual anomalies or unexpected states

"""

    @staticmethod
    def bug_analysis_prompt(
        bug_type: str,
        description: str,
        activity_name: str = "",
        operation: str = "",
        widget: str = "",
        crash_log: str = ""
    ) -> str:
        """
        Build bug analysis prompt

        Args:
            bug_type: Type of bug (crash, logic_error, ui_state_error, etc.)
            description: Human-readable description
            activity_name: Current activity
            operation: Operation that triggered the bug
            widget: Widget involved
            crash_log: Crash log if applicable

        Returns:
            Bug analysis prompt string
        """
        parts = [
            "# Bug Analysis Request",
            "",
            "Analyze the following bug detected during automated testing. I have attached screenshot(s) for visual context.",
            "",
            "## Bug Information",
            f"- **Type**: {bug_type}",
            f"- **Description**: {description}",
        ]

        if activity_name:
            parts.append(f"- **Activity**: {activity_name}")
        if operation:
            parts.append(f"- **Trigger Operation**: {operation}")
        if widget:
            parts.append(f"- **Widget Involved**: {widget}")

        if crash_log:
            # Truncate long crash logs
            truncated_log = crash_log[:2000] if len(crash_log) > 2000 else crash_log
            parts.append(f"\n## Crash Log\n```\n{truncated_log}\n```\n")

        parts.append("""
## Required Analysis

Please provide a comprehensive analysis including:

1. **Root Cause Analysis** 
   - What is the underlying technical cause?
   - Why did this bug occur?
   - What conditions trigger it?

2. **Severity Assessment**
   - Critical: App crash, data loss, security vulnerability
   - Error: Feature malfunction, incorrect output
   - Warning: UX issues, potential problems
   - Info: Minor issues, suggestions

3. **Category Classification**
   - crash: Application crash
   - calculation_error: Wrong numerical results
   - data_inconsistency: Cross-page data mismatch
   - function_anomaly: Feature not working as expected

4. **Fix Suggestion**
   - What code changes are needed?
   - Any configuration changes required?

5. **Reproduction Steps**
   - Clear step-by-step instructions to reproduce

## Output Format

Please output your analysis in JSON format:

```json
{
  "root_cause": "Detailed analysis of the root cause",
  "severity": "Critical|Error|Warning|Info",
  "category": "bug_category",
  "fix_suggestion": "Suggested fix",
  "reproduction_steps": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ..."
  ],
  "confidence": 0.8
}
```
""")
        return "\n".join(parts)

    @staticmethod
    def logic_error_detection_prompt(
        error_type: str,
        expected_value: str,
        actual_value: str,
        context: str = ""
    ) -> str:
        """
        Build logic error detection prompt

        Args:
            error_type: Type of logic error
            expected_value: Expected value/result
            actual_value: Actual value/result
            context: Additional context

        Returns:
            Logic error detection prompt string
        """
        return f"""# Logic Error Detection Request

I have attached screenshot(s) showing the current application state. Please analyze for potential logic errors.

## Error Information

- **Error Type**: {error_type}
- **Expected Value/Behavior**: {expected_value}
- **Actual Value/Behavior**: {actual_value}
{f"- **Context**: {context}" if context else ""}

## Analysis Tasks

1. **Verify the Error**
   - Confirm whether this is a genuine bug
   - Identify what went wrong

2. **Determine Severity**
   - How critical is this error?
   - Does it affect core functionality?

3. **Suggest Fix**
   - What needs to be changed?
   - Any workarounds?

## Output Format

```json
{{
  "is_genuine_error": true,
  "root_cause": "Explanation",
  "severity": "Critical|Error|Warning|Info",
  "fix_suggestion": "How to fix",
  "confidence": 0.8
}}
```
"""

    @staticmethod
    def visual_anomaly_prompt() -> str:
        """
        Prompt for detecting visual anomalies

        Returns:
            Visual anomaly detection prompt
        """
        return """# Visual Anomaly Detection

Please analyze the attached screenshot(s) for any visual anomalies:

## Check for:

1. **Rendering Issues**
   - Overlapping elements
   - Cut-off text
   - Missing icons/images
   - Incorrect colors

2. **Layout Problems**
   - Elements out of place
   - Broken responsive design
   - Hidden/obscured elements

3. **UI State Issues**
   - Incorrect button states (disabled when should be enabled)
   - Wrong text displayed
   - Missing labels

4. **Unexpected Elements**
   - Error dialogs
   - Toast messages
   - Unexpected popups

## Output Format

If any issues found:
```json
{
  "issues_found": true,
  "anomalies": [
    {
      "type": "rendering|layout|state|unexpected",
      "description": "What's wrong",
      "location": "Where on screen",
      "severity": "Critical|Error|Warning|Info"
    }
  ]
}
```

If no issues:
```json
{
  "issues_found": false,
  "notes": "Any observations"
}
```
"""

    @staticmethod
    def comparison_prompt(
        description: str = "Compare the two screenshots"
    ) -> str:
        """
        Prompt for comparing two screenshots

        Args:
            description: Description of what to compare

        Returns:
            Comparison prompt string
        """
        return f"""# Screenshot Comparison Request

{description}

Please analyze both screenshots and identify:

1. **Differences**
   - What changed between the two states?
   - Are the changes expected or unexpected?

2. **State Transition**
   - Did the action have the intended effect?
   - Any unintended side effects?

3. **Anomalies**
   - Any unexpected visual changes?
   - Any errors or warnings appeared?

## Output Format

```json
{{
  "differences": [
    {{"element": "...", "before": "...", "after": "..."}}
  ],
  "transition_successful": true,
  "anomalies": [],
  "summary": "Brief summary of the comparison"
}}
```
"""


class SupervisorPromptTemplate:
    """鐩戠鑰呮彁绀鸿瘝妯℃澘 - 鐢ㄤ簬鍋囬槼鎬у鏌ュ拰婕忔妫€娴?"""

    @staticmethod
    def false_positive_review_prompt(bug_report, context: Dict) -> str:
        """
        鍋囬槼鎬у鏌ユ彁绀鸿瘝

        Args:
            bug_report: BugReport 瀵硅薄锛堥渶瀵煎叆 BugReport 绫诲瀷锛?

        Returns:
            鏍煎紡鍖栫殑鍋囬槼鎬у鏌ユ彁绀鸿瘝
        """
        # 瀵煎叆妫€鏌ワ細bug_report 搴旀湁 category, severity, description, activity, operation, widget 灞炴€?
        operation_history = context.get('operation_history', [])
        page_description = context.get('page_description') or 'Unknown'
        reported_bugs = context.get('reported_bugs', [])
        ui_state_str = context.get('ui_state_prompt') or SupervisorPromptTemplate._format_ui_state(
            context.get('ui_state', {})
        )
        widget_interactivity_str = (
            context.get('widget_interactivity_prompt')
            or SupervisorPromptTemplate._format_widget_interactivity(context.get('current_widgets', []))
        )
        causal_context = context.get('causal_context') or SupervisorPromptTemplate._format_causal_context(context)

        history_str = SupervisorPromptTemplate._format_history(operation_history)
        reported_bug_str = SupervisorPromptTemplate._format_reported_bugs(reported_bugs)

        # 瀹夊叏鑾峰彇 bug_report 灞炴€?
        try:
            category = bug_report.category.value if hasattr(bug_report.category, 'value') else str(bug_report.category)
            severity = bug_report.severity.value if hasattr(bug_report.severity, 'value') else str(bug_report.severity)
            description = bug_report.description or "No description"
            activity = bug_report.activity or "Unknown"
            operation = bug_report.operation or "Unknown"
            widget = bug_report.widget or "Unknown"
        except Exception:
            category = "unknown"
            severity = "Error"
            description = str(bug_report)
            activity = "Unknown"
            operation = "Unknown"
            widget = "Unknown"

        return f"""# False Positive Review Request

You are reviewing a bug report generated by the AI tester. Determine if this is a genuine bug or a false positive.

## Bug Report Under Review

- **Type**: {category}
- **Severity**: {severity}
- **Description**: {description}
- **Activity**: {activity}
- **Trigger Operation**: {operation} on {widget}

## Context

### Recent Operations
{history_str}

### Bug Assertion Context
- **Page Before Assertion**: {page_description}

### Causal Evidence Context
{causal_context}


### Structured UI State
{ui_state_str}

### Current Widget Interactivity Facts
{widget_interactivity_str}

### Already Reported Bugs
{reported_bug_str}

## Visual Evidence
[Attached: Current screenshot(s). These screenshots represent the UI state at the moment the bug was asserted.]

## Review Checklist

1. **Visual Evidence Check** - Does the screenshot support the bug claim?
2. **Causal Evidence Check** - Was the reported bug caused by an already executed operation, or is it only inferred from the Explorer's proposed next action?
4. **False Positive Indicators**:
   - Temporary UI state (loading, transition)
   - Wrong context comparison
   - Bug already fixed or self-resolved
   - Same symptom/root cause has already been reported above
   - Business-state mismatch after an input-only edit, before any submit/confirm/navigation verification

## Decision Rules

- The Explorer's current output action has not been executed yet. Do not treat it as the trigger.
- When judging disabled/clickability issues, distinguish functional disablement from visual-state mismatch.
- If widget facts show `enabled=false` or `clickable=false`, or a verifying tap fails, this may be a functional disabled/unresponsive bug.
- If widget facts show `enabled=true` and `clickable=true` but the screenshot visually looks disabled/grey/low-contrast, do not claim the control is functionally disabled. You may classify it as a visual UI state mismatch (`ui_state_error`, usually `Warning`) only when the visual style is clearly misleading.
- If the evidence only shows an edited-but-unsubmitted field conflicting with an older confirmation/result, classify it as a false positive for now and set `requires_more_verification` to true.
- Confirm a genuine data inconsistency only when a completed submit/save/confirm/navigation action should have synchronized the data and the current UI contradicts that completed action.
- If evidence is insufficient but suspicious, use `is_false_positive=true` with a reason explaining the missing verification step.

## Output Format

Output ONLY a single JSON code block:

```json
{{
  "is_false_positive": false,
  "requires_more_verification": false,
  "reason": "Detailed explanation for your decision",
  "confidence": 0.85,
  "reasoning": "Step-by-step reasoning process"
}}
```

Set `is_false_positive` to `true` if this is a false positive, `false` if genuine bug.
Provide detailed explanation in `reason` field."""

    @staticmethod
    def missed_bug_detection_prompt(context: Dict) -> str:
        """
        婕忔妫€娴嬫彁绀鸿瘝

        Args:
            context: 涓婁笅鏂囦俊鎭紝鍖呭惈 current_activity, operation_history, pending_verifications

        Returns:
            鏍煎紡鍖栫殑婕忔妫€娴嬫彁绀鸿瘝
        """
        activity_name = context.get('current_activity', 'Unknown')
        operation_history = context.get('operation_history', [])
        pending_verifications = context.get('pending_verifications', [])
        reported_bugs = context.get('reported_bugs', [])
        ui_state_str = context.get('ui_state_prompt') or SupervisorPromptTemplate._format_ui_state(
            context.get('ui_state', {})
        )
        widget_interactivity_str = (
            context.get('widget_interactivity_prompt')
            or SupervisorPromptTemplate._format_widget_interactivity(context.get('current_widgets', []))
        )

        history_str = SupervisorPromptTemplate._format_history(operation_history)
        verif_str = SupervisorPromptTemplate._format_verifications(pending_verifications)
        reported_bug_str = SupervisorPromptTemplate._format_reported_bugs(reported_bugs)

        return f"""# Missed Bug Detection Review

Review the current application state to identify any bugs that may have been missed by the tester.

## Current State
- **Activity**: {activity_name}
- **Recent Operations**: {len(operation_history)} steps

## Structured UI State
{ui_state_str}

## Current Widget Interactivity Facts
{widget_interactivity_str}

## Recent Test History
{history_str}

## Pending Verifications
{verif_str}

## Already Reported Bugs
{reported_bug_str}

## Detection Checklist

Check for the following bug types that may have been missed:

1. **Visual Anomalies**
   - Error messages visible on screen
   - UI rendering issues (overlapping, cut-off, missing)
   - Incorrect colors or icons

2. **State Inconsistencies**
   - Data mismatch between what was entered and what's displayed
   - Unexpected page state
   - Wrong data values
   - Current UI does not satisfy a supported predicted effect or verification target of a recent completed operation
   - Only report committed/saved/submitted state mismatches. If the latest relevant action was input-only, treat business-result mismatches as needing more verification.

3. **Functional Issues**
   - Unresponsive elements
   - Incorrect feedback after action
   - Feature not working as expected

Before adding a missed bug, compare it with **Already Reported Bugs**. Do not report duplicates with the same symptom/root cause.
Do not add a missed bug when the observed issue would require a submit/confirm/navigation action that has not happened yet.
For disabled/clickability claims, distinguish functional disablement from visual-state mismatch:
- If **Current Widget Interactivity Facts** show `enabled=false` or `clickable=false`, or a verifying tap fails, this may be a functional disabled/unresponsive bug.
- If the facts show `enabled=true` and `clickable=true` but the screenshot visually looks disabled/grey/low-contrast, do not claim the control is functionally disabled. You may report it only as a visual UI state mismatch (`ui_state_error`, usually `Warning`) when the style is clearly misleading.

Severity policy for missed bugs:
- Critical: crash, security issue, or committed user data is lost/missing after a confirmed submit/save/book/place-order action.
- Error: confirmed feature malfunction, incorrect calculation, wrong navigation, wrong business result without data loss, or UI state issue that blocks the main flow.
- Warning: non-blocking visual/UX/UI state issue, transient overlay/focus issue, or a possible issue that still needs verification.
- Use the same severity for the same root cause across steps/runs.

## Output Format

Output ONLY a single JSON code block:

```json
{{
  "bugs_found": false,
  "missed_bugs": [
    {{
      "type": "ui_state_error|data_inconsistency|function_anomaly|calculation_error",
      "severity": "Critical|Error|Warning",
      "description": "Detailed description of the bug",
      "evidence": "Visual or contextual evidence"
    }}
  ],
  "confidence": 0.8,
  "reasoning": "Analysis process explaining why these bugs were detected"
}}
```

If no bugs found, set `bugs_found` to `false` and `missed_bugs` to empty array.
If bugs found, set `bugs_found` to `true` and list each bug in `missed_bugs`.
Do not output testing strategy suggestions for the tester. This review is for offline bug auditing only."""

    @staticmethod
    def behavior_chain_review_prompt(context: Dict) -> str:
        """
        搴忓垪绾ц涓烘鍗峰鏌ユ彁绀鸿瘝銆?

        Args:
            context: 鍖呭惈 active_trace/behavior_chain_summary/current_activity 绛夎瘉鎹笂涓嬫枃

        Returns:
            鏍煎紡鍖栫殑妗堝嵎瀹℃煡鎻愮ず璇?
        """
        activity_name = context.get('current_activity', 'Unknown')
        operation_history = context.get('operation_history', [])
        reported_bugs = context.get('reported_bugs', [])
        trace = (
            context.get('active_trace')
            or context.get('behavior_dossier')
            or {}
        )
        behavior_summary = (
            context.get('behavior_chain_summary')
            or SupervisorPromptTemplate._format_behavior_chain_evidence(trace)
        )
        trigger = context.get('trigger_evaluation') or {}
        pending = context.get('pending_verification') or {}
        verification_target = (
            context.get('verification_target')
            or (trace or {}).get('verification_target')
            or pending.get('target')
            or ''
        )
        ui_state_str = context.get('ui_state_prompt') or SupervisorPromptTemplate._format_ui_state(
            context.get('ui_state', {})
        )
        widget_interactivity_str = (
            context.get('widget_interactivity_prompt')
            or SupervisorPromptTemplate._format_widget_interactivity(context.get('current_widgets', []))
        )

        history_str = SupervisorPromptTemplate._format_history(operation_history)
        reported_bug_str = SupervisorPromptTemplate._format_reported_bugs(reported_bugs)
        evidence_str = SupervisorPromptTemplate._format_behavior_chain_evidence(trace)

        return f"""# Evidence-Grounded Behavior Chain Review

You are auditing a completed or verification-stage functional behavior chain. Decide whether the chain shows a non-crash functional bug.

Important: The Explorer's narrative is only a claim. You must check it against the raw evidence: screenshots, XML paths, Activity changes, UI/content fingerprints, visible widgets, and current screenshot attachments.

## Current State
- **Activity**: {activity_name}
- **Verification Target**: {verification_target or 'Not specified'}
- **Pending Verification**: {_clip_text(pending.get('text') if isinstance(pending, dict) else pending, 240)}

## Trigger Evaluation
- **Score**: {trigger.get('score', 'unknown')}
- **Reasons**: {', '.join(trigger.get('reasons', []) or []) or 'unknown'}
- **Phase Signal**: {trigger.get('phase_signal', 'unknown')}

## Behavior Dossier Summary
{behavior_summary}

## Raw Evidence Index
{evidence_str}

## Recent Operation History
{history_str}

## Structured UI State
{ui_state_str}

## Current Widget Interactivity Facts
{widget_interactivity_str}

## Already Reported Bugs
{reported_bug_str}

## Review Rules

1. Verify that each important narrative claim is supported by screenshot/XML/widget/state evidence.
2. Do not report a bug only because the Explorer story sounds plausible.
3. A data inconsistency requires a completed save/submit/confirm/book/order action and a later result/history/list/detail view that contradicts it.
4. If the app only reached a confirmation page and the persistent history/list/detail view has not been checked, prefer `needs_more_verification` unless the confirmation itself visibly contradicts the committed action.
5. If the chain is blocked or repeats unchanged states, decide whether this is a real blocking function anomaly or whether more navigation/verification is needed.
6. Avoid duplicate reports by comparing with Already Reported Bugs.

## Output Format

Output ONLY a single JSON code block:

```json
{{
  "verdict": "bug|no_bug|needs_more_verification",
  "bug_type": "data_inconsistency|function_anomaly|ui_state_error|calculation_error|null",
  "severity": "Critical|Error|Warning|null",
  "story_supported_by_evidence": true,
  "unsupported_claims": [],
  "missing_evidence": [],
  "failure_step": null,
  "missing_verification": null,
  "reason": "Detailed evidence-based explanation",
  "confidence": 0.85
}}
```"""

    @staticmethod
    def _format_behavior_chain_evidence(trace: Dict) -> str:
        """Format BehaviorDossier raw evidence for Supervisor review."""
        if not trace:
            return "No behavior dossier evidence available."

        steps = trace.get("steps") or []
        global_story = trace.get("global_story") or {}
        lines = [
            f"Trace: {trace.get('trace_id', 'unknown')} | Goal: {_clip_text(trace.get('function_goal'), 180)} | Phase: {trace.get('phase', 'unknown')}",
        ]
        if global_story.get("case_story_so_far"):
            lines.append(f"Case story so far: {_clip_text(global_story.get('case_story_so_far'), 3000)}")
        for label, key in (
            ("Verified facts", "verified_facts"),
            ("Hypotheses", "hypotheses"),
            ("Contradiction candidates", "contradiction_candidates"),
        ):
            values = global_story.get(key) or []
            if values:
                lines.append(f"{label}: " + " | ".join(_clip_text(item, 180) for item in values[:10]))
        pending = trace.get("pending_verification") or {}
        if pending:
            lines.append(
                f"Pending verification: {_clip_text(pending.get('text'), 180)} "
                f"Target: {_clip_text(pending.get('target'), 120)}"
            )

        if not steps:
            lines.append("No steps in dossier.")
            return "\n".join(lines)

        for step in steps[-8:]:
            action = step.get("action") or {}
            narrative = step.get("step_narrative") or step.get("behavior_narrative") or {}
            target = action.get("operation_widget") or action.get("widget") or step.get("target_widget") or "N/A"
            evidence_paths = [
                f"before_png={step.get('screenshot_before_path')}" if step.get("screenshot_before_path") else "",
                f"after_png={step.get('screenshot_after_path')}" if step.get("screenshot_after_path") else "",
                f"before_xml={step.get('xml_before_path')}" if step.get("xml_before_path") else "",
                f"after_xml={step.get('xml_after_path')}" if step.get("xml_after_path") else "",
            ]
            evidence_paths = [item for item in evidence_paths if item]
            visible_after = []
            for widget in (step.get("widgets_after") or [])[:8]:
                text = widget.get("text") or widget.get("content_desc") or widget.get("resource_id") or ""
                if text:
                    visible_after.append(_clip_text(text, 45))
            lines.append(
                "\n".join([
                    f"Step {step.get('step_index')}: [{step.get('activity_before')} -> {step.get('activity_after') or step.get('activity_before')}] {action.get('operation') or 'unknown'} -> {target}",
                    f"  phase={step.get('function_phase')} end={step.get('function_end')} ui_changed={step.get('ui_changed')} activity_changed={step.get('activity_changed')}",
                    f"  actual={_clip_text(step.get('actual_observation'), 180)}",
                    f"  narrative_scene={_clip_text(narrative.get('current_scene') or narrative.get('scene') or narrative.get('narrative'), 220)}",
                    f"  narrative_evidence={_clip_text(narrative.get('visible_evidence'), 160)}",
                    f"  visible_after={'; '.join(visible_after) if visible_after else 'not captured'}",
                    f"  evidence_paths={'; '.join(evidence_paths) if evidence_paths else 'not captured'}",
                ])
            )

        if len(steps) > 8:
            lines.append(f"... {len(steps) - 8} earlier step(s) omitted.")
        return "\n".join(lines)

    @staticmethod
    def _format_history(operation_history: List[Dict]) -> str:
        """鏍煎紡鍖栨搷浣滃巻鍙?"""
        if not operation_history:
            return "No recent operations."

        lines = []
        # operation_history should be chronological here. Keep the most recent
        # five entries, but display them in real execution order.
        recent_ops = operation_history[-5:] if len(operation_history) > 5 else operation_history

        for i, entry in enumerate(recent_ops, 1):
            step_index = entry.get('step_index', i)
            op = entry.get('operation', 'unknown')
            widget = entry.get('target_widget', 'unknown')
            activity = entry.get('activity_name', 'unknown')
            success = "OK" if entry.get('success', True) else "FAIL"
            phase = entry.get('action_phase') or ''
            back_effect = entry.get('back_effect') or ''
            focused_before = SupervisorPromptTemplate._format_focused_node(
                (entry.get('ui_state_before') or {}).get('focused') or {}
            )
            focused_after = SupervisorPromptTemplate._format_focused_node(
                (entry.get('ui_state_after') or {}).get('focused') or {}
            )

            detail_parts = []
            if phase:
                detail_parts.append(f"phase={phase}")
            if back_effect:
                detail_parts.append(f"back_effect={back_effect}")
            if focused_before or focused_after:
                detail_parts.append(f"focused: {focused_before or 'unknown'} -> {focused_after or 'unknown'}")
            line = f"Step {step_index}. [{success}] [{activity}] {op} -> {widget}"
            if detail_parts:
                line += "\n   " + "; ".join(detail_parts)
            lines.append(line)

        return "\n".join(lines)

    @staticmethod
    def _format_causal_context(context: Dict) -> str:
        """Format action-causality facts for Supervisor review."""
        asserted_action = context.get('asserted_action') or {}
        latest = context.get('latest_completed_operation') or {}

        lines = [
            "The bug assertion is made before executing the Explorer's current proposed action.",
        ]

        if asserted_action:
            asserted_op = asserted_action.get("operation") or "unknown"
            asserted_widget = (
                asserted_action.get("widget")
                or asserted_action.get("operation_widget")
                or "unknown"
            )
            lines.append(f"- Proposed but not yet executed action: {asserted_op} -> {asserted_widget}")
        if latest:
            latest_op = latest.get("operation") or "unknown"
            latest_widget = latest.get("target_widget") or "unknown"
            latest_phase = latest.get("action_phase") or "unknown"
            latest_back_effect = latest.get("back_effect") or ""
            focused_before = SupervisorPromptTemplate._format_focused_node(
                (latest.get("ui_state_before") or {}).get("focused") or {}
            )
            focused_after = SupervisorPromptTemplate._format_focused_node(
                (latest.get("ui_state_after") or {}).get("focused") or {}
            )
            lines.append(
                f"- Last completed action: Step {latest.get('step_index', '?')} "
                f"[{latest.get('activity_name', 'unknown')}] {latest_op} -> {latest_widget} "
                f"(phase={latest_phase}, success={bool(latest.get('success', True))})"
            )
            if latest_back_effect:
                lines.append(f"- Last completed Back effect: {latest_back_effect}")
            if focused_before or focused_after:
                lines.append(f"- Focused field before/after last action: {focused_before or 'unknown'} -> {focused_after or 'unknown'}")
            if (latest_op or "").lower() in {"input", "type"} or latest_phase == "input":
                lines.append(
                    "- Causality warning: the last completed action was input-only. "
                    "Business-result mismatches usually require a later submit/confirm/navigation action before they can be confirmed."
                )

        return "\n".join(lines)

    @staticmethod
    def _format_focused_node(node: Dict) -> str:
        """Compact focused-node facts for history/causal context."""
        if not node:
            return ""
        class_name = (node.get("class") or "").split(".")[-1]
        text = _clip_text(node.get("text") or "", 60)
        bounds = node.get("bounds") or ""
        parts = [part for part in [class_name, f'text="{text}"' if text else "", bounds] if part]
        return " ".join(parts)

    @staticmethod
    def _format_verifications(pending_verifications: List[Dict]) -> str:
        """鏍煎紡鍖栧緟楠岃瘉鍒楄〃"""
        if not pending_verifications:
            return "No pending verifications."

        lines = []
        for i, v in enumerate(pending_verifications, 1):
            step_index = v.get('step_index', i)
            activity = v.get('activity_name', 'unknown')
            operation = v.get('operation', 'unknown')
            widget = v.get('target_widget', 'unknown')
            page_description = v.get('page_description') or v.get('visual_description') or 'Unknown'
            success = "success" if v.get('success', True) else "failed"
            action_phase = v.get('action_phase') or 'unknown'
            transient = v.get('transient_transition') or 'unknown'
            back_effect = v.get('back_effect') or ''
            ui_after = SupervisorPromptTemplate._format_ui_state(v.get('ui_state_after', {}))
            back_part = f"; Back Effect: {back_effect}" if back_effect else ""
            lines.append(
                f"Step {step_index}. [{success}] [{activity}] {operation} -> {widget}\n"
                f"   Action Phase: {action_phase}; UI Transition: {transient}{back_part}\n"
                f"   Page Before: {page_description}\n"
                f"   UI State After Action: {ui_after}\n"
            )

        return "\n".join(lines)

    @staticmethod
    def _format_ui_state(ui_state: Dict) -> str:
        """鏍煎紡鍖栫粨鏋勫寲 UI 鐘舵€佷簨瀹炪€?"""
        if not ui_state:
            return "No structured UI state available."
        layer = ui_state.get("transient_layer") or {}
        focused = SupervisorPromptTemplate._format_focused_node(ui_state.get("focused") or {})
        input_method = ui_state.get("input_method") or {}
        extras = []
        if focused:
            extras.append(f"focus={focused}")
        if input_method:
            if input_method.get("ime_visible"):
                ime = "visible"
            elif input_method.get("raw_ime_visible"):
                ime = "reported-visible-weak"
            else:
                ime = "hidden"
            extras.append(f"ime={ime}")
            if input_method.get("visibility_basis"):
                extras.append(f"ime_basis={input_method.get('visibility_basis')}")
        if not layer.get("active"):
            base = "Transient Layer: inactive"
            return base + (("; " + "; ".join(extras)) if extras else "")

        parts = [
            f"Transient Layer: active {layer.get('type', 'unknown')} "
            f"(confidence={float(layer.get('confidence', 0) or 0):.2f})"
        ]
        if layer.get("owner"):
            parts.append(f"owner={layer.get('owner')}")
        if layer.get("selected_option"):
            parts.append(f"selected={layer.get('selected_option')}")
        options = layer.get("options") or []
        if options:
            option_texts = []
            for option in options[:6]:
                text = option.get("text", "")
                if text:
                    option_texts.append(text + (" [selected]" if option.get("selected") else ""))
            if option_texts:
                parts.append("options=" + ", ".join(option_texts))
        parts.extend(extras)
        return "; ".join(parts)

    @staticmethod
    def _format_widget_interactivity(widgets: List[Dict]) -> str:
        """Format current widget enabled/clickable facts for Supervisor review."""
        if not widgets:
            return "No widget interactivity facts available."

        lines = []
        for widget in widgets[:25]:
            name = _clip_text(
                widget.get("text") or widget.get("content_desc") or widget.get("resource_id") or "unnamed",
                80,
            )
            class_name = (widget.get("class") or "Widget").split(".")[-1]
            enabled = str(widget.get("enabled")).lower()
            clickable = str(widget.get("clickable")).lower()
            bounds = widget.get("bounds") or ""
            lines.append(
                f"- {name} ({class_name}): enabled={enabled}, clickable={clickable}"
                f"{', bounds=' + bounds if bounds else ''}"
            )

        if len(widgets) > 25:
            lines.append(f"- ... {len(widgets) - 25} more widget(s) omitted")

        return "\n".join(lines)

    @staticmethod
    def _format_reported_bugs(reported_bugs: List[Dict]) -> str:
        """鏍煎紡鍖栧凡纭 Bug 鍒楄〃锛岀敤浜?Supervisor 鍘婚噸銆?"""
        if not reported_bugs:
            return "No confirmed bugs have been reported yet."

        lines = []
        for i, bug in enumerate(reported_bugs[-8:], 1):
            bug_id = bug.get("bug_id", "unknown")
            severity = bug.get("severity", "Unknown")
            category = bug.get("category", "unknown")
            activity = bug.get("activity", "Unknown")
            description = _clip_text(bug.get("description", ""), 150)
            lines.append(f"{i}. {bug_id} [{severity}/{category}] {activity}: {description}")
        return "\n".join(lines)


# Backward compatibility alias
TestHistoryTemplate = FunctionMemoryTemplate


# Convenience function for building complete prompts
def build_initial_prompt(
    app_name: str,
    activities_info: List[Dict],
    activity_name: str,
    widgets: List[Dict],
    widget_visits: Optional[Dict[str, int]],
    function_visits: Dict[str, Dict],
    covered_activities: List[Dict],
    operation_history: List[Dict],
    current_function: Optional[str] = None,
    current_status: Optional[str] = None,
    screen_width: int = 1080,  # NEW: 灞忓箷瀹藉害
    screen_height: int = 1920  # NEW: 灞忓箷楂樺害
) -> str:
    """
    Build complete initial phase prompt

    Combination: GUIContext[1,2,3,4,5] + FunctionMemory[1,2,3,4]

    Returns:
        Complete prompt string
    """
    parts = [
        GUIContextTemplate.app_info(app_name, activities_info),
        GUIContextTemplate.page_info(activity_name),
        GUIContextTemplate.widget_info(widgets, widget_visits, screen_width, screen_height),
        GUIContextTemplate.action_operation_question(),
        GUIContextTemplate.input_operation_question(),
        FunctionMemoryTemplate.explored_function(function_visits),
        FunctionMemoryTemplate.covered_activities(covered_activities),
        FunctionMemoryTemplate.latest_tested_history(operation_history),
        FunctionMemoryTemplate.function_query(current_function, current_status)
    ]

    return "\n\n".join(parts)


def build_test_prompt(
    activity_name: str,
    widgets: List[Dict],
    widget_visits: Optional[Dict[str, int]],
    function_visits: Dict[str, Dict],
    operation_history: List[Dict],
    current_function: Optional[str] = None,
    current_status: Optional[str] = None,
    screen_width: int = 1080,  # NEW: 灞忓箷瀹藉害
    screen_height: int = 1920  # NEW: 灞忓箷楂樺害
) -> str:
    """
    Build test phase prompt (after successful operation)

    Combination: "We successfully did the above operation." + GUIContext[2,3,4,5] + FunctionMemory[1,2,3,4]

    Returns:
        Complete prompt string
    """
    parts = [
        GUIContextTemplate.page_info(activity_name),
        GUIContextTemplate.widget_info(widgets, widget_visits, screen_width, screen_height),
        GUIContextTemplate.action_operation_question(),
        GUIContextTemplate.input_operation_question(),
        FunctionMemoryTemplate.explored_function(function_visits),
        FunctionMemoryTemplate.latest_tested_history(operation_history),
        FunctionMemoryTemplate.function_query(current_function, current_status)
    ]

    return "\n\n".join(parts)


def build_feedback_prompt(
    failed_widget: str,
    widgets: List[Dict],
    widget_visits: Optional[Dict[str, int]],
    function_visits: Dict[str, Dict],
    operation_history: List[Dict],
    current_function: Optional[str] = None,
    current_status: Optional[str] = None,
    screen_width: int = 1080,  # NEW: 灞忓箷瀹藉害
    screen_height: int = 1920  # NEW: 灞忓箷楂樺害
) -> str:
    """
    Build feedback phase prompt (after failed operation)

    Combination: GUIContext[6] + GUIContext[3,4,5] + FunctionMemory[3,4]

    Returns:
        Complete prompt stringFunction
    """
    parts = [
        GUIContextTemplate.testing_feedback(failed_widget),
        GUIContextTemplate.widget_info(widgets, widget_visits, screen_width, screen_height),
        GUIContextTemplate.action_operation_question(),
        GUIContextTemplate.input_operation_question(),
        FunctionMemoryTemplate.latest_tested_history(operation_history),
        FunctionMemoryTemplate.function_query(current_function, current_status)
    ]

    return "\n\n".join(parts)


# Test entry point
if __name__ == "__main__":
    # Test GUIContextTemplate
    print("=" * 60)
    print("Testing GUIContextTemplate")
    print("=" * 60)

    app_info = GUIContextTemplate.app_info(
        "Wikipedia",
        [
            {"name": "MainActivity", "visit_time": 2, "status": "visited"},
            {"name": "SearchActivity", "visit_time": 1, "status": "visited"},
            {"name": "SettingsActivity", "visit_time": 0, "status": "unvisited"}
        ]
    )
    print("[1] App Information:")
    print(app_info)

    print()
    print("[2] Page Information:")
    page_info = GUIContextTemplate.page_info("SearchActivity")
    print(page_info)

    print()
    print("[3] Widget Information:")
    widget_info = GUIContextTemplate.widget_info(
        [
            {"text": "search_input", "category": "EditText", "original_text": "android testing"},
            {"text": "Search", "category": "Button"},
            {"text": "Cancel", "category": "Button"}
        ],
        {"search_input": 1, "Search": 2, "Cancel": 0}
    )
    print(widget_info)

    print()
    print("[4] Action Operation Question:")
    print(GUIContextTemplate.action_operation_question())

    print()
    print("[5] Input Operation Question:")
    print(GUIContextTemplate.input_operation_question())

    print()
    print("[6] Testing Feedback:")
    print(GUIContextTemplate.testing_feedback("SubmitButton"))

    # Test FunctionMemoryTemplate
    print("\n" + "=" * 60)
    print("Testing FunctionMemoryTemplate")
    print("=" * 60)

    print("[1] Explored Function:")
    func_list = FunctionMemoryTemplate.explored_function({
        "Login": {"visits": 1, "status": "tested"},
        "Search": {"visits": 2, "status": "testing"}
    })
    print(func_list)

    print()
    print("[2] Covered Activities:")
    covered = FunctionMemoryTemplate.covered_activities([
        {"name": "MainActivity", "visit_time": 2, "status": "visited"},
        {"name": "SearchActivity", "visit_time": 1, "status": "visited"},
        {"name": "SettingsActivity", "visit_time": 0, "status": "unvisited"}
    ])
    print(covered)

    print()
    print("[3] Latest Tested History:")
    latest_ops = FunctionMemoryTemplate.latest_tested_history([
        {"activity_name": "MainActivity", "widgets_tested": [{"name": "Search", "visits": 1}, {"name": "Settings", "visits": 1}], "operation": "Click", "target_widget": "Search"},
        {"activity_name": "MainActivity", "widgets_tested": [{"name": "Login", "visits": 1}], "operation": "Click", "target_widget": "Login"}
    ])
    print(latest_ops)

    print()
    print("[4] Function Query:")
    print(FunctionMemoryTemplate.function_query())

    # Test complete prompt building
    print("\n" + "=" * 60)
    print("Testing Complete Initial Prompt")
    print("=" * 60)

    initial_prompt = build_initial_prompt(
        app_name="Wikipedia",
        activities_info=[
            {"name": "MainActivity", "visit_time": 2, "status": "visited"},
            {"name": "SearchActivity", "visit_time": 1, "status": "visited"},
            {"name": "SettingsActivity", "visit_time": 0, "status": "unvisited"}
        ],
        activity_name="SearchActivity",
        widgets=[
            {"text": "SearchBox", "category": "EditText"},
            {"text": "Search", "category": "Button"},
            {"text": "Cancel", "category": "Button"}
        ],
        widget_visits={"SearchBox": 1, "Search": 2, "Cancel": 0},
        function_visits={
            "Login": {"visits": 1, "status": "tested"},
            "Search": {"visits": 2, "status": "testing"}
        },
        covered_activities=[
            {"name": "MainActivity", "visit_time": 2, "status": "visited"},
            {"name": "SearchActivity", "visit_time": 1, "status": "visited"},
            {"name": "SettingsActivity", "visit_time": 0, "status": "unvisited"}
        ],
        operation_history=[
            {"activity_name": "MainActivity", "widgets_tested": [{"name": "Search", "visits": 1}], "operation": "Click", "target_widget": "Search"},
            {"activity_name": "MainActivity", "widgets_tested": [{"name": "Login", "visits": 1}], "operation": "Click", "target_widget": "Login"}
        ]
    )
    print(initial_prompt)
