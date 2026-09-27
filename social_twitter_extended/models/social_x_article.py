import base64

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.mimetypes import guess_mimetype

from ..tools.html_to_content_state import html_to_content_state
from .social_account import TwitterApiError

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
    utm_campaign_id = fields.Many2one(
        "utm.campaign", string="Campaign", ondelete="set null",
        domain="[('is_auto_campaign', '=', False)]")
    twitter_fixed_reply_template = fields.Char(
        related="utm_campaign_id.twitter_fixed_reply_template")
    twitter_reply_url = fields.Char(
        string="Reply URL for X",
        help="URL posted on X after the fixed reply of the campaign, as a reply to the "
        "post of the published Article.")
    state = fields.Selection([
        ("draft", "Draft"),
        ("published", "Published"),
        ("error", "Error")],
        string="Status", default="draft", required=True, readonly=True, copy=False)
    error_message = fields.Text(string="Error message", readonly=True, copy=False)
    twitter_article_id = fields.Char(string="X Article id", readonly=True, copy=False)
    twitter_post_id = fields.Char(string="X post id", readonly=True, copy=False)
    twitter_url = fields.Char(string="X link", readonly=True, copy=False)

    @api.constrains("account_id")
    def _check_account_id(self):
        for article in self:
            if article.account_id.media_type != "twitter" or not article.account_id.is_pro_account:
                raise ValidationError(_(
                    "Articles can only be published with an X account flagged as Pro account "
                    "(%(account)s is not).", account=article.account_id.display_name))

    def action_publish(self):
        for article in self:
            if article.state == "published":
                raise UserError(_("The Article \"%s\" is already published.", article.title))
            # Checked again here: the account may no longer be Pro since the Article was created
            article._check_account_id()
            if not html_to_content_state(article.body)["blocks"]:
                raise UserError(_("The body of the Article \"%s\" is empty.", article.title))
        for article in self:
            article._publish_on_twitter()

    def action_set_draft(self):
        self.filtered(lambda article: article.state == "error").write({
            "state": "draft",
            "error_message": False,
        })

    def _publish_on_twitter(self):
        """Upload the cover, create the draft, publish it, then post the campaign reply.

        On error, the raw response of X is stored in `error_message`.
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
            self.twitter_article_id = draft["id"]
            published = self._twitter_articles_request(
                account, f"/2/articles/{self.twitter_article_id}/publish")
        except (TwitterApiError, UserError) as error:
            self.write({"state": "error", "error_message": str(error)})
            return

        post_id = published["post_id"]
        self.write({
            "state": "published",
            "error_message": False,
            "twitter_post_id": post_id,
            "twitter_url": f"https://x.com/i/status/{post_id}",
        })

        try:
            account._twitter_post_campaign_reply(
                self.utm_campaign_id, self.twitter_reply_url, post_id,
                utm_values={
                    "campaign_id": self.utm_campaign_id.id,
                    "medium_id": account.utm_medium_id.id,
                },
            )
        except TwitterApiError as error:
            # The Article stays published: only the reply is missing
            self.error_message = _(
                "The Article was published, but the campaign reply failed: %(error)s",
                error=str(error))

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
        if not result.ok:
            raise TwitterApiError(result.text)
        response = result.json()
        if not response.get("data"):
            # Errors can also come with a 2xx status, in the `errors` key
            raise TwitterApiError(result.text)
        return response["data"]
