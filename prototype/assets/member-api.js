/* Shared, closure-scoped helpers. No credentials or private responses persist. */
const memberAPI = (() => {
  const repo = '/repos/ifipwg13/meetings';
  async function request(path, method = 'GET', body, credential) {
    if (path !== '/user' && path !== repo && !path.startsWith(repo + '/')) throw new Error('Unsupported request.');
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch('https://api.github.com' + path, {
        method, credentials: 'omit', cache: 'no-store', redirect: 'error',
        referrerPolicy: 'no-referrer', signal: controller.signal,
        headers: {Accept: 'application/vnd.github+json', Authorization: 'Bearer ' + credential,
          'X-GitHub-Api-Version': '2022-11-28', ...(body ? {'Content-Type': 'application/json'} : {})},
        ...(body ? {body: JSON.stringify(body)} : {}),
      });
      if (!response.ok) {
        const messages = {
          401: 'The credentials were rejected. Ask the organizer whether they have expired or been replaced.',
          403: 'The credentials do not permit this action. Contact the organizer.',
          404: 'The record is unavailable. Check your credentials or contact the organizer.',
          410: 'This private record is no longer available.',
          422: 'The request could not be accepted. Check the fields or contact the organizer.',
          429: 'Too many requests. Wait before checking again.',
        };
        const error = new Error(messages[response.status] || 'The service is temporarily unavailable. Check status before trying again.');
        error.httpStatus = response.status;
        throw error;
      }
      // Reaction deletion succeeds with no JSON body.
      return response.status === 204 ? null : await response.json();
    } finally { clearTimeout(timer); }
  }

  async function authenticate(credential) {
    const user = await request('/user', 'GET', undefined, credential);
    if (!user || typeof user.login !== 'string' || !/^[A-Za-z0-9-]+$/.test(user.login) || !Number.isSafeInteger(user.id) || user.id < 1) throw new Error('The credentials could not be verified.');
    const repository = await request(repo, 'GET', undefined, credential);
    if (repository.full_name !== 'ifipwg13/meetings' || repository.permissions?.pull === false) {
      throw new Error('The credentials do not allow access to meeting records.');
    }
    return user;
  }

  function inputError(message) { const error = new Error(message); error.safe = true; return error; }
  const directoryLabel = 'participant-directory';
  const directoryMarker = '<!-- wg13-participant-directory ';
  async function fingerprint(credential) {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(credential));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  }
  function uuid(value) { return typeof value === 'string' && /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(value); }
  function realName(value) { return typeof value === 'string' && !!value.trim() && value === value.trim() && Array.from(value).length <= 200 && !/[\x00-\x1f\x7f-\x9f\u2028\u2029]/.test(value) && !/(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+/.test(value); }
  function bot(record) { return record.user?.login === 'github-actions[bot]' && record.user?.type === 'Bot'; }
  function validateDirectory(data) {
    if (!data || Object.keys(data).sort().join(',') !== 'members,revision,schema_version' || data.schema_version !== 1 ||
        !Number.isSafeInteger(data.revision) || data.revision < 0 || !Array.isArray(data.members)) throw inputError('The participant directory needs organizer attention.');
    const ids = new Set(), prints = new Set();
    for (const member of data.members) {
      if (!member || Object.keys(member).sort().join(',') !== 'credentials,id,name' || !uuid(member.id) || ids.has(member.id) ||
          !realName(member.name) || !Array.isArray(member.credentials) || !member.credentials.length) throw inputError('The participant directory needs organizer attention.');
      ids.add(member.id);
      for (const key of member.credentials) {
        if (!key || Object.keys(key).sort().join(',') !== 'active,fingerprint' || typeof key.active !== 'boolean' ||
            typeof key.fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(key.fingerprint) || prints.has(key.fingerprint)) throw inputError('The participant directory needs organizer attention.');
        prints.add(key.fingerprint);
      }
    }
    return data;
  }
  async function directory(credential, required = true) {
    let reference;
    try { reference = await request(repo + '/labels/' + directoryLabel, 'GET', undefined, credential); }
    catch (error) {
      if (error.httpStatus === 404) {
        if (!required) return null;
        throw inputError('Participant names are not configured. Contact the organizer.');
      }
      throw error;
    }
    const match = /^wg13-directory:v1:([1-9][0-9]*)$/.exec(reference?.description || '');
    if (!match) throw inputError('The participant directory needs organizer attention.');
    const issue = await request(repo + '/issues/' + match[1], 'GET', undefined, credential);
    const labels = (issue.labels || []).map(label => typeof label === 'string' ? label : label.name);
    if (issue.number !== Number(match[1]) || !bot(issue) || issue.pull_request || issue.state !== 'closed' || !issue.locked || !labels.includes(directoryLabel)) throw inputError('The protected participant directory could not be verified.');
    const text = issue.body || '';
    if (text.length > 60000 || text.split(directoryMarker).length !== 2 || !text.endsWith(' -->')) throw inputError('The participant directory could not be read.');
    let data;
    try { data = JSON.parse(text.slice(text.indexOf(directoryMarker) + directoryMarker.length, -4)); }
    catch { throw inputError('The participant directory could not be read.'); }
    validateDirectory(data);
    const names = data.members.map(member => '- ' + markdownName(member.name) + (member.credentials.some(key => key.active) ? '' : ' (inactive)'));
    const expected = '# Participant directory\n\nManaged through Manage participants.\n\n' + names.join('\n') + '\n\n' + directoryMarker + metadata(data) + ' -->';
    if (text !== expected) throw inputError('The participant directory has independent edits. Contact the organizer.');
    return data;
  }
  function resolve(data, print, active = true) {
    for (const member of data.members) {
      const key = member.credentials.find(credential => credential.fingerprint === print);
      if (key) {
        if (active && !key.active) throw inputError('These credentials are disabled. Contact the organizer.');
        return {member_id: member.id, name: member.name, credential_fingerprint: print, active: key.active};
      }
    }
    throw inputError('These credentials have not been assigned a name. Contact the organizer.');
  }
  async function identify(credential, active = true) {
    const account = await authenticate(credential);
    const print = await fingerprint(credential);
    const names = await directory(credential);
    const person = resolve(names, print, active);
    return {account, name: person.name, participant: {member_id: person.member_id, credential_fingerprint: print}, active: person.active, names};
  }
  async function administrator(credential) {
    const account = await authenticate(credential);
    const role = await request(repo + '/collaborators/' + encodeURIComponent(account.login) + '/permission', 'GET', undefined, credential);
    if (role.permission !== 'admin') throw inputError('Participant management requires administrator access.');
    return account;
  }
  function metadata(data) {
    return JSON.stringify(data).replace(/[\u007f-\uffff]/g, character => '\\u' + character.charCodeAt(0).toString(16).padStart(4, '0'))
      .replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026');
  }
  function markdownName(value) {
    return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/[\\`*_{}\[\]()#+.!|>\-]/g, character => '\\' + character);
  }
  const attendanceMarker = '<!-- wg13-participation ';
  function attendanceBody(ident, person) {
    const data = {schema_version: 2, meeting_id: ident, member_id: person.member_id, name: person.name,
      credential_fingerprint: person.credential_fingerprint};
    return 'Yes — ' + markdownName(person.name) + '\n\n' + attendanceMarker + metadata(data) + ' -->';
  }
  function attendanceRecord(comment, ident, owner, names) {
    if (comment.user?.id !== owner.id || !Number.isSafeInteger(comment.id) || comment.id < 1) return null;
    const text = comment.body || '';
    const start = text.indexOf(attendanceMarker);
    if (start < 0 || !text.endsWith(' -->')) return null;
    try {
      const data = JSON.parse(text.slice(start + attendanceMarker.length, -4));
      if (data.meeting_id !== ident || typeof data.credential_fingerprint !== 'string' || !/^[a-f0-9]{64}$/.test(data.credential_fingerprint)) return null;
      const person = resolve(names, data.credential_fingerprint, false);
      if (data.schema_version === 1) {
        if (Object.keys(data).sort().join(',') !== 'credential_fingerprint,meeting_id,schema_version,username' ||
            typeof data.username !== 'string' || !/^[a-z0-9][a-z0-9._-]{0,63}$/.test(data.username) ||
            text !== 'Yes\n\nParticipant: ' + data.username + '\n\n' + attendanceMarker + JSON.stringify(data) + ' -->') return null;
      } else if (data.schema_version === 2) {
        if (Object.keys(data).sort().join(',') !== 'credential_fingerprint,meeting_id,member_id,name,schema_version' ||
            data.member_id !== person.member_id || !realName(data.name) ||
            text !== attendanceBody(ident, {...person, name: data.name})) return null;
      } else return null;
      return person;
    } catch { return null; }
  }

  function calendar(value) {
    let year, month, day;
    let match = /^([0-9]{4})-([0-9]{2})-([0-9]{2})$/.exec(value);
    if (match) [, year, month, day] = match;
    else {
      match = /^([0-9]{1,2})-([0-9]{1,2})-([0-9]{2}|[0-9]{4})$/.exec(value);
      if (!match) throw new Error('Enter a valid date as DD-MM-YYYY or DD-MM-YY.');
      [, day, month, year] = match;
      if (year.length === 2) year = '20' + year;
    }
    [year, month, day] = [year, month, day].map(Number);
    const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    if (year < 1 || month < 1 || month > 12 || day < 1 || day > days[month - 1]) throw new Error('Enter a valid calendar date.');
    return String(year).padStart(4, '0') + '-' + String(month).padStart(2, '0') + '-' + String(day).padStart(2, '0');
  }

  function clock(value) {
    const match = /^([0-9]{1,2}):([0-9]{2})$/.exec(value);
    if (!match || Number(match[1]) > 23 || Number(match[2]) > 59) throw new Error('Enter a time between 00:00 and 23:59, for example 09:00.');
    return match[1].padStart(2, '0') + ':' + match[2];
  }

  async function meetings() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('index.html', {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Meeting information unavailable.');
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      const found = new Map();
      for (const card of doc.querySelectorAll('article.meeting-card[data-meeting-id]')) {
        const id = card.dataset.meetingId;
        if (!/^(?:demo-001|meeting-[1-9][0-9]*)$/.test(id) || !['active', 'archived'].includes(card.dataset.meetingStatus)) continue;
        const name = card.querySelector('h3')?.textContent.trim();
        const dates = card.querySelectorAll('.meeting-summary time[datetime]');
        if (!name || !dates.length || found.has(id)) throw new Error('Meeting information is incomplete.');
        const date = calendar(dates[0].getAttribute('datetime').slice(0, 10));
        const endDate = calendar(dates[dates.length - 1].getAttribute('datetime').slice(0, 10));
        if (date > endDate) throw new Error('Meeting dates are invalid.');
        const registration = Number(card.dataset.registrationIssue);
        found.set(id, {name, date, endDate, status: card.dataset.meetingStatus,
          registration: Number.isSafeInteger(registration) && registration > 0 ? registration : null});
      }
      return found;
    } finally { clearTimeout(timer); }
  }

  return {repo, request, authenticate, identify, administrator, fingerprint, directory, resolve, metadata, uuid, realName, bot, attendanceBody, attendanceRecord, calendar, clock, meetings,
    displayDate: value => value.split('-').reverse().join('-')};
})();
