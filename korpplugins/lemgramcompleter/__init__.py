
"""
korpplugins.lemgramcompleter

A Korp plugin implementing /lemgram_complete endpoint, to find lemgram
completions for a prefix.
"""


# TODO:
# - Add docstrings and expand existing ones.
# - Add parameters affecting the result.


from pymemcache.exceptions import MemcacheError

from korp import db, memcached, pluginlib, utils
from flask import current_app as app


pluginconf = pluginlib.get_plugin_config(
    # The name of the lemgram index table in the MySQL database
    LEMGRAM_DBTABLE = "lemgram_index",
)


plugin = pluginlib.EndpointPlugin()


@plugin.route("/lemgram_complete")
@utils.main_handler
@utils.prevent_timeout
def lemgram_complete(args):
    """Find lemgrams beginning with the specified prefix.

    Find lemgram completions beginning with the specified prefix, based
    on the database table lemgram_index. If corpus ids are specified,
    prefer lemgrams from those corpora and fill in from the rest. The
    result is sorted descending by the frequency of the lemgram.

    Arguments:
    - wf: lemgram prefix
    - corpus (optional): list of corpus ids from which to get the
      lemgrams in the first place
    - limit (default: 10): the number of lemgrams to return
    - format (optional): if "old", use an old, Karp-like format, instead
      of the simpler default
    """
    utils.assert_key("wf", args, r"", True)
    utils.assert_key("corpus", args, utils.IS_IDENT)
    utils.assert_key("limit", args, utils.IS_NUMBER)
    utils.assert_key("format", args, r"old")
    wf = args.get("wf")
    corpora = utils.parse_corpora(args)
    limit = int(args.get("limit", 10))
    fmt = args.get("format")

    # Check if the result is cached
    # TODO: Add a helper function in korp.py abstracting the relevant
    # parts of the cache handling code
    if args["cache"]:
        checksum = utils.get_hash((wf, sorted(corpora), limit, fmt))
        with memcached.get_client() as mc:
            # Would it be better to use just "multi" in the cache key
            # instead of all the corpus ids?
            cache_key = (
                "%s:lemgramcomplete_%s" %
                (",".join(utils.cache_prefix(mc, corpora).values()),
                 checksum))
            print(cache_key)
            result = mc.get(cache_key)
            if result:
                if "debug" in args:
                    result.setdefault("DEBUG", {})
                    result["DEBUG"]["cache_read"] = True
                    result["DEBUG"]["checksum"] = checksum
                yield result
                return

    result = _get_lemgrams(wf, corpora, limit)
    if fmt == "old":
        result = _encode_lemgram_result(result)
        hits_name = "div"
    else:
        hits_name = "lemgrams"
    result = {
        hits_name: result,
        "count": len(result),
    }

    if args["cache"]:
        # Cache the result
        try:
            with memcached.get_client() as mc:
                saved = mc.add(cache_key, result)
        except MemcahceError:
            pass
        else:
            if saved and "debug" in args:
                result.setdefault("DEBUG", {})
                result["DEBUG"]["cache_saved"] = True

    yield result


def _get_lemgrams(wf, corpora, limit):
    with app.app_context():
        cursor = db.mysql.connection.cursor()
        result = _query_lemgrams(cursor, wf, corpora, limit)[:limit]
    return result


def _query_lemgrams(cursor, wf, param_corpora, limit):
    result = []
    # Also collect the results in a set to filter out duplicates
    result_set = set()
    modcase = (lambda w: w.lower()) if wf.islower() else (lambda w: w)
    corpora_lists = [param_corpora]
    if param_corpora:
        corpora_lists.append([])
    # Search for lemmas in the selected corpora, lemma prefixes in
    # them, lemmas in all corpora and lemma prefixes in them, in this
    # order, only until the limit is reached.
    for corpora in corpora_lists:
        for suffpatt, is_any_prefix in [("..%", False), ("%", True)]:
            sql = _make_lemgram_query_part(wf + suffpatt, corpora, limit)
            # print(sql)
            sql = (pluginlib.CallbackPluginCaller
                   .filter_value_for_request("filter_sql", sql))
            db.sql_execute(cursor, sql)
            _retrieve_lemgrams(cursor, wf, modcase, is_any_prefix, result,
                               result_set)
            # print(repr(result))
            if len(result) >= limit:
                return result
    return result


def _retrieve_lemgrams(cursor, wf, modcase, is_any_prefix, result, result_set):
    # Note: Checking and filtering the results returned from the database
    # is probably not needed when using collation utf8(mb4)_bin, since it
    # is case-sensitive and does not collate "har", "hår" and "här". Using
    # a case-insensitive collation such as utf8(mb4)_swedish_ci or
    # utf8(mb4)_unicode_ci would not use the index, since the collation for
    # the table is utf8(mb4)_bin, so it would be unacceptably slow.
    # Case-insensitive matching would probably require a separate column
    # with preprocessed (lowercased, perhaps accents removed) lemgrams,
    # since apparently MySQL/MariaDB does not support specifying indexes
    # with different collations.
    #
    # The SQL LIKE pattern lemma..% also matches lemmas in which the lemma
    # searched for is followed by any number of full stops before the two
    # full stops that separate the POS tag in the lemgram. We wish to
    # filter out these incorrect lemmas.
    incorrect_lemma = wf + "..."
    for row in cursor:
        lemgram = row["lemgram"]
        if lemgram in result_set:
            continue
        mod_row = modcase(lemgram)
        if (mod_row.startswith(wf)
            and (is_any_prefix or not mod_row.startswith(incorrect_lemma))):
            result.append(lemgram)
            result_set.add(lemgram)


def _make_lemgram_query_part(pattern, corpora, limit):
    return ("(SELECT DISTINCT lemgram FROM `" + pluginconf["LEMGRAM_DBTABLE"]
            + "` WHERE lemgram LIKE '" + pattern + "'"
            + (" AND CORPUS IN (" + ','.join(["'" + corp + "'"
                                             for corp in corpora]) + ")"
               if corpora else '')
            # This would be too slow:
            # + " COLLATE 'utf8_swedish_ci'"
            # Order the result first by descending total frequency and
            # then by lemgram and then take the requested number of
            # rows at the beginning.
            + " GROUP BY lemgram"
            + " ORDER BY SUM(freq) DESC, lemgram"
            + " LIMIT " + str(limit)
            + ")")


def _encode_lemgram_result(lemgrams):
    return [{"class": ["entry"],
             "div": {"class": "source",
                     "resource": "lemgram_index"},
             "LexicalEntry": {"lem": lemgram}}
            for lemgram in lemgrams]
