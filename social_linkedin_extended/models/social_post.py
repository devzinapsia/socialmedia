from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

# Maximum length of a LinkedIn comment. Not stated by the LinkedIn API
# documentation (LinkedIn help pages give 1000 or 1250 characters): the lowest
# figure is used, as agreed with the business
LINKEDIN_FIRST_COMMENT_MAX_LENGTH = 1000


class SocialPost(models.Model):
    _inherit = "social.post"

    linkedin_first_comment = fields.Text(
        string="LinkedIn first comment",
        compute="_compute_linkedin_first_comment", store=True, readonly=False, copy=True,
        help="Plain text posted as a comment by the same LinkedIn page right after the post is "
        "published on it (e.g. to share a link outside the body of the post).",
    )
    linkedin_comment_live_post_ids = fields.One2many(
        "social.live.post", string="LinkedIn first comments",
        compute="_compute_linkedin_comment_live_post_ids",
        help="Posts by LinkedIn account with the status of their first comment.",
    )

    @api.depends("utm_campaign_id", "has_linkedin_account")
    def _compute_linkedin_first_comment(self):
        """Pre-fill an empty first comment with the default comment of the campaign.

        A first comment already written (or edited) is never replaced. No check on
        the state of the post: the computation is delayed, a post created and
        published in the same transaction would lose its comment (the campaign is
        read-only in the form once the post is published anyway).
        """
        for post in self:
            template = post.utm_campaign_id.sudo().linkedin_first_comment_template
            if not post.linkedin_first_comment and template and post.has_linkedin_account:
                post.linkedin_first_comment = template
            else:
                post.linkedin_first_comment = post.linkedin_first_comment

    @api.depends("live_post_ids.linkedin_comment_state")
    def _compute_linkedin_comment_live_post_ids(self):
        for post in self:
            post.linkedin_comment_live_post_ids = post.live_post_ids.filtered(
                lambda live_post: live_post.media_type == "linkedin"
                and live_post.linkedin_comment_state not in (False, "none"))

    @api.constrains("linkedin_first_comment")
    def _check_linkedin_first_comment(self):
        for post in self.filtered("linkedin_first_comment"):
            if not post.linkedin_first_comment.strip():
                raise ValidationError(_("The LinkedIn first comment cannot be empty or contain only spaces."))
            if len(post.linkedin_first_comment) > LINKEDIN_FIRST_COMMENT_MAX_LENGTH:
                raise ValidationError(_(
                    "The LinkedIn first comment is too long: %(length)s characters (max %(max)s).",
                    length=len(post.linkedin_first_comment), max=LINKEDIN_FIRST_COMMENT_MAX_LENGTH))
