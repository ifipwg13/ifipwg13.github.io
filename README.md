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
   python3 -m http.server 8000 --bind 0.0.0.0 --directory prototype
   ```

5. When **Open in Browser** appears, click it. Otherwise, open the **Ports** tab
   beside **Terminal**, find port **8000**, and click its **Open in Browser**
   globe icon. If the port is missing, choose **Add Port** and enter `8000`.
6. The prototype opens in a new Firefox tab. Choose **View meeting** to inspect
   the fictitious event. Allow the popup if Firefox blocks the new tab.

Keep port visibility **Private**. This preview is separate from GitHub Pages:
opening it does not merge the pull request or publish the website. The Python
server serves only `prototype/`, never the repository root or private records.

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

If you already have a running Codespaces preview, open **Terminal → New Terminal**
and run `git pull --ff-only origin prototype/meeting-management`, then refresh the
preview tab. Leave the preview server running in its original terminal. A
Codespace does not automatically receive new commits pushed to the PR branch.

## Files and future meetings

`prototype/index.html` lists meetings. Each event has its own directory under
`prototype/meetings/`; `prototype/assets/style.css` supplies the shared styling.
Links within the site are relative, so they work in the Codespaces preview and
under `/prototype/` on a future Pages deployment.

To add another fictitious meeting, copy `prototype/meetings/demo-001/index.html`
into a new meeting directory, update its public details and three GitHub links,
then add its entry to `prototype/index.html`. Use the private administrator guide
for the matching form, label, and registration Issue. Never copy attendance or
proposal contents into public files, commits, pull request descriptions, or logs.

GitHub Pages currently publishes `main` from the repository root. Keep this
pull request unmerged throughout initial testing, including second-meeting tests.
Merging or publishing requires separate explicit approval; no deployment workflow
or Pages configuration is introduced here.
