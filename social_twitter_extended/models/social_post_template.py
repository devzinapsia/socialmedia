from odoo import _, api, models

# Context key used to drop X from the local length check of `social.post`
SKIP_TWITTER_LENGTH_CHECK = "social_twitter_extended_skip_length_check"


class SocialPostTemplate(models.Model):
    _inherit = "social.post.template"

    def _is_twitter_pro_only(self):
        """True when the record targets X, and every selected X account is Pro.

        With a mix of Pro and non-Pro X accounts, the standard limit still
        applies, since the non-Pro accounts would be rejected by X anyway.
        """
        self.ensure_one()
        twitter_accounts = self.account_ids._filter_by_media_types(["twitter"])
        return bool(twitter_accounts) and all(twitter_accounts.mapped("is_pro_account"))

    @api.model
    def _message_fields(self):
        message_fields = super()._message_fields()
        if self.env.context.get(SKIP_TWITTER_LENGTH_CHECK):
            message_fields.pop("twitter", None)
        return message_fields

    @api.depends("account_ids.is_pro_account")
    def _compute_twitter_post_limit_message(self):
        super()._compute_twitter_post_limit_message()
        for post in self.filtered("has_twitter_account"):
            if not post._is_twitter_pro_only():
                continue
            post.is_twitter_post_limit_exceed = False
            # Posts being published/published are left blank by `social_twitter`
            if post.twitter_post_limit_message:
                post.twitter_post_limit_message = _(
                    "%(current_length)s characters (Pro account: the length is validated by X)",
                    current_length=len(post.twitter_message or ""),
                )

    @api.depends("account_ids.is_pro_account")
    def _compute_twitter_preview(self):
        super()._compute_twitter_preview()

    def _prepare_preview_values(self, media):
        values = super()._prepare_preview_values(media)
        if media == "twitter":
            values["twitter_skip_limit"] = self._is_twitter_pro_only()
        return values
