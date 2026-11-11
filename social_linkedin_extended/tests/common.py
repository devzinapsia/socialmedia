import json
from contextlib import contextmanager
from unittest.mock import patch

import requests

from odoo.addons.social.tests.common import SocialCase
from odoo.addons.social.tests.tools import mock_void_external_calls

ACCESS_TOKEN = "AQX-secret-access-token-1234567890"
CLIENT_SECRET = "linkedin-app-client-secret-0987"


class FakeLinkedInApi:
    """Records every request sent to LinkedIn and answers with canned responses.

    :param answers: {call number (1-based): (status code, body, headers)} where body is a
        dict (sent as JSON) or a string; calls without an answer get a generic success
        (201 with a comment for a POST, 204 for a DELETE)
    """

    def __init__(self, answers=None):
        self.calls = []
        self.answers = answers or {}

    def request(self, method, url, params=None, json=None, data=None, headers=None, timeout=None, **kwargs):
        self.calls.append({
            "method": method, "url": url, "params": params, "json": json,
            "data": data, "headers": dict(headers or {}),
        })
        number = len(self.calls)
        if number in self.answers:
            status_code, body, response_headers = (*self.answers[number], {})[:3]
        elif method == "POST":
            status_code, response_headers = 201, {"x-restli-id": "7001"}
            body = {"id": "7001", "commentUrn": "urn:li:comment:(urn:li:activity:42,7001)",
                    "created": {"time": 1}}
        else:
            status_code, body, response_headers = 204, "", {}
        return self._response(status_code, body, response_headers)

    @staticmethod
    def _response(status_code, body, headers):
        response = requests.Response()
        response.status_code = status_code
        response._content = (json.dumps(body) if isinstance(body, dict) else body).encode()
        response.headers.update(headers)
        return response

    def calls_to(self, fragment):
        return [call for call in self.calls if fragment in call["url"]]


class SocialLinkedinExtendedCase(SocialCase):
    """Two LinkedIn organization accounts, every external call disabled."""

    @classmethod
    def setUpClass(cls):
        with mock_void_external_calls():
            super().setUpClass()
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
    def mock_linkedin_api(self, answers=None):
        api = FakeLinkedInApi(answers)
        with patch.object(requests, "request", side_effect=api.request):
            yield api
