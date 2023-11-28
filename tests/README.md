
# Tests for the Korp backend

This directory `tests` contains [Pytest](https://pytest.org) tests for
the Korp backend.


## Prerequisites

To be able to run tests, you need to install the development
requirements by running
```
$ pip3 install -r requirements-dev.txt
```

In addition, you need to have the Corpus Workbench (CWB), in
particular `cwb-encode`, and the CWB Perl tools (for `cwb-make`),
installed and on `PATH` (see the [main README
file](../README.md#corpus-workbench)). The CWB Perl tools can be
installed from the CWB Subversion repository at
http://svn.code.sf.net/p/cwb/code/perl/trunk

For database tests, you also need to have a MySQL/MariaDB server with
a user with the privileges to create a database and grant access to
it.


## Running tests

To run tests, run
```
$ pytest
```


### Database access

To run successfully tests that require Korp MySQL database data, you
may need to specify custom command-line options to `pytest`:

- `--db-host=`_HOST_: Use host _HOST_ for the Korp MySQL test database
- `--db-port=`_PORT_: Use port _PORT_ for the Korp MySQL test database
- `--db-name=`_NAME_: Use database name _NAME_ for the Korp MySQL test
  database
- `--db-user=`_USER_: Use user _USER_ to access the Korp MySQL test
  database
- `--db-password=`_PASSWORD_: Use password _PASSWORD_ to access the
  Korp MySQL test database
- `--db-create-user=`_USER_: Use user _USER_ to create the Korp MySQL
  test database
- `--db-create-password=`_PASSWORD_: Use password _PASSWORD_ to create
  the Korp MySQL test database

If these are not specified explicitly, tests try to use the values
specified in the Korp configuration for `DBHOST`, `DBPORT`, `DBUSER`
and `DBPASSWORD`. That fails unless the user specified there has the
privilege to create a database or you specify with `--db-name` the
name of an existing database in which the user has the table creation
privilege.

The database user should also have the file privilege to load data
from files.

If the test database cannot be created, tests using the database
(fixture `database`) are skipped.


### Test coverage

To find out test coverage using
[Coverage.py](https://coverage.readthedocs.io/), run
```
$ coverage -m pytest
```
and then, for example,
```
$ coverage report
```


## Directory Layout

This directory `tests/` contains:

- [`unit/`](unit): unit tests, typically testing functions in modules
  directly under the `korp` package
- [`functional/`](functional): functional tests, typically testing the endpoints
  (`korp.views.*`)
- `data/`: test data
  - [`data/corpora/src`](data/corpora/src): corpus source data
  - [`data/corpora/config`](data/corpora/config): corpus configuration
    data
  - [`data/db`](data/db): Korp MySQL database data
  - [`data/db/tableinfo`](data/db/tableinfo): YAML files with
    information for creating Korp MySQL database tables
- [`conftest.py`](conftest.py): Pytest configuration; in particular,
  fixtures to be used by individual tests
- [`configutils.py`](configutils.py): utility functions for processing
  the Korp configuration
- [`corpusutils.py`](corpusutils.py): utility functions for setting up
  CWB corpus data
- [`dbutils.py`](dbutils.py): `KorpDatabase` class for setting up and
  using Korp MySQL test database
- [`testutils.py`](testutils.py): utility functions for tests, typically
  functionality that recur in multiple tests but that cannot be made fixtures


## Adding tests

Individual test files and tests should follow Pytest conventions: the
names of files containing tests should begin with `test_`, as should
also the names of test functions and methods. Tests can be grouped in
classes whose names begin with `Test`.


### Fixtures

The following Pytest fixtures have been defined in
[`conftest.py`](conftest.py):

- `corpus_data_root`: Return CWB corpus root directory for a session
- `corpus_registry_dir`: Return CWB corpus registry directory for a session
- `cache_dir`: Return Korp cache directory
- `corpus_config_dir`: Return corpus configuration directory
- `corpus_configs`: Copy corpus configurations in
  `data/corpora/config` to a temporary directory used in tests
- `corpora`: Encode the corpora in `data/corpora/src` and return their ids
- `database`: Return a `KorpDatabase` object for a session
- `app`: Return a function to create and configure a Korp Flask app
  instance. The returned function optionally takes as its argument a
  `dict` for overriding default Korp configuration values.
- `client`: Return a function to create and return a test client. The
  returned function optionally takes as its argument a `dict` for
  overriding default Korp configuration values.


### Functional tests

A typical functional test testing an endpoint uses the `client` and
`corpora` fixtures. For example:

```python
def test_corpus_info_single_corpus(self, client, corpora):
    corpus = corpora[0].upper()
    response = client().get(
        "/corpus_info",
        query_string={
            "cache": "false",
            "corpus": corpus,
        })
    assert response.status_code == 200
    assert response.is_json == True
    data = response.get_json()
    corpus_data = data["corpora"][corpus]
    attrs = corpus_data["attrs"]
    assert attrs
```

If the endpoint uses the Korp MySQL database, it should also use the
`database` fixture and load the appropriate database table data with
`database.import_tables()`. For example:

```python
def test_lemgram_count_single_corpus(self, client, database):
    """Test /lemgram_count on a single corpus."""
    database.import_tables(["lemgram_index/*.tsv"])
    lemgram = "test..nn.1"
    response = client().get(
        "/lemgram_index",
        query_string={
            "corpus": "testcorpus1",
            "lemgram": lemgram,
            "cache": "false",
        })
    data = response.get_json()
    assert lemgram in data
```


### Corpus data

Each CWB corpus _corpus_ whose data is used in the tests should have a
source VRT file _corpus_`.vrt` in `data/corpora/src`. The corpus
source files use a slightly extended VRT (VeRticalized Text) format
(the input format for CWB), where structures are marked with XML-style
tags (with attributes) and each token is on its own line, token
attributes separated by tags.

The extension is that the positional and structural attributes need to
be declared at the top of the file as XML comments as follows:
```
<!-- #vrt positional-attributes: attr1 attr2 ... -->
<!-- #vrt structural-attributes: text:0+a1+a2 sentence:0+a3+a4 ... -->
```
For example:
```
<!-- #vrt positional-attributes: word lemma -->
<!-- #vrt structural-attributes: text:0+id paragraph:0+id sentence:0+id -->
<text id="t1">
<paragraph id="p1">
<sentence id="s1">
</sentence>
This	this
is	be
a	a
test	test
.	.
<sentence id="s2">
Great	great
!	!
</sentence>
</paragraph>
</text>
```

In addition to the VRT file _corpus_`.vrt`, a corpus should have a
corresponding info file _corpus_`.info` containing at least the number
of sentences and date of update in the ISO format as follows:
```
Sentences: 2
Updated: 2023-01-20
```

Note that the encoded test corpus data is placed under a temporary
directory for the duration of a test session, so test corpora are
isolated from any other CWB corpora in the system.


### Corpus configuration data

Corpus configuration data used in tests for the `/corpus_config`
endpoint is under `data/corpora/config` in the format expected by
Korp; please see [the
documentation](../README.md#corpus-configuration-for-the-korp-frontend)
for more information.


### Database data

Test database data resides in TSV (tab-separated values) files under
the subdirectory `data/db/` and its subdirectories. The files should
not have a header row. Backslash escapes are not recognized, so values
cannot contain tab or newline characters.

YAML files in [`data/db/tableinfo/`](data/db/tableinfo) contain table
information specifying a mapping from data files to database tables.
Each file contains a sequence of one or more mappings with the
following keys recognized:

- `tablename`: The name of the table. The name may contain format
  specifications referring to capturing groups in the regular
  expressions in `filenames`: `{1}` is expanded to the value of the
  first group, `{2}` to that of the second one and so on. In addition,
  a format specification may contain a case-converting type: `{1:u}`
  is the value of the first group uppercased, `{1:l}` lowercased and
  `{1:t}` title-cased.
- `filenames`: A sequence of file name regular expressions. If a full
  file name matches one of the expressions and none of those in
  `exclude_filenames`, load the data from it to the table specified in
  `tablename`.
- `exclude_filenames`: A sequence of excluded file name regular expressions.
- `definition`: A string containing the MySQL table definition:
  columns and possible keys.

If a file name would match regular expression in multiple mappings,
the first mapping found is used. Regular expressions are matched to
absolute file names in their entirety, including the directory. If the
regular expressions in `filenames` and `exclude_filenames` do not
begin with `.*/` and end with `\.tsv`, these are affixed to the
expressions.

The value of `definition` may contain variable references as
`{`_var_`}`. Their values must be defined before use in a separate
sequence item with key `definition_vars` and value that is a mapping
from variable names to values:

```yaml
- definition_vars:
    var1: value1
    var2: value2
```

Currently, the table information files support the following file
names for the various tables, shown here relative to `tests/data/db/`
and using shell globs instead of regular expressions:

- Table `lemgram_index`:
  - `lemgram_index/*.tsv`
  - `*/lemgram_index*.tsv`
- Table `timedata`:
  - `timedata/*.tsv`
  - `*/timedata*.tsv`
  - _Not_ `*/*_date.tsv`
- Table `timedata_date`:
  - `timedata/*_date.tsv`
  - `*/timedata*_date.tsv`
- Table `relations_CORPUS` (for corpus `corpus`):
  - `relations/corpus.tsv`
  - `relations/corpus[:+]relations.tsv`
  - `corpus/relations.tsv`
  - _Not_ `*/*_strings.tsv`, `*/*_rel.tsv`, `*/*_head_rel.tsv`,
    `*/*_dep_rel.tsv`, `*/*_sentences.tsv`
- Table `relations_CORPUS_strings`:
  - `relations/corpus_strings.tsv`
  - `relations/corpus[:+]relations_strings.tsv`
  - `corpus/relations_strings.tsv`
- Table `relations_CORPUS_rel`:
  - `relations/corpus_rel.tsv`
  - `relations/corpus[:+]relations_rel.tsv`
  - `corpus/relations_rel.tsv`
  - _Not_ `*/*_head_rel.tsv`, `*/*_dep_rel.tsv`
- Table `relations_CORPUS_head_rel`:
  - `relations/corpus_head_rel.tsv`
  - `relations/corpus[:+]relations_head_rel.tsv`
  - `corpus/relations_head_rel.tsv`
- Table `relations_CORPUS_dep_rel`:
  - `relations/corpus_dep_rel.tsv`
  - `relations/corpus[:+]relations_dep_rel.tsv`
  - `corpus/relations_dep_rel.tsv`
- Table `relations_CORPUS_sentences`:
  - `relations/corpus_sentences.tsv`
  - `relations/corpus[:+]relations_sentences.tsv`
  - `corpus/relations_sentences.tsv`
