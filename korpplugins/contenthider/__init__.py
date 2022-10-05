
"""
korpplugins.contenthider

Hide marked structures in KWIC results by replacing their attribute values with
specified fixed strings.
"""


# TODO (if found useful):
# - Allow completely removing hidden structures from the result (configurable)
# - Allow hiding results from hidden structures in statistics, probably by
#   adding a term to the CQP query (configurable)
# - Hide hidden structure names from the results of corpus_info


import korppluginlib


# See config.py.template for further documentation of the configuration
# variables
pluginconf = korppluginlib.get_plugin_config(
    # Structural attribute (annotation) names marking a structure as hidden and
    # not to be shown to the user in query results
    HIDDEN_STRUCT_NAMES = ["text__removed"],
    # The value with which to replace positional attribute values within
    # structures marked as hidden in query results
    HIDDEN_VALUE_POS_ATTR = "_",
    # The value with which to replace structural attribute annotation values
    # within structures marked as hidden in query results
    HIDDEN_VALUE_STRUCT_ATTR = "removed",
    # Set the match position to 0 in query results within hidden structures
    HIDE_MATCH_POS = True,
)


class QueryContentHider(korppluginlib.KorpCallbackPlugin):

    """Callback plugin class for hiding the content of marked query results"""

    def applies_to(self, request):
        """Apply hiding only to KWIC results."""
        return (pluginconf.HIDDEN_STRUCT_NAMES
                and request.endpoint in ("query", "relations_sentences"))

    def filter_args(self, request, args):
        """Add to show_struct attributes names marking a structure hidden."""
        args["show_struct"] = (
            args.get("show_struct", "")
            + ",".join([""] + pluginconf.HIDDEN_STRUCT_NAMES)
        ).lstrip(",")
        return args

    def filter_result(self, request, result):
        """Hide (mask) attributes of structures marked as hidden."""
        for row_num, kwic_row in enumerate(result.get("kwic", [])):
            linestructs = kwic_row.get("structs", {})
            # Hide (mask) results that are within structures listed in
            # pluginconf.HIDDEN_STRUCT_NAMES by replacing actual attribute values
            # with fixed values. Note that the structure name exists in
            # linestructs in the results from all corpora having it, so we need
            # to check that its value is not None, which indicates that the
            # structure is actually marked as hidden.
            if any((hidden in linestructs and linestructs[hidden] is not None)
                   for hidden in pluginconf.HIDDEN_STRUCT_NAMES):
                # Replace positional attribute values with
                # pluginconf.HIDDEN_VALUE_POS_ATTR
                if pluginconf.HIDDEN_VALUE_POS_ATTR is not None:
                    kwic_row["tokens"] = [
                        dict((key, (pluginconf.HIDDEN_VALUE_POS_ATTR
                                    if key != "structs" else val))
                             for key, val in token.items())
                        for token in kwic_row.get("tokens", [])]
                # Replace structural attribute annotation values with
                # pluginconf.HIDDEN_VALUE_STRUCT_ATTR
                if pluginconf.HIDDEN_VALUE_STRUCT_ATTR is not None:
                    kwic_row["structs"] = dict(
                        (key,
                         (pluginconf.HIDDEN_VALUE_STRUCT_ATTR
                          if key not in pluginconf.HIDDEN_STRUCT_NAMES
                          else val))
                        for key, val in linestructs.items())
                # Adjust match position to the start of the sentence if
                # pluginconf.HIDE_MATCH_POS
                if pluginconf.HIDE_MATCH_POS:
                    match = kwic_row.get("match", {"position": 0, "start": 0})
                    pos = match["position"] - match["start"]
                    kwic_row["match"] = {
                        "position": pos,
                        "start": 0,
                        "end": 1,
                    }
                result["kwic"][row_num] = kwic_row
        return result
