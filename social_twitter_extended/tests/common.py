from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from odoo.addons.link_tracker.models.link_tracker import LinkTracker
from odoo.addons.social.tests.common import SocialCase
from odoo.addons.social_twitter.models.social_account import SocialAccount
from odoo.addons.social_twitter.models.social_stream import SocialStream


class FakeXApi:
    """Records every POST sent to X and answers with incremental ids.

    :param fail_on: {call number (1-based): error text} to answer with an error
    :param json_on: {call number (1-based): body} to answer a successful call with a given body
    """

    def __init__(self, fail_on=None, json_on=None):
        self.calls = []
        self.fail_on = fail_on or {}
        self.json_on = json_on or {}

    def post(self, url, *args, **kwargs):
        return self._answer("POST", url, **kwargs)

    def get(self, url, *args, **kwargs):
        return self._answer("GET", url, **kwargs)

    def _answer(self, method, url, **kwargs):
        self.calls.append({
            "method": method, "url": url, "json": kwargs.get("json"),
            "files": kwargs.get("files"), "params": kwargs.get("params"),
        })
        number = len(self.calls)
        response = MagicMock()
        if number in self.fail_on:
            response.ok = False
            response.status_code = 403
            response.text = self.fail_on[number]
            response.json.return_value = {"detail": self.fail_on[number]}
        else:
            response.ok = True
            response.status_code = 200
            # `id` for posts, drafts and media, `post_id` for published Articles
            response.json.return_value = self.json_on.get(
                number, {"data": {"id": str(1000 + number), "post_id": str(2000 + number)}})
        return response

    @property
    def tweet_calls(self):
        return [call for call in self.calls if call["url"].endswith("/2/tweets")]


class SocialTwitterExtendedCase(SocialCase):
    """Base case with two X accounts and every external X call disabled."""

    @classmethod
    def setUpClass(cls):
        with patch.object(SocialAccount, "_compute_statistics", lambda x: None), \
                patch.object(SocialAccount, "_create_default_stream_twitter", lambda *args, **kwargs: None), \
                patch.object(SocialStream, "_fetch_stream_data", lambda *args, **kwargs: None):
            super().setUpClass()
        cls.social_accounts.write({
            "twitter_oauth_token": "TOKEN",
            "twitter_oauth_token_secret": "SECRET",
        })
        cls.social_accounts[0].twitter_user_id = "1234"
        cls.social_accounts[1].twitter_user_id = "5678"
        cls.env["ir.config_parameter"].sudo().set_param("social.twitter_consumer_key", "key")
        cls.env["ir.config_parameter"].sudo().set_param("social.twitter_consumer_secret_key", "secret_key")

    @classmethod
    def _get_social_media(cls):
        return cls.env.ref("social_twitter.social_media_twitter")

    @contextmanager
    def mock_x_api(self, fail_on=None, json_on=None):
        api = FakeXApi(fail_on, json_on)
        with patch("requests.post", side_effect=api.post), \
                patch("requests.get", side_effect=api.get), \
                patch("time.sleep"), \
                patch.object(LinkTracker, "_get_title_from_url", lambda self, url: url):
            yield api
