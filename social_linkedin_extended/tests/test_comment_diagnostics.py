from unittest.mock import patch

import requests

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.social.tests.tools import mock_void_external_calls

from .common import ACCESS_TOKEN, CLIENT_SECRET, SocialLinkedinExtendedCase

POST_URN = "urn:li:share:42"


@tagged("post_install", "-at_install")
class TestCommentDiagnostics(SocialLinkedinExtendedCase):

    def _open_wizard(self, account=None, user=None):
        # The reports are checked in English, whatever the language of the database
        env = self.env(user=user or self.social_manager, context=dict(self.env.context, lang="en_US"))
        action = (account or self.account).with_env(env).action_open_linkedin_comment_test()
        return env[action["res_model"]].with_context(**action["context"]).create({})

    def _run(self, wizard, answers=None):
        with self.mock_linkedin_api(answers) as api:
            wizard.action_run_test()
        return api, wizard.report

    def _publish_live_post(self, account, post_urn):
        return self.env["social.live.post"].create({
            "post_id": self.social_post.id,
            "account_id": account.id,
            "state": "posted",
            "linkedin_post_id": post_urn,
        })

    def test_default_post_urn_is_last_published_post(self):
        self._publish_live_post(self.account, "urn:li:share:1")
        self._publish_live_post(self.account, "urn:li:ugcPost:2")
        self._publish_live_post(self.social_accounts[1], "urn:li:share:3")
        self.assertEqual(self._open_wizard().post_urn, "urn:li:ugcPost:2")
        with mock_void_external_calls():
            account_without_posts = self.env["social.account"].create({
                "media_id": self._get_social_media().id, "name": "Without posts"})
        self.assertFalse(self._open_wizard(account_without_posts).post_urn)

    def test_default_post_urn_falls_back_to_feed(self):
        with mock_void_external_calls():
            stream = self.env["social.stream"].create({
                "media_id": self._get_social_media().id,
                "stream_type_id": self.env.ref("social_linkedin.stream_type_linkedin_company_post").id,
                "account_id": self.account.id,
            })
        self.env["social.stream.post"].create([
            {"stream_id": stream.id, "linkedin_post_urn": "urn:li:share:old", "published_date": "2026-01-01 10:00:00"},
            {"stream_id": stream.id, "linkedin_post_urn": "urn:li:ugcPost:new", "published_date": "2026-02-01 10:00:00"},
        ])
        self.assertEqual(self._open_wizard().post_urn, "urn:li:ugcPost:new")
        self._publish_live_post(self.account, POST_URN)
        self.assertEqual(self._open_wizard().post_urn, POST_URN, "A post published from Odoo comes first")

    def test_success_without_comment_id(self):
        """A success without id: a comment probably exists, the report must not say otherwise."""
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        api, report = self._run(wizard, {1: (201, {"created": {"time": 1}})})
        self.assertEqual(len(api.calls), 1, "No id: nothing can be deleted")
        self.assertIn("HTTP 201, ", report)
        self.assertIn("LinkedIn answered with a success but without the id of the comment", report)
        self.assertIn("A comment was probably created", report)
        self.assertNotIn("Skipped: no comment was created.", report)
        self.assertIn("Result: LinkedIn accepted the comment but did not return its id", report)

    def test_success_creates_then_deletes_the_comment(self):
        self._publish_live_post(self.account, POST_URN)
        wizard = self._open_wizard()
        api, report = self._run(wizard)

        self.assertEqual(len(api.calls), 2, "Without own LinkedIn app: no introspection, create + delete")
        create, delete = api.calls
        self.assertEqual(create["method"], "POST")
        self.assertTrue(create["url"].endswith("/rest/socialActions/urn%3Ali%3Ashare%3A42/comments"))
        self.assertEqual(create["json"], {
            "actor": "urn:li:organization:111",
            "object": POST_URN,
            "message": {"text": "Odoo comment test, will be deleted"},
        })
        self.assertEqual(create["headers"]["LinkedIn-Version"], "202610")
        self.assertEqual(create["headers"]["Authorization"], f"Bearer {ACCESS_TOKEN}")
        self.assertEqual(delete["method"], "DELETE")
        self.assertTrue(delete["url"].endswith("/rest/socialActions/urn%3Ali%3Ashare%3A42/comments/7001"))
        self.assertEqual(delete["params"], {"actor": "urn:li:organization:111"})
        self.assertEqual(delete["headers"]["LinkedIn-Version"], "202610")

        self.assertEqual(wizard.state, "done")
        for expected in ("Date (UTC): ", "Author URN: urn:li:organization:111",
                         "API version sent: 202610", "Access token: present (never shown)",
                         "Expiry: unknown", "Granted permissions: unknown",
                         "HTTP 201, ", "Comment id: 7001", "Comment URN: urn:li:comment:(urn:li:activity:42,7001)",
                         "HTTP 204, ", "Test comment deleted.", "Result: OK"):
            self.assertIn(expected, report)
        self.assertIn(
            f"API version of the core social_linkedin module: {self.account._linkedin_extended_core_api_version()}",
            report)
        self.assertNotIn(ACCESS_TOKEN, report)
        self.assertFalse(self.account.is_media_disconnected)

    def test_missing_permission(self):
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        api, report = self._run(wizard, {1: (403, {
            "status": 403, "serviceErrorCode": 100,
            "message": "Not enough permissions to access: partnerApiSocialActions.CREATE.20261001",
        })})

        self.assertEqual(len(api.calls), 1, "Nothing to delete when the comment was not created")
        self.assertIn("HTTP 403, ", report)
        self.assertIn("Not enough permissions to access: partnerApiSocialActions.CREATE", report)
        self.assertIn("Result: NOT POSSIBLE, missing permission", report)
        self.assertIn("w_organization_social_feed", report)
        self.assertIn("Skipped: no comment was created.", report)
        self.assertFalse(self.account.is_media_disconnected,
                         "Unlike the core comment methods, a failed test never disconnects the account")

    def test_invalid_token(self):
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        _api, report = self._run(wizard, {1: (401, {"status": 401, "serviceErrorCode": 65600,
                                                     "message": "Invalid access token"})})
        self.assertIn("Result: NOT POSSIBLE, the access token is invalid, expired or revoked", report)
        self.assertFalse(self.account.is_media_disconnected)

    def test_rejected_api_version(self):
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        _api, report = self._run(wizard, {1: (426, {"status": 426, "code": "NONEXISTENT_VERSION",
                                                     "message": "Requested version 20261000 is not active"})})
        self.assertIn("rejected the API version 202610", report)
        self.assertIn("social_linkedin_extended.api_version", report)

    def test_missing_token_makes_no_call(self):
        self.account.linkedin_access_token = False
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        api, report = self._run(wizard)
        self.assertFalse(api.calls)
        self.assertIn("Access token: missing", report)
        self.assertIn("Result: the account has no access token", report)

    def test_comment_not_deleted_is_reported(self):
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        _api, report = self._run(wizard, {2: (500, {"status": 500, "message": "Internal Server Error"})})
        self.assertIn("HTTP 500, ", report)
        self.assertIn("WARNING: the test comment was NOT deleted", report)
        self.assertIn("Result: this account can comment, but the test comment could not be deleted.", report)

    def test_network_error(self):
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        with patch.object(requests, "request", side_effect=requests.exceptions.ConnectTimeout("timed out")):
            wizard.action_run_test()
        self.assertIn("no HTTP answer (network error)", wizard.report)
        self.assertIn("ConnectTimeout: timed out", wizard.report)
        self.assertIn("Result: LinkedIn could not be reached", wizard.report)

    def test_secrets_never_in_report_or_logs(self):
        self.env["ir.config_parameter"].sudo().set_param("social.linkedin_client_secret", CLIENT_SECRET)
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        echoed = (f"Invalid header Authorization: Bearer {ACCESS_TOKEN}; access_token={ACCESS_TOKEN}; "
                  f"secret {CLIENT_SECRET}; " + "x" * 1000)
        with self.assertLogs("odoo.addons.social_linkedin_extended", level="INFO") as logs:
            _api, report = self._run(wizard, {1: (400, echoed)})
        self.assertNotIn(ACCESS_TOKEN, report)
        self.assertNotIn(CLIENT_SECRET, report)
        self.assertIn("[hidden]", report)
        error_line = next(line for line in report.splitlines() if line.startswith("LinkedIn error: "))
        self.assertLessEqual(len(error_line), len("LinkedIn error: ") + 500 + len("..."),
                             "LinkedIn error bodies are cut")
        self.assertTrue(logs.output)
        self.assertFalse([line for line in logs.output if ACCESS_TOKEN in line or CLIENT_SECRET in line])

    def test_introspection_with_own_linkedin_app(self):
        config = self.env["ir.config_parameter"].sudo()
        config.set_param("social.linkedin_use_own_account", "True")
        config.set_param("social.linkedin_app_id", "my-app-id")
        config.set_param("social.linkedin_client_secret", CLIENT_SECRET)
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        api, report = self._run(wizard, {1: (200, {
            "active": True, "status": "active", "client_id": "my-app-id",
            "scope": "r_organization_social,w_organization_social_feed", "expires_at": 1798761600,
        })})

        self.assertEqual(len(api.calls), 3)
        introspect = api.calls[0]
        self.assertEqual(introspect["url"], "https://www.linkedin.com/oauth/v2/introspectToken")
        self.assertEqual(introspect["data"], {
            "client_id": "my-app-id", "client_secret": CLIENT_SECRET, "token": ACCESS_TOKEN})
        self.assertIn("Token introspection: HTTP 200, ", report)
        self.assertIn("Token active: Yes", report)
        self.assertIn("Expiry (UTC): 2027-01-01 00:00:00", report)
        self.assertIn("Granted permissions: r_organization_social,w_organization_social_feed", report)
        self.assertNotIn(CLIENT_SECRET, report)
        self.assertNotIn(ACCESS_TOKEN, report)

    def test_api_version_parameter(self):
        config = self.env["ir.config_parameter"].sudo()
        core_version = self.account._linkedin_extended_core_api_version()
        self.assertTrue(core_version)
        self.assertEqual(self.account._linkedin_extended_api_version(), "202610")
        config.set_param("social_linkedin_extended.api_version", " 202701 ")
        self.assertEqual(self.account._linkedin_extended_headers()["LinkedIn-Version"], "202701")
        self.assertEqual(self.account._linkedin_bearer_headers()["LinkedIn-Version"], core_version,
                         "The core calls keep their own version")
        with self.assertLogs("odoo.addons.social_linkedin_extended", level="WARNING"):
            config.set_param("social_linkedin_extended.api_version", "latest")
            self.assertEqual(self.account._linkedin_extended_api_version(), core_version)
        config.set_param("social_linkedin_extended.api_version", False)
        self.assertEqual(self.account._linkedin_extended_api_version(), core_version)

    def test_invalid_post_urn(self):
        wizard = self._open_wizard()
        wizard.post_urn = "https://www.linkedin.com/feed/update/123"
        with self.mock_linkedin_api() as api, self.assertRaises(UserError):
            wizard.action_run_test()
        self.assertFalse(api.calls)

    def test_only_social_managers(self):
        with self.assertRaises(AccessError):
            self.account.with_user(self.social_user).action_open_linkedin_comment_test()
        with self.assertRaises(AccessError):
            self.env["social.linkedin.comment.test"].with_user(self.social_user).create({
                "account_id": self.account.id, "post_urn": POST_URN})
        wizard = self._open_wizard()
        wizard.post_urn = POST_URN
        with self.mock_linkedin_api() as api, self.assertRaises(AccessError):
            wizard.with_user(self.social_user).action_run_test()
        self.assertFalse(api.calls)

    def test_not_a_linkedin_account(self):
        other_media = self.env["social.media"].create({"name": "Other", "media_type": False})
        with mock_void_external_calls():
            other_account = self.env["social.account"].create({"media_id": other_media.id, "name": "Other account"})
        with self.assertRaises(UserError):
            other_account.with_user(self.social_manager).action_open_linkedin_comment_test()
