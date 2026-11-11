/* Shared, closure-scoped helpers. No credentials or private responses persist. */
const memberAPI = (() => {
  const repo = '/repos/ifipwg13/meetings';
  async function request(path, method = 'GET', body, credential) {
    if (path !== '/user' && path !== repo && !path.startsWith(repo + '/')) throw new Error('Unsupported GitHub request.');
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
          401: 'GitHub rejected the token. Check whether it has expired or been revoked.',
          403: 'GitHub denied access. Check token permissions, organization approval or SSO, and repository access.',
          404: 'The private record is unavailable to this token. Check repository access and meeting availability.',
          410: 'This private record is no longer available.',
          422: 'GitHub could not accept the request. Check its fields, permissions, and meeting availability.',
          429: 'GitHub is limiting requests. Wait before checking again.',
        };
        const error = new Error(messages[response.status] || 'GitHub is temporarily unavailable. Check status before trying again.');
        error.httpStatus = response.status;
        throw error;
      }
      // Reaction deletion succeeds with no JSON body.
      return response.status === 204 ? null : await response.json();
    } finally { clearTimeout(timer); }
  }

  async function authenticate(credential) {
    const user = await request('/user', 'GET', undefined, credential);
    if (!user || typeof user.login !== 'string' || !/^[A-Za-z0-9-]+$/.test(user.login)) throw new Error('GitHub did not identify the token owner.');
    const repository = await request(repo, 'GET', undefined, credential);
    if (repository.full_name !== 'ifipwg13/meetings' || repository.permissions?.pull === false) {
      throw new Error('The token owner needs at least Read access to the private meeting repository.');
    }
    return user;
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

  return {repo, request, authenticate, calendar, clock, meetings,
    displayDate: value => value.split('-').reverse().join('-')};
})();
