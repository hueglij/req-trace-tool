"""
Global styling helpers for the Streamlit app.
"""
import streamlit as st

DEFAULT_FONT_SCALE = 0.65

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
</style>
"""


def render_sticky_header(title: str) -> None:
    """Render a fixed header bar with page title and a back-to-overview button."""
    st.markdown(_STICKY_HEADER_CSS, unsafe_allow_html=True)
    st.markdown(
        f"""<div class="sticky-page-header">
  <h1>{title}</h1>
  <a class="back-btn" href="/" target="_self">← Project Overview</a>
</div>""",
        unsafe_allow_html=True,
    )


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
