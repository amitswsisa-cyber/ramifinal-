# Savitzky Appraisal Automation — Deployment Root

This repository contains the full appraisal automation project for **סויצקי רמי שמאות מקרקעין וניהול בע"מ**.

## Repository Structure

- `appraisal-automation/`: Core application logic, Streamlit frontend, and processing scripts.
- `APPRAISAL_AUTOMATION_SPEC_v2 (1).md`: Implementation specification.
- `.gitignore`: Configured to protect API keys and private files.

## Streamlit Cloud Deployment Instructions

1. Go to [share.streamlit.io](https://share.streamlit.io).
2. Click **New app**.
3. Repository: `amitswsisa-cyber/rami_project`
4. Main file path: `appraisal-automation/app.py` (Crucial since the app is in a subfolder).
5. Click **Advanced settings**.
6. Paste your secrets in the Secrets box:

```toml
[api_keys]
ANTHROPIC_API_KEY = "your_key_here"
OPENAI_API_KEY = "your_key_here"
GEMINI_API_KEY = "your_key_here"

[passwords]
APP_PASSWORD = "your_chosen_password"
```

7. Click **Deploy**.

## Local Development

```bash
cd appraisal-automation
pip install -r requirements.txt
streamlit run app.py
```
