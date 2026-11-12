/* Attendance comments resolve names through the protected private directory. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ident = new URLSearchParams(location.search).get('meeting');
  const tokenField = $('github-token');
  let meeting = null;
  let accepting = false;
  let token = '';
  let owner = null;
  let participant = null;
  let directoryData = null;
  let credentialActive = false;
  let personName = "";
  let busy = false;
  let pending = null;

  function problem(message) { const error = new Error(message); error.safe = true; return error; }
  function showError(message = '') { $('form-error').textContent = message; $('form-error').hidden = !message; }
  function message(error) { return error.httpStatus || error.safe ? error.message : 'The service could not be reached. Check status before trying again.'; }
  function action() { return document.querySelector('input[name="participation"]:checked')?.value; }
  function controls() {
    $('submit-participation').disabled = busy || !!pending || !owner || !credentialActive || !accepting || !action();
    $('check-token').disabled = busy;
    $('check-status').disabled = busy || !owner;
    tokenField.disabled = busy;
    for (const radio of document.querySelectorAll('input[name="participation"]')) radio.disabled = busy;
  }
  function resetIdentity() {
    token = '';
    owner = null;
    participant = null;
    directoryData = null;
    credentialActive = false;
    personName = "";
    $('identity').textContent = '';
    $('participation-status').textContent = 'Check your credentials to see your current participation status.';
    $('legacy-attendance').hidden = true;
    if (!pending) $('submission-status').textContent = '';
    controls();
  }
  function readToken() {
    const value = tokenField.value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw problem('Enter the password supplied by the organizer, without spaces.');
    return value;
  }
  function api(path, method = 'GET', body, credential = token) {
    return memberAPI.request(path, method, body, credential);
  }
  function issuePath() { return memberAPI.repo + '/issues/' + meeting.registration; }

  async function currentIssue(requireOpen = true, credential = token) {
    const issue = await api(issuePath(), 'GET', undefined, credential);
    const names = (issue.labels || []).map(label => typeof label === 'string' ? label : label.name);
    const associations = names.filter(name => name.startsWith('meeting:'));
    if (issue.number !== meeting.registration || issue.pull_request || !names.includes('registration') ||
        associations.length !== 1 || associations[0] !== 'meeting:' + ident) {
      accepting = false;
      throw problem('The registration record could not be verified. Contact the organizer.');
    }
    accepting = issue.state === 'open' && !issue.locked && !names.includes('archived') && !names.includes('hidden');
    if (requireOpen && !accepting) throw problem('This meeting is closed for participation changes.');
    return issue;
  }

  async function ownAttendance(user, person, credential = token) {
    let found = null;
    for (let page = 1; page <= 100; page++) {
      const batch = await api(issuePath() + '/comments?per_page=100&page=' + page, 'GET', undefined, credential);
      if (!Array.isArray(batch)) throw problem('Participation status could not be read.');
      for (const comment of batch) {
        const record = memberAPI.attendanceRecord(comment, ident, user, directoryData);
        if (!record || record.member_id !== person.member_id) continue;
        if (found) throw problem('More than one participation record exists for this participant. Contact the organizer.');
        found = comment;
      }
      if (batch.length < 100) return found;
    }
    throw problem('There are too many participation records to check. Contact the organizer.');
  }

  async function checkEarlierRegistrations(credential) {
    const reactions = await api(issuePath() + '/reactions?content=%2B1&per_page=1', 'GET', undefined, credential);
    if (!Array.isArray(reactions)) throw problem('Earlier registrations could not be checked. Contact the organizer.');
    $('legacy-attendance').hidden = !reactions.length;
  }

  function displayState(comment) {
    $('participation-status').textContent = comment ? 'You are currently registered.' :
      $('legacy-attendance').hidden ? 'You are currently not registered.' :
      'No registration for you was found. Earlier registrations need organizer confirmation.';
  }

  async function checkToken() {
    if (busy || !meeting) return;
    showError();
    resetIdentity();
    let candidate;
    try { candidate = readToken(); }
    catch (error) { showError(message(error)); return; }
    busy = true;
    controls();
    try {
      const identity = await memberAPI.identify(candidate, !pending);
      const user = identity.account;
      const person = identity.participant;
      if (pending && (pending.owner !== user.id || pending.member_id !== person.member_id || pending.fingerprint !== person.credential_fingerprint)) throw problem('Use the original password to confirm the pending participation change.');
      await currentIssue(!pending, candidate);
      directoryData = identity.names;
      const comment = await ownAttendance(user, person, candidate);
      await checkEarlierRegistrations(candidate);
      if (tokenField.value.trim() !== candidate) throw problem('The credentials changed. Check them again.');
      token = candidate;
      owner = user;
      participant = person;
      credentialActive = identity.active;
      personName = identity.name;
      $('identity').textContent = 'Credentials accepted for ' + personName + '.';
      displayState(comment);
    } catch (error) { showError(message(error)); }
    finally { busy = false; controls(); }
  }

  async function verifyPending() {
    if (!owner || !participant || readToken() !== token || owner.id !== pending.owner ||
        participant.member_id !== pending.member_id || participant.credential_fingerprint !== pending.fingerprint) throw problem('Check the original password before checking status.');
    await currentIssue(false);
    const comment = await ownAttendance(owner, participant);
    displayState(comment);
    if (!!comment === pending.register) {
      $('submission-status').textContent = pending.register ? 'Registration confirmed.' : 'Unregistration confirmed.';
      pending = null;
      $('check-status').hidden = true;
    } else {
      $('submission-status').textContent = 'The requested change is not yet confirmed. Use Check participation status; do not send another request.';
    }
  }

  async function checkStatus() {
    if (busy || !pending) return;
    busy = true;
    controls();
    showError();
    try { await verifyPending(); }
    catch (error) { showError(message(error)); }
    finally { busy = false; controls(); }
  }

  $('talk-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || pending || !owner || !meeting || !accepting || !action()) return;
    showError();
    try { if (readToken() !== token || !participant) throw problem('Check your credentials before submitting.'); }
    catch (error) { showError(message(error)); return; }
    const desired = action() === 'register';
    $('submission-status').textContent = 'Updating participation…';
    busy = true;
    controls();
    let writing = false;
    let written = false;
    try {
      // Recheck current private state immediately before a mutation.
      await currentIssue();
      directoryData = await memberAPI.directory(token);
      const currentPerson = memberAPI.resolve(directoryData, participant.credential_fingerprint);
      if (currentPerson.member_id !== participant.member_id) throw problem('The participant association changed. Check credentials again.');
      personName = currentPerson.name;
      const comment = await ownAttendance(owner, participant);
      pending = {owner: owner.id, member_id: participant.member_id, fingerprint: participant.credential_fingerprint, register: desired};
      if (desired && !comment) {
        writing = true;
        await api(issuePath() + '/comments', 'POST', {body: memberAPI.attendanceBody(ident, {...participant, name: personName})});
      } else if (!desired && comment) {
        writing = true;
        await api(memberAPI.repo + '/issues/comments/' + comment.id, 'DELETE');
      }
      written = writing;
      await verifyPending();
    } catch (error) {
      // Never blindly repeat a mutation after a lost response. Status checks
      // perform reads only, and registration/removal are explicit desired states.
      if (!writing || (!written && [401, 403, 410, 422, 429].includes(error.httpStatus))) pending = null;
      if (pending) $('submission-status').textContent = 'The response was interrupted. Check participation status to confirm the result.';
      else $('submission-status').textContent = 'The participation change was not confirmed.';
      showError(message(error));
      if (error.httpStatus === 401) resetIdentity();
      if (error.httpStatus === 403 && owner) {
        try {
          await currentIssue(false);
          if (!accepting) showError('This meeting is closed for participation changes.');
        } catch { /* Retain the original safe failure if state cannot be read. */ }
      }
    } finally {
      busy = false;
      $('check-status').hidden = !pending;
      controls();
    }
  });

  async function loadMeeting() {
    meeting = null;
    accepting = false;
    resetIdentity();
    $('participation-fields').disabled = true;
    $('credential-fields').disabled = true;
    $('retry-meetings').hidden = true;
    $('form-status').textContent = 'Loading meeting information…';
    try {
      if (!/^(?:demo-001|meeting-[1-9][0-9]*)$/.test(ident || '')) throw problem('Open a meeting and choose Participation.');
      const available = await memberAPI.meetings();
      const context = available.get(ident);
      if (!context || context.status !== 'active' || !context.registration) throw problem('This meeting is unavailable or closed for participation changes.');
      meeting = context;
      accepting = true;
      $('meeting-name').textContent = context.name;
      $('form-status').textContent = '';
      $('participation-fields').disabled = false;
      $('credential-fields').disabled = false;
      $('meeting-link').href = 'meetings/' + ident + '/';
      $('meeting-link').hidden = false;
    } catch (error) {
      $('meeting-name').textContent = 'Unavailable';
      $('form-status').textContent = error.safe ? error.message : 'Meeting information could not be loaded. Click Retry loading to try again.';
      $('retry-meetings').hidden = false;
    } finally { controls(); }
  }

  $('check-token').addEventListener('click', checkToken);
  $('check-status').addEventListener('click', checkStatus);
  $('retry-meetings').addEventListener('click', () => { showError(); loadMeeting(); });
  for (const radio of document.querySelectorAll('input[name="participation"]')) radio.addEventListener('change', controls);
  tokenField.addEventListener('input', resetIdentity);
  window.addEventListener('pagehide', () => { tokenField.value = ''; resetIdentity(); });
  loadMeeting();
})();
