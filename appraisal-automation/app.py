"""
app.py — Savitzky Appraisal Automation | Streamlit Frontend
============================================================
Two-tab interface:
  Tab 1 — Stage 1: Upload template → Extract fields → Confirm → Download filled DOCX
  Tab 2 — Stage 2: Upload filled DOCX → Run AI review → Download reviewed DOCX

Run locally:
    streamlit run app.py

Deploy to Streamlit Cloud:
    Push to GitHub → connect at streamlit.io/cloud
    Set ANTHROPIC_API_KEY in Streamlit Secrets.
"""
import os
import streamlit as st
from config import APP_PASSWORD

def check_password():
    """Returns True if the user had the correct password."""

    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password"] == APP_PASSWORD:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.text_input(
            "סיסמה", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.text_input(
            "סיסמה", type="password", on_change=password_entered, key="password"
        )
        st.error("😕 סיסמה לא נכונה")
        return False
    else:
        # Password correct.
        return True

if not APP_PASSWORD:
    # If no password set, skip the gate (allow access or show warning)
    pass
elif not check_password():
    st.stop()

# ── SHUMA type options ───────────────────────────────────────────────
SHUMA_TYPE_OPTIONS = [
    "דירת מגורים",
    "בית מגורים צמוד קרקע",
    "מגרש",
    "נכס מסחרי",
    "משרדים",
    "אחר",
]

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Savitzky Appraisal Automation",
    page_icon="🏢",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── RTL CSS for Hebrew UI ─────────────────────────────────────────────────────
st.markdown("""
<style>
/* Force RTL layout for Hebrew */
body, .stApp {
    direction: rtl;
    font-family: 'Segoe UI', Arial, sans-serif;
}
h1, h2, h3, h4, .stMarkdown, .stText, label, .stAlert {
    direction: rtl;
    text-align: right;
}
/* Input boxes RTL */
input[type="text"], textarea {
    direction: rtl;
    text-align: right;
}
/* Tab labels */
button[data-baseweb="tab"] {
    font-size: 1rem;
    font-weight: 600;
}
/* Download button */
.stDownloadButton > button {
    width: 100%;
    background-color: #1a7f37;
    color: white;
    border-radius: 8px;
    padding: 0.6rem 1.2rem;
    font-size: 1rem;
    font-weight: bold;
}
.stDownloadButton > button:hover {
    background-color: #15692e;
}
/* Primary button */
.stButton > button[kind="primary"],
.stButton > button {
    border-radius: 8px;
    font-weight: 600;
}
/* Warning/empty field */
.empty-field {
    color: #c0392b;
    font-weight: bold;
}
/* Section divider */
.section-divider {
    border-top: 2px solid #e0e0e0;
    margin: 1.5rem 0;
}
/* Replacement stats box */
.stats-box {
    background: #f0fff4;
    border: 1px solid #2ecc71;
    border-radius: 8px;
    padding: 1rem;
    margin-top: 1rem;
    direction: rtl;
    font-family: monospace;
    white-space: pre-wrap;
}
</style>
""", unsafe_allow_html=True)

# ── Imports (after page config) ───────────────────────────────────────────────
from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY
from field_extractor import extract_cover_fields, detect_document_type
from stage1_inject import run_stage1
from stage2_review import run_stage2_with_progress

# ── Header ────────────────────────────────────────────────────────────────────
st.title("🏢 כלי אוטומציה לשמאות — סויצקי רמי")
st.markdown("**שמאות מקרקעין וניהול בע\"מ** | מערכת מילוי וביקורת דוחות")
st.markdown("---")

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📋 שלב 1 — מילוי הדוח", "🔍 שלב 2 — ביקורת לפני הגשה"])

# ═══════════════════════════════════════════════════════════════════════
# TAB 1 — STAGE 1: Data Injection
# ═══════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("שלב 1: מילוי אוטומטי של שדות הדוח")
    st.markdown(
        "העלה את תבנית הדוח. המערכת תזהה אוטומטית את כל השדות בעמוד השער "
        "ותציג אותם לאישור לפני המילוי."
    )

    uploaded_template = st.file_uploader(
        "📤 העלה תבנית DOCX",
        type=["docx"],
        key="stage1_uploader",
        help="העלה את קובץ ה-DOCX לפני מילוי. הקובץ יישאר על המחשב שלך.",
    )

    if uploaded_template is not None:
        with st.spinner("🔍 קורא שדות מעמוד השער..."):
            try:
                fields = extract_cover_fields(uploaded_template)
                doc_type = detect_document_type(uploaded_template)
            except Exception as e:
                st.error(f"❌ שגיאה בקריאת הקובץ: {e}")
                st.stop()

        # Show document type
        type_labels = {
            "betterment": "🏗️ היטל השבחה",
            "correction":  "📝 תיקון שומה",
            "standard":    "📄 שומת נכס מקרקעין",
        }
        st.info(f"סוג מסמך שזוהה: **{type_labels.get(doc_type, doc_type)}**")

        if not fields:
            st.warning(
                "⚠️ לא נמצאו שדות בעמוד השער. ודא שהמסמך מכיל טבלת כיסוי עם זוגות label:value."
            )
        else:
            st.markdown(f"**נמצאו {len(fields)} שדות. ערוך לפי הצורך ולחץ על עיבוד:**")
            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

            edited_fields: dict[str, str] = {}
            has_empty = False

            # ── SHUMA type selector (shown only when the field exists in doc) ────
            if "סוג שומה" in fields:
                st.markdown("**סוג הנכס / סוג השומה:**")
                shuma_choice = st.selectbox(
                    "סוג שומה",
                    options=SHUMA_TYPE_OPTIONS,
                    index=0,
                    key="shuma_type_select",
                    help="בחר את סוג הנכס לשומה",
                )
                if shuma_choice == "אחר":
                    shuma_choice = st.text_input(
                        "פרט סוג נכס:",
                        placeholder="לדוגמא: תעשייה",
                        key="shuma_type_custom",
                    )
                # Pre-fill the field value with the selected type
                edited_fields["סוג שומה"] = shuma_choice
                st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

            # ── Other cover fields ─────────────────────────────────────
            for label, value in fields.items():
                # סוג שומה is handled by the selectbox above — skip it here
                if label == "סוג שומה":
                    continue

                display_val = value if value else ""
                if not value.strip():
                    has_empty = True
                    st.markdown(
                        f'<span class="empty-field">⚠️ {label}: שדה ריק</span>',
                        unsafe_allow_html=True,
                    )

                edited_val = st.text_input(
                    label=label,
                    value=display_val,
                    key=f"field_{label}",
                )
                edited_fields[label] = edited_val


            st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

            if has_empty:
                st.warning("⚠️ ישנם שדות ריקים. בדוק אותם לפני העיבוד.")

            col1, col2 = st.columns([2, 1])
            with col1:
                process_btn = st.button(
                    "⚙️ עבד מסמך",
                    type="primary",
                    use_container_width=True,
                    key="process_stage1",
                )

            if process_btn:
                with st.spinner("🔄 מחליף שדות בכל המסמך..."):
                    try:
                        output_path, counts = run_stage1(uploaded_template, edited_fields)
                    except Exception as e:
                        st.error(f"❌ שגיאה בעיבוד: {e}")
                        st.stop()

                # Show replacement summary
                total_replacements = sum(counts.values())
                summary_lines = [f"✅ הושלם. {total_replacements} החלפות סה\"כ:\n"]
                for label, n in counts.items():
                    if n > 0:
                        old_val = fields.get(label, "")
                        new_val = edited_fields.get(label, "")
                        summary_lines.append(
                            f"  {label}: {old_val} → {new_val} ({n} מיקומים)"
                        )

                st.markdown(
                    f'<div class="stats-box">{"<br>".join(summary_lines)}</div>',
                    unsafe_allow_html=True,
                )

                # Download button
                output_name = os.path.basename(output_path)
                with open(output_path, "rb") as f:
                    st.download_button(
                        label="⬇️ הורד דוח ממולא",
                        data=f,
                        file_name=output_name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="download_stage1",
                    )

                st.success(
                    "✅ הדוח ממולא ומוכן. הורד אותו, ערוך אותו ידנית, "
                    "ואז העלה לשלב 2 לביקורת לפני הגשה."
                )

# ═══════════════════════════════════════════════════════════════════════
# TAB 2 — STAGE 2: AI Review
# ═══════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("שלב 2: ביקורת עמיתים בינה מלאכותית")
    st.markdown(
        "לאחר שסיימת לעבוד על הדוח — העלה אותו לביקורת. "
        "המערכת תשתמש ב-Claude AI כדי לבדוק עקביות, חסרים, ניסוח, כתיב ופיסוק. "
        "הממצאים יוזרקו כהערות Word מקוריות."
    )

    # from config import ANTHROPIC_API_KEY, OPENAI_API_KEY, GEMINI_API_KEY

    st.markdown("**בחר מנוע בינה מלאכותית:**")
    api_provider_label = st.radio(
        "מנוע AI",
        options=[
            "ביקורת רב-סוכנית (מהיר ומקיף) 🚀", 
            "Claude (Anthropic)", 
            "GPT-4o/o3-mini (OpenAI)", 
            "Gemini 2.0 Flash (Google)"
        ],
        horizontal=True,
        key="api_provider_radio",
        label_visibility="collapsed",
    )
    if "רב-סוכנית" in api_provider_label:
        api_provider = "multi"
    elif "Anthropic" in api_provider_label:
        api_provider = "anthropic"
    elif "OpenAI" in api_provider_label:
        api_provider = "openai"
    else:
        api_provider = "gemini"

    # Validate the key for the selected provider
    if api_provider == "multi":
        if not OPENAI_API_KEY or not GEMINI_API_KEY:
            st.warning("⚠️ דרושים מפתחות API של OpenAI ו-Gemini עבור ביקורת רב-סוכנית.")
            api_key = None
        else:
            api_key = "multi" # Dummy value to enable button
    elif api_provider == "anthropic":
        api_key = ANTHROPIC_API_KEY
        if not api_key:
            st.warning(
                "⚠️ מפתח API של Anthropic לא מוגדר. "
                "הגדר `ANTHROPIC_API_KEY` כמשתנה סביבה לפני הרצת שלב 2."
            )
    elif api_provider == "openai":
        api_key = OPENAI_API_KEY
        if not api_key:
            st.warning(
                "⚠️ מפתח API של OpenAI לא מוגדר. "
                "הגדר `OPENAI_API_KEY` כמשתנה סביבה לפני הרצת שלב 2."
            )
    else:
        api_key = GEMINI_API_KEY
        if not api_key:
            st.warning(
                "⚠️ מפתח API של Google Gemini לא מוגדר. "
                "הגדר `GEMINI_API_KEY` כמשתנה סביבה לפני הרצת שלב 2."
            )

    uploaded_filled = st.file_uploader(
        "📤 העלה DOCX מוכן לביקורת",
        type=["docx"],
        key="stage2_uploader",
        help="העלה את הגרסה הסופית של הדוח לאחר עריכה ידנית.",
    )

    if uploaded_filled is not None:
        st.info(f"📄 קובץ: **{uploaded_filled.name}** ({uploaded_filled.size:,} bytes)")

        col1, col2 = st.columns([2, 1])
        with col1:
            review_btn = st.button(
                "🔍 הפעל ביקורת",
                type="primary",
                use_container_width=True,
                key="run_stage2",
                disabled=not api_key,
            )

        if review_btn:
            try:
                with st.status("🔄 מריץ ביקורת...", expanded=True) as status:
                    output_path = None
                    summary = None
                    for item in run_stage2_with_progress(uploaded_filled, api_provider=api_provider):
                        if isinstance(item, str):
                            # Progress update
                            status.update(label=item)
                            st.write(item)
                        else:
                            # Final result tuple
                            output_path, summary = item
                    status.update(label="✅ הביקורת הושלמה!", state="complete")
            except ValueError as e:
                st.error(f"❌ שגיאת הגדרה: {e}")
                st.stop()
            except Exception as e:
                st.error(f"❌ שגיאה בביקורת: {e}")
                raise

            # Display Hebrew summary
            st.markdown("---")
            st.markdown("### 📊 סיכום ממצאים")
            for line in summary.split("\n"):
                if line.startswith("✅"):
                    st.success(line)
                elif line.startswith("🔍") or line.startswith("📋") or \
                     line.startswith("✍️") or line.startswith("🗣️") or \
                     line.startswith("✏️"):
                    st.markdown(f"- {line}")
                elif "חמור:" in line or "High:" in line:
                    st.markdown(f"**{line}**")
                else:
                    st.markdown(line)

            st.markdown("---")

            # Download reviewed DOCX
            output_name = os.path.basename(output_path)
            with open(output_path, "rb") as f:
                st.download_button(
                    label="⬇️ הורד דוח נסקר עם הערות",
                    data=f,
                    file_name=output_name,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key="download_stage2",
                )

            st.success(
                "✅ הביקורת הושלמה. פתח את הקובץ ב-Word כדי לראות את ההערות."
            )

# ── Footer ────────────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown(
    "<div style='text-align:center; color:#888; font-size:0.8rem;'>"
    "Savitzky Appraisal Automation v2.0 | סויצקי רמי שמאות מקרקעין וניהול בע\"מ"
    "</div>",
    unsafe_allow_html=True,
)
