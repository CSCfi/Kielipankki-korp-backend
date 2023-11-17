
"""
conftest.py

Pytest fixtures for testing the Korp backend as a Flask app.
"""


import pytest

from pathlib import Path
from shutil import copytree

from korp import create_app
from tests.corpusutils import CWBEncoder


# Functions in tests.utils are called by tests and contain assertions
# that should be rewritten
pytest.register_assert_rewrite("tests.testutils")


# Test data (source) directory
_datadir = Path(__file__).parent / "data"


@pytest.fixture(scope="session")
def corpus_data_root(tmp_path_factory):
    """Return a corpus data root directory for a session."""
    return tmp_path_factory.mktemp("corpora")


@pytest.fixture(scope="session")
def corpus_registry_dir(corpus_data_root):
    """Return a corpus registry directory for a session."""
    return str(corpus_data_root / "registry")


@pytest.fixture()
def cache_dir(tmp_path_factory):
    """Return a cache directory."""
    # Should this fixture have a non-default scope?
    return tmp_path_factory.mktemp("cache")


@pytest.fixture()
def corpus_config_dir(tmp_path_factory):
    """Return a corpus configuration directory."""
    # Should this fixture have a non-default scope (session?)?
    return tmp_path_factory.mktemp("corpus-config")


@pytest.fixture()
def app(corpus_registry_dir, cache_dir, corpus_config_dir):
    """Return a function for creating and configuring a Korp app instance.

    Uses the "factory as fixture" pattern:
    https://docs.pytest.org/en/7.3.x/how-to/fixtures.html#factories-as-fixtures
    """

    def _app(config=None):
        """Return Korp app instance with config overriding defaults."""
        base_config = {
            # https://flask.palletsprojects.com/en/2.2.x/config/#TESTING
            "TESTING": True,
            "CWB_REGISTRY": corpus_registry_dir,
            "CACHE_DIR": cache_dir,
            "CORPUS_CONFIG_DIR": corpus_config_dir,
        }
        base_config.update(config or {})
        return create_app(base_config)
        # print(app.config)

    yield _app


@pytest.fixture()
def client(app):
    """Return a function for creating and returning a test client."""

    def _client(config=None):
        """Return test client for app with config overriding defaults."""
        return app(config).test_client()

    return _client


@pytest.fixture(scope="session")
def corpora(corpus_data_root):
    """Encode corpora in data/corpora/src and return their corpus ids."""
    corpus_source_dir = _datadir / "corpora" / "src"
    cwb_encoder = CWBEncoder(str(corpus_data_root))
    return cwb_encoder.encode_corpora(str(corpus_source_dir))


@pytest.fixture()
def corpus_configs(corpus_config_dir):
    """Copy corpus configs from data/corpora/config to corpus_config_dir."""
    config_src_dir = _datadir / "corpora" / "config"
    # KLUDGE: Remove corpus_config_dir created in the fixture so
    # named, as shutil.copytree expects the destination not to exists.
    # For Python 3.8+, the argument dirs_exist_ok=True could be
    # specified, but this also supports older Pythons.
    corpus_config_dir.rmdir()
    copytree(str(config_src_dir), str(corpus_config_dir))
