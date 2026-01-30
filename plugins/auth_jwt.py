"""Authorization using JWT.

Configuration:
- licensing_mode: "språkbanken" (default) or "kielipankki"

Språkbanken mode (upstream/default):
- All corpora with Protected: true require explicit corpus grant in JWT scope.corpora
- License field is ignored

Kielipankki mode (extended):
- License: ACA → Requires JWT ACA flag (academic affiliation)
- License: ACA-Fi → Requires JWT "ACA-Fi" flag (Finnish academic status)
- License: RES → Requires explicit grant in JWT scope.corpora
- No License field → Requires explicit grant in JWT scope.corpora (same as Språkbanken)

Note: .info files use "ACA-Fi" with hyphen, and JWT also uses "ACA-Fi" (quoted key).
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

        Behavior depends on licensing_mode configuration.

        Returns:
            Tuple of (success, unauthorized_corpora, error_message)
        """
        licensing_mode = bp.config("licensing_mode", "språkbanken")

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

        # Kielipankki mode: check License field for authorization type
        if licensing_mode == "kielipankki":
            # Get license types for corpora that need checking
            # Always bypass cache for security: .info file changes don't trigger cache invalidation
            corpus_info = utils.generator_to_dict(info.corpus_info({"corpus": corpora_to_check, "cache": False}))

            # Check authorization for each corpus
            unauthorized = []
            for corpus_upper in corpora_to_check:
                c_info = corpus_info.get("corpora", {}).get(corpus_upper, {}).get("info", {})
                license_value = c_info.get("License", "").upper()

                if license_value == "ACA":
                    # ACA license requires academic status
                    if not user_token or not user_token.get("ACA"):
                        unauthorized.append(corpus_upper)
                elif license_value == "ACA-Fi":
                    # ACA-Fi license requires Finnish academic status
                    if not user_token or not user_token.get("ACA-Fi"):
                        unauthorized.append(corpus_upper)
                elif license_value == "RES":
                    # RES license requires explicit grant in scope
                    if corpus_upper not in user_scope_corpora:
                        unauthorized.append(corpus_upper)
                else:
                    # No License field or other value requires explicit grant in scope
                    if corpus_upper not in user_scope_corpora:
                        unauthorized.append(corpus_upper)

            if unauthorized:
                return False, unauthorized, None
            return True, [], None

        # Default mode (Språkbanken): all protected corpora require explicit grant in scope
        else:
            unauthorized = [c.upper() for c in corpora_to_check if c.upper() not in user_scope_corpora]
            if unauthorized:
                return False, unauthorized, None
            return True, [], None

    @property
    def jwt_key(self):
        """Return the public key for validating JWTs."""
        if not self._pubkey:
            if bp.config("pubkey_file"):
                self._pubkey = open(Path(app.instance_path) / bp.config("pubkey_file")).read()
        return self._pubkey
