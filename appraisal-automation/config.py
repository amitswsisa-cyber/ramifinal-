"""
config.py — Central configuration for Savitzky Appraisal Automation
"""
import os
from dotenv import load_dotenv

# ── Load .env file ────────────────────────────────────────────────────────────
# Search order: 1) appraisal-automation/.env  2) parent directory .env
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)

# Try app directory first, then parent directory
_env_path = os.path.join(_THIS_DIR, ".env")
if not os.path.exists(_env_path):
    _env_path = os.path.join(_PARENT_DIR, ".env")

if os.path.exists(_env_path):
    load_dotenv(_env_path, override=False)

# ── Model ─────────────────────────────────────────────────────────────────────
# Options: "claude-opus-4-6", "claude-sonnet-4-6"
REVIEW_MODEL = "claude-sonnet-4-6"

# ── Review parameters ─────────────────────────────────────────────────────────
REVIEW_MAX_TOKENS = 10000

# ── Word comment author ───────────────────────────────────────────────────────
COMMENT_AUTHOR = "רמי סויצקי"

# ── API Key ───────────────────────────────────────────────────────────────────
# Prioritize st.secrets (Streamlit Cloud) then fall back to environment variables
def get_api_key(key_name: str) -> str:
    """Dynamically get the API key. Priority: session_state > st.secrets > env vars."""
    try:
        import streamlit as st
        # Check session_state first (user-provided key in UI)
        session_key = f"user_{key_name}"
        if session_key in st.session_state:
            val = st.session_state[session_key]
            if val:
                return str(val).strip().strip("\"'")
        if "api_keys" in st.secrets and key_name in st.secrets["api_keys"]:
            val = st.secrets["api_keys"][key_name]
            if val: return str(val).strip().strip("\"'")
        if key_name in st.secrets:
            val = st.secrets[key_name]
            if val: return str(val).strip().strip("\"'")
    except (ImportError, KeyError, FileNotFoundError, Exception):
        pass
    return os.environ.get(key_name, "").strip().strip("\"'")

def get_app_password() -> str:
    """Dynamically get the app password."""
    try:
        import streamlit as st
        if "passwords" in st.secrets and "APP_PASSWORD" in st.secrets["passwords"]:
            val = st.secrets["passwords"]["APP_PASSWORD"]
            if val: return val
        if "APP_PASSWORD" in st.secrets:
            val = st.secrets["APP_PASSWORD"]
            if val: return val
    except (ImportError, KeyError, FileNotFoundError, Exception):
        pass
    return os.environ.get("APP_PASSWORD", "")

# Fallback constants for any older code (still cached at module load)
ANTHROPIC_API_KEY = get_api_key("ANTHROPIC_API_KEY")
OPENAI_API_KEY    = get_api_key("OPENAI_API_KEY")
GEMINI_API_KEY    = get_api_key("GEMINI_API_KEY")
APP_PASSWORD      = get_app_password()

# OpenAI models for Stage 2 review
OPENAI_REVIEW_MODEL = "o3-mini"
OPENAI_DOCX_REVIEW_MODEL = "gpt-4o"  # Single-call docx upload path
GEMINI_REVIEW_MODEL = "gemini-2.0-flash" # Default for single-agent
GEMINI_FULL_REVIEW_MODEL = "gemini-3-flash"  # Rich-text full-doc scan (3 Flash — faster & cheaper than 2.5 Pro)
SPELLING_ONLY_MODEL = "gemini-3-flash"       # Fast spelling/grammar/punctuation-only check

# Multi-Agent Architecture (Task 4)
MULTI_AGENT_PHRASING_A = "gpt-4o"
MULTI_AGENT_PHRASING_B = "gemini-2.0-flash"
MULTI_AGENT_SPELLING   = "gemini-2.0-flash"
MULTI_AGENT_CONSISTENCY = "gemini-2.0-flash"

PHRASING_AB_RATIO = 0.5 # 50/50 test

# -- Output naming -------------------------------------------------------------
STAGE1_SUFFIX = "_filled"
STAGE2_SUFFIX = "_reviewed"

# ── Temp directory ────────────────────────────────────────────────────────────
TEMP_DIR = os.path.join(os.path.dirname(__file__), "_temp")
os.makedirs(TEMP_DIR, exist_ok=True)
