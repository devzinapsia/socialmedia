import logging

from psycopg2 import errors as pg_errors

from odoo import _, api, fields, models, modules
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL

from .social_post import LINKEDIN_FIRST_COMMENT_MAX_LENGTH

_logger = logging.getLogger(__name__)

# A first comment is tried at most this many times (first attempt included)
LINKEDIN_COMMENT_MAX_ATTEMPTS = 3
# Errors worth a retry: rate limit, LinkedIn server error, network error, and
# "post not found" (a post published a few seconds ago may not be available yet)
LINKEDIN_COMMENT_TRANSIENT_ERRORS = {"rate_limit", "server", "network", "not_found"}
# First comments retried per run of the cron
LINKEDIN_COMMENT_CRON_BATCH = 200
LINKEDIN_COMMENT_FIELDS = [
    "linkedin_comment_state", "linkedin_comment_id", "linkedin_comment_urn", "linkedin_comment_date",
    "linkedin_comment_attempts", "linkedin_comment_error", "linkedin_comment_message",
]


class SocialLivePost(models.Model):
    _inherit = "social.live.post"

    linkedin_comment_state = fields.Selection(
        [("none", "None"), ("pending", "Pending"), ("posted", "Posted"), ("failed", "Failed")],
        # Not required: a NOT NULL column would break the inserts of modules loaded
        # before this one (e.g. their at_install tests); empty means "none"
        string="LinkedIn comment status", default="none", readonly=True,
        help="Status of the first comment of the post on this LinkedIn account:\n"
        "- None: no first comment to post\n"
        "- Pending: not posted yet, or a temporary error to retry\n"
        "- Posted: the comment is on LinkedIn\n"
        "- Failed: LinkedIn refused it, or every retry failed")
    linkedin_comment_message = fields.Text(
        string="LinkedIn comment text", readonly=True, copy=False,
        help="Final text of the first comment, with its tracked links, as posted (or to post) on LinkedIn.")
    linkedin_comment_id = fields.Char(string="LinkedIn comment ID", readonly=True, copy=False)
    linkedin_comment_urn = fields.Char(string="LinkedIn comment URN", readonly=True, copy=False)
    linkedin_comment_date = fields.Datetime(
        string="LinkedIn comment date", readonly=True, copy=False,
        help="When the comment was posted, or when the last attempt was made.")
    linkedin_comment_attempts = fields.Integer(string="LinkedIn comment attempts", readonly=True, copy=False)
    linkedin_comment_error = fields.Text(
        string="LinkedIn comment error", readonly=True, copy=False,
        help="Summary of the last error returned by LinkedIn for the comment.")

    @api.model_create_multi
    def create(self, vals_list):
        live_posts = super().create(vals_list)
        # `social.post._action_post` creates the live posts, then commits, then
        # publishes: the link trackers of the comment are committed before it is
        # posted, like the ones of the main message
        live_posts._prepare_linkedin_first_comment()
        return live_posts

    def _prepare_linkedin_first_comment(self):
        """Store the final text of the first comment (tracked links with the UTM values of the post).

        A retry posts exactly this text.
        """
        for live_post in self._filter_by_media_types(["linkedin"]):
            comment = live_post.post_id.linkedin_first_comment
            if not comment or live_post.linkedin_comment_state not in (False, "none"):
                continue
            live_post.write({
                "linkedin_comment_message": self.env["mail.render.mixin"].sudo()._shorten_links_text(
                    comment, live_post._get_utm_values()),
                "linkedin_comment_state": "pending",
            })

    def _post_linkedin(self):
        # Same hook for an instant post, a scheduled post (cron) and the "Retry"
        # of the core: right after the post is published on each account
        super()._post_linkedin()
        self.filtered(
            lambda live_post: live_post.state == "posted" and live_post.linkedin_post_id
            and live_post.linkedin_comment_state == "pending"
        )._linkedin_publish_first_comment(lookup_first=False)

    # ------------------------------------------------------------------
    # Retries
    # ------------------------------------------------------------------

    @api.model
    def _cron_retry_linkedin_first_comments(self):
        """Retry the first comments left pending by a temporary error (hourly cron).

        Only for posts actually published on LinkedIn. Each retry first looks on
        LinkedIn for the comment, in case a previous attempt created it.
        """
        live_posts = self.search([
            ("linkedin_comment_state", "=", "pending"),
            ("linkedin_comment_attempts", "<", LINKEDIN_COMMENT_MAX_ATTEMPTS),
            ("state", "=", "posted"),
            ("linkedin_post_id", "!=", False),
            ("account_id.media_type", "=", "linkedin"),
        ], order="id", limit=LINKEDIN_COMMENT_CRON_BATCH)
        live_posts._linkedin_publish_first_comment(lookup_first=True)

    def action_retry_linkedin_comment(self):
        """Retry a failed first comment by hand (Social Marketing managers only).

        Starts a new cycle of attempts: if it fails again with a temporary error,
        the cron retries it.
        """
        if not self.env.user.has_group("social.group_social_manager"):
            raise AccessError(_("Only Social Marketing managers can retry LinkedIn comments."))
        for live_post in self:
            if live_post.linkedin_comment_state != "failed":
                raise UserError(_("Only a failed LinkedIn comment can be retried."))
            if live_post.state != "posted" or not live_post.linkedin_post_id:
                raise UserError(_("The post is not published on LinkedIn: retry the post first."))
        self.sudo().write({"linkedin_comment_state": "pending", "linkedin_comment_attempts": 0})
        self.sudo()._linkedin_publish_first_comment(lookup_first=True)

    # ------------------------------------------------------------------
    # First comment engine
    # ------------------------------------------------------------------

    def _linkedin_publish_first_comment(self, lookup_first):
        """Post the pending first comment of each live post. Never raises.

        The post itself is already published: whatever happens to the comment,
        the live post stays "posted" (an exception reaching `_action_post` would
        mark it failed).

        :param bool lookup_first: look on LinkedIn for the comment before posting
            it. True for every retry: a previous attempt may have created it
            without Odoo knowing. False right after the publication (a new post
            cannot have the comment yet).
        :return: the live posts actually handled (not the ones skipped because
            another process is handling them, or because they are not pending anymore)
        """
        handled = self.browse()
        for live_post in self:
            try:
                with self.env.cr.savepoint():
                    if live_post._linkedin_comment_attempt(lookup_first):
                        handled |= live_post
            except pg_errors.SerializationFailure:
                # Another transaction changed this live post after this one
                # started (e.g. the cron and the retry button): it handled it
                _logger.info("LinkedIn first comment of social.live.post %s handled by another process.",
                             live_post.id)
                continue
            except Exception:
                _logger.exception("LinkedIn first comment of social.live.post %s: unexpected error.", live_post.id)
                try:
                    with self.env.cr.savepoint():
                        live_post._linkedin_comment_record_unexpected_error()
                    handled |= live_post
                except Exception:
                    _logger.exception("Could not record the error of social.live.post %s.", live_post.id)
            if live_post in handled and not modules.module.current_test:
                # Manual commit, justified: once LinkedIn has the comment, its id
                # must be stored at once. Otherwise an error later in the same
                # transaction (another live post, the end of the cron or of the
                # request) would roll it back and the comment would be posted again.
                # It also releases the lock of the row (see _linkedin_comment_lock).
                # The core already commits in `social.post._action_post` before
                # publishing, so the transaction is not shared with unrelated work.
                try:
                    self.env.cr.commit()
                except Exception:
                    _logger.exception("Could not commit the LinkedIn first comment of social.live.post %s.",
                                      live_post.id)
        return handled

    def _linkedin_comment_lock(self):
        """Lock the row of this live post until the end of the transaction.

        :return: False when another transaction holds it (it is handling the comment)
        :raise SerializationFailure: when another transaction changed it after this
            one started (REPEATABLE READ)
        """
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute(SQL(
            "SELECT id FROM social_live_post WHERE id = %s FOR NO KEY UPDATE SKIP LOCKED", self.id))
        return bool(self.env.cr.fetchone())

    def _linkedin_comment_attempt(self, lookup_first):
        """One attempt to post the first comment of this live post.

        :return: False when skipped (locked by another process, or not pending anymore)
        """
        self.ensure_one()
        if not self._linkedin_comment_lock():
            return False
        # Values committed by another process before the lock
        self.invalidate_recordset(LINKEDIN_COMMENT_FIELDS + ["state", "linkedin_post_id"])
        if (self.linkedin_comment_state != "pending" or self.linkedin_comment_id
                or self.state != "posted" or not self.linkedin_post_id):
            return False

        account = self.account_id
        message = self.linkedin_comment_message or ""
        attempts = self.linkedin_comment_attempts + 1
        values = {"linkedin_comment_attempts": attempts, "linkedin_comment_date": fields.Datetime.now()}

        if not account.sudo().linkedin_access_token:
            return self._linkedin_comment_finish(values, failed_reason=_(
                "The LinkedIn account has no access token: reconnect it."))
        if not message.strip():
            return self._linkedin_comment_finish(values, failed_reason=_("The comment text is empty."))
        if len(message) > LINKEDIN_FIRST_COMMENT_MAX_LENGTH:
            return self._linkedin_comment_finish(values, failed_reason=_(
                "The comment is too long once its links are tracked: %(length)s characters (max %(max)s).",
                length=len(message), max=LINKEDIN_FIRST_COMMENT_MAX_LENGTH))

        if lookup_first:
            lookup, existing = account._linkedin_extended_find_comment(self.linkedin_post_id, message)
            if existing:
                return self._linkedin_comment_finish(values, comment=existing)
            if not lookup.ok:
                # Never post without knowing whether the comment already exists
                return self._linkedin_comment_finish_with_error(values, lookup, lookup=True)

        create = account._linkedin_extended_create_comment(self.linkedin_post_id, message)
        if create.ok:
            return self._linkedin_comment_finish(values, comment={
                "id": create.comment_id, "commentUrn": create.comment_urn})
        if create.error_kind == "no_id":
            # LinkedIn accepted a comment without giving its id: look for it once
            # instead of posting again
            lookup, existing = account._linkedin_extended_find_comment(self.linkedin_post_id, message)
            if existing:
                return self._linkedin_comment_finish(values, comment=existing)
            return self._linkedin_comment_finish(values, failed_reason=_(
                "LinkedIn accepted the comment without returning its id: check the post on LinkedIn "
                "before retrying (%(error)s).", error=create.error_text))
        return self._linkedin_comment_finish_with_error(values, create)

    def _linkedin_comment_finish_with_error(self, values, call, lookup=False):
        """Store a failed call: pending again for a temporary error (until the last attempt), else failed."""
        reason = self._linkedin_comment_error_summary(call, lookup=lookup)
        _logger.warning(
            "LinkedIn first comment of social.live.post %s: attempt %s failed (%s, HTTP %s): %s",
            self.id, values["linkedin_comment_attempts"], call.error_kind, call.status_code, call.error_text)
        if (call.error_kind in LINKEDIN_COMMENT_TRANSIENT_ERRORS
                and values["linkedin_comment_attempts"] < LINKEDIN_COMMENT_MAX_ATTEMPTS):
            self.write({**values, "linkedin_comment_state": "pending", "linkedin_comment_error": reason})
            return True
        return self._linkedin_comment_finish(values, failed_reason=reason)

    def _linkedin_comment_finish(self, values, comment=None, failed_reason=None):
        """Store the final outcome of the comment and log it in the chatter of the post."""
        account_name = self.account_id.display_name
        if comment is not None:
            self.write({
                **values,
                "linkedin_comment_state": "posted",
                "linkedin_comment_id": str(comment.get("id") or ""),
                "linkedin_comment_urn": comment.get("commentUrn") or False,
                "linkedin_comment_error": False,
            })
            body = _("LinkedIn first comment posted on %(account)s.", account=account_name)
        else:
            self.write({**values, "linkedin_comment_state": "failed", "linkedin_comment_error": failed_reason})
            body = _("LinkedIn first comment failed on %(account)s: %(reason)s",
                     account=account_name, reason=failed_reason)
        self.post_id.sudo()._message_log(body=body)
        return True

    def _linkedin_comment_record_unexpected_error(self):
        """Count an attempt that crashed: retried later (looking for the comment first)."""
        self.invalidate_recordset(LINKEDIN_COMMENT_FIELDS)
        if self.linkedin_comment_state != "pending":
            return
        values = {
            "linkedin_comment_attempts": self.linkedin_comment_attempts + 1,
            "linkedin_comment_date": fields.Datetime.now(),
        }
        reason = _("Unexpected error, see the server log.")
        if values["linkedin_comment_attempts"] >= LINKEDIN_COMMENT_MAX_ATTEMPTS:
            self._linkedin_comment_finish(values, failed_reason=reason)
        else:
            self.write({**values, "linkedin_comment_error": reason})

    def _linkedin_comment_error_summary(self, call, lookup=False):
        """Short reason of a failed call, without any secret (already removed from `error_text`)."""
        if call.status_code is None:
            details = _("network error: %(error)s", error=call.error_text or _("no details"))
        else:
            details = _("HTTP %(status)s: %(error)s", status=call.status_code, error=call.error_text or _("no details"))
        kind = call.error_kind
        if kind == "permission" and lookup:
            hint = _("Missing permission to read the comments of the page (r_organization_social_feed), "
                     "needed to check that the comment was not already posted.")
        elif kind == "permission":
            hint = _("Missing permission to comment as this page (w_organization_social_feed).")
        elif kind == "token":
            hint = _("Invalid, expired or revoked access token: reconnect the LinkedIn account.")
        elif kind == "version":
            hint = _("LinkedIn API version %(version)s not active anymore: update the system parameter "
                     "social_linkedin_extended.api_version.",
                     version=self.account_id._linkedin_extended_api_version())
        elif kind == "rate_limit":
            hint = _("LinkedIn rate limit reached.")
        elif kind == "not_found":
            hint = _("Post not found on LinkedIn (it may not be available yet).")
        elif lookup:
            hint = _("Could not check whether the comment was already posted.")
        else:
            hint = _("LinkedIn refused the comment.")
        return f"{hint} ({details})"
