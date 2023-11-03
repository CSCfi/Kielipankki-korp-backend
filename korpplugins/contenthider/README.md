
"""
korpplugins.contenthider.config (template)

Sample configuration for korpplugins.contenthider.
"""


# Structural attribute (annotation) names marking a structure as hidden and
# not to be shown to the user in query results
HIDDEN_STRUCT_NAMES = ["text__removed"]

# The value with which to replace positional attribute values within structures
# marked as hidden in query results, None to keep the original
HIDDEN_VALUE_POS_ATTR = "_"

# The value with which to replace structural attribute annotation values within
# structures marked as hidden in query results, None to keep the original
HIDDEN_VALUE_STRUCT_ATTR = "removed"

# If True, always set the match position to 0 in query results within
# structures marked as hidden
HIDE_MATCH_POS = True
