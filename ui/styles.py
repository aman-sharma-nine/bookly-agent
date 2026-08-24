"""Scoped CSS for the Bookly customer-support surface."""

APP_CSS = r"""
<style>
:root {
  --bookly-ink: #2a2926;
  --bookly-muted: #77736b;
  --bookly-paper: #f8f3ec;
  --bookly-surface: #fffaf5;
  --bookly-sand: #eee4d9;
  --bookly-line: #dfd2c4;
  --bookly-plum: #563c4b;
  --bookly-plum-soft: #eee2e8;
  --bookly-sage: #53655a;
  --bookly-sage-soft: #e3ece5;
  --bookly-warm: #a36d48;
  --bookly-warm-soft: #f2e3d6;
  --bookly-ochre: #bd9153;
  --bookly-ochre-soft: #f1e6d1;
  --bookly-clay: #98645c;
  --bookly-clay-soft: #f2e1de;
  --bookly-blue: #587477;
  --bookly-blue-soft: #e1ebeb;
  --bookly-lavender: #74657b;
  --bookly-lavender-soft: #ebe5ee;
}

html, body, [class*="css"] { font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
body { background: var(--bookly-paper); color: var(--bookly-ink); }

[data-testid="stAppViewContainer"] {
  background: radial-gradient(circle at 90% 0%, rgba(189, 145, 83, .14), transparent 23%), var(--bookly-paper);
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { visibility: hidden; height: 0; }
section.main > div.block-container {
  max-width: 1040px;
  padding: 34px clamp(18px, 4vw, 56px) 110px;
}

.bookly-header {
  display: flex; align-items: center; justify-content: space-between;
  padding-bottom: 24px; border-bottom: 1px solid var(--bookly-line);
  margin-bottom: 68px;
}
.bookly-header-brand {
  display: flex; align-items: center; justify-content: space-between;
  padding-bottom: 24px; border-bottom: 1px solid #d6c3b4;
  margin-bottom: 68px; min-height: 38px;
}
.bookly-brand { display: flex; align-items: center; gap: 11px; color: var(--bookly-ink); }
.bookly-mark {
  width: 38px; height: 34px; display: inline-flex; align-items: center; justify-content: center;
  color: var(--bookly-plum); transform: rotate(-2deg); filter: drop-shadow(0 4px 7px rgba(86, 60, 75, .16));
}
.bookly-mark svg { display: block; width: 38px; height: 34px; }
.bookly-name { font: 600 24px/1 "Iowan Old Style", Baskerville, Georgia, serif; letter-spacing: -0.03em; }
.bookly-header-note { color: var(--bookly-muted); font-size: 13px; letter-spacing: .02em; }

.welcome { max-width: 680px; margin: 0 auto 44px; text-align: center; }
.welcome-kicker { color: var(--bookly-warm); font-size: 12px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; margin-bottom: 13px; }
.welcome-illustration { width: min(210px, 58vw); margin: 0 auto 11px; filter: drop-shadow(0 12px 18px rgba(86, 60, 75, .08)); }
.welcome-illustration svg { display: block; width: 100%; height: auto; }
.welcome h1 { font: 600 clamp(38px, 5.6vw, 62px)/1.02 "Iowan Old Style", Baskerville, Georgia, serif; letter-spacing: -.045em; margin: 0 0 18px; color: var(--bookly-ink); }
.welcome p { color: var(--bookly-muted); font-size: 16px; line-height: 1.65; margin: 0 auto; max-width: 450px; }

/* One button language for all custom Streamlit actions. Suggestion chips
   layer their own muted fills on top of this shared geometry. */
div[data-testid="stButton"] button {
  min-height: 40px; padding: 0 16px; border: 1px solid #d2c1b3;
  border-radius: 999px; background: var(--bookly-surface); color: var(--bookly-plum);
  font-size: 12px; font-weight: 600; letter-spacing: .005em;
  box-shadow: 0 2px 0 rgba(86, 60, 75, .04);
  transition: background .18s ease-out, border-color .18s ease-out, color .18s ease-out, transform .18s ease-out, box-shadow .18s ease-out;
}
div[data-testid="stButton"] button:hover {
  border-color: var(--bookly-plum); background: var(--bookly-plum-soft); color: var(--bookly-plum);
  box-shadow: 0 4px 10px rgba(86, 60, 75, .09); transform: translateY(-1px);
}
div[data-testid="stButton"] button:focus-visible { outline: 3px solid var(--bookly-ochre-soft); outline-offset: 2px; }

.suggestion-label { color: var(--bookly-muted); font-size: 12px; margin: 0 0 10px 2px; text-align: left; }
div[data-testid="stHorizontalBlock"]:has(.suggestion-chip) { gap: 9px; margin-bottom: 9px; }
div[data-testid="stHorizontalBlock"]:has(.suggestion-chip) [data-testid="stButton"] button {
  width: 100%; min-height: 46px; padding: 7px 14px; border-radius: 999px; border: 1px solid var(--bookly-line);
  background: var(--bookly-surface); color: var(--bookly-ink); font-size: 13px; font-weight: 500; line-height: 1.25;
  transition: all .18s ease-out; box-shadow: none;
}
/* Each pill is keyed in Streamlit, giving it a stable st-key-* hook. */
.st-key-suggestion-pill-plum button { background: var(--bookly-plum-soft) !important; border-color: #d9c3cf !important; color: var(--bookly-plum) !important; }
.st-key-suggestion-pill-sage button { background: var(--bookly-sage-soft) !important; border-color: #c7d8cb !important; color: var(--bookly-sage) !important; }
.st-key-suggestion-pill-ochre button { background: var(--bookly-ochre-soft) !important; border-color: #dfcba7 !important; color: #946f38 !important; }
.st-key-suggestion-pill-blue button { background: var(--bookly-blue-soft) !important; border-color: #c5d8d9 !important; color: var(--bookly-blue) !important; }
.st-key-suggestion-pill-clay button { background: var(--bookly-clay-soft) !important; border-color: #e1c5c0 !important; color: var(--bookly-clay) !important; }
.st-key-suggestion-pill-lavender button { background: var(--bookly-lavender-soft) !important; border-color: #d5c9da !important; color: var(--bookly-lavender) !important; }
.st-key-suggestion-pill-plum button:hover,
.st-key-suggestion-pill-sage button:hover,
.st-key-suggestion-pill-ochre button:hover,
.st-key-suggestion-pill-blue button:hover,
.st-key-suggestion-pill-clay button:hover,
.st-key-suggestion-pill-lavender button:hover {
  transform: translateY(-1px); box-shadow: 0 4px 10px rgba(86, 60, 75, .08);
}

[data-testid="stChatMessage"] { padding: 13px 0; gap: 13px; }
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarUser"] { background: var(--bookly-sand); color: var(--bookly-muted); }
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"] { background: var(--bookly-plum); color: #fffaf7; }
[data-testid="stChatMessage"] [data-testid="stChatMessageAvatarAssistant"] svg { width: 18px; height: 18px; }
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] p { line-height: 1.7; font-size: 15px; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { margin-left: 12%; }
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) > div:last-child {
  background: var(--bookly-plum-soft); border: 1px solid #e1d0d8; border-radius: 18px 18px 4px 18px; padding: 4px 17px;
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) > div:last-child { padding-top: 0; }

.thinking-panel { min-width: min(390px, 75vw); padding: 10px 13px 11px; color: var(--bookly-muted); background: var(--bookly-warm-soft); border-left: 3px solid var(--bookly-ochre); border-radius: 3px 11px 11px 3px; }
.thinking-heading { color: var(--bookly-ink); font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.thinking-dot { display: inline-block; width: 7px; height: 7px; margin: 0 8px 1px 1px; border-radius: 50%; background: var(--bookly-ochre); animation: bookly-pulse 1.25s ease-in-out infinite; }
.thinking-step { padding: 3px 0 3px 16px; font-size: 12px; line-height: 1.45; }
@keyframes bookly-pulse { 0%, 100% { opacity: .35; transform: scale(.82); } 50% { opacity: 1; transform: scale(1); } }

.action-card {
  display: flex; align-items: flex-start; gap: 13px; margin: 18px 0 7px;
  border: 1px solid var(--bookly-line); border-left: 3px solid var(--bookly-sage);
  background: var(--bookly-sage-soft); padding: 16px 17px; border-radius: 4px 12px 12px 4px;
}
.action-card.review { border-color: #e2c9af; border-left-color: var(--bookly-warm); background: var(--bookly-warm-soft); }
.action-card.blocked, .action-card.failed { border-color: #e1c5c0; border-left-color: var(--bookly-clay); background: var(--bookly-clay-soft); }
.action-icon { color: var(--bookly-sage); padding-top: 1px; flex: 0 0 22px; }
.action-icon svg { display: block; width: 22px; height: 22px; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
.review .action-icon { color: var(--bookly-warm); }
.blocked .action-icon, .failed .action-icon { color: var(--bookly-clay); }
.action-title { font-size: 14px; font-weight: 700; margin-bottom: 3px; }
.action-body { color: var(--bookly-muted); font-size: 13px; line-height: 1.5; }
.action-value { color: var(--bookly-ink); font: 600 23px/1.1 "Iowan Old Style", Baskerville, Georgia, serif; margin: 3px 0 5px; }

.trace-wrap { margin-top: 14px; }
.trace-row { border-top: 1px solid var(--bookly-line); padding: 10px 0; }
.trace-call { color: var(--bookly-ink); font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
.trace-result { color: var(--bookly-sage); font-size: 12px; margin-top: 3px; }
.trace-result.failed { color: var(--bookly-clay); }

div[data-testid="stExpander"] { border: 0; border-top: 1px solid var(--bookly-line); border-radius: 0; background: transparent; }
div[data-testid="stExpander"] summary p { color: var(--bookly-muted); font-size: 12px; }

[data-testid="stChatInput"] { padding-bottom: 14px; }
[data-testid="stChatInput"] > div { border: 1px solid #d6c4b4; background: var(--bookly-surface); border-radius: 16px; box-shadow: 0 9px 26px rgba(86, 60, 75, .08); }
[data-testid="stChatInput"] textarea { color: var(--bookly-ink); font-size: 15px; }
[data-testid="stChatInput"] textarea::placeholder { color: #9d988f; }
[data-testid="stChatInput"] > div:focus-within { border-color: var(--bookly-plum); box-shadow: 0 0 0 3px var(--bookly-plum-soft), 0 9px 26px rgba(86, 60, 75, .08); }

[data-testid="stSidebar"] { background: var(--bookly-sage-soft); border-right: 1px solid #c7d8cb; }
[data-testid="stSidebar"] > div:first-child { padding: 25px 20px; }
.sidebar-kicker { color: var(--bookly-warm); font-size: 11px; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; margin: 4px 0 11px; }
.sidebar-title { font: 600 27px/1.08 "Iowan Old Style", Baskerville, Georgia, serif; letter-spacing: -.03em; margin-bottom: 10px; }
.sidebar-copy { color: var(--bookly-muted); font-size: 13px; line-height: 1.55; }
.demo-order { border-top: 1px solid var(--bookly-line); padding: 14px 0 2px; margin-top: 22px; }
.demo-order strong { display: block; color: var(--bookly-ink); font-size: 13px; margin-bottom: 4px; }
.demo-order span { display: block; color: var(--bookly-muted); font-size: 12px; line-height: 1.45; }
.demo-note { color: var(--bookly-muted); font-size: 11px; line-height: 1.5; margin-top: 28px; }

div[data-testid="stHorizontalBlock"]:has(.bookly-header-brand) [data-testid="stButton"] button {
  min-height: 38px; font-size: 12px; white-space: nowrap; background: var(--bookly-plum-soft); border-color: #d9c3cf;
}
section[data-testid="stSidebar"] [data-testid="stButton"] button {
  background: var(--bookly-surface); border-color: #c7d8cb; color: var(--bookly-sage);
}

@media (max-width: 680px) {
  section.main > div.block-container { padding: 22px 15px 100px; }
  .bookly-header { margin-bottom: 48px; padding-bottom: 18px; }
  .bookly-header-brand { margin-bottom: 48px; padding-bottom: 18px; }
  .bookly-header-note { display: none; }
  .welcome { margin-bottom: 34px; }
  .welcome h1 { font-size: 42px; }
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) { margin-left: 3%; }
  div[data-testid="stHorizontalBlock"]:has(.suggestion-chip) [data-testid="stButton"] button { min-height: 48px; font-size: 12px; padding: 7px 8px; white-space: normal; }
  div[data-testid="stHorizontalBlock"]:has(.bookly-header-brand) [data-testid="stButton"] button { font-size: 11px; padding: 0 5px; }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { transition-duration: .01ms !important; animation-duration: .01ms !important; }
  .thinking-dot { animation: none; opacity: 1; }
}
</style>
"""
