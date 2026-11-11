import logging
from datetime import datetime, timezone

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.social_linkedin_extended.models.social_account import API_VERSION_PARAM

_logger = logging.getLogger(__name__)

# Text of the comment created (then deleted) on LinkedIn: content posted on the
# page, intentionally not translated
TEST_COMMENT_TEXT = "Odoo comment test, will be deleted"


class SocialLinkedinCommentTest(models.TransientModel):
    _name = "social.linkedin.comment.test"
    _description = "LinkedIn comment diagnostics"

    account_id = fields.Many2one(
        "social.account", string="LinkedIn account", required=True, readonly=True, ondelete="cascade",
        domain="[('media_type', '=', 'linkedin')]")
    post_urn = fields.Char(
        # Required in the view only: a stored computed field is computed after the
        # INSERT, a NOT NULL column would reject wizards without a default post
        string="Post URN", compute="_compute_post_urn", store=True, readonly=False,
        help="LinkedIn URN of a post of this page (urn:li:share:... or urn:li:ugcPost:...). "
        "Defaults to the last post published by this account from Odoo, else to its last post "
        "fetched in the Feed.")
    state = fields.Selection(
        [("draft", "Draft"), ("done", "Done")], string="Status", default="draft", required=True)
    report = fields.Text(string="Report", readonly=True)

    @api.depends("account_id")
    def _compute_post_urn(self):
        """Last post published from Odoo by the account, else its last post fetched in the Feed."""
        for wizard in self:
            last_live_post = self.env["social.live.post"].search([
                ("account_id", "=", wizard.account_id.id),
                ("state", "=", "posted"),
                ("linkedin_post_id", "!=", False),
            ], order="id desc", limit=1)
            last_feed_post = self.env["social.stream.post"]
            if not last_live_post:
                last_feed_post = self.env["social.stream.post"].search([
                    ("account_id", "=", wizard.account_id.id),
                    ("linkedin_post_urn", "!=", False),
                ], order="published_date desc, id desc", limit=1)
            wizard.post_urn = last_live_post.linkedin_post_id or last_feed_post.linkedin_post_urn or False

    def action_run_test(self):
        self.ensure_one()
        account = self.account_id
        account._linkedin_extended_check_manager()
        post_urn = (self.post_urn or "").strip()
        if not post_urn.startswith("urn:li:"):
            raise UserError(_("The post URN must start with “urn:li:” (e.g. urn:li:share:123)."))
        self.write({"report": self._build_report(account, post_urn), "state": "done"})
        return {
            "type": "ir.actions.act_window",
            "name": _("Test LinkedIn comment"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Report
    # ------------------------------------------------------------------

    def _build_report(self, account, post_urn):
        """Run the test and return the report: never contains the token."""
        yes_no = {True: _("Yes"), False: _("No")}
        api_version = account._linkedin_extended_api_version()
        lines = [
            _("LinkedIn comment diagnostics"),
            _("Date (UTC): %(date)s", date=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
            _("Account: %(name)s (id %(id)s)", name=account.name, id=account.id),
            _("Author URN: %(urn)s", urn=account.linkedin_account_urn or _("missing")),
            _("Account marked as disconnected in Odoo: %(value)s", value=yes_no[bool(account.is_media_disconnected)]),
            _("Route: direct call to the LinkedIn REST API, with the authentication headers of the core "
              "(social.account._linkedin_bearer_headers) and the API version of this module"),
            _("API version sent: %(version)s (system parameter %(param)s)", version=api_version, param=API_VERSION_PARAM),
            _("API version of the core social_linkedin module: %(version)s",
              version=account._linkedin_extended_core_api_version() or _("unknown")),
            _("Post URN: %(urn)s", urn=post_urn),
            "",
            _("1. Token"),
        ]

        if not account.sudo().linkedin_access_token:
            lines += [
                _("Access token: missing"),
                "",
                _("Result: the account has no access token. Reconnect the LinkedIn account in Odoo "
                  "(Social Marketing > Configuration > Social Media > LinkedIn > Link account)."),
            ]
            return "\n".join(lines)

        lines.append(_("Access token: present (never shown)"))
        lines += self._report_token_lines(account.sudo()._linkedin_extended_introspect_token())

        lines += ["", _("2. Create the test comment")]
        create = account._linkedin_extended_create_comment(post_urn, TEST_COMMENT_TEXT)
        lines.append(self._report_call_line(create))
        if create.ok:
            lines.append(_("Comment id: %(id)s", id=create.comment_id))
            if create.comment_urn:
                lines.append(_("Comment URN: %(urn)s", urn=create.comment_urn))
        else:
            lines.append(_("LinkedIn error: %(error)s", error=create.error_text or _("no details")))

        lines += ["", _("3. Delete the test comment")]
        delete = None
        if create.ok:
            delete = account._linkedin_extended_delete_comment(post_urn, create.comment_id)
            lines.append(self._report_call_line(delete))
            if delete.ok:
                lines.append(_("Test comment deleted."))
            else:
                lines += [
                    _("LinkedIn error: %(error)s", error=delete.error_text or _("no details")),
                    _("WARNING: the test comment was NOT deleted, delete it by hand on LinkedIn."),
                ]
        elif create.error_kind == "no_id":
            lines.append(_("Not possible: LinkedIn did not return the id of the comment. A comment was probably "
                           "created: check the post and delete the test comment by hand on LinkedIn."))
        else:
            lines.append(_("Skipped: no comment was created."))

        lines += ["", self._report_result_line(create, delete, api_version)]
        _logger.info(
            "LinkedIn comment diagnostics on social.account %s: create HTTP %s (%s), delete HTTP %s",
            account.id, create.status_code, create.error_kind or "ok", delete.status_code if delete else "-")
        return "\n".join(lines)

    def _report_token_lines(self, introspection):
        if introspection is None:
            return [
                _("Expiry: unknown"),
                _("Granted permissions: unknown"),
                _("LinkedIn only reveals them to the app that issued the token, with its client secret: "
                  "possible only when the account was connected with your own LinkedIn app "
                  "(Social Marketing > Configuration > Settings > Use your own LinkedIn Account). "
                  "The comment test below is the real check."),
            ]
        lines = [_("Token introspection: %(call)s", call=self._format_status(
            introspection.get("status_code"), introspection.get("elapsed_ms")))]
        if introspection.get("error"):
            lines.append(_("LinkedIn error: %(error)s", error=introspection["error"]))
        if introspection.get("active") is False:
            lines.append(_("Token active: No (expired, revoked, or not issued by the configured LinkedIn app)"))
        elif introspection.get("active"):
            lines.append(_("Token active: Yes"))
        if introspection.get("expires_at"):
            expiry = datetime.fromtimestamp(introspection["expires_at"], timezone.utc)
            lines.append(_("Expiry (UTC): %(date)s", date=expiry.strftime("%Y-%m-%d %H:%M:%S")))
        else:
            lines.append(_("Expiry: unknown"))
        lines.append(_("Granted permissions: %(scope)s", scope=introspection.get("scope") or _("unknown")))
        return lines

    @api.model
    def _format_status(self, status_code, elapsed_ms):
        if status_code is None:
            return _("no HTTP answer (network error), %(ms)s ms", ms=elapsed_ms)
        return _("HTTP %(status)s, %(ms)s ms", status=status_code, ms=elapsed_ms)

    @api.model
    def _report_call_line(self, call):
        return self._format_status(call.status_code, call.elapsed_ms)

    @api.model
    def _report_result_line(self, create, delete, api_version):
        if create.ok:
            if delete and delete.ok:
                return _("Result: OK, this account can comment on its LinkedIn posts.")
            return _("Result: this account can comment, but the test comment could not be deleted.")
        messages = {
            "permission": _(
                "Result: NOT POSSIBLE, missing permission. The token cannot comment as this organization: "
                "it needs w_organization_social_feed (named w_organization_social in older LinkedIn "
                "documentation), granted only to page administrators, through an app approved for the "
                "LinkedIn Community Management API. A token keeps the permissions it was issued with: "
                "the account must be authorized again with an app that has this permission."),
            "token": _(
                "Result: NOT POSSIBLE, the access token is invalid, expired or revoked. Reconnect the "
                "LinkedIn account in Odoo and run the test again."),
            "version": _(
                "Result: LinkedIn rejected the API version %(version)s (not active anymore). Set a "
                "current version (YYYYMM) in the system parameter %(param)s and run the test again.",
                version=api_version, param=API_VERSION_PARAM),
            "rate_limit": _(
                "Result: LinkedIn throttled the request (rate limit). Run the test again in a few minutes."),
            "server": _("Result: temporary error at LinkedIn. Run the test again later."),
            "network": _("Result: LinkedIn could not be reached (network error). Run the test again later."),
            "no_id": _(
                "Result: LinkedIn accepted the comment but did not return its id, so it could not be deleted: "
                "check the post on LinkedIn and delete the test comment by hand."),
            "not_found": _(
                "Result: LinkedIn did not find the post. Check the URN; a post published a few seconds "
                "ago may not be available yet."),
        }
        return messages.get(create.error_kind, _(
            "Result: LinkedIn rejected the request as invalid, see the error above."))
