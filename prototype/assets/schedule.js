/* One administrator session, one meeting, one private batch request. */
(() => {
  'use strict';
  const MARKER = '<!-- wg13-schedule-request -->';
  const STATUS = '<!-- wg13-schedule-status ';
  const ident = new URLSearchParams(location.search).get('meeting');
  const $ = id => document.getElementById(id);
  let meeting = null, credential = '', account = null, registrationHash = '';
  let busy = false, rows = [], pending = null, timer = null, polls = 0;
  const problem = message => Object.assign(new Error(message), {safe:true});
  const labels = issue => (issue.labels || []).map(label => typeof label === 'string' ? label : label.name);
  const hash = text => memberAPI.fingerprint(text);
  function error(message = '') { $('form-error').textContent = message; $('form-error').hidden = !message; }
  function safe(failure) { return failure.safe || failure.httpStatus ? failure.message : 'The service could not be reached. Check progress before trying again.'; }
  function password() {
    const value = $('admin-token').value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw problem('Enter your administrator password, without spaces.');
    return value;
  }
  function checked() {
    if (!account || !credential || password() !== credential) throw problem('Check administrator credentials before continuing.');
  }
  function api(path, method = 'GET', body) { checked(); return memberAPI.request(path, method, body, credential); }
  function controls() {
    $('admin-token').readOnly = busy;
    $('check-admin').disabled = busy || !meeting;
    $('save-schedule').disabled = busy || !account || !!pending || !rows.length;
    $('reload-talks').hidden = !account;
    $('reload-talks').disabled = busy || !!pending && !pending.complete;
    $('check-status').hidden = !pending;
    $('check-status').disabled = busy || !account;
    for (const row of rows) {
      for (const field of [row.dateField, row.timeField]) field.disabled = busy || !account || !!pending || !row.editable;
      row.hiddenField.disabled = busy || !account || !!pending;
    }
  }
  function resetAccess() { credential = ''; account = null; clearTimeout(timer); $('admin-identity').textContent = ''; controls(); }
  function headings(body) {
    const found = []; let offset = 0, fence = null;
    for (const line of body.match(/[^\n]*\n|[^\n]+$/g) || []) {
      const marker = /^\s{0,3}(`{3,}|~{3,})/.exec(line);
      if (marker) {
        if (!fence) fence = marker[1];
        else if (marker[1][0] === fence[0] && marker[1].length >= fence.length) fence = null;
      } else if (!fence) {
        const heading = /^(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$/.exec(line);
        if (heading) found.push({start:offset, end:offset + line.length, depth:heading[1].length, title:heading[2]});
      }
      offset += line.length;
    }
    return found;
  }
  function answer(body, label) {
    const found = headings(body), matches = found.filter(h => h.depth === 3 && h.title === label);
    if (matches.length > 1) throw problem('Duplicate fields need manual correction.');
    if (!matches.length) return '';
    const h = matches[0], next = found.find(item => item.start > h.start && item.depth <= h.depth);
    const value = body.slice(h.end, next ? next.start : body.length).trim();
    return /^_No response_$/i.test(value) ? '' : value;
  }
  async function currentMeeting() {
    const issue = await api(memberAPI.repo + '/issues/' + meeting.registration);
    const names = labels(issue);
    if (issue.number !== meeting.registration || issue.pull_request || !names.includes('registration') ||
        names.filter(name => name.startsWith('meeting:')).join(',') !== 'meeting:' + ident || names.includes('hidden')) {
      throw problem('This meeting is hidden or unavailable. Return to all meetings.');
    }
    const body = issue.body || '';
    const olderBody = body.replace(/\\([\\`*_{}\[\]()<>#+.!|~-])/g, '$1');
    const oldStart = /^- (?:\*\*)?(?:Date|Start):(?:\*\*)?\s+(\S+)/m.exec(olderBody)?.[1];
    const oldEnd = /^- (?:\*\*)?End:(?:\*\*)?\s+(\S+)/m.exec(olderBody)?.[1];
    let date, endDate;
    try {
      date = memberAPI.calendar(answer(body, 'Start date') || answer(body, 'Date') || oldStart || '');
      endDate = memberAPI.calendar(answer(body, 'End date') || oldEnd || date);
      if (endDate < date) throw new Error();
    } catch { throw problem('The meeting dates need administrator correction before scheduling.'); }
    return {issue, date, endDate, hash:await hash(body)};
  }
  function talk(issue) {
    const names = labels(issue);
    if (!Number.isSafeInteger(issue.number) || issue.number < 1 || issue.pull_request || !names.includes('talk') || names.includes('registration') ||
        names.filter(name => name.startsWith('meeting:')).join(',') !== 'meeting:' + ident) return null;
    const body = issue.body || '';
    let title = (issue.title || '').replace(/^\[(?:meeting [0-9]+|meeting-[0-9]+|demo-001)\]\s*/, '');
    let authors, date, time, editable = true;
    try {
      if (body.startsWith('<!-- wg13-web-talk -->') || names.includes('talk-format:v1')) {
        const match = /^<!-- wg13-web-talk -->\n```json\n([\s\S]+)\n```\s*$/.exec(body);
        const data = JSON.parse(match?.[1] || '');
        if (data.meeting_id !== ident || typeof data.authors !== 'string') throw new Error();
        authors = data.authors; date = data.date; time = data.time;
      } else {
        authors = answer(body, 'Authors'); date = answer(body, 'Talk date'); time = answer(body, 'Talk time');
      }
    } catch { editable = false; authors = ''; }
    let correction = false;
    try { date = date ? memberAPI.calendar(date) : meeting.date; } catch { date = ''; correction = true; }
    try { time = time ? memberAPI.clock(time) : '09:00'; } catch { time = ''; correction = true; }
    if (date < meeting.date || date > meeting.endDate) correction = true;
    const originalDate = date;
    if (meeting.date === meeting.endDate) date = meeting.date;
    return {number:issue.number, body, title, authors, date, time, originalDate, originalTime:time, editable, hidden:names.includes('talk-hidden'),
      status:[names.includes('talk-hidden') ? 'Hidden' : '', issue.state === 'closed' ? 'Closed' : '',
        !editable ? 'Needs manual correction' : correction ? 'Needs schedule correction' : ''].filter(Boolean).join('; ')};
  }
  function render() {
    $('schedule-rows').replaceChildren();
    for (const row of rows) {
      const tr = document.createElement('tr'); tr.dataset.talkNumber = row.number;
      const titleCell = document.createElement('th'); titleCell.scope = 'row';
      titleCell.textContent = row.title + (row.authors ? ' by ' + row.authors : '');
      tr.append(titleCell);
      for (const [kind, value] of [['date', row.date], ['time', row.time]]) {
        const td = document.createElement('td'), input = document.createElement('input');
        input.type = 'text'; input.value = kind === 'date' && value ? memberAPI.displayDate(value) : value;
        input.maxLength = kind === 'date' ? 10 : 5;
        input.setAttribute('aria-label', (kind === 'date' ? 'Date' : 'Time') + ' for ' + row.title);
        input.readOnly = kind === 'date' && meeting.date === meeting.endDate;
        row[kind + 'Text'] = input.value;
        row[kind + 'Field'] = input; td.append(input); tr.append(td);
      }
      const visibility = document.createElement('td'), checkbox = document.createElement('input');
      checkbox.type = 'checkbox'; checkbox.checked = row.hidden;
      checkbox.setAttribute('aria-label', 'Hidden for ' + row.title);
      checkbox.addEventListener('change', () => {
        row.statusField.textContent = checkbox.checked === row.hidden ? row.status : checkbox.checked ? 'Will hide on save' : 'Will restore on save';
      });
      row.hiddenField = checkbox; visibility.append(checkbox); tr.append(visibility);
      const status = document.createElement('td'); status.className = 'schedule-result'; status.textContent = row.status;
      row.statusField = status; tr.append(status); $('schedule-rows').append(tr);
    }
    $('schedule-editor').hidden = false;
    $('form-status').textContent = rows.length ? '' : 'This meeting has no talks to schedule.';
    controls();
  }
  async function loadTalks() {
    const current = await currentMeeting();
    meeting.date = current.date; meeting.endDate = current.endDate; registrationHash = current.hash;
    $('meeting-name').textContent = current.issue.title.replace(/^\[(?:meeting [0-9]+|meeting-[0-9]+|demo-001)\]\s*/, '');
    $('meeting-dates').textContent = 'When: ' + memberAPI.displayDate(meeting.date) + (meeting.date === meeting.endDate ? '' : ' – ' + memberAPI.displayDate(meeting.endDate));
    const loaded = [], seen = new Set();
    for (let page = 1; page <= 100; page++) {
      const batch = await api(memberAPI.repo + '/issues?state=all&labels=' + encodeURIComponent('talk,meeting:' + ident) + '&per_page=100&page=' + page);
      if (!Array.isArray(batch)) throw new Error('Invalid response');
      for (const issue of batch) {
        const row = talk(issue);
        if (row) {
          if (seen.has(row.number)) throw problem('Talk records changed while loading. Reload talks.');
          seen.add(row.number); row.bodyHash = await hash(row.body); delete row.body; loaded.push(row);
        }
      }
      if (batch.length < 100) break;
      if (page === 100) throw problem('Too many talks to load safely. Contact the organizer.');
    }
    rows = loaded.sort((a, b) => a.date.localeCompare(b.date) || a.time.localeCompare(b.time) || a.number - b.number);
    pending = null; polls = 0; clearTimeout(timer); $('submission-status').textContent = '';
    render();
  }
  async function verify() {
    const candidate = password(), verified = await memberAPI.administrator(candidate);
    if (password() !== candidate || pending && verified.login !== pending.login) throw problem('Check the original administrator credentials before continuing.');
    credential = candidate; account = verified;
    $('admin-identity').textContent = 'Administrator access confirmed.';
  }
  async function checkAccess() {
    if (busy || !meeting) return;
    error(); resetAccess(); busy = true; controls();
    try { await verify(); if (!pending) await loadTalks(); }
    catch (failure) { resetAccess(); error(safe(failure)); }
    finally { busy = false; controls(); }
  }
  async function progress() {
    checked();
    const comments = [];
    for (let page = 1; page <= 100; page++) {
      const batch = await api(memberAPI.repo + '/issues/' + meeting.registration + '/comments?per_page=100&page=' + page);
      if (!Array.isArray(batch)) throw new Error('Invalid response');
      comments.push(...batch);
      if (batch.length < 100) break;
      if (page === 100) throw problem('Too many comments to check safely. Contact the organizer.');
    }
    const requests = comments.filter(c => c.user?.login === pending.login && c.body === pending.body);
    if (requests.length > 1) throw problem('More than one matching scheduling request exists. Contact the organizer.');
    if (!pending.commentId && requests.length === 1) pending.commentId = requests[0].id;
    let latest = null;
    for (const comment of comments) {
      if (!memberAPI.bot(comment) || !(comment.body || '').startsWith(STATUS)) continue;
      try {
        const value = JSON.parse(comment.body.slice(STATUS.length, comment.body.indexOf(' -->')));
        if (value.schema_version === 1 && value.request_id === pending.id && value.request_hash === pending.hash &&
            value.meeting_id === ident && value.comment_id === pending.commentId && Array.isArray(value.results) &&
            value.results.length === pending.changes.length && value.results.every((row, i) => row.number === pending.changes[i].number)) latest = value;
      } catch { /* Only a matching trusted receipt can confirm synchronization. */ }
    }
    const messages = {saved:'Saved', applying:'Saving…', pending:'Waiting', conflict:'Changed elsewhere — reload', unavailable:'Unavailable or moved', invalid:'Needs manual correction', failed:'Not confirmed — reload'};
    for (const result of latest?.results || []) {
      const row = rows.find(row => row.number === result.number);
      if (!row) continue;
      const requested = pending.changes.find(item => item.number === result.number), parts = [];
      if (result.schedule_state) parts.push(('hidden' in requested ? 'Schedule: ' : '') + (messages[result.schedule_state] || 'Not confirmed'));
      if (result.visibility_state && result.publication !== 'changed-elsewhere') parts.push(result.visibility_state === 'saved' ? requested.hidden ? 'Hidden' : 'Restored' : 'Visibility: ' + (messages[result.visibility_state] || 'Not confirmed'));
      if (result.publication === 'not-published') parts.push(requested.hidden ? 'Hiding not confirmed' : 'Not published — check proposal content and meeting status');
      if (result.publication === 'changed-elsewhere') parts.push('Visibility changed elsewhere — reload');
      row.statusField.textContent = parts.length ? parts.join('; ') : messages[result.state] || 'Not confirmed';
    }
    if (['synchronized', 'partial'].includes(latest?.state) && /^[a-f0-9]{40}$/.test(latest.revision)) {
      pending.complete = true; clearTimeout(timer);
      $('submission-status').textContent = latest.state === 'synchronized' ? 'Schedule synchronized. Return to the meeting to see the updated programme.' : 'Some changes need attention. Review the talk results, then reload talks before retrying.';
    } else if (latest?.state === 'needs-attention') {
      pending.complete = true; clearTimeout(timer);
      $('submission-status').textContent = 'Scheduling needs attention. Some changes may already be saved; synchronization is not confirmed. Reload talks to review the current schedule.';
    } else {
      $('submission-status').textContent = 'Request submitted. Waiting for scheduling and synchronization. Use Check progress if this takes longer.';
      if (++polls < 12) timer = setTimeout(checkProgress, 5000);
    }
  }
  async function checkProgress() {
    if (busy || !pending) return;
    clearTimeout(timer); busy = true; controls(); error();
    try { await progress(); } catch (failure) { error(safe(failure)); }
    finally { busy = false; controls(); }
  }
  $('talk-form').addEventListener('submit', async event => {
    event.preventDefault(); if (busy || pending || !account) return;
    error(); busy = true; controls();
    try {
      checked(); const changes = [];
      for (const row of rows) {
        const change = {number:row.number, body_hash:row.bodyHash};
        const visibilityChanged = row.hiddenField.checked !== row.hidden;
        if (visibilityChanged) Object.assign(change, {hidden:row.hiddenField.checked, expected_hidden:row.hidden});
        const slotChanged = row.dateField.value.trim() !== row.dateText || row.timeField.value.trim() !== row.timeText;
        if (row.editable && (slotChanged || !visibilityChanged && row.date !== row.originalDate)) {
          let date, time;
          try { date = memberAPI.calendar(row.dateField.value.trim()); time = memberAPI.clock(row.timeField.value.trim()); }
          catch { throw problem('Enter valid dates and HH:MM times for the talks.'); }
          if (date < meeting.date || date > meeting.endDate) throw problem('Choose talk dates within the meeting dates.');
          if (date !== row.originalDate || time !== row.originalTime) Object.assign(change, {date, time});
        }
        if ('date' in change || 'hidden' in change) changes.push(change);
      }
      if (!changes.length) { $('submission-status').textContent = 'No scheduling changes to save.'; return; }
      if (changes.length > 100) throw problem('Save at most 100 changed talks at a time.');
      await verify();
      const current = await currentMeeting();
      if (current.hash !== registrationHash) throw problem('The meeting details changed. Reload talks before saving.');
      const id = crypto.randomUUID();
      const body = MARKER + '\n```json\n' + JSON.stringify({schema_version:1, request_id:id, meeting_id:ident, registration_hash:registrationHash, changes}) + '\n```';
      pending = {id, body, hash:await hash(body), login:account.login, commentId:null, changes, complete:false};
      $('submission-status').textContent = 'Submitting scheduling request…';
      try {
        const result = await api(memberAPI.repo + '/issues/' + meeting.registration + '/comments', 'POST', {body});
        if (!Number.isSafeInteger(result.id) || result.id < 1) throw new Error('Unconfirmed request');
        pending.commentId = result.id;
      } catch (failure) {
        if ([400,401,403,404,410,422,429].includes(failure.httpStatus)) { pending = null; throw failure; }
        // An uncertain POST is recovered by GET + UUID, never posted twice.
      }
      await progress();
    } catch (failure) { error(safe(failure)); }
    finally { busy = false; controls(); }
  });
  $('check-admin').addEventListener('click', checkAccess);
  $('check-status').addEventListener('click', checkProgress);
  $('reload-talks').addEventListener('click', async () => {
    if (busy || pending && !pending.complete) return;
    error(); busy = true; controls();
    try { await verify(); await loadTalks(); } catch (failure) { error(safe(failure)); }
    finally { busy = false; controls(); }
  });
  for (const event of ['input', 'change']) $('admin-token').addEventListener(event, resetAccess);
  addEventListener('pagehide', () => { resetAccess(); $('admin-token').value = ''; rows = []; pending = null; $('schedule-rows').replaceChildren(); $('schedule-editor').hidden = true; });
  async function start() {
    try {
      if (!/^(?:demo-001|meeting-[1-9][0-9]*)$/.test(ident || '')) throw problem('Open Schedule from the meeting you want to edit.');
      const meetings = await memberAPI.meetings(); meeting = meetings.get(ident);
      if (!meeting?.registration) throw problem('This meeting is unavailable. Return to all meetings.');
      $('meeting-name').textContent = meeting.name;
      $('meeting-link').href = 'meetings/' + ident + '/'; $('meeting-link').textContent = 'Return to meeting';
      $('admin-fields').disabled = false; $('form-status').textContent = '';
    } catch (failure) { meeting = null; $('form-status').textContent = failure.safe ? failure.message : 'Meeting information could not be loaded. Please reload this page.'; }
    controls();
  }
  start();
})();
