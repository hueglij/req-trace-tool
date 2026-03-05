"""
Global styling helpers for the Streamlit app.
"""
import streamlit as st

DEFAULT_FONT_SCALE = 0.65

_SAVE_BTN_CONTAINER = (
    '[data-testid="stVerticalBlock"]'
    ":has(.header-save-marker)"
    ":not(:has("
    '[data-testid="stVerticalBlock"] .header-save-marker'
    "))"
)

_STICKY_HEADER_CSS = """
<style>
/* Hide Streamlit's default header so ours can take its place */
header[data-testid="stHeader"] {
  display: none !important;
}
.sticky-page-header {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 999991;
  background: white;
  border-bottom: 2px solid #e0e0e0;
  padding: 0.6rem 1.5rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.sticky-page-header h1 {
  margin: 0;
  padding: 0;
  font-size: 2.5rem;
  line-height: 2.0;
}
.sticky-page-header a.back-btn {
  text-decoration: none;
  background: #1f77b4;
  color: white;
  padding: 0.35rem 1.2rem;
  border-radius: 6px;
  font-size: 1.4rem;
  white-space: nowrap;
}
.sticky-page-header a.back-btn:hover {
  background: #155a8a;
}
/* Push page content below the fixed header */
section[data-testid="stMain"] > div[data-testid="stMainBlockContainer"] {
  padding-top: 3.5rem !important;
}

/* --- Save button: real st.button() CSS-positioned into the header --- */
.header-save-marker { display: none; }

/* Collapse the save-button container so it takes no page space */
%(ctr)s {
  height: 0 !important;
  min-height: 0 !important;
  overflow: visible !important;
  gap: 0 !important;
}
%(ctr)s > div {
  height: 0 !important;
  min-height: 0 !important;
  overflow: visible !important;
  padding: 0 !important;
  margin: 0 !important;
}

/* Force every wrapper div inside the container to shrink-wrap */
%(ctr)s div {
  width: auto !important;
  min-width: 0 !important;
}

/* Float the button wrapper into the sticky header bar */
%(ctr)s [data-testid="stButton"] {
  position: fixed !important;
  top: 1.7rem;
  right: 17rem;
  z-index: 999992;
  width: auto !important;
  display: inline-block !important;
}
%(ctr)s [data-testid="stButton"] > button {
  width: auto !important;
  min-width: 0 !important;
  display: inline-flex !important;
  background-color: #28a745 !important;
  color: white !important;
  border: none !important;
  padding: 0.35rem 1.2rem !important;
  border-radius: 6px !important;
  font-size: 1.4rem !important;
  white-space: nowrap !important;
}
%(ctr)s [data-testid="stButton"] > button p {
  color: white !important;
  font-size: 1.4rem !important;
  margin: 0 !important;
}
%(ctr)s [data-testid="stButton"] > button:hover:not(:disabled) {
  background-color: #218838 !important;
}
%(ctr)s [data-testid="stButton"] > button:disabled {
  background-color: #6c757d !important;
  cursor: not-allowed !important;
}

</style>
""" % {"ctr": _SAVE_BTN_CONTAINER}


def render_sticky_header(title: str, with_save: bool = False):
    """Render a fixed header bar with page title and a back-to-overview button.

    When *with_save* is ``True``, returns a container where the calling page
    can place its save button via ``container.button(...)``.  CSS will
    reposition that button into the sticky header bar automatically.
    """
    st.markdown(_STICKY_HEADER_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""<div class="sticky-page-header">
  <h1>{title}</h1>
  <a class="back-btn" href="/" target="_self">← Project Overview</a>
</div>""",
        unsafe_allow_html=True,
    )
    if with_save:
        save_container = st.container()
        with save_container:
            st.markdown(
                '<div class="header-save-marker"></div>',
                unsafe_allow_html=True,
            )
        return save_container
    return None


# ---------------------------------------------------------------------------
# Shared form-field styling constants & helpers
# ---------------------------------------------------------------------------

REQUIRED_EMPTY_BG = "#fff3bf"
REQUIRED_FILLED_BG = "#e6f4ea"


def css_escape(value: str) -> str:
    """Escape a string for safe use inside CSS attribute selectors."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def is_filled(value, empty_values=None) -> bool:
    """Check whether a form value counts as 'filled in'."""
    if empty_values and value in empty_values:
        return False
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def queue_required_style(style_rules, widget_type: str, label: str, is_filled_val: bool) -> None:
    """Append a CSS rule that highlights a required widget green (filled) or yellow (empty)."""
    color = REQUIRED_FILLED_BG if is_filled_val else REQUIRED_EMPTY_BG
    safe_label = css_escape(label)
    if widget_type == "text":
        style_rules.append(
            f'div[data-testid="stTextInput"] input[aria-label="{safe_label}"] {{ background-color: {color} !important; }}'
        )
        return
    if widget_type == "textarea":
        style_rules.append(
            f'div[data-testid="stTextArea"] textarea[aria-label="{safe_label}"] {{ background-color: {color} !important; }}'
        )
        return
    if widget_type == "select":
        style_rules.append(
            f'div[data-testid="stSelectbox"]:has([aria-label="{safe_label}"]) div[data-baseweb="select"] > div {{ background-color: {color} !important; }}'
        )
        style_rules.append(
            f'div[data-testid="stSelectbox"] [aria-label="{safe_label}"] {{ background-color: {color} !important; }}'
        )


def apply_required_styles(style_rules) -> None:
    """Emit accumulated required-field CSS rules into the page."""
    if not style_rules:
        return
    st.markdown("<style>\n" + "\n".join(style_rules) + "\n</style>", unsafe_allow_html=True)


def apply_global_style(font_scale: float = DEFAULT_FONT_SCALE) -> None:
    """Apply global CSS overrides for consistent sizing."""
    if font_scale <= 0:
        return
    percent = int(round(font_scale * 100))
    st.markdown(
        f"""<style>
html, body, [data-testid=\"stAppViewContainer\"] {{
  font-size: {percent}%;
}}
</style>""",
        unsafe_allow_html=True,
    )
