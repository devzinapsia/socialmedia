========================
Social LinkedIn extended
========================

Description
===========

Extends the LinkedIn integration of Odoo Social Marketing (technical module
``social_linkedin``).

First comment on LinkedIn posts
-------------------------------

Right after a post is published on a LinkedIn page, Odoo adds a comment to it,
written by the same page. Typical use: put the external link in the first
comment instead of in the body of the post.

- Works for posts sent now and for scheduled posts, with a single mechanism:
  the comment is posted at the exact moment the core marks the post as
  published on each LinkedIn account (also after the *Retry* of the core on a
  post that failed).
- When a post is published on several LinkedIn pages, each page comments on
  its own post.
- The links of the comment go through Odoo link tracking, like the links of the
  post: they are shortened with the UTM values of the post, and their clicks
  are counted in the campaign. The final text is prepared when the post is
  published and stored, so a retry posts exactly the same text.
- A campaign can hold a *Default first comment for LinkedIn*, pre-filled on its
  posts that target a LinkedIn account while their first comment is empty
  (it can then be edited on each post).
- Posts without a first comment, and accounts of other social media, keep the
  standard behavior: no call is made.

What happens on errors
----------------------

The post always stays published: an error on the comment never changes the
status of the post.

- **Temporary errors** (LinkedIn rate limit, LinkedIn server error, network
  error, post not available yet): the comment stays *Pending* and an hourly
  scheduled action retries it, up to 3 attempts in total.
- **Other errors** (missing permission, invalid or expired token, retired API
  version, invalid request): the comment is *Failed* at once, without automatic
  retry.
- The status, the number of attempts, the date and the last error (cut, without
  any secret) are shown for each LinkedIn account on the post, and the chatter
  of the post tells, for each account, when the comment is posted or has failed
  and why. The *LinkedIn comment failed* filter lists the posts concerned.
- Social Marketing managers can *Retry comment* on a failed one, e.g. after
  reconnecting the account.

A comment is never posted twice: the stored comment id and status are checked
before any call, the retries of the scheduled action and of the button cannot
run at the same time on the same post, and every retry first looks on LinkedIn
for a comment of the page with the same text (a previous attempt may have
created it without Odoo knowing, e.g. after a timeout). If that lookup fails,
nothing is posted.

LinkedIn comment diagnostics
----------------------------

A *Test LinkedIn comment* action on LinkedIn accounts checks whether the page
can comment through the LinkedIn API: it creates and then deletes a real test
comment, and gives a report (see *Usage*).

Technical notes
---------------

The calls of this module go directly to the LinkedIn REST API with the access
token the core module stores on the account and its authentication headers,
except for the API version, which comes from a system parameter of this module
(the core calls keep their own version). Unlike the comment features of the
core, an error never marks the account as disconnected.

Difference with the X module
----------------------------

``social_twitter_extended`` (X) and this module are independent: neither depends
on the other.

- On X, the extra content of a post is a thread and a campaign reply (fixed text
  of the campaign followed by a URL set on each post); a free first comment
  only exists for X Articles. Here, every LinkedIn post can have a free first
  comment, with a default text per campaign.
- On X, failed follow-up posts and Article comments are retried by hand only.
  Here, temporary errors are also retried automatically by a scheduled action,
  and a retry first checks on LinkedIn that the comment does not exist yet.

Limitations
-----------

- Plain text only: no image in the comment, and ``@mentions`` or ``#hashtags``
  written in the comment are not turned into LinkedIn mentions (they stay plain
  text).
- 1000 characters at most, tracked links included. The LinkedIn API does not
  document a limit for comments; the lowest figure given by LinkedIn help pages
  is used.
- The comment is posted as the LinkedIn page of the account (the core only
  connects organization pages, not personal profiles).
- Only for posts published from Odoo. Once posted, the comment is not edited
  nor deleted from Odoo.
- Not tested yet against LinkedIn: how LinkedIn answers when a post published a
  few seconds before is not available yet. It is assumed to be "not found"
  (retried); if LinkedIn answers otherwise, the comment fails and can be
  retried with the button. Every failed attempt is logged on the server with
  the HTTP status.

Configuration
=============

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

Usage
=====

Adding a first comment to a post
--------------------------------

#. Create a post in *Social Marketing* and select at least one LinkedIn
   account: the *LinkedIn first comment* field appears.
#. Write the comment (plain text, 1000 characters at most), e.g.
   ``Read the full article: https://www.example.com/article``. If the campaign
   of the post has a default first comment, it is pre-filled and can be edited.
#. Post now or schedule the post as usual.

Once the post is published, the *LinkedIn first comment* section of the post
shows, for each LinkedIn account, the status of the comment (*Pending*,
*Posted*, *Failed*), its date, the number of attempts and the last error. The
final text, with its tracked links, and the LinkedIn URN of the comment are
available as optional columns.

On a failed comment, fix the cause given in the error (e.g. reconnect the
account), then click *Retry comment* (Social Marketing managers only). Use the
*LinkedIn comment failed* filter of the posts to find them.

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
