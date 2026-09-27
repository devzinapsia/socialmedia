import json
import time

import requests

from odoo import _, fields, models
from odoo.addons.social_twitter.models.social_account import TWITTER_IMAGES_UPLOAD_ENDPOINT
from odoo.tools.urls import urljoin as url_join

# Same endpoint as the core upload (https://api.x.com/2/media/upload)
TWITTER_MEDIA_UPLOAD_ENDPOINT = TWITTER_IMAGES_UPLOAD_ENDPOINT
# Images are usually ready at once; this bounds the wait to about 30 seconds
TWITTER_MEDIA_STATUS_MAX_CHECKS = 10


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

    def _twitter_upload_image(self, image_bytes, mimetype):
        """Upload an image through the v2 media upload of X and return its media id.

        Same endpoints as the core (`_format_images_twitter`), but every step is
        checked and the raw response of X is kept on error: the core only reads
        the `error` key, while the v2 API answers with `title` / `detail`, so its
        message is always empty. Also waits for X to process the media when
        `processing_info` is returned.

        :raise TwitterApiError: with the failed step and the raw response of X
        """
        self.ensure_one()
        category = "tweet_gif" if mimetype == "image/gif" else "tweet_image"

        def _check(step, result):
            if not result.ok:
                raise TwitterApiError(_(
                    "Image upload failed (%(step)s, HTTP %(status)s): %(response)s",
                    step=step, status=result.status_code, response=result.text or "-",
                ))
            return result

        try:
            url = f"{TWITTER_MEDIA_UPLOAD_ENDPOINT}/initialize"
            result = _check("initialize", requests.post(
                url,
                json={"total_bytes": len(image_bytes), "media_type": mimetype, "media_category": category},
                headers=self._get_twitter_oauth_header(url),
                timeout=15,
            ))
            media_id = result.json()["data"]["id"]

            url = f"{TWITTER_MEDIA_UPLOAD_ENDPOINT}/{media_id}/append"
            _check("append", requests.post(
                url,
                files={"media": image_bytes},
                data={"segment_index": 0},
                headers=self._get_twitter_oauth_header(url),
                timeout=30,
            ))

            url = f"{TWITTER_MEDIA_UPLOAD_ENDPOINT}/{media_id}/finalize"
            result = _check("finalize", requests.post(
                url, headers=self._get_twitter_oauth_header(url), timeout=15))
            processing = (result.json() or {}).get("data", {}).get("processing_info")
            self._twitter_wait_media_processing(media_id, processing, _check)
        except requests.RequestException as error:
            raise TwitterApiError(_("Image upload failed: %(error)s", error=str(error))) from error
        return media_id, category

    def _twitter_wait_media_processing(self, media_id, processing, check):
        """Poll the upload status until X has processed the media (or failed)."""
        for _attempt in range(TWITTER_MEDIA_STATUS_MAX_CHECKS):
            state = (processing or {}).get("state")
            if not state or state == "succeeded":
                return
            if state == "failed":
                raise TwitterApiError(_(
                    "Image upload failed (processing): %(response)s", response=json.dumps(processing)))
            time.sleep(min(processing.get("check_after_secs") or 1, 5))
            params = {"command": "STATUS", "media_id": media_id}
            result = check("status", requests.get(
                TWITTER_MEDIA_UPLOAD_ENDPOINT,
                params=params,
                headers=self._get_twitter_oauth_header(TWITTER_MEDIA_UPLOAD_ENDPOINT, params=params, method="GET"),
                timeout=15,
            ))
            processing = (result.json() or {}).get("data", {}).get("processing_info")
        raise TwitterApiError(_("Image upload failed: X did not finish processing the image in time."))

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
