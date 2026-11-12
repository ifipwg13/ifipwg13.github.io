# IFIP WG1.3 website

A static group homepage, public member list, and meeting website.
Registration and discussion use the private GitHub repository. Group information,
the roster, and historical meetings use public-only content stored here.

The prototype uses plain HTML/CSS and self-hosted scripts for list ordering and
the own-site talk and participation forms, with no runtime dependencies or
additional backend. The forms call GitHub directly using organizer-issued credentials.
Participation and discussion belong in the private `ifipwg13/meetings` repository.
The website displays each talk's date/time, title, entered authors, and expandable
abstract. An optional PDF makes the title a link to the public slide file.

## Preview in Firefox without publishing

1. Sign in to GitHub in Firefox and open this repository.
2. Select `prototype/meeting-management`, then choose
   **Code → Codespaces → Create codespace**. This is the branch maintained by
   meeting synchronization. For unmerged changes, use **Preview this feature
   draft** below instead.
3. Wait for the browser editor to open. If there is no terminal panel, use the
   top-left menu **☰ → Terminal → New Terminal**.
4. Paste this command into the terminal and press Enter:

   ```sh
   python3 scripts/preview_server.py --port 8001
   ```

5. When **Open in Browser** appears, click it. Otherwise, open the **Ports** tab
   beside **Terminal**, find port **8001**, and click its **Open in Browser**
   globe icon. If the port is missing, choose **Add Port** and enter `8001`.
6. The group homepage opens in a new Firefox tab with a **Synchronized preview** bar.
   Use **Members** and **Meetings** in its navigation. On the meetings page,
   click a meeting's name to inspect it.

Keep port visibility **Private**. This preview is separate from GitHub Pages:
opening it does not merge the pull request or publish the website. The Python
server serves the root homepage, `members/index.html`, and the allowed HTML/CSS,
meeting-list and talk-form scripts, exact IFIP logo path, and narrowly allowed
versioned PDF paths under `prototype/` on the selected public branch. Other
root files, hidden files, and private records cannot be served. It fetches the
branch when a page is requested, so refreshing Firefox receives updates without
another terminal command. Your local files and branches are not changed.
The server includes the stylesheet, list sorter, and IFIP logo in each preview
page, using the same Git version for all assets. Styling, sorting, and the logo do not depend on a
second browser request. The **Preview status** bar shows the source branch,
retrieved version, and time (Europe/Berlin).
Port **8001** distinguishes this preview from an older server on port 8000.

**Synchronized preview** follows `prototype/meeting-management`. After a private
Issue changes, wait for **Prepare meeting** to succeed, then refresh Firefox.
**Review snapshot** follows an explicitly selected feature branch. Refreshing
that branch does not bring in Issue updates, including after its PR is merged.
Use **Switch to synchronized preview** in its status bar to view current meeting
states. The switch is read-only and keeps subsequent navigation in that view;
its URL starts with `/__preview/synchronized/`. No branch is merged or modified.
These status controls appear only in the Codespaces preview, not the static site.

Use a personally billed, two-core codespace within your available free allowance.
The creation dialog identifies who pays. A GitHub Free personal account includes
120 core-hours and 15 GB-month of storage per month; organization accounts do not
include a free Codespaces allowance. Stop the codespace at
<https://github.com/codespaces> when finished; delete it after testing to release
storage. No local software installation is needed.

## Using the prototype

Member and organizer instructions are in the
[private repository README](https://github.com/ifipwg13/meetings/blob/main/README.md),
which requires repository access.

## Update an existing preview after integration

After this feature is approved and merged into `prototype/meeting-management`,
update an existing preview with the following steps. To review the unmerged
feature in an existing Codespace, use **Preview this feature draft** below.

1. Click the terminal running the server and press **Ctrl+C** to stop it.
2. Paste this whole block and press Enter. It runs the current preview server
   from GitHub and preserves local files, even if your checkout is older:

   ```sh
   cd "$(git rev-parse --show-toplevel)" &&
   git fetch origin refs/heads/prototype/meeting-management:refs/remotes/origin/prototype/meeting-management &&
   meeting_preview_script="$(mktemp /tmp/meeting-preview.XXXXXX.py)" &&
   git show origin/prototype/meeting-management:scripts/preview_server.py > "$meeting_preview_script" &&
   python3 "$meeting_preview_script" --repository "$PWD" --port 8001
   ```

   The terminal must report **SYNCHRONIZED PREVIEW on port 8001**. If it reports an error,
   copy that error for diagnosis; the block stops rather than running older code.
3. Close the old preview tab. In **Ports**, open **8001** using its globe icon.
   Add port `8001` if it is absent, keeping its visibility **Private**. Confirm
   the new tab shows the **Synchronized preview** bar, styled buttons, and the current
   meetings. Subsequent updates need only a browser refresh.

The preview uses the same paths as static hosting: `/` is the group homepage,
`/members/` is the roster, and `/prototype/` is the meetings list. Old preview
links under `/meetings/`, `/legacy-meetings/`, and `/assets/` redirect beneath
`/prototype/`. Directory links without a final slash redirect to the correct URL. HTML, styling,
redirects, and errors all instruct browsers not to cache preview responses. A
GitHub or stylesheet failure shows an error rather than an old or unstyled page.

After meeting updates, refresh Firefox. No further `git pull` is needed to display
new meetings or activate their talk buttons. The server must stay running and
the Codespace must be able to reach GitHub. If an update fails, the preview shows
an error rather than silently displaying an old meeting list.

## Editing the site

- `index.html`: group name, affiliation, current/past chairs, Aims, and Scope;
  edit the HTML directly. Corina Cirstea is first among the past chairs as
  specified by the group. Do not infer appointment dates or terms.
- `members/index.html`: the Members and Emeriti lists, with one entry per `<li>`.
  Preserve names, country codes, categories, and deceased markers when updating
  entries. Leadership roles are listed on Home rather than beside members.
  This public roster does not grant or remove private GitHub repository access.
- `prototype/assets/style.css`: the shared stylesheet for every page. The
  variables at the top control the main colours and content width. Navigation
  and member columns wrap for small screens without a framework. The purple
  background, white panels, green navigation, and rounded corners follow the
  original site's appearance; `prototype/assets/ifip-logo.png` is the local logo.
- `prototype/data/legacy-meetings.json`: historical meeting/talk content; edit
  this dataset and rerun the renderer described below.

The homepage, members page, and meeting list share Home / Members / Meetings
navigation. Meeting detail pages link back to the list. Relative paths are the
same in the preview and static site. Neither the homepage nor the roster depends
on JavaScript, a login, or another website at page-load time.
On Home, the logo, WG brand, and IFIP TC1 text link in the same tab to
<https://www.ifip.org/technical-committees-and-working-groups/>. Only IFIP TC1 has
ordinary link styling; all three links retain keyboard focus outlines. On other
pages, the logo and WG brand continue to link back to the local Home page.

### Synchronized meetings

For functional testing, use **Synchronized preview** on
`prototype/meeting-management`, without a `--branch` option. A successful
administrator submission creates its registration and working talk form in one
run. No per-meeting setup PR is required. Wait for **Meeting ready** and refresh.
The private automation verifies the committed meeting card, detail page, and
talk-form link before reporting success. Read members can participate; the
creation and repair paths remain restricted to administrators.

Administrators edit meeting names in the canonical registration Issue's Title
and edit dates, location, and description in its designated opening-post fields.
Saving triggers synchronization of both the card and detail page; configuration
is derived, so these values are entered once. Clearing Description removes it.
DD-MM-YYYY and DD-MM-YY are accepted (YY means 20YY), with optional leading zeros
for day/month: `1-3-27` is displayed as `01-03-2027`. Archived metadata can be
corrected; hidden meetings stay absent until
restored, with individual talk visibility preserved.

Meeting cards have no archive status paragraph. Archived detail pages say
**This meeting is archived, registration and talk submission are closed.**
Their Participation and Add talk controls remain disabled. Talk visibility
retains its existing behavior; public talk titles are non-clickable.

Synchronization runs on Issue events, with no periodic publication timer.
Wait for **Prepare meeting** to succeed, then refresh: every HTML request fetches
the current branch. There is no automatic browser reload. The two-second limit
on supporting requests does not delay HTML updates. Ordinary updates process the
affected meeting; the manual administrator workflow remains a full reconciliation.
GitHub's scheduling and queue can add delay, so no fixed update time is guaranteed.

`prototype/index.html` lists meetings. Each event has its own directory under
`prototype/meetings/`; `prototype/assets/style.css` supplies the shared styling.
`prototype/assets/meetings-list.js` puts all cards in descending start-date order
in the same list, including historical meetings interleaved with Issue-backed
meetings. It moves existing elements without fetching data or duplicating cards.
Links within the site are relative, so they work in the Codespaces preview and
under `/prototype/` on a future Pages deployment.

Cards are ordered by start date, latest first. **When:** shows DD-MM-YYYY dates
or date ranges, **Where:** shows the location, and descriptions remain unlabeled
paragraphs. Meeting hours and timezones are not displayed. Talk slots are local
24-hour clock values. Matching talk Issues appear on cards and meeting pages as
**09:00 — title by authors**, with an underlined, non-clickable title. Automatic meeting prefixes and Issue-number labels are omitted.
Each Issue-backed meeting page shows an initially collapsed **Abstract** disclosure
beside each talk that has supplied abstract text. Its collapsed row reads
**09:00 — Title by Presenter ▸ Abstract** when space permits. Long titles and small
screens wrap naturally. Opening Abstract places the full text below that row.
Titles and presenter names are underlined and are not private-repository links.
Abstracts are escaped text with paragraph breaks; Issue-backed
index cards omit them.
Comments, registration accounts, and unrelated private content remain private.
Talks labeled `talk-hidden` are omitted completely, including their links. Meeting
Hide takes precedence over talk visibility. Closed talks have no added status suffix;
archived talks remain synchronized, with late submissions excluded by the private
archive cutoff. Hide/restore preserves individual talk settings.
The `generated-meetings` markers reserve the Issue-backed portion of the list
for generated updates; the rest of the index is preserved. A meeting's name
opens its detail page. Cards have no View meeting, Archive, or Hide buttons.

### Historical meeting content

`prototype/data/legacy-meetings.json` contains only meeting names, start/end dates,
locations, talk titles, authors, and abstracts. It has no private-repository records or
administrative state. Dates are stored as ISO dates and displayed as DD-MM-YYYY.
The Python standard-library renderer writes static cards inside the same meeting
list and detail pages under `prototype/legacy-meetings/`:

```sh
python3 scripts/build_legacy_meetings.py
python3 scripts/build_legacy_meetings.py --check
```

For each historical talk, `authors` is the presenter identified by the explicit
“by Name” field. Supplied “Joint work with” information belongs in `abstract`,
after the original text separated by a blank line. If there is no abstract text,
that supplied collaboration line can be the entire `abstract` value. Leave
`abstract` empty when neither was supplied. Do not infer names or content.
Talk titles and presenters display as plain **Title by Presenter** text; they
are not links. The **Abstract** disclosure contains the full abstract value.

The renderer preserves the `generated-meetings` region exactly. Its own
`legacy-meetings` markers are ownership boundaries inside the same section,
without a separate visible group. Historical cards use the same styling, with
clickable meeting names and expandable talks/abstracts where present. They have
no registration, submission, archive, hide, or talk-management controls. Native
disclosures work without JavaScript. The list sorter only orders existing cards;
historical pages make no requests to another website or private repository.

The private README explains how to create, archive, hide, and restore meetings.
Meeting metadata, talk titles, entered authors, and abstracts belong in public files. Never
copy attendance, comments, unrelated Issue sections, or GitHub account identities into public files,
commits, or PR descriptions.

Hiding removes current listings, not previously published Git history, earlier
artifacts, external caches, screenshots, or downloaded copies. The private Issue
and its discussion remain retained. Administrator instructions are in the private
README; ordinary members retain Read access and cannot manage visibility labels.

Meeting pages place **Participation | Add talk** in a single
responsive group. These links remain visible on the static site; GitHub enforces
private-repository access. Active members need Read access or higher. Archived
pages disable both participation changes and Add talk. Hidden meetings
have no public page. Meeting administration uses `archived` and `hidden` on the
private registration Issue, under the existing Admin/Read role model. The private
README gives the Labels-menu steps. There are no public administrative buttons.
There is no talk-level Hide shortcut. An Admin opens the talk's private Issue
from the repository Issues list and applies/removes `talk-hidden`.
This label still controls publication on both meeting cards and detail pages.
The meeting-level `hidden` label remains separate. Hidden talks have no public
identifying placeholder.

## Preview this feature draft

In a Codespace opened from this feature PR, stop an existing preview with Ctrl+C,
then run:

```sh
python3 scripts/preview_server.py --branch feature/talk-pdf-uploads --port 8003
```

Open port **8003** using **Ports → Open in Browser**. Firefox displays the review
branch and refreshes it from GitHub, with HTML, styling, and the list sorter from
the same commit.
This optional branch selection leaves the existing prototype preview default
unchanged. Issue-backed pages in this feature draft are a review snapshot.
The bar must say **Review snapshot**, name this feature branch, and offer
**Switch to synchronized preview**. Use the review view for unmerged presentation
changes. This feature adds optional PDF uploads and simplifies the forms. Add talk
asks only for Password alongside its public fields; Participation keeps Name and
Password. Meeting creation defaults the end date to the start date.
The private compatibility change must be integrated before real submissions from
these member forms.
Read-account testing and private editing instructions are in
[the feature guide](https://github.com/ifipwg13/meetings/blob/feature/talk-pdf-uploads/README.md).
No PR is merged or Pages website published by starting a preview.

In an existing Codespace with older local scripts, press **Ctrl+C** to stop its
server, then paste this entire block. It runs the review branch's server without
switching branches or overwriting local work:

```sh
cd "$(git rev-parse --show-toplevel)" &&
git fetch origin refs/heads/feature/talk-pdf-uploads:refs/remotes/origin/feature/talk-pdf-uploads &&
group_preview_script="$(mktemp /tmp/group-preview.XXXXXX.py)" &&
git show origin/feature/talk-pdf-uploads:scripts/preview_server.py > "$group_preview_script" &&
python3 "$group_preview_script" --repository "$PWD" --branch feature/talk-pdf-uploads --port 8003
```

Open port **8003** from **Ports**, keeping it **Private**. The first page must be
the group homepage with Home / Members / Meetings navigation and a **Review
snapshot** status bar. This block does not change local HTML, the checked-out
branch, or the published site. For current Issue states, click **Switch to
synchronized preview**; the status must then say **Synchronized preview** and
name `prototype/meeting-management`.

After the paired implementation is approved, integrate the private parser first,
then this public feature into `prototype/meeting-management`. Distribute a shared
Read-account password with the upload repository selected and Contents read/write
for PDF tests. Complete the private PDF setup guide first.
Keep website-publication PR #1 unmerged.
Refresh the existing **Synchronized preview** tab; no Codespace restart or new
port is needed. Do not test new live submissions before both integrations.

The public feature PR targets the existing prototype branch. Public website PR
#1 stays draft and unmerged. After the paired feature is approved and integrated, use
the normal preview command without `--branch` for real event synchronization.
The isolated feature branch remains a review snapshot until it is updated again;
merging it does not make it the synchronization target.

GitHub Pages currently publishes `main` from the repository root. Keep publication
PR #1 unmerged throughout initial testing, including second-meeting tests.
Merging or publishing requires separate explicit approval; no deployment workflow
or Pages configuration is introduced here.

The preview server uses the Git authentication already provided by Codespaces.
It needs no extra token or secret and reads no private Issues. The static site
remains HTML/CSS with self-hosted list and talk-form scripts. To test rendering and preview
synchronization without credentials or internet access, run
`python3 -m unittest discover -s tests -v`. A read-only integration test also runs
when the private checkout is available as a sibling directory; otherwise that
test is skipped. It uses in-memory fixtures and does not write private records.

If Playwright and Chromium are already installed, run the optional browser
regressions with `python3 tests/browser_meetings.py`. These exercise the actual
HTML/CSS/JavaScript at desktop, 375 px, and 320 px widths, using local HTTP only.
They check sorting across both card types, repeated sorting without duplicates,
all historical detail pages, exact presenter/abstract text, native keyboard
disclosures, inline abstract alignment, underlined noninteractive legacy text,
removed meeting shortcuts, Home link destinations and keyboard focus, and
overflow. They also check Home / Members /
Meetings navigation through detail pages, the roster on desktop/mobile, and
group-page/abstract use with JavaScript disabled. They add no site dependencies.


## Own-site talk form

`prototype/submit-talk.html` and `prototype/assets/talk-submission.js` provide
required ASCII title/authors/abstract, schedule, a shared Password, and an optional
PDF upload. No separate submitter Name is needed. The Issue author records the
issuing account privately. Participation still asks for Name. No directory or
per-person token is required.
The visible wording is neutral; the Password is an issued PAT, not a GitHub login password.
An active meeting's **Add talk** link fixes the meeting and displays its name;
there is no second selection step. The generic form without a `meeting` query
parameter retains a selector. Public `data-meeting-id`/`data-meeting-status` card
attributes check availability; an unavailable meeting-specific link cannot fall
back to a different event. Archived, hidden, and historical meetings cannot be
selected. Actions independently checks the authoritative private state.

The delivered HTML includes its script, authorized by an exact CSP SHA-256 hash.
It needs no separate script request, so it also works with a running preview
server whose older allowlist cannot serve the new JS path. The version bar
identifies the fetched website content, not the running server executable.
Editable entries are `prototype/assets/talk-submission.js` and
`prototype/assets/participation.js`; `prototype/assets/member-api.js` holds shared
API, identity, calendar, and meeting-loading helpers. These are bundled into
closure-scoped scripts in each HTML page, without external script requests.
The administrator source is `prototype/assets/create-meeting.js`.
After editing any source, regenerate and check **all three** served forms:

```sh
python3 scripts/build_talk_form.py
python3 scripts/build_talk_form.py --check
```

Unit tests reject stale generated HTML or a mismatched CSP hash. Meeting loading
is bounded at 15 seconds, including the response body, and failures show
**Retry loading** while fields remain disabled. Typed values are retained after
a failed pre-submission availability check; no Issue is posted in that case.

The issuing account is an ordinary organization member with effective **Read**
access to `ifipwg13/meetings`. Issues read/write plus Metadata Read supports text
submissions and participation. PDF uploads additionally require Write on a separate
private `ifipwg13/meeting-slides-uploads` repository, selected on the token with
Contents read/write. The account keeps Read on meetings and no write access to the
website. GitHub permissions apply repository-wide, not just to one's own uploads.
Actions, Workflows, Pull requests, and administration permissions are unnecessary
for the browser token.
Outside collaborators cannot use this fine-grained organization-token route.
The approved Read account's membership/role were verified before implementation.

Participants share a Read-account PAT (the website's Password). Participation
asks for Name and records name/fingerprint metadata privately; Add talk needs no
name and does not record that participant object. No name directory is consulted.
Names are self-declared labels, not human authentication; a password holder can
enter another name and act on that shared account's records. Names accept plain
text and accents; the public talk title/authors/abstract retain strict ASCII.
The public Authors field remains required and independent of participation names.

The Manage Participants form, navigation and reconciliation workflow are retired.
Existing directory Issues and records remain private and unchanged. Former
active/disabled directory flags no longer control form access: revoke unwanted
PATs in GitHub. Existing attendance/talk formats stay readable without lookup.
See the private [shared-password guide](https://github.com/ifipwg13/meetings/blob/feature/talk-pdf-uploads/SHARED_CREDENTIALS.md)
for issuance, compatibility, replacement and the Firefox acceptance procedure.

The browser verifies access, then posts an unlabeled structured Issue
directly to the fixed GitHub API origin. Trusted private Actions validates it,
adds computed labels with its built-in token, and invokes publication in the
same run. Private bot status distinguishes submission from verified publication.
A lost POST response triggers GET-only recovery by a per-submission UUID.
The app uses no local/session storage or token URLs; password-manager
saving/autofill is best effort via current-password hints (Participation also has
username). Token values never enter a repository or an Issue. Participation stores
only their fingerprints in private metadata; Add talk binds recovery in memory.
Only designated talk title, authors, abstract and scheduling fields are rendered
publicly as escaped text, with a PDF link when applicable. Directory names/IDs
and fingerprints never enter public output. **Create meeting** remains at the top
of the list and opens our website administrator form; trusted Actions enforces its access. The token is not the administrator's
`MEETING_AUTOMATION_TOKEN` publishing secret. Native form submission is blocked
by CSP, and fields remain disabled if JavaScript cannot load.

Talk edits/withdrawals still use GitHub's existing interface; Participation
changes are submitted directly from our website. New web-format Issues are revalidated on edits; invalid ones remain
private and are omitted publicly until corrected. Existing legacy-format Issues
and imported meetings retain their current behavior. `talk-hidden`, meeting
Hide, archive cutoffs, and historical closed-talk display continue unchanged.

To run credential-free browser/Python integration tests with a sibling private
checkout, use `python3 tests/browser_talk_submission.py`. The fake token is sent
only to intercepted GitHub API requests; no live Issues are created. Actual
Read-account PAT acceptance, organization restrictions, and Firefox vault behavior
remain manual checks after separately approved activation.


The loading repair adds regressions using the actual preview HTTP handler and
synchronized-view URL prefix, including an older script allowlist that returns
404 for `talk-submission.js`. The browser follows a meeting's Add talk link,
checks its fixed context, submits a fictitious talk through the private REST
model, and returns to the correct meeting. Additional checks cover a stalled
meeting request, HTTP failure/retry without lost input or duplicate POST, generic
selection, inactive/invalid context, and the compiled script's CSP hash.


## Participation and talk scheduling

Participation fixes the meeting, checks the credentials and current canonical
registration Issue, and adds/removes a **Yes — Real Name** comment for the entered
participant. Repeated choices preserve the desired state. Unregister deletes only
that participant's recognized comment during normal form use. Existing reactions,
unrelated comments, other authors and labels remain unchanged. Duplicates require
organizer review. Earlier reaction registrations are flagged for reconciliation;
no automatic mapping or deletion is performed. A replacement password on the
same issuing account can manage existing attendance by name, independent of the
historical fingerprint. Existing version-2 name/member-ID comments remain readable;
version-1 comments match their original usernames. Unknown records are preserved.

A successful DELETE returns HTTP 204 without JSON. Lost responses require
read-only status checks using the original name/password instead of
repeating writes. Changing either field invalidates checked credentials and
clears stale confirmation text. The Clear token button is removed; page exit
clears entered credentials. Browser password-manager saving remains best effort.
Attendance and account responses never enter public output or persistent storage.

Public cards provide `data-registration-issue` from the canonical manifest; never
construct the registration Issue number from the meeting counter. The form also
checks its private registration/meeting labels and live open/locked/hidden/archive
state before a change. GitHub enforces access and locked-conversation rules.

Talk Time starts at 09:00. The date is automatic for a single-day meeting; a
multi-day form asks for Talk date, initially the first day, using the existing
day-first formats. Private Issues store optional `date`/`time` fields, with strict
validation and no timezone conversion. Both public listings group multi-day talks
by date and sort by date/time/actual creation time. Existing Issue-backed talks
without fields default to the first day at 09:00, without bulk Issue rewrites.
Explicit fields override defaults; imported historical records are unchanged.
Existing slots invalidated by a meeting-date correction remain visible as
Unscheduled talks and receive private correction guidance.

With both checkouts and Playwright/Chromium installed, run
`python3 tests/browser_participation.py` as well as the existing form and meeting
browser tests. They use fictitious credentials and the actual preview handler.
The private guide above supplies the real two-account Firefox checklist; local
API models do not establish GitHub's actual authorization or browser vault behavior.


## Administrator meeting creation

**Create meeting** stays at the top of the list and opens
`prototype/create-meeting.html`. It asks for the existing meeting details and a
separate masked Admin-account password. The entry script is
`prototype/assets/create-meeting.js`, compiled with the shared helper and exact
CSP hash. There is no member Name field on this administrator form.

Check credentials verifies the actual repository Admin role. Submission rechecks
that role immediately before any Issue POST and rejects silently changed
credentials. A non-admin password creates no Issue through this form, even if a
previously checked administrator has been downgraded. Missing/denied permission
checks fail closed. Trusted private Actions independently checks the trigger and
original request author before preparing meeting resources. A name, token
fingerprint or browser visibility flag never grants administration.

GitHub's Issues write permission still allows raw API callers to create ordinary
Issues, including malformed meeting requests. They must never become prepared
meetings through the private workflow. Preventing all such direct Issue creation
would also prevent talk submission under this static/direct-API design.

The form creates one registration Issue with its submission UUID, assigned prefix
and existing synchronization. It shows Submitted until trusted bot status confirms
verified public revision content; only then does it offer Open meeting. Lost
responses use bounded GET-only UUID recovery, without duplicate POSTs. Preserve
the marker when editing saved Issues. Hidden/archived meeting behavior is retained.

The private [README](https://github.com/ifipwg13/meetings/blob/feature/talk-pdf-uploads/README.md#create-limited-member-and-administrator-tokens)
gives exact issuance steps: one shared Read-account password for member forms,
and a separate Admin-account password for Create meeting. Both select only
meetings with Issues read/write plus automatic Metadata read. The publishing
secret remains separate because it writes repository files. No new secret,
backend, database or dependency is needed.

Run `python3 tests/browser_create_meeting.py` with the sibling private checkout,
alongside talk, participation and meeting/browser tests. These use fictitious
credentials and the real preview/controller with a modeled API. Actual minimal-
scope PAT acceptance, live Actions timing and Firefox vault behavior remain manual
after integration approval. Both implementation PRs stay draft/unmerged until
approved. Publication PR #1 and backup/export/restore remain separate and deferred.


## PDF uploads

One optional PDF of at most **10,000,000 bytes** can accompany a talk. The browser
uses the shared member password to stage it in a separate private GitHub repository,
then creates the talk Issue with a commit-pinned file reference. The trusted private
publisher verifies the size, checksums and PDF structure before copying it into
`prototype/slides/<meeting ID>/` and linking the title. Without a PDF the title
remains non-clickable. Abstract disclosures and schedules are preserved.

HTML and PDFs are committed together. The preview permits only generated PDF
paths and serves them as `application/pdf` with `nosniff`; use this feature's
preview-server version when reviewing PDF links. Hide/restore follows existing
meeting/talk visibility. Public history and caches retain previously published
material; the complete PDF and its embedded metadata become public.

The private [PDF setup and testing guide](https://github.com/ifipwg13/meetings/blob/feature/talk-pdf-uploads/SLIDES_UPLOADS.md)
explains repository creation, roles, token scopes, the publisher secret and
recovery. Provisioning is required before real uploads can work. No credentials
or PDF bytes are stored in public JavaScript, browser local/session storage,
URLs or logs; only selected PDFs are intentionally copied to public files.

The paired private publisher adds the pinned `pypdf` dependency for structural
checks in a credential-free subprocess with memory/time limits. The site itself
has no new runtime dependencies. For local integration tests, install it using:

```sh
python3 -m pip install --require-hashes -r ../meetings/.github/scripts/pdf-requirements.txt
```
