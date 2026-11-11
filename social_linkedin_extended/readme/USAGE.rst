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
