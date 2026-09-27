from odoo import fields, models


class UtmCampaign(models.Model):
    _inherit = "utm.campaign"

    twitter_fixed_reply_template = fields.Char(
        string="Fixed reply template for X",
        groups="social.group_social_user",
        help="Text posted on X as an automatic reply to the posts and Articles of this "
        "campaign, followed by the URL set on each of them (e.g. \"Learn more at:\").",
    )
