# Code Level: appraisal-automation

## 1. Overview
- **Name:** Appraisal Automation Core System
- **Description:** The root directory for the application, containing the Streamlit user interface, and the high-level orchestration controllers for Stage 1 (injection) and Stage 2 (review).
- **Location:** [appraisal-automation/](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/)
- **Language:** Python
- **Purpose:** To provide a complete end-to-end pipeline allowing users to extract data from templates, replace it globally, and send the result for an AI critique.

## 2. Code Elements

### Modules

#### `app.py`
- **Description:** Main Streamlit entry point. Implements a tabbed dashboard that governs user interaction, password gating, file uploads, state feedback, and downloading modified files.
- **Location:** [app.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/app.py)

#### `stage2_review.py`
- **Description:** Orchestrates the AI review process. Formats paragraph lists into Rich Markdown, builds indexing models, directly invokes various AI vendors (OpenAI, Gemini), and calls the injector.
- **Location:** [stage2_review.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/stage2_review.py)

#### `stage1_inject.py`
- **Description:** Orchestrates Stage 1 data insertion. Runs extraction, safe-replaces user modifications across the document, and removes empty template lines.
- **Location:** [stage1_inject.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/stage1_inject.py)

#### `docx_utils.py`
- **Description:** Reusable utility toolkit for manipulating DOCX XML. Provides safe content modification with unicode/boundary checks (`_safe_replace`), gets paragraph texts, maps Rich Markdown, and triggers `unpack`/`pack`.
- **Location:** [docx_utils.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/docx_utils.py)

#### `field_extractor.py`
- **Description:** Analyzes unformatted Hebrew documentation covers to guess label and value maps (`extract_cover_fields`). Features heuristic checks against known metadata formats.
- **Location:** [field_extractor.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/field_extractor.py)

#### `section_mapper.py`
- **Description:** Uses regex mapping and OOXML styling features to deduce human-readable context structures from basic parsed `<w:p>` iterations (e.g. converting `TOC1` into `תוכן עניינים`).
- **Location:** [section_mapper.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/section_mapper.py)

#### `comment_injector.py`
- **Description:** Serves as an interface between the `Finding` structured dictionaries produced by the LLM logic to the highly strict XML manipulation API nested inside `scripts/office`.
- **Location:** [comment_injector.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/comment_injector.py)

#### `config.py`
- **Description:** Bootstraps basic `.env` properties, establishes API credentials, configures multi-LLM router logic, and defines temporary directory bounds.
- **Location:** [config.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/config.py)

## 3. Dependencies

### Internal Dependencies
Uses sub-packages heavily:
- `scripts.office.unpack`, `scripts.office.pack`, `scripts.office.comment`
- `agents.reviewer`
- `agents.prompts`

### External Dependencies
- `streamlit` - For Web UI
- `pydantic` - Enforcing strict structures over JSON LLM returns
- `lxml` - Core to all `docx_utils` / `section_mapper` operations for parsing XML.
- `python-docx` - Heavy lifting associated with `field_extractor`.
- `openai`, `google-genai`, `anthropic` - LLM provider SDKs.

## 4. Relationships
The components exhibit a very flat hierarchy below the UI. The UI (`app.py`) loads the workflow triggers (`stage1`, `stage2`), which depend downward completely on modular data structures configured in `docx_utils` and `agents`. There's an intentional architectural abstraction between the "raw XML edit functions" (in `scripts/office/`) and the business logic applied directly in the core application folder here.
