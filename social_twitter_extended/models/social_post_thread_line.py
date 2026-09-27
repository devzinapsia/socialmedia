from odoo import fields, models


class SocialPostThreadLine(models.Model):
    _name = "social.post.thread.line"
    _description = "Social post thread line"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    body = fields.Text(string="Text", required=True)
    post_id = fields.Many2one(
        "social.post", string="Social post", required=True, index=True, ondelete="cascade")
