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

    def test_cover_image_is_sent_as_uploaded(self):
        article = self._create_article(cover_image=PNG_1PX)
        with self.mock_x_api() as api:
            article.action_publish()
        init, append = api.calls[0], api.calls[1]
        image_bytes = base64.b64decode(article.cover_image)
        self.assertEqual(init["json"]["media_type"], "image/png")
        self.assertEqual(init["json"]["total_bytes"], len(image_bytes))
        self.assertEqual(append["files"]["media"], image_bytes)
