import base64

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import SocialTwitterExtendedCase

# 1x1 transparent PNG
PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


@tagged("post_install", "-at_install")
class TestXArticle(SocialTwitterExtendedCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.social_account.is_pro_account = True
        cls.campaign = cls.env["utm.campaign"].create({
            "name": "Articles",
            "twitter_fixed_reply_template": "Learn more at:",
        })

    def _create_article(self, **values):
        return self.env["social.x.article"].create({
            "title": "My Article",
            "body": "<h2>Intro</h2><p>Some <b>bold</b> text</p>",
            "account_id": self.social_account.id,
            **values,
        })

    def test_publish_with_cover_and_reply(self):
        article = self._create_article(
            cover_image=PNG_1PX,
            utm_campaign_id=self.campaign.id,
            twitter_reply_url="https://www.example.com/landing",
        )
        with self.mock_x_api() as api:
            article.action_publish()

        self.assertEqual([call["url"].split("api.x.com")[-1].split("api.twitter.com")[-1] for call in api.calls], [
            "/2/media/upload/initialize",
            "/2/media/upload/1001/append",
            "/2/media/upload/1001/finalize",
            "/2/articles/draft",
            "/2/articles/1004/publish",
            "/2/tweets",
        ])
        draft_payload = api.calls[3]["json"]
        self.assertEqual(draft_payload["title"], "My Article")
        self.assertEqual(draft_payload["cover_media"], {"media_id": "1001", "media_category": "tweet_image"})
        self.assertEqual(
            [(block["type"], block["text"]) for block in draft_payload["content_state"]["blocks"]],
            [("header-two", "Intro"), ("unstyled", "Some bold text")])
        # The campaign reply answers the post created for the published Article
        reply_payload = api.calls[5]["json"]
        self.assertEqual(reply_payload["reply"], {"in_reply_to_tweet_id": "2005"})
        self.assertTrue(reply_payload["text"].startswith("Learn more at: "))

        self.assertEqual(article.state, "published")
        self.assertFalse(article.error_message)
        self.assertEqual(article.twitter_article_id, "1004")
        self.assertEqual(article.twitter_post_id, "2005")
        self.assertEqual(article.twitter_url, "https://x.com/i/status/2005")

    def test_publish_without_cover_nor_reply(self):
        article = self._create_article(utm_campaign_id=self.campaign.id)
        with self.mock_x_api() as api:
            article.action_publish()
        self.assertEqual(len(api.calls), 2)
        self.assertNotIn("cover_media", api.calls[0]["json"])
        self.assertEqual(article.state, "published")

    def test_non_pro_account_cannot_create_nor_publish(self):
        non_pro = self.social_accounts[1]
        with self.mock_x_api() as api:
            with self.assertRaises(ValidationError):
                self._create_article(account_id=non_pro.id)
            article = self._create_article()
            self.social_account.is_pro_account = False
            with self.assertRaises(ValidationError):
                article.action_publish()
        self.assertFalse(api.calls)
        self.assertEqual(article.state, "draft")

    def test_api_error_is_stored_as_is(self):
        article = self._create_article()
        error = ('{"title":"Forbidden","detail":"You are not permitted to perform this action.",'
                 '"type":"about:blank","status":403}')
        with self.mock_x_api(fail_on={2: error}):
            article.action_publish()
        self.assertEqual(article.state, "error")
        self.assertEqual(article.error_message, error)
        # The draft was created, the id is kept for reference
        self.assertEqual(article.twitter_article_id, "1001")
        self.assertFalse(article.twitter_post_id)

        article.action_set_draft()
        self.assertEqual(article.state, "draft")
        self.assertFalse(article.error_message)

    def test_reply_failure_keeps_article_published(self):
        article = self._create_article(
            utm_campaign_id=self.campaign.id, twitter_reply_url="https://www.example.com")
        with self.mock_x_api(fail_on={3: "reply rejected"}):
            article.action_publish()
        self.assertEqual(article.state, "published")
        self.assertIn("campaign reply failed: reply rejected", article.error_message)

    def test_cannot_publish_empty_or_published(self):
        article = self._create_article(body="<p><br></p>")
        with self.mock_x_api() as api, self.assertRaises(UserError):
            article.action_publish()
        self.assertFalse(api.calls)

        article.body = "<p>Text</p>"
        with self.mock_x_api():
            article.action_publish()
        with self.assertRaises(UserError):
            article.action_publish()

    def test_publish_from_list_action(self):
        action = self.env.ref("social_twitter_extended.action_social_x_article_publish")
        self.assertEqual(action.binding_model_id.model, "social.x.article")
        self.assertEqual(action.binding_view_types, "list")
        self.assertIn(self.env.ref("social.group_social_user"), action.group_ids)

        articles = self._create_article() | self._create_article(title="Second")
        with self.mock_x_api() as api:
            action.with_context(active_model="social.x.article", active_ids=articles.ids).run()
        self.assertEqual(articles.mapped("state"), ["published", "published"])
        self.assertEqual(len([call for call in api.calls if call["url"].endswith("/publish")]), 2)

        # A selection containing an already published Article is refused, without calling X
        draft = self._create_article(title="Third")
        with self.mock_x_api() as api, self.assertRaises(UserError):
            action.with_context(active_model="social.x.article", active_ids=(articles | draft).ids).run()
        self.assertFalse(api.calls)
        self.assertEqual(draft.state, "draft")

    def test_cover_upload_error_shows_x_response(self):
        # X API v2 errors come in `title` / `detail`: the core read `error` and showed "(error: )"
        error = ('{"title":"Forbidden","detail":"You are not permitted to perform this action.",'
                 '"type":"about:blank","status":403}')
        article = self._create_article(cover_image=PNG_1PX)
        with self.mock_x_api(fail_on={1: error}) as api:
            article.action_publish()
        self.assertEqual(len(api.calls), 1)
        self.assertEqual(article.state, "error")
        self.assertIn("initialize, HTTP 403", article.error_message)
        self.assertIn("You are not permitted to perform this action.", article.error_message)

    def test_cover_append_or_finalize_error_stops_before_draft(self):
        for step, number in (("append", 2), ("finalize", 3)):
            article = self._create_article(cover_image=PNG_1PX)
            with self.mock_x_api(fail_on={number: "rejected"}) as api:
                article.action_publish()
            self.assertEqual(len(api.calls), number, step)
            self.assertFalse([call for call in api.calls if "/articles/" in call["url"]])
            self.assertIn(f"({step}, HTTP 403): rejected", article.error_message)

    def test_cover_waits_for_media_processing(self):
        article = self._create_article(cover_image=PNG_1PX)
        pending = {"data": {"id": "1001", "processing_info": {"state": "pending", "check_after_secs": 1}}}
        succeeded = {"data": {"id": "1001", "processing_info": {"state": "succeeded"}}}
        with self.mock_x_api(json_on={3: pending, 4: pending, 5: succeeded}) as api:
            article.action_publish()
        status_calls = [call for call in api.calls if call["method"] == "GET"]
        self.assertEqual(len(status_calls), 2)
        self.assertEqual(status_calls[0]["params"], {"command": "STATUS", "media_id": "1001"})
        # The draft is created only once X has processed the image
        self.assertTrue(api.calls[5]["url"].endswith("/2/articles/draft"))
        self.assertEqual(article.state, "published")

    def test_cover_processing_failed(self):
        article = self._create_article(cover_image=PNG_1PX)
        failed = {"data": {"id": "1001", "processing_info": {
            "state": "failed", "error": {"message": "Unsupported image"}}}}
        with self.mock_x_api(json_on={3: failed}) as api:
            article.action_publish()
        self.assertEqual(len(api.calls), 3)
        self.assertEqual(article.state, "error")
        self.assertIn("Unsupported image", article.error_message)

    def test_cover_image_is_sent_as_uploaded(self):
        article = self._create_article(cover_image=PNG_1PX)
        with self.mock_x_api() as api:
            article.action_publish()
        init, append = api.calls[0], api.calls[1]
        image_bytes = base64.b64decode(article.cover_image)
        self.assertEqual(init["json"]["media_type"], "image/png")
        self.assertEqual(init["json"]["total_bytes"], len(image_bytes))
        self.assertEqual(append["files"]["media"], image_bytes)
