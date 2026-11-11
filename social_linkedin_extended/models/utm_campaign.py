from odoo import fields, models


class UtmCampaign(models.Model):
    _inherit = "utm.campaign"

    linkedin_first_comment_template = fields.Text(
        string="Default first comment for LinkedIn",
        groups="social.group_social_user",
        help="Pre-fills the LinkedIn first comment of the posts of this campaign that target a "
        "LinkedIn account, while their first comment is empty. It can be edited on each post.",
    )
