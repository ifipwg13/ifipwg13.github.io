# IFIP WG 1.3 website

This repository contains the static group website: Home, meetings, talk forms,
and locally hosted presentation slides. It needs no application server or
operated database. The private meeting repository supplies approved public
meeting and talk fields through its existing workflow.

The operating guide for members and administrators is the
[private repository README](https://github.com/ifipwg13/meetings/blob/main/README.md).
Read that guide for credentials, editing Home, meeting creation, registration,
scheduling, visibility, synchronization, publication and recovery. Historical
feature branches are snapshots; use the integrated branch described below.

## Publication

Publication is awaiting final approval. PR #1 brings the integrated
`prototype/meeting-management` website into `main`. GitHub Pages is configured to
serve `main` at <https://ifipwg13.github.io/>. This does not change either private
repository's visibility. Existing `/prototype/` URLs are retained.

The trusted private `.github/site-publication.json` selects the destination:
`preview` uses `prototype/meeting-management`, `live` uses `main`, and `paused`
blocks public writes. Changing the destination does not merge a PR, deploy older
content, or replay failed requests by itself. Follow the private README's cutover
and recovery procedure. Synchronization no longer depends on PR #1 staying open.
A successful form confirmation means the repository content was verified;
GitHub Pages deployment can take additional time.

## Codespaces preview before publication

Open the website repository's existing Codespace. Stop its running preview with
**Ctrl+C**, then paste this whole block into its terminal:

```sh
cd "$(git rev-parse --show-toplevel)" &&
git fetch origin refs/heads/prototype/meeting-management:refs/remotes/origin/prototype/meeting-management &&
meeting_preview_script="$(mktemp /tmp/meeting-preview.XXXXXX.py)" &&
git show origin/prototype/meeting-management:scripts/preview_server.py > "$meeting_preview_script" &&
python3 "$meeting_preview_script" --repository "$PWD" --synchronized-branch prototype/meeting-management --port 8003
```

Open **Ports → 8003 → Open in browser**. Keep port visibility **Private**. Leave
the server running. Refresh the browser after a successful workflow. The bar
should say **Synchronized preview**, with source `prototype/meeting-management`.
The server fetches the branch, including all slide formats; no `git pull` or
manual slide copying is needed. It preserves local uncommitted work.

## Review the unmerged publication preparation

Before the paired changes are integrated, use this block instead:

```sh
cd "$(git rev-parse --show-toplevel)" &&
git fetch origin refs/heads/feature/prepare-publication:refs/remotes/origin/feature/prepare-publication &&
group_preview_script="$(mktemp /tmp/group-preview.XXXXXX.py)" &&
git show origin/feature/prepare-publication:scripts/preview_server.py > "$group_preview_script" &&
python3 "$group_preview_script" --repository "$PWD" --branch feature/prepare-publication --synchronized-branch prototype/meeting-management --port 8003
```

Open port **8003** as above. This is a **Review snapshot** of the candidate;
Issue changes go to the synchronized branch. Its switch link opens that view.
The preview bar and `/__preview/` routing are local preview features only.
The published static site needs neither Codespaces nor this server.

## Preview after publication

After the approved cutover, use the integrated `main` server. Its default source
is `main`; it uses port **8003**:

```sh
cd "$(git rev-parse --show-toplevel)" &&
git fetch origin refs/heads/main:refs/remotes/origin/main &&
live_preview_script="$(mktemp /tmp/live-preview.XXXXXX.py)" &&
git show origin/main:scripts/preview_server.py > "$live_preview_script" &&
python3 "$live_preview_script" --repository "$PWD" --port 8003
```

To review future feature work, use `--branch feature/your-branch`. The synchronized
view will still follow `main`. Preview reads public repository files only and
does not alter a branch or deploy the website. If GitHub cannot be reached it
shows an error rather than an old snapshot.

## Source and checks

* `index.html` is Home; `prototype/data/group-people.json` supplies its six editable
  sections. Use Admin to edit them together. `members/` redirects to Home.
* `prototype/index.html` combines generated and historical meeting cards, ordered
  by start date, newest first. The two generated regions are maintained separately.
* `prototype/meetings/` holds synchronized meeting pages; `prototype/legacy-meetings/`
  and `prototype/data/legacy-meetings.json` hold imported history.
* `prototype/slides/` contains the published slide bytes, including legacy slides.
* `prototype/assets/` contains shared CSS and form source. The build script embeds
  form JavaScript with matching CSP hashes. `.nojekyll` publishes the static files
  directly, preserving text and braces in abstracts.

With the private repository checked out alongside this one, run:

```sh
python3 scripts/build_talk_form.py --check
python3 scripts/build_legacy_meetings.py --check
python3 -m unittest discover -s tests
python3 tests/browser_talk_submission.py
python3 tests/browser_participation.py
python3 tests/browser_create_meeting.py
python3 tests/browser_group_admin.py
python3 tests/browser_schedule.py
python3 tests/browser_meetings.py
python3 tests/browser_release.py
```

Browser checks use isolated fictitious credentials and the actual trusted Python
handlers. Real token scopes, queued Actions, Firefox autofill, and final Pages
deployment still require the private guide's live checks. Never commit raw tokens,
private notes, attendance, participant fingerprints or private comments here.
Removing published information does not erase earlier Git commits or caches.
