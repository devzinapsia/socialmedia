from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import SocialLinkedinExtendedCase


@tagged("post_install", "-at_install")
class TestFirstCommentRetry(SocialLinkedinExtendedCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.cron = cls.env.ref("social_linkedin_extended.ir_cron_retry_linkedin_first_comments")

    def _published_post(self, comment_answers=None, accounts=None):
        post = self.env["social.post"].create({
            "message": "A post without images",
            "account_ids": [(6, 0, (accounts or self.account).ids)],
            "linkedin_first_comment": "Thanks for reading",
        })
        with self.mock_linkedin_api(comment_answers=comment_answers):
            post._action_post()
        return post

    def _run_cron(self, **mock_values):
        with self.mock_linkedin_api(**mock_values) as api:
            self.env["social.live.post"]._cron_retry_linkedin_first_comments()
        return api

    def _failed_messages(self, post):
        return [message for message in post.message_ids.mapped("body")
                if message and "LinkedIn first comment failed" in str(message)]

    def test_cron_definition(self):
        self.assertTrue(self.cron.active)
        self.assertEqual((self.cron.interval_number, self.cron.interval_type), (60, "minutes"))
        self.assertEqual(self.cron.code.strip(), "model._cron_retry_linkedin_first_comments()")

    def test_cron_retries_a_temporary_error(self):
        post = self._published_post(comment_answers=[(429, {"message": "Comment create throttled"})])
        live_post = post.live_post_ids
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_attempts), ("pending", 1))

        api = self._run_cron()
        self.assertEqual(len(api.comment_lookups), 1, "The cron looks for the comment before posting it")
        self.assertEqual(len(api.comment_posts), 1)
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_attempts), ("posted", 2))
        self.assertFalse(live_post.linkedin_comment_error)

    def test_cron_stops_after_three_attempts(self):
        post = self._published_post(comment_answers=[(500, {"message": "Internal error"})])
        live_post = post.live_post_ids
        self._run_cron(comment_answers=[(503, {"message": "Unavailable"})])
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_attempts), ("pending", 2))
        self.assertFalse(self._failed_messages(post))

        self._run_cron(comment_answers=[(503, {"message": "Unavailable"})])
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_attempts), ("failed", 3))
        self.assertEqual(len(self._failed_messages(post)), 1)
        self.assertEqual(post.state, "posted")

        api = self._run_cron()
        self.assertFalse(api.calls, "A failed comment is never retried by the cron")

    def test_cron_does_not_retry_permission_errors(self):
        post = self._published_post(comment_answers=[(403, {"message": "Not enough permissions"})])
        self.assertEqual(post.live_post_ids.linkedin_comment_state, "failed")
        api = self._run_cron()
        self.assertFalse(api.calls)

    def test_cron_finds_the_comment_already_posted(self):
        post = self._published_post(comment_answers=[(504, "Gateway timeout")])
        live_post = post.live_post_ids
        api = self._run_cron(lookup_answers=[(200, {"elements": [{
            "actor": "urn:li:organization:111", "id": "9003",
            "commentUrn": "urn:li:comment:(urn:li:activity:1,9003)",
            "message": {"text": "Thanks for reading"},
        }]})])
        self.assertFalse(api.comment_posts)
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_id), ("posted", "9003"))

    def test_cron_ignores_posts_not_published(self):
        post = self.env["social.post"].create({
            "message": "A post without images", "account_ids": [(6, 0, self.account.ids)],
            "linkedin_first_comment": "Thanks for reading",
        })
        with self.mock_linkedin_api(answers={1: (500, {"message": "Internal error"})}):
            post._action_post()
        live_post = post.live_post_ids
        self.assertEqual((live_post.state, live_post.linkedin_comment_state), ("failed", "pending"))
        api = self._run_cron()
        self.assertFalse(api.calls, "No comment on a post that is not on LinkedIn")

    def test_cron_ignores_posts_without_comment(self):
        post = self.env["social.post"].create({
            "message": "A post without images", "account_ids": [(6, 0, self.account.ids)]})
        with self.mock_linkedin_api():
            post._action_post()
        self.assertEqual(post.live_post_ids.linkedin_comment_state, "none")
        self.assertFalse(self._run_cron().calls)

    def test_retry_button(self):
        post = self._published_post(comment_answers=[(403, {"message": "Not enough permissions"})])
        live_post = post.live_post_ids
        self.assertEqual(live_post.linkedin_comment_state, "failed")

        with self.mock_linkedin_api() as api:
            live_post.with_user(self.social_manager).action_retry_linkedin_comment()
        self.assertEqual([call["method"] for call in api.calls], ["GET", "POST"],
                         "The button looks for the comment before posting it")
        self.assertEqual(live_post.linkedin_comment_state, "posted")
        self.assertEqual(live_post.linkedin_comment_attempts, 1, "A manual retry starts a new cycle of attempts")
        self.assertTrue([message for message in post.message_ids.mapped("body")
                         if message and "LinkedIn first comment posted" in str(message)])

    def test_retry_button_temporary_error_goes_back_to_the_cron(self):
        post = self._published_post(comment_answers=[(403, {"message": "Not enough permissions"})])
        live_post = post.live_post_ids
        with self.mock_linkedin_api(comment_answers=[(429, {"message": "Throttled"})]):
            live_post.with_user(self.social_manager).action_retry_linkedin_comment()
        self.assertEqual((live_post.linkedin_comment_state, live_post.linkedin_comment_attempts), ("pending", 1))
        self._run_cron()
        self.assertEqual(live_post.linkedin_comment_state, "posted")

    def test_retry_button_rights_and_states(self):
        post = self._published_post(comment_answers=[(403, {"message": "Not enough permissions"})])
        live_post = post.live_post_ids
        with self.mock_linkedin_api() as api:
            with self.assertRaises(AccessError):
                live_post.with_user(self.social_user).action_retry_linkedin_comment()
            self.assertFalse(api.calls)
            self.assertEqual(live_post.linkedin_comment_state, "failed")

            live_post.with_user(self.social_manager).action_retry_linkedin_comment()
            calls = len(api.calls)
            with self.assertRaises(UserError):
                live_post.with_user(self.social_manager).action_retry_linkedin_comment()
            self.assertEqual(len(api.calls), calls, "A posted comment is never posted again")
