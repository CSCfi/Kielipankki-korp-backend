"""Authorization using JWT.

Configuration:
- licensing_mode: "språkbanken" (default) or "kielipankki"

Språkbanken mode (upstream/default):
- All corpora with Protected: true require explicit corpus grant in JWT scope.corpora
- License field is ignored

Kielipankki mode (extended):
- License: ACA → Requires JWT ACA flag (academic affiliation)
- License: ACA-Fi → Requires JWT ACA_Fi flag (Finnish academic status)
- License: RES → Requires explicit grant in JWT scope.corpora
- No License field → Requires explicit grant in JWT scope.corpora (same as Språkbanken)

Note: .info files use "ACA-Fi" with hyphen, but JWT uses "ACA_Fi" with underscore.
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

print(f"=== AUTH_JWT: Plugin initialized, import_name={bp.import_name} ===", flush=True)


class AuthJWT(utils.Authorizer):

    def __init__(self):
        print("=== AUTH_JWT: AuthJWT class instantiated ===", flush=True)
        self._pubkey = None

    def get_protected_corpora(self, use_cache: bool = True) -> List[str]:
        """Get list of corpora with restricted access.

        Returns all corpora where Protected: true (regardless of License type).

        Note: Caching is disabled for security. The cache invalidation system only
        monitors registry files, not .info files, so cached protection status could
        become stale when .info files are edited.
        """
        print("=== AUTH_JWT: get_protected_corpora called ===", flush=True)
        # Always bypass cache for security: .info file changes don't trigger cache invalidation
        corpora = cwb.run_cqp("show corpora;")
        next(corpora)  # Skip version number
        corpus_list = list(corpora)
        print(f"=== AUTH_JWT: checking {len(corpus_list)} corpora ===", flush=True)
        corpus_info = utils.generator_to_dict(info.corpus_info({"corpus": corpus_list, "cache": False}))
        print(f"=== AUTH_JWT: corpus_info keys: {list(corpus_info.keys())} ===", flush=True)
        print(f"=== AUTH_JWT: corpora count: {len(corpus_info.get('corpora', {}))} ===", flush=True)
        protected_corpora = []
        for corpus, c_info in corpus_info["corpora"].items():
            protected_value = c_info["info"].get("Protected", "").lower()
            if protected_value in ("true", "yes"):
                print(f"=== AUTH_JWT: {corpus} is PROTECTED (Protected={protected_value}) ===", flush=True)
                protected_corpora.append(corpus.upper())

        print(f"=== AUTH_JWT: returning {protected_corpora} ===", flush=True)
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
            print(f"=== AUTH_JWT: Decoding JWT, token length={len(auth_token)}, key type={type(self.jwt_key)} ===", flush=True)

            # First decode header and payload without verification to see what we're dealing with
            import json
            import base64
            try:
                header_b64, payload_b64, signature_b64 = auth_token.split('.')
                header = json.loads(base64.urlsafe_b64decode(header_b64 + '=='))
                payload = json.loads(base64.urlsafe_b64decode(payload_b64 + '=='))
                print(f"=== AUTH_JWT: JWT header (unverified): {header} ===", flush=True)
                print(f"=== AUTH_JWT: JWT payload email (unverified): {payload.get('email')} ===", flush=True)
            except Exception as e:
                print(f"=== AUTH_JWT: Failed to decode JWT without verification: {e} ===", flush=True)

            # Now try to verify
            try:
                user_token = jwt.decode(auth_token, key=self.jwt_key, algorithms=["RS256"])
                print(f"=== AUTH_JWT: JWT decoded successfully, ACA={user_token.get('ACA')} ===", flush=True)
            except Exception as e:
                print(f"=== AUTH_JWT: JWT decode FAILED: {type(e).__name__}: {e} ===", flush=True)
                # Show first and last few chars of public key for debugging
                key_preview = self.jwt_key[:50] + "..." + self.jwt_key[-50:] if len(self.jwt_key) > 100 else self.jwt_key
                print(f"=== AUTH_JWT: Public key preview: {key_preview} ===", flush=True)
                raise
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
                elif license_value == "ACA-FI":
                    # ACA-Fi license requires Finnish academic status
                    if not user_token or not user_token.get("ACA_Fi"):
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
            pubkey_file = bp.config("pubkey_file")
            if pubkey_file:
                # Handle both absolute and relative paths
                if pubkey_file.startswith("/"):
                    pubkey_path = Path(pubkey_file)
                else:
                    pubkey_path = Path(app.instance_path) / pubkey_file

                try:
                    self._pubkey = pubkey_path.read_text()
                    print(f"=== AUTH_JWT: Loaded public key from {pubkey_path}, length={len(self._pubkey)} ===", flush=True)
                except Exception as e:
                    print(f"=== AUTH_JWT: ERROR loading public key from {pubkey_path}: {e} ===", flush=True)
                    raise
            else:
                print("=== AUTH_JWT: No pubkey_file configured ===", flush=True)
        return self._pubkey
