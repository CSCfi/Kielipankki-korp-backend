
"""
korpplugins.shibauth

A Korp callback plugin to support authorization with information
obtained from Shibboleth authentication in /authenticate.

Ported to a Korp backend plugin from the modifications made to Korp
for the Language Bank of Finland, originally by Jussi Piitulainen.
"""


import urllib.error
import urllib.parse
import urllib.request
from typing import List, Tuple, Optional

from flask import request

from korp import pluginlib, utils


plugin = pluginlib.EndpointPlugin()


@plugin.route("/authenticate", methods=["GET", "POST"])
@utils.main_handler
def authenticate(_=None):
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

        try:
            contents = urllib.request.urlopen(
                plugin.config("AUTH_SERVER"),
                urllib.parse.urlencode(postdata).encode("utf-8")
            ).read().decode("utf-8")
            auth_response = json.loads(contents)
        except urllib.error.HTTPError:
            raise utils.KorpAuthorizationError(
                "Could not contact authentication server.")
        except ValueError:
            raise utils.KorpAuthorizationError(
                "Invalid response from authentication server.")
        except:
            raise utils.KorpAuthorizationError(
                "Unexpected error during authentication.")

        if auth_response["authenticated"]:
            permitted_resources = auth_response["permitted_resources"]
            result = {"corpora": []}
            if "corpora" in permitted_resources:
                for c in permitted_resources["corpora"]:
                    if permitted_resources["corpora"][c]["read"]:
                        result["corpora"].append(c.upper())
            result["username"] = remote_user
            yield result
            return

    yield {"foo": "bar"}


class ShibAuth(utils.BaseAuthorizer):

    def check_authorization(
            self, corpora: List[str]
    ) -> Tuple[bool, List[str], Optional[str]]:
        """Take a list of corpora, and check if the user has access to them."""

        protected = utils.get_protected_corpora()
        c = [c for c in corpora if c.upper() in protected]
        if c:
            auth = utils.generator_to_dict(authenticate({}))
            unauthorized = [
                x for x in c if x.upper() not in auth.get("corpora", [])]
            if not auth or unauthorized:
                return False, unauthorized, None
        return True, [], None
