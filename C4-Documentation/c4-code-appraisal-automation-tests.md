# Code Level: appraisal-automation/tests

## 1. Overview
- **Name:** Appraisal Automation Test Suite
- **Description:** A collection of pytest-based test files ensuring the correctness of various modules within the appraisal automation system, including the multi-agent reviewer, sections mapping, and stage 1 document injection.
- **Location:** [appraisal-automation/tests](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/)
- **Language:** Python (pytest)
- **Purpose:** To validate agent behavior, text aggregation logic, section mapping of DOCX structures, and text replacement logic for the document injector.

## 2. Code Elements

### Functions / Test Cases

#### `test_aggregator.py`
- **`test_aggregate_findings()`**
  - **Description:** Tests the `aggregate_findings` function by passing mocked phrasing, spelling, and consistency findings. Asserts that phrasing findings get their own comment while spelling and consistency findings are merged based on paragraph index.
  - **Location:** [test_aggregator.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_aggregator.py#L4)
  - **Dependencies:** `agents.aggregator.aggregate_findings`, `pytest`.

#### `test_reviewer_parallel.py`
- **`MockReviewer` (Class)**
  - **Description:** Mocks the LLM calls (`_call_llm`) with predefined sleep intervals to test parallel execution.
  - **Location:** [test_reviewer_parallel.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_reviewer_parallel.py#L5)
  - **Dependencies:** `agents.reviewer.MultiAgentReviewer`.
- **`test_reviewer_parallel_timing()`**
  - **Description:** Tests that the `run_review` method of `MockReviewer` executes in parallel (total duration should be close to the maximum latency rather than the sum of all latencies).
  - **Location:** [test_reviewer_parallel.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_reviewer_parallel.py#L18)
- **`test_reviewer_ab_selection()`**
  - **Description:** Verifies that the Phrasing Agent uses both A and B prompt variants by running multiple iterations and asserting that both models are selected.
  - **Location:** [test_reviewer_parallel.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_reviewer_parallel.py#L35)

#### `test_section_mapper.py`
- **`temp_unpacked_dir(tmp_path)` (Fixture)**
  - **Description:** Generates a temporary directory with a mock `word/document.xml` containing predefined Word styling (`TOC1`, `Heading1`, `a9`, etc.).
  - **Location:** [test_section_mapper.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_section_mapper.py#L24)
- **`test_section_mapper_logic(temp_unpacked_dir)`**
  - **Description:** Tests the `SectionMapper` against the mock XML correctly tagging paragraphs and their inherited parent sections based on Word paragraph styles.
  - **Location:** [test_section_mapper.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_section_mapper.py#L33)
  - **Dependencies:** `section_mapper.SectionMapper`.

#### `test_stage1.py`
- **`TestSafeReplaceNumeric` (Class)**
  - **Description:** Contains tests verifying boundary protection for numeric replacement logic using `_safe_replace`, preventing matching within larger numbers or dates.
  - **Location:** [test_stage1.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_stage1.py#L20)
- **`TestSafeReplaceHebrew` (Class)**
  - **Description:** Contains tests for safe Hebrew text replacements, ensuring replacements only occur on standalone words and not substrings.
  - **Location:** [test_stage1.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_stage1.py#L108)
- **`TestSafeReplaceMixed` (Class)**
  - **Description:** Edge cases testing XML node ignorance and ensuring labels are distinct from replaced values.
  - **Location:** [test_stage1.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_stage1.py#L150)
- **`test_stage1_real_document_type_b()`**
  - **Description:** An integration test that actually copies a real file (`2026023T.docx`), runs `stage1_inject` with a dictionary of confirmed fields, and validates the output file format inside the unpacked XML.
  - **Location:** [test_stage1.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/tests/test_stage1.py#L187)
  - **Dependencies:** `stage1_inject.run_stage1`, `docx_utils.docx_unpack`, `config.TEMP_DIR`.

## 3. Dependencies

### Internal Dependencies
- `agents.aggregator`
- `agents.reviewer`
- `section_mapper`
- `docx_utils`
- `stage1_inject`
- `config`

### External Dependencies
- `pytest`: Used as the underlying framework for all these tests.
- `shutil`, `tempfile`: Used for setup/teardown in integration tests.

## 4. Relationships
Tests are largely isolated from each other. They import application code (`agents`, `docx_utils`, etc.) directly from the source directory (`..`) to validate logic in separation.
