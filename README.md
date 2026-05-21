# GUIdebuger

GUIdebuger is an LLM-assisted Android GUI testing prototype. It explores a
running Android application, collects UI XML and screenshots, asks an Explorer
LLM to choose the next GUI action, reviews candidate defects with a Supervisor
model, and generates evidence-rich bug reports in Markdown and JSON.

The tool is designed for research and artifact evaluation around mobile app
maintenance, regression testing, and non-crash GUI defect discovery. It is not a
drop-in replacement for a human oracle: every generated report should still be
checked against the saved screenshots, UI context, and reproduction steps.

## What the Tool Does

- Collects the foreground Android package, Activity, UI hierarchy, screenshots,
  and logcat state through ADB and UIAutomator.
- Extracts operable controls from UI XML and filters system or non-interactive
  widgets.
- Builds prompts from GUI context, user instructions, testing memory, execution
  feedback, and behavior-chain dossiers.
- Uses an Explorer LLM to select actions such as click, input, scroll, and back.
- Pre-parses model output before execution and saves evidence when the Explorer
  reports a candidate bug.
- Uses a Supervisor model to review false positives and cross-step behavior
  evidence.
- Generates Markdown and JSON BugReports with screenshots, operations, Activity
  information, reproduction steps, and review metadata.

## Repository Layout

```text
.
|-- main.py                         # Main outer loop
|-- env_interactor/
|   |-- adb_utils.py                 # ADB, UI dump, screenshot, logcat helpers
|   `-- action_executor.py           # Action parsing and execution
|-- gui_extractor/
|   |-- manifest_parser.py           # Package and Activity metadata
|   |-- ui_state_analyzer.py         # UI state summaries and action phases
|   `-- xml_parser.py                # UI XML control extraction
|-- llm_agent/
|   |-- llm_client.py                # OpenAI-compatible text model client
|   |-- multimodal_llm_client.py     # Screenshot + text model client
|   |-- prompt_builder.py            # Prompt construction entry point
|   |-- prompt_templates.py          # Prompt templates
|   |-- memory_manager.py            # Testing memory
|   |-- behavior_dossier.py          # Cross-step behavior evidence
|   |-- supervisor.py                # Supervisor review logic
|   |-- screenshot_manager.py        # Screenshot storage and encoding
|   |-- bug_analysis_engine.py       # BugReport generation
|   |-- experiment_logger.py         # Structured run logs
|   `-- token_monitor.py             # Token and latency statistics
|-- tests/                           # Unit tests for core logic
|-- samples/                         # Sanitized sample reports and run logs
|-- requirements.txt                 # Minimal live-run dependencies
`-- .env.example                     # Template for local model settings
```

Runtime directories such as `bug_reports/`, `experiment_results/`,
`temp_data/`, and local app data are intentionally ignored in this public
branch. Keep large screenshots, APKs, raw logs, and paper build artifacts in a
release asset or a separate artifact archive.

## Quick Start for Artifact Review

This path does not require an Android device or an API key. It lets reviewers
inspect the tool outputs and run local unit tests.

1. Clone the repository and enter the project root.

2. Inspect sample bug reports:

```powershell
Get-ChildItem samples\bug_reports -Filter *.md
Get-ChildItem samples\bug_reports -Filter *.json
```

3. Inspect archived experiment runs:

```powershell
Get-ChildItem samples\experiment_results
Get-ChildItem samples\experiment_results -Recurse -Filter steps.jsonl
Get-ChildItem samples\experiment_results -Recurse -Filter bugs.jsonl
```

4. Run unit tests:

```powershell
python -m unittest discover -s tests
```

These tests cover behavior-dossier handling, Supervisor fallback behavior, and
BugReport metadata logic.

## Live Android Run

Use this path when you want to run GUIdebuger against an Android app.

### Requirements

- Windows with PowerShell or cmd.
- Python 3.10 or later.
- Android SDK Platform Tools, with `adb` available on `PATH`.
- One connected Android device or emulator with USB debugging enabled.
- A target Android app already installed and opened in the foreground.
- An OpenAI-compatible API endpoint for live LLM exploration.

Install the minimal Python dependencies:

```powershell
python -m pip install -r requirements.txt
```

Check device connectivity:

```powershell
adb devices
adb shell dumpsys window | findstr mCurrentFocus
```

### Model Configuration

Copy `.env.example` to `.env`, then set your local API key and endpoint. Do not
commit real keys.

```env
OPENAI_API_KEY=your-api-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o

OPENAI_ENABLE_THINKING=false
OPENAI_PRINT_REASONING=false
OPENAI_RETRY_WITHOUT_THINKING=true
OPENAI_MAX_TOKENS=2000

OPENAI_MULTIMODAL_ENABLE_THINKING=false
OPENAI_MULTIMODAL_MAX_TOKENS=1000

AUTO_HIDE_KEYBOARD_AFTER_INPUT=1
```

The text Explorer and multimodal Supervisor currently read the same
OpenAI-compatible API settings.

### Run

Open the target app on the device, then run:

```powershell
python main.py
```

The program asks for an application name and testing instructions. The
application name is used in prompts and logs; the current foreground package is
used as the actual Android target.

Example instruction:

```text
Focus on adding, saving, list refresh, and cross-page data consistency.
```

## Execution Workflow

Each testing step follows this high-level loop:

1. Dump the current UI XML, Activity, screenshot, and logcat state.
2. Parse UI XML and extract candidate controls.
3. Build an Explorer prompt from page context, recent actions, Function Memory,
   and any active behavior dossier.
4. Call the LLM and parse its JSON action response.
5. If the Explorer reports a candidate bug, save the current evidence before
   executing the next action.
6. Ask the Supervisor to review the candidate bug or behavior-chain evidence.
7. Execute valid actions through ADB/UIAutomator.
8. Compare before/after UI state and update testing memory.
9. Save structured logs, screenshots, prompts, responses, and final BugReports.

## Output Files

| Path | Description |
| --- | --- |
| `temp_data/current_ui.xml` | Most recent UI hierarchy dump. |
| `temp_data/screenshots/` | Runtime screenshots. |
| `temp_data/logs/` | Human-readable process logs. |
| `experiment_results/run_*/run_meta.json` | Run metadata, including app, device, model, and configuration. |
| `experiment_results/run_*/steps.jsonl` | Structured per-step records. |
| `experiment_results/run_*/events.jsonl` | Review, fallback, and important event records. |
| `experiment_results/run_*/bugs.jsonl` | Bug index for a run. |
| `experiment_results/run_*/prompts/` | Explorer and Supervisor prompts and responses. |
| `experiment_results/run_*/screenshots/` | Archived screenshots for a run. |
| `bug_reports/*.md` | Human-readable bug reports. |
| `bug_reports/*.json` | Machine-readable bug reports. |
| `samples/bug_reports/` | Small sanitized reports included for artifact inspection. |
| `samples/experiment_results/` | Small sanitized run logs included for artifact inspection. |

## Example Report Contents

A confirmed report typically contains:

- bug id, timestamp, severity, and category;
- target package and Activity;
- triggering operation and widget;
- reproduction steps;
- screenshot paths and visual evidence;
- Explorer analysis;
- Supervisor review result;
- structured fields for later aggregation.

## Evaluation Snapshot

In the current thesis evaluation, GUIdebuger was run on 50 Android applications
from Themis. It generated 98 candidate reports, of which 72 were manually
confirmed as valid and 26 were false positives, yielding 73.47% report-level
precision. In an ablation without Supervisor review, precision dropped to
51.11%, showing that the review stage helps reduce LLM over-reporting.

These numbers are preliminary and descriptive. They are intended to support tool
demonstration and artifact review, not to replace a full repeated-run benchmark.

## Development Commands

Run unit tests:

```powershell
python -m unittest discover -s tests
```

Clear logcat:

```powershell
adb logcat -c
```

Capture recent logcat:

```powershell
adb logcat -d
```

If PowerShell displays non-ASCII output incorrectly, switch the terminal to
UTF-8:

```powershell
chcp 65001
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::UTF8
```

## Artifact Notes

For a conference artifact package, prepare the following before submission:

- public repository URL;
- 3-5 minute screencast URL;
- short quick-start instructions for live Android mode;
- sample Markdown and JSON BugReports;
- screenshot evidence used in the demo;
- optional archived logs for reviewers who do not configure an API key.

## Known Limitations

- LLM decisions are stochastic and can over-infer expected behavior when product
  requirements are unavailable.
- Screenshots improve review quality but do not create a complete oracle for
  dynamic content, server state, animations, or delayed UI updates.
- Live mode requires Android tooling, a connected device or emulator, and an API
  key.
- Current aggregate evaluation lacks repeated-run statistics and per-app
  significance tests.

## License

No license has been selected yet. Add one before publishing the repository.
