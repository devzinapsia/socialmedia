from odoo.exceptions import ValidationError
from odoo.tests import Form, tagged

from odoo.addons.social.tests.tools import mock_void_external_calls
from odoo.addons.social_linkedin_extended.models.social_post import LINKEDIN_FIRST_COMMENT_MAX_LENGTH

from .common import SocialLinkedinExtendedCase


@tagged("post_install", "-at_install")
class TestFirstCommentFields(SocialLinkedinExtendedCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.campaign = cls.env["utm.campaign"].create({
            "name": "Launch",
            "linkedin_first_comment_template": "Read more: https://example.com/launch",
        })
        cls.campaign_without_template = cls.env["utm.campaign"].create({"name": "No template"})
        other_media = cls.env["social.media"].create({"name": "Other", "media_type": False})
        with mock_void_external_calls():
            cls.other_account = cls.env["social.account"].create({
                "media_id": other_media.id, "name": "Other account"})

    def _new_post(self, **values):
        return self.env["social.post"].with_user(self.social_user).create({
            "message": "Hello", "account_ids": [(6, 0, self.social_accounts.ids)], **values})

    def test_prefilled_from_campaign(self):
        post = self._new_post(utm_campaign_id=self.campaign.id)
        self.assertEqual(post.linkedin_first_comment, "Read more: https://example.com/launch")

        post.linkedin_first_comment = "Edited by hand"
        post.utm_campaign_id = self.campaign_without_template
        post.utm_campaign_id = self.campaign
        self.assertEqual(post.linkedin_first_comment, "Edited by hand", "A written comment is never replaced")

    def test_prefilled_in_the_form_and_editable(self):
        with Form(self.env["social.post"].with_user(self.social_manager)) as form:
            form.message = "Hello"
            form.account_ids.add(self.account)
            form.utm_campaign_id = self.campaign
            self.assertEqual(form.linkedin_first_comment, "Read more: https://example.com/launch")
            form.linkedin_first_comment = "Read more, edited: https://example.com/launch?x=1"
        self.assertEqual(form.record.linkedin_first_comment, "Read more, edited: https://example.com/launch?x=1")

    def test_not_prefilled_without_linkedin_account(self):
        post = self._new_post(account_ids=[(6, 0, self.other_account.ids)], utm_campaign_id=self.campaign.id)
        self.assertFalse(post.linkedin_first_comment)
        post.account_ids = [(4, self.account.id)]
        self.assertEqual(post.linkedin_first_comment, "Read more: https://example.com/launch",
                         "Adding a LinkedIn account to a post of the campaign pre-fills the comment")

    def test_not_prefilled_without_template(self):
        self.assertFalse(self._new_post(utm_campaign_id=self.campaign_without_template.id).linkedin_first_comment)

    def test_prefilled_when_created_and_published_at_once(self):
        """The pre-fill is computed lazily: it must survive a publication in the same transaction."""
        post = self._new_post(utm_campaign_id=self.campaign.id)
        post.write({"state": "posted"})
        self.assertEqual(post.linkedin_first_comment, "Read more: https://example.com/launch")
        post.flush_recordset()
        post.invalidate_recordset()
        self.assertEqual(post.linkedin_first_comment, "Read more: https://example.com/launch")

    def test_validation(self):
        with self.assertRaises(ValidationError):
            self._new_post(linkedin_first_comment="   \n  ")
        with self.assertRaises(ValidationError):
            self._new_post(linkedin_first_comment="x" * (LINKEDIN_FIRST_COMMENT_MAX_LENGTH + 1))
        self.assertEqual(LINKEDIN_FIRST_COMMENT_MAX_LENGTH, 1000)
        post = self._new_post(linkedin_first_comment="x" * LINKEDIN_FIRST_COMMENT_MAX_LENGTH)
        self.assertEqual(len(post.linkedin_first_comment), 1000)
        post.linkedin_first_comment = False
        self.assertFalse(post.linkedin_first_comment, "The first comment is optional")

    def test_copy(self):
        post = self._new_post(linkedin_first_comment="Link: https://example.com")
        self.assertEqual(post.copy().linkedin_first_comment, "Link: https://example.com")

    def test_comment_status_per_account_and_failed_filter(self):
        post = self._new_post(linkedin_first_comment="Link: https://example.com")
        live_posts = self.env["social.live.post"].create([
            {"post_id": post.id, "account_id": self.social_accounts[0].id, "state": "posted",
             "linkedin_comment_state": "posted", "linkedin_comment_attempts": 1},
            {"post_id": post.id, "account_id": self.social_accounts[1].id, "state": "posted",
             "linkedin_comment_state": "failed", "linkedin_comment_attempts": 1,
             "linkedin_comment_error": "HTTP 403"},
            {"post_id": post.id, "account_id": self.other_account.id, "state": "posted"},
        ])
        self.assertEqual(post.linkedin_comment_live_post_ids, live_posts[:2],
                         "Only the LinkedIn accounts with a first comment are listed")
        self.assertEqual(live_posts[2].linkedin_comment_state, "none")

        other_post = self._new_post()
        failed = self.env["social.post"].search([("live_post_ids.linkedin_comment_state", "=", "failed")])
        self.assertIn(post, failed)
        self.assertNotIn(other_post, failed)
