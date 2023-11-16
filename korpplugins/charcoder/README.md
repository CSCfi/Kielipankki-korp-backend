
# Special characters encoded
SPECIAL_CHARS = " /<>|"
# The character for encoding the first character in SPECIAL_CHARS. The
# characters used for encoding should not appear in the corpus as
# such, unless a multi-character encoding prefix is defined which does
# not appear in the corpus as such.
ENCODED_SPECIAL_CHAR_OFFSET = 0x7F
# Prefix for the encoded form of special characters. Note that a
# non-empty prefix means that a special character will not be matched
# by a single-character pattern in CQP regular expressions.
ENCODED_SPECIAL_CHAR_PREFIX = ""
