import sys
from pathlib import Path

# Add project root to Python path BEFORE importing backend modules
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import asyncio
import uuid

import streamlit as st
import httpx

from backend.config import settings
from backend.graph.workflow import run_weather_bot
from backend.services.sop_service import sop_service


# ============================================================
# Page Configuration
# ============================================================

st.set_page_config(
    page_title="Weather Advisory Support Bot",
    page_icon="⛅",
    layout="wide"
)


# ============================================================
# Custom Styling
# ============================================================

st.markdown("""
<style>
    .main-title {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
        color: #1E3A8A;
    }

    .sub-title {
        font-size: 1.0rem;
        color: #4B5563;
        margin-bottom: 1.5rem;
    }

    .badge-critical {
        background-color: #FEE2E2;
        color: #991B1B;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.85rem;
        border: 1px solid #F87171;
    }

    .badge-high {
        background-color: #FFEDD5;
        color: #9A3412;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.85rem;
        border: 1px solid #FB923C;
    }

    .badge-moderate {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.85rem;
        border: 1px solid #FCD34D;
    }

    .badge-low {
        background-color: #DCFCE7;
        color: #166534;
        padding: 4px 10px;
        border-radius: 9999px;
        font-weight: 700;
        font-size: 0.85rem;
        border: 1px solid #86EFAC;
    }

    .weather-card {
        background-color: #F3F4F6;
        border-radius: 8px;
        padding: 10px 14px;
        margin-top: 8px;
        font-size: 0.9rem;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# Session State Initialization
# ============================================================

if "session_id" not in st.session_state:
    st.session_state.session_id = f"sess_{str(uuid.uuid4())[:8]}"

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


# ============================================================
# Sidebar
# ============================================================

with st.sidebar:

    st.header("⚙️ Session & Policy Controls")

    st.write(
        f"**Session ID:** `{st.session_state.session_id}`"
    )

    if st.button(
        "🔄 Reset / New Session",
        use_container_width=True
    ):
        st.session_state.session_id = (
            f"sess_{str(uuid.uuid4())[:8]}"
        )

        st.session_state.chat_history = []

        st.rerun()

    st.markdown("---")

    st.subheader("📋 Active SOP Policies")

    try:
        sops = sop_service.load_sops()

        st.write(
            f"Loaded **{len(sops)} authorized SOPs**:"
        )

        for sop in sops:

            sev_color = {
                "critical": "red",
                "high": "orange",
                "moderate": "gold",
                "low": "green"
            }.get(
                sop.severity,
                "blue"
            )

            st.markdown(
                f"- **{sop.id}**: "
                f"{sop.name} "
                f"(:{sev_color}[{sop.severity.upper()}])"
            )

    except Exception as e:

        st.error(
            f"Unable to load SOP policies: {str(e)}"
        )

    st.markdown("---")

    st.caption(
        "🛡️ Core Principle: The LLM NEVER invents safety advice. "
        "All guidance strictly derives from active SOP policies "
        "evaluated against live Open-Meteo data."
    )


# ============================================================
# Main Interface Header
# ============================================================

st.markdown(
    '<div class="main-title">'
    '⛅ Weather-Advisory Support Bot'
    '</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="sub-title">'
    'Deterministic safety guidance powered by LangGraph, '
    'Live Open-Meteo data, and externalized SOP policies.'
    '</div>',
    unsafe_allow_html=True
)


# ============================================================
# Display Chat History
# ============================================================

for msg in st.session_state.chat_history:

    with st.chat_message(msg["role"]):

        st.markdown(msg["content"])

        # Assistant metadata
        if (
            msg["role"] == "assistant"
            and "metadata" in msg
        ):

            meta = msg["metadata"]

            # ------------------------------------------------
            # SOP Citation
            # ------------------------------------------------

            if meta.get("selected_sop"):

                sop = meta["selected_sop"]

                sev = sop.get(
                    "severity",
                    "moderate"
                ).lower()

                badge_class = f"badge-{sev}"

                st.markdown(
                    f'<div style="margin-top: 8px;">'
                    f'<span class="{badge_class}">'
                    f'SOP Citation: '
                    f'{sop.get("id")} — '
                    f'{sop.get("name")} '
                    f'({sev.upper()})'
                    f'</span>'
                    f'</div>',
                    unsafe_allow_html=True
                )

            # ------------------------------------------------
            # Weather Facts
            # ------------------------------------------------

            if meta.get("weather"):

                w = meta["weather"]

                st.markdown(
                    f'<div class="weather-card">'
                    f'<b>Verified Meteorological '
                    f'Observations '
                    f'({w.get("time_context", "current")}):'
                    f'</b><br>'

                    f'🌡️ Temp: '
                    f'<b>{w.get("temperature_c")}°C</b> | '

                    f'💨 Wind: '
                    f'<b>{w.get("wind_speed_kmh")} km/h</b> | '

                    f'🌧️ Rain: '
                    f'<b>{w.get("precipitation_mm")} mm</b> '
                    f'({w.get("precipitation_probability")}%) | '

                    f'☀️ UV: '
                    f'<b>{w.get("uv_index")}</b>'

                    f'</div>',
                    unsafe_allow_html=True
                )


# ============================================================
# Chat Input
# ============================================================

user_query = st.chat_input(
    "Ask about outdoor safety "
    "(e.g., 'Is it safe to cycle in Bhopal today?')"
)


# ============================================================
# Process User Query
# ============================================================

if user_query:

    # --------------------------------------------------------
    # Add User Message
    # --------------------------------------------------------

    st.session_state.chat_history.append(
        {
            "role": "user",
            "content": user_query
        }
    )

    with st.chat_message("user"):
        st.markdown(user_query)


    # --------------------------------------------------------
    # Assistant Response
    # --------------------------------------------------------

    with st.chat_message("assistant"):

        with st.spinner(
            "Analyzing live weather and evaluating "
            "authorized SOP policies..."
        ):

            try:

                # ------------------------------------------------
                # Create event loop
                # ------------------------------------------------

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                try:

                    result_state = loop.run_until_complete(
                        run_weather_bot(
                            user_query,
                            session_id=(
                                st.session_state.session_id
                            )
                        )
                    )

                finally:

                    loop.close()


                # ------------------------------------------------
                # Extract Response
                # ------------------------------------------------

                response_text = result_state.get(
                    "response",
                    "No response generated."
                )

                st.markdown(response_text)


                # ------------------------------------------------
                # Metadata
                # ------------------------------------------------

                metadata = {
                    "status": result_state.get(
                        "status"
                    ),

                    "selected_sop": result_state.get(
                        "selected_sop"
                    ),

                    "weather": result_state.get(
                        "weather"
                    ),

                    "location": result_state.get(
                        "location"
                    )
                }


                # ------------------------------------------------
                # SOP Citation
                # ------------------------------------------------

                if metadata.get("selected_sop"):

                    sop = metadata[
                        "selected_sop"
                    ]

                    sev = sop.get(
                        "severity",
                        "moderate"
                    ).lower()

                    badge_class = (
                        f"badge-{sev}"
                    )

                    st.markdown(
                        f'<div style="margin-top: 8px;">'
                        f'<span class="{badge_class}">'
                        f'SOP Citation: '
                        f'{sop.get("id")} — '
                        f'{sop.get("name")} '
                        f'({sev.upper()})'
                        f'</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )


                # ------------------------------------------------
                # Weather Facts
                # ------------------------------------------------

                if metadata.get("weather"):

                    w = metadata["weather"]

                    st.markdown(
                        f'<div class="weather-card">'
                        f'<b>Verified Meteorological '
                        f'Observations '
                        f'({w.get("time_context", "current")}):'
                        f'</b><br>'

                        f'🌡️ Temp: '
                        f'<b>{w.get("temperature_c")}°C</b> | '

                        f'💨 Wind: '
                        f'<b>{w.get("wind_speed_kmh")} km/h</b> | '

                        f'🌧️ Rain: '
                        f'<b>{w.get("precipitation_mm")} mm</b> '
                        f'({w.get("precipitation_probability")}%) | '

                        f'☀️ UV: '
                        f'<b>{w.get("uv_index")}</b>'

                        f'</div>',
                        unsafe_allow_html=True
                    )


                # ------------------------------------------------
                # Save Assistant Message
                # ------------------------------------------------

                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": response_text,
                        "metadata": metadata
                    }
                )


            # ----------------------------------------------------
            # Error Handling
            # ----------------------------------------------------

            except Exception as e:

                err_msg = (
                    "⚠️ An error occurred while evaluating "
                    f"your request: {str(e)}"
                )

                st.error(err_msg)

                st.session_state.chat_history.append(
                    {
                        "role": "assistant",
                        "content": err_msg
                    }
                )