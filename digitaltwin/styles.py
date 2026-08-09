"""Styling constants for the digital twin Gradio app."""

GOLD = "#ecad0a"
BLUE = "#209dd7"
PURPLE = "#753991"

EXAMPLES = [
    "Tell me about your background and experience.",
    "What kinds of projects are you working on now?",
    "What are your strongest technical skills?",
    "How can I get in touch with you?",
]

CSS = """
:root {
  --twin-gold: #eab308;
  --twin-blue: #2563eb;
  --twin-purple: #7c3aed;
  --twin-bg: #0f1115;
  --twin-surface: #171a21;
  --twin-surface-2: #1d222b;
  --twin-border: #2b313c;
  --twin-border-strong: #3a4250;
  --twin-text: #f5f7fb;
  --twin-muted: #9aa4b2;
}

/* Light mode: Gradio adds `.dark` to <body> when dark; absence = light.
   Only the neutral palette flips — gold/blue/purple accents stay identical. */
body:not(.dark) {
  --twin-bg: #f6f7fb;
  --twin-surface: #ffffff;
  --twin-surface-2: #f4f6fa;
  --twin-border: #d9dee8;
  --twin-border-strong: #c2cad7;
  --twin-text: #10131a;
  --twin-muted: #5f6977;
}

footer, .built-with, .show-api, .api-docs { display: none !important; }

html, body, gradio-app {
  background: var(--twin-bg) !important;
}

*, *::before, *::after {
  box-sizing: border-box;
}

/* ---------- Stable layout ---------- */
.gradio-container {
  background: var(--twin-bg) !important;
  color: var(--twin-text) !important;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
  width: 100% !important;
  max-width: 920px !important;
  min-width: 0 !important;
  margin: 0 auto !important;
  padding: 40px 24px 56px !important;
}
.gradio-container .main,
.gradio-container .contain,
.gradio-container .wrap {
  width: 100% !important;
  max-width: 100% !important;
  min-width: 0 !important;
}
.gradio-container * { min-width: 0; }

/* ---------- Title ---------- */
.gradio-container h1 {
  color: var(--twin-text) !important;
  font-size: 2rem !important;
  line-height: 1.15 !important;
  font-weight: 650 !important;
  letter-spacing: -0.03em !important;
  margin: 0 0 18px !important;
  padding: 0 0 12px !important;
  border-bottom: 1px solid var(--twin-border) !important;
  text-align: left !important;
}

/* ---------- Sharp corners on structural pieces ---------- */
.chatbot,
.block,
.form {
  border-radius: 16px !important;
}

button,
input,
textarea,
.examples button,
.icon-button {
  border-radius: 10px !important;
}

/* ---------- Block surfaces ---------- */
.block,
.form {
  background: transparent !important;
  box-shadow: none !important;
}

/* ---------- Hide the Chatbot label / header strip ---------- */
.chatbot > .block-label,
.chatbot > label,
.chatbot .label-wrap,
.chatbot .block-label,
.chatbot > .label-container {
  display: none !important;
}

/* ---------- Chatbot frame ---------- */
.chatbot,
.chatbot.block {
  background: var(--twin-surface) !important;
  border: 1px solid var(--twin-border) !important;
  min-height: 480px !important;
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.18) !important;
  overflow: hidden !important;
}
.chatbot .placeholder, .chatbot .placeholder * { color: var(--twin-muted) !important; }

/* ---------- Message rows: strip parent backgrounds ---------- */
.message-row,
.message-row > div,
.message-row .role,
.message-wrap, .bubble-wrap {
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
}

/* ---------- Reset borders on every bubble variant first ---------- */
.message-row .message,
.message-row .message-bubble,
.message-row .bubble {
  border: 1px solid transparent !important;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04) !important;
  padding: 12px 16px !important;
  margin: 0 0 12px !important;
  border-radius: 12px !important;
}

/* ---------- Bubble backgrounds (broad to cover Gradio variants) ---------- */
.message-row.user-row .message,
.message-row.user-row .message-bubble,
.message-row.user-row .bubble,
.message-row[data-role="user"] .message,
.message-row[data-role="user"] .message-bubble {
  background: var(--twin-blue) !important;
  color: #ffffff !important;
}

.message-row.bot-row .message,
.message-row.bot-row .message-bubble,
.message-row.bot-row .bubble,
.message-row[data-role="assistant"] .message,
.message-row[data-role="assistant"] .message-bubble {
  background: var(--twin-surface-2) !important;
  color: var(--twin-text) !important;
}

/* ---------- Purple stripe ----------
   Apply to every common bubble class for assistant rows (we don't know which
   one the running Gradio uses), then suppress on any *nested* instance so the
   stripe lands on the outermost matching element only — exactly one stripe. */
.message-row.bot-row .message,
.message-row.bot-row .bubble,
.message-row.bot-row .message-bubble,
.message-row[data-role="assistant"] .message,
.message-row[data-role="assistant"] .bubble,
.message-row[data-role="assistant"] .message-bubble {
  border-left: 2px solid var(--twin-purple) !important;
}

.message-row.bot-row .message .message,
.message-row.bot-row .message .bubble,
.message-row.bot-row .message .message-bubble,
.message-row.bot-row .bubble .message,
.message-row.bot-row .bubble .bubble,
.message-row.bot-row .bubble .message-bubble,
.message-row.bot-row .message-bubble .message,
.message-row.bot-row .message-bubble .bubble,
.message-row.bot-row .message-bubble .message-bubble,
.message-row[data-role="assistant"] .message .message,
.message-row[data-role="assistant"] .message .bubble,
.message-row[data-role="assistant"] .message .message-bubble,
.message-row[data-role="assistant"] .bubble .message,
.message-row[data-role="assistant"] .bubble .bubble,
.message-row[data-role="assistant"] .bubble .message-bubble,
.message-row[data-role="assistant"] .message-bubble .message,
.message-row[data-role="assistant"] .message-bubble .bubble,
.message-row[data-role="assistant"] .message-bubble .message-bubble {
  border-left: 0 !important;
}

/* ---------- Uniform font size in bubbles ----------
   The "first paragraph different size" was caused by a leaky `.prose p:first-of-type`
   selector. Force every paragraph in a bubble to the same size. Lists (`<ul>/<li>`)
   rendered from markdown bullet points can otherwise inherit Gradio's larger default
   markdown size, so they are matched here too and normalized to match the paragraphs. */
.message-row .message,
.message-row .message-bubble,
.message-row .bubble {
  font-size: 12px !important;
  line-height: 1.55 !important;
}
.message-row .message p,
.message-row .message-bubble p,
.message-row .bubble p,
.message-row .prose p,
.message-row .message li,
.message-row .message-bubble li,
.message-row .bubble li,
.message-row .message ul,
.message-row .message-bubble ul,
.message-row .bubble ul,
.message-row .message ol,
.message-row .message-bubble ol,
.message-row .bubble ol {
  font-size: 14px !important;
  line-height: 1.55 !important;
  margin: 0 0 8px !important;
  color: inherit !important;
}
.message-row .message p:last-child,
.message-row .message-bubble p:last-child,
.message-row .bubble p:last-child,
.message-row .prose p:last-child,
.message-row .message li:last-child,
.message-row .message-bubble li:last-child,
.message-row .bubble li:last-child { margin-bottom: 0 !important; }

/* Keep default list indentation + marker alignment but tidy the spacing. */
.message-row .message ul,
.message-row .message-bubble ul,
.message-row .bubble ul,
.message-row .message ol,
.message-row .message-bubble ol,
.message-row .bubble ol {
  margin: 0 0 8px !important;
  padding-left: 1.4em !important;
}
.message-row .message li,
.message-row .message-bubble li,
.message-row .bubble li {
  margin-bottom: 4px !important;
}

/* Strip stray internal borders/backgrounds from anything inside a bubble */
.message-row .message *,
.message-row .message-bubble *,
.message-row .bubble * {
  background: transparent !important;
  border-color: transparent !important;
  box-shadow: none !important;
  color: inherit !important;
}
.message-row .message a,
.message-row .message-bubble a {
  color: var(--twin-gold) !important;
  text-decoration: underline;
}

/* ---------- Input row alignment ---------- */
.input-row,
.gr-input-row,
.chat-input-row,
form[class*="input"] { align-items: stretch !important; }

textarea,
input[type="text"] {
  background: var(--twin-surface) !important;
  border: 1px solid var(--twin-border) !important;
  color: var(--twin-text) !important;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
  font-size: 14px !important;
  padding: 14px 16px !important;
  line-height: 1.5 !important;
  min-height: 48px !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02) !important;
}
textarea:focus,
input[type="text"]:focus {
  border-color: var(--twin-blue) !important;
  outline: none !important;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.16) !important;
}
textarea::placeholder,
input::placeholder {
  color: var(--twin-muted) !important;
}

/* ---------- Buttons ---------- */
button {
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
  letter-spacing: 0.01em !important;
  text-transform: none !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  border: 1px solid var(--twin-border) !important;
  background: var(--twin-surface) !important;
  color: var(--twin-text) !important;
  padding: 0 18px !important;
  min-height: 44px !important;
  align-self: stretch !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  transition: background 0.16s ease, color 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}
button:hover {
  border-color: var(--twin-blue) !important;
  color: var(--twin-text) !important;
  background: var(--twin-surface-2) !important;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}
button:focus-visible {
  outline: 0 !important;
  box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.18) !important;
}

button.primary,
button[variant="primary"],
button.submit,
button.submit-button,
.submit-button,
button.lg.primary {
  background: linear-gradient(180deg, var(--twin-gold), #d99c0b) !important;
  border: 1px solid rgba(255, 255, 255, 0.06) !important;
  color: #111111 !important;
  min-height: 44px !important;
  align-self: stretch !important;
  padding: 0 18px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  box-shadow: 0 10px 20px rgba(234, 179, 8, 0.18) !important;
}
button.primary:hover,
button.submit:hover,
.submit-button:hover,
button.lg.primary:hover {
  background: linear-gradient(180deg, #f6c43a, #eab308) !important;
  border-color: rgba(255, 255, 255, 0.08) !important;
  color: #111111 !important;
  box-shadow: 0 14px 24px rgba(234, 179, 8, 0.24) !important;
  transform: translateY(-1px);
}

/* ---------- Submit-button icon: center vertically and size correctly ---------- */
button.submit svg,
button.submit-button svg,
.submit-button svg,
button.primary svg,
button[variant="primary"] svg {
  width: 18px !important;
  height: 18px !important;
  margin: 0 auto !important;
  display: block !important;
  align-self: center !important;
  color: #111111 !important;
  fill: currentColor !important;
  stroke: currentColor !important;
}

/* ---------- Examples ---------- */
.examples,
.examples-holder,
[data-testid="examples"] {
  background: transparent !important;
  padding: 0 !important;
  margin-top: 16px !important;
}
.examples table,
.examples-table {
  background: transparent !important;
  border: 0 !important;
}
.examples button,
.example,
.examples td button,
[data-testid="examples"] button {
  background: var(--twin-surface) !important;
  border: 1px solid var(--twin-border) !important;
  color: var(--twin-text) !important;
  text-transform: none !important;
  letter-spacing: 0 !important;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  padding: 11px 14px !important;
  text-align: left !important;
  min-height: 0 !important;
  align-self: auto !important;
  display: inline-flex !important;
  align-items: center !important;
  gap: 8px !important;
}
.examples button:hover,
.example:hover,
[data-testid="examples"] button:hover {
  border-color: var(--twin-blue) !important;
  color: var(--twin-text) !important;
  background: var(--twin-surface-2) !important;
}

/* ---------- Icon buttons (clear, retry, copy) ---------- */
.icon-button,
.chatbot .icon-button {
  color: var(--twin-muted) !important;
  background: transparent !important;
  border: 0 !important;
  min-height: 0 !important;
  align-self: auto !important;
  padding: 6px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
}
.icon-button:hover,
.chatbot .icon-button:hover {
  color: var(--twin-blue) !important;
}

/* ---------- Scrollbar ---------- */
::-webkit-scrollbar {
  width: 10px;
  height: 10px;
}
::-webkit-scrollbar-track {
  background: var(--twin-bg);
}
::-webkit-scrollbar-thumb {
  background: var(--twin-border-strong);
  border-radius: 999px;
  border: 2px solid var(--twin-bg);
}
::-webkit-scrollbar-thumb:hover {
  background: var(--twin-purple);
}

/* ---------- Selection ---------- */
::selection {
  background: rgba(234, 179, 8, 0.32);
  color: var(--twin-text);
}

/* ---------- Mobile ---------- */
@media (max-width: 640px) {
  .gradio-container {
    padding: 20px 12px 28px !important;
  }
  .gradio-container h1 {
    font-size: 1.6rem !important;
    margin-bottom: 14px !important;
  }
}
"""

JS = """
() => {
  document.title = 'Digital Twin';

  const focusInput = () => {
    const areas = document.querySelectorAll('textarea');
    if (areas.length) areas[areas.length - 1].focus();
  };
  setTimeout(focusInput, 300);

  // Re-focus the message field whenever Gradio re-enables it
  // (i.e. after the assistant finishes responding).
  const watchTextarea = (area) => {
    if (area.dataset.twinWatched) return;
    area.dataset.twinWatched = '1';
    let wasDisabled = area.disabled || area.readOnly;
    new MutationObserver(() => {
      const isDisabled = area.disabled || area.readOnly;
      if (wasDisabled && !isDisabled) area.focus();
      wasDisabled = isDisabled;
    }).observe(area, { attributes: true, attributeFilter: ['disabled', 'readonly'] });
  };

  const scan = () => document.querySelectorAll('textarea').forEach(watchTextarea);
  setTimeout(scan, 500);
  new MutationObserver(scan).observe(document.body, { childList: true, subtree: true });
}
"""
