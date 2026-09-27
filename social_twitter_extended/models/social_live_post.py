from odoo import _, models

from .social_account import TwitterApiError

# Context key delaying `social.post._check_post_completion` until the whole
# chain (main post, thread, campaign reply) of an X live post is published
DEFER_POST_COMPLETION = "social_twitter_extended_defer_completion"


class SocialLivePost(models.Model):
    _inherit = "social.live.post"

    def _post_twitter(self):
        live_posts = self.with_context(**{DEFER_POST_COMPLETION: True})
        super(SocialLivePost, live_posts)._post_twitter()
        for live_post in live_posts:
            if live_post.state == "posted" and live_post.twitter_tweet_id:
                live_post._post_twitter_follow_ups()
        self.post_id._check_post_completion()

    def _post_twitter_follow_ups(self):
        """Publish the thread lines, then the campaign reply, chained to the main post.

        What is already published is never deleted: on error, the live post
        is marked as failed with the step that failed and the error of X.
        """
        self.ensure_one()
        post = self.post_id
        account = self.account_id
        last_tweet_id = self.twitter_tweet_id

        if post.is_thread:
            lines = post.thread_line_ids
            for index, line in enumerate(lines, start=1):
                try:
                    last_tweet_id = account._twitter_post_tweet(
                        self._prepare_twitter_follow_up_text(line.body),
                        in_reply_to_tweet_id=last_tweet_id,
                    )
                except TwitterApiError as error:
                    self.write({
                        "state": "failed",
                        "failure_reason": _(
                            "The main post and %(posted)s thread post(s) were published, "
                            "but thread post %(index)s of %(total)s failed: %(error)s",
                            posted=index - 1, index=index, total=len(lines), error=str(error),
                        ),
                    })
                    return

        try:
            account._twitter_post_campaign_reply(
                post.utm_campaign_id, post.twitter_reply_url, last_tweet_id,
                utm_values=self._get_utm_values(),
            )
        except TwitterApiError as error:
            self.write({
                "state": "failed",
                "failure_reason": _(
                    "The post was published, but the campaign reply failed: %(error)s",
                    error=str(error),
                ),
            })

    def _prepare_twitter_follow_up_text(self, text):
        """Same processing as the main message: tracked links and mentions handling."""
        self.ensure_one()
        text = self.env["mail.render.mixin"].sudo()._shorten_links_text(text, self._get_utm_values())
        return self.env["social.post"]._prepare_post_content(
            text,
            self.account_id.media_type,
            **{field: self.post_id[field] for field in self.env["social.post"]._get_post_message_modifying_fields()},
        )
