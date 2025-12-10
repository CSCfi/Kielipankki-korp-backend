
"""
test_cwb.py

Unit tests for functions in module korp.cwb.
"""


import pytest

from korp.cwb import cwb
from korp import utils

from tests.testutils import get_info_value


@pytest.fixture()
def cwb_object(corpus_registry_dir, korp_config, scope="session"):
    """Return korp.cwb.cwb object with registry dir set as appropriate."""
    cwb.init(
        executable=korp_config["CQP_EXECUTABLE"],
        scan_executable=korp_config["CWB_SCAN_EXECUTABLE"],
        registry=corpus_registry_dir,
        locale=korp_config["LC_COLLATE"],
        encoding=korp_config["CQP_ENCODING"]
    )
    return cwb


@pytest.fixture()
def run_cqp(cwb_object, corpora):
    """Return a function for getting the result of CQP commands."""

    def _run_cqp(command, corpus=None, **kwargs):
        """Run CQP command using cwb_object.run_cqp and return result as list.

        command can be a single string or a list of strings. command
        is prepended with selecting corpus; if corpus is None, select
        the first corpus listed by corpora. The returned value is a
        list of lines (strings).
        """
        if isinstance(command, str):
            command = [command]
        if corpus is None:
            corpus = corpora[0]
        command = [corpus.upper() + ";"] + command
        return list(cwb_object.run_cqp(command, **kwargs))

    yield _run_cqp


class TestRunCqp:

    """Tests for function korp.cwb.CWB.run_cqp."""

    def test_run_cqp_simple(self, run_cqp):
        """Test run_cqp with info and a simple CQP query."""
        result = run_cqp(
            ["info;", "cat \"-----\\n\";", "<sentence> [];", "cat Last;"])
        assert result[0].startswith("CQP version")
        size = int(get_info_value("Sentences", result))
        assert size
        query_result_size = len(result) - result.index("-----") - 1
        assert query_result_size == size

    def test_run_cqp_no_attr_ignore(self, run_cqp):
        """Test run_cqp for showing non-existent attribute."""
        with pytest.raises(utils.CQPError, match="No such attribute"):
            run_cqp("show +_zzz;")

    def test_run_cqp_attr_ignore(self, run_cqp):
        """Test run_cqp for showing non-existent attribute, with attr_ignore."""
        result = run_cqp("show +_zzz;", attr_ignore=True)
        assert len(result) == 1

    def test_run_cqp_errors_strict(self, run_cqp):
        """Test run_cqp with a command causing a syntax error."""
        with pytest.raises(utils.CQPError, match="CQP Syntax Error:"):
            run_cqp("---;")

    def test_run_cqp_errors_ignore(self, run_cqp):
        """Test run_cqp with command causing syntax error, errors="ignore"."""
        result = run_cqp("---;", errors="ignore")
        assert len(result) == 1

    def test_run_cqp_errors_report(self, run_cqp):
        """Test run_cqp with command causing syntax error, errors="report"."""
        result = run_cqp("---;", errors="report")
        assert result[0].startswith("CQP Error: CQP Syntax Error:")
        assert result[1].startswith("CQP version")

    def test_run_cqp_errors_report_multi(self, run_cqp):
        """Test run_cqp with two commands causing errors, errors="report"."""
        result = run_cqp(
            ["---;", "<sentence> [];", "[_zzz=\"a\"];", "cat Last;"],
            errors="report")
        # Note that the errors are at the beginning of the result,
        # even when a succeeding command is between the commands
        # causing errors
        assert result[0].startswith("CQP Error: CQP Syntax Error:")
        assert (result[1].startswith("CQP Error:") and "_zzz" in result[1]
                and "neither a positional/structural attribute" in result[1])
        assert result[2].startswith("CQP version")
