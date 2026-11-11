/* Only the PAT owner's +1 on the canonical registration opening post is changed. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const ident = new URLSearchParams(location.search).get('meeting');
  const tokenField = $('github-token');
  let meeting = null;
  let accepting = false;
  let token = '';
  let owner = null;
  let busy = false;
  let pending = null;

  function problem(message) { const error = new Error(message); error.safe = true; return error; }
  function showError(message = '') { $('form-error').textContent = message; $('form-error').hidden = !message; }
  function message(error) { return error.httpStatus || error.safe ? error.message : 'GitHub could not be reached. Check status before trying again.'; }
  function action() { return document.querySelector('input[name="participation"]:checked')?.value; }
  function controls() {
    $('submit-participation').disabled = busy || !!pending || !owner || !accepting || !action();
    $('check-token').disabled = busy;
    $('clear-token').disabled = busy;
    $('check-status').disabled = busy || !owner;
    tokenField.disabled = busy;
    for (const radio of document.querySelectorAll('input[name="participation"]')) radio.disabled = busy;
  }
  function resetIdentity() {
    token = '';
    owner = null;
    $('identity').textContent = '';
    $('participation-status').textContent = 'Check your token to see your current participation status.';
    controls();
  }
  function readToken() {
    const value = tokenField.value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw problem('Enter your personal access token on one line without spaces.');
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

  async function ownReaction(user, credential = token) {
    let found = null;
    for (let page = 1; page <= 100; page++) {
      const batch = await api(issuePath() + '/reactions?content=%2B1&per_page=100&page=' + page, 'GET', undefined, credential);
      if (!Array.isArray(batch)) throw problem('GitHub did not return participation status.');
      for (const reaction of batch) {
        if (reaction.content !== '+1' || reaction.user?.id !== user.id) continue;
        if (found || !Number.isSafeInteger(reaction.id) || reaction.id < 1) throw problem('The participation record needs organizer review.');
        found = reaction;
      }
      if (batch.length < 100) return found;
    }
    throw problem('There are too many participation records to check. Contact the organizer.');
  }

  function displayState(reaction) {
    $('participation-status').textContent = reaction ? 'You are currently registered.' : 'You are currently not registered.';
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
      const user = await memberAPI.authenticate(candidate);
      if (!Number.isSafeInteger(user.id) || user.id < 1) throw problem('GitHub did not identify the token owner.');
      if (pending && pending.owner !== user.id) throw problem('Use the original account to confirm the pending participation change.');
      await currentIssue(!pending, candidate);
      const reaction = await ownReaction(user, candidate);
      if (tokenField.value.trim() !== candidate) throw problem('The token changed. Check it again.');
      token = candidate;
      owner = user;
      $('identity').textContent = 'Submitting as ' + user.login + '. Check that this is your account.';
      displayState(reaction);
    } catch (error) { showError(message(error)); }
    finally { busy = false; controls(); }
  }

  async function verifyPending() {
    if (!owner || readToken() !== token || owner.id !== pending.owner) throw problem('Check the original account\'s token before checking status.');
    await currentIssue(false);
    const reaction = await ownReaction(owner);
    displayState(reaction);
    if (!!reaction === pending.register) {
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
    try { if (readToken() !== token) throw problem('Check your token before submitting.'); }
    catch (error) { showError(message(error)); return; }
    const desired = action() === 'register';
    busy = true;
    controls();
    let writing = false;
    let written = false;
    try {
      // Recheck current private state immediately before a mutation.
      await currentIssue();
      const reaction = await ownReaction(owner);
      pending = {owner: owner.id, register: desired};
      if (desired && !reaction) {
        writing = true;
        await api(issuePath() + '/reactions', 'POST', {content: '+1'});
      } else if (!desired && reaction) {
        writing = true;
        await api(issuePath() + '/reactions/' + reaction.id, 'DELETE');
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
  $('clear-token').addEventListener('click', () => {
    tokenField.value = '';
    resetIdentity();
    $('identity').textContent = 'Token cleared from this page. Saved password-manager entries are managed by your browser.';
  });
  window.addEventListener('pagehide', () => { tokenField.value = ''; resetIdentity(); });
  loadMeeting();
})();
