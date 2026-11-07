from odoo import fields, models


class SocialLivePostFollowUp(models.Model):
    """A post published on X right after the main post of a live post, as a reply chain.

    Technical model, no menu nor view: one record per thread post and one for
    the campaign reply, created with their final text when the live post is
    created. The id returned by X is stored as soon as each one is published,
    so a retry resumes from the first one not published yet.
    """

    _name = "social.live.post.follow.up"
    _description = "X follow-up post"
    _order = "sequence, id"

    live_post_id = fields.Many2one(
        "social.live.post", string="Live post", required=True, index=True, ondelete="cascade")
    sequence = fields.Integer(string="Sequence")
    follow_up_type = fields.Selection(
        [("thread", "Thread post"), ("reply", "Campaign reply")],
        string="Type", required=True)
    message = fields.Text(string="Message")
    twitter_tweet_id = fields.Char(string="X post id")
