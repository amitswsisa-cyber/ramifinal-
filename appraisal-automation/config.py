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
try:
    import streamlit as st
    ANTHROPIC_API_KEY = st.secrets["api_keys"].get("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", ""))
    OPENAI_API_KEY    = st.secrets["api_keys"].get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    GEMINI_API_KEY    = st.secrets["api_keys"].get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
    APP_PASSWORD      = st.secrets["passwords"].get("APP_PASSWORD", "")
except (ImportError, KeyError, FileNotFoundError):
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY    = os.environ.get("OPENAI_API_KEY", "")
    GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
    APP_PASSWORD      = os.environ.get("APP_PASSWORD", "") # Fallback for local testing

# OpenAI model for Stage 2 review (alternative to Claude)
OPENAI_REVIEW_MODEL = "o3-mini"
GEMINI_REVIEW_MODEL = "gemini-3-flash-preview"

# ── Output naming ─────────────────────────────────────────────────────────────
STAGE1_SUFFIX = "_filled"
STAGE2_SUFFIX = "_reviewed"

# ── Temp directory ────────────────────────────────────────────────────────────
TEMP_DIR = os.path.join(os.path.dirname(__file__), "_temp")
os.makedirs(TEMP_DIR, exist_ok=True)
