from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .social_live_post import DEFER_POST_COMPLETION
from .social_post_template import SKIP_TWITTER_LENGTH_CHECK


class SocialPost(models.Model):
    _inherit = "social.post"

    is_thread = fields.Boolean(
        string="Is a thread",
        help="Publish the posts below on X as replies chained to the main post, in order.")
    thread_line_ids = fields.One2many(
        "social.post.thread.line", "post_id", string="Thread posts", copy=True)
    twitter_reply_url = fields.Char(
        string="Reply URL for X",
        help="URL posted on X after the fixed reply of the campaign, as a reply to the "
        "last post published (the main post, or the last post of the thread).")
    twitter_fixed_reply_template = fields.Char(
        related="utm_campaign_id.twitter_fixed_reply_template")

    @api.onchange("has_twitter_account")
    def _onchange_has_twitter_account(self):
        # Threads only exist on X
        for post in self.filtered(lambda post: not post.has_twitter_account):
            post.is_thread = False

    def _check_post_completion(self):
        # Wait for the thread and campaign reply before logging "Message posted"
        if self.env.context.get(DEFER_POST_COMPLETION):
            return
        super()._check_post_completion()

    def _check_post_access(self):
        """Skip the local X length check for posts targeting only Pro X accounts.

        The rest of the checks (accounts set, other media limits) still run,
        and the lines of a thread follow the same rule as the main message.
        """
        pro_posts = self.filtered(lambda post: post._is_twitter_pro_only())
        super(SocialPost, self - pro_posts)._check_post_access()
        if pro_posts:
            super(
                SocialPost, pro_posts.with_context(**{SKIP_TWITTER_LENGTH_CHECK: True})
            )._check_post_access()
        (self - pro_posts)._check_thread_lines_length()

    def _check_thread_lines_length(self):
        errors = []
        for post in self.filtered(lambda post: post.is_thread and post.has_twitter_account):
            max_length = post.account_ids._filter_by_media_types(["twitter"]).media_id.max_post_length
            if not max_length:
                continue
            for index, line in enumerate(post.thread_line_ids, start=1):
                if len(line.body or "") > max_length:
                    errors.append(_(
                        "%(post)s: thread post %(index)s (max %(max_chars)s chars)",
                        post=post.display_name, index=index, max_chars=max_length,
                    ))
        if errors:
            raise ValidationError(_(
                "Due to length restrictions, the following thread posts cannot be posted:\n%s",
                "\n".join(errors),
            ))
