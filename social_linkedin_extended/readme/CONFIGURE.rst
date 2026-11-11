LinkedIn API version
~~~~~~~~~~~~~~~~~~~~

Every LinkedIn REST API call must send a ``LinkedIn-Version`` header
(``YYYYMM``). LinkedIn publishes a version every month and retires each one
about one year after its release: a retired version is rejected with HTTP 426
(``NONEXISTENT_VERSION``).

The calls of this module send the version stored in the system parameter
``social_linkedin_extended.api_version`` (``202610`` when the module is
installed). To update it, with developer mode active:

#. Go to *Settings > Technical > System Parameters*.
#. Open ``social_linkedin_extended.api_version``.
#. Set a version that is still active (see
   https://learn.microsoft.com/en-us/linkedin/marketing/versioning) and save.

If the parameter is missing or is not a ``YYYYMM`` value, the version of the
core ``social_linkedin`` module is used. This parameter does **not** change the
version of the core calls (publishing posts, the Feed, statistics).

Permissions
~~~~~~~~~~~

Commenting as a LinkedIn page needs the ``w_organization_social_feed``
permission (``w_organization_social`` in older LinkedIn documentation),
granted only to page administrators, through a LinkedIn app approved for the
Community Management API. A token keeps the permissions it was issued with:
to change them, the account must be authorized again (*Social Marketing >
Configuration > Social Media > LinkedIn > Link account*).
