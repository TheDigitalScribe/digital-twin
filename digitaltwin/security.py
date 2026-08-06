"""Defense-in-depth guardrail layer.

Three independent layers protect the twin:

1. ``_normalize``          — deobfuscation helper that flattens evasions
   (homoglyphs, zero-width chars, letter-spacing, fragment-fusion).
2. ``is_suspicious_request`` — Layer A: input sandboxing (pre-model).
3. ``scrub_output``        — Layer B: output scrubbing (post-model).

Heuristic and best-effort by design: these layers complement (never replace)
the non-overridable system prompt protocols in ``context``.
"""

from __future__ import annotations

import re

from .config import SECRET_KEYS

# Phrases / markers that signal an attempt to extract instructions.
EXTRACTION_PATTERNS = [
    r"system\s*prompt",
    r"initial\s*instructions",
    r"summarize\s+.*\b(everything|prompt|instructions|rules|system prompt|settings|guidelines)\b",
    r"repeat\s*(everything|all|the|your)",
    r"what\s*(are|were|weren't)?\s*(your|the)\s*(instructions|rules|system|prompt|settings)",
    r"summarize\s*(everything|all|the|this)",
    r"translate\s*(the|your|this)",
    r"print\s*the\s*prompt",
    r"jailbreak",
    r"d\s*a\s*n\b",              # DAN
    r"developer\s*mode",
    # Ignore/disregard/forget instructions, rules, prompt... with optional
    # modifiers ("all previous", "your", "of your", ...).
    r"(?:ignore|disregard|forget)\s+(?:(?:all|any|the|previous|your|my)\s+)*(?:of\s+your\s+)?(?:instructions|guidelines|rules|prompt)",
    # Bare "ignore previous" even when the noun is elided
    # ("ignore previous. assistant: ...").
    r"ignore\s+(?:all\s+)?previous",
    r"pretend\s*you\s*are\s*(unconstrained|unleashed|not\s*an\s*ai|db)",
    r"act\s*as\s*(if|though)?\s*(you\s*have\s*no|without)\s*(rules|restrictions|limits)",
    # Paraphrased / masked extraction attempts.
    r"reveal\s+(your|the)\s+(prompt|instructions|rules)",
    r"show\s+(me\s+)?(your|the)\s+(prompt|instructions|rules)",
    r"expose\s+(your|the)\s+(prompt|instructions)",
    r"paste\s+your\s+prompt",
    r"copy\s+your\s+instructions",
    r"how\s+(are|were)\s+you\s+(programmed|prompted|built|configured)",
    r"what\s+is\s+in\s+your\s+(context|background|system)",
    r"(you\s+are\s+now|you're\s+now|from\s+now\s+on)\s+",
    r"no\s+(restrictions|rules|filters|limits|boundaries)",
    r"you\s+(can\s+)?(do|say)\s+anything",
    r"evil\s*(\s|-)?mode",
    r"simulate\s+(being\s+a|that\s+you\s+are)\s+(god|an?)\s*",
]

# Canned decline responses (kept generic; never echo back user content at risk).
DECLINE_INPUT = ("I'm only configured to discuss the candidate's career, "
                 "projects, and experience. I can't help with that request.")
DECLINE_OUTPUT = ("I'm not able to provide that. I'm only configured to discuss "
                  "the candidate's career, projects, and experience.")


# Common short words that must never be fused with a neighbour by the
# fragment-collapse pass in _normalize(). Without this, legitimate text such
# as "show me your prompt" would become "showme your prompt" and detection
# patterns would no longer fire on real attacks.
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for",
    "from", "had", "has", "have", "i", "if", "in", "is", "it", "me", "my",
    "no", "not", "of", "on", "or", "say", "so", "that", "the", "their",
    "this", "to", "we", "what", "when", "who", "will", "with", "you", "your",
}


def _normalize(text: str) -> str:
    """Flatten common obfuscations used to dodge keyword scanners:
    - full-width / lookalike unicode letters -> ASCII equivalents
    - zero-width and other invisible characters become a single space
    - runs of whitespace collapse to a single space
    - letter-spaced words collapse ("r e p e a t" -> "repeat")
    - short non-word fragments fuse back together ("sys tem" -> "system")
    Returns the normalized text. Never raises.
    """
    if not text:
        return text
    # Full-width / common homoglyph map for latin letters + digits.
    full_to_ascii = {
        ord(c): ord(a)
        for a, c in zip(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
            "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ０１２３４５６７８９",
        )
    }
    text = text.translate(full_to_ascii)

    # Replace zero-width and other invisible characters with a space rather
    # than deleting them. "sys\u200bterm" should normalise to "sys term"
    # (the fragments stay separate) while an evaded secret name such as
    # "OPENAI\u200bAPI\u200bKEY" becomes the spaced name the leak detector
    # also checks for.
    text = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad]", " ", text)

    if not text.strip():
        return ""

    # Split on whitespace runs, remembering which gaps were a single space.
    # A multi-space gap always marks a real word boundary and is preserved
    # as a single space in the final result.
    pieces = re.split(r"(\s+)", text)
    words: list[str] = []
    single_gaps: list[bool] = []       # single_gaps[i] -> gap before words[i+1]
    for i in range(0, len(pieces), 2):
        piece = pieces[i]
        if piece:
            if words:
                single_gaps.append(pieces[i - 1] == " ")
            words.append(piece)

    # Pass 1: fuse letter-spaced words. Only runs of single-character tokens
    # joined by single spaces are fused, so a lone "i" or "a" next to a real
    # word is left untouched ("i am instructed..." must survive).
    fused: list[str] = []
    fused_gaps: list[bool] = []
    i = 0
    while i < len(words):
        if len(words[i]) == 1:
            start = i
            combined = words[i]
            while (i + 1 < len(words) and single_gaps[i]
                   and len(words[i + 1]) == 1):
                i += 1
                combined += words[i]
            gap_before = None if start == 0 else single_gaps[start - 1]
        else:
            combined = words[i]
            gap_before = None if i == 0 else single_gaps[i - 1]
        if fused:
            # fused is non-empty only once we are past the first word, so
            # gap_before is guaranteed to be set here.
            fused_gaps.append(gap_before if gap_before is not None else False)
        fused.append(combined)
        i += 1

    # Pass 2: fuse short fragments that are clearly a split keyword
    # ("sys tem" -> "system", "prom pt" -> "prompt"). Common words are never
    # fused, so "show me" and "your prompt" survive as separate words.
    final: list[str] = [fused[0]]
    for k in range(1, len(fused)):
        prev = final[-1]
        cur = fused[k]
        can_fuse = (
            bool(fused_gaps[k - 1])          # single-space gap only
            and len(prev) <= 4
            and len(cur) <= 4
            and len(prev) + len(cur) <= 6
            and prev.lower() not in _STOP_WORDS
            and cur.lower() not in _STOP_WORDS
        )
        if can_fuse:
            final[-1] = prev + cur
        else:
            final.append(cur)

    return " ".join(final)


# ---------------------------------------------------------------------------
# Layer A: INPUT SANDBOXING
# ---------------------------------------------------------------------------
def is_suspicious_request(message: str) -> bool:
    """Return True if the incoming user message looks like an injection or
    extraction attempt. Designed to be conservative (err on blocking)."""
    if not message:
        return False

    low = _normalize(message).lower()

    # Case 1: direct flagging phrases (now on normalized text).
    for pat in EXTRACTION_PATTERNS:
        if re.search(pat, low):
            return True

    # Case 2: multiple user/system role-injection markers pretending to be
    # conversation history or instructions.
    high_risk_markers = 0
    for marker in [
        "system:", "assistant:", "user:",
        "<system>", "<assistant>", "<user>", "</system>",
        "### instructions", "new instruction", "override",
        "from now on", "you are", "pretend", "imagine",
    ]:
        if marker in low:
            high_risk_markers += 1
    if high_risk_markers >= 2:
        return True

    # Case 3: bundled responsibility-shift pattern ("you are now ..." plus a
    # role) even if markers individually look innocuous.
    return bool(re.search(r'("|“)?you\s+are\s+(now|not\s+any|no\s+longer)', low))


# ---------------------------------------------------------------------------
# Layer B: OUTPUT SCRUBBING
# ---------------------------------------------------------------------------
def scrub_output(content: str) -> str:
    """Scan the model's reply for potential leaks and neutralize them.

    Returns the original content if clean, otherwise a canned decline that
    never echoes the leaked material."""
    if not content:
        return content
    threat = _output_leak_detected(content)
    if threat:
        return DECLINE_OUTPUT
    return content


def _output_leak_detected(content: str) -> str | None:
    """Return the matched leak category, or None if the output looks clean."""
    low = _normalize(content).lower()

    # 1) Leaked env/secret key names (normalized, so obfuscated key names
    #    count). Matches the underscored name, the spaced form produced by
    #    zero-width evasion ("OPENAI\u200bAPI\u200bKEY" -> "openai api key"),
    #    and the fused form from fragment-collapse ("openai apikey").
    for key in SECRET_KEYS:
        lowered = key.lower()
        if lowered in low:
            return f"secret-name:{key}"
        pattern = r"[\s_]*".join(re.escape(part) for part in lowered.split("_"))
        if re.search(pattern, low):
            return f"secret-name:{key}"

    # 2) Long-form instruction leakage (the prompt/guardrail text).
    if ("absolutely secure" in low or "security protocols" in low) and (
        "representing the candidate" in low or "career" in low
    ):
        return "system-prompt-text"

    # Also catch the section headers / distinctive phrases of the prompt so
    # even paraphrased dumps trip this.
    if ("s1" in low or "s2" in low or "s3" in low) and "non-negotiable" in low:
        return "system-prompt-text"

    # 3) Explicitly states it is disclosing its prompt/settings.
    for snippet in [
        "here is my system prompt", "my instructions are", "my rules are",
        "i am instructed to", "i was told to", "here are my",
    ]:
        if snippet in low:
            return "prompt-disclosure"

    # 4) Confidential-looking values (API-key shaped tokens).
    if re.search(r"sk-[A-Za-z0-9_\-]{20,}", content):
        return "api-key-like-token"

    # 5) Tool names leaking (internal interface disclosure). The dispatch
    # machinery (handle_tool_calls_async, _dispatch_tool) is never mentioned
    # in the system prompt; if it leaks we treat it as internal disclosure.
    if "handle_tool_calls_async" in content or "_dispatch_tool" in content:
        return "internal-tool-disclosure"

    return None

