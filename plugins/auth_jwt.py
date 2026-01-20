"""Authorization using JWT.

Supports three access levels:
- PUB (public): No Protected field in .info, accessible to all
- ACA (academic): Protected: ACA in .info, requires academic affiliation (JWT ACA flag)
- RES (restricted): Protected: RES in .info, requires explicit entitlement grant in JWT scope

Additionally, mink-* corpora (user-uploaded) use Protected: true/yes and require
explicit user grants in JWT scope.
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

        Returns all protected corpora (ACA, RES, and true/yes) as a flat list.
        """
        if use_cache:
            with memcached.get_client() as mc:
                key = f"protected:{utils.cache_prefix(mc)}"
                result = mc.get(key)
            if result is not None:
                return result

        # Get list of all corpora from CWB
        corpora = cwb.run_cqp("show corpora;")
        next(corpora)  # Skip version number
        corpus_info = utils.generator_to_dict(info.corpus_info({"corpus": list(corpora)}))
        protected_corpora = []
        for corpus, c_info in corpus_info["corpora"].items():
            protected_value = c_info["info"].get("Protected", "").lower()
            if protected_value in ("aca", "res", "true", "yes"):
                protected_corpora.append(corpus.upper())

        if use_cache:
            with memcached.get_client() as mc:
                mc.add(key, protected_corpora)
        return protected_corpora

    def check_authorization(self, corpora: List[str]) -> Tuple[bool, List[str], Optional[str]]:
        """Check if user is authorized to access the given corpora.

        Authorization rules:
        - ACA corpora: User must have ACA (academic) status in JWT
        - RES corpora: User must have explicit entitlement grant in JWT scope.corpora
        - true/yes corpora (incl. mink-*): User must have explicit user grant in JWT scope.corpora

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

        # Get protection types for corpora that need checking
        corpus_info = utils.generator_to_dict(info.corpus_info({"corpus": corpora_to_check}))

        # Check authorization for each corpus
        unauthorized = []
        for corpus_upper in corpora_to_check:
            protected_value = corpus_info.get("corpora", {}).get(
                corpus_upper, {}).get("info", {}).get("Protected", "").lower()

            if protected_value == "aca":
                # ACA corpora require academic status
                if not user_token or not user_token.get("ACA"):
                    unauthorized.append(corpus_upper)
            elif protected_value in ("res", "true", "yes"):
                # RES and true/yes corpora require explicit grant in scope
                if corpus_upper not in user_scope_corpora:
                    unauthorized.append(corpus_upper)

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
