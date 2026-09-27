from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import SocialTwitterExtendedCase


@tagged("post_install", "-at_install")
class TestThreadAndReply(SocialTwitterExtendedCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.campaign = cls.env["utm.campaign"].create({
            "name": "Launch",
            "twitter_fixed_reply_template": "Learn more at:",
        })

    def _create_post(self, thread_lines=(), reply_url=False, campaign=None):
        return self.env["social.post"].create({
            "message": "Main post",
            "account_ids": [(6, 0, self.social_account.ids)],
            "is_thread": bool(thread_lines),
            "thread_line_ids": [(0, 0, {"sequence": index, "body": body})
                                for index, body in enumerate(thread_lines)],
            "utm_campaign_id": (campaign or self.campaign).id,
            "twitter_reply_url": reply_url,
        })

    @staticmethod
    def _reply_to(call):
        return (call["json"].get("reply") or {}).get("in_reply_to_tweet_id")

    def test_thread_two_lines_chains_three_posts(self):
        post = self._create_post(thread_lines=["Second", "Third"])
        with self.mock_x_api() as api:
            post.action_post()
        calls = api.tweet_calls
        self.assertEqual([call["json"]["text"] for call in calls], ["Main post", "Second", "Third"])
        self.assertEqual([self._reply_to(call) for call in calls], [None, "1001", "1002"])
        live_post = post.live_post_ids
        self.assertEqual(live_post.state, "posted")
        self.assertEqual(live_post.twitter_tweet_id, "1001")
        self.assertEqual(post.state, "posted")
        # "Message posted" is logged once, after the whole chain
        self.assertEqual(len(post.message_ids.filtered(lambda m: "posted" in (m.body or ""))), 1)

    def test_reply_without_thread_replies_to_main_post(self):
        post = self._create_post(reply_url="https://www.example.com/landing")
        with self.mock_x_api() as api:
            post.action_post()
        main, reply = api.tweet_calls
        self.assertEqual(self._reply_to(reply), "1001")
        self.assertTrue(reply["json"]["text"].startswith("Learn more at: "))
        self.assertEqual(post.live_post_ids.state, "posted")
        # The URL is tracked like the links of the main message
        tracker = self.env["link.tracker"].search([("url", "=", "https://www.example.com/landing")])
        self.assertEqual(tracker.campaign_id, self.campaign)
        self.assertIn(tracker.short_url, reply["json"]["text"])

    def test_reply_with_thread_replies_to_last_line(self):
        post = self._create_post(thread_lines=["Second", "Third"], reply_url="https://www.example.com")
        with self.mock_x_api() as api:
            post.action_post()
        calls = api.tweet_calls
        self.assertEqual(len(calls), 4)
        self.assertEqual(self._reply_to(calls[-1]), "1003")
        self.assertTrue(calls[-1]["json"]["text"].startswith("Learn more at: "))

    def test_no_reply_without_template_or_url(self):
        no_template = self.env["utm.campaign"].create({"name": "No template"})
        for post in (self._create_post(reply_url="https://www.example.com", campaign=no_template),
                     self._create_post()):
            with self.mock_x_api() as api:
                post.action_post()
            self.assertEqual(len(api.tweet_calls), 1)

    def test_thread_line_failure_keeps_published_posts(self):
        post = self._create_post(thread_lines=["Second", "Third"], reply_url="https://www.example.com")
        error = '{"detail":"You are not allowed to create a Tweet with duplicate content."}'
        with self.mock_x_api(fail_on={3: error}) as api:
            post.action_post()
        # Main post and line 1 published, line 2 failed, nothing posted after it
        self.assertEqual(len(api.tweet_calls), 3)
        live_post = post.live_post_ids
        self.assertEqual(live_post.state, "failed")
        self.assertEqual(live_post.twitter_tweet_id, "1001")
        self.assertIn("thread post 2 of 2", live_post.failure_reason)
        self.assertIn(error, live_post.failure_reason)
        self.assertEqual(post.state, "posted")

    def test_reply_failure_is_reported(self):
        post = self._create_post(reply_url="https://www.example.com")
        with self.mock_x_api(fail_on={2: "reply rejected"}):
            post.action_post()
        live_post = post.live_post_ids
        self.assertEqual(live_post.state, "failed")
        self.assertIn("campaign reply failed: reply rejected", live_post.failure_reason)

    def test_main_post_failure_skips_follow_ups(self):
        post = self._create_post(thread_lines=["Second"], reply_url="https://www.example.com")
        with self.mock_x_api(fail_on={1: "main rejected"}) as api:
            post.action_post()
        self.assertEqual(len(api.tweet_calls), 1)
        self.assertEqual(post.live_post_ids.failure_reason, "main rejected")

    def test_thread_line_length(self):
        too_long = "x" * (self.social_media.max_post_length + 1)
        post = self._create_post(thread_lines=["Second", too_long])
        with self.assertRaises(ValidationError):
            post.action_schedule()
        self.social_account.is_pro_account = True
        with self.mock_x_api() as api:
            post.action_post()
        self.assertEqual(api.tweet_calls[-1]["json"]["text"], too_long)
