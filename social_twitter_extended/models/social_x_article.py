import base64
import json
import logging

import requests

from odoo import _, api, fields, models, modules
from odoo.exceptions import UserError, ValidationError
from odoo.tools.mimetypes import guess_mimetype

from ..tools.html_to_content_state import html_to_content_state
from .social_account import TwitterApiError

_logger = logging.getLogger(__name__)

# Host of the Articles endpoints in the X API documentation
TWITTER_ARTICLES_ENDPOINT = "https://api.x.com"


class SocialXArticle(models.Model):
    _name = "social.x.article"
    _description = "X Article"
    _order = "create_date desc, id desc"
    _rec_name = "title"

    title = fields.Char(required=True)
    body = fields.Html(required=True)
    cover_image = fields.Image(string="Cover image", max_width=1920, max_height=1920)
    account_id = fields.Many2one(
        "social.account", string="X account", required=True, ondelete="restrict",
        domain="[('media_type', '=', 'twitter'), ('is_pro_account', '=', True)]",
        help="Only X accounts flagged as Pro accounts can publish Articles.")
    company_id = fields.Many2one(related="account_id.company_id", store=True)
    post_method = fields.Selection([
        ("now", "Send now"),
        ("scheduled", "Schedule later")],
        string="When", default="now", required=True, copy=False,
        help="Publish the Article immediately or schedule it at a later time.")
    scheduled_date = fields.Datetime(string="Scheduled date", copy=False)
    utm_campaign_id = fields.Many2one(
        "utm.campaign", string="Campaign", ondelete="set null",
        domain="[('is_auto_campaign', '=', False)]")
    twitter_fixed_reply_template = fields.Char(
        related="utm_campaign_id.twitter_fixed_reply_template")
    twitter_reply_url = fields.Char(
        string="Reply URL for X",
        help="URL posted on X after the fixed reply of the campaign, as a reply to the "
        "first comment, or to the post of the Article when there is no first comment.")
    twitter_first_comment = fields.Text(
        string="First comment",
        help="Text posted on X as the first reply to the post of the published Article. "
        "Its links are tracked like the ones of the campaign reply.")
    state = fields.Selection([
        ("draft", "Draft"),
        ("scheduled", "Scheduled"),
        ("published", "Published"),
        ("error", "Error")],
        string="Status", default="draft", required=True, readonly=True, copy=False)
    error_message = fields.Text(string="Error message", readonly=True, copy=False)
    twitter_article_id = fields.Char(string="X Article id", readonly=True, copy=False)
    twitter_post_id = fields.Char(string="X post id", readonly=True, copy=False)
    twitter_url = fields.Char(string="X link", readonly=True, copy=False)
    twitter_first_comment_post_id = fields.Char(string="First comment X post id", readonly=True, copy=False)
    twitter_reply_post_id = fields.Char(string="Campaign reply X post id", readonly=True, copy=False)
    twitter_comments_pending = fields.Boolean(
        string="Comments pending", compute="_compute_twitter_comments_pending",
        help="Technical: the Article is published, but its first comment or campaign reply "
        "failed and is not on X yet.")

    @api.depends("state", "error_message", "twitter_post_id", "twitter_first_comment",
                 "twitter_first_comment_post_id", "twitter_fixed_reply_template", "twitter_reply_url",
                 "twitter_reply_post_id")
    def _compute_twitter_comments_pending(self):
        for article in self:
            # Only after an error: Articles published before the ids of the comments were
            # stored have none, and posting their comments again would duplicate them
            article.twitter_comments_pending = bool(
                article.state == "published" and article.error_message and article.twitter_post_id
                and article._get_twitter_pending_comment_types()
            )

    @api.constrains("account_id")
    def _check_account_id(self):
        for article in self:
            if article.account_id.media_type != "twitter" or not article.account_id.is_pro_account:
                raise ValidationError(_(
                    "Articles can only be published with an X account flagged as Pro account "
                    "(%(account)s is not).", account=article.account_id.display_name))

    @api.constrains("state", "scheduled_date")
    def _check_scheduled_date(self):
        # Only scheduled Articles: an Article in error may keep a date of the past
        for article in self.filtered(lambda article: article.state == "scheduled"):
            if not article.scheduled_date:
                raise ValidationError(_("Set the scheduled date of the Article \"%s\".", article.title))
            if article.scheduled_date < fields.Datetime.now():
                raise ValidationError(_(
                    "The scheduled date of the Article \"%s\" cannot be in the past.", article.title))

    def write(self, vals):
        result = super().write(vals)
        if vals.get("scheduled_date") or vals.get("state") == "scheduled":
            self.filtered(lambda article: article.state == "scheduled")._trigger_twitter_publication()
        return result

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------

    def action_publish(self):
        # Everything is checked before anything is sent to X
        for article in self:
            article._check_twitter_publishable()
        # Published now: a schedule set before no longer applies (as `social.post.action_post`)
        self.filtered(lambda article: article.state == "scheduled").write({"state": "draft"})
        self.filtered(lambda article: article.post_method == "scheduled").write({
            "post_method": "now",
            "scheduled_date": False,
        })
        self._publish_twitter_articles()

    def action_schedule(self):
        for article in self:
            article._check_twitter_publishable()
        self.write({"state": "scheduled", "post_method": "scheduled", "error_message": False})

    def action_set_draft(self):
        # Also cancels the schedule of a scheduled Article
        self.filtered(lambda article: article.state in ("error", "scheduled")).write({
            "state": "draft",
            "error_message": False,
        })

    def action_retry_comments(self):
        """Post the first comment and/or the campaign reply that failed, after the last one on X."""
        for article in self.filtered("twitter_comments_pending"):
            comments = article._prepare_twitter_comments()
            self._commit_twitter_progress()
            article.error_message = False
            article._post_twitter_comments(comments)
            self._commit_twitter_progress()

    @api.model
    def _cron_publish_scheduled(self):
        """Publish the scheduled Articles whose date has come.

        Each Article is checked and published on its own: one that cannot be
        published anymore (e.g. its account is no longer Pro), or that fails
        unexpectedly, goes to error without blocking the others.
        """
        articles = self.search([
            ("state", "=", "scheduled"),
            ("scheduled_date", "<=", fields.Datetime.now()),
        ])
        for article in articles:
            try:
                article._check_twitter_publishable()
            except (UserError, ValidationError) as error:
                article.write({"state": "error", "error_message": str(error)})
                self._commit_twitter_progress()
                continue
            try:
                article._publish_twitter_articles()
            except Exception as error:  # noqa: BLE001 - one Article must not block the others
                _logger.exception("Scheduled publication of the X Article %s failed", article.id)
                article._set_twitter_unexpected_error(error)
            self._commit_twitter_progress()

    # ------------------------------------------------------------
    # Publication
    # ------------------------------------------------------------

    def _check_twitter_publishable(self):
        self.ensure_one()
        if self.state == "published":
            raise UserError(_("The Article \"%s\" is already published.", self.title))
        # Checked again here: the account may no longer be Pro since the Article was created
        self._check_account_id()
        if not html_to_content_state(self.body)["blocks"]:
            raise UserError(_("The body of the Article \"%s\" is empty.", self.title))

    def _set_twitter_unexpected_error(self, error):
        """Show an unexpected error on this Article, back to its last committed state."""
        self.ensure_one()
        if not modules.module.current_test:
            # The transaction may be aborted; the progress is committed at each step
            self.env.cr.rollback()
        self.invalidate_recordset()
        if self.state == "published":
            # Already on X: only the comments are missing, publishing it again would duplicate it
            self.error_message = str(error)
        else:
            self.write({"state": "error", "error_message": str(error)})

    def _trigger_twitter_publication(self):
        cron = self.env.ref("social_twitter_extended.ir_cron_x_article_scheduled", raise_if_not_found=False)
        dates = set(self.mapped("scheduled_date")) - {False}
        if cron and dates:
            cron._trigger(at=dates)

    def _commit_twitter_progress(self):
        # Same guard as `social.post._action_post`: never commit during tests
        if not modules.module.current_test:
            self.env.cr.commit()

    def _publish_twitter_articles(self):
        for article in self:
            # Tracked and committed before publishing: X fetches the links of the
            # comments to build their cards, the link trackers must exist by then
            comments = article._prepare_twitter_comments()
            self._commit_twitter_progress()
            article._publish_on_twitter(comments)
            # An Article published on X stays published here, even if a later one fails
            self._commit_twitter_progress()

    def _publish_on_twitter(self, comments=None):
        """Upload the cover, create the draft, publish it, then post the comments.

        On error, the raw response of X is stored in `error_message`.

        :param comments: see `_prepare_twitter_comments`
        """
        self.ensure_one()
        account = self.account_id
        try:
            payload = {
                "title": self.title,
                "content_state": html_to_content_state(self.body),
            }
            if self.cover_image:
                payload["cover_media"] = self._upload_twitter_cover(account)

            draft = self._twitter_articles_request(account, "/2/articles/draft", payload)
            if not draft.get("id"):
                raise TwitterApiError(_("X did not return the id of the draft: %s", json.dumps(draft)))
            self.twitter_article_id = draft["id"]
            published = self._twitter_articles_request(
                account, f"/2/articles/{self.twitter_article_id}/publish")
        except (TwitterApiError, UserError) as error:
            self.write({"state": "error", "error_message": str(error)})
            return

        post_id = published.get("post_id")
        if not post_id:
            # X answered the publication with a success: the Article stays published,
            # so that publishing it again does not duplicate it on X
            self.write({
                "state": "published",
                "error_message": _(
                    "The Article was published, but X did not return the id of its post "
                    "(no link to it, and no comments): %(response)s",
                    response=json.dumps(published)),
            })
            return
        self.write({
            "state": "published",
            "error_message": False,
            "twitter_post_id": post_id,
            "twitter_url": f"https://x.com/i/status/{post_id}",
        })
        # Committed before the comments: the Article is on X, it must never be published again
        self._commit_twitter_progress()
        self._post_twitter_comments(comments or [])

    # ------------------------------------------------------------
    # Comments: first comment, then campaign reply, chained to the post
    # ------------------------------------------------------------

    def _get_twitter_pending_comment_types(self):
        """Types of the comments to post that are not on X yet, in publication order."""
        self.ensure_one()
        types = []
        if self.twitter_first_comment and self.twitter_first_comment.strip() \
                and not self.twitter_first_comment_post_id:
            types.append("first_comment")
        if self.twitter_fixed_reply_template and self.twitter_reply_url and not self.twitter_reply_post_id:
            types.append("reply")
        return types

    def _get_twitter_utm_values(self):
        self.ensure_one()
        return {
            "campaign_id": self.utm_campaign_id.id,
            "medium_id": self.account_id.utm_medium_id.id,
        }

    def _prepare_twitter_comments(self):
        """Return the comments not on X yet as [(type, text)], with their tracked links.

        Called before anything is sent to X (and before a commit), so the link
        trackers exist when X fetches the links.
        """
        self.ensure_one()
        comments = []
        for comment_type in self._get_twitter_pending_comment_types():
            if comment_type == "first_comment":
                text = self.env["mail.render.mixin"].sudo()._shorten_links_text(
                    self.twitter_first_comment.strip(), self._get_twitter_utm_values())
                # Mentions handling of X posts, as for the main message of a post
                text = self.env["social.post"]._prepare_post_content(text, "twitter")
            else:
                text = self._prepare_twitter_reply_message()
            if text:
                comments.append((comment_type, text))
        return comments

    def _prepare_twitter_reply_message(self):
        """Return the text of the campaign reply of this Article, with its tracked link, or False."""
        self.ensure_one()
        return self.account_id._twitter_prepare_campaign_reply(
            self.utm_campaign_id, self.twitter_reply_url, utm_values=self._get_twitter_utm_values())

    def _post_twitter_comments(self, comments):
        """Post `comments` as a chain under the last post of this Article already on X.

        The id of each one is stored as soon as X returns it. On error, the
        Article stays published and the error is shown on it.
        """
        self.ensure_one()
        id_fields = {"first_comment": "twitter_first_comment_post_id", "reply": "twitter_reply_post_id"}
        last_post_id = self.twitter_first_comment_post_id or self.twitter_post_id
        for comment_type, text in comments:
            try:
                last_post_id = self.account_id._twitter_post_tweet(text, in_reply_to_tweet_id=last_post_id)
            except TwitterApiError as error:
                if comment_type == "first_comment":
                    message = _("The Article was published, but the first comment failed: %(error)s",
                                error=str(error))
                else:
                    message = _("The Article was published, but the campaign reply failed: %(error)s",
                                error=str(error))
                self.error_message = message
                return
            self[id_fields[comment_type]] = last_post_id

    # ------------------------------------------------------------
    # X API
    # ------------------------------------------------------------

    def _upload_twitter_cover(self, account):
        """Upload the cover image to X and return the `cover_media` value of the draft."""
        image_bytes = base64.b64decode(self.cover_image)
        media_id, media_category = account._twitter_upload_image(image_bytes, guess_mimetype(image_bytes))
        return {"media_id": media_id, "media_category": media_category}

    @api.model
    def _twitter_articles_request(self, account, path, payload=None):
        """POST to an Articles endpoint of X and return the `data` of the response.

        :raise TwitterApiError: with the raw response of X when it fails
        """
        url = f"{TWITTER_ARTICLES_ENDPOINT}{path}"
        try:
            result = requests.post(
                url,
                json=payload,
                headers=account._get_twitter_oauth_header(url),
                timeout=15,
            )
        except requests.RequestException as error:
            raise TwitterApiError(str(error)) from error
        data = account._twitter_response_data(result) if result.ok else {}
        if not data:
            # Errors can also come with a 2xx status, in the `errors` key, or as a non-JSON body
            raise TwitterApiError(account._twitter_error_text(result))
        return data
