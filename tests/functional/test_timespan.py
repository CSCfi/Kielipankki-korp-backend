
"""
test_timespan.py

Pytest tests for the Korp /timespan endpoint
"""


import pytest

from korp.utils import QUERY_DELIM

from tests.testutils import get_response_json


@pytest.fixture
def timespan_testcorpus(client, database):
    """Yield function returning JSON response for /timespan to testcorpus.

    The returned function takes as its parameters a corpus (or
    corpora), possible additional query parameters and Korp
    configuration parameters. It returns the JSON response for
    /timespan to the corpora with the given parameters (and
    cache=false).
    """

    def _timespan_testcorpus(corpus, params=None, config=None):
        query_params = {
            "corpus": corpus,
            "cache": "false",
        }
        # Import all timedata table data
        database.import_table_files(["timedata/*.tsv"])
        query_params.update(params or {})
        return get_response_json(
            client(config or {}), "/timespan", query_string=query_params)

    yield _timespan_testcorpus


class TestTimespan:

    """Tests for /timespan"""

    @pytest.mark.parametrize("granularity", ["y", "m", "d", "h", "n", "s"])
    def test_timespan_granularity(self, granularity, timespan_testcorpus):
        """Test /timespan with granularity on testcorpus3 and testcorpus4."""
        corpora = ["testcorpus3", "testcorpus4"]
        data = timespan_testcorpus(
            ",".join(corpora), {"granularity": granularity})
        assert "combined" in data and "corpora" in data
        for corpus in corpora:
            assert corpus.upper() in data["corpora"]
