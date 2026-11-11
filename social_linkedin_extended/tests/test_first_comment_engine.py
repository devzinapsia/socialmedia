from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time
from psycopg2 import errors as pg_errors

from odoo import fields
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.social.tests.tools import mock_void_external_calls
from odoo.addons.social_linkedin_extended.models.social_account import SocialAccount
from odoo.addons.social_linkedin_extended.models.social_live_post import SocialLivePost

from .common import ACCESS_TOKEN, SocialLinkedinExtendedCase

COMMENT = "Read the full article: https://example.com/article"


@tagged("post_install", "-at_install")
class TestFirstCommentEngine(SocialLinkedinExtendedCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.campaign = cls.env["utm.campaign"].create({"name": "Launch"})
        other_media = cls.env["social.media"].create({"name": "Other", "media_type": False})
        with mock_void_external_calls():
            cls.other_account = cls.env["social.account"].create({
                "media_id": other_media.id, "name": "Other account"})

    def _new_post(self, accounts=None, comment=COMMENT, **values):
        return self.env["social.post"].create({
            "message": "A post without images",
            "account_ids": [(6, 0, (accounts or self.social_accounts).ids)],
            "utm_campaign_id": self.campaign.id,
            "linkedin_first_comment": comment,
            **values,
        })

    def _publish(self, post, **mock_values):
        with self.mock_linkedin_api(**mock_values) as api:
            post._action_post()
        return api

    def _chatter(self, post):
        return post.message_ids.mapped(lambda message: message.body and str(message.body) or "")

    def _assert_comments_posted(self, post, api):
        live_posts = post.live_post_ids.sorted("id")
        self.assertEqual(post.state, "posted")
        self.assertEqual(live_posts.mapped("state"), ["posted", "posted"])
        self.assertEqual(len(api.comment_posts), 2, "One comment per LinkedIn account")
        for live_post, account, call in zip(live_posts, self.social_accounts, api.comment_posts):
            self.assertEqual(call["json"]["actor"], account.linkedin_account_urn, "Same author as the post")
            self.assertEqual(call["json"]["object"], live_post.linkedin_post_id)
            self.assertIn(live_post.linkedin_post_id.replace(":", "%3A"), call["url"])
            self.assertEqual(call["json"]["message"]["text"], live_post.linkedin_comment_message)
            self.assertEqual(call["headers"]["LinkedIn-Version"], "202610")
            self.assertEqual(live_post.linkedin_comment_state, "posted")
            self.assertTrue(live_post.linkedin_comment_id)
            self.assertTrue(live_post.linkedin_comment_urn.startswith("urn:li:comment:("))
            self.assertEqual(live_post.linkedin_comment_attempts, 1)
            self.assertTrue(live_post.linkedin_comment_date)
            self.assertFalse(live_post.linkedin_comment_error)
        chatter = self._chatter(post)
        for account in self.social_accounts:
            self.assertTrue(any(f"LinkedIn first comment posted on {account.display_name}" in body
                                for body in chatter))
        self.assertFalse(post.live_post_ids.account_id.filtered("is_media_disconnected"))

    # ------------------------------------------------------------------
    # Instant and scheduled publication
    # ------------------------------------------------------------------

    def test_instant_post(self):
        post = self._new_post()
        api = self._publish(post)
        self._assert_comments_posted(post, api)
        # The link goes through link tracking, with the UTM values of the post
        text = post.live_post_ids[0].linkedin_comment_message
        self.assertTrue(text.startswith("Read the full article: "))
        self.assertIn("/r/", text)
        self.assertNotIn("https://example.com/article", text)
        tracker = self.env["link.tracker"].search([("url", "=", "https://example.com/article")])
        self.assertEqual(tracker.campaign_id, self.campaign)
        self.assertEqual(tracker.source_id, post.source_id)

    def test_scheduled_post(self):
        scheduled_date = fields.Datetime.now() + timedelta(hours=1)
        post = self._new_post(post_method="scheduled", scheduled_date=scheduled_date)
        post.action_schedule()
        with freeze_time(scheduled_date + timedelta(minutes=1)), self.mock_linkedin_api() as api:
            self.env["social.post"]._cron_publish_scheduled()
        self._assert_comments_posted(post, api)

    def test_core_retry_of_a_failed_post_posts_the_comment(self):
        post = self._new_post()
        api = self._publish(post, answers={1: (500, {"message": "Internal error"})})
        failed_live_post = post.live_post_ids.sorted("id")[0]
        self.assertEqual(failed_live_post.state, "failed")
        self.assertEqual(failed_live_post.linkedin_comment_state, "pending")
        self.assertEqual(len(api.comment_posts), 1, "No comment on a post that failed")

        with self.mock_linkedin_api() as api:
            failed_live_post.action_retry_post()
        self.assertEqual(failed_live_post.state, "posted")
        self.assertEqual(failed_live_post.linkedin_comment_state, "posted")
        self.assertEqual(len(api.comment_posts), 1)
        self.assertFalse(api.comment_lookups, "A new post cannot have the comment yet")

    def test_post_without_comment_makes_no_comment_call(self):
        post = self._new_post(comment=False)
        api = self._publish(post)
        self.assertEqual(len(api.calls_to("/rest/posts", "POST")), 2)
        self.assertFalse(api.comment_posts)
        self.assertEqual(post.live_post_ids.mapped("linkedin_comment_state"), ["none", "none"])

    def test_other_media_untouched(self):
        post = self._new_post(accounts=self.other_account)
        api = self._publish(post)
        self.assertFalse(api.calls)
        self.assertEqual(post.live_post_ids.linkedin_comment_state, "none")
        self.assertFalse(post.live_post_ids.linkedin_comment_message)

    def test_comment_too_long_once_links_are_tracked(self):
        comment = "x" * 988 + " https://a.b"
        self.assertEqual(len(comment), 1000)
        post = self._new_post(comment=comment)
        api = self._publish(post)
        self.assertFalse(api.comment_posts)
        self.assertEqual(post.live_post_ids.mapped("state"), ["posted", "posted"])
        self.assertEqual(post.live_post_ids.mapped("linkedin_comment_state"), ["failed", "failed"])
        self.assertIn("too long once its links are tracked", post.live_post_ids[0].linkedin_comment_error)

    # ------------------------------------------------------------------
    # Failures: the post always stays published
    # ------------------------------------------------------------------

    def test_temporary_error_keeps_the_comment_pending(self):
        post = self._new_post()
        self._publish(post, comment_answers=[(429, {"status": 429, "message": "Comment create throttled"})])
        first, second = post.live_post_ids.sorted("id")
        self.assertEqual(post.state, "posted")
        self.assertEqual((first.state, first.linkedin_comment_state), ("posted", "pending"))
        self.assertEqual(first.linkedin_comment_attempts, 1)
        self.assertIn("rate limit", first.linkedin_comment_error)
        self.assertIn("HTTP 429", first.linkedin_comment_error)
        self.assertEqual(second.linkedin_comment_state, "posted")
        self.assertFalse([body for body in self._chatter(post) if "LinkedIn first comment failed" in body],
                         "Nothing logged while a retry is planned")

    def test_permission_error_fails_at_once(self):
        post = self._new_post()
        self._publish(post, comment_answers=[(403, {"status": 403, "message": "Not enough permissions"})])
        first = post.live_post_ids.sorted("id")[0]
        self.assertEqual((first.state, first.linkedin_comment_state), ("posted", "failed"))
        self.assertIn("w_organization_social_feed", first.linkedin_comment_error)
        self.assertIn("Not enough permissions", first.linkedin_comment_error)
        self.assertTrue([body for body in self._chatter(post)
                         if f"LinkedIn first comment failed on {first.account_id.display_name}" in body
                         and "w_organization_social_feed" in body])
        self.assertFalse(first.account_id.is_media_disconnected)

    def test_last_attempt_fails(self):
        post = self._new_post()
        self._publish(post, comment_answers=[(503, {"message": "Unavailable"})] * 2)
        first = post.live_post_ids.sorted("id")[0]
        self.assertEqual(first.linkedin_comment_state, "pending")
        first.sudo().write({"linkedin_comment_attempts": 2})
        with self.mock_linkedin_api(comment_answers=[(503, {"message": "Unavailable"})]):
            first._linkedin_publish_first_comment(lookup_first=True)
        self.assertEqual((first.linkedin_comment_state, first.linkedin_comment_attempts), ("failed", 3))

    def test_success_without_id_is_looked_up(self):
        post = self._new_post(accounts=self.account, comment="Thanks for reading")
        api = self._publish(
            post,
            comment_answers=[(201, {"created": {"time": 1}})],
            lookup_answers=[(200, {"elements": [{
                "actor": "urn:li:organization:111", "id": "9001",
                "commentUrn": "urn:li:comment:(urn:li:activity:1,9001)",
                # Compared without trailing spaces nor Windows line ends
                "message": {"text": "Thanks for reading\r\n"},
            }]})])
        self.assertEqual(len(api.comment_posts), 1, "Never posted twice")
        self.assertEqual(post.live_post_ids.linkedin_comment_state, "posted")
        self.assertEqual(post.live_post_ids.linkedin_comment_id, "9001")

    def test_success_without_id_not_found_fails(self):
        post = self._new_post(accounts=self.account)
        api = self._publish(post, comment_answers=[(201, {"created": {"time": 1}})])
        self.assertEqual(len(api.comment_posts), 1)
        self.assertEqual(len(api.comment_lookups), 1)
        self.assertEqual(post.live_post_ids.linkedin_comment_state, "failed")
        self.assertIn("check the post on LinkedIn", post.live_post_ids.linkedin_comment_error)

    @mute_logger("odoo.addons.social_linkedin_extended.models.social_live_post")
    def test_unexpected_error_keeps_the_post_published(self):
        post = self._new_post(accounts=self.account)
        with patch.object(SocialAccount, "_linkedin_extended_create_comment", side_effect=RuntimeError("boom")), \
                self.mock_linkedin_api():
            post._action_post()
        live_post = post.live_post_ids
        self.assertEqual(post.state, "posted")
        self.assertEqual(live_post.state, "posted", "The core must never see the exception")
        self.assertEqual(live_post.linkedin_comment_state, "pending")
        self.assertEqual(live_post.linkedin_comment_attempts, 1)
        self.assertEqual(live_post.linkedin_comment_error, "Unexpected error, see the server log.")

    def test_secrets_never_stored_or_logged_in_chatter(self):
        post = self._new_post(accounts=self.account)
        with self.assertLogs("odoo.addons.social_linkedin_extended", level="WARNING") as logs:
            self._publish(post, comment_answers=[(401, f"Invalid token Bearer {ACCESS_TOKEN} token={ACCESS_TOKEN}")])
        self.assertTrue(logs.output, "The failed attempt is logged")
        self.assertFalse([line for line in logs.output if ACCESS_TOKEN in line])
        live_post = post.live_post_ids
        self.assertEqual(live_post.linkedin_comment_state, "failed")
        self.assertIn("reconnect the LinkedIn account", live_post.linkedin_comment_error)
        self.assertNotIn(ACCESS_TOKEN, live_post.linkedin_comment_error)
        self.assertFalse([body for body in self._chatter(post) if ACCESS_TOKEN in body])

    # ------------------------------------------------------------------
    # Never comment twice
    # ------------------------------------------------------------------

    def test_second_run_does_nothing(self):
        post = self._new_post()
        self._publish(post)
        with self.mock_linkedin_api() as api:
            post.live_post_ids._linkedin_publish_first_comment(lookup_first=True)
        self.assertFalse(api.calls)

    def test_retry_finds_the_comment_already_posted(self):
        post = self._new_post(accounts=self.account)
        self._publish(post, comment_answers=[(504, "Gateway timeout")])
        live_post = post.live_post_ids
        self.assertEqual(live_post.linkedin_comment_state, "pending")
        existing = {"actor": "urn:li:organization:111", "id": "9002",
                    "commentUrn": "urn:li:comment:(urn:li:activity:1,9002)",
                    "message": {"text": live_post.linkedin_comment_message}}
        with self.mock_linkedin_api(lookup_answers=[(200, {"elements": [
                {"actor": "urn:li:organization:999", "id": "1", "message": {"text": live_post.linkedin_comment_message}},
                existing]})]) as api:
            live_post._linkedin_publish_first_comment(lookup_first=True)
        self.assertFalse(api.comment_posts, "The comment created by the timed-out attempt is not posted again")
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_id), ("posted", "9002"))

    def test_retry_never_posts_when_the_lookup_fails(self):
        post = self._new_post(accounts=self.account)
        self._publish(post, comment_answers=[(500, "error")])
        live_post = post.live_post_ids
        with self.mock_linkedin_api(lookup_answers=[(500, "error")]) as api:
            live_post._linkedin_publish_first_comment(lookup_first=True)
        self.assertFalse(api.comment_posts)
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_attempts), ("pending", 2))
        self.assertIn("Could not check whether the comment was already posted", live_post.linkedin_comment_error)

        with self.mock_linkedin_api(lookup_answers=[(403, {"message": "Not enough permissions"})]) as api:
            live_post._linkedin_publish_first_comment(lookup_first=True)
        self.assertFalse(api.comment_posts)
        self.assertEqual(live_post.linkedin_comment_state, "failed")
        self.assertIn("r_organization_social_feed", live_post.linkedin_comment_error)

    def test_locked_by_another_process(self):
        post = self._new_post(accounts=self.account)
        self._publish(post, comment_answers=[(500, "error")])
        live_post = post.live_post_ids
        for side_effect in (lambda self: False, pg_errors.SerializationFailure("concurrent update")):
            with self.subTest(side_effect=side_effect), self.mock_linkedin_api() as api, \
                    patch.object(SocialLivePost, "_linkedin_comment_lock", autospec=True, side_effect=side_effect):
                handled = live_post._linkedin_publish_first_comment(lookup_first=True)
            self.assertFalse(handled)
            self.assertFalse(api.calls)
            self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_attempts), ("pending", 1))
