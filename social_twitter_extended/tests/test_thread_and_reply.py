from unittest.mock import patch

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

    def test_follow_ups_prepared_when_live_post_is_created(self):
        # Created with the live post, i.e. before `_action_post` commits and posts:
        # the link trackers already exist when X fetches the links for their cards
        post = self._create_post(
            thread_lines=["Second https://www.example.com/thread", "Third"],
            reply_url="https://www.example.com/landing",
        )
        live_post_model = self.env.registry["social.live.post"]
        with self.mock_x_api() as api, patch.object(live_post_model, "_post", lambda self: None):
            post.action_post()
        self.assertFalse(api.calls)
        live_post = post.live_post_ids
        self.assertEqual(live_post.state, "ready")
        self.assertTrue(live_post.twitter_follow_ups_prepared)
        follow_ups = live_post.twitter_follow_up_ids
        self.assertEqual(follow_ups.mapped("follow_up_type"), ["thread", "thread", "reply"])
        self.assertFalse(any(follow_ups.mapped("twitter_tweet_id")))
        for url, follow_up in (("https://www.example.com/thread", follow_ups[0]),
                               ("https://www.example.com/landing", follow_ups[2])):
            tracker = self.env["link.tracker"].search([("url", "=", url)])
            self.assertEqual(tracker.campaign_id, self.campaign)
            self.assertIn(tracker.short_url, follow_up.message)
        self.assertEqual(follow_ups[1].message, "Third")
        self.assertTrue(follow_ups[2].message.startswith("Learn more at: "))

    def test_no_follow_ups_without_thread_nor_reply(self):
        post = self._create_post()
        with self.mock_x_api():
            post.action_post()
        self.assertTrue(post.live_post_ids.twitter_follow_ups_prepared)
        self.assertFalse(post.live_post_ids.twitter_follow_up_ids)

    def test_follow_up_ids_are_stored(self):
        post = self._create_post(thread_lines=["Second"], reply_url="https://www.example.com")
        with self.mock_x_api():
            post.action_post()
        self.assertEqual(post.live_post_ids.twitter_follow_up_ids.mapped("twitter_tweet_id"), ["1002", "1003"])

    def test_retry_after_thread_failure_resumes_the_chain(self):
        post = self._create_post(thread_lines=["Second", "Third"], reply_url="https://www.example.com")
        with self.mock_x_api(fail_on={3: "line rejected"}):
            post.action_post()
        live_post = post.live_post_ids
        self.assertEqual(live_post.state, "failed")

        with self.mock_x_api() as api:
            live_post.action_retry_post()
        # The main post and the first line are not posted again: the chain resumes
        # with the line that failed, replying to the last post published (1002)
        calls = api.tweet_calls
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["json"]["text"], "Third")
        self.assertEqual(self._reply_to(calls[0]), "1002")
        self.assertTrue(calls[1]["json"]["text"].startswith("Learn more at: "))
        self.assertEqual(self._reply_to(calls[1]), "1001")
        self.assertEqual(live_post.state, "posted")
        self.assertFalse(live_post.failure_reason)
        self.assertEqual(live_post.twitter_tweet_id, "1001")
        self.assertEqual(live_post.twitter_follow_up_ids.mapped("twitter_tweet_id"), ["1002", "1001", "1002"])

    def test_retry_after_reply_failure_posts_only_the_reply(self):
        post = self._create_post(thread_lines=["Second"], reply_url="https://www.example.com")
        with self.mock_x_api(fail_on={3: "reply rejected"}):
            post.action_post()
        live_post = post.live_post_ids
        self.assertEqual(live_post.state, "failed")

        with self.mock_x_api() as api:
            live_post.action_retry_post()
        calls = api.tweet_calls
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["json"]["text"].startswith("Learn more at: "))
        self.assertEqual(self._reply_to(calls[0]), "1002")
        self.assertEqual(live_post.state, "posted")

    def test_retry_failing_again_reports_the_same_step(self):
        post = self._create_post(thread_lines=["Second", "Third"])
        with self.mock_x_api(fail_on={3: "line rejected"}):
            post.action_post()
        live_post = post.live_post_ids
        with self.mock_x_api(fail_on={1: "still rejected"}) as api:
            live_post.action_retry_post()
        self.assertEqual(len(api.tweet_calls), 1)
        self.assertEqual(live_post.state, "failed")
        self.assertIn("The main post and 1 thread post(s) were published", live_post.failure_reason)
        self.assertIn("thread post 2 of 2 failed: still rejected", live_post.failure_reason)

    def test_retry_live_post_created_before_follow_ups(self):
        # Live posts failed before this version have no follow-up posts: the
        # previous behavior applies, everything is posted again from the main post
        post = self._create_post(thread_lines=["Second"])
        with self.mock_x_api(fail_on={2: "line rejected"}):
            post.action_post()
        live_post = post.live_post_ids
        live_post.twitter_follow_up_ids.unlink()
        live_post.twitter_follow_ups_prepared = False

        with self.mock_x_api() as api:
            live_post.action_retry_post()
        self.assertEqual([call["json"]["text"] for call in api.tweet_calls], ["Main post", "Second"])
        self.assertEqual(live_post.state, "posted")
        self.assertTrue(live_post.twitter_follow_ups_prepared)

    def test_success_answer_without_post_keeps_the_raw_answer(self):
        # A 2xx answer of X without the new post, as JSON or not, is reported as
        # sent by X, not as the "Unknown error" of the core
        for body, expected in (({"errors": [{"detail": "Something went wrong"}]}, "Something went wrong"),
                               ("<html>Bad gateway</html>", "<html>Bad gateway</html>")):
            post = self._create_post(thread_lines=["Second"])
            with self.mock_x_api(json_on={2: body}):
                post.action_post()
            live_post = post.live_post_ids
            self.assertEqual(live_post.state, "failed")
            self.assertIn("thread post 1 of 1 failed: ", live_post.failure_reason)
            self.assertIn(expected, live_post.failure_reason)
