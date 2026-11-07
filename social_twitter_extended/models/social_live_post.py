from odoo import Command, _, api, fields, models

from .social_account import TwitterApiError

# Context key delaying `social.post._check_post_completion` until the whole
# chain (main post, thread, campaign reply) of an X live post is published
DEFER_POST_COMPLETION = "social_twitter_extended_defer_completion"


class SocialLivePost(models.Model):
    _inherit = "social.live.post"

    twitter_follow_up_ids = fields.One2many(
        "social.live.post.follow.up", "live_post_id", string="X follow-up posts", readonly=True)
    twitter_follow_ups_prepared = fields.Boolean(
        string="X follow-up posts prepared", readonly=True,
        help="Technical: set once the thread posts and the campaign reply of this X post are "
        "prepared. A retry then resumes from the first one not published yet.")

    @api.model_create_multi
    def create(self, vals_list):
        live_posts = super().create(vals_list)
        # `social.post._action_post` creates the live posts before committing and
        # posting: the link trackers of the follow-up posts must be committed by
        # then, as X fetches the links to build their cards, like the main message
        live_posts._filter_by_media_types(["twitter"])._prepare_twitter_follow_ups()
        return live_posts

    def _prepare_twitter_follow_ups(self):
        """Create the follow-up posts (thread posts, then the campaign reply), with their final text.

        A retry posts exactly the text the first attempt would have posted.
        """
        for live_post in self:
            post = live_post.post_id
            values = []
            if post.is_thread:
                values += [
                    {"follow_up_type": "thread", "message": live_post._prepare_twitter_follow_up_text(line.body)}
                    for line in post.thread_line_ids
                ]
            reply = live_post.account_id._twitter_prepare_campaign_reply(
                post.utm_campaign_id, post.twitter_reply_url, utm_values=live_post._get_utm_values())
            if reply:
                values.append({"follow_up_type": "reply", "message": reply})
            live_post.write({
                "twitter_follow_up_ids": [
                    Command.create({**follow_up_values, "sequence": index})
                    for index, follow_up_values in enumerate(values)
                ],
                "twitter_follow_ups_prepared": True,
            })

    def _post_twitter(self):
        live_posts = self.with_context(**{DEFER_POST_COMPLETION: True})
        # Main post already on X (retry after a follow-up post failed): only resume
        # the follow-up posts, posting the main post again would duplicate it
        resumed = live_posts.filtered(lambda live_post: live_post.twitter_follow_ups_prepared
                                      and live_post.twitter_tweet_id)
        # Live posts created before the follow-up posts existed: prepared now, and
        # posted again from the main post (the previous behavior)
        (live_posts - resumed).filtered(
            lambda live_post: not live_post.twitter_follow_ups_prepared)._prepare_twitter_follow_ups()

        super(SocialLivePost, live_posts - resumed)._post_twitter()
        for live_post in live_posts:
            if live_post.twitter_tweet_id and (live_post in resumed or live_post.state == "posted"):
                live_post._post_twitter_follow_ups()
        self.post_id._check_post_completion()

    def _post_twitter_follow_ups(self):
        """Publish the follow-up posts not published yet, chained to the last one published.

        What is already published is never deleted: on error, the live post
        is marked as failed with the step that failed and the error of X.
        Each id is stored as soon as X returns it, for a later retry.
        """
        self.ensure_one()
        follow_ups = self.twitter_follow_up_ids
        published = follow_ups.filtered("twitter_tweet_id")
        last_tweet_id = published[-1:].twitter_tweet_id or self.twitter_tweet_id
        thread_follow_ups = follow_ups.filtered(lambda follow_up: follow_up.follow_up_type == "thread")

        for follow_up in follow_ups - published:
            try:
                last_tweet_id = self.account_id._twitter_post_tweet(
                    follow_up.message, in_reply_to_tweet_id=last_tweet_id)
            except TwitterApiError as error:
                if follow_up.follow_up_type == "thread":
                    index = list(thread_follow_ups).index(follow_up) + 1
                    failure_reason = _(
                        "The main post and %(posted)s thread post(s) were published, "
                        "but thread post %(index)s of %(total)s failed: %(error)s",
                        posted=index - 1, index=index, total=len(thread_follow_ups), error=str(error),
                    )
                else:
                    failure_reason = _(
                        "The post was published, but the campaign reply failed: %(error)s",
                        error=str(error),
                    )
                self.write({"state": "failed", "failure_reason": failure_reason})
                return
            follow_up.twitter_tweet_id = last_tweet_id

        if self.state != "posted" or self.failure_reason:
            # Resumed after a failure: the whole chain is now published
            self.write({"state": "posted", "failure_reason": False})

    def _prepare_twitter_follow_up_text(self, text):
        """Same processing as the main message: tracked links and mentions handling."""
        self.ensure_one()
        text = self.env["mail.render.mixin"].sudo()._shorten_links_text(text, self._get_utm_values())
        return self.env["social.post"]._prepare_post_content(
            text,
            self.account_id.media_type,
            **{field: self.post_id[field] for field in self.env["social.post"]._get_post_message_modifying_fields()},
        )
