/* Static talk form. Tokens go only to the fixed GitHub API origin, never storage. */
(() => {
  'use strict';
  const REPO = '/repos/ifipwg13/meetings';
  const MARKER = '<!-- wg13-web-talk -->';
  const STATUS_MARKER = '<!-- wg13-web-talk-status ';
  const requestedMeeting = new URLSearchParams(location.search).get('meeting');
  const $ = id => document.getElementById(id);
  const form = $('talk-form');
  const tokenField = $('github-token');
  const usernameField = $('github-username');
  let token = '';
  let login = '';
  let checkedToken = '';
  let participant = null;
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
    participant = null;
    $('identity').textContent = '';
    buttons();
  }

  function readToken() {
    const value = tokenField.value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) {
      throw new Error('Enter the password supplied by the organizer, without spaces.');
    }
    return value;
  }

  async function api(path, method = 'GET', body, credential = token) {
    return memberAPI.request(path, method, body, credential);
  }

  function requireCheckedCredentials() {
    if (!checkedToken || readToken() !== checkedToken || !participant || memberAPI.assignedUsername(usernameField.value) !== participant.username) {
      resetIdentity();
      throw new Error('Use Check credentials before submitting.');
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
    const context = meetings.get(meeting);
    const date = context.date === context.endDate ? context.date : memberAPI.calendar($('talk-date').value);
    if (date < context.date || date > context.endDate) throw new Error('Choose a talk date within the meeting dates.');
    return {meeting, title, date, time: memberAPI.clock($('talk-time').value),
      authors: ascii($('authors').value, 'Authors', 500),
      abstract: ascii($('abstract').value.replace(/\r\n?/g, '\n'), 'Abstract', 20000, true)};
  }

  let dateMeeting = null;
  function scheduleFields() {
    const id = $('meeting').value;
    const context = meetings.get(id);
    const multiple = context && context.date !== context.endDate;
    $('talk-date-field').hidden = !multiple;
    $('talk-date').required = !!multiple;
    $('talk-date').disabled = !multiple;
    if (multiple && (dateMeeting !== id || !$('talk-date').value)) {
      $('talk-date').value = memberAPI.displayDate(context.date);
    }
    dateMeeting = id;
  }

  async function loadMeetings() {
    const selected = requestedMeeting || $('meeting').value;
    meetings = new Map();
    $('talk-fields').disabled = true;
    $('credential-fields').disabled = true;
    $('retry-meetings').hidden = true;
    $('form-status').textContent = 'Loading meeting information…';
    buttons();
    try {
      const available = await memberAPI.meetings();
      meetings = new Map([...available].filter(([, context]) => context.status === 'active'));
      $('meeting').replaceChildren(new Option('Choose a meeting', ''));
      for (const [id, context] of meetings) $('meeting').add(new Option(context.name, id));
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
        $('meeting-name').textContent = meetings.get(requestedMeeting).name;
      }
      scheduleFields();
      $('retry-meetings').hidden = ready;
    } catch {
      meetings.clear();
      if (requestedMeeting) $('meeting-name').textContent = 'Unavailable';
      $('form-status').textContent = 'Meeting information could not be loaded. Click Retry loading to try again.';
      $('retry-meetings').hidden = false;
      throw new Error('Meeting information could not be loaded. Use Retry loading before submitting.');
    } finally {
      buttons();
    }
  }

  async function checkToken() {
    error();
    resetIdentity();
    const candidate = readToken();
    const username = memberAPI.assignedUsername(usernameField.value);
    busy = true;
    buttons();
    try {
      const identity = await memberAPI.identify(username, candidate);
      if (tokenField.value.trim() !== candidate || memberAPI.assignedUsername(usernameField.value) !== username) throw new Error('The credentials changed. Check them again.');
      if (pending && (pending.username !== username || pending.fingerprint !== identity.participant.credential_fingerprint || pending.login !== identity.account.login)) {
        throw Object.assign(new Error('Use the original username and password to check this submission.'), {safe: true});
      }
      token = candidate;
      checkedToken = candidate;
      login = identity.account.login;
      participant = identity.participant;
      $('identity').textContent = 'Credentials accepted.';
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
      return data.submission_id === pending.id && data.participant?.username === pending.username &&
        data.participant?.credential_fingerprint === pending.fingerprint;
    } catch {
      return false;
    }
  }

  async function recover() {
    // GET-only recovery after an ambiguous POST; never automatically POST again.
    for (let page = 1; page <= 5; page++) {
      const issues = await api(REPO + '/issues?state=all&creator=' + encodeURIComponent(login) +
        '&sort=created&direction=desc&per_page=100&page=' + page);
      if (!Array.isArray(issues)) throw new Error('The submission list could not be read.');
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
    if (!checkedToken || checkedToken !== readToken() || !participant || pending.username !== participant.username ||
        pending.fingerprint !== participant.credential_fingerprint || pending.login !== login) throw new Error('Check the original username and password to read this submission status.');
    if (!pending.number) await recover();
    if (!Number.isSafeInteger(pending.number) || pending.number < 1) throw new Error('A valid submission reference was not returned.');
    const comments = [];
    // Only private bot comments with our identifier count as publication status.
    for (let page = 1; page <= 10; page++) {
      const batch = await api(REPO + '/issues/' + pending.number + '/comments?per_page=100&page=' + page);
      if (!Array.isArray(batch)) throw new Error('Submission status could not be read.');
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
      $('submission-status').textContent = 'Your talk is published. Refresh the meeting page to see it.';
      $('meeting-link').href = 'meetings/' + latest.meeting_id + '/';
      $('meeting-link').hidden = false;
      return;
    }
    if (latest?.state === 'hidden') {
      $('submission-status').textContent = 'Your talk is recorded privately and is hidden from the public page.';
      return;
    }
    if (latest?.state === 'needs-correction') {
      $('submission-status').textContent = 'Your talk needs correction. Contact the organizer for help.';
      return;
    }
    if (latest?.state === 'needs-attention') {
      $('submission-status').textContent = 'Your talk is recorded, but processing needs attention. Contact the organizer; do not submit another copy.';
      return;
    }
    $('submission-status').textContent = 'Submitted. Submission is not yet confirmed. You can keep this page open or check again later.';
    if (++pollCount < 12) pollTimer = setTimeout(checkStatus, 5000);
  }

  async function checkStatus() {
    if (busy || !pending) return;
    clearTimeout(pollTimer);
    busy = true;
    buttons();
    error();
    try { await status(); }
    catch { error('Submission status could not be confirmed. Check your credentials and use Check submission status again. No second submission was sent.'); }
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
      requireCheckedCredentials();
      // Re-read public eligibility immediately before submission; Actions checks
      // authoritative private state independently (including race conditions).
      await loadMeetings();
      requireCheckedCredentials();
      $('meeting').value = data.meeting;
      if (!meetings.has(data.meeting)) throw new Error('This meeting is no longer open for talk submissions.');
      const context = meetings.get(data.meeting);
      if (data.date < context.date || data.date > context.endDate) throw new Error('The meeting dates changed. Review your talk date before submitting.');
      if (!crypto.randomUUID) throw new Error('Use a browser with secure HTTPS access to submit a talk.');
    } catch (failure) { error(failure.message); busy = false; buttons(); return; }
    pending = {id: crypto.randomUUID(), login, username: participant.username, fingerprint: participant.credential_fingerprint, number: null};
    buttons();
    $('talk-fields').disabled = true;
    const prefix = data.meeting === 'demo-001' ? '[meeting 1]' : '[meeting ' + data.meeting.slice(8) + ']';
    const payload = {schema_version: 1, meeting_id: data.meeting, authors: data.authors,
      abstract: data.abstract, date: data.date, time: data.time, submission_id: pending.id, participant: {...participant}};
    const issue = {title: prefix + ' ' + data.title, body: MARKER + '\n```json\n' + JSON.stringify(payload, null, 2) + '\n```'};
    $('submission-status').textContent = 'Submitting your talk…';
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
        $('submission-status').textContent = 'The service did not accept this submission.';
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

  $('check-token').addEventListener('click', () => checkToken().catch(failure => error(failure.httpStatus || failure.safe ? failure.message : 'The credentials could not be checked. Verify them and try again.')));
  $('check-status').addEventListener('click', checkStatus);
  tokenField.addEventListener('input', resetIdentity);
  usernameField.addEventListener('input', resetIdentity);
  // No token, credentials, or private responses are persisted by this app.
  window.addEventListener('pagehide', () => {
    clearTimeout(pollTimer);
    tokenField.value = '';
    usernameField.value = '';
    resetIdentity();
  });
  // A meeting-specific Add talk link fixes the event; the generic form still
  // offers selection when opened without a meeting query parameter.
  $('meeting').addEventListener('change', scheduleFields);
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
