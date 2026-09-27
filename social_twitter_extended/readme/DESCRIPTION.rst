Extends the X (formerly Twitter) integration of Odoo Social Marketing
(technical module ``social_twitter``).

Pro accounts
============

X accounts can be flagged as **Pro accounts**. For posts published only
on Pro X accounts, Odoo no longer checks the text against the standard X
character limit (the "Max Post Length" of the X social media, 280 by
default):

- the post can be scheduled and published whatever its length;
- the character counter only shows the current length;
- the preview shows the whole message instead of cutting it at the
  standard limit.

X itself then accepts or rejects the text, so no new limit is hardcoded
in Odoo (X changes it over time). If the X account is not really
subscribed to an X plan allowing longer posts, the error returned by X is
shown on the post as the failure reason.

When a post targets several X accounts and at least one of them is not
Pro, the standard limit still applies. Accounts that are not Pro keep the
standard Odoo behavior.

Threads
=======

Any X account (Pro or not) can publish a post as a **thread**: enable
*Is a thread* on the post and add the next posts of the thread, in order.
When publishing, Odoo posts the main message, then each post of the
thread as a reply to the previous one.

The posts of a thread get the same processing as the main message
(tracked links with the UTM values of the post, mentions handling), and
the same length rule: they are checked against the standard X limit,
except when every selected X account is Pro.

If a post of the thread fails, nothing already published is deleted: the
post of the account is marked as failed, and the reason tells which post
of the thread failed, with the error returned by X. Retrying a failed
post publishes it again from the main message.

Campaign reply
==============

A campaign can hold a *Fixed reply template for X* (e.g. "Learn more
at:"). On posts linked to that campaign, a *Reply URL for X* can be set:
right after the post (and its thread, if any) is published, Odoo replies
to the last published post with the fixed reply followed by that URL.
The URL is tracked like the links of the main message, so its clicks are
counted in the campaign.

The reply is only posted when both the fixed reply of the campaign and
the URL of the post are set. If the reply fails, the post stays
published and is marked as failed with the error returned by X.

X Articles
==========

*Social Marketing > X Articles* lets you write long-form **Articles** with
rich text (the Odoo HTML editor: text pasted from other tools keeps its
bold, italic, headings, links and lists) and an optional cover image, and
publish them on X.

Only X accounts flagged as **Pro account** in Odoo can be selected, and
Odoo refuses to create or publish an Article with any other account,
without calling X.

**The Odoo checkbox is not the X subscription.** Publishing Articles
requires the X account itself to have an X subscription that includes
Articles (X Premium). The *Pro account* checkbox only tells Odoo to allow
it: Odoo does not check the real subscription on X. If the account is
not entitled to Articles on X, X rejects the request and its error is
shown as is in the *Error message* of the Article (the Article goes to
*Error*).

Publishing an Article:

#. uploads the cover image (if any) with the v2 media upload of X
   (initialize, append, finalize, then waits for X to process it when
   needed). Unlike the upload of ``social_twitter``, every step is checked
   and the full response of X is shown on error: the core only reads an
   ``error`` key that the v2 API does not send, and its message ends with
   an empty ``(error: )``;
#. creates the draft (``POST /2/articles/draft``) with the title, the body
   and the cover;
#. publishes it (``POST /2/articles/{id}/publish``), which returns the id
   of the post created by X for the Article;
#. posts the campaign reply (see above) under that post, if the campaign
   has a fixed reply and the Article a reply URL.

The ids returned by X are stored on the Article, with a link to the post
(``https://x.com/i/status/<post id>``). If the draft was created but the
publication failed, *Reset to draft* and *Publish* create a new draft on
X: the previous draft stays in the X account. If only the campaign reply
fails, the Article stays published and the error is shown on it.

Body format sent to X
---------------------

The body is converted from HTML to the ``content_state`` format of the X
Articles API: a list of ``blocks`` (``text``, ``type``,
``inline_style_ranges``, ``entity_ranges``) and a list of ``entities``
(links). It looks like the DraftJS raw state but is not the same:
snake_case keys, and ``entities`` is a list, not an ``entityMap``.
Offsets are counted in UTF-16 code units, as in DraftJS.

Supported:

- paragraphs (``unstyled``) and line breaks inside them;
- bold, italic and strikethrough (style ranges inside a block);
- headings: ``h1``, ``h2``, ``h3`` (``header-one`` to ``header-three``);
  ``h4`` to ``h6`` become ``header-three``, X has no deeper level;
- links (``link`` entities on their text range);
- bulleted and numbered lists (``unordered-list-item`` /
  ``ordered-list-item``);
- quotes (``blockquote``).

Not supported, flattened or dropped:

- nested lists: X blocks have no depth, nested items follow their parent;
- code blocks: kept as plain text in a paragraph;
- tables: one paragraph per row, cells separated by ``|``;
- images inside the body, horizontal rules, embedded media: dropped
  (only the cover image is supported);
- underline, colors, fonts, alignment: dropped.

Scheduled posts with images (investigation)
===========================================

A post with images failing when published by the scheduler, while the
same post works when published immediately, was investigated. The
suspected cause (images uploaded to X when the post is scheduled, their
media ids expiring before publication; X media ids last 24 hours) is
**not** what ``social_twitter`` does on Odoo 19: the images are uploaded
when the post is published, in both cases, and a local reproduction
showed that both paths send exactly the same requests to X. The real
error returned by X on an affected post is needed to go further, so no
change is made about it in this module.
