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
   beside **Terminal**, find port **8001**, and click its **Open in Browser**
   globe icon. If the port is missing, choose **Add Port** and enter `8001`.
6. The prototype opens in a new Firefox tab with a **Live preview** bar at the
   top. That bar confirms this is the server receiving GitHub updates. Choose **View meeting** to inspect
   the fictitious event. Allow the popup if Firefox blocks the new tab.

Keep port visibility **Private**. This preview is separate from GitHub Pages:
opening it does not merge the pull request or publish the website. The Python
server serves only HTML and CSS from `prototype/` on the latest public PR branch,
never the repository root or private records. It fetches the branch when a page
is requested, so refreshing Firefox receives generated meeting updates without
another terminal command. Your local files and branches are not changed.
The server includes the stylesheet in each preview page, using the same Git
version for both. Styling does not depend on a second browser request. The
**Live preview** bar shows the retrieved version and time (Europe/Berlin).
Port **8001** distinguishes this preview from an older server on port 8000.

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

## Update an existing preview

If an existing preview shows old meetings or loses its styling, update and
restart the preview server:

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

   The terminal must report **LIVE PREVIEW on port 8001**. If it reports an error,
   copy that error for diagnosis; the block stops rather than running older code.
3. Close the old preview tab. In **Ports**, open **8001** using its globe icon.
   Add port `8001` if it is absent, keeping its visibility **Private**. Confirm
   the new tab shows the **Live preview** bar, styled buttons, and the current
   meetings. Subsequent updates need only a browser refresh.

Old `/prototype/` URLs redirect to the current preview's root, and meeting links
without a final slash redirect to their correct directory URL. HTML, styling,
redirects, and errors all instruct browsers not to cache preview responses. A
GitHub or stylesheet failure shows an error rather than an old or unstyled page.

After meeting updates, refresh Firefox. No further `git pull` is needed to display
new meetings or activate their talk buttons. The server must stay running and
the Codespace must be able to reach GitHub. If an update fails, the preview shows
an error rather than silently displaying an old meeting list.

## Prototype files

`prototype/index.html` lists meetings. Each event has its own directory under
`prototype/meetings/`; `prototype/assets/style.css` supplies the shared styling.
Links within the site are relative, so they work in the Codespaces preview and
under `/prototype/` on a future Pages deployment.

Cards are ordered by start date, latest first. Dates are displayed as DD-MM-YYYY,
including multi-day ranges. The `generated-meetings` markers reserve the list
area for generated updates; the rest of the index is preserved.

The private README explains how to create, archive, hide, and restore meetings.
Only meeting metadata and generic private links belong in public files. Never
copy attendance, proposal contents, comments, or identities into public files,
commits, or PR descriptions.

GitHub Pages currently publishes `main` from the repository root. Keep this
pull request unmerged throughout initial testing, including second-meeting tests.
Merging or publishing requires separate explicit approval; no deployment workflow
or Pages configuration is introduced here.

The preview server uses the Git authentication already provided by Codespaces.
It needs no extra token or secret and reads no private Issues. The static site
remains plain HTML/CSS. To test preview synchronization without credentials or
network access, run `python3 -m unittest discover -s tests -v`.
