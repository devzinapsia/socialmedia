# Zinapsia — Odoo development project memory

This file is generic and lives in multiple repositories, on multiple machines and
operating systems (macOS, Windows) — every Odoo module development repo (e.g.
`account-financial-tools`, `stock`, `sales`, `rrhh`, `phantom`), and every
client/odoo.sh deployment repo. Only the section relevant to the repo you are
actually in applies. Detect which kind of repo you're in before doing anything:

- If it contains Odoo module folders (each with its own `__manifest__.py`),
  it's a **module development repo** → use Section A.
- If it has a `.gitmodules` file referencing other git repos (e.g.
  `zinapsia/*`, `ingadhoc/*`, `OCA/*`), it's a **client/deployment repo** →
  use Section B.

## Local, per-machine paths — read this before anything else

This file NEVER hardcodes absolute filesystem paths (like Odoo source locations,
or where client repos/database backups live on disk), because it's shared across
machines with different operating systems and folder layouts (this repo may be
cloned on a colleague's Windows machine, not just this one). Instead:

1. At the start of a session, look for a local paths file in the current user's
   home directory:
   - macOS/Linux: `~/.claude/local-paths.env`
   - Windows: `%USERPROFILE%\.claude\local-paths.env`
2. If it exists, read it (`KEY=value` per line, `#` for comments) and use those
   values wherever this file or a task refers to a "local path". Expected keys:
   - `ODOO_19_SRC` / `ODOO_18_SRC` — Odoo source code, for confirming real
     view/menu/field names before writing an xpath or referencing a core field.
   - `ZINAPSIA_MODULES_ROOT` — the parent folder that holds every repo of
     modules Zinapsia develops (e.g. `account-financial-tools`, `stock`,
     `sales`, `rrhh`, `phantom`, `dashboards`, `miscellaneous`, `pos`, ...).
     A specific repo's path is `<ZINAPSIA_MODULES_ROOT>/<repo-name>` — don't
     ask for each repo's path individually, derive it from this root plus the
     repo name.
   - `ZINAPSIA_CLIENTS_ROOT` — the parent folder that holds every client's
     odoo.sh deployment repo (e.g. `grupolara`, `umbrella`, `s-train`, `iteo`,
     `pi`, `zinapsia`). This list of clients grows over time — a specific
     client's path is `<ZINAPSIA_CLIENTS_ROOT>/<client-name>`, derived the
     same way. If a client folder you expect isn't there, ask the user instead
     of assuming it doesn't exist yet or picking the closest-sounding name.
   - `ZINAPSIA_DB_BACKUPS_ROOT` — where downloaded odoo.sh database backup
     `.zip` files live, for local restores when a task needs to test against
     real client data. Filenames follow the pattern
     `<account>-<client>-<branch>-<id>_<date>_<time>_test_nofs.zip` but the
     `<account>` prefix varies (seen: `devzinapsia-...`, `campopablo-...`) —
     match by the `<client>` name appearing in the filename, don't assume a
     fixed prefix. List the folder and confirm the exact file with the user
     if more than one plausible match exists (e.g. multiple dates for the
     same client).
3. If the local paths file does NOT exist, or is missing a key/root you need
   for the current task, ASK the user for that path — don't guess a default,
   and don't assume it matches a path used in an earlier conversation on a
   different machine. Offer to create/update the file with what they give you,
   so future sessions on this same machine don't have to ask again.
4. Never suggest committing this file to any repo, and never write local paths
   directly into this shared `CLAUDE.md` — if you find yourself about to do
   that, stop and use the local paths file instead. This also applies to any
   other project-specific file that currently hardcodes a machine path (e.g. a
   migration project's `CLIENT_INFO.md`) — if you notice one, flag it to the
   user as worth updating to reference these roots instead, rather than
   copying the hardcoded value forward into new work.

## Shell / OS awareness

Confirm what shell/environment you're actually running in before assuming command
syntax (macOS/Linux default to bash/zsh; Windows may be PowerShell, Git Bash, or
WSL — they are not interchangeable for things like path separators, environment
variable syntax, or flags on commands like `grep`/`find`). If a command fails and
the likely cause is shell syntax rather than logic, try the equivalent for the
actual shell in use instead of repeating the same command.

## Company info (used in every manifest / LICENSE / README)

- Legal name: Zinapsia SRL (used in the LICENSE file's copyright line)
- Manifest `author` / README "Credits > Authors": just "Zinapsia" (no
  "SRL") — this is the string Odoo's Apps list groups modules by, and it
  must match exactly across all modules or they split into separate
  author groups in the UI. Don't use "Zinapsia SRL" here even though it's
  the legal name.
- Website: https://www.zinapsia.com
- Dev contact: dev@zinapsia.com
- GitHub org: https://github.com/devzinapsia

## Things to always ask — don't assume, don't skip

1. **Brand-new module**: should it be `auto_install = True` (installs
   automatically as soon as its dependencies are present), or a regular
   opt-in module (`auto_install = False`, the default)?
2. **New standalone model with its own ABM** (a new model with its own
   list/form views, i.e. a new "table" the user manages, like a
   classification or configuration catalog): ask —
   - Does it need the chatter (`mail.thread` / `mail.activity.mixin`,
     `message_ids`/`activity_ids` fields and the chatter widget in the
     form view)? Don't add it by default.
   - Which fields should be available as filters in its search view, and
     which (if any) as default group-by options?
3. **New field added to an existing model** (e.g. adding a field to
   `account.move`, `stock.picking`, `res.partner`, etc.): ask —
   - Should it be searchable/filterable from the search bar?
   - Should it be available as a "Group By" option?
   - Should it be added as an optional column in the relevant list/grid
     view (`optional="hide"`)?
   Don't assume any of these — a new field is not automatically wired into
   search/group-by/grid just because a previous module did it that way.

---

## Section A — Module development repos (e.g. account-financial-tools, stock, sales, rrhh, phantom)

### Environment
- Odoo 19 source, used for tests and to confirm real view/menu/field names
  before writing any xpath or referencing a core field (never guess these from
  memory): the path in `ODOO_19_SRC` from the local paths file (see above).
- Odoo 18 source, same purpose, for modules targeting 18.0: `ODOO_18_SRC` from
  the local paths file.
- If a task needs a path that isn't in the local paths file yet, ask the user
  for it (see "Local, per-machine paths" above) rather than assuming it matches
  a path used in an earlier conversation.
- Always confirm the current git branch matches the Odoo version you're
  developing for (branch `19.0` → check against the Odoo 19 source, branch
  `18.0` → Odoo 18 source). Run `git branch` and check before starting;
  don't assume the checked-out branch is the right one.

### Module folder naming
- English, snake_case, descriptive of the feature (unless the repo/team has
  explicitly agreed on a different convention for that repo — e.g. a repo
  named in Spanish may host modules with a Spanish-leaning prefix by
  deliberate choice; if unsure, ask rather than assume).

### Standard module contents (every module must have all of this)
```
<module_name>/
├── __init__.py
├── __manifest__.py
├── LICENSE                    (full AGPL-3 text, same as repo root)
├── README.rst                 (documents the functionality — see below)
├── models/
├── views/
├── security/
├── data/                       (config/seed data, if any, noupdate="1")
├── i18n/ (.pot, es.po, es_AR.po — always fully translated, no empty msgstr)
├── static/description/index.html
├── readme/ (DESCRIPTION.rst, CONFIGURE.rst, USAGE.rst — source fragments)
└── tests/
```
- `README.rst` at the module root must document what the module does, how
  to configure it, and how to use it. Build it from the `readme/*.rst`
  fragments (OCA convention), plus a "Bug Tracker" section linking to this
  module's own GitHub repo URL, and a "Credits > Authors" section listing
  "Zinapsia". Don't skip this file — `static/description/index.html`
  alone is not enough, that one is only for the Apps Store listing.

### Manifest fields (mandatory on every module)
- `license`: `"AGPL-3"`
- `author`: `"Zinapsia"`
- `website`: `"https://www.zinapsia.com"`
- Also put this module's own GitHub repo URL in `README.rst`'s "Bug
  Tracker" section (not in the manifest — the manifest `website` key only
  holds one URL, and that slot is reserved for the company site).

### Coding language rules (strict)
1. All Python/XML/JS code and ALL comments/docstrings: English, no
   exceptions.
2. All UI-facing strings (field `string=`, menu/action `name=`, help text):
   English source, fully translated in `es.po` and `es_AR.po` — never leave
   `msgstr ""` empty.
3. Business/master-data literal seed values may stay in Spanish when
   they're proper nouns or client-facing business terms — confirm with the
   user case by case, don't assume.
4. Label capitalization: sentence case only — first letter capitalized,
   rest lowercase, except proper nouns (e.g. "Agreed payment method", not
   "Agreed Payment Method"). Applies to English source AND Spanish
   translations, on every field/menu/action label added.

### View development rules
- Never assume a view id, menu id, field name, or xpath target from memory —
  confirm it against the real Odoo source path from the local paths file (or
  against how it was already solved in an existing sibling module in this
  same repo). If it can't be confirmed, leave an explicit `TODO` comment and
  flag it instead of guessing.
- `account.move` has a single shared form view across all `move_type`
  values (invoices, bills, credit/debit notes) — use
  `invisible="move_type not in (...)"` to scope a field, instead of
  duplicating views. (The same "one shared view across sub-types" pattern
  shows up elsewhere in Odoo too — e.g. `stock.picking` across picking
  types — check for it before assuming you need separate inherited views.)
- Modern view syntax only: `readonly="..."`, `invisible="..."` as direct
  attributes — never `attrs={}` (deprecated).
- Extra grid/list columns that shouldn't show by default: `optional="hide"`.
- Search view "Group By" filters: available as an option, not
  auto-activated, unless the user explicitly asks for auto-activation.

### Security patterns
- `ir.model.access.csv`: read access for the module's relevant base user
  group, full CRUD for the module's relevant manager/admin group (e.g.
  `account.group_account_invoice` / `account.group_account_manager` for
  accounting modules, `stock.group_stock_user` /
  `stock.group_stock_manager` for inventory modules — adjust to the
  module's actual domain, don't default to accounting groups on a
  non-accounting module).
- Multi-company models: `ir.rule` domain
  `['|', ('company_id', '=', False), ('company_id', 'in', company_ids)]`
  (empty `company_id` = shared across all companies).

### Testing & validation before showing a diff
1. `python3 -m py_compile` on all `.py` files.
2. Well-formed XML check on all `.xml` files.
3. TransactionCase tests covering the core scenarios of the module.
4. **Always run this install/uninstall cycle against the matching local
   Odoo source** (the Odoo 19 or 18 path from the local paths file, whichever
   matches the branch) before considering the module done, using a local
   test database:
   - Install the module. Confirm it installs with no errors.
   - Verify it's actually active (e.g. `-i <module> --stop-after-init` exits
     cleanly, and/or check `ir.module.module` state is `installed`).
   - Uninstall the module (`-u`/`--uninstall` as applicable, or via the
     Apps list). Confirm it uninstalls cleanly with no leftover errors.
   - Install it again. Confirm the second install also succeeds cleanly.
   - Report the outcome of all four steps explicitly — don't just say
     "tests passed" without showing this cycle ran.
   - If there's no local test database set up yet to run this against, ask
     what's needed to set one up before marking the module as ready for
     review — don't skip this step silently.

### Git workflow
- Always show `git status` and the full `git diff` before committing.
- Never commit or push without explicit user confirmation — ask first,
  every time.
- Commit message format (English): `[ADD] <module_name>: <short summary>`.

### Hard-won Odoo debugging lessons
- `self.assertRaises(...)` in Odoo's `TransactionCase` wraps the call in a
  cursor savepoint that rolls back once the expected exception is caught —
  this erases every change the code made before raising, not just the
  exception itself. If a test needs to inspect state *after* an expected
  exception, use a manual `try/except` + `self.fail(...)` instead of
  `self.assertRaises()`.
- When overriding a method on a core model that *other installed modules
  also override* (e.g. `account.payment.action_post()`,
  `stock.picking.button_validate()`), never assume your override is the
  one that actually runs, or that it runs at all. Verify with
  `inspect.getsourcefile(type(record).method_name)` /
  `inspect.getsourcelines(...)` in `odoo-bin shell` before spending time
  debugging logic that never executes — the real MRO owner is sometimes a
  third-party module loaded later.
- A field meant to identify "the related record" that a user will also
  need to reference from a *visual* domain/filter builder should reuse an
  existing, obviously-named core field rather than a new custom technical
  field with a different label. Users naturally pick the field with the
  intuitive name in the picker; if that's not the one your code actually
  populates, conditions silently never match and the bug looks like
  "nothing works" with no error anywhere.
- When syncing a relational field from another source on every change, use
  `Command.set` (replace) not `Command.link` (add-only) — otherwise stale
  entries accumulate over time, and can leak into *other* modules that
  also read that same field, not just your own logic.
- If a module needs to optionally interoperate with a third-party module
  that isn't installed in every deployment reusing this repo (e.g.
  ingadhoc's modules on some clients but not others), build a separate
  glue module (`<base_module>_<other_module>`, `depends=[base, other]`,
  `auto_install=True`) rather than hard-depending on the optional module
  from the base one, or littering it with defensive
  `if field in self._fields` checks. Keeps the base module portable across
  every client repo that reuses it.
- Some third-party modules add their own separate, *unnamed* `<notebook>`
  to a form instead of extending a core model's named one. Inserting a new
  tab into the "obviously correct" named notebook can silently render as a
  disconnected second tab strip. Before assuming a tab landed where you
  put it, check the actual resolved view (`env['model'].get_view(view_id=...,
  view_type='form')` and inspect the `<notebook>` elements in the returned
  arch) — and use `position="move"` plus a high view `priority` to relocate
  it if needed.
- To verify a fix against a client's actual third-party modules instead of
  guessing: point a temporary `--addons-path` at that client's deployment
  repo submodules (e.g. `<client-repo>/ingadhoc/*`, `<client-repo>/OCA/*`)
  and install for real in a scratch local database. Reading those
  submodules for this kind of investigation/testing is fine and often the
  only reliable way to reproduce a client-specific bug — the "never touch
  `ingadhoc/*`/`OCA/*`" rule (Section B) is about not *modifying* them, not
  about being unable to read/install them locally for diagnosis.
- Some modules are meant to grow over time with more than one feature added
  under the same "base"-style module (as opposed to `dashboards_base` /
  `sales_base`, which are empty shared infrastructure for sibling modules to
  depend on). When a module is explicitly described as this kind of growing
  base, organize `models/` with one file per feature from the start, so
  adding the next feature later doesn't require reshuffling existing code.

---

## Section B — Client / odoo.sh deployment repos (e.g. grupolara, umbrella)

### Environment
- These repos deploy Odoo for a specific client via odoo.sh, and consume
  module repos (like account-financial-tools, stock, phantom) as git
  submodules, typically grouped under a `zinapsia/` folder alongside other
  submodule groups such as `ingadhoc/*` and `OCA/*`.
- **Never touch `ingadhoc/*` or `OCA/*` submodules unless explicitly
  asked** — only work with `zinapsia/*`.
- Confirm the tracked branch of a submodule with:
  `grep -A5 "<submodule-name>" .gitmodules`

### Golden rules for submodule commands
1. Always run submodule commands from the **repo root**, never from inside
   a subfolder — a submodule path is relative to the repo root, and
   running the command elsewhere can make git silently update *all*
   submodules instead of just the intended one.
2. Always scope the update to the specific path:
   ```bash
   git submodule update --remote --merge -- zinapsia/<module-repo>
   ```
3. `git checkout <branch>` does NOT auto-realign submodule working trees to
   what that branch expects. After switching branches, check `git status`:
   if submodules other than the intended one show up as "modified (new
   commits)", realign them with
   `git submodule update -- <path1> <path2> ...`, or configure
   `git config submodule.recurse true` once, locally, to avoid this
   going forward.

### Standard update flow (repeat per branch — pointers are independent per branch)
```bash
cd <repo root>
git checkout <branch>
git submodule update --remote --merge -- zinapsia/<module-repo>
git status   # must show ONLY the intended submodule as modified
git add zinapsia/<module-repo>
git commit -m "Update <module-repo> submodule: <short summary of what changed>"
git push origin <branch>
```

### Branch caution
- `staging2` is the primary branch for first-round testing of new submodule
  changes.
- Never push to a production branch (e.g. `main`) without explicit
  confirmation in the conversation that testing passed on a staging branch
  first — even if the update already went out to `staging2`/`staging`.

### A pushed submodule update may need a rebuild to actually take effect
Updating the submodule pointer and pushing does NOT guarantee the running
Odoo server picks up the new code. On odoo.sh, a push to a linked branch
usually triggers an automatic rebuild — but if a user reports "I pushed the
fix and it's still broken," don't assume the code itself is wrong before
confirming a rebuild actually ran:
1. Ask the user to check the module's installed version in **Apps** (should
   match the version in the latest commit's `__manifest__.py`). If it's
   older, the update never ran on that server at all.
2. If the version *does* match but behavior is still the old one, the DB
   update likely ran (picking up view/field/version changes) but the
   long-running web workers may still have the old Python source loaded in
   memory — ask the user to trigger an explicit rebuild (not just an app
   update) and retest.
View/XML changes are less likely to hit this than Python logic changes,
since views are re-read from the DB on every request, but a rebuild is the
safe first troubleshooting step either way when "it looks like my fix
should have worked but didn't."
