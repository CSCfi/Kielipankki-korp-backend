#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
korp.cgi is a CGI interface for querying the corpora that are available on the server.
Currently it acts as a wrapper for the CQP querying language of Corpus Workbench.

Configuration is done by editing korp_config.py.

http://spraakbanken.gu.se/korp/
"""

from subprocess import Popen, PIPE
from collections import defaultdict
from concurrent import futures

import sys
import os
import random
import time
import cgi
import re
import json
import MySQLdb
import zlib
import urllib
import urllib2
import base64
import md5
from Queue import Queue, Empty
import threading
import ast
import itertools
import MySQLdb.cursors
import cPickle
import logging
import korp_config as config

################################################################################
# Nothing needs to be changed in this file. Use korp_config.py for configuration.

# The version of this script
KORP_VERSION = "2.8"

# The available CGI commands; for each command there must be a function
# with the same name, taking one argument (the CGI form)
COMMANDS = "info query count count_all relations relations_sentences lemgram_count timespan count_time optimize loglike query_sample authenticate names names_sentences".split()


def default_command(form):
    return "query" if "cqp" in form else "info"


# Special symbols used by this script; they must NOT be in the corpus
END_OF_LINE = "-::-EOL-::-"
LEFT_DELIM = "---:::"
RIGHT_DELIM = ":::---"

# Regular expressions for parsing CGI parameters
IS_NUMBER = re.compile(r"^\d+$")
IS_IDENT = re.compile(r"^[\w\-,|]+$")

QUERY_DELIM = ","

# Special characters in CQP regular expressions that need to be
# escaped with a backslash to match literally. If they are not
# preceded with a backslash, they should not be replaced in queries.
CQP_REGEX_SPECIAL_CHARS = "()|[].*+?{}^$"
# The character with which to replace literal backslashes escaped by
# another backslash, so that a regex metacharacter preceded by such
# will not be replaced. The literal backslashes are replaced before
# other replacements and they are restored after other replacements.
REGEX_ESCAPE_CHAR_TMP = (config.ENCODED_SPECIAL_CHAR_PREFIX
                         + unichr(config.ENCODED_SPECIAL_CHAR_OFFSET
                                  + len(config.SPECIAL_CHARS)))
# Encoding and decoding mapping (list of pairs (string, replacement))
# for special characters. Since the replacement for a regex
# metacharacter should not be a regex metacharacter, it is not
# preceded by a backslash.
SPECIAL_CHAR_ENCODE_MAP = [
    (escape + c, (config.ENCODED_SPECIAL_CHAR_PREFIX
                   + unichr(i + config.ENCODED_SPECIAL_CHAR_OFFSET)))
     for (i, c) in enumerate(config.SPECIAL_CHARS)
     for escape in ["\\" if c in CQP_REGEX_SPECIAL_CHARS else ""]]
# Handle literal backslashes only if any of config.SPECIAL_CHARS is a
# regex metacharacter.
if any(spch == rech for spch in config.SPECIAL_CHARS
       for rech in CQP_REGEX_SPECIAL_CHARS):
    SPECIAL_CHAR_ENCODE_MAP = (
        [("\\\\", REGEX_ESCAPE_CHAR_TMP)]
        + SPECIAL_CHAR_ENCODE_MAP
        + [(REGEX_ESCAPE_CHAR_TMP, "\\\\")])

# When decoding, we need not take into account regex metacharacter
# escaping
SPECIAL_CHAR_DECODE_MAP = [(repl[-1], c[-1])
                           for (c, repl) in SPECIAL_CHAR_ENCODE_MAP
                           if c != "\\\\" and repl != "\\\\"]

# The regexp for the names of the corpora whose sentences should never
# be shown in corpus order; initialized in main()
RESTRICTED_SENTENCES_CORPORA_REGEXP = None

################################################################################
# And now the functions corresponding to the CGI commands

def main():
    """The main CGI handler; reads the 'command' parameter and calls
    the same-named function with the CGI form as argument.

    Global CGI parameter are
     - command: (default: 'info' or 'query' depending on the 'cqp' parameter)
     - callback: an identifier that the result should be wrapped in
     - encoding: the encoding for interacting with the corpus (default: UTF-8)
     - indent: pretty-print the result with a specific indentation (for debugging)
     - debug: if set, return some extra information (for debugging)
    """
    starttime = time.time()
    sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 0)  # Open unbuffered stdout
    print_header()

    if config.CACHE_DIR and not os.path.exists(config.CACHE_DIR):
        os.makedirs(config.CACHE_DIR)
    
    # Convert form fields to regular dictionary
    form_raw = cgi.FieldStorage()
    form = dict((field, form_raw.getvalue(field)) for field in form_raw.keys())

    # Configure logging
    loglevel = logging.DEBUG if "debug" in form else config.LOG_LEVEL
    logging.basicConfig(filename=config.LOG_FILE,
                        format=('[%(filename)s %(process)d' +
                                ' %(levelname)s @ %(asctime)s]' +
                                ' %(message)s'),
                        level=loglevel)

    global RESTRICTED_SENTENCES_CORPORA_REGEXP
    RESTRICTED_SENTENCES_CORPORA_REGEXP = read_corpora_regexp_file(
        config.RESTRICTED_SENTENCES_CORPORA_FILE)

    incremental = form.get("incremental", "").lower() == "true"
    callback = form.get("callback")
    if callback:
        print callback + "(",
    
    if incremental:
        print "{"
            
    command = form.get("command")
    if not command:
        command = default_command(form)

    # Log remote IP address, HTTP refer(r)er and CGI parameters
    logging.info('IP: %s', cgi.os.environ.get('REMOTE_ADDR'))
    logging.info('User-agent: %s', cgi.os.environ.get('HTTP_USER_AGENT'))
    logging.info('Referer: %s', cgi.os.environ.get('HTTP_REFERER'))
    logging.info('Script: %s', cgi.os.environ.get('SCRIPT_NAME'))
    logging.info('Command: %s', command)
    logging.info('Params: %s', form)
    logging.debug('Env: %s', cgi.os.environ)

    try:
        if command not in COMMANDS:
            raise ValueError("'%s' is not a permitted command, try these instead: '%s'" % (command, "', '".join(COMMANDS)))
        assert_key("callback", form, IS_IDENT)
        assert_key("encoding", form, IS_IDENT)
        assert_key("indent", form, IS_NUMBER)

        # Here we call the command function:
        result = globals()[command](form)
        result["time"] = time.time() - starttime
        print_object(result, form)
        # Log elapsed time
        logging.info("Elapsed: %s", str(result["time"]))
    except:
        import traceback
        exc = sys.exc_info()
        if isinstance(exc[1], CustomTracebackException):
            exc = exc[1].exception
        error = {"ERROR": {"type": exc[0].__name__,
                           "value": str(exc[1])
                           },
                 "time": time.time() - starttime}
        trace = "".join(traceback.format_exception(*exc)).splitlines()
        if "debug" in form:
            error["ERROR"]["traceback"] = trace
        print_object(error, form)
        # Traceback for logging
        error["ERROR"]["traceback"] = trace
        # Log error message with traceback and elapsed time
        logging.error("%s", error["ERROR"])
        logging.info("Elapsed: %s", str(error["time"]))
    
    if incremental:
        print "}"

    if callback:
        print ")",


################################################################################
# INFO
################################################################################

def info(form):
    """Return information, either about a specific corpus
    or general information about the available corpora.
    """
    if "corpus" in form:
        return corpus_info(form)
    else:
        return general_info(form)


def general_info(form):
    """Return information about the available corpora.
    """
    corpora = runCQP("show corpora;", form)
    version = corpora.next()
    protected = []
    
    if config.PROTECTED_FILE:
        with open(config.PROTECTED_FILE) as infile:
            protected = [x.strip() for x in infile.readlines()]
    else:
        protected = get_protected_corpora()
    
    return {"cqp-version": version, "corpora": list(corpora), "protected_corpora": protected}


def corpus_info(form):
    """Return information about a specific corpus or corpora.
    """
    assert_key("corpus", form, IS_IDENT, True)
    
    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = uniquify_corpora(corpora)
    
    use_cache = bool(not form.get("cache", "").lower() == "false" and config.CACHE_DIR)
    
    # Caching
    checksum = get_hash((sorted(corpora),))
    
    if use_cache:
        cachefilename = os.path.join(config.CACHE_DIR, "info_" + checksum)
        if os.path.exists(cachefilename):
            with open(cachefilename, "r") as cachefile:
                result = json.load(cachefile)
                if "debug" in form:
                    result.setdefault("DEBUG", {})
                    result["DEBUG"]["cache_read"] = True
                    result["DEBUG"]["checksum"] = checksum
                return result
    
    result = {"corpora": {}}
    total_size = 0
    total_sentences = 0
    
    cmd = []

    for corpus in corpora:
        cmd += ["%s;" % corpus]
        cmd += show_attributes()
        cmd += ["info; .EOL.;"]

    cmd += ["exit;"]

    # call the CQP binary
    lines = runCQP(cmd, form)

    # skip CQP version 
    lines.next()
    
    for corpus in corpora:
        # read attributes
        attrs = read_attributes(lines)

        # corpus information
        info = {}
        
        for line in lines:
            if line == END_OF_LINE:
                break
            if ":" in line and not line.endswith(":"):
                infokey, infoval = (x.strip() for x in line.split(":", 1))
                info[infokey] = infoval
                if infokey == "Size":
                    total_size += int(infoval)
                elif infokey == "Sentences" and infoval.isdigit():
                    total_sentences += int(infoval)

        result["corpora"][corpus] = {"attrs": attrs, "info": info}

    if config.DB_HAS_CORPUSINFO:
        add_corpusinfo_from_database(result, corpora)
    
    result["total_size"] = total_size
    result["total_sentences"] = total_sentences
    
    if use_cache:
        cachefilename = os.path.join(config.CACHE_DIR, "info_" + checksum)
        if not os.path.exists(cachefilename):
            tmpfile = "%s.%s" % (cachefilename, os.getenv("UNIQUE_ID"))

            with open(tmpfile, "w") as cachefile:
                json.dump(result, cachefile)
            os.rename(tmpfile, cachefilename)
            
            if "debug" in form:
                result.setdefault("DEBUG", {})
                result["DEBUG"]["cache_saved"] = True
    
    if "debug" in form:
        result.setdefault("DEBUG", {})
        result["DEBUG"]["cmd"] = cmd
    
    return result


def add_corpusinfo_from_database(result, corpora):
    """Add extra info items from database to the info of corpora in result."""
    try:
        conn = MySQLdb.connect(use_unicode=True,
                               charset="utf8",
                               **config.DBCONNECT)
        cursor = conn.cursor()
        sql = ("SELECT `corpus`, `key`, `value` FROM corpus_info WHERE corpus IN (%s)"
               % ", ".join("%s" % conn.escape(c) for c in corpora))
        cursor.execute(sql)
        for row in cursor:
            corpus, key, value = row
            result["corpora"][corpus]["info"][key] = value
        cursor.close()
        conn.close()
    except (MySQLdb.MySQLError, MySQLdb.InterfaceError, MySQLdb.DatabaseError):
        # Return the result unmodified if the database access caused
        # an error.
        pass
    return result


################################################################################
# QUERY
################################################################################

def query_sample(form):
    import random
    
    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = list(set(corpora))
    # Randomize corpus order
    random.shuffle(corpora)
    
    for i in range(len(corpora)):
        corpus = corpora[i]
        check_authentication([corpus])
        
        form["corpus"] = corpus
        form["sort"] = "random"
        
        result = query(form)
        if result["hits"] > 0:
            return result
        
    return result


def query(form):
    """Perform a CQP query and return a number of matches.

    Each match contains position information and a list of the words and attributes in the match.

    The required parameters are
     - corpus: the CWB corpus. More than one parameter can be used.
     - cqp: the CQP query string
     - start, end: which result rows that should be returned

    The optional parameters are
     - context: how many words/sentences to the left/right should be returned
       (default '10 words')
     - show: add once for each corpus parameter (positional/strutural/alignment)
       (default only show the 'word' parameter)
     - show_struct: structural annotations for matched region. Multiple parameters possible.
     - within: only search for matches within the given s-attribute (e.g., within a sentence)
       (default: no within)
     - cut: set cutoff threshold to reduce the size of the result
       (default: no cutoff)
     - sort: sort the results by keyword ('keyword'), left or right context ('left'/'right') or random ('random')
       (default: no sorting)
     - incremental: returns the result incrementally instead of all at once
    """
    assert_key("cqp", form, r"", True)
    assert_key("corpus", form, IS_IDENT, True)
    assert_key("start", form, IS_NUMBER, True)
    assert_key("end", form, IS_NUMBER, True)
    #assert_key("context", form, r"^\d+ [\w-]+$")
    assert_key("show", form, IS_IDENT)
    assert_key("show_struct", form, IS_IDENT)
    #assert_key("within", form, IS_IDENT)
    assert_key("cut", form, IS_NUMBER)
    assert_key("sort", form, r"")
    assert_key("incremental", form, r"(true|false)")

    ############################################################################
    # First we read all CGI parameters and translate them to CQP
    
    incremental = form.get("incremental", "").lower() == "true"
    use_cache = bool(not form.get("cache", "").lower() == "false" and config.CACHE_DIR)
    
    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = uniquify_corpora(corpora)
    
    check_authentication(corpora)

    shown = form.get("show", [])
    if isinstance(shown, basestring):
        shown = shown.split(QUERY_DELIM)
    shown = set(shown)
    shown.add("word")

    shown_structs = form.get("show_struct", [])
    if isinstance(shown_structs, basestring):
        shown_structs = shown_structs.split(QUERY_DELIM)
    shown_structs = set(shown_structs)
    
    expand_prequeries = not form.get("expand_prequeries", "").lower() == "false"
    
    start, end = int(form.get("start")), int(form.get("end"))

    if config.MAX_KWIC_ROWS and end - start >= config.MAX_KWIC_ROWS:
        raise ValueError("At most %d KWIC rows can be returned per call." % config.MAX_KWIC_ROWS)

    # Arguments to be added at the end of every CQP query
    cqpextra = {}

    if "within" in form:
        cqpextra["within"] = form.get("within")
    if "cut" in form:
        cqpextra["cut"] = form.get("cut")

    # Sort numbered CQP-queries numerically
    cqp = [form.get(key).decode("utf-8") for key in sorted([k for k in form.keys() if k.startswith("cqp")], key=lambda x: int(x[3:]) if len(x) > 3 else 0)]

    result = {}

    checksum_data = (
                     sorted(corpora),
                     cqp,
                     sorted(cqpextra.items()),
                     form.get("defaultwithin", ""),
                     expand_prequeries
                    )

    # Calculate querydata checksum
    checksum = get_hash(checksum_data)
    
    debug = {}
    if "debug" in form:
        debug["checksum"] = checksum

    ns = Namespace()
    ns.total_hits = 0
    statistics = {}
    
    saved_statistics = {}
    saved_total_hits = 0
    saved_hits = form.get("querydata", "")
    
    if saved_hits or (use_cache and os.path.exists(os.path.join(config.CACHE_DIR, "query_" + checksum))):
        if not saved_hits:
            with open(os.path.join(config.CACHE_DIR, "query_" + checksum), "r") as cachefile:
                saved_hits = cachefile.read()
            if "debug" in form:
                debug["cache_read"] = True
        
        try:
            saved_hits = zlib.decompress(saved_hits.replace("\\n", "\n").replace("-", "+").replace("_", "/").decode("base64"))
        except:
            saved_hits = ""
        
        if saved_hits:
            if "debug" in form and not "using_cache" in result:
                debug["using_querydata"] = True
            saved_crc32, saved_total_hits, stats_temp = saved_hits.split(";", 2)
            if saved_crc32 == checksum:
                saved_total_hits = int(saved_total_hits)
                for pair in stats_temp.split(";"):
                    c, h = pair.split(":")
                    saved_statistics[c] = int(h)
        
    ns.start_local = start
    ns.end_local = end
    
    ############################################################################
    # If saved_statistics is available, calculate which corpora need to be queried
    # and then query them in parallel.
    # If saved_statistics is NOT available, query the corpora in serial until we
    # have the needed rows, and then query the remaining corpora in parallel to get
    # number of hits.
    
    if saved_statistics:
        statistics = saved_statistics
        ns.total_hits = sum(saved_statistics.values())
        corpora_hits = which_hits(corpora, saved_statistics, start, end)
        corpora_kwics = {}
        
        ns.progress_count = 0
        
        if len(corpora_hits) == 0:
            result["kwic"] = []
        elif len(corpora_hits) == 1:
            # If only hits in one corpus, it is faster to not use threads
            corpus, hits = corpora_hits.items()[0]

            def anti_timeout0(queue):
                result["kwic"], _ = query_and_parse(form, corpus, cqp, cqpextra, shown, shown_structs, hits[0], hits[1], expand_prequeries=expand_prequeries)
                queue.put("DONE")

            anti_timeout_loop(anti_timeout0)
        else:
            if incremental:
                print '"progress_corpora": [%s],' % ('"' + '", "'.join(corpora_hits.keys()) + '"' if corpora_hits.keys() else "")
            with futures.ThreadPoolExecutor(max_workers=config.PARALLEL_THREADS) as executor:
                future_query = dict((executor.submit(query_and_parse, form, corpus, cqp, cqpextra, shown, shown_structs, corpora_hits[corpus][0], corpora_hits[corpus][1], False, expand_prequeries), corpus) for corpus in corpora_hits)
                
                def anti_timeout1(queue):
                    for future in futures.as_completed(future_query):
                        corpus = future_query[future]
                        if future.exception() is not None:
                            raise CQPError(future.exception())
                        else:
                            kwic, _ = future.result()
                            corpora_kwics[corpus] = kwic
                            if incremental:
                                queue.put('"progress_%d": {"corpus": "%s", "hits": %d},' % (ns.progress_count, corpus, corpora_hits[corpus][1] - corpora_hits[corpus][0] + 1))
                                ns.progress_count += 1
                    queue.put("DONE")

                anti_timeout_loop(anti_timeout1)

                for corpus in corpora:
                    if corpus in corpora_hits.keys():
                        if "kwic" in result:
                            result["kwic"].extend(corpora_kwics[corpus])
                        else:
                            result["kwic"] = corpora_kwics[corpus]
    else:
        if incremental:
            print '"progress_corpora": [%s],' % ('"' + '", "'.join(corpora) + '"' if corpora else "")
        
        ns.progress_count = 0
        ns.rest_corpora = []
        
        def anti_timeout2(queue):
            # Serial until we've got all the requested rows
            for i, corpus in enumerate(corpora):
                           
                if ns.end_local < 0:
                    ns.rest_corpora = corpora[i:]
                    break
                            
                kwic, nr_hits = query_and_parse(form, corpus, cqp, cqpextra, shown, shown_structs, ns.start_local, ns.end_local, False, expand_prequeries)
            
                statistics[corpus] = nr_hits
                ns.total_hits += nr_hits
                
                # Calculate which hits from next corpus we need, if any
                ns.start_local -= nr_hits
                ns.end_local -= nr_hits
                if ns.start_local < 0:
                    ns.start_local = 0

                if "kwic" in result:
                    result["kwic"].extend(kwic)
                else:
                    result["kwic"] = kwic
                
                if incremental:
                    queue.put('"progress_%d": {"corpus": "%s", "hits": %d},' % (ns.progress_count, corpus, nr_hits))
                    ns.progress_count += 1
            queue.put("DONE")
                
        anti_timeout_loop(anti_timeout2)
        
        if incremental:
            print_object(result, form)
            result = {}
        
        if ns.rest_corpora:

            if incremental:
                print ",",
            with futures.ThreadPoolExecutor(max_workers=config.PARALLEL_THREADS) as executor:
                future_query = dict((executor.submit(query_corpus, form, corpus, cqp, cqpextra, shown, shown_structs, 0, 0, True, expand_prequeries), corpus) for corpus in ns.rest_corpora)
                
                def anti_timeout3(queue):
                    for future in futures.as_completed(future_query):
                        corpus = future_query[future]
                        if future.exception() is not None:
                            raise CQPError(future.exception())
                        else:
                            _, nr_hits, _, _ = future.result()
                            statistics[corpus] = nr_hits
                            ns.total_hits += nr_hits
                            if incremental:
                                print '"progress_%d": {"corpus": "%s", "hits": %d},' % (ns.progress_count, corpus, nr_hits)
                                ns.progress_count += 1
                    queue.put("DONE")

                anti_timeout_loop(anti_timeout3)

        elif incremental:
            print ",",

    if "debug" in form:
        debug["cqp"] = cqp

    result["hits"] = ns.total_hits
    result["corpus_hits"] = statistics
    result["corpus_order"] = corpora
    result["querydata"] = zlib.compress(checksum + ";" + str(ns.total_hits) + ";" + ";".join("%s:%d" % (c, h) for c, h in statistics.iteritems())).encode("base64").replace("+", "-").replace("/", "_")
    
    if use_cache:
        cachefilename = os.path.join(config.CACHE_DIR, "query_" + checksum)
        if not os.path.exists(cachefilename):
            tmpfile = "%s.%s" % (cachefilename, os.getenv("UNIQUE_ID"))

            with open(tmpfile, "w") as cachefile:
                cachefile.write(result["querydata"])
            os.rename(tmpfile, cachefilename)
            
            if "debug" in form:
                debug["cache_saved"] = True

    if debug:
        result["DEBUG"] = debug

    # Log the number of hits by corpus
    logging.info("Hits: %s", statistics)
    return result


def optimize(form):
    assert_key("cqp", form, r"", True)
    
    cqpextra = {}

    if "within" in form:
        cqpextra["within"] = form["within"]
    if "cut" in form:
        cqpextra["cut"] = form["cut"]
    
    cqp = form["cqp"]  # cqp = [form.get(key).decode("utf-8") for key in sorted([k for k in form.keys() if k.startswith("cqp")], key=lambda x: int(x[3:]) if len(x) > 3 else 0)]
    result = {"cqp": query_optimize(cqp, cqpextra)}
    return result


def query_optimize(cqp, cqpextra, find_match=True, expand=True):
    """ Optimizes simple queries with multiple words by converting them to an MU query.
        Optimization only works for queries with at least two tokens, or one token preceded
        by one or more wildcards. The query also must use "within".
        """
    q, rest = parse_cqp(cqp)

    if expand:
        expand = cqpextra.get("within")
    
    leading_wildcards = False
    trailing_wildcards = False
    # Remove leading and trailing wildcards since they will only slow us down
    while q and q[0].startswith("[]"):
        leading_wildcards = True
        del q[0]
    while q and q[-1].startswith("[]"):
        trailing_wildcards = True
        del q[-1]
    
    # Determine if this query may not benefit from optimization
    if len(q) == 0 or (len(q) == 1 and not leading_wildcards) or rest or not expand:
        return make_query(make_cqp(cqp, cqpextra))
    
    cmd = ["MU"]
    wildcards = {}

    for i in range(len(q) - 1):
        if q[i].startswith("[]"):
            n1 = n2 = None
            if q[i] == "[]":
                n1 = n2 = 1
            elif re.search(r"{\s*(\d+)\s*,\s*(\d*)\s*}$", q[i]):
                n = re.search(r"{\s*(\d+)\s*,\s*(\d*)\s*}$", q[i]).groups()
                n1 = int(n[0])
                n2 = int(n[1]) if n[1] else 9999
            elif re.search(r"{\s*(\d*)\s*}$", q[i]):
                n1 = n2 = int(re.search(r"{\s*(\d*)\s*}$", q[i]).groups()[0])
            if not n1 is None:
                wildcards[i] = (n1, n2)
            continue
        elif re.search(r"{.*?}$", q[i]):
            # Repetition for anything other than wildcards can't be optimized
            return make_query(make_cqp(cqp, cqpextra))
        cmd[0] += " (meet %s" % (q[i])

    if re.search(r"{.*?}$", q[-1]):
        # Repetition for anything other than wildcards can't be optimized
        return make_query(make_cqp(cqp, cqpextra))

    cmd[0] += " %s" % q[-1]

    wildcard_range = [1, 1]
    for i in range(len(q) - 2, -1, -1):
        if i in wildcards:
            wildcard_range[0] += wildcards[i][0]
            wildcard_range[1] += wildcards[i][1]
            continue
        elif i + 1 in wildcards:
            if wildcard_range[1] >= 9999:
                cmd[0] += " %s)" % expand
            else:
                cmd[0] += " %d %d)" % (wildcard_range[0], wildcard_range[1])
            wildcard_range = [1, 1]
        else:
            cmd[0] += " 1 1)"

    if find_match:
        # MU searches only highlights the first keyword of each hit. To highlight all keywords we need to
        # do a new non-optimized search within the results, and to be able to do that we first need to expand the rows.
        # Most of the times we only need to expand to the right, except for when leading wildcards are used.
        if leading_wildcards:
            cmd[0] += " expand to %s;" % expand
        else:
            cmd[0] += " expand right to %s;" % expand
        cmd += ["Last;"]
        cmd += make_query(make_cqp(cqp, cqpextra))
    else:
        cmd[0] += " expand to %s;" % expand

    return cmd


def query_corpus(form, corpus, cqp, cqpextra, shown, shown_structs, start, end, no_results=False, expand_prequeries=True):

    # Optimization
    optimize = True
    
    shown = shown.copy()  # To not edit the original
    
    # Context
    contexts = {"leftcontext": form.get("leftcontext", {}),
                "rightcontext": form.get("rightcontext", {}),
                "context": form.get("context", {})}
    defaultcontext = form.get("defaultcontext", "10 words")
    
    for c in contexts: 
        if contexts[c]:
            if not ":" in contexts[c]:
                raise ValueError("Malformed value for key '%s'." % c)
            contexts[c] = dict(x.split(":") for x in contexts[c].split(","))

    # For aligned corpora, use the context and within parameters of
    # the main (first) corpus.
    corpus1 = corpus.split("|")[0]
    if corpus1 in contexts["leftcontext"] or corpus1 in contexts["rightcontext"]:
        context = (contexts["leftcontext"].get(corpus1, defaultcontext), contexts["rightcontext"].get(corpus1, defaultcontext))
    else:
        context = (contexts["context"].get(corpus1, defaultcontext),)

    # Split the context parameters to a primary and secondary context,
    # specified as "primary/secondary". The primary context is passed
    # to CQP as usual, and the secondary context is handled in
    # query_parse_lines. The secondary context is used to limit the
    # context further if necessary; for example, "20 words/1 sentence"
    # limits a context to a maximum of 20 words within a single
    # sentence and "1 paragraph/3 sentence" to a maximum of three
    # sentences within a single paragraph. The contexts A/B and B/A
    # produce the same result for any A and B. This might be
    # generalized to multiple secondary contexts, each providing a
    # maximum context by a different unit.
    #
    # context2 is always a pair of pairs: for the left and right
    # context, a pair of the context unit (a structural attribute name
    # or "words"/"word") and the number of units. It is returned by
    # the function as an additional value in the tuple. If a context
    # has only the primary context, the corresponding item in context2
    # is None.
    #
    # Conceptually it might be better to split the context in
    # query_and_parse (or a separate function called by it), but this
    # was simpler to implement. (Jyrki Niemi 2016-11-30)
    context2 = []
    for ctxt in context:
        ctxt2 = ctxt.partition('/')[2]
        if ctxt2:
            try:
                unit_count, context_unit = ctxt2.split()
                if context_unit == "word":
                    context_unit = "words"
                context2.append((context_unit, int(unit_count)))
            except ValueError:
                raise ValueError("Malformed value for secondary context.")
        else:
            context2.append(None)
    if len(context2) == 1:
        context2.append(context2[0])
    context2 = tuple(context2)
    context = tuple([ctxt.partition('/')[0] for ctxt in context])

    # Within
    defaultwithin = form.get("defaultwithin", "")
    within = form.get("within", defaultwithin)
    if within:
        if ":" in within:
            within = dict(x.split(":") for x in within.split(","))
            within = within.get(corpus1, defaultwithin)
        cqpextra["within"] = within
    
    cqpextra_internal = cqpextra.copy()
    
    # Handle aligned corpora
    if "|" in corpus:
        linked = corpus.split("|")
        cqpnew = []
        
        for c in cqp:
            cs = c.split("LINKED_CORPUS:")
            
            # In a multi-language query, the "within" argument must be placed directly after the main (first language) query
            if len(cs) > 1 and "within" in cqpextra:
                cs[0] = "%s within %s : " % (cs[0].rstrip()[:-1], cqpextra["within"])
                del cqpextra_internal["within"]

            c = [cs[0]]
            
            for d in cs[1:]:
                linked_corpora, link_cqp = d.split(None, 1)
                if linked[1] in linked_corpora.split("|"):
                    c.append("%s %s" % (linked[1], link_cqp))
                    
            cqpnew.append("".join(c).rstrip(": "))
            
        cqp = cqpnew
        corpus = linked[0]
        shown.add(linked[1].lower())

    # Sorting
    sort = form.get("sort")
    random_seed = ""
    # If the sentences of the corpus should never be displayed in
    # corpus order and "sort" has not been specified, use
    # config.RESTRICTED_SENTENCES_DEFAULT_SORT
    if (RESTRICTED_SENTENCES_CORPORA_REGEXP
        and sort not in ["left", "keyword", "right", "random"]
        and RESTRICTED_SENTENCES_CORPORA_REGEXP.match(corpus)):
        sort = config.RESTRICTED_SENTENCES_DEFAULT_SORT
        # Use a random but fixed order if "random" is used
        random_seed = "1"
    if sort == "left":
        sortcmd = ["sort by word on match[-1] .. match[-3];"]
    elif sort == "keyword":
        sortcmd = ["sort by word;"]
    elif sort == "right":
        sortcmd = ["sort by word on matchend[1] .. matchend[3];"]
    elif sort == "random":
        random_seed = random_seed or form.get("random_seed", "")
        sortcmd = ["sort randomize %s;" % random_seed]
    elif sort:
        # Sort by positional attribute
        sortcmd = ["sort by %s;" % sort]
    else:
        sortcmd = []

    # Build the CQP query
    cmd = ["%s;" % corpus]
    # This prints the attributes and their relative order:
    cmd += show_attributes()
    for i, c in enumerate(cqp):
        cqpextra_temp = cqpextra_internal.copy()
        pre_query = i+1 < len(cqp)
        
        if pre_query and expand_prequeries:
            cqpextra_temp["expand"] = "to " + cqpextra["within"]
        
        # If expand_prequeries is False, we can't use optimization
        if optimize and expand_prequeries:
            cmd += query_optimize(c, cqpextra_temp, find_match=(not pre_query), expand=not (pre_query and not expand_prequeries))
        else:
            cmd += make_query(make_cqp(c, cqpextra_temp))
        
        if pre_query:
            cmd += ["Last;"]
    
    # This prints the size of the query (i.e., the number of results):
    cmd += ["size Last;"]
    if not no_results:
        cmd += ["show +%s;" % " +".join(shown)]
        if len(context) == 1:
            cmd += ["set Context %s;" % context[0]]
        else:
            cmd += ["set LeftContext %s;" % context[0]]
            cmd += ["set RightContext %s;" % context[1]]
        cmd += ["set LeftKWICDelim '%s '; set RightKWICDelim ' %s';" % (LEFT_DELIM, RIGHT_DELIM)]
        if shown_structs:
            cmd += ["set PrintStructures '%s';" % ", ".join(shown_structs)]
        cmd += ["set ExternalSort yes;"]
        cmd += sortcmd
        # This prints the result rows:
        cmd += ["cat Last %s %s;" % (start, end)]
    cmd += ["exit;"]

    ######################################################################
    # Then we call the CQP binary, and read the results

    lines = runCQP(cmd, form, attr_ignore=True)

    # Skip the CQP version
    lines.next()
    
    # Read the attributes and their relative order 
    attrs = read_attributes(lines)
    
    # Read the size of the query, i.e., the number of results
    nr_hits = int(lines.next())
    
    return (lines, nr_hits, attrs, context2)


def query_parse_lines(corpus, lines, attrs, shown, shown_structs,
                      context2=None):
    ######################################################################
    # Now we create the concordance (kwic = keywords in context)
    # from the remaining lines

    # Filter out unavailable attributes
    p_attrs = [attr for attr in attrs["p"] if attr in shown]
    nr_splits = len(p_attrs) - 1
    s_attrs = set(attr for attr in attrs["s"] if attr in shown)
    ls_attrs = set(attr for attr in attrs["s"] if attr in shown_structs)
    #a_attrs = set(attr for attr in attrs["a"] if attr in shown)

    if context2 is None:
        context2 = (None, None)

    kwic = []
    for line in lines:
        linestructs = {}
        match = {}

        header, line = line.split(":", 1)
        if header[:3] == "-->":
            # For aligned corpora, every other line is the aligned result
            aligned = header[3:]
        else:
            # This is the result row for the query corpus
            aligned = None
            match["position"] = int(header)

        # Handle PrintStructures
        if ls_attrs and not aligned:
            if ":  " in line:
                lineattr, line = line.rsplit(":  ", 1)
            else:
                # Sometimes, depending on context, CWB uses only one space instead of two as a separator
                lineattr, line = line.split(">: ", 1)
                lineattr += ">"
            
            lineattrs = lineattr[2:-1].split("><")
            
            # Handle "><" in attribute values
            if not len(lineattrs) == len(ls_attrs):
                new_lineattrs = []
                for la in lineattrs:
                    if not la.split(" ", 1)[0] in ls_attrs:
                        new_lineattrs[-1] += "><" + la
                    else:
                        new_lineattrs.append(la)
                lineattrs = new_lineattrs
            
            for s in lineattrs:
                if s in ls_attrs:
                    s_key = s
                    s_val = None
                else:
                    s_key, s_val = s.split(" ", 1)

                linestructs[s_key] = s_val

        words = line.split()
        tokens = []
        n = 0
        structs = defaultdict(list)
        struct = None

        for word in words:
        
            if struct:
                # Structural attrs can be split in the middle (<s_n 123>),
                # so we need to finish the structure here
                struct_id, word = word.split(">", 1)
                if config.ENCODED_SPECIAL_CHARS:
                    struct_id = decode_special_chars(struct_id)
                structs["open"].append(struct + " " + struct_id)
                struct = None

            # We use special delimiters to see when we enter and leave the match region
            if word == LEFT_DELIM:
                match["start"] = n
                continue
            elif word == RIGHT_DELIM:
                match["end"] = n
                continue

            # We read all structural attributes that are opening (from the left)
            while word[0] == "<":
                if word[1:] in s_attrs:
                    # If we stopped in the middle of a struct (<s_n 123>),
                    # we need to continue with the next word
                    struct = word[1:]
                    break
                elif ">" in word and word[1:word.find(">")] in s_attrs:
                    # This is for s-attrs that have no arguments (<s>)
                    struct, word = word[1:].split(">", 1)
                    structs["open"].append(struct)
                    struct = None
                else:
                    # What we've found is not a structural attribute
                    break

            if struct:
                # If we stopped in the middle of a struct (<s_n 123>),
                # we need to continue with the next word
                continue

            # Now we read all s-attrs that are closing (from the right)
            while word[-1] == ">" and "</" in word:
                tempword, struct = word[:-1].rsplit("</", 1)
                if not tempword or struct not in s_attrs:
                    struct = None
                    break
                elif struct in s_attrs:
                    word = tempword
                    structs["close"].insert(0, struct)
                    struct = None

            # What's left is the word with its p-attrs
            values = word.rsplit("/", nr_splits)
            token = dict((attr, translate_undef(val)) for (attr, val) in zip(p_attrs, values))
            if structs:
                token["structs"] = structs
                structs = defaultdict(list)
            tokens.append(token)

            n += 1

        # Limit the tokens according to the possible secondary
        # context, left context first.
        if context2[0] is not None:
            context_unit, unit_count = context2[0]
            first_token_num = 0
            if context_unit == "words":
                # Context unit is token
                if match["start"] > unit_count:
                    first_token_num = match["start"] - unit_count
            else:
                # Context unit is a structural attribute: go through
                # tokens from the match start towards the beginning,
                # until the number of closing context units matches
                # the secondary context unit count.
                i = match["start"] - 1
                struct_count = 0
                while i >= 0 and struct_count < unit_count:
                    if context_unit in (tokens[i].get("structs", {})
                                        .get("close", [])):
                        struct_count += 1
                    i -= 1
                first_token_num = i + 1 + int(struct_count >= unit_count)
            if first_token_num > 0:
                tokens[:first_token_num] = []
                match["start"] -= first_token_num
                match["end"] -= first_token_num
        # Secondary right context
        if context2[1] is not None:
            context_unit, unit_count = context2[1]
            token_count = len(tokens)
            last_token_num = token_count
            if context_unit == "words":
                last_token_num = min(match["end"] + unit_count, last_token_num)
            else:
                # Go through toknes from the match end towards the
                # end, until the number of opening context units
                # matches the secondary context unit count.
                i = match["end"]
                struct_count = 0
                while i < token_count and struct_count < unit_count:
                    if context_unit in (tokens[i].get("structs", {})
                                        .get("open", [])):
                        struct_count += 1
                    i += 1
                last_token_num = i - int(struct_count >= unit_count)
            if last_token_num <= token_count:
                tokens[last_token_num:] = []

        if aligned:
            # If this was an aligned row, we add it to the previous kwic row
            if words != ["(no", "alignment", "found)"]:
                kwic[-1].setdefault("aligned", {})[aligned] = tokens
        else:
            if not "start" in match:
                # TODO: CQP bug - CQP can't handle too long sentences, skipping
                continue
            # Otherwise we add a new kwic row
            kwic_row = {"corpus": corpus, "match": match}
            if linestructs:
                kwic_row["structs"] = linestructs
            kwic_row["tokens"] = tokens
            kwic.append(kwic_row)

    if config.ENCODED_SPECIAL_CHARS:

        def decode_attr_values(attrs, exclude=None):
            # Decode encoded special characters in the attributes of
            # attrs (a dict), except those whose names are listed in
            # exclude.
            exclude = exclude or []
            for attr, val in attrs.iteritems():
                if attr not in exclude and val is not None:
                    attrs[attr] = decode_special_chars(val)

        for kwic_row in kwic:
            # Decode encoded special characters in p-attribute values
            for token in kwic_row["tokens"]:
                decode_attr_values(token, exclude=["structs"])
            # Also in aligned attributes
            if "aligned" in kwic_row:
                for tokens in kwic_row["aligned"].itervalues():
                    for token in tokens:
                        decode_attr_values(token, exclude=["structs"])
            # The special characters would seem to work as such in
            # s-attribute values, but decode them because they have
            # been encoded in queries.
            if "structs" in kwic_row:
                decode_attr_values(kwic_row["structs"])

    return kwic


def query_and_parse(form, corpus, cqp, cqpextra, shown, shown_structs, start, end, no_results=False, expand_prequeries=True):
    lines, nr_hits, attrs, context2 = query_corpus(form, corpus, cqp, cqpextra, shown, shown_structs, start, end, no_results, expand_prequeries)
    kwic = query_parse_lines(corpus, lines, attrs, shown, shown_structs,
                             context2)
    return kwic, nr_hits
    

def which_hits(corpora, stats, start, end):
    corpus_hits = {}
    for corpus in corpora:
        hits = stats[corpus]
        if hits > start:
            corpus_hits[corpus] = (start, min(hits - 1, end))
        
        start -= hits
        end -= hits
        if start < 0:
            start = 0
        if end < 0:
            break
    
    return corpus_hits


################################################################################
# COUNT
################################################################################

def count(form):
    """Perform a CQP query and return a count of the given words/attrs.

    The required parameters are
     - corpus: the CWB corpus
     - cqp: the CQP query string
     - groupby: add once for each corpus positional or structural attribute

    The optional parameters are
     - within: only search for matches within the given s-attribute (e.g., within a sentence)
       (default: no within)
     - cut: set cutoff threshold to reduce the size of the result
       (default: no cutoff)
     - ignore_case: changes all values of the selected attribute to lower case
     - incremental: incrementally report the progress while executing
       (default: false)
     - expand_prequeries: when using multiple queries, this determines whether
       subsequent queries should be run on the containing sentences (or any other structural attribute
       defined by 'within') from the previous query, or just the matches.
       (default: true)
    """
    assert_key("cqp", form, r"", True)
    assert_key("corpus", form, IS_IDENT, True)
    assert_key("groupby", form, IS_IDENT, True)
    assert_key("cut", form, IS_NUMBER)
    assert_key("ignore_case", form, IS_IDENT)
    assert_key("incremental", form, r"(true|false)")
    
    incremental = form.get("incremental", "").lower() == "true"
    use_cache = bool(not form.get("cache", "").lower() == "false" and config.CACHE_DIR)
    
    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = set(corpora)
    
    check_authentication(corpora)
    
    groupby = form.get("groupby")
    if isinstance(groupby, basestring):
        groupby = groupby.split(QUERY_DELIM)
    
    ignore_case = form.get("ignore_case", [])
    if isinstance(ignore_case, basestring):
        ignore_case = ignore_case.split(QUERY_DELIM)
    ignore_case = set(ignore_case)
    
    defaultwithin = form.get("defaultwithin", "")
    within = form.get("within", defaultwithin)
    if ":" in within:
        within = dict(x.split(":") for x in within.split(","))
    else:
        within = {"": defaultwithin}
    
    start = int(form.get("start", 0))
    end = int(form.get("end", -1))
    
    split = form.get("split", "")
    if isinstance(split, basestring):
        split = split.split(QUERY_DELIM)
    
    strippointer = form.get("strippointer", "")
    if isinstance(strippointer, basestring):
        strippointer = strippointer.split(QUERY_DELIM)
    
    # Sort numbered CQP-queries numerically
    cqp = [form.get(key).decode("utf-8") for key in sorted([k for k in form.keys() if k.startswith("cqp")], key=lambda x: int(x[3:]) if len(x) > 3 else 0)]
    simple = form.get("simple", "").lower() == "true"

    if cqp == ["[]"]:
        simple = True
    
    expand_prequeries = not form.get("expand_prequeries", "").lower() == "false"

    checksum_data = (sorted(corpora),
                     cqp,
                     groupby,
                     sorted(within.iteritems()),
                     defaultwithin,
                     sorted(ignore_case),
                     sorted(split),
                     sorted(strippointer),
                     start,
                     end,
                     form.get("defaultwithin"),
                     form.get("within"))
    checksum = get_hash(checksum_data)
    
    if use_cache:
        cachefilename = os.path.join(config.CACHE_DIR, "count_" + checksum)
        if os.path.exists(cachefilename):
            with open(cachefilename, "r") as cachefile:
                result = json.load(cachefile)
                if "debug" in form:
                    result.setdefault("DEBUG", {})
                    result["DEBUG"]["cache_read"] = True
                    result["DEBUG"]["checksum"] = checksum
                return result

    result = {"corpora": {}}
    total_stats = {"absolute": defaultdict(int),
                   "relative": defaultdict(float),
                   "sums": {"absolute": 0, "relative": 0.0}}
    
    ns = Namespace()  # To make variables writable from nested functions
    ns.total_size = 0

    count_function = count_query_worker if not simple else count_query_worker_simple

    ns.limit_count = 0
    ns.progress_count = 0
    if incremental:
        print '"progress_corpora": [%s],' % ('"' + '", "'.join(corpora) + '"' if corpora else "")

    with futures.ThreadPoolExecutor(max_workers=config.PARALLEL_THREADS) as executor:
        future_query = dict((executor.submit(count_function, corpus, cqp, groupby, ignore_case, form, expand_prequeries), corpus) for corpus in corpora)
        
        def anti_timeout(queue):

            for future in futures.as_completed(future_query):
                corpus = future_query[future]
                if future.exception() is not None:
                    raise CQPError(future.exception())
                else:
                    lines, nr_hits, corpus_size = future.result()

                    ns.total_size += corpus_size
                    corpus_stats = {"absolute": defaultdict(int),
                                    "relative": defaultdict(float),
                                    "sums": {"absolute": 0, "relative": 0.0}}
                    
                    for line in lines:
                        count, ngram = line.lstrip().split(" ", 1)
                        
                        if config.ENCODED_SPECIAL_CHARS:
                            ngram = decode_special_chars(ngram)

                        if len(groupby) > 1:
                            ngram_groups = ngram.split("\t")
                        else:
                            ngram_groups = [ngram]
                        
                        all_ngrams = []
                        
                        for i, ngram in enumerate(ngram_groups):
                            # Split value sets and treat each value as a hit
                            if groupby[i] in split:
                                tokens = ngram.split(" ")
                                split_tokens = [[x for x in token.split("|") if x] if not token == "|" else ["|"] for token in tokens]
                                ngrams = itertools.product(*split_tokens)
                                ngrams = [" ".join(x) for x in ngrams]
                            else:
                                ngrams = [ngram]
                            
                            # Remove multi word pointers
                            if groupby[i] in strippointer:
                                for i in range(len(ngrams)):
                                    if ":" in ngrams[i]:
                                        ngramtemp, pointer = ngrams[i].rsplit(":", 1)
                                        if pointer.isnumeric():
                                            ngrams[i] = ngramtemp
                            all_ngrams.append(ngrams)
                        
                        cross = list(itertools.product(*all_ngrams))
                                                        
                        for ngram in cross:
                            ngram = "/".join(ngram)
                            corpus_stats["absolute"][ngram] += int(count)
                            corpus_stats["relative"][ngram] += int(count) / float(corpus_size) * 1000000
                            corpus_stats["sums"]["absolute"] += int(count)
                            corpus_stats["sums"]["relative"] += int(count) / float(corpus_size) * 1000000
                            total_stats["absolute"][ngram] += int(count)
                            total_stats["sums"]["absolute"] += int(count)
                
                    result["corpora"][corpus] = corpus_stats
                    
                    ns.limit_count += len(corpus_stats["absolute"])
                    
                    if incremental:
                        queue.put('"progress_%d": "%s",' % (ns.progress_count, corpus))
                        ns.progress_count += 1
            queue.put("DONE")

        anti_timeout_loop(anti_timeout)

    result["count"] = len(total_stats["absolute"])
    
    if end > -1 and (start > 0 or len(total_stats["absolute"]) > (end - start) + 1):
        total_absolute = sorted(total_stats["absolute"].iteritems(), key=lambda x: x[1], reverse=True)[start:end+1]
        new_corpora = {}
        for ngram, count in total_absolute:
            total_stats["relative"][ngram] = count / float(ns.total_size) * 1000000
                    
            for corpus in corpora:
                new_corpora.setdefault(corpus, {"absolute": {}, "relative": {}, "sums": result["corpora"][corpus]["sums"]})
                if ngram in result["corpora"][corpus]["absolute"]:
                    new_corpora[corpus]["absolute"][ngram] = result["corpora"][corpus]["absolute"][ngram]
                if ngram in result["corpora"][corpus]["relative"]:
                    new_corpora[corpus]["relative"][ngram] = result["corpora"][corpus]["relative"][ngram]
        
        result["corpora"] = new_corpora
        total_stats["absolute"] = dict(total_absolute)
    else:
        for ngram, count in total_stats["absolute"].iteritems():
            total_stats["relative"][ngram] = count / float(ns.total_size) * 1000000
    
    total_stats["sums"]["relative"] = total_stats["sums"]["absolute"] / float(ns.total_size) * 1000000 if ns.total_size > 0 else 0.0
    result["total"] = total_stats
    
    if "debug" in form:
        result["DEBUG"] = {"cqp": cqp, "checksum": checksum, "simple": simple}
    
    if use_cache and ns.limit_count <= config.CACHE_MAX_STATS:
        unique_id = os.getenv("UNIQUE_ID")
        cachefilename = os.path.join(config.CACHE_DIR, "count_" + checksum)
        tmpfile = "%s.%s" % (cachefilename, unique_id)

        with open(tmpfile, "w") as cachefile:
            json.dump(result, cachefile)
        os.rename(tmpfile, cachefilename)
        
        if "debug" in form:
            result["DEBUG"]["cache_saved"] = True
    
    return result


def count_all(form):
    """Returns a count of the given attrs.

    The required parameters are
     - corpus: the CWB corpus
     - groupby: add once for each corpus positional or structural attribute

    The optional parameters are
     - within: only search for matches within the given s-attribute (e.g., within a sentence)
       (default: no within)
     - cut: set cutoff threshold to reduce the size of the result
       (default: no cutoff)
     - ignore_case: changes all values of the selected attribute to lower case
     - incremental: incrementally report the progress while executing
       (default: false)
    """
    assert_key("corpus", form, IS_IDENT, True)
    assert_key("groupby", form, IS_IDENT, True)
    assert_key("cut", form, IS_NUMBER)
    assert_key("ignore_case", form, IS_IDENT)
    assert_key("incremental", form, r"(true|false)")
    
    form["cqp"] = "[]"  # Dummy value, not used
    form["simple"] = "true"

    return count(form)


def count_time(form):
    """
    """
    import datetime
    from dateutil.relativedelta import relativedelta
    
    assert_key("cqp", form, r"", True)
    assert_key("corpus", form, IS_IDENT, True)
    assert_key("cut", form, IS_NUMBER)
    assert_key("incremental", form, r"(true|false)")
    assert_key("granularity", form, r"[ymdhnsYMDHNS]")
    assert_key("from", form, r"^\d{14}$")
    assert_key("to", form, r"^\d{14}$")
    assert_key("strategy", form, r"^[123]$")
    
    incremental = form.get("incremental", "").lower() == "true"

    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = set(corpora)
    
    check_authentication(corpora)
    
    # Sort numbered CQP-queries numerically
    cqp = [form.get(key).decode("utf-8") for key in sorted([k for k in form.keys() if k.startswith("cqp")], key=lambda x: int(x[3:]) if len(x) > 3 else 0)]
    subcqp = [form.get(key).decode("utf-8") for key in sorted([k for k in form.keys() if k.startswith("subcqp")], key=lambda x: int(x[6:]) if len(x) > 6 else 0)]

    if subcqp:
        cqp.append(subcqp)
    granularity = form.get("granularity", "y").lower()
    fromdate = form.get("from", "")
    todate = form.get("to", "")
    
    # Check that we have a suitable date range for the selected granularity
    df = None
    dt = None
    
    if fromdate or todate:
        if not fromdate or not todate:
            raise ValueError("When using 'from' or 'to', both need to be specified.")

    # Get date range of selected corpora
    corpus_info = info({"corpus": ",".join(corpora)})
    corpora_copy = corpora.copy()

    if fromdate and todate:
        df = datetime.datetime.strptime(fromdate, "%Y%m%d%H%M%S")
        dt = datetime.datetime.strptime(todate, "%Y%m%d%H%M%S")
        
        # Remove corpora not within selected date span
        for c in corpus_info["corpora"]:
            firstdate = corpus_info["corpora"][c]["info"].get("FirstDate")
            lastdate = corpus_info["corpora"][c]["info"].get("LastDate")
            if firstdate and lastdate:
                firstdate = datetime.datetime.strptime(firstdate, "%Y-%m-%d %H:%M:%S")
                lastdate = datetime.datetime.strptime(lastdate, "%Y-%m-%d %H:%M:%S")
                
                if not (firstdate <= dt and lastdate >= df):
                    corpora.remove(c)
                
    else:
        # If no date range was provided, use whole date range of the selected corpora
        for c in corpus_info["corpora"]:
            firstdate = corpus_info["corpora"][c]["info"].get("FirstDate")
            lastdate = corpus_info["corpora"][c]["info"].get("LastDate")
            if firstdate and lastdate:
                firstdate = datetime.datetime.strptime(firstdate, "%Y-%m-%d %H:%M:%S")
                lastdate = datetime.datetime.strptime(lastdate, "%Y-%m-%d %H:%M:%S")
                
                if not df or firstdate < df:
                    df = firstdate
                if not dt or lastdate > dt:
                    dt = lastdate
    
    if df and dt:
        maxpoints = 3600
        
        if granularity == "y":
            add = relativedelta(years=maxpoints)
        elif granularity == "m":
            add = relativedelta(months=maxpoints)
        elif granularity == "d":
            add = relativedelta(days=maxpoints)
        elif granularity == "h":
            add = relativedelta(hours=maxpoints)
        elif granularity == "n":
            add = relativedelta(minutes=maxpoints)
        elif granularity == "s":
            add = relativedelta(seconds=maxpoints)
        
        if dt > (df + add):
            raise ValueError("The date range is too large for the selected granularity. Use 'to' and 'from' to limit the range.")
    
    
    strategy = int(form.get("strategy", "1"))
    
    use_cache = bool(not form.get("cache", "").lower() == "false" and config.CACHE_DIR)
    
    if granularity in "hns":
        groupby = ["text_datefrom", "text_timefrom", "text_dateto", "text_timeto"]
    else:
        groupby = ["text_datefrom", "text_dateto"]

    result = {"corpora": {}}
    corpora_sizes = {}
    
    ns = Namespace()
    total_rows = [[] for i in range(len(subcqp))] + [[]]
    ns.total_size = 0
    
    ns.progress_count = 0
    if incremental:
        print '"progress_corpora": [%s],' % ('"' + '", "'.join(corpora) + '"' if corpora else "")

    with futures.ThreadPoolExecutor(max_workers=config.PARALLEL_THREADS) as executor:
        future_query = dict((executor.submit(count_query_worker, corpus, cqp, groupby, [], form), corpus) for corpus in corpora)
        
        def anti_timeout(queue):
            for future in futures.as_completed(future_query):
                corpus = future_query[future]
                if future.exception() is not None:
                    if not "Can't find attribute ``text_datefrom''" in future.exception().message:
                        raise CQPError(future.exception())
                else:
                    lines, _, corpus_size = future.result()

                    corpora_sizes[corpus] = corpus_size
                    ns.total_size += corpus_size
                    
                    query_no = 0
                    for line in lines:
                        if line == END_OF_LINE:
                            query_no += 1
                            continue
                        count, values = line.lstrip().split(" ", 1)
                        values = values.strip(" ")
                        if granularity in "hns":
                            datefrom, timefrom, dateto, timeto = values.split("\t")
                            # Only use the value from the first token
                            timefrom = timefrom.split(" ")[0]
                            timeto = timeto.split(" ")[0]
                        else:
                            datefrom, dateto = values.split("\t")
                            timefrom = ""
                            timeto = ""
                            
                        # Only use the value from the first token
                        datefrom = datefrom.split(" ")[0]
                        dateto = dateto.split(" ")[0]
                        
                        total_rows[query_no].append((corpus, datefrom + timefrom, dateto + timeto, int(count)))
                    
                    if incremental:
                        queue.put('"progress_%d": "%s",' % (ns.progress_count, corpus))
                        ns.progress_count += 1
            queue.put("DONE")
        
        anti_timeout_loop(anti_timeout)

    corpus_timedata = timespan({"corpus": list(corpora), "granularity": granularity, "from": fromdate, "to": todate, "cache": str(use_cache), "strategy": str(strategy)})
    search_timedata = []
    search_timedata_combined = []
    for total_row in total_rows:
        temp = timespan_calculator(total_row, granularity=granularity, strategy=strategy)
        search_timedata.append(temp["corpora"])
        search_timedata_combined.append(temp["combined"])
       
    for corpus in corpora:
                
        corpus_stats = [{"absolute": defaultdict(int),
                        "relative": defaultdict(float),
                        "sums": {"absolute": 0, "relative": 0.0}} for i in range(len(subcqp) + 1)]
        
        basedates = dict([(date, None if corpus_timedata["corpora"][corpus][date] == 0 else 0) for date in corpus_timedata["corpora"].get(corpus, {})])
        
        for i, s in enumerate(search_timedata):
        
            prevdate = None
            for basedate in sorted(basedates):
                if not basedates[basedate] == prevdate:
                    corpus_stats[i]["absolute"][basedate] = basedates[basedate]
                    corpus_stats[i]["relative"][basedate] = basedates[basedate]
                prevdate = basedates[basedate]

            for row in s.get(corpus, {}).iteritems():
                date, count = row
                corpus_date_size = float(corpus_timedata["corpora"].get(corpus, {}).get(date, 0))
                if corpus_date_size > 0.0:
                    corpus_stats[i]["absolute"][date] += count
                    corpus_stats[i]["relative"][date] += (count / corpus_date_size * 1000000)
                    corpus_stats[i]["sums"]["absolute"] += count
                    corpus_stats[i]["sums"]["relative"] += (count / corpus_date_size * 1000000)
            
            if subcqp and i > 0:
                corpus_stats[i]["cqp"] = subcqp[i - 1]
            
        result["corpora"][corpus] = corpus_stats if len(corpus_stats) > 1 else corpus_stats[0]

    total_stats = [{"absolute": defaultdict(int),
                    "relative": defaultdict(float),
                    "sums": {"absolute": 0, "relative": 0.0}} for i in range(len(subcqp) + 1)]

    basedates = dict([(date, None if corpus_timedata["combined"][date] == 0 else 0) for date in corpus_timedata.get("combined", {})])

    for i, s in enumerate(search_timedata_combined):
    
        prevdate = None
        for basedate in sorted(basedates):
            if not basedates[basedate] == prevdate:
                total_stats[i]["absolute"][basedate] = basedates[basedate]
                total_stats[i]["relative"][basedate] = basedates[basedate]
            prevdate = basedates[basedate]
            
        if s:
            for row in s.iteritems():
                date, count = row
                combined_date_size = float(corpus_timedata["combined"].get(date, 0))
                if combined_date_size > 0.0:
                    total_stats[i]["absolute"][date] += count
                    total_stats[i]["relative"][date] += (count / combined_date_size * 1000000) if combined_date_size else 0
                    total_stats[i]["sums"]["absolute"] += count

        total_stats[i]["sums"]["relative"] = total_stats[i]["sums"]["absolute"] / float(ns.total_size) * 1000000 if ns.total_size > 0 else 0.0
        if subcqp and i > 0:
            total_stats[i]["cqp"] = subcqp[i - 1]

    result["combined"] = total_stats if len(total_stats) > 1 else total_stats[0]
    
    # Add zero values for the corpora we removed because of the selected date span
    for corpus in corpora_copy.difference(corpora):
        result["corpora"][corpus] = {"absolute": 0, "relative": 0.0, "sums": {"absolute": 0, "relative": 0.0}}
    
    if "debug" in form:
        result["DEBUG"] = {"cqp": cqp}
        
    return result


def count_query_worker(corpus, cqp, groupby, ignore_case, form, expand_prequeries=True):

    optimize = True
    cqpextra = {}
    
    if "cut" in form:
        cqpextra["cut"] = form.get("cut")

    # Within
    defaultwithin = form.get("defaultwithin", "")
    within = form.get("within", defaultwithin)
    if within:
        if ":" in within:
            within = dict(x.split(":") for x in within.split(","))
            within = within.get(corpus, defaultwithin)
        cqpextra["within"] = within

    subcqp = None
    if isinstance(cqp[-1], list):
        subcqp = cqp[-1]
        cqp = cqp[:-1]

    cmd = ["%s;" % corpus]
    for i, c in enumerate(cqp):
        cqpextra_temp = cqpextra.copy()
        pre_query = i+1 < len(cqp)
        
        if pre_query and expand_prequeries:
            cqpextra_temp["expand"] = "to " + cqpextra["within"]
        
        if optimize:
            cmd += query_optimize(c, cqpextra_temp, find_match=(not pre_query))
        else:
            cmd += make_query(make_cqp(c, cqpextra_temp))
        
        if pre_query:
            cmd += ["Last;"]
    
    cmd += ["size Last;"]
    cmd += ["info; .EOL.;"]
    
    # TODO: Match targets in a better way
    if any("@[" in x for x in cqp):
        match = "target"
    else:
        match = "match .. matchend"

    cmd += ["""tabulate Last %s > "| sort | uniq -c | sort -nr";""" % ", ".join("%s %s%s" % (match, g, " %c" if g in ignore_case else "") for g in groupby)]
    
    if subcqp:
        cmd += ["mainresult=Last;"]
        if "expand" in cqpextra_temp:
            del cqpextra_temp["expand"]
        for c in subcqp:
            cmd += [".EOL.;"]
            cmd += ["mainresult;"]
            cmd += query_optimize(c, cqpextra_temp, find_match=True)
            cmd += ["""tabulate Last %s > "| sort | uniq -c | sort -nr";""" % ", ".join("match .. matchend %s" % g for g in groupby)]

    #else:
        
    cmd += ["exit;"]
    
    lines = runCQP(cmd, form)

    # skip CQP version
    lines.next()

    # size of the query result
    nr_hits = int(lines.next())

    # Get corpus size
    for line in lines:
        if line.startswith("Size:"):
            _, corpus_size = line.split(":")
            corpus_size = int(corpus_size.strip())
        elif line == END_OF_LINE:
            break

    return lines, nr_hits, corpus_size


def count_query_worker_simple(corpus, cqp, groupby, ignore_case, form, expand_prequeries=True):

    lines = list(run_cwb_scan(corpus, groupby, form))
    nr_hits = 0

    for i in range(len(lines)):
        c, v = lines[i].split("\t")
        # Convert result to the same format as the regular CQP count
        lines[i] = "%s %s" % (c, v)
        nr_hits += int(c)
    
    # Corpus size equals number of hits since we count all tokens
    corpus_size = nr_hits
    return lines, nr_hits, corpus_size


def loglike(form):
    """Runs a log-likelihood comparison on two queries.
    
    The required parameters are
     - set1_cqp: the first CQP query
     - set2_cqp: the second CQP query
     - set1_corpus: the corpora for the first query
     - set2_corpus: the corpora for the second query
     - groupby: what positional or structural attribute to use for comparison

    The optional parameters are
     - ignore_case: ignore case when comparing
     - max: maxium number of results per set
       (default: 15)
    """

    import math

    def expected(total, wordtotal, sumtotal):
        """ The expected is that the words are uniformely distributed over the corpora. """
        return wordtotal * (float(total) / sumtotal)

    def compute_loglike((wf1, tot1), (wf2, tot2)):
        """ Computes log-likelihood for a single pair. """
        e1 = expected(tot1, wf1 + wf2, tot1 + tot2)
        e2 = expected(tot2, wf1 + wf2, tot1 + tot2)
        (l1, l2) = (0, 0)
        if wf1 > 0:
            l1 = wf1 * math.log(wf1 / e1)
        if wf2 > 0:
            l2 = wf2 * math.log(wf2 / e2)
        loglike = 2 * (l1 + l2)
        return round(loglike, 2)

    def critical(val):
        # 95th percentile; 5% level; p < 0.05; critical value = 3.84
        # 99th percentile; 1% level; p < 0.01; critical value = 6.63
        # 99.9th percentile; 0.1% level; p < 0.001; critical value = 10.83
        # 99.99th percentile; 0.01% level; p < 0.0001; critical value = 15.13
        return val > 15.13

    def select(w, ls):
        """ Splits annotations on | and returns as list. If annotation is missing, returns the word instead. """
        #    for c in w:
        #        if not (c.isalpha() or (len(w) > 1 and c in '-:')):
        #            return []
        xs = [l for l in ls.split('|') if len(l) > 0]
        return xs or [w]
        
    def wf_frequencies(texts):
        freqs = []
        for (name, text) in texts:
            d = defaultdict(int)  # Lemgram-frekvens
            tc = 0  # Totalt antal token
            for w in [r for s in text for (w, a) in s for r in select(w, a['lex'])]:
                tc += 1
                d[w] += 1
            freqs.append((name, d, tc))
        return freqs

    def reference_material(filename):
        d = defaultdict(int)
        tot = 0
        with codecs.open(filename, encoding='utf8') as f:
            for l in f:
                (wf, msd, lemgram, comp, af, rf) = l[:-1].split('\t')
                for l in select(wf, lemgram):
                    tot += int(af)  # Totalt antal token
                    d[l] += int(af)  # Lemgram-frekvens
        return (d, tot)

    def compute_list(d1, tot1, ref, reftot):
        """ Computes log-likelyhood for lists. """
        result = []
        all_w = set(d1.keys()).union(set(ref.keys()))
        for w in all_w:
            ll = compute_loglike((d1.get(w, 0), tot1), (ref.get(w, 0), reftot))
            result.append((ll, w))
        result.sort(reverse=True)
        return result

    def compute_ll_stats(ll_list, count, sets):
        """ Calculates max, min, average, and truncates word list. """
        tot = len(ll_list)
        new_list = []
        
        set1count, set2count = 0, 0
        for ll_w in ll_list:
            ll, w = ll_w
            
            if (sets[0]["freq"].get(w) and not sets[1]["freq"].get(w)) or sets[0]["freq"].get(w) and (sets[0]["freq"].get(w, 0) / (sets[0]["total"] * 1.0)) > (sets[1]["freq"].get(w, 0) / (sets[1]["total"] * 1.0)):
                set1count += 1
                if set1count <= count or not count:
                    new_list.append((ll * -1, w))
            else:
                set2count += 1
                if set2count <= count or not count:
                    new_list.append((ll, w))
            
            if count and (set1count >= count and set2count >= count):
                break

        nums = [ll for (ll, _) in ll_list]
        return (
            new_list,
            round(sum(nums) / float(tot), 2) if tot else 0.0,
            min(nums) if nums else 0.0,
            max(nums) if nums else 0.0
        )

    assert_key("set1_cqp", form, r"", True)
    assert_key("set2_cqp", form, r"", True)
    assert_key("set1_corpus", form, r"", True)
    assert_key("set2_corpus", form, r"", True)
    assert_key("groupby", form, IS_IDENT, True)
    assert_key("ignore_case", form, IS_IDENT)
    assert_key("max", form, IS_NUMBER, False)
    
    maxresults = int(form.get("max", 15))
    
    set1 = form.get("set1_corpus").upper()
    if isinstance(set1, basestring):
        set1 = set1.split(QUERY_DELIM)
    set1 = set(set1)
    set2 = form.get("set2_corpus").upper()
    if isinstance(set2, basestring):
        set2 = set2.split(QUERY_DELIM)
    set2 = set(set2)
    
    corpora = set1.union(set2)
    check_authentication(corpora)
    
    same_cqp = form.get("set1_cqp") == form.get("set2_cqp")
    
    # If same CQP for both sets, handle as one query for better performance
    if same_cqp:
        form["cqp"] = form.get("set1_cqp")
        form["corpus"] = ",".join(corpora)
        count_result = count(form)
        
        sets = [{"total": 0, "freq": defaultdict(int)}, {"total": 0, "freq": defaultdict(int)}]
        for i, cset in enumerate((set1, set2)):
            for corpus in cset:
                sets[i]["total"] += count_result["corpora"][corpus]["sums"]["absolute"]
                if len(cset) == 1:
                    sets[i]["freq"] = count_result["corpora"][corpus]["absolute"]
                else:
                    for w, f in count_result["corpora"][corpus]["absolute"].iteritems():
                        sets[i]["freq"][w] += f
        
    else:
        form1, form2 = form.copy(), form.copy()
        form1["corpus"] = ",".join(set1)
        form1["cqp"] = form.get("set1_cqp")
        form2["corpus"] = ",".join(set2)
        form2["cqp"] = form.get("set2_cqp")
        count_result = [count(form1), count(form2)]
    
        sets = [{}, {}]
        for i, cset in enumerate((set1, set2)):
            count_result_temp = count_result if same_cqp else count_result[i]
            sets[i]["total"] = count_result_temp["total"]["sums"]["absolute"]
            sets[i]["freq"] = count_result_temp["total"]["absolute"]
    
    ll_list = compute_list(sets[0]["freq"], sets[0]["total"], sets[1]["freq"], sets[1]["total"])
    (ws, avg, mi, ma) = compute_ll_stats(ll_list, maxresults, sets)
    
    result = {"loglike": {}, "average": avg, "set1": {}, "set2": {}}

    for (ll, w) in ws:
        result["loglike"][w] = ll
        result["set1"][w] = sets[0]["freq"].get(w, 0)
        result["set2"][w] = sets[1]["freq"].get(w, 0)

    return result


################################################################################
# LEMGRAM_COUNT
################################################################################

def lemgram_count(form):
    """Returns lemgram statistics per corpus.

    The required parameters are
     - lemgram: list of lemgrams

    The optional parameters are
     - corpus: the CWB corpus/corpora
       (default: all corpora)
     - count: what to count (lemgram/prefix/suffix)
       (default: lemgram)
    """

    assert_key("lemgram", form, r"", True)
    assert_key("corpus", form, IS_IDENT)
    assert_key("count", form, r"(lemgram|prefix|suffix)")
    
    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = set(corpora) if corpora else set()
    
    check_authentication(corpora)
    
    lemgram = form.get("lemgram")
    if isinstance(lemgram, basestring):
        lemgram = lemgram.split(QUERY_DELIM)
    lemgram = set(lemgram)
    
    count = form.get("count", "lemgram")
    if isinstance(count, basestring):
        count = count.split(QUERY_DELIM)
    count = set(count)
       
    counts = {"lemgram": "freq",
              "prefix": "freq_prefix",
              "suffix": "freq_suffix"}
    
    sums = " + ".join("SUM(%s)" % counts[c] for c in count)
    
    conn = MySQLdb.connect(use_unicode=True,
                           charset="utf8",
                           **config.DBCONNECT)
    # Get Unicode objects even with collation utf8_bin; see
    # <http://stackoverflow.com/questions/9522413/mysql-python-collation-issue-how-to-force-unicode-datatype>
    conn.converter[MySQLdb.constants.FIELD_TYPE.VAR_STRING] = [
        (None, conn.string_decoder)]
    cursor = conn.cursor()
    
    lemgram_sql = " lemgram IN (%s)" % "%s" % ", ".join(conn.escape(l).decode("utf-8") for l in lemgram)
    corpora_sql = " AND corpus IN (%s)" % ", ".join("%s" % conn.escape(c) for c in corpora) if corpora else ""
    
    sql = "SELECT lemgram, " + sums + " FROM lemgram_index WHERE" + lemgram_sql + corpora_sql + " GROUP BY lemgram COLLATE utf8_bin;"
    
    result = {}
    cursor.execute(sql)

    for row in cursor:
        # We need this check here, since a search for "hår" also returns "här" and "har".
        if row[0].encode("utf-8") in lemgram and int(row[1]) > 0:
            result[row[0]] = int(row[1])
    
    return result


################################################################################
# TIMESPAN
################################################################################

def timespan(form):
    """Calculates timespan information for corpora.
    The time information is retrieved from the database.

    The required parameters are
     - corpus: the CWB corpus/corpora

    The optional parameters are
     - granularity: granularity of result (y = year, m = month, d = day, h = hour, n = minute, s = second)
       (default: year)
     - spans: if set to true, gives results as spans instead of points
       (default: points)
     - combined: include combined results
       (default: true)
     - per_corpus: include results per corpus
       (default: true)
     - from: from this date and time, on the format 20150513063500 or 2015-05-13 06:35:00 (times optional) (optional)
     - to: to this date and time (optional)
    """
    
    assert_key("corpus", form, IS_IDENT, True)
    assert_key("granularity", form, r"[ymdhnsYMDHNS]")
    assert_key("spans", form, r"(true|false)")
    assert_key("combined", form, r"(true|false)")
    assert_key("per_corpus", form, r"(true|false)")
    assert_key("strategy", form, r"^[123]$")
    assert_key("from", form, r"^(\d{8}\d{6}?|\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?)$")
    assert_key("to", form, r"^(\d{8}\d{6}?|\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?)$")
    
    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = sorted(set(corpora))
    
    use_cache = bool(not form.get("cache", "").lower() == "false" and config.CACHE_DIR)
    
    #check_authentication(corpora)

    granularity = form.get("granularity", "y").lower()
    spans = (form.get("spans", "").lower() == "true")
    combined = (not form.get("combined", "").lower() == "false")
    per_corpus = (not form.get("per_corpus", "").lower() == "false")
    strategy = int(form.get("strategy", "1"))
    fromdate = form.get("from")
    todate = form.get("to")
    
    if fromdate or todate:
        if not fromdate or not todate:
            raise ValueError("When using 'from' or 'to', both need to be specified.")
    
    shorten = {"y": 4, "m": 7, "d": 10, "h": 13, "n": 16, "s": 19}

    unique_id = os.getenv("UNIQUE_ID")
    
    if use_cache:
        cachedata = (granularity,
                     spans,
                     combined,
                     per_corpus,
                     fromdate,
                     todate,
                     sorted(corpora))
        cachefile = os.path.join(config.CACHE_DIR, "timespan_%s" % (get_hash(cachedata)))
        
        if os.path.exists(cachefile):
            with open(cachefile, "rb") as f:
                result = cPickle.load(f)
                if "debug" in form:
                    result.setdefault("DEBUG", {})
                    result["DEBUG"]["cache_read"] = True
                return result

    conn = MySQLdb.connect(use_unicode=True,
                           charset="utf8",
                           cursorclass=MySQLdb.cursors.SSCursor,
                           **config.DBCONNECT)
    cursor = conn.cursor()

    ns = {}
    
    def anti_timeout_fun(queue):
        corpora_sql = "(%s)" % ", ".join("%s" % conn.escape(c) for c in corpora)

        fromto = ""
    
        if strategy == 1:
            if fromdate and todate:
                fromto = " AND ((datefrom >= %s AND dateto <= %s) OR (datefrom <= %s AND dateto >= %s))" % (conn.escape(fromdate), conn.escape(todate), conn.escape(fromdate), conn.escape(todate))
        elif strategy == 2:
            if todate:
                fromto += " AND datefrom <= %s" % conn.escape(todate)
            if fromdate:
                fromto = " AND dateto >= %s" % conn.escape(fromdate)
        elif strategy == 3:
            if fromdate:
                fromto = " AND datefrom >= %s" % conn.escape(fromdate)
            if todate:
                fromto += " AND dateto <= %s" % conn.escape(todate)

        # We do the granularity truncation and summation in the DB query if we can (depending on strategy), since it's much faster than doing it afterwards
        
        timedata_corpus = "timedata_date" if granularity in ("y", "m", "d") else "timedata"
        if strategy == 1:
            # We need the full dates for this strategy, so no truncating the results
            sql = "SELECT corpus, datefrom AS df, dateto AS dt, SUM(tokens) FROM " + timedata_corpus + " WHERE corpus IN " + corpora_sql + fromto + " GROUP BY corpus, df, dt ORDER BY NULL;"
        else:
            sql = "SELECT corpus, LEFT(datefrom, " + str(shorten[granularity]) + ") AS df, LEFT(dateto, " + str(shorten[granularity]) + ") AS dt, SUM(tokens) FROM " + timedata_corpus + " WHERE corpus IN " + corpora_sql + fromto + " GROUP BY corpus, df, dt ORDER BY NULL;"
        cursor.execute(sql)
        
        ns["result"] = timespan_calculator(cursor, granularity=granularity, spans=spans, combined=combined, per_corpus=per_corpus, strategy=strategy)

        if use_cache:
            tmpfile = "%s.%s" % (cachefile, unique_id)
            with open(tmpfile, "w") as f:
                cPickle.dump(ns["result"], f, protocol=-1)
            os.rename(tmpfile, cachefile)
        
        if "debug" in form:
            ns["result"].setdefault("DEBUG", {})
            ns["result"]["DEBUG"]["cache_saved"] = True

        queue.put("DONE")

    anti_timeout_loop(anti_timeout_fun)

    return ns["result"]


def timespan_calculator(timedata, granularity="y", spans=False, combined=True, per_corpus=True, strategy=1):
    """Calculates timespan information for corpora.

    The required parameters are
     - timedata: the time data to be processed

    The optional parameters are
     - granularity: granularity of result (y = year, m = month, d = day)
       (default: year)
     - spans: give results as spans instead of points
       (default: points)
     - combined: include combined results
       (default: true)
     - per_corpus: include results per corpus
       (default: true)
    """
    
    import datetime
    from dateutil.relativedelta import relativedelta

    gs = {"y": 4, "m": 6, "d": 8, "h": 10, "n": 12, "s": 14}

    def strftime(dt, fmt):
        """Python datetime.strftime < 1900 workaround, taken from https://gist.github.com/2000837"""

        TEMPYEAR = 9996  # We need to use a leap year to support feb 29th

        if dt.year < 1900:
            # create a copy of this datetime, just in case, then set the year to
            # something acceptable, then replace that year in the resulting string
            tmp_dt = datetime.datetime(TEMPYEAR, dt.month, dt.day,
                                       dt.hour, dt.minute,
                                       dt.second, dt.microsecond,
                                       dt.tzinfo)
            
            tmp_fmt = fmt
            tmp_fmt = re.sub('(?<!%)((?:%%)*)(%y)', '\\1\x11\x11', tmp_fmt, re.U)
            tmp_fmt = re.sub('(?<!%)((?:%%)*)(%Y)', '\\1\x12\x12\x12\x12', tmp_fmt, re.U)
            tmp_fmt = tmp_fmt.replace(str(TEMPYEAR), '\x13\x13\x13\x13')
            tmp_fmt = tmp_fmt.replace(str(TEMPYEAR)[-2:], '\x14\x14')
            
            result = tmp_dt.strftime(tmp_fmt)
            
            if '%c' in fmt:
                # local datetime format - uses full year but hard for us to guess where.
                result = result.replace(str(TEMPYEAR), str(dt.year))
            
            result = result.replace('\x11\x11', str(dt.year)[-2:])
            result = result.replace('\x12\x12\x12\x12', str(dt.year))
            result = result.replace('\x13\x13\x13\x13', str(TEMPYEAR))
            result = result.replace('\x14\x14', str(TEMPYEAR)[-2:])
                
            return result
            
        else:
            return dt.strftime(fmt)

    def plusminusone(date, value, df, negative=False):
        date = "0" + date if len(date) % 2 else date  # Handle years with three digits
        d = datetime.datetime.strptime(date, df)
        if negative:
            d = d - value
        else:
            d = d + value
        return int(strftime(d, df))

    def shorten(date, g):
        date = str(date)
        alt = 1 if len(date) % 2 else 0  # Handle years with three digits
        return int(date[:gs[g]-alt])
        
    points = not spans
    
    if granularity == "y":
        df = "%Y"
        add = relativedelta(years=1)
    elif granularity == "m":
        df = "%Y%m"
        add = relativedelta(months=1)
    elif granularity == "d":
        df = "%Y%m%d"
        add = relativedelta(days=1)
    elif granularity == "h":
        df = "%Y%m%d%H"
        add = relativedelta(hours=1)
    elif granularity == "n":
        df = "%Y%m%d%H%M"
        add = relativedelta(minutes=1)
    elif granularity == "s":
        df = "%Y%m%d%H%M%S"
        add = relativedelta(seconds=1)
    
    rows = defaultdict(list)
    nodes = defaultdict(set)

    datemin = "00000101" if granularity in ("y", "m", "d") else "00000101000000"
    datemax = "99991231" if granularity in ("y", "m", "d") else "99991231235959"

    for row in timedata:
        # corpus, datefrom, dateto, tokens
        corpus = row[0]
        datefrom = filter(lambda x: x.isdigit(), str(row[1])) if row[1] else ""
        if datefrom == "0" * len(datefrom):
            datefrom = ""
        dateto = filter(lambda x: x.isdigit(), str(row[2])) if row[2] else ""
        if dateto == "0" * len(dateto):
            dateto = ""
        datefrom_short = shorten(datefrom, granularity) if datefrom else ""
        dateto_short = shorten(dateto, granularity) if dateto else ""
        
        if strategy == 1:
            # Some overlaps permitted
            # (t1 >= t1' AND t2 <= t2') OR (t1 <= t1' AND t2 >= t2')
            if not datefrom_short == dateto_short:
                if not datefrom[gs[granularity]:] == datemin[gs[granularity]:]:
                    # Add 1 to datefrom_short
                    datefrom_short = plusminusone(str(datefrom_short), add, df)
                    
                if not dateto[gs[granularity]:] == datemax[gs[granularity]:]:
                    # Subtract 1 from dateto_short
                    dateto_short = plusminusone(str(dateto_short), add, df, negative=True)
                
                # Check that datefrom is still before dateto
                if not datefrom < dateto:
                    continue
        elif strategy == 2:
            # All overlaps permitted
            # t1 <= t2' AND t2 >= t1'
            pass
        elif strategy == 3:
            # Strict matching. No overlaps tolerated.
            # t1 >= t1' AND t2 <= t2'
            
            if not datefrom_short == dateto_short:
                continue

                
        tokens = int(row[3])

        r = {"datefrom": datefrom_short, "dateto": dateto_short, "corpus": corpus, "tokens": tokens}
        if combined:
            rows["__combined__"].append(r)
            nodes["__combined__"].add(("f", datefrom_short))
            nodes["__combined__"].add(("t", dateto_short))
        if per_corpus:
            rows[corpus].append(r)
            nodes[corpus].add(("f", datefrom_short))
            nodes[corpus].add(("t", dateto_short))
    
    corpusnodes = dict((k, sorted(v, key=lambda x: (x[1], x[0]))) for k, v in nodes.iteritems())

    result = {}
    if per_corpus:
        result["corpora"] = {}
    if combined:
        result["combined"] = {}
    
    for corpus, nodes in corpusnodes.iteritems():
        data = defaultdict(int)
    
        for i in range(0, len(nodes) - 1):
            start = nodes[i]
            end = nodes[i + 1]
            if start[0] == "t":
                start = plusminusone(str(start[1]), add, df) if not start == "" else ""
                if start == end[1] and end[0] == "f":
                    continue
            else:
                start = start[1]
            if end[1] == "":
                end = ""
            else:
                end = end[1] if end[0] == "t" else plusminusone(str(end[1]), add, df, True)
            
            if points and not start == "":
                data["%d" % start] = 0
                
            for row in rows[corpus]:
                if row["datefrom"] <= start and row["dateto"] >= end:
                    if points:
                        data[str(start)] += row["tokens"]
                    else:
                        data["%d - %d" % (start, end) if start else ""] += row["tokens"]
            if points and not end == "":
                data["%d" % plusminusone(str(end), add, df, False)] = 0
        
        if combined and corpus == "__combined__":
            result["combined"] = data
        else:
            result["corpora"][corpus] = data
    
    return result


################################################################################
# RELATIONS
################################################################################

def relations(form):
    """Calculates word picture data.

    The required parameters are
     - corpus: the CWB corpus/corpora
     - word: a word or lemgram to lookup

    The optional parameters are
     - min: cut off results with a frequency lower than this
       (default: no cut-off)
     - max: maximum number of results
       (default: 15)
     - type: type of search (word/lemgram)
       (default: word)
     - incremental: incrementally report the progress while executing
       (default: false)
    """
    
    import math

    assert_key("corpus", form, IS_IDENT, True)
    assert_key("word", form, "", True)
    assert_key("type", form, r"(word|lemgram)", False)
    assert_key("min", form, IS_NUMBER, False)
    assert_key("max", form, IS_NUMBER, False)
    assert_key("incremental", form, r"(true|false)")
    
    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.upper().split(QUERY_DELIM)
    corpora = set(corpora)
    
    check_authentication(corpora)
    
    incremental = form.get("incremental", "").lower() == "true"
    
    use_cache = bool(not form.get("cache", "").lower() == "false" and config.CACHE_DIR)
    word = form.get("word")
    search_type = form.get("type", "")
    minfreq = form.get("min")
    sortby = form.get("sortby", "mi")
    maxresults = int(form.get("max", 15))
    minfreqsql = " AND freq >= %s" % minfreq if minfreq else ""
    
    checksum_data = (sorted(corpora),
                     word,
                     search_type,
                     minfreq,
                     sortby,
                     maxresults)
    checksum = get_hash(checksum_data)
    
    if use_cache and os.path.exists(os.path.join(config.CACHE_DIR, "wordpicture_" + checksum)):
        with open(os.path.join(config.CACHE_DIR, "wordpicture_" + checksum), "r") as cachefile:
            result = json.load(cachefile)
            if "debug" in form:
                result.setdefault("DEBUG", {})
                result["DEBUG"]["cache_read"] = True
            return result
    
    result = {}

    conn = MySQLdb.connect(use_unicode=True,
                           charset="utf8",
                           **config.DBCONNECT)
    # Get Unicode objects even with collation utf8_bin; see
    # <http://stackoverflow.com/questions/9522413/mysql-python-collation-issue-how-to-force-unicode-datatype>
    conn.converter[MySQLdb.constants.FIELD_TYPE.VAR_STRING] = [
        (None, conn.string_decoder)]
    cursor = conn.cursor()
    cursor.execute("SET @@session.long_query_time = 1000;")
    
    # Get available tables
    cursor.execute("SHOW TABLES LIKE '" + config.DBTABLE + "_%';")
    tables = set(x[0] for x in cursor)
    logging.debug("tables = %s", tables)
    # Filter out corpora which doesn't exist in database
    corpora = filter(lambda x: config.DBTABLE + "_" + x.upper() in tables, corpora)
    if not corpora:
        return {}
    
    selects = []
    
    if search_type == "lemgram":
        lemgram_sql = conn.escape(word).decode("utf-8")
        
        for corpus in corpora:
            corpus_table = config.DBTABLE + "_" + corpus.upper()

            selects.append((corpus.upper(), u"(SELECT S1.string AS head, S1.pos AS headpos, F.rel, S2.string AS dep, S2.pos AS deppos, S2.stringextra AS depextra, F.freq, R.freq AS rel_freq, HR.freq AS head_rel_freq, DR.freq AS dep_rel_freq, " + conn.string_literal(corpus.upper()) + u" AS corpus, F.id " +
                            u"FROM `" + corpus_table + "_strings` AS S1, `" + corpus_table + "_strings` AS S2, `" + corpus_table + "` AS F, `" + corpus_table + "_rel` AS R, `" + corpus_table + "_head_rel` AS HR, `" + corpus_table + "_dep_rel` AS DR " +
                            u"WHERE S1.string = " + lemgram_sql + " COLLATE utf8_bin AND F.head = S1.id AND S2.id = F.dep " +
                            minfreqsql +
                            u"AND F.bfhead = 1 AND F.bfdep = 1 AND F.rel = R.rel AND F.head = HR.head AND F.rel = HR.rel AND F.dep = DR.dep AND F.rel = DR.rel)"
                            ))
            selects.append((None, u"(SELECT S1.string AS head, S1.pos AS headpos, F.rel, S2.string AS dep, S2.pos AS deppos, S2.stringextra AS depextra, F.freq, R.freq AS rel_freq, HR.freq AS head_rel_freq, DR.freq AS dep_rel_freq, " + conn.string_literal(corpus.upper()) + u" AS corpus, F.id " +
                            u"FROM `" + corpus_table + "_strings` AS S1, `" + corpus_table + "_strings` AS S2, `" + corpus_table + "` AS F, `" + corpus_table + "_rel` AS R, `" + corpus_table + "_head_rel` AS HR, `" + corpus_table + "_dep_rel` AS DR " +
                            u"WHERE S2.string = " + lemgram_sql + " COLLATE utf8_bin AND F.dep = S2.id AND S1.id = F.head " +
                            minfreqsql +
                            u"AND F.bfhead = 1 AND F.bfdep = 1 AND F.rel = R.rel AND F.head = HR.head AND F.rel = HR.rel AND F.dep = DR.dep AND F.rel = DR.rel)"
                            ))
    else:
        word_sql = conn.escape(word).decode("utf-8")
        word = word.decode("utf-8")
        
        for corpus in corpora:
            corpus_table = config.DBTABLE + "_" + corpus.upper()
    
            selects.append((corpus.upper(), u"(SELECT S1.string AS head, S1.pos AS headpos, F.rel, S2.string AS dep, S2.pos AS deppos, S2.stringextra AS depextra, F.freq, R.freq AS rel_freq, HR.freq AS head_rel_freq, DR.freq AS dep_rel_freq, " + conn.string_literal(corpus.upper()) + u" AS corpus, F.id " +
                            u"FROM `" + corpus_table + "_strings` AS S1, `" + corpus_table + "_strings` AS S2, `" + corpus_table + "` AS F, `" + corpus_table + "_rel` AS R, `" + corpus_table + "_head_rel` AS HR, `" + corpus_table + "_dep_rel` AS DR " +
                            u"WHERE S1.string = " + word_sql + " AND F.head = S1.id AND F.wfhead = 1 AND S2.id = F.dep " +
                            minfreqsql +
                            u"AND F.rel = R.rel AND F.head = HR.head AND F.rel = HR.rel AND F.dep = DR.dep AND F.rel = DR.rel)"
                            ))
            selects.append((None, u"(SELECT S1.string AS head, S1.pos AS headpos, F.rel, S2.string AS dep, S2.pos AS deppos, S2.stringextra AS depextra, F.freq, R.freq AS rel_freq, HR.freq AS head_rel_freq, DR.freq AS dep_rel_freq, " + conn.string_literal(corpus.upper()) + u" AS corpus, F.id " +
                            u"FROM `" + corpus_table + "_strings` AS S1, `" + corpus_table + "_strings` AS S2, `" + corpus_table + "` AS F, `" + corpus_table + "_rel` AS R, `" + corpus_table + "_head_rel` AS HR, `" + corpus_table + "_dep_rel` AS DR " +
                            u"WHERE S2.string = " + word_sql + " AND F.dep = S2.id AND F.wfdep = 1 AND S1.id = F.head " +
                            minfreqsql +
                            u"AND F.rel = R.rel AND F.head = HR.head AND F.rel = HR.rel AND F.dep = DR.dep AND F.rel = DR.rel)"
                            ))

    cursor_result = []
    if incremental:
        print '"progress_corpora": [%s],' % ('"' + '", "'.join(corpora) + '"' if corpora else "")
        progress_count = 0
        for sql in selects:
            logging.debug("sql = %s", sql[1])
            cursor.execute(sql[1])
            cursor_result.extend(list(cursor))
            if sql[0]:
                print '"progress_%d": {"corpus": "%s"},' % (progress_count, sql[0])
                progress_count += 1
    else:    
        sql = u" UNION ALL ".join(x[1] for x in selects)
        logging.debug("sql = %s", sql)
        cursor.execute(sql)
        cursor_result = cursor
    
    rels = {}
    counter = {}
    freq_rel = {}
    freq_head_rel = {}
    freq_rel_dep = {}
    
    # 0     1        2    3    4       5         6     7         8              9             10      11
    # head, headpos, rel, dep, deppos, depextra, freq, rel_freq, head_rel_freq, dep_rel_freq, corpus, id
    
    for row in cursor_result:
        #       head    headpos
        head = (row[0], row[1])
        #      dep     deppos  depextra
        dep = (row[3], row[4], row[5])
        rels.setdefault((head, row[2], dep), {"freq": 0, "source": set()})
        rels[(head, row[2], dep)]["freq"] += row[6]
        rels[(head, row[2], dep)]["source"].add("%s:%d" % (row[10], row[11]))
        #                   rel          corpus   rel        rel_freq
        freq_rel.setdefault(row[2], {})[(row[10], row[2])] = row[7]
        freq_head_rel.setdefault((head, row[2]), {})[(row[10], row[2])] = row[8]
        freq_rel_dep.setdefault((row[2], dep), {})[(row[10], row[2])] = row[9]
    
    # Calculate MI
    for rel in rels:
        f_rel = sum(freq_rel[rel[1]].values())
        f_head_rel = sum(freq_head_rel[(rel[0], rel[1])].values())
        f_rel_dep = sum(freq_rel_dep[(rel[1], rel[2])].values())
        rels[rel]["mi"] = rels[rel]["freq"] * math.log((f_rel * rels[rel]["freq"]) / (f_head_rel * f_rel_dep * 1.0), 2)
    
    sortedrels = sorted(rels.items(), key=lambda x: (x[0][1], x[1][sortby]), reverse=True)
    
    logging.debug("sortedrels = %s", sortedrels)

    for rel in sortedrels:
        counter.setdefault((rel[0][1], "h"), 0)
        counter.setdefault((rel[0][1], "d"), 0)
        if search_type == "lemgram" and rel[0][0][0] == word:
            counter[(rel[0][1], "h")] += 1
            if maxresults and counter[(rel[0][1], "h")] > maxresults:
                continue
        else:
            counter[(rel[0][1], "d")] += 1
            if maxresults and counter[(rel[0][1], "d")] > maxresults:
                continue

        r = {"head": rel[0][0][0],
             "headpos": rel[0][0][1],
             "rel": rel[0][1],
             "dep": rel[0][2][0],
             "deppos": rel[0][2][1],
             "depextra": rel[0][2][2],
             "freq": rel[1]["freq"],
             "mi": rel[1]["mi"],
             "source": list(rel[1]["source"])
             }
        result.setdefault("relations", []).append(r)
    
    cursor.close()
    conn.close()
    
    if use_cache:
        unique_id = os.getenv("UNIQUE_ID")
        cachefilename = os.path.join(config.CACHE_DIR, "wordpicture_" + checksum)
        tmpfile = "%s.%s" % (cachefilename, unique_id)
    
        with open(tmpfile, "w") as cachefile:
            json.dump(result, cachefile)
        os.rename(tmpfile, cachefilename)
        
        if "debug" in form:
            result.setdefault("DEBUG", {})
            result["DEBUG"]["cache_saved"] = True
    
    return result


################################################################################
# RELATIONS_SENTENCES
################################################################################

def relations_sentences(form):
    """Executes a CQP query to find sentences with a given relation from a word picture.

    The required parameters are
     - corpus: the CWB corpus/corpora
     - head: head of relation
     - rel: relation

    The optional parameters are
     - dep: dependent of relation
     - depextra: dependent prefix
     - start, end: which result rows that should be returned
     - show
     - show_struct
    """

    from copy import deepcopy
    
    assert_key("source", form, "", True)
    assert_key("start", form, IS_NUMBER, False)
    assert_key("end", form, IS_NUMBER, False)
    
    # TODO (Jyrki Niemi): Use uniquify_corpora() to optionally
    # preserve the order of corpora in source. We now probably need
    # here a separate list for storing the original order;
    # uniquify_corpora() should probably be used below where sorted()
    # is now used.
    temp_source = form.get("source")
    if isinstance(temp_source, basestring):
        temp_source = temp_source.split(QUERY_DELIM)
    source = defaultdict(set)
    for s in temp_source:
        c, i = s.split(":")
        source[c].add(i)
    
    check_authentication(source.keys())
    
    start = int(form.get("start", "0"))
    end = int(form.get("end", "99"))
    shown = form.get("show", "word")
    shown_structs = form.get("show_struct", [])
    if isinstance(shown_structs, basestring):
        shown_structs = shown_structs.split(QUERY_DELIM)
    shown_structs = set(shown_structs)
    
    querystarttime = time.time()

    conn = MySQLdb.connect(**config.DBCONNECT)
    # Get Unicode objects even with collation utf8_bin; see
    # <http://stackoverflow.com/questions/9522413/mysql-python-collation-issue-how-to-force-unicode-datatype>
    conn.converter[MySQLdb.constants.FIELD_TYPE.VAR_STRING] = [
        (None, conn.string_decoder)]
    cursor = conn.cursor()
    cursor.execute("SET @@session.long_query_time = 1000;")
    selects = []
    counts = []
    
    # Get available tables
    cursor.execute("SHOW TABLES LIKE '" + config.DBTABLE + "_%';")
    tables = set(x[0] for x in cursor)
    # Filter out corpora which doesn't exist in database
    source = sorted(filter(lambda x: config.DBTABLE + "_" + x[0].upper() in tables, source.iteritems()))
    if not source:
        return {}
    corpora = [x[0] for x in source]
    
    for s in source:
        corpus, ids = s
        ids = [conn.escape(i) for i in ids]
        ids_list = "(" + ", ".join(ids) + ")"
        
        corpus_table_sentences = config.DBTABLE + "_" + corpus.upper() + "_sentences"
        
        selects.append(u"(SELECT S.sentence, S.start, S.end, " + conn.string_literal(corpus.upper()) + u" AS corpus " +
                       u"FROM `" + corpus_table_sentences + u"` as S " +
                       u" WHERE S.id IN " + ids_list + u")"
                       )
        counts.append(u"(SELECT " + conn.string_literal(corpus.upper()) + u" AS corpus, COUNT(*) FROM `" + corpus_table_sentences + "` as S WHERE S.id IN " + ids_list + u")")

    sql_count = u" UNION ALL ".join(counts)
    cursor.execute(sql_count)
    
    corpus_hits = {}
    for row in cursor:
        corpus_hits[row[0]] = int(row[1])
    
    sql = u" UNION ALL ".join(selects) + (u" LIMIT %d, %d" % (start, end - 1))
    cursor.execute(sql)
    
    querytime = time.time() - querystarttime
    corpora_dict = {}
    for row in cursor:
        # 0 sentence, 1 start, 2 end, 3 corpus
        corpora_dict.setdefault(row[3], {}).setdefault(row[0], []).append((row[1], row[2]))

    cursor.close()
    
    total_hits = sum(corpus_hits.values())

    if not corpora_dict:
        return {"hits": 0}
    
    cqpstarttime = time.time()
    result = {}
    
    for corp, sids in sorted(corpora_dict.items(), key=lambda x: x[0]):
        cqp = u'<sentence_id="%s"> []* </sentence_id> within sentence' % "|".join(set(sids.keys()))
        q = {"cqp": cqp,
             "corpus": corp,
             "start": "0",
             "end": str(end - start),
             "show_struct": ["sentence_id"] + list(shown_structs),
             "defaultcontext": "1 sentence"}
        if shown:
            q["show"] = shown
        result_temp = query(q)

        # Loop backwards since we might be adding new items
        for i in range(len(result_temp["kwic"]) - 1, -1, -1):
            s = result_temp["kwic"][i]
            sid = s["structs"]["sentence_id"]
            r = sids[sid][0]
            s["match"]["start"] = min(map(int, r)) - 1
            s["match"]["end"] = max(map(int, r))
            
            # If the same relation appears more than once in the same sentence,
            # append copies of the sentence as separate results
            for r in sids[sid][1:]:
                s2 = deepcopy(s)
                s2["match"]["start"] = min(map(int, r)) - 1
                s2["match"]["end"] = max(map(int, r))
                result_temp["kwic"].insert(i + 1, s2)
    
        result.setdefault("kwic", []).extend(result_temp["kwic"])

    result["hits"] = total_hits
    result["corpus_hits"] = corpus_hits
    result["corpus_order"] = corpora
    result["querytime"] = querytime
    result["cqptime"] = time.time() - cqpstarttime
    
    return result


################################################################################
# NAMES
################################################################################

def names(form):
    """List names occurring in texts by category.

    The required parameters are
     - corpus: the CWB corpus/corpora
     - cqp

    The optional parameters are
     - groups
     - min: cut off results with a frequency lower than this
       (default: no cut-off)
     - max: maximum number of results
       (default: 15)
     - incremental: incrementally report the progress while executing
       (default: false)
    """
    
    assert_key("corpus", form, IS_IDENT, True)
    assert_key("cqp", form, r"", True)

    assert_key("groups", form, r"", False)
    assert_key("min", form, IS_NUMBER, False)
    assert_key("max", form, IS_NUMBER, False)
    assert_key("incremental", form, r"(true|false)")

    corpora = form.get("corpus")
    if isinstance(corpora, basestring):
        corpora = corpora.split(QUERY_DELIM)
    corpora = set(corpora)
    
    optimize = True
    
    check_authentication(corpora)
    
    incremental = form.get("incremental", "").lower() == "true"
    
    use_cache = bool(not form.get("cache", "").lower() == "false" and
                     config.CACHE_DIR)
    cqp = [form.get("cqp").decode('utf-8')]
    minfreq = int(form.get("min", 1))
    maxresults = int(form.get("max", 15))
    groups = form.get("groups")

    # minfreqsql = " AND freq >= %s" % minfreq if minfreq else ""
    
    checksum_data = ("".join(sorted(corpora)),
                     cqp,
                     minfreq,
                     groups,
                     maxresults)
    checksum = get_hash(checksum_data)
    
    result = {}

    if (use_cache and
        os.path.exists(os.path.join(config.CACHE_DIR, "names_" + checksum))):
        with open(os.path.join(
                config.CACHE_DIR, "names_" + checksum), "r") as cachefile:
            result = json.load(cachefile)
            if "debug" in form:
                result.setdefault("DEBUG", {})
                result["DEBUG"]["cache_read"] = True
            return result
    
    conn = MySQLdb.connect(use_unicode=True,
                           charset="utf8",
                           **config.DBCONNECT)
    # Get Unicode objects even with collation utf8_bin; see
    # <http://stackoverflow.com/questions/9522413/mysql-python-collation-issue-how-to-force-unicode-datatype>
    conn.converter[MySQLdb.constants.FIELD_TYPE.VAR_STRING] = [
        (None, conn.string_decoder)]
    cursor = conn.cursor()
    cursor.execute("SET @@session.long_query_time = 1000;")
    
    # Get available tables
    cursor.execute("SHOW TABLES LIKE '" + config.DBTABLE_NAMES + "_%';")
    tables = set(x[0] for x in cursor)
    logging.debug("tables: %s", tables)
    # Filter out corpora which do not exist in database
    corpora = filter(lambda x: config.DBTABLE_NAMES + "_" + x.upper() in tables,
                     corpora)
    logging.debug('corpora: %s', corpora)
    if not corpora:
        return {}

    (defaultwithin, within_all) = _get_default_and_corpus_specific_param(
        form, "within", "defaultwithin", "sentence")
    (default_nameswithin, nameswithin_all) = \
        _get_default_and_corpus_specific_param(
        form, "nameswithin", "default_nameswithin", "text_id")

    if incremental:
        print '"progress_corpora": [%s],' % ('"' + '", "'.join(corpora) + '"'
                                             if corpora else "")
        progress_count = 0

    name_freqs = {}
    cqp = cqp[0]

    for corpus in corpora:

        within = within_all.get(corpus, defaultwithin)
        nameswithin = nameswithin_all.get(corpus, default_nameswithin)
        text_ids = _names_find_matching_texts(
            form, corpus, cqp, within, nameswithin)
        if not text_ids:
            continue

        corpus_table = config.DBTABLE_NAMES + "_" + corpus.upper()
        # Use literal single quotes, since conn.escape() does not seem
        # to quote strings as expected. Why?
        text_ids_in = ",".join("'" + text_id + "'" for text_id in text_ids)
        # logging.debug("text_ids: %s", text_ids)
        # logging.debug("text_ids_in: %s", text_ids_in)

        select = u"""SELECT NS.name, NS.category, N.name_id, sum(N.freq)
                     FROM `{corptbl}` as N, `{corptbl}_strings` as NS
                     WHERE N.name_id = NS.id and N.text_id IN ({text_ids})
                     GROUP BY NS.id;""".format(
            corptbl=corpus_table,
            text_ids=text_ids_in)
        logging.debug('select: %s', select)

        cursor.execute(select)

        if incremental:
            print '"progress_%d": {"corpus": "%s"},' % (progress_count, corpus)
            progress_count += 1

        for row in cursor:
            logging.debug('row: %s', row)
            name, cat, name_id, freq = row
            cat_freqs = name_freqs.setdefault(cat, {})
            prev_freq, prev_source = cat_freqs.get(name, (0, []))
            cat_freqs[name] = (prev_freq + int(freq),
                               (prev_source + [corpus + ":" + str(name_id)]))

    cursor.close()
    conn.close()

    # An empty name_groups indicates that no names were found with the
    # query, whereas a completely empty result indicates that the
    # selected corpora have no name information.
    if not name_freqs:
        return {"name_groups": []}

    name_cats = sorted(name_freqs.keys())
    logging.debug('name_freqs: %s', name_freqs)
    if groups:
        groups = groups.split(',')
    else:
        groups = name_cats
    logging.debug('groups: %s', groups)

    result_names = []
    for group in groups:
        group_result = {"group": group}
        namelist = []
        for cat in name_cats:
            if re.match(group, cat):
                for name, freq_src in name_freqs[cat].iteritems():
                    freq, source = freq_src
                    if freq >= minfreq:
                        namelist.append((freq, name, cat, source))
        namelist.sort(reverse=True)
        logging.debug('namelist: %s', namelist)
        if maxresults > 0:
            namelist = namelist[:maxresults]
        group_result["names"] = [{"name": name,
                                  "category": cat,
                                  "freq": freq,
                                  "source": source}
                                 for freq, name, cat, source in namelist]
        result_names.append(group_result)
    result = {"name_groups": result_names}

    if use_cache:
        unique_id = os.getenv("UNIQUE_ID")
        cachefilename = os.path.join(config.CACHE_DIR, "names_" + checksum)
        tmpfile = "%s.%s" % (cachefilename, unique_id)

        with open(tmpfile, "w") as cachefile:
            json.dump(result, cachefile)
        os.rename(tmpfile, cachefilename)

        if "debug" in form:
            result.setdefault("DEBUG", {})
            result["DEBUG"]["cache_saved"] = True

    return result


def _get_default_and_corpus_specific_param(form, param_name,
                                           default_param_name, default_value):
    """Get default and possible corpus-specific form parameter values.

    Get both the default value and possible corpus-specific values for
    parameters with a default and corpus-specific variant, such as
    "defaultwithin" and "within".

    Returns a tuple containing the default value and a dictionary of
    corpus-specific values with corpus names as keys.

    A helper function used by names and names_sentences.
    """

    default = form.get(default_param_name, default_value)
    corpus_specific = form.get(param_name, default)
    if corpus_specific and ":" in corpus_specific:
        corpus_specific = dict(
            (x.split(":")[0], x) for x in corpus_specific.split(","))
    else:
        corpus_specific = {}
    return (default, corpus_specific)


def _names_find_matching_texts(form, corpus, cqp, within, nameswithin):
    """Find the text ids with matches for a CQP query.

    A helper function used by names and names_sentences.
    """

    cqpextra = {}
    if within:
        cqpextra["within"] = within
    cmd = ["%s;" % corpus]
    cmd += ["set Context 0 words;"]
    cmd += ["set PrintStructures \"%s\";" % nameswithin]
    cmd += ["show -cpos;"]
    cmd += make_query(make_cqp(cqp, cqpextra))
    cmd += ["size Last;"]
    cmd += ["cat Last;"]
    cmd += ["exit;"]
    lines = runCQP(cmd, form)

    # skip CQP version
    lines.next()
    # size of the query result
    nr_hits = int(lines.next())
    logging.debug('nr_hits: %s', nr_hits)

    text_ids = []
    for line in lines:
        logging.debug('line: %s', line)
        # Extract text_id from the concordance lines, which should
        # be of the following form because of the option settings
        # above: <textid_attr_name text_id>: <matching words>
        line_words = line.split(" ")
        if len(line_words) > 1 and line_words[0][1:] == nameswithin:
            text_id = line.split(" ")[1].rstrip(">:")
            if not text_ids or text_id != text_ids[-1]:
                text_ids.append(text_id)
    logging.debug('text_ids: %s', text_ids)
    return text_ids


################################################################################
# NAMES_SENTENCES
################################################################################

def names_sentences(form):
    """Executes a CQP query to find sentences with a given relation from a word picture.

    The required parameters are
     - source: the CWB corpus/corpora with name ids

    The optional parameters are
     - start, end: which result rows that should be returned
     - show
     - show_struct
     - cqp
     - defaultwithin, within
     - default_nameswithin, nameswithin
    """

    from copy import deepcopy
    
    assert_key("source", form, "", True)
    assert_key("start", form, IS_NUMBER, False)
    assert_key("end", form, IS_NUMBER, False)
    
    # TODO (Jyrki Niemi): Use uniquify_corpora() to optionally
    # preserve the order of corpora in source. We now probably need
    # here a separate list for storing the original order;
    # uniquify_corpora() should probably be used below where sorted()
    # is now used.
    temp_source = form.get("source")
    if isinstance(temp_source, basestring):
        temp_source = temp_source.split(QUERY_DELIM)
    source = defaultdict(set)
    for s in temp_source:
        c, i = s.split(":")
        source[c].add(i)
    
    check_authentication(source.keys())
    
    start = int(form.get("start", "0"))
    end = int(form.get("end", "99"))
    shown = form.get("show", "word")
    shown_structs = form.get("show_struct", [])
    if isinstance(shown_structs, basestring):
        shown_structs = shown_structs.split(QUERY_DELIM)
    shown_structs = set(shown_structs)
    
    querystarttime = time.time()

    conn = MySQLdb.connect(**config.DBCONNECT)
    # Get Unicode objects even with collation utf8_bin; see
    # <http://stackoverflow.com/questions/9522413/mysql-python-collation-issue-how-to-force-unicode-datatype>
    conn.converter[MySQLdb.constants.FIELD_TYPE.VAR_STRING] = [
        (None, conn.string_decoder)]
    cursor = conn.cursor()
    cursor.execute("SET @@session.long_query_time = 1000;")
    selects = []
    counts = []
    
    # Get available tables
    cursor.execute("SHOW TABLES LIKE '" + config.DBTABLE_NAMES + "_%';")
    tables = set(x[0] for x in cursor)
    # Filter out corpora which doesn't exist in database
    source = sorted(filter(
            lambda x: config.DBTABLE_NAMES + "_" + x[0].upper() in tables,
            source.iteritems()))
    if not source:
        return {}
    corpora = [x[0] for x in source]
    
    cqp = form.get("cqp", "").decode('utf-8')
    if cqp:
        (defaultwithin, within_all) = _get_default_and_corpus_specific_param(
            form, "within", "defaultwithin", "sentence")
        (default_nameswithin, nameswithin_all) = \
            _get_default_and_corpus_specific_param(
            form, "nameswithin", "default_nameswithin", "text_id")

    for s in source:
        corpus, ids = s
        ids_list = ", ".join(conn.escape(i) for i in ids)

        if cqp:
            within = within_all.get(corpus, defaultwithin)
            nameswithin = nameswithin_all.get(corpus, default_nameswithin)
            text_ids = _names_find_matching_texts(
                form, corpus, cqp, within, nameswithin)
            if not text_ids:
                continue
            # Use literal single quotes, since conn.escape() does not
            # seem to quote strings as expected. Why?
            text_ids_list = ",".join("'" + i + "'" for i in text_ids)
            text_ids_sql = "AND S.text_id in ({text_ids})".format(
                text_ids=text_ids_list)
        else:
            text_ids_sql = ""

        corpus_table_sentences = (
            config.DBTABLE_NAMES + "_" + corpus.upper() + "_sentences")

        sql_params = dict(corpus_u=conn.string_literal(corpus.upper()),
                          corptbl=corpus_table_sentences,
                          name_ids=ids_list,
                          text_ids_sql=text_ids_sql)
        selects.append(
            u"""(SELECT S.sentence_id, S.start, S.end, {corpus_u} AS corpus
                 FROM `{corptbl}` as S
                 WHERE S.name_id IN ({name_ids}) {text_ids_sql})"""
            .format(**sql_params))
        counts.append(
            u"""(SELECT {corpus_u} AS corpus, COUNT(*)
                 FROM `{corptbl}` as S
                 WHERE S.name_id IN ({name_ids}) {text_ids_sql})"""
            .format(**sql_params))

    sql_count = u" UNION ALL ".join(counts)
    logging.debug('sql_count: %s', sql_count)
    cursor.execute(sql_count)
    
    corpus_hits = {}
    for row in cursor:
        corpus_hits[row[0]] = int(row[1])
    
    sql = u" UNION ALL ".join(selects) + (u" LIMIT %d, %d" % (start, end - 1))
    logging.debug('sql: %s', sql)
    cursor.execute(sql)
    
    querytime = time.time() - querystarttime
    corpora_dict = {}
    for row in cursor:
        # 0 sentence, 1 start, 2 end, 3 corpus
        corpora_dict.setdefault(row[3], {}).setdefault(row[0], []).append((row[1], row[2]))

    cursor.close()
    
    total_hits = sum(corpus_hits.values())

    if not corpora_dict:
        return {"hits": 0}
    
    (defaultcontext, context_all) = _get_default_and_corpus_specific_param(
        form, "context", "defaultcontext", "1 sentence")
    cqpstarttime = time.time()
    result = {}
    
    for corp, sids in sorted(corpora_dict.items(), key=lambda x: x[0]):
        cqp = (u'<sentence_id="%s"> []* </sentence_id> within sentence'
               % "|".join(set(sids.keys())))
        q = {"cqp": cqp,
             "corpus": corp,
             "start": "0",
             "end": str(end - start),
             "show_struct": ["sentence_id"] + list(shown_structs),
             "defaultcontext": defaultcontext}
        context = context_all.get(corpus)
        if context:
            q["context"] = context
        if shown:
            q["show"] = shown
        result_temp = query(q)

        # Loop backwards since we might be adding new items
        for i in range(len(result_temp["kwic"]) - 1, -1, -1):
            s = result_temp["kwic"][i]
            sid = s["structs"]["sentence_id"]
            r = sids[sid][0]
            s["match"]["start"] = min(map(int, r)) - 1
            s["match"]["end"] = max(map(int, r))
            
            # If the same name appears more than once in the same sentence,
            # append copies of the sentence as separate results
            for r in sids[sid][1:]:
                s2 = deepcopy(s)
                s2["match"]["start"] = min(map(int, r)) - 1
                s2["match"]["end"] = max(map(int, r))
                result_temp["kwic"].insert(i + 1, s2)
    
        result.setdefault("kwic", []).extend(result_temp["kwic"])

    result["hits"] = total_hits
    result["corpus_hits"] = corpus_hits
    result["corpus_order"] = corpora
    result["querytime"] = querytime
    result["cqptime"] = time.time() - cqpstarttime
    
    return result


################################################################################
# Helper functions

def parse_cqp(cqp):
    """ Tries to parse a CQP query, returning identified tokens and a
    boolean indicating partial failure if True."""
    
    sections = []
    last_start = 0
    in_bracket = 0
    in_quote = False
    in_curly = False
    quote_type = ""
    
    for i in range(len(cqp)):
        c = cqp[i]
        
        if c in '"\'':
            if in_quote and quote_type == c and not cqp[i - 1] == "\\":
                in_quote = False
                if not in_bracket:
                    sections.append([last_start, i])
            elif not in_quote:
                in_quote = True
                quote_type = c
                if not in_bracket:
                    last_start = i
        elif c == "[":
            if not in_bracket and not in_quote:
                last_start = i
                in_bracket = True
        elif c == "]":
            if in_bracket and not in_quote:
                sections.append([last_start, i])
                in_bracket = False
        elif c == "{" and not in_bracket and not in_quote:
            in_curly = True
        elif c == "}" and not in_bracket and not in_quote and in_curly:
            in_curly = False
            sections[-1][1] = i

    last_section = (0, 0)
    sections.append([len(cqp), len(cqp)])
    tokens = []
    rest = False

    for section in sections:
        if last_section[1] < section[0]:
            if cqp[last_section[1]+1:section[0]].strip():
                rest = True
        last_section = section
        if cqp[section[0]:section[1]+1]:
            tokens.append(cqp[section[0]:section[1]+1])
    
    return (tokens, rest)


def make_cqp(cqp, cqpextra):
    """ Combine CQP query and extra options. """
    if config.ENCODED_SPECIAL_CHARS:
        cqp = encode_special_chars_in_query(cqp)
    order = ("within", "cut", "expand")
    for i in sorted(cqpextra.items(), key=lambda x: order.index(x[0])):
        cqp += " %s %s" % i
    return cqp


def make_query(cqp):
    """Create web-safe commands for a CQP query.
    """
    querylock = random.randrange(10**8, 10**9)
    return ["set QueryLock %s;" % querylock,
            "%s;" % cqp,
            "unlock %s;" % querylock]


def translate_undef(s):
    """Translate None to '__UNDEF__'."""
    return None if s == "__UNDEF__" else s


def get_hash(values):
    """Get a hash for a list of values."""
    return str(zlib.crc32(";".join(x.encode("UTF-8") if isinstance(x, unicode) else str(x) for x in values)))


class CQPError(Exception):
    pass


class KorpAuthenticationError(Exception):
    pass


class Namespace:
    pass


def runCQP(command, form, executable=config.CQP_EXECUTABLE, registry=config.CWB_REGISTRY, attr_ignore=False):
    """Call the CQP binary with the given command, and the CGI form.
    Yield one result line at the time, disregarding empty lines.
    If there is an error, raise a CQPError exception.
    """
    env = os.environ.copy()
    env["LC_COLLATE"] = config.LC_COLLATE
    if config.TMPDIR:
        env["TMPDIR"] = config.TMPDIR
    encoding = form.get("encoding", config.CQP_ENCODING)
    if not isinstance(command, basestring):
        command = "\n".join(command)
    command = "set PrettyPrint off;\n" + command
    # Log the CQP query if the log level is DEBUG
    logging.debug("CQP: %s", repr(command))
    command = command.encode(encoding)
    process = Popen([executable, "-c", "-r", registry],
                    stdin=PIPE, stdout=PIPE, stderr=PIPE, env=env)
    reply, error = process.communicate(command)
    if error:
        # remove newlines from the error string:
        error = re.sub(r"\s+", r" ", error)
        # keep only the first CQP error (the rest are consequences):
        error = re.sub(r"^CQP Error: *", r"", error)
        error = re.sub(r" *(CQP Error:).*$", r"", error)
        # Ignore certain errors: 1) "show +attr" for unknown attr, 2) querying unknown structural attribute, 3) calculating statistics for empty results
        if not (attr_ignore and "No such attribute:" in error) and not "is not defined for corpus" in error and not "cl->range && cl->size > 0" in error and not "neither a positional/structural attribute" in error:
            raise CQPError(error)
    for line in reply.decode(encoding, errors="ignore").splitlines():
        if line:
            yield line


def run_cwb_scan(corpus, attrs, form, executable=config.CWB_SCAN_EXECUTABLE, registry=config.CWB_REGISTRY):
    """Call the cwb-scan-corpus binary with the given arguments.
    Yield one result line at the time, disregarding empty lines.
    If there is an error, raise a CQPError exception.
    """
    encoding = form.get("encoding", config.CQP_ENCODING)
    process = Popen([executable, "-q", "-r", registry, corpus] + attrs,
                    stdout=PIPE, stderr=PIPE)
    reply, error = process.communicate()
    if error:
        # remove newlines from the error string:
        error = re.sub(r"\s+", r" ", error)
        # Ignore certain errors: 1) "show +attr" for unknown attr, 2) querying unknown structural attribute, 3) calculating statistics for empty results
        raise CQPError(error)
    for line in reply.decode(encoding, errors="ignore").splitlines():
        if line and len(line) < 65536:
            yield line


def show_attributes():
    """Command sequence for returning the corpus attributes."""
    return ["show cd; .EOL.;"]


def read_attributes(lines):
    """Read the CQP output from the show_attributes() command."""
    attrs = {'p': [], 's': [], 'a': []}
    for line in lines:
        if line == END_OF_LINE:
            break
        (typ, name, _rest) = (line + " X").split(None, 2)
        attrs[typ[0]].append(name)
    return attrs


def uniquify_corpora(corpora):
    """Uniquify a list of corpora, either preserving order or sorted."""
    if config.SORT_CORPORA:
        # The original version
        return sorted(set(corpora))
    else:
        return uniquify_list(corpora)


def uniquify_list(lst):
    """Uniquify a list, preserving order."""
    # Source:
    # http://stackoverflow.com/questions/480214/how-do-you-remove-duplicates-from-a-list-in-python-whilst-preserving-order
    # In Python 2.7+, we could use collections.OrderedDict.
    seen = set()
    # Avoid attribute lookup in the loop
    seen_add = seen.add
    # seen.add ony has a side-effect and returns None
    return [elem for elem in lst if elem not in seen and not seen_add(elem)]


def replace_substrings(s, mapping):
    """Replace substrings in s according to mapping (a sequence of
    pairs (string, replacement): replace each string with the
    corresponding replacement.
    """
    for (s1, repl) in mapping:
        s = s.replace(s1, repl)
    return s


def encode_special_chars(s):
    """Encode the special characters in s."""
    return replace_substrings(s, SPECIAL_CHAR_ENCODE_MAP)


def decode_special_chars(s):
    """Decode the encoded special characters in s."""
    return replace_substrings(s, SPECIAL_CHAR_DECODE_MAP)


def encode_special_chars_in_query(cqp):
    """Encode the special characters in the double-quoted substrings
    of the CQP query cqp.
    """
    # Allow empty strings within double quotes, so that the regexp
    # does not match from an ending double quote of a quoted empty
    # string to the next double quote.
    return re.sub(r'("(?:[^\\"]|\\.)*")',
                  lambda mo: encode_special_chars(mo.group(0)), cqp)


def encode_special_chars_in_queries(cqp_list):
    """Encode the special characters in the double-quoted substrings
    of the list of CQP queryies cqp_list.
    """
    return [encode_special_chars_in_query(cqp) for cqp in cqp_list]


def read_corpora_regexp_file(fname):
    """Return a compiled regular expression of the disjunction of the
    (corpus name) regexps listed in the file 'fname', with each
    non-empty, non-comment line as one disjunct. The regexps are
    uppercased. If the argument 'fname' or the file itself is empty or
    if an IOError occurs, return None.
    """
    corpus_name_regexps = []
    if fname:
        try:
            with open(fname, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        corpus_name_regexps.append(line.upper())
        except IOError:
            pass
    if corpus_name_regexps:
        re_str = ('^(?:'
                  + '|'.join('(?:' + regexp + ')'
                             for regexp in corpus_name_regexps)
                  + ')$')
        return re.compile(re_str)
    else:
        return None


def assert_key(key, form, regexp, required=False):
    """Check that the value of the attribute 'key' in the CGI form
    matches the specification 'regexp'. If 'required' is True, then
    the key has to be in the form.
    """
    value = form.get(key, "")
    if value and not isinstance(value, list):
        value = [value]
    if required and not value:
        raise KeyError("Key is required: %s" % key)
    if not all(re.match(regexp, x) for x in value):
        pattern = regexp.pattern if hasattr(regexp, "pattern") else regexp
        raise ValueError("Value(s) for key %s do(es) not match /%s/: %s" % (key, pattern, value))


def print_header():
    """Prints the JSON header."""
    print "Content-Type: application/json"
    print "Access-Control-Allow-Origin: *"
    print "Access-Control-Allow-Methods: GET, POST"
    print "Access-Control-Allow-Headers: Authorization, Content-Type"
    print


def print_object(obj, form):
    """Prints an object in JSON format.
    The CGI form can contain optional parameter 'indent'
    which change the output format.
    """
    try:
        indent = int(form.get("indent"))
        out = json.dumps(obj, sort_keys=True, indent=indent)
        out = out[1:-1] if form.get("incremental", "").lower() == "true" else out
        print out,
    except:
        out = json.dumps(obj, separators=(",", ":"))
        out = out[1:-1] if form.get("incremental", "").lower() == "true" else out
        print out,


def authenticate(_=None):
    """Authenticates a user against config.AUTH_SERVER.
    """
    remote_user = cgi.os.environ.get('REMOTE_USER')
    auth_header = cgi.os.environ.get('HTTP_AUTH_HEADER')

    logging.debug("cgi.os.environ: %s", cgi.os.environ)
    if remote_user:
        # In which order should we check the affiliation variables?
        affiliation = (cgi.os.environ.get('HTTP_UNSCOPED_AFFILIATION') or
                       cgi.os.environ.get('HTTP_AFFILIATION') or '')

        entitlement = (cgi.os.environ.get('HTTP_ENTITLEMENT') or '')

        postdata = {
            "remote_user": remote_user,
            "affiliation": affiliation.lower(),
            "entitlement": entitlement
        }
    elif auth_header and auth_header.startswith("Basic "):
        user, pw = base64.b64decode(auth_header[6:]).split(":")

        postdata = {
            "username": user,
            "password": pw,
            "checksum": md5.new(user + pw + config.AUTH_SECRET).hexdigest()
        }
    else:
        return dict(username=None)

    try:
        contents = urllib2.urlopen(config.AUTH_SERVER, urllib.urlencode(postdata)).read()
        auth_response = json.loads(contents)
    except urllib2.HTTPError:
        raise KorpAuthenticationError("Could not contact authentication server.")
    except ValueError:
        raise KorpAuthenticationError("Invalid response from authentication server.")
    except:
        raise KorpAuthenticationError("Unexpected error during authentication.")

    # Response contains username and corpora, or username=None
    return auth_response.get('permitted_resources', {})


def get_protected_corpora():
    """Return a list of protected corpora listed in the auth database."""
    protected = []
    try:
        conn = MySQLdb.connect(use_unicode=True,
                               charset="utf8",
                               **config.AUTH_DBCONNECT)
        cursor = conn.cursor()
        cursor.execute('''
        select corpus from auth_license
        where license = 'ACA' or license = 'RES'
        ''')
        protected = [ corpus for corpus, in cursor ]
        cursor.close()
        conn.close()
    except AttributeError:
        pass
    return protected


def check_authentication(corpora):
    """Raises an exception if any of the corpora are protected and the
    user is not authorized to access them (by config.AUTH_SERVER)."""

    protected = get_protected_corpora()
    logging.debug("check_auth: corpora: %s; protected: %s", corpora, protected)

    if protected:
        auth = authenticate()
        authorized = auth.get('corpora', [])
        unauthorized = [ corpus for corpus_or_pair in corpora
                         for corpus in corpus_or_pair.split('|')
                         if corpus in protected
                         and corpus not in authorized ]
        logging.debug("check_auth: auth: %s; authorized: %s; unauthorized: %s",
                      auth, authorized, unauthorized)

        if unauthorized:
            raise KorpAuthenticationError("You do not have access to the following corpora: %s" % ", ".join(unauthorized))


class CustomTracebackException(Exception):
    def __init__(self, exception):
        self.exception = exception
        

def anti_timeout_loop(f, args=None, timeout=90):
    """ Used in places where the script otherwise might timeout. Keeps the CGI alive by printing
    out whitespace. """
    q = Queue()
    
    def error_catcher(g, *args, **kwargs):
        try:
            g(*args, **kwargs)
        except Exception, e:
            q.put(sys.exc_info())
    
    args = args or []
    args.append(q)
    t = threading.Thread(target=error_catcher, args=[f] + args)
    t.start()

    while True:
        try:
            msg = q.get(True, timeout=timeout)
            if msg == "DONE":
                break
            elif isinstance(msg, tuple):
                raise CustomTracebackException(msg)
            else:
                print msg
        except Empty:
            print " ",


if __name__ == "__main__":
    main()


