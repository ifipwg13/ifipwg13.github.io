/* Admin association requests contain only names/IDs/hashes, never passwords. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const REQUEST = '<!-- wg13-participant-request -->';
  const STATUS = '<!-- wg13-participant-status ';
  let credential = '', account = null, names = null, pending = null, busy = false, timer = null, polls = 0;
  function error(text = '') { $('form-error').textContent = text; $('form-error').hidden = !text; }
  function safe(failure) { return failure.httpStatus || failure.safe ? failure.message : 'The update could not be confirmed. Check its status before trying again.'; }
  function controls() {
    $('check-admin').disabled = busy;
    $('admin-token').disabled = busy;
    $('save-participant').disabled = busy || !!pending || !account;
    $('management-fields').disabled = busy || !!pending || !account;
    $('check-request').disabled = busy || !account;
    $('retry-request').disabled = busy || !account;
    $('next-update').disabled = busy;
  }
  function resetAccess() {
    credential = ''; account = null; names = null;
    $('admin-identity').textContent = '';
    $('participant-list').replaceChildren();
    $('directory-status').textContent = 'Check administrator access to load names.';
    controls();
  }
  function readPassword() {
    const value = $('admin-token').value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw Object.assign(new Error('Enter the administrator password without spaces.'), {safe: true});
    return value;
  }
  function api(path, method = 'GET', body) { return memberAPI.request(path, method, body, credential); }
  function fields() {
    const action = $('operation').value;
    const person = action !== 'add', name = ['add', 'rename'].includes(action), issued = ['add', 'replace'].includes(action);
    $('person-choice').hidden = !person; $('person').required = person; $('person').disabled = !person;
    $('name-field').hidden = !name; $('person-name').required = name; $('person-name').disabled = !name;
    $('issued-field').hidden = !issued; $('issued-token').required = issued; $('issued-token').disabled = !issued;
    if (!issued) $('issued-token').value = '';
    if (action === 'rename') {
      const selected = names?.members.find(member => member.id === $('person').value);
      if (selected) $('person-name').value = selected.name;
    }
  }
  async function loadNames() {
    names = await memberAPI.directory(credential, false);
    $('participant-list').replaceChildren(); $('person').replaceChildren();
    for (const [index, member] of (names?.members || []).entries()) {
      const active = member.credentials.some(key => key.active);
      const item = document.createElement('li'); item.textContent = member.name + (active ? '' : ' (inactive)');
      $('participant-list').append(item);
      $('person').add(new Option(member.name + (active ? '' : ' (inactive)') + ' · ' + (index + 1), member.id));
    }
    $('directory-status').textContent = names ? names.members.length ? '' : 'No participants have been added.' : 'Add the first participant to initialize the directory.';
    fields();
  }
  async function checkAccess() {
    if (busy) return;
    error(); resetAccess();
    let value;
    try { value = readPassword(); } catch (failure) { error(safe(failure)); return; }
    busy = true; controls();
    try {
      const verified = await memberAPI.administrator(value);
      if ($('admin-token').value.trim() !== value) throw new Error('Credentials changed');
      if (pending && verified.login !== pending.login) throw Object.assign(new Error('Use the original administrator account to check this update.'), {safe:true});
      credential = value; account = verified;
      await loadNames();
      $('admin-identity').textContent = 'Administrator access confirmed.';
    } catch (failure) { resetAccess(); error(safe(failure)); }
    finally { busy = false; controls(); }
  }
  function sameRequest(issue) {
    if (issue.pull_request || issue.user?.login !== pending.login || !(issue.body || '').startsWith(REQUEST + '\n```json\n')) return false;
    try {
      const data = JSON.parse(issue.body.slice((REQUEST + '\n```json\n').length).replace(/\n```\s*$/, ''));
      return JSON.stringify(data) === JSON.stringify(pending.payload);
    } catch { return false; }
  }
  async function recover() {
    for (let page = 1; page <= 5; page++) {
      const rows = await api(memberAPI.repo + '/issues?state=all&creator=' + encodeURIComponent(pending.login) + '&sort=created&direction=desc&per_page=100&page=' + page);
      if (!Array.isArray(rows)) throw new Error('Invalid response');
      const matches = rows.filter(sameRequest);
      if (matches.length > 1) throw Object.assign(new Error('More than one matching update exists. Review it before continuing.'), {safe:true});
      if (matches.length === 1) { pending.number = matches[0].number; return; }
      if (rows.length < 100) break;
    }
    throw Object.assign(new Error('The update has not been located. Check status again; do not submit another copy.'), {safe:true});
  }
  async function status() {
    if (!pending || !account || readPassword() !== credential || account.login !== pending.login) throw Object.assign(new Error('Check the original administrator credentials before checking status.'), {safe:true});
    if (!pending.number) await recover();
    const states = [];
    for (let page = 1; page <= 10; page++) {
      const comments = await api(memberAPI.repo + '/issues/' + pending.number + '/comments?per_page=100&page=' + page);
      if (!Array.isArray(comments)) throw new Error('Invalid response');
      for (const comment of comments) {
        if (!memberAPI.bot(comment) || !(comment.body || '').startsWith(STATUS)) continue;
        try {
          const value = JSON.parse(comment.body.slice(STATUS.length, comment.body.indexOf(' -->')));
          if (value.schema_version === 1 && value.request_id === pending.payload.request_id) states.push(value);
        } catch { /* Only trusted, matching status metadata counts. */ }
      }
      if (comments.length < 100) break;
      if (page === 10) throw new Error('Too many status comments');
    }
    const latest = states.at(-1);
    if (latest?.state === 'complete' && memberAPI.uuid(latest.member_id) && Number.isSafeInteger(latest.revision)) {
      await loadNames();
      if (!names || names.revision < latest.revision || !names.members.some(member => member.id === latest.member_id)) throw new Error('Directory verification pending');
      $('update-status').textContent = 'Participant update confirmed.';
      $('check-request').hidden = true; $('retry-request').hidden = true; $('next-update').hidden = false;
      pending.complete = true;
    } else if (latest?.state === 'needs-attention') {
      const reason = typeof latest.reason === 'string' && latest.reason.length <= 300 ? latest.reason : 'Check the private configuration before retrying this same request.';
      $('update-status').textContent = 'The update needs administrator attention. ' + reason;
      $('retry-request').hidden = false;
    } else {
      $('update-status').textContent = 'Update submitted. Waiting for confirmation.';
      if (++polls < 12) timer = setTimeout(checkStatus, 5000);
    }
  }
  async function checkStatus() {
    if (busy || !pending) return;
    clearTimeout(timer); busy = true; controls(); error();
    try { await status(); } catch (failure) { error(safe(failure)); }
    finally { busy = false; controls(); }
  }
  $('talk-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || pending || !account) return;
    error();
    const action = $('operation').value;
    let payload;
    let issued = '';
    try {
      if (!crypto?.randomUUID || !crypto?.subtle) throw Object.assign(new Error('Open this page over HTTPS to manage participants.'), {safe:true});
      payload = {schema_version: 1, request_id: crypto.randomUUID(), action};
      if (readPassword() !== credential) throw new Error('Check administrator credentials');
      if (action !== 'add') {
        if (!memberAPI.uuid($('person').value)) throw Object.assign(new Error('Select a participant.'), {safe:true});
        payload.member_id = $('person').value;
      }
      if (['add', 'rename'].includes(action)) {
        payload.name = $('person-name').value.trim();
        if (!memberAPI.realName(payload.name) || payload.name === credential) throw Object.assign(new Error('Enter a name on one line, at most 200 characters; never enter a password here.'), {safe:true});
      }
      if (['add', 'replace'].includes(action)) {
        issued = $('issued-token').value.trim();
        $('issued-token').value = ''; // Clear before any asynchronous request.
        if (!issued || !/^[\x21-\x7e]+$/.test(issued) || issued === credential || issued === payload.name) throw Object.assign(new Error('Enter the issued member password, not the administrator credential or participant name.'), {safe:true});
      }
    } catch (failure) { issued = ''; $('issued-token').value = ''; error(safe(failure)); return; }
    busy = true; controls();
    try {
      if (issued) payload.fingerprint = await memberAPI.fingerprint(issued);
      issued = '';
      if (readPassword() !== credential || !account) throw new Error('Administrator credentials changed');
      pending = {payload, login: account.login, number: null};
      const body = REQUEST + '\n```json\n' + JSON.stringify(payload, null, 2) + '\n```';
      $('update-status').textContent = 'Submitting participant update…';
      const created = await api(memberAPI.repo + '/issues', 'POST', {title: 'Participant management request', body});
      if (!Number.isSafeInteger(created.number) || created.number < 1) throw new Error('Unconfirmed request');
      pending.number = created.number;
    } catch (failure) {
      issued = '';
      if (failure.httpStatus && [401,403,404,410,422,429].includes(failure.httpStatus)) {
        pending = null; error(safe(failure)); $('update-status').textContent = 'The update was not accepted.';
      } else if (pending) {
        $('update-status').textContent = 'The response was interrupted. Check update status; do not send another copy.';
        error(safe(failure));
      } else {
        $('update-status').textContent = 'No update was sent.';
        error(safe(failure));
      }
    } finally {
      issued = ''; busy = false; $('check-request').hidden = !pending; controls();
    }
    if (pending) await checkStatus();
  });
  $('retry-request').addEventListener('click', async () => {
    if (busy || !pending || !account || !pending.number) return;
    busy = true; controls(); error();
    try {
      if (readPassword() !== credential || account.login !== pending.login) throw new Error('Check original administrator credentials');
      await api(memberAPI.repo + '/issues/' + pending.number + '/comments', 'POST', {body:'/retry-participants'});
      polls = 0; $('retry-request').hidden = true;
      $('update-status').textContent = 'Retry requested. Check update status for confirmation.';
    } catch (failure) { error(safe(failure)); }
    finally { busy = false; controls(); }
  });
  $('next-update').addEventListener('click', () => {
    if (busy || !pending?.complete) return;
    pending = null; polls = 0; clearTimeout(timer);
    $('next-update').hidden = true; $('update-status').textContent = ''; $('person-name').value = ''; fields(); controls();
  });
  $('check-admin').addEventListener('click', checkAccess);
  $('check-request').addEventListener('click', checkStatus);
  $('admin-token').addEventListener('input', resetAccess);
  $('operation').addEventListener('change', fields);
  $('person').addEventListener('change', fields);
  window.addEventListener('pagehide', () => {
    clearTimeout(timer); $('admin-token').value = ''; $('issued-token').value = ''; $('person-name').value = ''; resetAccess();
  });
  $('form-status').textContent = '';
  $('admin-fields').disabled = false;
  fields(); controls();
})();
