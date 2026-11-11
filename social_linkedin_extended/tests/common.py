import json
from contextlib import contextmanager
from unittest.mock import patch

import requests

from odoo.addons.link_tracker.models.link_tracker import LinkTracker
from odoo.addons.mail.tools import link_preview
from odoo.addons.social.tests.common import SocialCase
from odoo.addons.social.tests.tools import mock_void_external_calls

ACCESS_TOKEN = "AQX-secret-access-token-1234567890"
CLIENT_SECRET = "linkedin-app-client-secret-0987"


class FakeLinkedInApi:
    """Records every request sent to LinkedIn and answers with canned responses.

    :param answers: {call number (1-based): (status code, body[, headers])}, body being a
        dict (sent as JSON) or a string; used by the diagnostics tests
    :param comment_answers: answers of the successive comment creations (POST .../comments)
    :param lookup_answers: answers of the successive comment lookups (GET .../comments)

    Calls without a canned answer get a success: a post URN for POST /rest/posts, a new
    comment for POST .../comments, no comment for GET .../comments, 204 for a DELETE.
    """

    def __init__(self, answers=None, comment_answers=None, lookup_answers=None):
        self.calls = []
        self.answers = answers or {}
        self.comment_answers = list(comment_answers or [])
        self.lookup_answers = list(lookup_answers or [])

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None, **kwargs):
        self.calls.append({
            "method": method, "url": url, "params": params, "json": json,
            "data": data, "headers": dict(headers or {}),
        })
        number = len(self.calls)
        if number in self.answers:
            return self._response(*(*self.answers[number], {})[:3])
        if method == "POST" and url.endswith("/rest/posts"):
            return self._response(201, "", {"x-restli-id": f"urn:li:share:{8000 + number}"})
        if url.endswith("/comments") and method == "POST":
            if self.comment_answers:
                return self._response(*(*self.comment_answers.pop(0), {})[:3])
            comment_id = str(7000 + number)
            post_urn = (json or {}).get("object", "")
            return self._response(201, {
                "id": comment_id, "actor": (json or {}).get("actor"),
                "commentUrn": f"urn:li:comment:(urn:li:activity:{post_urn.split(':')[-1]},{comment_id})",
                "message": (json or {}).get("message"), "created": {"time": 1},
            }, {"x-restli-id": comment_id})
        if url.endswith("/comments") and method == "GET":
            if self.lookup_answers:
                return self._response(*(*self.lookup_answers.pop(0), {})[:3])
            return self._response(200, {"elements": [], "paging": {"total": 0}}, {})
        if method == "DELETE":
            return self._response(204, "", {})
        return self._response(201, {"id": "7001", "commentUrn": "urn:li:comment:(urn:li:activity:42,7001)",
                                     "created": {"time": 1}}, {"x-restli-id": "7001"})

    @staticmethod
    def _response(status_code, body, headers):
        response = requests.Response()
        response.status_code = status_code
        response._content = (json.dumps(body) if isinstance(body, dict) else body).encode()
        response.headers.update(headers)
        return response

    def calls_to(self, fragment, method=None):
        return [call for call in self.calls
                if fragment in call["url"] and (method is None or call["method"] == method)]

    @property
    def comment_posts(self):
        return [call for call in self.calls if call["method"] == "POST" and call["url"].endswith("/comments")]

    @property
    def comment_lookups(self):
        return [call for call in self.calls if call["method"] == "GET" and call["url"].endswith("/comments")]


class SocialLinkedinExtendedCase(SocialCase):
    """Two LinkedIn organization accounts, every external call disabled."""

    @classmethod
    def setUpClass(cls):
        with mock_void_external_calls():
            super().setUpClass()
        # Reports, errors and chatter messages are checked in English, whatever the
        # language of the database
        cls.env = cls.env(context=dict(cls.env.context, lang="en_US"))
        cls.social_accounts = cls.social_accounts.with_env(cls.env)
        cls.social_post = cls.social_post.with_env(cls.env)
        cls.social_accounts.write({"linkedin_access_token": ACCESS_TOKEN})
        cls.social_accounts[0].linkedin_account_urn = "urn:li:organization:111"
        cls.social_accounts[1].linkedin_account_urn = "urn:li:organization:222"
        cls.account = cls.social_accounts[0]
        cls.env["ir.config_parameter"].sudo().set_param(
            "social_linkedin_extended.api_version", "202610")

    @classmethod
    def _get_social_media(cls):
        return cls.env.ref("social_linkedin.social_media_linkedin")

    @contextmanager
    def mock_linkedin_api(self, answers=None, comment_answers=None, lookup_answers=None):
        """Every HTTP call goes to a FakeLinkedInApi; link titles and previews are not fetched."""
        api = FakeLinkedInApi(answers, comment_answers, lookup_answers)
        with patch.object(requests, "request", side_effect=api.request), \
                patch.object(requests, "get", side_effect=lambda url, **kw: api.request("GET", url, **kw)), \
                patch.object(link_preview, "get_link_preview_from_url", lambda *args, **kwargs: {}), \
                patch.object(LinkTracker, "_get_title_from_url", lambda self, url: url):
            yield api
