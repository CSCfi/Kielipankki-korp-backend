"""Authorization using JWT.

For corpora with Protected: true in the .info file:
- If corpus is in JWT scope.corpora (explicit grant), it's authorized
- Otherwise, if License field is present in .info, check if JWT has that license key as truthy value
  (e.g., License: ACA → requires jwt["ACA"], License: ACA-Fi → requires jwt["ACA-Fi"])
- Otherwise, it's not authorized

"""

import time
from pathlib import Path
from typing import List, Tuple, Optional

import jwt  # From pyjwt[crypto]
from flask import current_app as app
from flask import request

from korp import cwb, utils
from korp import memcached
from korp.views import info

bp = utils.Plugin("auth_jwt", __name__)


class AuthJWT(utils.Authorizer):

    def __init__(self):
        self._pubkey = None

    def get_protected_corpora(self, use_cache: bool = True) -> List[str]:
        """Get list of corpora with restricted access.

        Returns all corpora where Protected: true (regardless of License type).

        Note: Caching is disabled for security. The cache invalidation system only
        monitors registry files, not .info files, so cached protection status could
        become stale when .info files are edited.
        """
        # Always bypass cache for security: .info file changes don't trigger cache invalidation
        corpora = cwb.run_cqp("show corpora;")
        next(corpora)  # Skip version number
        corpus_info = utils.generator_to_dict(info.corpus_info({"corpus": list(corpora), "cache": False}))
        protected_corpora = []
        for corpus, c_info in corpus_info["corpora"].items():
            protected_value = c_info["info"].get("Protected", "").lower()
            if protected_value in ("true", "yes"):
                protected_corpora.append(corpus.upper())

        return protected_corpora

    def check_authorization(self, corpora: List[str]) -> Tuple[bool, List[str], Optional[str]]:
        """Check if user is authorized to access the given corpora.

        For corpora with License field: check if JWT has that license key as truthy.
        For corpora without License field: check if corpus is in JWT scope.corpora.

        Returns:
            Tuple of (success, unauthorized_corpora, error_message)
        """
        protected_set = set(self.get_protected_corpora())

        # Find which requested corpora need authorization
        corpora_to_check = [c.upper() for c in corpora if c.upper() in protected_set]

        if not corpora_to_check:
            return True, [], None

        # Parse JWT if present
        user_token = None
        user_scope_corpora = set()

        auth_header = request.headers.get("Authorization")
        if auth_header and " " in auth_header:
            auth_token = auth_header.split(" ")[1]

            # Parse JWT
            user_token = jwt.decode(auth_token, key=self.jwt_key, algorithms=["RS256"])
            if user_token["exp"] < time.time():
                return False, [], "The provided JWT has expired"

            # Collect user's granted corpora from scope
            for corpus in user_token.get("scope", {}).get("corpora", {}).keys():
                user_scope_corpora.add(corpus.upper())

        # Get license info for protected corpora
        # Bypass cache for security: .info file changes don't trigger cache invalidation
        corpus_info = utils.generator_to_dict(
            info.corpus_info({"corpus": corpora_to_check, "cache": False})
        )

        # Check authorization for each corpus
        unauthorized = []
        for corpus_upper in corpora_to_check:
            if corpus_upper in user_scope_corpora:
                continue
            license_value = (
                corpus_info.get("corpora", {})
                .get(corpus_upper, {})
                .get("info", {})
                .get("License", "")
            )
            if license_value and user_token.get(license_value):
                continue
            unauthorized.append(corpus_upper)

        if unauthorized:
            return False, unauthorized, None
        return True, [], None

    @property
    def jwt_key(self):
        """Return the public key for validating JWTs."""
        if not self._pubkey:
            if bp.config("pubkey_file"):
                self._pubkey = open(
                    Path(app.instance_path) / bp.config("pubkey_file")
                ).read()
        return self._pubkey
