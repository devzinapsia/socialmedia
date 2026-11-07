import json
import time

import requests

from odoo import _, api, fields, models
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
        tweet_id = self._twitter_response_data(result).get("id") if result.ok else False
        if not tweet_id:
            # Also when X answers with a success status but no post (e.g. `errors` only)
            raise TwitterApiError(self._twitter_error_text(result))
        return tweet_id

    @api.model
    def _twitter_response_data(self, result):
        """Return the `data` dict of an X response, or {} when the body has none.

        Never raises: a body that is not JSON (e.g. an HTML error page of a
        proxy) or that has no `data` object gives {}.
        """
        try:
            body = result.json()
        except ValueError:  # also the JSONDecodeError of requests
            return {}
        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else {}

    @api.model
    def _twitter_error_text(self, result):
        """The raw answer of X to show as error, never empty."""
        return result.text or _("Empty answer from X (HTTP %s)", result.status_code)

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
                raise _upload_error(step, result)
            return result

        def _upload_error(step, result):
            # `self.env._`: a nested function has no `self` for `_` to detect the language
            return TwitterApiError(self.env._(
                "Image upload failed (%(step)s, HTTP %(status)s): %(response)s",
                step=step, status=result.status_code, response=result.text or "-",
            ))

        try:
            url = f"{TWITTER_MEDIA_UPLOAD_ENDPOINT}/initialize"
            result = _check("initialize", requests.post(
                url,
                json={"total_bytes": len(image_bytes), "media_type": mimetype, "media_category": category},
                headers=self._get_twitter_oauth_header(url),
                timeout=15,
            ))
            media_id = self._twitter_response_data(result).get("id")
            if not media_id:
                raise _upload_error("initialize", result)

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
            processing = self._twitter_response_data(result).get("processing_info")
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
            processing = self._twitter_response_data(result).get("processing_info")
        raise TwitterApiError(_("Image upload failed: X did not finish processing the image in time."))

    def _twitter_prepare_campaign_reply(self, campaign, reply_url, utm_values=None):
        """Return the text of the campaign reply: the fixed reply of `campaign` followed by `reply_url`.

        Shared by posts/threads and Articles. Called before anything is sent
        to X, so the link tracker of the URL is committed when X fetches it to
        build the link card of the reply.

        :param utm_values: UTM values used to track the link, as for the main message
        :return: the text, or False when there is nothing to reply
        """
        self.ensure_one()
        template = campaign.sudo().twitter_fixed_reply_template
        if not (template and reply_url):
            return False
        body = f"{template.strip()} {reply_url.strip()}"
        if utm_values:
            body = self.env["mail.render.mixin"].sudo()._shorten_links_text(body, utm_values)
        return body
