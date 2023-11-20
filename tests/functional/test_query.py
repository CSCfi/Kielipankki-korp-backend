
"""
test_query.py

Pytest tests for the Korp /query endpoint
"""


import pytest

from tests.testutils import get_response_json


@pytest.fixture
def query_testcorpus(client):
    """Yield function returning JSON response for /query to testcorpus.

    The returned function takes as its parameters the CQP query,
    possible additional query parameters and Korp configuration
    parameters. It returns the JSON response for /query to corpus
    "testcorpus" with the given parameters (and cache=false).
    """

    def _query_testcorpus(cqp, params=None, config=None):
        query = {
            "corpus": "testcorpus",
            "cqp": cqp,
            "cache": "false",
        }
        query.update(params or {})
        return get_response_json(
            client(config or {}), "/query", query_string=query)

    yield _query_testcorpus


class TestQuery:

    """Tests for /query"""

    def test_query_single_corpus(self, query_testcorpus):
        """Test a simple query on a single corpus."""
        data = query_testcorpus("[lemma=\"this\"]")
        kwic = data["kwic"]
        assert len(kwic) == data["hits"]
        # print(data)
        # assert 0
