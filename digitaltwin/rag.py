"""Lightweight RAG for the candidate's work achievements.

The full achievement dataset is never embedded in the system prompt (context
minimization). Instead, markdown achievement files are chunked, embedded with an
OpenAI-compatible embedding model, and persisted to a local JSON index
(``data/rag_index.json``). On a visitor question, the question is embedded and
the top-k semantically-similar chunks are returned as context for the model.

Storage is deliberately a single JSON file of ``{text, embedding}`` pairs
loaded into memory: for a personal dataset this is far simpler than a vector
database and costs nothing to run. If the dataset ever grows beyond ~50k
chunks, swap this storage layer for ChromaDB behind the same
``query_index`` / ``build_index`` interface.

Privacy: both the source markdown (``data/achievements/``) and the index
(``data/rag_index.json``) live under ``data/``, which is gitignored — the raw
achievements never reach the public repository.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from openai import OpenAIError

from .config import get_settings
from .logger import get_logger

logger = get_logger(__name__)

# Embedding functions: take a list of texts, return a same-length list of vectors.
EmbedFunc = Callable[[list[str]], Awaitable[list[list[float]]]]


class RAGEmbeddingError(RuntimeError):
    """Raised when embedding a query fails (API unreachable, auth, etc.).

    Lets callers distinguish an infrastructure failure (``RAGEmbeddingError``)
    from a genuine no-match (empty result list) so the user-facing message is
    accurate instead of a misleading "no achievements found".
    """


# ---------------------------------------------------------------------------
# Markdown chunking
# ---------------------------------------------------------------------------


def chunk_markdown(text: str, max_chars: int = 1000) -> list[str]:
    """Split markdown into chunks by ``##`` headings, bounded by ``max_chars``.

    A new chunk starts at every ``##`` heading. Chunks that would exceed
    ``max_chars`` are further split at line boundaries so a section with a
    long body is broken into readable pieces rather than one giant blob.
    """
    return [entry["text"] for entry in _chunk_markdown_entries(text, "unknown.md", max_chars)]


def _chunk_markdown_entries(
    text: str, source: str, max_chars: int
) -> list[dict[str, str]]:
    """Split markdown into ``{"text": ..., "source": ...}`` entries.

    Same chunking rules as :func:`chunk_markdown`, but each chunk is tagged
    with its source file name so retrieval results can be attributed.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        body = "\n".join(current).strip()
        if body:
            chunks.append(body)
        current = []
        current_len = 0

    for line in text.splitlines():
        line_len = len(line) + 1  # +1 for the newline
        if line.lstrip().startswith("## ") and current:
            flush()
        if current_len + line_len > max_chars and current:
            flush()
        current.append(line)
        current_len += line_len
    flush()
    return [{"text": chunk, "source": source} for chunk in chunks]


# ---------------------------------------------------------------------------
# Embedding (real client)
# ---------------------------------------------------------------------------


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using the configured OpenAI-compatible endpoint.

    Reads the API key / base URL / embedding model from the app settings, so
    deployments can point at Azure or a local OpenAI-compatible server just
    like the chat client does. Batches under the API per-request input cap.
    """
    from openai import AsyncOpenAI

    settings = get_settings()
    kwargs: dict[str, Any] = {}
    if settings.openai_api_key:
        kwargs["api_key"] = settings.openai_api_key.get_secret_value()
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    client = AsyncOpenAI(**kwargs)

    batch_size = 100
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = await client.embeddings.create(
            model=settings.rag_embedding_model,
            input=batch,
        )
        vectors.extend(item.embedding for item in response.data)
    return vectors


# ---------------------------------------------------------------------------
# Index build / save / load
# ---------------------------------------------------------------------------


def _resolve_path(raw: str) -> Path:
    """Resolve a possibly-relative path against the repository root."""
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


async def build_index(
    embed: EmbedFunc,
    achievements_dir: str,
    *,
    chunk_chars: int,
) -> list[dict[str, Any]]:
    """Read markdown achievement files, chunk, and embed them.

    Returns a list of ``{"text": ..., "embedding": [...]}`` entries suitable
    for ``save_index``. Raises RuntimeError if the directory is missing,
    contains no markdown, or the embedder returns a mismatched count.
    """
    directory = _resolve_path(achievements_dir)
    if not directory.is_dir():
        raise RuntimeError(f"Achievements directory not found: {directory}")

    files = sorted(directory.rglob("*.md"))
    if not files:
        raise RuntimeError(f"No markdown files found in {directory}")

    entries: list[dict[str, Any]] = []
    for path in files:
        entries.extend(
            _chunk_markdown_entries(
                path.read_text(encoding="utf-8"), path.name, chunk_chars
            )
        )
    if not entries:
        raise RuntimeError("No content chunks extracted from achievement files")

    chunks = [entry["text"] for entry in entries]
    embeddings = await embed(chunks)
    if len(embeddings) != len(chunks):
        raise RuntimeError(
            f"Embedder returned {len(embeddings)} vectors for {len(chunks)} chunks"
        )

    return [
        {"text": entry["text"], "source": entry["source"], "embedding": vector}
        for entry, vector in zip(entries, embeddings)
    ]


def save_index(entries: list[dict[str, Any]], path: str, model: str) -> None:
    """Persist the index as JSON: ``{"model": ..., "chunks": [...]}``."""
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"model": model, "chunks": entries}
    target.write_text(json.dumps(payload), encoding="utf-8")


def load_index(path: str) -> list[dict[str, Any]] | None:
    """Load the index file, or None if it is missing/corrupt."""
    target = _resolve_path(path)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        chunks = data.get("chunks")
        return chunks if isinstance(chunks, list) else None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Failed to load RAG index %s: %s", target, exc)
        return None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

# Messages returned by the tool when retrieval cannot be satisfied. Kept as
# module constants so tests and the eager context path can assert on them.
NO_INDEX_MESSAGE = (
    "No achievements have been indexed yet. Run `python -m digitaltwin.rag` "
    "to build the index from the markdown files in data/achievements/."
)
NO_MATCH_MESSAGE = "I couldn't find achievement details matching that question."
RETRIEVAL_UNAVAILABLE_MESSAGE = (
    "Achievement retrieval is temporarily unavailable. Please try again later."
)


async def query_index(
    question: str,
    embed: EmbedFunc,
    *,
    top_k: int,
    path: str,
    min_score: float = 0.0,
) -> list[dict[str, str]]:
    """Return the top-k relevant chunks as ``{"text": ..., "source": ...}`` dicts.

    Similarity is a dot product — OpenAI embedding vectors are normalized, so
    this equals cosine similarity. Only chunks scoring at least ``min_score``
    are returned. Returns ``[]`` when the index is missing/empty, nothing
    scores above the threshold, or the query embedding fails.
    """
    entries = load_index(path)
    if not entries:
        logger.info("rag_query_no_index", extra={"event": "rag_query", "question": question})
        return []

    try:
        [qvec] = await embed([question])
    except OpenAIError as exc:
        logger.error("Failed to embed RAG query: %s", exc)
        raise RAGEmbeddingError(str(exc)) from exc

    scored: list[dict[str, Any]] = []
    for entry in entries:
        score = sum(a * b for a, b in zip(qvec, entry.get("embedding", [])))
        scored.append(
            {
                "score": score,
                "text": entry["text"],
                "source": entry.get("source", "unknown.md"),
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)

    hits = [
        {"text": item["text"], "source": item["source"]}
        for item in scored
        if float(item["score"]) >= min_score
    ][:top_k]

    logger.info(
        "rag_query_result",
        extra={
            "event": "rag_query",
            "question": question,
            "index_chunks": len(entries),
            "top_score": round(float(scored[0]["score"]), 6) if scored else None,
            "hits": len(hits),
            "min_score": min_score,
        },
    )
    return hits


# ---------------------------------------------------------------------------
# High-level entry point used by the tool layer
# ---------------------------------------------------------------------------


def _format_hits(hits: list[dict[str, str]]) -> str:
    """Format retrieved chunks with their source file for readability."""
    return "\n\n---\n\n".join(
        f"(Source: {hit['source']})\n{hit['text']}" for hit in hits
    )


async def retrieve_achievements(question: str) -> str:
    """Return top-k achievement chunks relevant to ``question`` as plain text.

    Used by the ``retrieve_achievements`` tool. Degrades gracefully: a clear
    message when no index has been built yet, a "no match" message when nothing
    scores above ``RAG_MIN_SCORE``, and a distinct "temporarily unavailable"
    message when the embedding call fails so the model never mistakes an
    infrastructure problem for a genuine lack of data.
    """
    settings = get_settings()

    path = _resolve_path(settings.rag_index_path)
    if not path.is_file():
        logger.info("rag_missing_index", extra={"event": "rag_query", "index_path": str(path)})
        return NO_INDEX_MESSAGE

    try:
        hits = await query_index(
            question,
            _embed_texts,
            top_k=settings.rag_top_k,
            path=settings.rag_index_path,
            min_score=settings.rag_min_score,
        )
    except RAGEmbeddingError as exc:
        logger.error("RAG retrieval unavailable for question: %s", exc)
        return RETRIEVAL_UNAVAILABLE_MESSAGE
    if not hits:
        return NO_MATCH_MESSAGE
    return _format_hits(hits)


# ---------------------------------------------------------------------------
# Eager context: inject RAG context before the model call for achievement-like
# questions, so retrieval does not depend solely on the model choosing to call
# the tool. The tool remains as a runtime fallback for clarifying follow-ups.
# ---------------------------------------------------------------------------

# Words/phrases that strongly suggest a question is about work achievements
# (results, outcomes, metrics, impact) rather than general background.
_ACHIEVEMENT_HINT_WORDS = frozenset(
    {
        "achiev", "accomplish", "result", "outcome", "impact", "metric", "measure",
        "improve", "improved", "deliver", "delivered", "built", "build", "created",
        "launched", "shipped", "reduced", "increased", "saved", "record", "records",
        "win", "won", "milestone", "success", "successful", "highlight", "highlighted",
        "contribution", "contributions", "x12", "edi", "claims", "claim",
    }
)


def _looks_like_achievement_question(question: str) -> bool:
    """Heuristic gate: does this question sound like it targets achievements?

    Operates on the raw message text (before the LLM call) because the point
    is to avoid relying on model discretion. Deliberately broad — a false
    positive only wastes a cheap embedding call, while a false negative keeps
    the tool as the fallback.
    """
    text = (question or "").lower()
    return any(word in text for word in _ACHIEVEMENT_HINT_WORDS)


async def get_achievements_context(question: str) -> str | None:
    """Return eager RAG context for the chat pipeline, or ``None`` to skip.

    Returns ``None`` when the question does not look achievement-related (the
    tool remains available as a fallback), when no index has been built yet, or
    when the index exists but nothing scores above ``RAG_MIN_SCORE``. Returns a
    non-empty context block otherwise.

    This is deliberately best-effort: any failure short-circuits to ``None`` so
    the chat handler can still answer from background knowledge alone.
    """
    if not _looks_like_achievement_question(question):
        return None

    settings = get_settings()
    path = _resolve_path(settings.rag_index_path)
    if not path.is_file():
        logger.info(
            "rag_eager_skip_no_index",
            extra={"event": "rag_eager", "question": question},
        )
        return None

    try:
        hits = await query_index(
            question,
            _embed_texts,
            top_k=settings.rag_top_k,
            path=settings.rag_index_path,
            min_score=settings.rag_min_score,
        )
    except Exception:
        # Embedding errors surface as [] from query_index, but guard any
        # unexpected exception so retrieval can never break the chat turn.
        logger.exception("Unexpected RAG eager retrieval failure", extra={"event": "rag_eager"})
        return None

    if not hits:
        return None
    block = _format_hits(hits)
    logger.info(
        "rag_eager_hit",
        extra={
            "event": "rag_eager",
            "question": question,
            "hits": len(hits),
        },
    )
    return block


# ---------------------------------------------------------------------------
# CLI: build / refresh the index
# ---------------------------------------------------------------------------


async def _build_and_save() -> None:
    """Build the index from the configured achievements directory."""
    settings = get_settings()
    entries = await build_index(
        _embed_texts,
        settings.rag_achievements_dir,
        chunk_chars=settings.rag_chunk_chars,
    )
    save_index(entries, settings.rag_index_path, settings.rag_embedding_model)
    print(
        f"✅ Indexed {len(entries)} chunks from {settings.rag_achievements_dir} "
        f"→ {settings.rag_index_path}"
    )


def main() -> None:
    """CLI entry point: ``python -m digitaltwin.rag``.

    Exits with a readable error instead of a stack trace when the source
    directory is missing or contains no markdown files.
    """
    try:
        asyncio.run(_build_and_save())
    except RuntimeError as exc:
        print(f"❌ {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()