#
#  Copyright (c) 2026, Adinfinitium team
#
#  Permission to use, copy, modify, and/or distribute this software for any
#  purpose with or without fee is hereby granted, provided that the above
#  copyright notice and this permission notice appear in all copies.
#
"""Streamlit wrapper that embeds the mission-control page next to the team's other apps.

The page itself is plain HTML/JS served by ``python -m lunar_ops.server``; this file only frames it, so there is
one user interface to maintain. Run::

    python -m lunar_ops.server --port 8600
    streamlit run lunar_ops/streamlit_app.py --server.port 8502
"""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

DEFAULT_URL = "http://127.0.0.1:8600/"
FRAME_HEIGHT_PX = 900  # [px] iframe height

st.set_page_config(page_title="Adinfinitium Mission Control", layout="wide")
url = st.sidebar.text_input("Mission-control server", DEFAULT_URL)
st.sidebar.caption("Append ?replay=1 to play the recorded sample instead of connecting to a live backend.")
components.iframe(url, height=FRAME_HEIGHT_PX, scrolling=False)
