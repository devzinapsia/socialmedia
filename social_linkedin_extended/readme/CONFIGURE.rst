LinkedIn permissions
--------------------

The LinkedIn account must be connected in Odoo (*Social Marketing >
Configuration > Social Media > LinkedIn > Link account*) by an administrator
of the LinkedIn page. The token must hold:

- ``w_organization_social_feed`` (``w_organization_social`` in older LinkedIn
  documentation): to comment as the page;
- ``r_organization_social_feed``: to read the comments of the page, used before
  each retry to make sure the comment is not posted twice.

Both are part of the permissions the core module requests when the account is
connected, and are only granted to page administrators, through a LinkedIn app
approved for the Community Management API (the app of Odoo, or your own app,
see *Social Marketing > Configuration > Settings > Use your own LinkedIn
Account*).

A token keeps the permissions it was issued with: renewing it does not change
them. If the diagnostics or a failed comment report a missing permission, the
account must be authorized again: click *Link account* on LinkedIn again with
a page administrator, accepting every permission requested. Then run the
diagnostics again, and *Retry comment* on the failed posts.

LinkedIn API version
--------------------

Every LinkedIn REST API call must send a ``LinkedIn-Version`` header
(``YYYYMM``). LinkedIn publishes a version every month and retires each one
about one year after its release: a retired version is rejected with HTTP 426
(``NONEXISTENT_VERSION``), and the comments fail with a message asking to
update it.

The calls of this module send the version stored in the system parameter
``social_linkedin_extended.api_version`` (``202610`` when the module is
installed). To update it, with developer mode active:

#. Go to *Settings > Technical > Parameters > System Parameters*.
#. Open ``social_linkedin_extended.api_version``.
#. Set a version that is still active (see
   https://learn.microsoft.com/en-us/linkedin/marketing/versioning) and save.
#. Run the diagnostics to check it, then *Retry comment* on the failed posts.

If the parameter is missing or is not a ``YYYYMM`` value, the version of the
core ``social_linkedin`` module is used. This parameter does **not** change the
version of the core calls (publishing posts, the Feed, statistics), which is
updated with the Odoo version.

Default comment per campaign
----------------------------

On a campaign (*Social Marketing > Campaigns*), fill *Default first comment for
LinkedIn* to pre-fill the first comment of its LinkedIn posts.

Scheduled action
----------------

*Social: Retry LinkedIn first comments* runs every 60 minutes (*Settings >
Technical > Automation > Scheduled Actions*, developer mode).
