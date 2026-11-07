# IFIP WG1.3 website

A static group homepage, public member list, and meeting website.
Registration and discussion use the private GitHub repository. Group information,
the roster, and historical meetings use public-only content stored here.

The prototype uses plain HTML/CSS and a small local script to sort the list,
with no runtime dependencies or external services.
Participation and discussion belong in the private `ifipwg13/meetings` repository.
The website displays each talk's title, entered authors, and expandable abstract.

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
meeting-list script, and exact IFIP logo path under `prototype/` on the selected public branch. Other
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

`prototype/index.html` lists meetings. Each event has its own directory under
`prototype/meetings/`; `prototype/assets/style.css` supplies the shared styling.
`prototype/assets/meetings-list.js` puts all cards in descending start-date order
in the same list, including historical meetings interleaved with Issue-backed
meetings. It moves existing elements without fetching data or duplicating cards.
Links within the site are relative, so they work in the Codespaces preview and
under `/prototype/` on a future Pages deployment.

Cards are ordered by start date, latest first. **When:** shows DD-MM-YYYY dates
or date ranges, **Where:** shows the location, and descriptions remain unlabeled
paragraphs. Hours and timezones are not displayed. Matching talk Issues appear
on the cards and meeting pages as **title by authors**, with the title linking to
its private Issue. Automatic meeting prefixes and Issue-number labels are omitted.
Each Issue-backed meeting page shows an initially collapsed **Abstract** disclosure
beside each talk that has supplied abstract text. Its collapsed row reads
**Title by Presenter ▸ Abstract** when space permits. Long titles and small
screens wrap naturally. Opening Abstract places the full text below that row.
Titles and presenter names are underlined; only Issue-backed titles are links.
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

Meeting pages place **View participants and register | Add talk** in a single
responsive group. These links remain visible on the static site; GitHub enforces
private-repository access. Active members need Read access or higher. Archived
pages disable Add talk and retain a registration-record link. Hidden meetings
have no public page. Meeting administration uses `archived` and `hidden` on the
private registration Issue, under the existing Admin/Read role model. The private
README gives the Labels-menu steps. There are no public administrative buttons.
There is no talk-level Hide shortcut. An Admin opens the talk's private Issue
from its title or the repository Issues list and applies/removes `talk-hidden`.
This label still controls publication on both meeting cards and detail pages.
The meeting-level `hidden` label remains separate. Hidden talks have no public
identifying placeholder.

## Preview this feature draft

In a Codespace opened from this feature PR, stop an existing preview with Ctrl+C,
then run:

```sh
python3 scripts/preview_server.py --branch feature/clean-talk-status --port 8003
```

Open port **8003** using **Ports → Open in Browser**. Firefox displays the review
branch and refreshes it from GitHub, with HTML, styling, and the list sorter from
the same commit.
This optional branch selection leaves the existing prototype preview default
unchanged. Issue-backed pages in this feature draft are a review snapshot.
The bar must say **Review snapshot**, name this feature branch, and offer
**Switch to synchronized preview**. Use the review view for unmerged presentation
changes and the synchronized view for label tests. Before integration, the
synchronized view shows currently merged content; the removal of generated talk
status suffixes remains in the review view. The separate private PR updates
the generator and meeting form, preserves talk states during archiving, and
repairs reactivation from current labels. It also queues label updates so they
are not replaced by later pending runs. Permissions remain unchanged.
No PR is merged or Pages website published by starting a preview.

In an existing Codespace with older local scripts, press **Ctrl+C** to stop its
server, then paste this entire block. It runs the review branch's server without
switching branches or overwriting local work:

```sh
cd "$(git rev-parse --show-toplevel)" &&
git fetch origin refs/heads/feature/clean-talk-status:refs/remotes/origin/feature/clean-talk-status &&
group_preview_script="$(mktemp /tmp/group-preview.XXXXXX.py)" &&
git show origin/feature/clean-talk-status:scripts/preview_server.py > "$group_preview_script" &&
python3 "$group_preview_script" --repository "$PWD" --branch feature/clean-talk-status --port 8003
```

Open port **8003** from **Ports**, keeping it **Private**. The first page must be
the group homepage with Home / Members / Meetings navigation and a **Review
snapshot** status bar. This block does not change local HTML, the checked-out
branch, or the published site. For current Issue states, click **Switch to
synchronized preview**; the status must then say **Synchronized preview** and
name `prototype/meeting-management`.

After separate approval, integrate the public feature before the private
generator, then run **Prepare
meeting** once from the private repository's Actions page to refresh all meeting
pages consistently. These operations still require separate merge approval.

The public feature PR targets the existing prototype branch. Public website PR
#1 stays draft and unmerged. After both feature PRs are separately approved and
integrated (public design to the prototype branch, private generator to `main`), use
the normal preview command without `--branch` for real event synchronization.
The isolated feature branch remains a review snapshot until it is updated again;
merging it does not make it the synchronization target.

GitHub Pages currently publishes `main` from the repository root. Keep this
pull request unmerged throughout initial testing, including second-meeting tests.
Merging or publishing requires separate explicit approval; no deployment workflow
or Pages configuration is introduced here.

The preview server uses the Git authentication already provided by Codespaces.
It needs no extra token or secret and reads no private Issues. The static site
remains HTML/CSS with the local list sorter. To test rendering and preview
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
