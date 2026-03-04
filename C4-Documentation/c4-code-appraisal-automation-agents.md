# Code Level: appraisal-automation/agents

## 1. Overview
- **Name:** Multi-Agent Review Architecture
- **Description:** The AI agent subsystem responsible for reviewing document text by running multiple specialized LLM agents in parallel (Phrasing, Spelling, Consistency) and aggregating their findings.
- **Location:** [appraisal-automation/agents](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/agents/)
- **Language:** Python
- **Purpose:** To provide automated, parallelized quality assurance and review of documents, catching style, grammar, and logical consistency issues.

## 2. Code Elements

### Classes
#### `MultiAgentReviewer`
- **Description:** Core orchestrator for the multi-agent review architecture. Manages thread pools, metrics, and executes API calls to various LLM providers in parallel.
- **Location:** [reviewer.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/agents/reviewer.py#L28)
- **Dependencies:** `concurrent.futures`, `openai`, `google.genai`, `agents.prompts`, `agents.aggregator.aggregate_findings`, `config`.
- **Methods:**
  - `_call_llm(self, agent_name: str, model: str, system_prompt: str, user_text: str) -> List[Finding]`: Generic LLM call wrapper with timing and fallback handling.
  - `_call_openai(self, model: str, system_prompt: str, user_text: str) -> List[Finding]`: Calls OpenAI API.
  - `_call_gemini(self, model: str, system_prompt: str, user_text: str) -> List[Finding]`: Calls Google Gemini API.
  - `run_review(self, paragraphs_text: str) -> List[Finding]`: Runs 3 specialized agents in parallel and aggregates their results.
  - `get_debug_summary(self) -> str`: Returns a markdown summary of timing and model usage.

### Functions

#### `aggregate_findings(phrasing_findings, spelling_findings, consistency_findings) -> list[Finding]`
- **Description:** Merges finding objects from multiple agents into a final list. Enforces rules such as limiting phrasing issues and merging minor issues into a single bulleted comment per paragraph to avoid review-clutter.
- **Location:** [aggregator.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/agents/aggregator.py#L14)
- **Dependencies:** Custom `Finding` TypedDict.

### Variables / Prompts

#### `PHRASING_PROMPT`
- **Description:** System prompt for the Phrasing & Hebrew Flow Agent.
- **Location:** [prompts.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/agents/prompts.py#L7)

#### `SPELLING_PROMPT`
- **Description:** System prompt for the Spelling & Punctuation Agent.
- **Location:** [prompts.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/agents/prompts.py#L32)

#### `CONSISTENCY_PROMPT`
- **Description:** System prompt for the Fact & Cross-Section Consistency Agent.
- **Location:** [prompts.py](file:///d:/Antigravity%20projects/RAMI%20PROJCT/rami_project/appraisal-automation/agents/prompts.py#L56)

## 3. Dependencies

### Internal Dependencies
- `config`: Provides configuration flags (`OPENAI_API_KEY`, `GEMINI_API_KEY`, model selection routers, etc.)

### External Dependencies
- `openai`: Python SDK for communicating with OpenAI endpoints.
- `google.genai`: Python SDK for communicating with Google Gemini endpoints.

## 4. Relationships
The `reviewer.py` orchestrates the process by taking text and spinning up independent task threads to query the LLMs with prompts defined in `prompts.py`. It takes the JSON array output of these models and passes them to `aggregator.py` which unifies the output structure.
