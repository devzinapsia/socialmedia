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
