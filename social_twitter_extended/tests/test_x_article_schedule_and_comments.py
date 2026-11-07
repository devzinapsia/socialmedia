from datetime import timedelta
from unittest.mock import patch

from freezegun import freeze_time

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import SocialTwitterExtendedCase


@tagged("post_install", "-at_install")
class TestXArticleScheduleAndComments(SocialTwitterExtendedCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.social_accounts.is_pro_account = True
        cls.campaign = cls.env["utm.campaign"].create({
            "name": "Articles",
            "twitter_fixed_reply_template": "Learn more at:",
        })
        cls.cron = cls.env.ref("social_twitter_extended.ir_cron_x_article_scheduled")

    def _create_article(self, **values):
        return self.env["social.x.article"].create({
            "title": "My Article",
            "body": "<p>Body</p>",
            "account_id": self.social_account.id,
            **values,
        })

    def _create_scheduled_article(self, delay, **values):
        article = self._create_article(
            post_method="scheduled", scheduled_date=fields.Datetime.now() + delay, **values)
        article.action_schedule()
        return article

    def _comments_values(self, first_comment="Thanks for reading!"):
        return {
            "utm_campaign_id": self.campaign.id,
            "twitter_reply_url": "https://www.example.com/landing",
            "twitter_first_comment": first_comment,
        }

    @staticmethod
    def _reply_to(call):
        return (call["json"].get("reply") or {}).get("in_reply_to_tweet_id")

    def _cron_trigger_dates(self):
        return self.env["ir.cron.trigger"].search([("cron_id", "=", self.cron.id)]).mapped("call_at")

    # ------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------

    def test_schedule_requires_a_future_date(self):
        article = self._create_article(post_method="scheduled")
        with self.mock_x_api() as api:
            with self.assertRaises(ValidationError):
                article.action_schedule()
            article.scheduled_date = fields.Datetime.now() - timedelta(hours=1)
            with self.assertRaises(ValidationError):
                article.action_schedule()
        self.assertFalse(api.calls)
        self.assertEqual(article.state, "draft")

    def test_schedule_checks_the_article_without_calling_x(self):
        empty = self._create_article(
            body="<p><br></p>", post_method="scheduled", scheduled_date=fields.Datetime.now() + timedelta(days=1))
        with self.mock_x_api() as api, self.assertRaises(UserError):
            empty.action_schedule()
        self.assertFalse(api.calls)

    def test_schedule_triggers_the_cron_at_the_date(self):
        with self.mock_x_api() as api:
            article = self._create_scheduled_article(timedelta(days=1))
        self.assertFalse(api.calls)
        self.assertEqual(article.state, "scheduled")
        self.assertIn(article.scheduled_date, self._cron_trigger_dates())
        # Moving the date of a scheduled Article triggers the cron at the new date
        article.scheduled_date = article.scheduled_date + timedelta(days=1)
        self.assertIn(article.scheduled_date, self._cron_trigger_dates())

    def test_cron_publishes_only_due_articles_with_their_comments(self):
        due = self._create_scheduled_article(timedelta(hours=1), title="Due", **self._comments_values())
        later = self._create_scheduled_article(timedelta(days=2), title="Later")
        with freeze_time(fields.Datetime.now() + timedelta(hours=2)), self.mock_x_api() as api:
            self.env["social.x.article"]._cron_publish_scheduled()

        self.assertEqual(later.state, "scheduled")
        self.assertEqual(due.state, "published")
        self.assertEqual(due.twitter_post_id, "2002")
        first_comment, reply = api.tweet_calls
        self.assertEqual(first_comment["json"]["text"], "Thanks for reading!")
        self.assertEqual(self._reply_to(first_comment), "2002")
        self.assertTrue(reply["json"]["text"].startswith("Learn more at: "))
        self.assertEqual(self._reply_to(reply), "1003")
        self.assertEqual(due.twitter_first_comment_post_id, "1003")
        self.assertEqual(due.twitter_reply_post_id, "1004")

    def test_cron_unpublishable_article_does_not_block_the_others(self):
        good = self._create_scheduled_article(timedelta(hours=1), title="Good")
        bad = self._create_scheduled_article(
            timedelta(hours=1), title="Bad", account_id=self.social_accounts[1].id)
        # No longer Pro since it was scheduled
        self.social_accounts[1].is_pro_account = False
        with freeze_time(fields.Datetime.now() + timedelta(hours=2)), self.mock_x_api() as api:
            self.env["social.x.article"]._cron_publish_scheduled()
        self.assertEqual(bad.state, "error")
        self.assertIn("flagged as Pro account", bad.error_message)
        self.assertEqual(good.state, "published")
        self.assertEqual(len([call for call in api.calls if call["url"].endswith("/publish")]), 1)

    def test_cron_unexpected_error_does_not_block_the_others(self):
        good = self._create_scheduled_article(timedelta(hours=1), title="Good")
        bad = self._create_scheduled_article(timedelta(hours=1), title="Bad")
        article_model = self.env.registry["social.x.article"]
        original = article_model._publish_on_twitter

        def publish(article, comments=None):
            if article.title == "Bad":
                raise RuntimeError("Unexpected")
            return original(article, comments)

        with freeze_time(fields.Datetime.now() + timedelta(hours=2)), self.mock_x_api(), \
                patch.object(article_model, "_publish_on_twitter", publish), \
                self.assertLogs("odoo.addons.social_twitter_extended.models.social_x_article", "ERROR"):
            self.env["social.x.article"]._cron_publish_scheduled()
        self.assertEqual(bad.state, "error")
        self.assertEqual(bad.error_message, "Unexpected")
        self.assertEqual(good.state, "published")

    def test_cancel_schedule(self):
        article = self._create_scheduled_article(timedelta(hours=1))
        article.action_set_draft()
        self.assertEqual(article.state, "draft")
        with freeze_time(fields.Datetime.now() + timedelta(hours=2)), self.mock_x_api() as api:
            self.env["social.x.article"]._cron_publish_scheduled()
        self.assertFalse(api.calls)
        self.assertEqual(article.state, "draft")

    def test_publish_now_clears_the_schedule(self):
        article = self._create_scheduled_article(timedelta(days=1))
        with self.mock_x_api():
            article.action_publish()
        self.assertEqual(article.state, "published")
        self.assertEqual(article.post_method, "now")
        self.assertFalse(article.scheduled_date)

    # ------------------------------------------------------------
    # First comment and campaign reply
    # ------------------------------------------------------------

    def test_first_comment_then_reply_are_chained(self):
        article = self._create_article(**self._comments_values("Read https://www.example.com/comment"))
        with self.mock_x_api() as api:
            article.action_publish()
        first_comment, reply = api.tweet_calls
        # Article post (2002) <- first comment (1003) <- campaign reply (1004)
        self.assertEqual(self._reply_to(first_comment), "2002")
        self.assertEqual(self._reply_to(reply), "1003")
        tracker = self.env["link.tracker"].search([("url", "=", "https://www.example.com/comment")])
        self.assertEqual(tracker.campaign_id, self.campaign)
        self.assertEqual(first_comment["json"]["text"], f"Read {tracker.short_url}")
        self.assertEqual((article.twitter_first_comment_post_id, article.twitter_reply_post_id), ("1003", "1004"))
        self.assertFalse(article.error_message)
        self.assertFalse(article.twitter_comments_pending)

    def test_first_comment_without_campaign_reply(self):
        article = self._create_article(twitter_first_comment="Thanks for reading!")
        with self.mock_x_api() as api:
            article.action_publish()
        (first_comment,) = api.tweet_calls
        self.assertEqual(self._reply_to(first_comment), "2002")
        self.assertFalse(article.twitter_reply_post_id)

    def test_first_comment_failure_then_retry_posts_both_comments(self):
        article = self._create_article(**self._comments_values())
        with self.mock_x_api(fail_on={3: "comment rejected"}) as api:
            article.action_publish()
        # Nothing is posted after the failed first comment
        self.assertEqual(len(api.tweet_calls), 1)
        self.assertEqual(article.state, "published")
        self.assertIn("first comment failed: comment rejected", article.error_message)
        self.assertTrue(article.twitter_comments_pending)

        with self.mock_x_api() as api:
            article.action_retry_comments()
        first_comment, reply = api.tweet_calls
        self.assertEqual(self._reply_to(first_comment), "2002")
        self.assertEqual(self._reply_to(reply), "1001")
        self.assertFalse(article.error_message)
        self.assertFalse(article.twitter_comments_pending)
        self.assertEqual((article.twitter_first_comment_post_id, article.twitter_reply_post_id), ("1001", "1002"))

    def test_reply_failure_then_retry_posts_only_the_reply(self):
        article = self._create_article(**self._comments_values())
        with self.mock_x_api(fail_on={4: "reply rejected"}):
            article.action_publish()
        self.assertEqual(article.twitter_first_comment_post_id, "1003")
        self.assertIn("campaign reply failed: reply rejected", article.error_message)

        with self.mock_x_api() as api:
            article.action_retry_comments()
        (reply,) = api.tweet_calls
        self.assertEqual(self._reply_to(reply), "1003")
        self.assertEqual(article.twitter_reply_post_id, "1001")
        self.assertFalse(article.twitter_comments_pending)

    def test_retry_failing_again_keeps_the_comments_pending(self):
        article = self._create_article(**self._comments_values())
        with self.mock_x_api(fail_on={3: "comment rejected"}):
            article.action_publish()
        with self.mock_x_api(fail_on={1: "still rejected"}) as api:
            article.action_retry_comments()
        self.assertEqual(len(api.tweet_calls), 1)
        self.assertIn("first comment failed: still rejected", article.error_message)
        self.assertTrue(article.twitter_comments_pending)

    def test_published_article_without_comment_ids_is_not_pending(self):
        # Published before the ids of the comments were stored: its campaign reply may be
        # on X already, retrying would duplicate it. Only an error makes it pending.
        article = self._create_article(**self._comments_values())
        article.write({"state": "published", "twitter_post_id": "2002"})
        self.assertFalse(article.twitter_comments_pending)
        article.error_message = "The Article was published, but the campaign reply failed: -"
        self.assertTrue(article.twitter_comments_pending)
