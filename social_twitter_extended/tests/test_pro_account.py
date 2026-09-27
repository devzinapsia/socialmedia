from unittest.mock import MagicMock, patch

from odoo.exceptions import ValidationError
from odoo.tests import tagged

from .common import SocialTwitterExtendedCase


@tagged("post_install", "-at_install")
class TestProAccount(SocialTwitterExtendedCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.max_length = cls.social_media.max_post_length
        cls.long_message = "x" * (cls.max_length + 50)

    def _create_long_post(self, accounts):
        return self.env["social.post"].create({
            "message": self.long_message,
            "account_ids": [(6, 0, accounts.ids)],
        })

    def test_non_pro_account_keeps_standard_limit(self):
        post = self._create_long_post(self.social_account)
        self.assertTrue(post.is_twitter_post_limit_exceed)
        self.assertIn(f"/ {self.max_length}", post.twitter_post_limit_message)
        self.assertIn("o_social_twitter_message_exceeding", post.twitter_preview)
        with self.assertRaises(ValidationError):
            post.action_schedule()

    def test_pro_account_skips_local_limit(self):
        self.social_account.is_pro_account = True
        post = self._create_long_post(self.social_account)
        self.assertFalse(post.is_twitter_post_limit_exceed)
        self.assertNotIn(f"/ {self.max_length}", post.twitter_post_limit_message)
        self.assertNotIn("o_social_twitter_message_exceeding", post.twitter_preview)
        # The whole message is shown in the preview, not cut at the standard limit
        self.assertIn(self.long_message, post.twitter_preview)

        response = MagicMock(ok=True)
        response.json.return_value = {"data": {"id": "999"}}
        with patch("odoo.addons.social_twitter.models.social_live_post.requests.post",
                   return_value=response) as mock_post:
            post.action_post()
        # X receives the full text and decides whether it is valid
        self.assertEqual(mock_post.call_args.kwargs["json"]["text"], self.long_message)
        self.assertEqual(post.live_post_ids.twitter_tweet_id, "999")
        self.assertEqual(post.live_post_ids.state, "posted")

    def test_pro_toggle_recomputes_limit(self):
        post = self._create_long_post(self.social_account)
        self.assertTrue(post.is_twitter_post_limit_exceed)
        self.social_account.is_pro_account = True
        self.assertFalse(post.is_twitter_post_limit_exceed)

    def test_mixed_pro_and_non_pro_accounts_keep_limit(self):
        self.social_accounts[0].is_pro_account = True
        post = self._create_long_post(self.social_accounts)
        self.assertTrue(post.is_twitter_post_limit_exceed)
        with self.assertRaises(ValidationError):
            post.action_schedule()
