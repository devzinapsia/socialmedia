import requests

from odoo import fields, models
from odoo.tools.urls import urljoin as url_join


class TwitterApiError(Exception):
    """A call to the X API failed; the message is the raw error returned by X."""


class SocialAccount(models.Model):
    _inherit = "social.account"

    is_pro_account = fields.Boolean(
        string="Pro account (extended character limit and Articles)",
        help="Configuration flag only: Odoo does not check the real X subscription. "
        "When set, posts are no longer checked against the standard X character "
        "limit in Odoo and X itself accepts or rejects the text.",
    )

    def _twitter_post_tweet(self, text, in_reply_to_tweet_id=None):
        """Publish a text post on this X account and return its id.

        Same endpoint, payload and OAuth signature as the core publication
        (`social.live.post._post_twitter`) and replies (`social.stream.post
        ._twitter_post_tweet`), but usable outside of an HTTP request (cron).

        :raise TwitterApiError: with the raw response of X when it fails
        """
        self.ensure_one()
        endpoint_url = url_join(self.env["social.media"]._TWITTER_ENDPOINT, "/2/tweets")
        payload = {"text": text}
        if in_reply_to_tweet_id:
            payload["reply"] = {"in_reply_to_tweet_id": in_reply_to_tweet_id}
        try:
            result = requests.post(
                endpoint_url,
                json=payload,
                headers=self._get_twitter_oauth_header(endpoint_url),
                timeout=5,
            )
        except requests.RequestException as error:
            raise TwitterApiError(str(error)) from error
        if not result.ok:
            raise TwitterApiError(result.text)
        return result.json()["data"]["id"]

    def _twitter_post_campaign_reply(self, campaign, reply_url, in_reply_to_tweet_id, utm_values=None):
        """Reply to `in_reply_to_tweet_id` with the fixed reply of `campaign` followed by `reply_url`.

        Shared by posts/threads and Articles, called right after their own
        publication with the id of the last post of their chain.

        :param utm_values: UTM values used to track the link, as for the main message
        :return: the id of the reply, or False when there is nothing to reply
        :raise TwitterApiError: with the raw response of X when it fails
        """
        self.ensure_one()
        template = campaign.sudo().twitter_fixed_reply_template
        if not (template and reply_url and in_reply_to_tweet_id):
            return False
        body = f"{template.strip()} {reply_url.strip()}"
        if utm_values:
            body = self.env["mail.render.mixin"].sudo()._shorten_links_text(body, utm_values)
        return self._twitter_post_tweet(body, in_reply_to_tweet_id=in_reply_to_tweet_id)
