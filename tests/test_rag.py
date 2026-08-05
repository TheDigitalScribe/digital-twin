"""Tests for the lightweight RAG module: chunking, index round-trip, and
retrieval. All tests use a fake embedder — no network, no API key, no cost.
"""

import asyncio
import json

import pytest
from openai import OpenAIError

from digitaltwin import rag
from digitaltwin.rag import (
    RETRIEVAL_UNAVAILABLE_MESSAGE,
    RAGEmbeddingError,
    build_index,
    chunk_markdown,
    get_achievements_context,
    load_index,
    query_index,
    retrieve_achievements,
    save_index,
)
from digitaltwin.tools import _TOOL_SCHEMAS, TOOL_MAP, _dispatch_tool

# ---------------------------------------------------------------------------
# Fake embedder: deterministic keyword-based vectors (no network).
# ---------------------------------------------------------------------------


def _fake_embed(texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for text in texts:
        low = text.lower()
        vectors.append(
            [
                1.0 if "acme" in low else 0.0,
                1.0 if "migration" in low else 0.0,
                1.0 if "kubernetes" in low else 0.0,
            ]
        )
    return vectors


async def fake_embed_async(texts: list[str]) -> list[list[float]]:
    return _fake_embed(texts)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


class TestChunkMarkdown:
    def test_splits_on_heading_level_two(self):
        md = (
            "# ACME Corp\n\n"
            "## Cost Cut\nReduced cloud spend by 30%.\n\n"
            "## Migration\nMoved to Kubernetes.\n"
        )
        chunks = chunk_markdown(md, max_chars=1000)
        assert len(chunks) == 3
        assert "ACME Corp" in chunks[0]
        assert chunks[1].startswith("## Cost Cut")
        assert "Reduced cloud spend by 30%." in chunks[1]
        assert chunks[2].startswith("## Migration")

    def test_long_body_split_approximate_cap(self):
        md = "## Long Section\n" + "\n".join(f"line {i} padding padding" for i in range(50))
        chunks = chunk_markdown(md, max_chars=200)
        # Multiple chunks because the body exceeds the cap; each sits roughly
        # at or under the cap (a single long line may exceed it slightly).
        assert len(chunks) > 1
        assert all(len(c) <= 200 + 50 for c in chunks)

    def test_empty_input_returns_no_chunks(self):
        assert chunk_markdown("", max_chars=1000) == []

    def test_no_headings_single_chunk(self):
        assert chunk_markdown("just some text", max_chars=1000) == ["just some text"]


# ---------------------------------------------------------------------------
# Index build / save / load
# ---------------------------------------------------------------------------


class TestIndexBuild:
    def test_build_index_extracts_and_embeds(self, tmp_path):
        (tmp_path / "one.md").write_text(
            "## ACME Cost Cut\nReduced cloud spend by 30%.\n", encoding="utf-8"
        )
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "two.md").write_text(
            "## Kubernetes Migration\nMoved 40 services.\n", encoding="utf-8"
        )

        entries = asyncio.run(
            build_index(
                fake_embed_async,
                str(tmp_path),
                chunk_chars=1000,
            )
        )
        assert len(entries) == 2
        assert all("text" in e and "embedding" in e for e in entries)
        assert all(len(e["embedding"]) == 3 for e in entries)
        assert any("ACME Cost Cut" in e["text"] for e in entries)
        assert any("Kubernetes Migration" in e["text"] for e in entries)

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="not found"):
            asyncio.run(
                build_index(
                    fake_embed_async,
                    str(tmp_path / "nope"),
                    chunk_chars=1000,
                )
            )

    def test_no_markdown_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="No markdown files"):
            asyncio.run(
                build_index(
                    fake_embed_async,
                    str(tmp_path),
                    chunk_chars=1000,
                )
            )

    def test_embedder_count_mismatch_raises(self, tmp_path):
        (tmp_path / "one.md").write_text("## X\nbody\n", encoding="utf-8")

        async def bad_embed(texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts] + [[0.0]]  # one too many

        with pytest.raises(RuntimeError, match="returned"):
            asyncio.run(
                build_index(bad_embed, str(tmp_path), chunk_chars=1000)
            )


class TestIndexPersistence:
    def test_round_trip(self, tmp_path):
        entries = [
            {"text": "hello", "embedding": [0.1, 0.2]},
            {"text": "world", "embedding": [0.3, 0.4]},
        ]
        target = tmp_path / "index.json"
        save_index(entries, str(target), "test-model")
        loaded = load_index(str(target))
        assert loaded == entries

    def test_save_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "index.json"
        save_index([], str(target), "test-model")
        assert target.is_file()

    def test_load_missing_returns_none(self, tmp_path):
        assert load_index(str(tmp_path / "missing.json")) is None

    def test_load_corrupt_returns_none(self, tmp_path):
        target = tmp_path / "bad.json"
        target.write_text("{not json", encoding="utf-8")
        assert load_index(str(target)) is None


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class TestQueryIndex:
    async def _make_index(self, tmp_path) -> str:
        entries = [
            {"text": "ACME cloud migration project", "embedding": [1.0, 1.0, 0.0]},
            {"text": "ACME cost reduction", "embedding": [1.0, 0.0, 0.0]},
            {"text": "kubernetes platform work", "embedding": [0.0, 0.0, 1.0]},
            {"text": "unrelated note", "embedding": [0.0, 0.0, 0.0]},
        ]
        target = tmp_path / "index.json"
        save_index(entries, str(target), "test-model")
        return str(target)

    # NOTE: the fake embedder maps keywords found in CHUNK TEXT, and the
    # question's embedding is the same function, so the question text itself
    # must contain the same keywords for the dot product to be non-zero.

    @pytest.mark.anyio
    async def test_returns_top_k_relevant_chunks(self, tmp_path):
        path = await self._make_index(tmp_path)
        result = await query_index(
            "ACME cloud migration project?",
            fake_embed_async,
            top_k=2,
            path=path,
        )
        assert result == [
            {"text": "ACME cloud migration project", "source": "unknown.md"},
            {"text": "ACME cost reduction", "source": "unknown.md"},
        ]

    @pytest.mark.anyio
    async def test_missing_index_returns_empty(self, tmp_path):
        result = await query_index(
            "anything",
            fake_embed_async,
            top_k=2,
            path=str(tmp_path / "missing.json"),
        )
        assert result == []

    @pytest.mark.anyio
    async def test_min_score_filters_low_relevance(self, tmp_path):
        path = await self._make_index(tmp_path)
        result = await query_index(
            "ACME anything?",
            fake_embed_async,
            top_k=4,
            path=path,
            min_score=0.5,
        )
        texts = [hit["text"] for hit in result]
        assert "kubernetes platform work" not in texts
        assert "unrelated note" not in texts
        assert len(result) == 2

    @pytest.mark.anyio
    async def test_source_attribution_preserved(self, tmp_path):
        entries = [
            {"text": "ACME cloud migration project", "embedding": [1.0, 1.0, 0.0], "source": "one.md"},
            {"text": "ACME cost reduction", "embedding": [1.0, 0.0, 0.0], "source": "two.md"},
        ]
        target = tmp_path / "index.json"
        save_index(entries, str(target), "test-model")
        result = await query_index(
            "ACME migration?",
            fake_embed_async,
            top_k=2,
            path=str(target),
        )
        assert {hit["source"] for hit in result} == {"one.md", "two.md"}

    @pytest.mark.anyio
    async def test_embed_failure_raises_rag_embedding_error(self, tmp_path):
        path = await self._make_index(tmp_path)

        async def failing_embed(texts: list[str]) -> list[list[float]]:
            raise OpenAIError("boom")

        with pytest.raises(RAGEmbeddingError):
            await query_index(
                "question", failing_embed, top_k=2, path=path
            )


# ---------------------------------------------------------------------------
# High-level retrieval (graceful degradation)
# ---------------------------------------------------------------------------


class TestRetrieveAchievements:
    @pytest.mark.anyio
    async def test_no_index_returns_guidance(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            rag, "_resolve_path", lambda raw: tmp_path / "missing.json"
        )
        result = await retrieve_achievements("what did you achieve?")
        assert "No achievements have been indexed" in result

    @pytest.mark.anyio
    async def test_no_match_returns_message(self, tmp_path, monkeypatch):
        # An empty index produces no retrieved chunks -> the friendly
        # "no match" message rather than an error.
        index = tmp_path / "index.json"
        save_index([], str(index), "test-model")
        monkeypatch.setattr(rag, "_resolve_path", lambda raw: index)
        monkeypatch.setattr(rag, "_embed_texts", fake_embed_async)
        result = await retrieve_achievements(
            "tell me about your interests in music"
        )
        assert "couldn't find achievement details" in result

    @pytest.mark.anyio
    async def test_match_returns_chunks(self, tmp_path, monkeypatch):
        index = tmp_path / "index.json"
        save_index(
            [
                {"text": "ACME migration", "embedding": [1.0, 1.0, 0.0]},
                {"text": "ACME cost cut", "embedding": [1.0, 0.0, 0.0]},
            ],
            str(index),
            "test-model",
        )
        monkeypatch.setattr(rag, "_resolve_path", lambda raw: index)
        monkeypatch.setattr(rag, "_embed_texts", fake_embed_async)
        result = await retrieve_achievements("ACME cloud migration?")
        assert "ACME migration" in result
        assert "ACME cost cut" in result

    @pytest.mark.anyio
    async def test_embed_failure_returns_unavailable_message(self, tmp_path, monkeypatch):
        index = tmp_path / "index.json"
        save_index(
            [{"text": "ACME migration", "embedding": [1.0, 1.0, 0.0]}],
            str(index),
            "test-model",
        )
        monkeypatch.setattr(rag, "_resolve_path", lambda raw: index)

        async def failing_embed(texts: list[str]) -> list[list[float]]:
            raise OpenAIError("boom")

        monkeypatch.setattr(rag, "_embed_texts", failing_embed)
        result = await retrieve_achievements("ACME migration?")
        assert result == RETRIEVAL_UNAVAILABLE_MESSAGE


# ---------------------------------------------------------------------------
# Eager context (chat-pipeline pre-fetch)
# ---------------------------------------------------------------------------


class TestAchievementsContext:
    """Eager context helper used by the chat pipeline before the model call."""

    @pytest.mark.anyio
    async def test_non_achievement_question_returns_none(self):
        # The heuristic gate returns None for non-achievement questions without
        # touching the embedding API or the index.
        assert await get_achievements_context("What languages do you know?") is None
        assert await get_achievements_context("What is your experience?") is None

    @pytest.mark.anyio
    async def test_achievement_question_without_index_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            rag, "_resolve_path", lambda raw: tmp_path / "missing.json"
        )
        result = await get_achievements_context("What achievements did you deliver?")
        assert result is None

    @pytest.mark.anyio
    async def test_achievement_question_returns_context_block(self, tmp_path, monkeypatch):
        index = tmp_path / "index.json"
        save_index(
            [
                {"text": "ACME migration", "embedding": [1.0, 1.0, 0.0], "source": "one.md"},
                {"text": "ACME cost cut", "embedding": [1.0, 0.0, 0.0], "source": "two.md"},
            ],
            str(index),
            "test-model",
        )
        monkeypatch.setattr(rag, "_resolve_path", lambda raw: index)
        monkeypatch.setattr(rag, "_embed_texts", fake_embed_async)
        result = await get_achievements_context("What impact did ACME migration deliver?")
        assert result is not None
        assert "ACME migration" in result
        assert "(Source: one.md)" in result
        assert "(Source: two.md)" in result

    @pytest.mark.anyio
    async def test_embed_failure_returns_none(self, tmp_path, monkeypatch):
        index = tmp_path / "index.json"
        save_index(
            [{"text": "ACME migration", "embedding": [1.0, 1.0, 0.0]}],
            str(index),
            "test-model",
        )
        monkeypatch.setattr(rag, "_resolve_path", lambda raw: index)

        async def failing_embed(texts: list[str]) -> list[list[float]]:
            raise OpenAIError("boom")

        monkeypatch.setattr(rag, "_embed_texts", failing_embed)
        result = await get_achievements_context("What did you achieve at ACME?")
        assert result is None


# ---------------------------------------------------------------------------
# Tool integration
# ---------------------------------------------------------------------------


class TestRetrieveAchievementsTool:
    def test_registered_in_map_and_schemas(self):
        assert "retrieve_achievements" in TOOL_MAP
        assert "retrieve_achievements" in _TOOL_SCHEMAS

    @pytest.mark.anyio
    async def test_dispatch_without_index_degrades(self, tmp_path, monkeypatch):
        # Point the RAG module at a non-existent index so the tool returns the
        # friendly guidance message with no network access.
        monkeypatch.setattr(
            rag, "_resolve_path", lambda raw: tmp_path / "missing.json"
        )
        result = await _dispatch_tool(
            "retrieve_achievements",
            json.dumps({"question": "what did you achieve at ACME?"}),
        )
        assert "No achievements have been indexed" in result

    @pytest.mark.anyio
    async def test_dispatch_rejects_missing_question(self):
        result = await _dispatch_tool("retrieve_achievements", "{}")
        assert "invalid arguments" in result.lower()