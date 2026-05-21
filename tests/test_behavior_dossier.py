import json
import tempfile
import unittest
from pathlib import Path

from env_interactor.action_executor import ActionExecutor
from gui_extractor.ui_state_analyzer import analyze_ui_state, format_ui_state_for_prompt
from llm_agent.behavior_dossier import BehaviorDossierManager
from llm_agent.memory_manager import TestingSequenceMemorizer
from llm_agent.prompt_builder import PromptGenerator


class BehaviorDossierTests(unittest.TestCase):
    def setUp(self):
        self.executor = ActionExecutor()

    def _parse(self, payload):
        response = "```json\n" + json.dumps(payload) + "\n```"
        action = self.executor.parse_action_only(response)
        self.assertIsNotNone(action)
        return action

    def test_old_json_still_parses_without_narrative_fields(self):
        action = self._parse({
            "Page_Description": "Home page with a Search button.",
            "Function": "Search",
            "Status": "Yes",
            "Operation": "click",
            "Widget": "Search",
            "Bug_Detected": False,
            "Bug_Description": None,
        })

        self.assertEqual(action.operation, "click")
        self.assertEqual(action.widget, "Search")
        self.assertEqual(action.behavior_narrative, {})
        self.assertIsNone(action.function_phase)
        self.assertFalse(action.function_end)
        self.assertIsNone(action.verification_target)

    def test_new_json_parses_narrative_phase_and_verification_target(self):
        action = self._parse({
            "Page_Description": "Booking form is visible.",
            "Function": "Book a flight",
            "Status": "Yes",
            "Operation": "click",
            "Widget": "Book",
            "Behavior_Narrative": {
                "current_scene": "Flight details page with Book button.",
                "visible_evidence": ["Book button", "Flight SR516"],
                "current_goal": "Book a flight",
                "decision_rationale": "The flight is selected and ready to commit.",
                "expected_effect": "Confirmation summary should appear.",
                "uncertainty": "Trip history still needs verification.",
            },
            "Function_Phase": "committing",
            "Function_End": False,
            "Verification_Target": "My Trips list should contain SR516",
            "Bug_Detected": False,
            "Bug_Description": None,
        })

        self.assertEqual(action.behavior_narrative["current_goal"], "Book a flight")
        self.assertEqual(action.function_phase, "committing")
        self.assertFalse(action.function_end)
        self.assertEqual(action.verification_target, "My Trips list should contain SR516")

    def test_step_narrative_and_case_story_update_are_parsed(self):
        action = self._parse({
            "Page_Description": "Flight details page is visible.",
            "Function": "Book a flight",
            "Status": "Yes",
            "Operation": "click",
            "Widget": "Book",
            "Step_Narrative": {
                "current_scene": "The screen shows flight SR516 details with a Book button. No loading or error state is visible.",
                "visible_evidence": ["SR516", "Book"],
                "past_context_used": ["SR516 was selected from results"],
                "decision_rationale": "The details page is the commitment point.",
                "action_purpose": "Commit the selected booking",
                "uncertainty": "Persistence in My Trips still needs verification",
            },
            "Case_Story_Update": {
                "case_story_so_far": (
                    "Step 1: On FlightDetailsActivity, the screen shows flight SR516 details and a Book button. "
                    "Because SR516 is selected and the details page is the commitment point, the Explorer chose Book. "
                    "It predicted that a confirmation page should appear and that My Trips still needs verification."
                ),
                "new_event": "The Book button is selected on the details page.",
                "key_entities": {"flight_id": "SR516"},
                "verified_facts": ["SR516 details were visible"],
                "open_obligations": ["Verify SR516 appears in My Trips"],
                "hypotheses": ["Booking should persist after confirmation"],
                "contradiction_candidates": [],
            },
            "Function_Phase": "committing",
            "Function_End": False,
            "Verification_Target": "My Trips list",
            "Bug_Detected": False,
            "Bug_Description": None,
        })

        self.assertEqual(action.step_narrative["visible_evidence"], ["SR516", "Book"])
        self.assertEqual(action.behavior_narrative["current_scene"], action.step_narrative["current_scene"])
        self.assertIn("Step 1:", action.case_story_update["case_story_so_far"])
        self.assertNotIn("key_entities", action.case_story_update)
        self.assertNotIn("open_obligations", action.case_story_update)

    def test_global_story_updates_with_numbered_step_story(self):
        manager = BehaviorDossierManager()
        first = self._parse({
            "Page_Description": "Flight details page is visible.",
            "Function": "Book a flight",
            "Status": "Yes",
            "Operation": "click",
            "Widget": "Book",
            "Step_Narrative": {
                "current_scene": "The details page shows SR516 and a Book button.",
                "visible_evidence": ["SR516", "Book"],
                "decision_rationale": "Commit the selected flight.",
                "action_purpose": "Book SR516",
                "uncertainty": "My Trips still needs verification",
            },
            "Case_Story_Update": {
                "case_story_so_far": (
                    "Step 1: On DetailsActivity, the details page shows flight SR516 and a Book button. "
                    "Because SR516 is the selected flight and the Book control is visible, the Explorer chose Book to commit the selected flight. "
                    "It predicted that a confirmation screen should appear, while the remaining verification need is to confirm SR516 later appears in My Trips."
                ),
                "new_event": "Book was selected.",
                "verified_facts": ["SR516 was visible on the details page"],
                "hypotheses": ["The booking should persist"],
                "contradiction_candidates": [],
            },
            "Function_Phase": "committing",
            "Verification_Target": "My Trips list",
            "Bug_Detected": False,
            "Bug_Description": None,
        })
        second = self._parse({
            "Page_Description": "My Trips list is visible.",
            "Function": "Book a flight",
            "Status": "No",
            "Operation": "click",
            "Widget": "My Trips",
            "Step_Narrative": {
                "current_scene": "The My Trips screen shows SR516 in the trip list. No empty state or error message is visible.",
                "visible_evidence": ["My Trips", "SR516"],
                "decision_rationale": "The persistence target is now visible.",
                "action_purpose": "Verify the booked trip",
                "uncertainty": "None for this entity",
            },
            "Case_Story_Update": {
                "case_story_so_far": (
                    "Step 1: On DetailsActivity, the details page showed flight SR516 and a Book button. "
                    "Because SR516 was the selected flight and the Book control was visible, the Explorer chose Book to commit the selected flight. "
                    "It predicted that a confirmation screen should appear and that My Trips would still need to be checked.\n\n"
                    "Step 2: On TripsActivity, the My Trips screen shows SR516 in the trip list and no empty state or error message is visible. "
                    "This supports that the booking is visible in the expected trip list. "
                    "The Explorer treated the persistence check as complete and predicted that the behavior-chain review should find the booked trip evidence satisfied."
                ),
                "new_event": "SR516 is visible in My Trips.",
                "verified_facts": [
                    "SR516 was visible on the details page",
                    "SR516 appears in My Trips",
                ],
                "hypotheses": [],
                "contradiction_candidates": [],
            },
            "Function_Phase": "completed",
            "Function_End": True,
            "Verification_Target": "My Trips list",
            "Bug_Detected": False,
            "Bug_Description": None,
        })

        manager.append_step(1, first, "DetailsActivity", "ConfirmationActivity", {"ui_changed": True})
        manager.append_step(2, second, "ConfirmationActivity", "TripsActivity", {"ui_changed": True, "activity_changed": True})

        trace = manager.to_dict()
        story = trace["global_story"]
        self.assertIn("Step 1:", story["case_story_so_far"])
        self.assertIn("Step 2:", story["case_story_so_far"])
        self.assertIn("SR516 in the trip list", story["case_story_so_far"])
        self.assertNotIn("key_entities", story)
        self.assertNotIn("open_obligations", story)
        self.assertEqual(story["hypotheses"], [])
        self.assertIn("SR516 appears in My Trips", story["verified_facts"])

    def test_input_only_does_not_trigger_sequence_review(self):
        manager = BehaviorDossierManager()
        action1 = self._parse({
            "Page_Description": "Passenger form.",
            "Function": "Book a flight",
            "Status": "Yes",
            "Operation": "input",
            "Inputs": [{"Widget": "Passenger", "Input": "Ada"}],
            "Function_Phase": "inputting",
            "Function_End": False,
            "Bug_Detected": False,
            "Bug_Description": None,
        })
        action2 = self._parse({
            "Page_Description": "Passenger form.",
            "Function": "Book a flight",
            "Status": "No",
            "Operation": "input",
            "Inputs": [{"Widget": "Email", "Input": "ada@example.com"}],
            "Function_Phase": "inputting",
            "Function_End": False,
            "Bug_Detected": False,
            "Bug_Description": None,
        })

        manager.append_step(1, action1, "BookingActivity", "BookingActivity", {"ui_changed": True})
        manager.append_step(2, action2, "BookingActivity", "BookingActivity", {"ui_changed": True})

        evaluation = manager.evaluate_trigger()
        self.assertFalse(evaluation.should_review)
        self.assertFalse(evaluation.phase_signal)

    def test_commit_confirmation_can_trigger_sequence_review(self):
        manager = BehaviorDossierManager()
        input_action = self._parse({
            "Page_Description": "Passenger form.",
            "Function": "Book a flight",
            "Status": "Yes",
            "Operation": "input",
            "Inputs": [{"Widget": "Passenger", "Input": "Ada"}],
            "Function_Phase": "inputting",
            "Function_End": False,
            "Bug_Detected": False,
            "Bug_Description": None,
        })
        commit_action = self._parse({
            "Page_Description": "Passenger form with Book button.",
            "Function": "Book a flight",
            "Status": "No",
            "Operation": "click",
            "Widget": "Book",
            "Function_Phase": "committing",
            "Function_End": False,
            "Verification_Target": "My Trips list should contain the booked trip",
            "Bug_Detected": False,
            "Bug_Description": None,
        })

        manager.append_step(1, input_action, "BookingActivity", "BookingActivity", {"ui_changed": True})
        manager.append_step(
            2,
            commit_action,
            "BookingActivity",
            "ConfirmationActivity",
            {
                "ui_changed": True,
                "activity_changed": True,
                "actual_observation": "Activity=ConfirmationActivity; visible=Confirmation; Trip summary",
            },
        )

        evaluation = manager.evaluate_trigger()
        self.assertTrue(evaluation.should_review)
        self.assertIn("commit_reached_verification_page_signal", evaluation.reasons)

    def test_blocked_repeated_no_change_triggers_review(self):
        manager = BehaviorDossierManager()
        for step in range(1, 4):
            action = self._parse({
                "Page_Description": "Same screen remains visible.",
                "Function": "Submit form",
                "Status": "No",
                "Operation": "click",
                "Widget": "Submit",
                "Function_Phase": "blocked" if step == 3 else "exploring",
                "Function_End": False,
                "Bug_Detected": False,
                "Bug_Description": None,
            })
            manager.append_step(
                step,
                action,
                "FormActivity",
                "FormActivity",
                {"ui_changed": False, "activity_changed": False},
            )

        evaluation = manager.evaluate_trigger()
        self.assertTrue(evaluation.should_review)
        self.assertIn("blocked_or_repeated_no_change", evaluation.reasons)

    def test_function_labels_do_not_split_active_trace(self):
        manager = BehaviorDossierManager()
        actions = [
            self._parse({
                "Page_Description": "Search page.",
                "Function": "Flight Search",
                "Status": "Yes",
                "Operation": "click",
                "Widget": "Search Flights",
                "Function_Phase": "start",
                "Bug_Detected": False,
                "Bug_Description": None,
            }),
            self._parse({
                "Page_Description": "Passenger page.",
                "Function": "Passenger Details Entry",
                "Status": "No",
                "Operation": "input",
                "Inputs": [{"Widget": "Passenger", "Input": "Ada"}],
                "Function_Phase": "inputting",
                "Bug_Detected": False,
                "Bug_Description": None,
            }),
            self._parse({
                "Page_Description": "Payment page.",
                "Function": "Payment Processing",
                "Status": "No",
                "Operation": "click",
                "Widget": "Pay Now",
                "Function_Phase": "committing",
                "Verification_Target": "Payment confirmation",
                "Bug_Detected": False,
                "Bug_Description": None,
            }),
        ]

        manager.append_step(1, actions[0], "MainActivity", "FlightResultsActivity", {"ui_changed": True})
        manager.append_step(2, actions[1], "PassengerActivity", "PassengerActivity", {"ui_changed": True})
        manager.append_step(3, actions[2], "PaymentActivity", "ConfirmationActivity", {"ui_changed": True})

        trace = manager.to_dict()
        self.assertEqual(trace["trace_id"], "trace_001")
        self.assertEqual(trace["function_goal"], "Flight Search")
        self.assertEqual(trace["function_name"], "Flight Search")
        self.assertEqual(trace["function_labels_seen"], [
            "Flight Search",
            "Passenger Details Entry",
            "Payment Processing",
        ])
        self.assertEqual(trace["steps"][1]["function_label"], "Passenger Details Entry")
        self.assertIn("MainActivity", trace["activities_seen"])
        self.assertIn("PaymentActivity", trace["activities_seen"])
        self.assertEqual(len(trace["steps"]), 3)

    def test_intermediate_no_bug_review_keeps_trace_active_until_terminal(self):
        manager = BehaviorDossierManager()
        start_action = self._parse({
            "Page_Description": "Search page.",
            "Function": "Flight Search",
            "Status": "Yes",
            "Operation": "click",
            "Widget": "Search Flights",
            "Function_Phase": "start",
            "Bug_Detected": False,
            "Bug_Description": None,
        })
        verify_action = self._parse({
            "Page_Description": "Results page.",
            "Function": "Flight Search",
            "Status": "No",
            "Operation": "click",
            "Widget": "Select SR218",
            "Function_Phase": "verifying",
            "Verification_Target": "Passenger details page",
            "Bug_Detected": False,
            "Bug_Description": None,
        })
        final_action = self._parse({
            "Page_Description": "Confirmation page.",
            "Function": "Payment Processing",
            "Status": "No",
            "Operation": "click",
            "Widget": "Pay Now",
            "Function_Phase": "completed",
            "Function_End": True,
            "Verification_Target": "Payment confirmation",
            "Bug_Detected": False,
            "Bug_Description": None,
        })

        manager.append_step(1, start_action, "MainActivity", "FlightResultsActivity", {"ui_changed": True})
        manager.append_step(2, verify_action, "FlightResultsActivity", "PassengerActivity", {"ui_changed": True})
        manager.apply_review_result({"verdict": "no_bug", "confidence": 0.9}, step_index=2)
        manager.archive_if_completed()

        self.assertIsNotNone(manager.active_trace)
        self.assertEqual(len(manager.archived_traces), 0)
        self.assertFalse(manager.to_dict()["completed"])

        manager.append_step(3, final_action, "PaymentActivity", "MainActivity", {"ui_changed": True})
        manager.apply_review_result({"verdict": "no_bug", "confidence": 0.9}, step_index=3)
        manager.archive_if_completed()

        self.assertIsNone(manager.active_trace)
        self.assertEqual(len(manager.archived_traces), 1)
        self.assertEqual(len(manager.archived_traces[0]["steps"]), 3)

    def test_explorer_prompt_uses_dossier_not_recent_history(self):
        memory = TestingSequenceMemorizer()
        memory.set_app_name("SkyReserve")
        memory.record_operation(
            activity_name="MainActivity",
            operation="click",
            target_widget="Search Flights",
            success=True,
            page_description="Old page description",
        )
        generator = PromptGenerator(memory_manager=memory)
        generator.set_behavior_dossier_section(
            "## Behavior Dossier\nCase story so far: Search flow is in progress."
        )

        prompt = generator.build_test_prompt(
            [{"text": "Search Flights", "class": "android.widget.Button", "bounds": "[0,0][100,100]"}],
            "MainActivity",
        )

        self.assertIn("## Behavior Dossier", prompt)
        self.assertIn("Case story so far", prompt)
        self.assertIn("Current Activity: MainActivity", prompt)
        self.assertIn("Search Flights", prompt)
        self.assertNotIn("## Recent Test History", prompt)
        self.assertNotIn("Old history should not appear", prompt)
        self.assertNotIn("What is the function currently being tested?", prompt)

    def test_prompt_requests_numbered_story_and_omits_legacy_fields(self):
        manager = BehaviorDossierManager()
        action = self._parse({
            "Page_Description": "Main flight search screen.",
            "Function": "Flight Search",
            "Status": "Yes",
            "Operation": "click",
            "Widget": "From",
            "Step_Narrative": {
                "current_scene": "MainActivity shows a flight search form with From, To, Departure date, Return date, and Passengers fields.",
                "visible_evidence": ["From", "To", "Departure date", "Return date", "Passengers"],
                "decision_rationale": "The origin selector is the first field needed for flight search.",
                "action_purpose": "Open the From dropdown",
                "uncertainty": "The selected origin still needs to be reflected in later results",
            },
            "Case_Story_Update": {
                "case_story_so_far": (
                    "Step 1: On MainActivity, the screen shows a flight search form with From, To, Departure date, Return date, and Passengers. "
                    "Because the active task is to test flight search behavior, the Explorer chose the From dropdown. "
                    "It predicted that an airport option list should appear, and the remaining verification need is to confirm the selected origin affects later search results."
                ),
                "new_event": "From dropdown was chosen.",
                "verified_facts": ["MainActivity shows the flight search form"],
                "hypotheses": ["Airport options should appear"],
                "contradiction_candidates": [],
            },
            "Function_Phase": "start",
            "Verification_Target": "Origin selection should affect search results",
            "Bug_Detected": False,
            "Bug_Description": None,
        })
        manager.append_step(1, action, "MainActivity", "MainActivity", {"ui_changed": True})

        dossier_prompt = manager.format_for_prompt()
        self.assertIn("numbered Step N paragraphs", dossier_prompt)
        self.assertIn("Step 1:", dossier_prompt)
        self.assertNotIn("key_entities", dossier_prompt)
        self.assertNotIn("open_obligations", dossier_prompt)
        self.assertNotIn("Key entities", dossier_prompt)
        self.assertNotIn("Open verification obligations", dossier_prompt)
        self.assertNotIn("obligation", dossier_prompt.lower())

        generator = PromptGenerator(memory_manager=TestingSequenceMemorizer())
        system_prompt = generator.build_system_prompt()
        self.assertIn('"case_story_so_far"', system_prompt)
        self.assertIn("Step 1:", system_prompt)
        self.assertNotIn("key_entities", system_prompt)
        self.assertNotIn("open_obligations", system_prompt)
        self.assertNotIn("obligation", system_prompt.lower())

    def test_long_numbered_case_story_is_retained(self):
        manager = BehaviorDossierManager()
        long_story = "\n\n".join(
            (
                f"Step {idx}: On Activity{idx}, the screen shows a detailed form section with field A{idx}, "
                f"field B{idx}, a visible confirmation control, and no error or loading state. "
                f"The Explorer used this evidence to choose action {idx}, predicted observable result {idx}, "
                f"and recorded remaining verification need marker-{idx}."
            )
            for idx in range(1, 16)
        )
        action = self._parse({
            "Page_Description": "Detailed multi-step flow.",
            "Function": "Long Flow",
            "Status": "Yes",
            "Operation": "click",
            "Widget": "Continue",
            "Step_Narrative": {
                "current_scene": "The current screen shows the Continue control for the long flow.",
                "visible_evidence": ["Continue"],
                "decision_rationale": "Continue advances the long flow.",
                "action_purpose": "Advance",
                "uncertainty": "Later screens need verification",
            },
            "Case_Story_Update": {
                "case_story_so_far": long_story,
                "new_event": "Continue was selected.",
                "verified_facts": ["Long flow is visible"],
                "hypotheses": ["Next screen should appear"],
                "contradiction_candidates": [],
            },
            "Function_Phase": "exploring",
            "Bug_Detected": False,
            "Bug_Description": None,
        })
        manager.append_step(1, action, "Activity1", "Activity2", {"ui_changed": True})

        stored_story = manager.to_dict()["global_story"]["case_story_so_far"]
        self.assertGreater(len(stored_story), 3000)
        self.assertIn("Step 15:", stored_story)
        self.assertIn("marker-15", stored_story)

    def test_stale_dumpsys_ime_does_not_create_keyboard_layer(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.FrameLayout" package="com.example.app" bounds="[0,0][1080,1920]" focused="false">
    <node class="android.widget.TextView" package="com.example.app" text="Payment successful" bounds="[28,489][1052,1043]" focused="false" />
  </node>
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "ui.xml"
            xml_path.write_text(xml, encoding="utf-8")
            state = analyze_ui_state(
                xml_path,
                target_package="com.example.app",
                device_state={
                    "ime_visible": True,
                    "served_view": "DecorView@e1d7925[MainActivity]",
                },
            )

        self.assertFalse(state["transient_layer"]["active"])
        self.assertFalse(state["input_method"]["ime_visible"])
        self.assertTrue(state["input_method"]["raw_ime_visible"])
        self.assertIn("weak_ime_visible", state["indicators"])
        self.assertIn("reported visible (weak/stale", format_ui_state_for_prompt(state))

    def test_visible_input_method_nodes_create_keyboard_layer(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node class="android.widget.FrameLayout" package="com.example.app" bounds="[0,0][1080,1200]" focused="false" />
  <node class="android.inputmethodservice.KeyboardView" package="com.android.inputmethod.latin" bounds="[0,1200][1080,1920]" focused="false" />
</hierarchy>
"""
        with tempfile.TemporaryDirectory() as tmp:
            xml_path = Path(tmp) / "ui.xml"
            xml_path.write_text(xml, encoding="utf-8")
            state = analyze_ui_state(
                xml_path,
                target_package="com.example.app",
                device_state={"ime_visible": True},
            )

        self.assertTrue(state["transient_layer"]["active"])
        self.assertEqual(state["transient_layer"]["type"], "keyboard")
        self.assertTrue(state["input_method"]["ime_visible"])
        self.assertTrue(state["input_method"]["visibility_reliable"])


if __name__ == "__main__":
    unittest.main()
