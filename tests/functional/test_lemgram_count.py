
"""
test_lemgram_count.py

Pytest tests for the Korp /lemgram_count endpoint
"""


import pytest

from tests.testutils import get_response_json


@pytest.fixture
def lemgram_count_testcorpus(client, database):
    """Yield function returning JSON response for /lemgram_count to testcorpus.

    The returned function takes as its parameters a lemgram, possible
    additional request parameters and Korp configuration parameters.
    It returns the JSON response for /lemgram_count to corpus
    "testcorpus1" with the given parameters (and cache=false). It imports
    """

    def _lemgram_count_testcorpus(lemgram, params=None, config=None):
        query_params = {
            "corpus": "testcorpus1",
            "lemgram": lemgram,
            "cache": "false",
        }
        # Import all lemgram_index table data
        database.import_tables(["lemgram_index/*.tsv"])
        query_params.update(params or {})
        return get_response_json(
            client(config or {}), "/lemgram_count", query_string=query_params)

    yield _lemgram_count_testcorpus


class TestLemgramCount:

    """Tests for /lemgram_count"""

    def test_lemgram_count_single_corpus(self, lemgram_count_testcorpus):
        """Test /lemgram_count on a single corpus and single lemgram."""
        lemgram = "test..nn.1"
        data = lemgram_count_testcorpus(lemgram)
        assert lemgram in data
