
"""
korpplugins.shibauth

A Korp callback plugin to support authorization with information
obtained from Shibboleth authentication in /authenticate.

Ported to a Korp backend plugin from the modifications made to Korp
for the Language Bank of Finland, originally by Jussi Piitulainen.
"""


import korppluginlib


class ShibbolethAuthorizer(korppluginlib.KorpCallbackPlugin):

    """A Korp callback plugin for authentication handling Shibboleth info"""

    # dict to map requests to usernames, for saving a username in
    # filter_auth_postdata to be added to the result in filter_result, as
    # expected by the frontend (plugin).
    _username = {}

    def exit_handler(self, request, *args):
        """Remove request username at the end of handling the request."""
        if request in self._username:
            del self._username[request]

    def filter_result(self, request, result):
        """Add "username" to the result of /authenticate."""
        # Note: You cannot specify method applies_to() to restrict to
        # /authenticate, as also other endpoints call authenticate internally.
        if request.endpoint == "authenticate":
            result["username"] = self._username.get(request)

    def filter_auth_postdata(self, request, postdata):
        """If REMOTE_USER is set, return postdata with Shibboleth info.

        If REMOTE_USER is set, return postdata with remote_user,
        affiliation and entitlement set from the corresponding
        environment variables set by Shibboleth (or from the
        corresponding headers set by the reverse proxy); otherwise
        return postdata intact.
        """

        def get_value(key):
            """Get the value of env variable key or the corresponding header.

            If the environment variable `key` does not exist or is
            empty and its name begins with "HTTP_", first try the
            environment variable without the "HTTP_" prefix. Then try
            the corresponding HTTP headers X-Key and Key, where Key is
            title-cased and with the possible "HTTP_" prefix removed.
            """
            value = request.environ.get(key)
            if not value:
                if key.startswith("HTTP_"):
                    key = key[5:]
                    value = request.environ.get(key)
                # Try to get a value from HTTP headers
                if not value:
                    key = key.replace("_", "-").title()
                    value = (request.headers.get("X-" + key)
                             or request.headers.get(key)
                             or "")
            return value

        # Apache seems to pass the remote user information in the environment
        # variable HTTP_REMOTE_USER
        remote_user = get_value("HTTP_REMOTE_USER")
        # Save the username to be added to the result in filter_result
        self._username[request] = remote_user
        # print("remote user:", remote_user)
        if remote_user:
            # In which order should we check the affiliation variables?
            affiliation = (get_value("HTTP_UNSCOPED_AFFILIATION") or
                           get_value("HTTP_AFFILIATION"))
            entitlement = get_value("HTTP_ENTITLEMENT")
            postdata = {
                "remote_user": remote_user,
                "affiliation": affiliation.lower(),
                "entitlement": entitlement,
            }
        # print("postdata:", postdata)
        return postdata
