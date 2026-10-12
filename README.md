# Meeting Management Prototype

A small experiment in managing meeting registration and talk proposals with
GitHub. All event details are fictitious. This is not an official working-group
website and contains no migrated content.

The prototype uses plain HTML and CSS, with no dependencies or build step.
Private participation and proposal records belong exclusively in the private
`ifipwg13/meetings` repository.

## Preview in Firefox without publishing

1. Sign in to GitHub in Firefox and open this repository's prototype pull request.
2. On the pull request, click **Code**, choose **Codespaces**, and select the
   option to create a codespace for the pull request branch. If that option is
   unavailable, open the repository, select the `prototype/meeting-management`
   branch, then choose **Code → Codespaces → Create codespace**.
3. Wait for the browser editor to open. If there is no terminal panel, use the
   top-left menu **☰ → Terminal → New Terminal**.
4. Paste this command into the terminal and press Enter:

   ```sh
   python3 scripts/preview_server.py
   ```

5. When **Open in Browser** appears, click it. Otherwise, open the **Ports** tab
   beside **Terminal**, find port **8000**, and click its **Open in Browser**
   globe icon. If the port is missing, choose **Add Port** and enter `8000`.
6. The prototype opens in a new Firefox tab. Choose **View meeting** to inspect
   the fictitious event. Allow the popup if Firefox blocks the new tab.

Keep port visibility **Private**. This preview is separate from GitHub Pages:
opening it does not merge the pull request or publish the website. The Python
server serves only HTML and CSS from `prototype/` on the latest public PR branch,
never the repository root or private records. It fetches the branch when a page
is requested, so refreshing Firefox receives generated meeting updates without
another terminal command. Your local files and branches are not changed.

Use a personally billed, two-core codespace within your available free allowance.
The creation dialog identifies who pays. A GitHub Free personal account includes
120 core-hours and 15 GB-month of storage per month; organization accounts do not
include a free Codespaces allowance. Stop the codespace at
<https://github.com/codespaces> when finished; delete it after testing to release
storage. No local software installation is needed.

## Current activation state

The private configuration PR was merged after approval. The `registration`,
`talk`, and `meeting:demo-001` labels now exist, and the demo registration Issue is
open. The public PR remains unmerged; public `main` and Pages settings are unchanged.

- The participants button opens the demo meeting's exact registration Issue:
  <https://github.com/ifipwg13/meetings/issues/2>.
- The proposal list includes both open and closed Issues for this meeting.
- The submission form is on the private repository's default branch and its
  labels exist. Actual Read-role label assignment, field validation, and usability
  remain live test cases; they have not been recorded as passed.
- An account without private repository access cannot use these GitHub links.

The public preview can now link to the activated private demo. See the private
repository's `ADMINISTRATION.md` and `TESTING.md` for the two-account test procedure.
All test proposals should remain fictitious and private.

If you already have a running preview using `python3 -m http.server`, switch it
once to the server that receives GitHub updates:

1. Click its terminal and press **Ctrl+C** to stop the old server.
2. Run these commands, one at a time:

   ```sh
   cd "$(git rev-parse --show-toplevel)"
   git pull --ff-only origin prototype/meeting-management
   python3 scripts/preview_server.py
   ```

3. Open port **8000** from the **Ports** tab again. The new server opens directly
   at the meeting list; an old URL ending in `/prototype/` must be replaced by
   the port's root address. Subsequently, just refresh Firefox.

For each subsequent meeting, wait for the **Meeting prepared** comment on its
request Issue, then refresh Firefox. No further `git pull` is needed to display
new meetings or activate their talk buttons. The server must stay running and
the Codespace must be able to reach GitHub. If an update fails, the preview shows
an error rather than silently displaying an old meeting list.

## Files and future meetings

`prototype/index.html` lists meetings. Each event has its own directory under
`prototype/meetings/`; `prototype/assets/style.css` supplies the shared styling.
Links within the site are relative, so they work in the Codespaces preview and
under `/prototype/` on a future Pages deployment.

The meeting list now includes **Create meeting** for administrators. It opens
a private GitHub form, like the talk-submission button. The form and automation
are active; its configured Actions credential has successfully prepared the
second meeting and enabled its talk button after an approved private setup merge.

The administrator enters fictitious meeting details once. The generator adds
registration instructions to that same Issue and a meeting label, prepares a
private talk-form PR, and adds the page and list entry to this existing draft PR
branch. Talk submission is enabled
after an approved private setup merge. No HTML editing or Codespaces session is
needed to submit a meeting request. With the preview server above, refreshing
Firefox fetches generated updates. The older plain Python file server continues
to require manual pulls; restart it with the new command once.

The `generated-meetings` markers in the index reserve the generated list area.
Cards are ordered by start date, latest first; equal dates use the larger existing
meeting counter first. The original demo card is in this same region so it follows
the order. Its confirmed metadata is retained privately and its card/page are
synchronized like subsequent meetings, preserving its original private links. Other index
content is preserved. Future generated updates and retries retain this order.
Only confirmed public meeting metadata and generic private links are exported.

The draft preview displays dates as DD-MM-YYYY, including the start and end
of multi-day meetings. The activated private form/workflow simplifies
meeting creation to one name in GitHub's **Title** field and accepts DD-MM-YYYY
input. Registration titles and talk-form prefixes use `[meeting N] `; talk
prefixes remain editable by their authors. Existing IDs, labels, and private
destinations are retained. GitHub's Cancel behavior and the new-tab links are
unchanged; no custom meeting form or redirect is introduced.

Never copy attendance or proposal contents into public files, commits, pull
request descriptions, or logs. Read the private repository's `ADMINISTRATION.md`
and `AUTOMATION.md` for activation and the administrator's form procedure.

## Archive and hide

On a meeting card or page, expand **Manage meeting — organizers**. **Archive
meeting** opens the existing private registration Issue: the administrator
confirms by clicking **Close issue**. **Hide meeting** opens that same Issue:
the administrator selects **hidden** in its **Labels** menu. Wait for Actions
to succeed, then refresh the preview. Clicking a preview button alone does not
change the meeting. No extra operation Issue or browser credential is needed.

Archived meetings remain visible with an **Archived** notice and links to retained
private records. Hidden meetings have neither a current card nor a page; their
private registration and proposals remain available to invited members. There
is no Delete button. Read-role members cannot complete these administrator actions.

Successful setup and visibility changes reconcile all meetings, including pending
private setups, in start-date order. An administrator can repair the complete list
using **Actions → Prepare meeting → Run workflow** in the private repository.
The public preview remains plain HTML/CSS and uses no private API in the browser.

GitHub Pages currently publishes `main` from the repository root. Keep this
pull request unmerged throughout initial testing, including second-meeting tests.
Merging or publishing requires separate explicit approval; no deployment workflow
or Pages configuration is introduced here.

The preview server uses the Git authentication already provided by Codespaces.
It needs no extra token or secret and reads no private Issues. The static site
remains plain HTML/CSS. To test preview synchronization without credentials or
network access, run `python3 -m unittest discover -s tests -v`.
