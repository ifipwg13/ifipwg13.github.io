/* Static talk form. Tokens go only to the fixed GitHub API origin, never storage. */
(() => {
  'use strict';
  const API = 'https://api.github.com';
  const REPO = '/repos/ifipwg13/meetings';
  const MARKER = '<!-- wg13-web-talk -->';
  const STATUS_MARKER = '<!-- wg13-web-talk-status ';
  const requestedMeeting = new URLSearchParams(location.search).get('meeting');
  const $ = id => document.getElementById(id);
  const form = $('talk-form');
  const tokenField = $('github-token');
  let token = '';
  let login = '';
  let checkedToken = '';
  let busy = false;
  let pending = null;
  let pollTimer = null;
  let pollCount = 0;
  let meetings = new Map();

  function error(message = '') {
    $('form-error').textContent = message;
    $('form-error').hidden = !message;
  }

  function buttons() {
    $('submit-talk').disabled = busy || !!pending || !checkedToken || !meetings.size;
    $('check-token').disabled = busy;
    $('check-status').disabled = busy;
  }

  function resetIdentity() {
    token = '';
    checkedToken = '';
    login = '';
    $('identity').textContent = '';
    buttons();
  }

  function readToken() {
    const value = tokenField.value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) {
      throw new Error('Enter a personal access token on one line, without spaces.');
    }
    return value;
  }

  async function api(path, method = 'GET', body = undefined, credential = token) {
    // Do not follow API redirects: Authorization must never reach another host.
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(API + path, {
        method, credentials: 'omit', cache: 'no-store', redirect: 'error',
        referrerPolicy: 'no-referrer', signal: controller.signal,
        headers: {Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + credential,
          'X-GitHub-Api-Version': '2022-11-28', ...(body ? {'Content-Type': 'application/json'} : {})},
        ...(body ? {body: JSON.stringify(body)} : {}),
      });
      if (!response.ok) {
        const messages = {
          401: 'GitHub rejected the token. Check whether it has expired or been revoked.',
          403: 'GitHub denied access. Check token permissions, organization approval or SSO, and repository access.',
          404: 'The token cannot access the private meeting repository. Check the account, repository selection, and organization policy.',
          410: 'This private record is no longer available.',
          422: 'GitHub could not accept the submission. Check the fields and token permissions before starting a new submission.',
          429: 'GitHub is limiting requests. Wait before checking again.',
        };
        const failure = new Error(messages[response.status] || 'GitHub is temporarily unavailable. Check submission status before trying again.');
        failure.httpStatus = response.status;
        throw failure;
      }
      return await response.json();
    } finally {
      clearTimeout(timer);
    }
  }

  function ascii(value, label, limit, multiline = false) {
    if (!value.trim()) throw new Error(label + ' is required.');
    const pattern = multiline ? /^[\x09\x0a\x20-\x7e]+$/ : /^[\x20-\x7e]+$/;
    if (!pattern.test(value)) throw new Error(label + ' must contain ASCII text' +
      (multiline ? ' (line breaks and tabs are allowed).' : ' on one line.'));
    if (value.trim().length > limit) throw new Error(label + ' exceeds its character limit.');
    return value.trim();
  }

  function details() {
    const meeting = $('meeting').value;
    if (!meetings.has(meeting)) throw new Error('Select a meeting that is open for talk submissions.');
    const title = ascii($('talk-title').value, 'Title', 200);
    if (/^\[meeting(?:[ -])\d+\]/i.test(title)) throw new Error('Enter the talk title without a meeting prefix.');
    return {meeting, title, authors: ascii($('authors').value, 'Authors', 500),
      abstract: ascii($('abstract').value.replace(/\r\n?/g, '\n'), 'Abstract', 20000, true)};
  }

  async function loadMeetings() {
    const selected = requestedMeeting || $('meeting').value;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    meetings = new Map();
    $('talk-fields').disabled = true;
    $('credential-fields').disabled = true;
    $('retry-meetings').hidden = true;
    $('form-status').textContent = 'Loading meeting information…';
    buttons();
    try {
      const response = await fetch('index.html', {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Meeting information unavailable');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      for (const card of doc.querySelectorAll('article.meeting-card[data-meeting-status="active"]')) {
        const id = card.dataset.meetingId;
        const title = card.querySelector('h3')?.textContent.trim();
        if (/^(?:demo-001|meeting-[1-9][0-9]*)$/.test(id) && title) meetings.set(id, title);
      }
      $('meeting').replaceChildren(new Option('Choose a meeting', ''));
      for (const [id, title] of meetings) $('meeting').add(new Option(title, id));
      if (meetings.has(selected)) $('meeting').value = selected;
      const unavailable = requestedMeeting && !meetings.has(requestedMeeting);
      const ready = meetings.size > 0 && !unavailable;
      $('talk-fields').disabled = !ready;
      $('credential-fields').disabled = !ready;
      $('form-status').textContent = unavailable
        ? 'This meeting is unavailable or closed for talk submissions. Return to all meetings.'
        : ready ? '' : 'No meetings are currently open for talk submissions.';
      if (unavailable) {
        // Never silently switch a meeting-specific submission to another event.
        meetings.clear();
        $('meeting-name').textContent = 'Unavailable';
      } else if (requestedMeeting) {
        $('meeting-name').textContent = meetings.get(requestedMeeting);
      }
      $('retry-meetings').hidden = ready;
    } catch {
      meetings.clear();
      if (requestedMeeting) $('meeting-name').textContent = 'Unavailable';
      $('form-status').textContent = 'Meeting information could not be loaded. Click Retry loading to try again.';
      $('retry-meetings').hidden = false;
      throw new Error('Meeting information could not be loaded. Use Retry loading before submitting.');
    } finally {
      clearTimeout(timer);
      buttons();
    }
  }

  async function checkToken() {
    error();
    resetIdentity();
    const candidate = readToken();
    busy = true;
    buttons();
    try {
      const user = await api('/user', 'GET', undefined, candidate);
      if (!user || typeof user.login !== 'string' || !/^[A-Za-z0-9-]+$/.test(user.login)) {
        throw new Error('GitHub did not identify the token owner.');
      }
      const repo = await api(REPO, 'GET', undefined, candidate);
      // Some API credentials omit the optional permissions object. A matching
      // private-repository read is the preliminary check; Actions independently
      // verifies the real author's membership before admission.
      if (repo.full_name !== 'ifipwg13/meetings' || repo.permissions?.pull === false) {
        throw new Error('The token owner needs at least Read access to the private meeting repository.');
      }
      if (tokenField.value.trim() !== candidate) throw new Error('The token changed. Check it again.');
      token = candidate;
      checkedToken = candidate;
      login = user.login;
      $('identity').textContent = 'Submitting as ' + login + '. Check that this is your account.';
    } finally {
      busy = false;
      buttons();
    }
  }

  function matchedSubmission(issue) {
    if (issue.pull_request || issue.user?.login?.toLowerCase() !== login.toLowerCase()) return false;
    try {
      const body = issue.body || '';
      if (!body.startsWith(MARKER + '\n```json\n')) return false;
      const data = JSON.parse(body.slice((MARKER + '\n```json\n').length).replace(/\n```\s*$/, ''));
      return data.submission_id === pending.id;
    } catch {
      return false;
    }
  }

  async function recover() {
    // GET-only recovery after an ambiguous POST; never automatically POST again.
    for (let page = 1; page <= 5; page++) {
      const issues = await api(REPO + '/issues?state=all&creator=' + encodeURIComponent(login) +
        '&sort=created&direction=desc&per_page=100&page=' + page);
      if (!Array.isArray(issues)) throw new Error('GitHub did not return a submission list.');
      const matches = issues.filter(matchedSubmission);
      if (matches.length > 1) throw new Error('More than one matching private record exists. Ask the organizer to inspect it.');
      if (matches.length === 1) {
        pending.number = matches[0].number;
        return;
      }
      if (issues.length < 100) break;
    }
    throw new Error('Submission could not be confirmed. Use Check submission status again; do not submit another copy.');
  }

  async function status() {
    if (!pending) return;
    if (!checkedToken || checkedToken !== readToken()) throw new Error('Check the original account\'s token to read this submission status.');
    if (pending.login.toLowerCase() !== login.toLowerCase()) throw new Error('Use the same account that submitted this talk.');
    if (!pending.number) await recover();
    if (!Number.isSafeInteger(pending.number) || pending.number < 1) throw new Error('GitHub did not return a valid submission number.');
    const comments = [];
    // Only private bot comments with our identifier count as publication status.
    for (let page = 1; page <= 10; page++) {
      const batch = await api(REPO + '/issues/' + pending.number + '/comments?per_page=100&page=' + page);
      if (!Array.isArray(batch)) throw new Error('GitHub did not return submission status.');
      comments.push(...batch);
      if (batch.length < 100) break;
      if (page === 10) throw new Error('The private record has too many comments. Ask the organizer to check its status.');
    }
    const states = [];
    for (const comment of comments) {
      if (comment.user?.login !== 'github-actions[bot]' || comment.user?.type !== 'Bot') continue;
      const body = comment.body || '';
      if (!body.startsWith(STATUS_MARKER)) continue;
      try {
        const end = body.indexOf(' -->');
        const value = JSON.parse(body.slice(STATUS_MARKER.length, end));
        if (value.schema_version === 1 && value.submission_id === pending.id) states.push(value);
      } catch { /* Ignore unrelated or malformed comments; never render their text. */ }
    }
    const latest = states.at(-1);
    if (latest?.state === 'published' && /^[a-f0-9]{40}$/.test(latest.revision) && meetings.has(latest.meeting_id)) {
      $('submission-status').textContent = 'Your talk is published in the synchronized website preview. Refresh the meeting page to see it.';
      $('meeting-link').href = 'meetings/' + latest.meeting_id + '/';
      $('meeting-link').hidden = false;
      return;
    }
    if (latest?.state === 'hidden') {
      $('submission-status').textContent = 'Your talk is recorded privately and is hidden from the public page.';
      return;
    }
    if (latest?.state === 'needs-correction') {
      $('submission-status').textContent = 'Your talk needs correction. Open your private Issue in GitHub for the validation message, or ask the organizer for help.';
      return;
    }
    if (latest?.state === 'needs-attention') {
      $('submission-status').textContent = 'Your talk is recorded, but processing needs attention. Ask the organizer to check GitHub Actions; do not submit another copy.';
      return;
    }
    $('submission-status').textContent = 'Submitted. GitHub Actions is checking your talk; it is not yet confirmed as published. You can keep this page open or check again later.';
    if (++pollCount < 12) pollTimer = setTimeout(checkStatus, 5000);
  }

  async function checkStatus() {
    if (busy || !pending) return;
    clearTimeout(pollTimer);
    busy = true;
    buttons();
    error();
    try { await status(); }
    catch { error('Submission status could not be confirmed. Check your token and use Check submission status again. No second submission was sent.'); }
    finally { busy = false; buttons(); }
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || pending) return;
    busy = true;
    buttons();
    error();
    let data;
    try {
      data = details();
      if (!checkedToken || readToken() !== checkedToken) throw new Error('Use Check token before submitting.');
      // Re-read public eligibility immediately before submission; Actions checks
      // authoritative private state independently (including race conditions).
      await loadMeetings();
      $('meeting').value = data.meeting;
      if (!meetings.has(data.meeting)) throw new Error('This meeting is no longer open for talk submissions.');
      if (!crypto.randomUUID) throw new Error('Use a browser with secure HTTPS access to submit a talk.');
    } catch (failure) { error(failure.message); busy = false; buttons(); return; }
    pending = {id: crypto.randomUUID(), login, number: null};
    buttons();
    $('talk-fields').disabled = true;
    const prefix = data.meeting === 'demo-001' ? '[meeting 1]' : '[meeting ' + data.meeting.slice(8) + ']';
    const payload = {schema_version: 1, meeting_id: data.meeting, authors: data.authors,
      abstract: data.abstract, submission_id: pending.id};
    const issue = {title: prefix + ' ' + data.title, body: MARKER + '\n```json\n' + JSON.stringify(payload, null, 2) + '\n```'};
    $('submission-status').textContent = 'Sending your talk to GitHub…';
    try {
      const created = await api(REPO + '/issues', 'POST', issue);
      if (!Number.isSafeInteger(created.number) || created.number < 1) throw new Error('Unconfirmed submission');
      pending.number = created.number;
    } catch (failure) {
      // A definite API rejection is safe to correct and submit again; transport
      // failures and 5xx responses may have created an Issue and require recovery.
      if ([401, 403, 404, 410, 422, 429].includes(failure.httpStatus)) {
        pending = null;
        $('talk-fields').disabled = false;
        $('submission-status').textContent = 'GitHub did not accept this submission.';
        error(failure.message);
      } else {
        $('submission-status').textContent = 'The connection ended before submission was confirmed. Checking for your private record without sending another copy…';
      }
    } finally {
      busy = false;
      buttons();
    }
    $('check-status').hidden = !pending;
    if (pending) await checkStatus();
  });

  $('check-token').addEventListener('click', () => checkToken().catch(failure => error(failure.httpStatus ? failure.message : 'The token could not be checked. Verify it and try again.')));
  $('check-status').addEventListener('click', checkStatus);
  tokenField.addEventListener('input', resetIdentity);
  $('clear-token').addEventListener('click', () => {
    clearTimeout(pollTimer);
    tokenField.value = '';
    resetIdentity();
    $('identity').textContent = 'Token cleared from this page. Saved password-manager entries are managed by your browser.';
  });
  // No token, credentials, or private responses are persisted by this app.
  window.addEventListener('pagehide', () => {
    clearTimeout(pollTimer);
    tokenField.value = '';
    resetIdentity();
  });
  // A meeting-specific Add talk link fixes the event; the generic form still
  // offers selection when opened without a meeting query parameter.
  $('meeting-choice').hidden = !!requestedMeeting;
  $('meeting-context').hidden = !requestedMeeting;
  $('meeting').required = !requestedMeeting;
  $('meeting').disabled = !!requestedMeeting;
  if (requestedMeeting) $('meeting-name').textContent = 'Loading…';
  $('retry-meetings').addEventListener('click', () => {
    error();
    loadMeetings().catch(() => {});
  });
  loadMeetings().catch(() => {});
})();
