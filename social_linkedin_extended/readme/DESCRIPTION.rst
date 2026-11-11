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
