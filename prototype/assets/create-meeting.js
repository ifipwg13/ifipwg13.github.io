/* Administrator-only Issue creation. Credentials stay in memory/Authorization. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let automaticEnd = '';
  $('start-date').addEventListener('input', () => {
    if (!$('end-date').value || $('end-date').value === automaticEnd) {
      $('end-date').value = $('start-date').value;
      automaticEnd = $('end-date').value;
    }
  });
  const MARKER = '<!-- wg13-meeting-submission:';
  const STATUS = '<!-- wg13-meeting-status ';
  let credential = '', account = null, pending = null, busy = false, timer = null, polls = 0;
  const problem = text => Object.assign(new Error(text), {safe:true});
  function error(text = '') { $('form-error').textContent = text; $('form-error').hidden = !text; }
  function safe(failure) { return failure.httpStatus || failure.safe ? failure.message : 'The request could not be confirmed. Check creation status before trying again.'; }
  function controls() {
    $('create-meeting').disabled = busy || !!pending || !account;
    $('check-admin').disabled = busy;
    $('admin-token').disabled = busy;
    $('meeting-fields').disabled = busy || !!pending;
    $('check-status').disabled = busy || !account;
  }
  function resetAccess() {
    credential = ''; account = null;
    $('admin-identity').textContent = '';
    controls();
  }
  function password() {
    const value = $('admin-token').value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw problem('Enter the administrator password without spaces.');
    return value;
  }
  function checked() {
    if (!account || password() !== credential || (pending && account.login !== pending.login)) throw problem('Check the administrator credentials before continuing.');
  }
  function api(path, method = 'GET', body) { checked(); return memberAPI.request(path, method, body, credential); }
  async function checkAccess() {
    if (busy) return;
    error(); resetAccess();
    let candidate;
    try { candidate = password(); } catch (failure) { error(safe(failure)); return; }
    busy = true; controls();
    try {
      const verified = await memberAPI.administrator(candidate);
      if (password() !== candidate) throw problem('The password changed. Check credentials again.');
      if (pending && verified.login !== pending.login) throw problem('Use the original administrator account to check this meeting.');
      credential = candidate; account = verified;
      $('admin-identity').textContent = 'Administrator access confirmed.';
    } catch (failure) { resetAccess(); error(safe(failure)); }
    finally { busy = false; controls(); }
  }
  function field(id, title, limit, required = true, multiline = false) {
    const text = $(id).value.trim();
    if ((required && !text) || Array.from(text).length > limit || /[\x00-\x09\x0b-\x1f\x7f]/.test(text) || (!multiline && text.includes('\n'))) throw problem('Enter ' + title + ' using at most ' + limit + ' characters.');
    if (text && (text === credential || /(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+/.test(text))) throw problem('Enter meeting details only; never enter a password in these fields.');
    return text;
  }
  function details() {
    const name = field('meeting-name', 'the meeting name', 200);
    if (/^\[meeting[ -][0-9]+\]/.test(name)) throw problem('Enter the meeting name without a meeting number.');
    let start, end;
    try {
      start = memberAPI.calendar($('start-date').value.trim());
      end = $('end-date').value.trim() ? memberAPI.calendar($('end-date').value.trim()) : start;
    } catch { throw problem('Enter valid dates as DD-MM-YYYY or DD-MM-YY, leading zeros are optional.'); }
    if (end < start) throw problem('The end date must be on or after the start date.');
    const location = field('location', 'the location', 200);
    const description = field('description', 'the description', 1200, false, true);
    if (/^### .+$/m.test(description)) throw problem('Use plain paragraphs in the description, without lines starting with ###.');
    return {name, start, end, location, description};
  }
  function matches(issue) {
    return !issue.pull_request && issue.user?.login === pending.login &&
      (issue.body || '').split('\n').includes(MARKER + pending.id + ' -->');
  }
  async function recover() {
    for (let page = 1; page <= 5; page++) {
      const batch = await api(memberAPI.repo + '/issues?state=all&creator=' + encodeURIComponent(pending.login) + '&sort=created&direction=desc&per_page=100&page=' + page);
      if (!Array.isArray(batch)) throw new Error('Invalid response');
      const found = batch.filter(matches);
      if (found.length > 1) throw problem('More than one matching record exists. Review the saved meeting before continuing.');
      if (found.length === 1) { pending.number = found[0].number; return; }
      if (batch.length < 100) break;
    }
    throw problem('The submitted meeting has not been located. Check creation status again; do not create another copy.');
  }
  async function status() {
    checked();
    if (!pending.number) await recover();
    if (!Number.isSafeInteger(pending.number) || pending.number < 1) throw new Error('Invalid reference');
    const issue = await api(memberAPI.repo + '/issues/' + pending.number);
    if (!matches(issue)) throw problem('The saved meeting could not be matched to this submission. Contact the organizer.');
    const states = [];
    for (let page = 1; page <= 10; page++) {
      const batch = await api(memberAPI.repo + '/issues/' + pending.number + '/comments?per_page=100&page=' + page);
      if (!Array.isArray(batch)) throw new Error('Invalid response');
      for (const comment of batch) {
        if (!memberAPI.bot(comment) || !(comment.body || '').startsWith(STATUS)) continue;
        try {
          const data = JSON.parse(comment.body.slice(STATUS.length, comment.body.indexOf(' -->')));
          if (data.schema_version === 1 && data.submission_id === pending.id && data.meeting_id === 'meeting-' + pending.number) states.push(data);
        } catch { /* Unrelated comments never become confirmation or page content. */ }
      }
      if (batch.length < 100) break;
      if (page === 10) throw new Error('Too many comments');
    }
    const latest = states.at(-1);
    if (latest?.state === 'ready' && /^[a-f0-9]{40}$/.test(latest.revision)) {
      const labels = (issue.labels || []).map(label => typeof label === 'string' ? label : label.name);
      if (!labels.includes('registration') || !labels.includes('meeting:' + latest.meeting_id)) throw new Error('Registration verification pending');
      const hidden = labels.includes('hidden');
      const archived = labels.includes('archived') || issue.state !== 'open' || issue.locked;
      $('submission-status').textContent = hidden ? 'Meeting synchronized. It is currently hidden.' : archived ? 'Meeting synchronized. It is currently archived.' : 'Meeting ready. Open the meeting or refresh the meetings page.';
      $('meeting-link').href = 'meetings/' + latest.meeting_id + '/';
      $('meeting-link').hidden = hidden;
      pending.complete = true; clearTimeout(timer);
    } else if (latest?.state === 'needs-attention') {
      $('submission-status').textContent = 'Meeting preparation needs attention. An administrator can correct the saved meeting issue by editing it. Then check creation status again.';
      $('meeting-link').hidden = true;
    } else {
      $('submission-status').textContent = 'Submitted. Waiting for the meeting to be synchronized.';
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
    let data, id;
    try {
      checked(); data = details();
      if (!crypto.randomUUID) throw problem('Open this page over HTTPS to create a meeting.');
      id = crypto.randomUUID();
    } catch (failure) { error(safe(failure)); return; }
    const body = MARKER + id + ' -->\n\n### Start date\n\n' + memberAPI.displayDate(data.start) + '\n\n### End date\n\n' + memberAPI.displayDate(data.end) + '\n\n### Location\n\n' + data.location + '\n\n### Description\n\n' + (data.description || '_No response_') + '\n';
    busy = true; controls();
    $('submission-status').textContent = 'Submitting meeting…';
    try {
      // Recheck the current role at submission, before any Issue POST.
      const verified = await memberAPI.administrator(credential);
      checked();
      if (verified.login !== account.login) throw problem('Check administrator credentials again.');
      pending = {id, login:account.login, number:null};
      $('check-status').hidden = false;
      const created = await api(memberAPI.repo + '/issues', 'POST', {title:data.name, body});
      if (!Number.isSafeInteger(created.number) || created.number < 1) throw new Error('Unconfirmed submission');
      pending.number = created.number;
    } catch (failure) {
      if (!pending || [400,401,403,404,410,422,429].includes(failure.httpStatus)) {
        pending = null; $('check-status').hidden = true;
        $('submission-status').textContent = 'The meeting was not accepted.';
        resetAccess();
      } else $('submission-status').textContent = 'The response was interrupted. Check creation status; do not create another copy.';
      error(safe(failure));
    } finally { busy = false; controls(); }
    if (pending) await checkStatus();
  });
  $('check-admin').addEventListener('click', checkAccess);
  $('check-status').addEventListener('click', checkStatus);
  $('admin-token').addEventListener('input', resetAccess);
  window.addEventListener('pagehide', () => { clearTimeout(timer); $('admin-token').value = ''; resetAccess(); });
  $('form-status').textContent = '';
  $('admin-fields').disabled = false;
  controls();
})();
