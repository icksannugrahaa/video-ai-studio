"""Text helpers: sentence splitting for TTS and subtitle cue chunking."""

from __future__ import annotations

import re

_SENTENCE_RE = re.compile(r"(?<=[.!?。！？…])\s+|\n+")


def split_sentences(text: str, max_chars: int = 220) -> list[str]:
    """Split narration into sentences; very long sentences are cut at commas
    or spaces so each TTS request stays short (better timing granularity)."""
    out: list[str] = []
    for sentence in (s.strip() for s in _SENTENCE_RE.split(text or "")):
        if not sentence:
            continue
        while len(sentence) > max_chars:
            cut = max(sentence.rfind(", ", 0, max_chars), sentence.rfind(" ", 0, max_chars))
            cut = cut + 1 if cut > max_chars // 3 else max_chars
            out.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            out.append(sentence)
    return out


def chunk_cue(text: str, start: float, end: float, max_words: int) -> list[tuple[float, float, str]]:
    """Split one timed sentence into cues of at most ``max_words`` words, with
    time distributed proportionally to character count."""
    words = text.split()
    if not words:
        return []
    if len(words) <= max_words:
        return [(start, end, text.strip())]
    groups = [" ".join(words[i:i + max_words]) for i in range(0, len(words), max_words)]
    total_chars = sum(len(g) for g in groups) or 1
    span = max(0.0, end - start)
    cues, cursor = [], start
    for i, group in enumerate(groups):
        length = span * len(group) / total_chars
        cue_end = end if i == len(groups) - 1 else cursor + length
        cues.append((round(cursor, 3), round(cue_end, 3), group))
        cursor = cue_end
    return cues


def wrap_lines(text: str, width: int) -> str:
    """Greedy wrap into at most two lines (subtitle readability)."""
    words, lines, line = text.split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if len(candidate) > width and line:
            lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    if len(lines) > 2:
        lines = [lines[0], " ".join(lines[1:])]
    return "\n".join(lines)
