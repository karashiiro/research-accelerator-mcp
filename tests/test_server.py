"""Unit tests for the Research Index MCP Server."""

import os

import pytest

# Set up in-memory database before importing server
os.environ["RESEARCH_DB_PATH"] = ":memory:"

from server import get_db, research_create, research_delete, research_search, reset_db


@pytest.fixture(autouse=True)
def fresh_db():
    """Ensure each test gets a fresh in-memory database."""
    # Reset any existing connection to start fresh
    reset_db()
    # Get the new connection (creates fresh in-memory DB)
    conn = get_db()
    yield conn
    # Clean up after test
    reset_db()


class TestCreate:
    """Tests for research_create tool."""

    def test_create_and_retrieve(self):
        """Create an entry, search for it, verify the description and resource match."""
        result = research_create(
            description="Vaswani 2017 - Attention Is All You Need. Transformer.",
            resource="https://arxiv.org/abs/1706.03762",
        )
        assert "Saved with ID" in result

        search_result = research_search("Attention Transformer")
        assert "Vaswani" in search_result
        assert "https://arxiv.org/abs/1706.03762" in search_result


class TestSearch:
    """Tests for research_search tool."""

    def test_search_returns_best_matches_first(self):
        """Create multiple entries with varying relevance to a query, verify ordering."""
        # Create entries with different relevance to "transformer"
        research_create(
            description="RNN based sequence model for translation",
            resource="rnn-paper",
        )
        research_create(
            description="Transformer transformer transformer - all about transformers",
            resource="transformer-paper",
        )
        research_create(
            description="BERT uses transformer architecture",
            resource="bert-paper",
        )

        result = research_search("transformer")
        lines = result.split("\n\n")

        # The entry with more "transformer" mentions should rank higher
        assert "transformer-paper" in lines[0]

    def test_search_no_results(self):
        """Search for something that doesn't exist, verify empty response."""
        result = research_search("nonexistent_query_xyz123")
        assert result == "No results found."

    def test_search_with_phrases(self):
        """Create entries, search with exact phrase, verify only phrase matches return."""
        research_create(
            description="deep learning for computer vision",
            resource="dl-cv",
        )
        research_create(
            description="learning about deep sea creatures",
            resource="sea-creatures",
        )

        # Exact phrase should only match the first
        result = research_search('"deep learning"')
        assert "dl-cv" in result
        assert "sea-creatures" not in result

    def test_search_with_or(self):
        """Search with foo OR bar, verify entries with either term return."""
        research_create(description="paper about cats", resource="cats-paper")
        research_create(description="paper about dogs", resource="dogs-paper")
        research_create(description="paper about birds", resource="birds-paper")

        result = research_search("cats OR dogs")
        assert "cats-paper" in result
        assert "dogs-paper" in result
        assert "birds-paper" not in result

    def test_search_with_not(self):
        """Search with foo NOT bar, verify exclusion works."""
        research_create(
            description="neural network for images",
            resource="nn-images",
        )
        research_create(
            description="neural network survey paper",
            resource="nn-survey",
        )

        result = research_search("neural NOT survey")
        assert "nn-images" in result
        assert "nn-survey" not in result

    def test_search_with_prefix(self):
        """Search with transform*, verify prefix matching works."""
        research_create(description="transformer model", resource="transformer")
        research_create(description="data transformation pipeline", resource="transformation")
        research_create(description="convolutional network", resource="convnet")

        result = research_search("transform*")
        assert "transformer" in result
        assert "transformation" in result
        assert "convnet" not in result

    def test_search_with_limit(self):
        """Verify limit parameter restricts results."""
        for i in range(5):
            research_create(description=f"test entry {i} with keyword", resource=f"resource-{i}")

        result = research_search("keyword", limit=2)
        # Count how many entries are in the result
        entry_count = result.count("->")
        assert entry_count == 2


class TestDelete:
    """Tests for research_delete tool."""

    def test_delete_existing(self):
        """Create an entry, delete it by ID, verify it's gone."""
        create_result = research_create(description="temporary entry", resource="temp")
        # Extract ID from "Saved with ID X"
        entry_id = int(create_result.split()[-1])

        delete_result = research_delete(entry_id)
        assert f"Deleted entry {entry_id}" in delete_result

        # Verify it's gone
        search_result = research_search("temporary")
        assert search_result == "No results found."

    def test_delete_nonexistent(self):
        """Delete an ID that doesn't exist, verify graceful 'not found' response."""
        result = research_delete(99999)
        assert "No entry found with ID 99999" in result


class TestErrorHandling:
    """Tests for edge cases and error handling."""

    def test_invalid_query_syntax(self):
        """Pass malformed query, verify error handling."""
        # FTS5 will raise an error for unbalanced quotes
        with pytest.raises(Exception):
            research_search('"unbalanced quote')
