========================
Social LinkedIn extended
========================

Extends the LinkedIn integration of Odoo Social Marketing (technical module
``social_linkedin``).

This first version only adds a **LinkedIn comment diagnostics** tool: it checks
whether a connected LinkedIn page can comment on its own posts through the
LinkedIn API, before the automatic first comment on LinkedIn posts is built on
top of it.

The diagnostics call the LinkedIn REST API directly, with the access token the
core module stores on the account and the same authentication headers, except
for the API version, which comes from a system parameter of this module (the
core calls keep their own version). Unlike the comment features of the core,
an error never marks the account as disconnected.

Configuration
=============

LinkedIn API version
--------------------

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
-----------

Commenting as a LinkedIn page needs the ``w_organization_social_feed``
permission (``w_organization_social`` in older LinkedIn documentation),
granted only to page administrators, through a LinkedIn app approved for the
Community Management API. A token keeps the permissions it was issued with:
to change them, the account must be authorized again (*Social Marketing >
Configuration > Social Media > LinkedIn > Link account*).

Usage
=====

How to run the diagnostics
--------------------------

Only Social Marketing managers (group *Social Marketing / Social Manager*) can
run it.

#. Go to *Social Marketing > Configuration > Social Accounts* and open a
   LinkedIn account.
#. Click *Test LinkedIn comment*.
#. Check the *Post URN*: by default, the last post published from Odoo by this
   account, else its last post fetched in the *Feed*. Any post of the page can
   be used (``urn:li:share:...`` or ``urn:li:ugcPost:...``).
#. Click *Run test*. **This creates and then deletes a real comment on that
   page** ("Odoo comment test, will be deleted").
#. Click *Copy report* and send the report.

The report gives:

- the date and time (UTC), the account and the author URN;
- the route used (direct call to the LinkedIn REST API) and the API version
  sent, next to the version of the core module;
- whether the account has an access token (the token itself is never shown),
  and its expiry and granted permissions when LinkedIn can reveal them (only
  when the account was connected with your own LinkedIn app, see *Social
  Marketing > Configuration > Settings > Use your own LinkedIn Account*);
- for the creation and the deletion of the test comment: the HTTP status, the
  duration in milliseconds and the error returned by LinkedIn, cut and without
  any secret;
- a result line: OK, or the reason why the page cannot comment (missing
  permission, invalid token, retired API version, temporary error...).

If the deletion fails, or if LinkedIn accepts the comment without returning its
id, the report says so: delete the test comment by hand on LinkedIn.

Bug Tracker
===========

Bugs are tracked on `GitHub Issues <https://github.com/devzinapsia/socialmedia/issues>`_.
In case of trouble, please check there if your issue has already been
reported, mentioning the ``social_linkedin_extended`` module in the
issue title.

Credits
=======

Authors
-------

* Zinapsia
