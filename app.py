"""Bookly's customer-facing Streamlit support experience.

This module owns presentation state only. The existing Agents SDK agent,
SQLiteSession, tools, policies, and prompts remain the source of truth.
"""

from __future__ import annotations

import asyncio
import html
import re
import uuid

import streamlit as st

import tools
from agent import create_session, run_turn
from ui.styles import APP_CSS
from ui.trace import derive_action_cards, extract_tool_events, icon_svg, trace_line


SUGGESTIONS = [
    {"label": "Where is my order?", "icon": ":material/local_shipping:", "tone": "plum"},
    {"label": "My order hasn't arrived", "icon": ":material/package_2:", "tone": "sage"},
    {"label": "I'd like help with a refund", "icon": ":material/replay:", "tone": "ochre"},
    {"label": "What are your shipping options?", "icon": ":material/route:", "tone": "blue"},
    {"label": "I need to return a book", "icon": ":material/undo:", "tone": "clay"},
    {"label": "I forgot my password", "icon": ":material/key:", "tone": "lavender"},
]

_CURRENCY_SYMBOL_RE = re.compile(r"(?<!\\)\$(?=\d)")


def _new_session() -> object:
    return create_session(f"bookly-streamlit-{uuid.uuid4().hex}")


def _ensure_state() -> None:
    # Streamlit reruns this script after most interactions. Keeping the
    # SQLiteSession object in session_state is what preserves SDK memory.
    if "conversation_session" not in st.session_state:
        st.session_state.conversation_session = _new_session()
    if "messages" not in st.session_state:
        st.session_state.messages = []


def _reset_conversation() -> None:
    old_session = st.session_state.get("conversation_session")
    if old_session is not None:
        old_session.close()

    # The SQLite conversation and mutable simulated action state are separate
    # stores, so a demo reset must clear both of them explicitly.
    tools.reset_state()
    st.session_state.conversation_session = _new_session()
    st.session_state.messages = []


def _run_async(coro):
    """Run the existing async agent entrypoint from Streamlit's sync script."""
    return asyncio.run(coro)


def _loading_label(message: str) -> str:
    """Describe the user's intent without claiming a tool has already run."""
    lowered = message.lower()
    if any(word in lowered for word in ("refund", "money back", "return")):
        return "Bookly is reviewing the available refund options…"
    if any(word in lowered for word in ("order", "arrived", "delivery", "delivered", "shipping")):
        return "Bookly is checking the delivery details…"
    return "Bookly is reviewing your request…"


def _render_copy(text: str) -> None:
    """Render chat Markdown without letting currency become inline math.

    Streamlit's Markdown renderer treats `$...$` as LaTeX. Escaping dollar
    signs before a numeric amount keeps customer text such as ``A$75`` and
    ``A$50`` readable while preserving normal bold, lists, and line breaks.
    """
    st.markdown(_CURRENCY_SYMBOL_RE.sub(r"\\$", text))


def _handle_message(message: str) -> None:
    message = message.strip()
    if not message:
        return

    st.session_state.messages.append({"role": "user", "content": message})
    events = []
    assistant_text = ""
    cards = []

    # Render the assistant progress surface in the same Streamlit run as the
    # submitted user message. The SDK call is complete-result based, so the
    # exact tool trace is rendered only after result.new_items is available.
    with st.chat_message("assistant", avatar=":material/menu_book:"):
        with st.status(_loading_label(message), expanded=True) as progress:
            st.markdown(
                '<div class="thinking-panel">'
                '<div class="thinking-heading"><span class="thinking-dot"></span>Reviewing your request</div>'
                '<div class="thinking-step">Keeping the conversation in context</div>'
                '<div class="thinking-step">Using Bookly’s support workflow where needed</div>'
                '<div class="thinking-step">Preparing the clearest next step</div>'
                '</div>',
                unsafe_allow_html=True,
            )
            try:
                result = _run_async(run_turn(message, st.session_state.conversation_session))
                events = extract_tool_events(result)
                assistant_text = str(getattr(result, "final_output", "") or "").strip()
                if not assistant_text:
                    assistant_text = "I’m sorry, I wasn’t able to complete that response. Please try again."
                cards = derive_action_cards(events)
                progress.update(label="Bookly Support is ready", state="complete", expanded=False)
            except Exception:
                # Keep SDK exceptions out of the customer surface. The local
                # demo can still continue after a transient integration error.
                assistant_text = "I’m sorry, I couldn’t connect to Bookly Support just now. Please try again."
                progress.update(label="Bookly Support couldn’t connect", state="error", expanded=False)

        _render_copy(assistant_text)
        for card in cards:
            _render_action_card(card)
        _render_trace(events)

    st.session_state.messages.append({
        "role": "assistant",
        "content": assistant_text,
        "events": events,
        "cards": cards,
    })


def _logo() -> str:
    return """<div class="bookly-brand"><span class="bookly-mark"><svg width="38" height="34" viewBox="0 0 38 34" fill="none" aria-hidden="true"><rect x="1" y="1" width="36" height="32" rx="10" fill="#563C4B"/><path d="M8.5 10.5c4.2-1.8 7.8-1.4 10.5.8v13.2c-2.8-1.9-6.3-2.2-10.5-.8V10.5Z" fill="#FFF8EF"/><path d="M29.5 10.5c-4.2-1.8-7.8-1.4-10.5.8v13.2c2.8-1.9 6.3-2.2 10.5-.8V10.5Z" fill="#F1E6D1"/><path d="M19 11.3v13.1" stroke="#A36D48" stroke-width="1.5" stroke-linecap="round"/><path d="M25.5 5.8v6.1l2.1-1.4 2.1 1.4V5.8" fill="#BD9153"/></svg></span><span class="bookly-name">Bookly</span></div>"""


def _render_header() -> None:
    brand_column, action_column = st.columns([4, 1])
    with brand_column:
        st.markdown(
            f'<div class="bookly-header-brand">{_logo()}<span class="bookly-header-note">Customer Support</span></div>',
            unsafe_allow_html=True,
        )
    with action_column:
        if st.button(
            "New conversation",
            key="new-conversation",
            type="secondary",
            use_container_width=True,
        ):
            _reset_conversation()
            st.rerun()


def _render_action_card(card: dict) -> None:
    state = html.escape(str(card.get("state", "success")))
    icon = icon_svg(str(card.get("icon", "check")))
    title = html.escape(str(card.get("title", "Action updated")))
    body = html.escape(str(card.get("body", "")))
    value = card.get("value")
    value_html = f'<div class="action-value">{html.escape(str(value))}</div>' if value else ""
    st.markdown(
        f'<div class="action-card {state}"><div class="action-icon">'
        f'{icon}</div><div>'
        f'<div class="action-title">{title}</div>{value_html}'
        f'<div class="action-body">{body}</div></div></div>',
        unsafe_allow_html=True,
    )


def _render_trace(events: list[dict]) -> None:
    if not events:
        return
    with st.expander("View agent activity", expanded=False):
        for event in events:
            call, result = trace_line(event)
            result_class = "" if event.get("success") is not False else "failed"
            st.markdown(
                f'<div class="trace-row"><div class="trace-call">{call}</div>'
                f'<div class="trace-result {result_class}">{html.escape(result)}</div></div>',
                unsafe_allow_html=True,
            )


def _render_message(message: dict) -> None:
    role = message["role"]
    avatar = ":material/menu_book:" if role == "assistant" else ":material/person:"
    with st.chat_message(role, avatar=avatar):
        _render_copy(message["content"])
        for card in message.get("cards", []):
            _render_action_card(card)
        _render_trace(message.get("events", []))


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown('<div class="sidebar-kicker">Local demonstration</div>', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-title">Demo controls</div>', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-copy">Explore Bookly’s delayed-order, refund and review journeys with synthetic order data.</div>', unsafe_allow_html=True)
        st.markdown('<div class="demo-order"><strong>B1001 · Standard order</strong><span>$25 paperback · delayed<br>Useful for delivery and eligible-refund demonstrations.</span></div>', unsafe_allow_html=True)
        st.markdown('<div class="demo-order"><strong>B1002 · Collector edition</strong><span>$250 collector edition · delayed<br>Requires human review.</span></div>', unsafe_allow_html=True)
        st.markdown('<div style="height: 18px"></div>', unsafe_allow_html=True)
        if st.button("Reset conversation", use_container_width=True, type="secondary"):
            _reset_conversation()
            st.rerun()
        st.markdown('<div class="demo-note">Synthetic demo data only. This session is not an authenticated customer account.</div>', unsafe_allow_html=True)


def _render_empty_state() -> str | None:
    st.markdown(
        '<div class="welcome"><div class="welcome-kicker">Bookly Customer Support</div>'
        '<div class="welcome-illustration" aria-hidden="true">'
        '<svg viewBox="0 0 210 126" fill="none">'
        '<circle cx="157" cy="42" r="27" fill="#E9D3A8"/>'
        '<path d="M31 82c28-25 61-28 74-5 17-22 46-19 75 5-34 4-66 17-75 29-10-12-40-25-74-29Z" fill="#563C4B" opacity=".95"/>'
        '<path d="M105 77c-13-19-38-25-62-15l13 35c17 1 35 7 49 14V77Z" fill="#FAF4E9"/>'
        '<path d="M105 77c13-19 38-25 62-15l-13 35c-17 1-35 7-49 14V77Z" fill="#F0E5D6"/>'
        '<path d="M105 77v34M58 68c14 0 31 7 47 17M152 68c-14 0-31 7-47 17" stroke="#A36D48" stroke-width="2" stroke-linecap="round"/>'
        '<path d="M36 45h11M41.5 39.5v11M178 74h8M182 70v8" stroke="#53655A" stroke-width="2" stroke-linecap="round"/>'
        '</svg></div>'
        '<h1>Hi, how can we help?</h1>'
        '<p>Ask about an order, delivery or refund and we’ll help get it sorted.</p></div>',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="suggestion-label">Try asking</div>', unsafe_allow_html=True)
    # Keep the six quick starts in two balanced rows. A single six-column row
    # makes the latter pills too narrow and causes their styling to drift.
    for row_start in range(0, len(SUGGESTIONS), 3):
        columns = st.columns(3)
        for column, suggestion in zip(columns, SUGGESTIONS[row_start:row_start + 3]):
            with column:
                st.markdown('<div class="suggestion-chip">', unsafe_allow_html=True)
                clicked = st.button(
                    suggestion["label"],
                    icon=suggestion["icon"],
                    key=f"suggestion-pill-{suggestion['tone']}",
                    use_container_width=True,
                )
                st.markdown('</div>', unsafe_allow_html=True)
                if clicked:
                    return suggestion["label"]
    return None


def main() -> None:
    st.set_page_config(page_title="Bookly Customer Support", page_icon="📖", layout="centered", initial_sidebar_state="expanded")
    st.markdown(APP_CSS, unsafe_allow_html=True)
    _ensure_state()
    _render_sidebar()
    _render_header()

    for message in st.session_state.messages:
        _render_message(message)

    suggestion = _render_empty_state() if not st.session_state.messages else None
    typed_message = st.chat_input("Message Bookly Support…")
    submitted = typed_message or suggestion
    if submitted:
        # Streamlit normally reruns only after the full script finishes. Paint
        # the user's message before awaiting the agent so the chat feels
        # immediate instead of appearing only after the response is ready.
        with st.chat_message("user", avatar=":material/person:"):
            _render_copy(submitted)
        _handle_message(submitted)
        st.rerun()


if __name__ == "__main__":
    main()
