import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote

import requests

from odoo import _, models
from odoo.exceptions import AccessError, UserError
from odoo.tools.urls import urljoin as url_join

from odoo.addons.social_linkedin.utils import urn_to_id

_logger = logging.getLogger(__name__)

# System parameter holding the LinkedIn-Version header (YYYYMM) of the calls of
# this module. The core `social_linkedin` calls keep their own version.
API_VERSION_PARAM = "social_linkedin_extended.api_version"
API_VERSION_PATTERN = re.compile(r"^\d{6}$")
INTROSPECT_TOKEN_URL = "https://www.linkedin.com/oauth/v2/introspectToken"
REQUEST_TIMEOUT = 10
# LinkedIn error bodies are cut to this length before being shown or stored
ERROR_BODY_MAX_LENGTH = 500
SECRET_MASK = "[hidden]"
# Values of "credential-like" keys in an error body, e.g. "access_token": "...", token=...
CREDENTIAL_VALUE_PATTERN = re.compile(
    r"""(?i)((?:access_token|refresh_token|client_secret|id_token|token)["']?\s*[:=]\s*["']?)[^\s"'&,}]+""")
BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[^\s\"',]+")


@dataclass
class LinkedInCall:
    """Outcome of one call to LinkedIn, safe to show: no token, no authorization header."""

    ok: bool
    status_code: int | None
    elapsed_ms: int
    body: dict = field(default_factory=dict)
    error_text: str = ""
    restli_id: str = ""
    comment_id: str = ""
    comment_urn: str = ""

    @property
    def error_kind(self):
        """Category of the error, used to explain it and to decide if a retry makes sense.

        - ``token``: invalid, expired or revoked token (reconnect the account)
        - ``permission``: the token lacks the permission for this action
        - ``version``: the LinkedIn-Version sent is not active anymore
        - ``rate_limit``, ``server``, ``network``: temporary errors
        - ``not_found``: unknown post (wrong URN, or a post not available yet)
        - ``no_id``: success answer without the id of the created object (the
          object probably exists on LinkedIn)
        - ``invalid``: any other rejected request
        """
        if self.ok:
            return False
        if self.status_code is None:
            return "network"
        if 200 <= self.status_code < 300:
            return "no_id"
        if self.status_code == 401 or self.body.get("serviceErrorCode") == 65600:
            return "token"
        if self.status_code == 403:
            return "permission"
        if self.status_code == 426:
            return "version"
        if self.status_code == 429:
            return "rate_limit"
        if self.status_code >= 500:
            return "server"
        if self.status_code == 404:
            return "not_found"
        return "invalid"


class SocialAccount(models.Model):
    _inherit = "social.account"

    def action_open_linkedin_comment_test(self):
        """Open the wizard creating, then deleting, a test comment with this account."""
        self.ensure_one()
        self._linkedin_extended_check_manager()
        if self.media_type != "linkedin":
            raise UserError(_("The LinkedIn comment test is only available for LinkedIn accounts."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Test LinkedIn comment"),
            "res_model": "social.linkedin.comment.test",
            "view_mode": "form",
            "target": "new",
            "context": {"default_account_id": self.id},
        }

    def _linkedin_extended_check_manager(self):
        if not self.env.user.has_group("social.group_social_manager"):
            raise AccessError(_("Only Social Marketing managers can test LinkedIn comments."))

    # ------------------------------------------------------------------
    # LinkedIn API (calls of this module only)
    # ------------------------------------------------------------------

    def _linkedin_extended_core_api_version(self):
        """LinkedIn-Version header sent by the core `social_linkedin` calls."""
        headers = self._linkedin_bearer_headers(linkedin_access_token="")
        return next((value for key, value in headers.items() if key.lower() == "linkedin-version"), "")

    def _linkedin_extended_api_version(self):
        """LinkedIn-Version header of the calls of this module.

        Read from the system parameter; falls back to the version of the core
        when the parameter is missing or not a YYYYMM value.
        """
        value = (self.env["ir.config_parameter"].sudo().get_param(API_VERSION_PARAM) or "").strip()
        if API_VERSION_PATTERN.match(value):
            return value
        if value:
            _logger.warning("Ignoring invalid value %r of system parameter %s (expected YYYYMM).",
                            value, API_VERSION_PARAM)
        return self._linkedin_extended_core_api_version()

    def _linkedin_extended_headers(self):
        """Authentication headers of the core, with the API version of this module."""
        self.ensure_one()
        headers = {
            key: value for key, value in self._linkedin_bearer_headers().items()
            if key.lower() != "linkedin-version"
        }
        headers["LinkedIn-Version"] = self._linkedin_extended_api_version()
        return headers

    def _linkedin_extended_sanitize(self, text):
        """Remove every secret from a text coming from LinkedIn or from an exception, and cut it."""
        text = str(text or "")
        client_secret = self.env["ir.config_parameter"].sudo().get_param("social.linkedin_client_secret")
        secrets = [secret for secret in (*self.sudo().mapped("linkedin_access_token"), client_secret) if secret]
        for secret in secrets:
            text = text.replace(secret, SECRET_MASK)
        text = BEARER_PATTERN.sub(r"\1" + SECRET_MASK, text)
        text = CREDENTIAL_VALUE_PATTERN.sub(r"\1" + SECRET_MASK, text)
        if len(text) > ERROR_BODY_MAX_LENGTH:
            text = text[:ERROR_BODY_MAX_LENGTH] + "..."
        return text

    def _linkedin_extended_request(self, method, endpoint, json=None, params=None):
        """Call the LinkedIn REST API; never raises, never disconnects the account.

        Unlike the comment methods of the core (`social.stream.post`), an error
        does not mark the account as disconnected: the caller decides.

        :return: LinkedInCall
        """
        self.ensure_one()
        url = url_join(self.env["social.media"]._LINKEDIN_ENDPOINT, endpoint)
        start = time.monotonic()
        try:
            response = requests.request(
                method, url, params=params, json=json,
                headers=self._linkedin_extended_headers(), timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as error:
            return LinkedInCall(
                ok=False, status_code=None, elapsed_ms=self._linkedin_extended_elapsed_ms(start),
                error_text=self._linkedin_extended_sanitize(f"{type(error).__name__}: {error}"))
        elapsed_ms = self._linkedin_extended_elapsed_ms(start)
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        call = LinkedInCall(
            ok=response.ok, status_code=response.status_code, elapsed_ms=elapsed_ms, body=body,
            restli_id=response.headers.get("x-restli-id") or "")
        if not response.ok:
            call.error_text = self._linkedin_extended_sanitize(response.text)
        return call

    @staticmethod
    def _linkedin_extended_elapsed_ms(start):
        return int(round((time.monotonic() - start) * 1000))

    def _linkedin_extended_create_comment(self, post_urn, text):
        """Comment on a post (share or ugcPost URN) as the author of this account.

        :return: LinkedInCall, with `comment_id` / `comment_urn` set on success
        """
        self.ensure_one()
        call = self._linkedin_extended_request(
            "POST", f"socialActions/{quote(post_urn)}/comments",
            json={
                "actor": self.linkedin_account_urn,
                "object": post_urn,
                "message": {"text": text},
            })
        if call.ok:
            call.comment_urn = call.body.get("commentUrn") or ""
            call.comment_id = str(call.restli_id or call.body.get("id") or urn_to_id(call.comment_urn) or "")
            if not call.comment_id:
                call.ok = False
                call.error_text = self._linkedin_extended_sanitize(
                    _("LinkedIn answered with a success but without the id of the comment: %(body)s",
                      body=call.body))
        return call

    def _linkedin_extended_delete_comment(self, post_urn, comment_id):
        """Delete a comment of this account (the organization is passed as actor)."""
        self.ensure_one()
        return self._linkedin_extended_request(
            "DELETE", f"socialActions/{quote(post_urn)}/comments/{quote(str(comment_id))}",
            params={"actor": self.linkedin_account_urn})

    def _linkedin_extended_introspect_token(self):
        """Ask LinkedIn for the expiry and the permissions of the token.

        LinkedIn only answers to the app that issued the token, with its client
        secret: only possible when the account uses its own LinkedIn app
        (Settings > Social Marketing > Use your own LinkedIn Account).

        :return: None when not possible, else a dict with only non secret values
        """
        self.ensure_one()
        config = self.env["ir.config_parameter"].sudo()
        app_id = config.get_param("social.linkedin_app_id")
        client_secret = config.get_param("social.linkedin_client_secret")
        if not (config.get_param("social.linkedin_use_own_account") and app_id and client_secret):
            return None
        start = time.monotonic()
        try:
            response = requests.request(
                "POST", INTROSPECT_TOKEN_URL,
                data={"client_id": app_id, "client_secret": client_secret, "token": self.linkedin_access_token},
                timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException as error:
            return {
                "status_code": None, "elapsed_ms": self._linkedin_extended_elapsed_ms(start),
                "error": self._linkedin_extended_sanitize(f"{type(error).__name__}: {error}"),
            }
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        result = {
            "status_code": response.status_code,
            "elapsed_ms": self._linkedin_extended_elapsed_ms(start),
            **{key: body.get(key) for key in ("active", "status", "scope", "expires_at", "auth_type")},
        }
        if not response.ok:
            result["error"] = self._linkedin_extended_sanitize(response.text)
        return result
