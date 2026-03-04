# Code Level: appraisal-automation/scripts/office

## 1. Overview
- **Name:** DOCX Office Automation Scripts
- **Description:** A collection of Python scripts designed to unpack, pack, and manipulate Microsoft Word (DOCX) files directly at the XML level. It handles structural merging of runs and precise injection of Word comments into the OOXML file structure.
- **Location:** [appraisal-automation/scripts/office](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/)
- **Language:** Python
- **Purpose:** To provide low-level tools necessary to interact with and edit the underlying XML structure of Microsoft Word documents. 

## 2. Code Elements

### Functions

#### `comment.py`

- **`inject_comments_batch(unpacked_dir: str, comments: list[dict], author: str = "רמי סויצקי") -> int`**
  - **Description:** Inject multiple comments in a single pass into an unpacked DOCX directory. It edits `word/comments.xml`, `word/document.xml`, `[Content_Types].xml`, and `word/_rels/document.xml.rels`.
  - **Location:** [comment.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/comment.py#L47)
  - **Dependencies:** `lxml.etree`, internal helpers (`_ensure_comments_xml`, `_add_all_comments_to_xml`, `_ensure_comments_relationship`, `_ensure_content_type`, `_inject_all_markers`).

- **`inject_comment(unpacked_dir: str, comment_id: int, text: str, author: str = "רמי סויצקי", para_index: int = 0) -> None`**
  - **Description:** Legacy single-comment API that delegates to `inject_comments_batch`.
  - **Location:** [comment.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/comment.py#L86)
  - **Dependencies:** `inject_comments_batch`.

- **`_ensure_comments_xml(word_dir: str) -> str`**
  - **Description:** Creates `word/comments.xml` if it does not exist and returns its path.
  - **Location:** [comment.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/comment.py#L106)
  - **Dependencies:** `lxml.etree`.

- **`_add_all_comments_to_xml(comments_path: str, comments: list[dict], author: str) -> None`**
  - **Description:** Appends all `<w:comment>` elements to `comments.xml` in one pass.
  - **Location:** [comment.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/comment.py#L119)
  - **Dependencies:** `lxml.etree`.

- **`_ensure_comments_relationship(word_dir: str) -> None`**
  - **Description:** Adds comments relationship to `word/_rels/document.xml.rels` if missing.
  - **Location:** [comment.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/comment.py#L151)
  - **Dependencies:** `lxml.etree`.

- **`_ensure_content_type(unpacked_dir: str) -> None`**
  - **Description:** Adds `comments.xml` Override to `[Content_Types].xml` if missing.
  - **Location:** [comment.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/comment.py#L186)
  - **Dependencies:** `lxml.etree`.

- **`_inject_all_markers(doc_path: str, comments: list[dict]) -> None`**
  - **Description:** Inserts commentRangeStart/End and commentReference markers inside the target `<w:p>` elements in `document.xml`.
  - **Location:** [comment.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/comment.py#L207)
  - **Dependencies:** `lxml.etree`.

#### `pack.py`

- **`pack(src_dir: str, dst_docx: str) -> None`**
  - **Description:** Zips up `src_dir` into a new `.docx` file using `ZIP_DEFLATED` compression to match what Word produces.
  - **Location:** [pack.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/pack.py#L15)
  - **Dependencies:** `zipfile`, `os`.

#### `unpack.py`

- **`_runs_have_same_rpr(run_a: etree._Element, run_b: etree._Element) -> bool`**
  - **Description:** Returns True if both DOCX runs `<w:r>` have identical run properties (`<w:rPr>`).
  - **Location:** [unpack.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/unpack.py#L26)
  - **Dependencies:** `lxml.etree`.

- **`merge_runs_in_paragraph(para: etree._Element) -> None`**
  - **Description:** Merges consecutive `<w:r>` elements that share the same `<w:rPr>`. Repairs text fragmentation (e.g. from RTL bidi engine or revisions).
  - **Location:** [unpack.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/unpack.py#L38)
  - **Dependencies:** `lxml.etree`, `_runs_have_same_rpr`.

- **`merge_runs_in_xml(xml_path: str) -> None`**
  - **Description:** Parses a single XML file, applies `merge_runs_in_paragraph` to all paragraphs, and writes the changes back.
  - **Location:** [unpack.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/unpack.py#L86)
  - **Dependencies:** `lxml.etree`, `merge_runs_in_paragraph`.

- **`unpack(src_docx: str, dst_dir: str) -> None`**
  - **Description:** Unpacks a `src_docx` zip into `dst_dir`. After extraction, it merges separated `<w:r>` text runs inside all `word/*.xml` files.
  - **Location:** [unpack.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/scripts/office/unpack.py#L96)
  - **Dependencies:** `zipfile`, `shutil`, `os`, `merge_runs_in_xml`.

## 3. Dependencies

### Internal Dependencies
*(None within this specific Python package, as they are mostly standalone utility scripts).*

### External Dependencies
* **Standard Lib:** `sys`, `os`, `argparse`, `zipfile`, `shutil`
* **Third-Party Types:**
  * `lxml.etree` - used extensively across the scripts to parse, navigate, and transform DOCX (OOXML) files securely and precisely.

## 4. Relationships
- **Input/Output flow:** `unpack.py` extracts a DOCX -> `comment.py` manipulates the OOXML directly to add Word Comments -> `pack.py` bundles the modified directory back into a standard `.docx` file.
