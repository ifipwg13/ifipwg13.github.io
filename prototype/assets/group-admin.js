/* Public Home text/lists; private requests, one checked Admin password per session. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fields = {current_chairs:'current-chairs', past_chairs:'past-chairs', members:'members', emeriti:'emeriti'};
  const texts = {aims:'aims', scope:'scope'};
  const MARKER = '<!-- wg13-group-profile-update -->', STATUS = '<!-- wg13-group-profile-status ';
  const CONTROL = '<!-- wg13-group-administration -->';
  let credential='', account=null, loaded=null, controller=null, pending=null, busy=false, timer=null, polls=0;
  const BACKUP='<!-- wg13-backup-request -->', BACKUP_STATUS='<!-- wg13-backup-status ';
  const BACKUP_DOWNLOAD='https://github.com/ifipwg13/meetings/releases/download/website-backup/website-backup.zip';
  let backupPending=null, backupTimer=null, backupPolls=0;
  const problem = message => Object.assign(new Error(message),{safe:true});
  function error(message='') { $('form-error').textContent=message; $('form-error').hidden=!message; }
  function safe(failure) { return failure.safe || failure.httpStatus ? failure.message : 'The service could not be reached. Check progress before retrying.'; }
  function password() {
    const value=$('admin-token').value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw problem('Enter the administrator password without spaces.');
    return value;
  }
  function checked() {
    if (!account || !credential || password()!==credential || pending && account.login!==pending.login) {
      reset(); throw problem('Check the original administrator credentials before continuing.');
    }
  }
  async function api(path,method='GET',body) {
    checked();
    try { return await memberAPI.request(path,method,body,credential); }
    catch (failure) { if ([401,403].includes(failure.httpStatus)) reset(); throw failure; }
  }
  function controls() {
    const backing=!!backupPending && !backupPending.complete;
    $('admin-token').readOnly=busy;
    $('check-admin').disabled=busy;
    $('people-fields').hidden=!account || !loaded;
    $('people-fields').disabled=busy || !account || !loaded || !!pending || backing;
    $('save-people').hidden=!account;
    $('reload-people').hidden=!account;
    $('save-people').disabled=busy || !account || !loaded || !controller || !!pending || backing;
    $('reload-people').disabled=busy || !account || !!pending && !pending.complete || backing;
    $('backup-site').hidden=!account;
    $('backup-site').disabled=busy || !account || !loaded || !controller || !!pending && !pending.complete || backing || unsavedHome();
    $('check-status').hidden=!pending && !backupPending;
    $('check-status').disabled=busy || !account;
  }
  function resetBackup() {
    clearTimeout(backupTimer); backupPending=null; backupPolls=0;
    $('backup-status').textContent=''; $('backup-download').hidden=true; $('backup-download').removeAttribute('href');
  }
  function reset() { credential=''; account=null; clearTimeout(timer); resetBackup(); $('admin-identity').textContent=''; controls(); }
  function unsavedHome() {
    if (!loaded) return false;
    if (pending?.complete) return pending.result!=='published';
    try { return JSON.stringify(collect())!==JSON.stringify({people:loaded.people,content:loaded.content}); }
    catch { return true; }
  }
  async function verify() {
    const candidate=password();
    let user;
    try { user=await memberAPI.administrator(candidate); }
    catch (failure) { reset(); throw failure; }
    if (password()!==candidate || pending && user.login!==pending.login) throw problem('Check the original administrator credentials before continuing.');
    credential=candidate; account=user; $('admin-identity').textContent='Administrator access confirmed.';
  }
  async function homeLists() {
    const abort=new AbortController(), timeout=setTimeout(()=>abort.abort(),15000);
    try {
      const response=await fetch('../index.html',{cache:'no-store',credentials:'same-origin',signal:abort.signal});
      if (!response.ok) throw new Error();
      const doc=new DOMParser().parseFromString(await response.text(),'text/html');
      const revisions=doc.querySelectorAll('meta[name="group-people-revision"]'), versions=doc.querySelectorAll('meta[name="group-people-version"]');
      const revision=revisions[0]?.content, version=Number(versions[0]?.content);
      if (revisions.length!==1 || versions.length!==1 || !/^[a-f0-9]{64}$/.test(revision || '') || !Number.isSafeInteger(version) || version<1 || version>=999999999) throw new Error();
      const people={};
      for (const key of Object.keys(fields)) {
        const lists=doc.querySelectorAll('ul[data-group-list="'+key+'"]');
        if (lists.length!==1 || Array.from(lists[0].children).some(child=>child.tagName!=='LI' || child.children.length)) throw new Error();
        people[key]=Array.from(lists[0].children, item=>item.textContent);
      }
      const content={};
      for (const key of Object.keys(texts)) {
        const paragraphs=doc.querySelectorAll('p[data-group-text="'+key+'"]');
        if (paragraphs.length!==1 || paragraphs[0].children.length) throw new Error();
        content[key]=paragraphs[0].textContent;
      }
      return {revision,version,people,content};
    } catch { throw problem('Home content could not be loaded. Use Reload content; saving is disabled until all six fields are available.'); }
    finally { clearTimeout(timeout); }
  }
  async function controlRecord() {
    const found=[];
    for (let page=1;page<=100;page++) {
      const batch=await api(memberAPI.repo+'/issues?state=open&labels=group-administration&per_page=100&page='+page);
      if (!Array.isArray(batch)) throw new Error();
      for (const issue of batch) {
        if (!issue.pull_request && !issue.locked && (issue.body || '').startsWith(CONTROL)) found.push(issue);
      }
      if (batch.length<100) break;
      if (page===100) throw new Error();
    }
    if (found.length!==1 || !Number.isSafeInteger(found[0].number) || found[0].number<1) throw problem('The administration record is unavailable or ambiguous. Contact the organizer.');
    return found[0].number;
  }
  async function load() {
    resetBackup();
    loaded=null; controls();
    const snapshot=await homeLists();
    const number=await controlRecord();
    checked();
    for (const [key,id] of Object.entries(fields)) $(id).value=snapshot.people[key].join('\n');
    for (const [key,id] of Object.entries(texts)) $(id).value=snapshot.content[key];
    loaded=snapshot; controller=number; pending=null; polls=0; clearTimeout(timer);
    $('submission-status').textContent=''; $('form-status').textContent='';
  }
  async function checkAccess() {
    if (busy) return;
    error(); reset(); busy=true; controls();
    try { await verify(); if (!pending) await load(); }
    catch (failure) {
      loaded=null;
      if (!account || [401,403].includes(failure.httpStatus) || $('admin-token').value.trim()!==credential) reset();
      error(safe(failure));
    }
    finally { busy=false; controls(); }
  }
  function collect() {
    const people={};
    for (const [key,id] of Object.entries(fields)) {
      const entries=$(id).value.replace(/\r\n?/g,'\n').split('\n').map(line=>line.normalize('NFC').trim()).filter(Boolean);
      if (entries.length>500) throw problem('Use at most 500 entries in each list.');
      for (const name of entries) {
        if (Array.from(name).length>200 || /[\x00-\x1f\x7f-\x9f\u2028\u2029]/.test(name)) throw problem('Use names on one line, at most 200 characters each.');
        if (name.includes(credential) || /(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+/.test(name)) throw problem('Enter names only; never put a password in a list.');
        if (/[\ud800-\udfff]/u.test(name)) throw problem('Use valid Unicode text in the name lists.');
      }
      people[key]=entries;
    }
    const content={};
    for (const [key,id] of Object.entries(texts)) {
      const text=$(id).value.replace(/\r\n?/g,'\n').normalize('NFC').trim();
      if (Array.from(text).length>10000 || /[\x00-\x08\x0b-\x1f\x7f-\x9f\u2028\u2029]/.test(text) || /[\ud800-\udfff]/u.test(text)) throw problem('Use plain text for Aims and Scope, at most 10,000 characters each.');
      if (text.includes(credential) || /(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+/.test(text)) throw problem('Never put a password in Home content.');
      content[key]=text;
    }
    if (new TextEncoder().encode(JSON.stringify(people)).length>50000 || new TextEncoder().encode(JSON.stringify({schema_version:2,version:loaded.version+1,...people,...content},null,2)+'\n').length>60000) throw problem('The Home content is too large; shorten it before saving.');
    return {people,content};
  }
  async function progress() {
    checked(); const comments=[];
    for (let page=1;page<=100;page++) {
      const batch=await api(memberAPI.repo+'/issues/'+controller+'/comments?per_page=100&page='+page);
      if (!Array.isArray(batch)) throw new Error(); comments.push(...batch);
      if (batch.length<100) break;
      if (page===100) throw new Error();
    }
    const matching=comments.filter(item=>item.user?.login===pending.login && item.body===pending.body);
    if (matching.length>1) throw problem('Duplicate update records were found. Contact the organizer.');
    if (!pending.commentId && matching.length===1) pending.commentId=matching[0].id;
    let latest=null;
    for (const comment of comments) {
      if (!memberAPI.bot(comment) || !(comment.body || '').startsWith(STATUS)) continue;
      try {
        const value=JSON.parse(comment.body.slice(STATUS.length,comment.body.indexOf(' -->')));
        if (value.schema_version===1 && value.request_id===pending.id && value.comment_id===pending.commentId && value.request_hash===pending.hash) latest=value;
      } catch { /* Other comments and identities cannot confirm an update. */ }
    }
    if (latest?.state==='published' && /^[a-f0-9]{40}$/.test(latest.revision)) {
      pending.complete=true; pending.result='published'; clearTimeout(timer); $('submission-status').textContent='Home saved. The website update may take a few minutes; then refresh Home.';
    } else if (latest?.state==='conflict') {
      pending.complete=true; pending.result='conflict'; clearTimeout(timer); $('submission-status').textContent='Home changed elsewhere. Reload content before editing again; your request did not replace the newer content.';
    } else if (latest?.state==='needs-attention') {
      pending.complete=true; pending.result='needs-attention'; clearTimeout(timer); $('submission-status').textContent='The update needs administrator attention. Its publication is not confirmed. Check progress or reload the current content before retrying.';
    } else {
      $('submission-status').textContent='Update submitted. Waiting for synchronization. Use Check progress if this takes longer.';
      if (++polls<12) timer=setTimeout(checkProgress,5000);
    }
  }
  async function checkProgress() {
    if (busy || !pending) return;
    clearTimeout(timer); busy=true; controls(); error();
    try { await progress(); } catch (failure) { error(safe(failure)); }
    finally { busy=false; controls(); }
  }
  async function backupProgress() {
    checked();
    const comments=[];
    for (let page=1;page<=100;page++) {
      const batch=await api(memberAPI.repo+'/issues/'+controller+'/comments?per_page=100&page='+page);
      if (!Array.isArray(batch)) throw new Error();
      comments.push(...batch);
      if (batch.length<100) break;
      if (page===100) throw problem('Too many records to check safely. Contact the organizer.');
    }
    const matching=comments.filter(c=>c.user?.login===backupPending.login && c.body===backupPending.body);
    if (matching.length>1) throw problem('Duplicate backup requests need administrator review.');
    if (!backupPending.commentId && matching.length===1) backupPending.commentId=matching[0].id;
    let latest=null;
    for (const comment of comments) {
      if (!memberAPI.bot(comment) || !(comment.body || '').startsWith(BACKUP_STATUS)) continue;
      try {
        const value=JSON.parse(comment.body.slice(BACKUP_STATUS.length,comment.body.indexOf(' -->')));
        if (value.schema_version===1 && value.request_id===backupPending.id &&
            value.comment_id===backupPending.commentId && value.request_hash===backupPending.hash) latest=value;
      } catch { /* Unrelated text cannot confirm a backup or supply a download URL. */ }
    }
    checked();
    if (latest?.state==='ready' && latest.download_url===BACKUP_DOWNLOAD &&
        /^[a-f0-9]{64}$/.test(latest.sha256 || '') && Number.isSafeInteger(latest.asset_id) && latest.asset_id>0 &&
        Number.isSafeInteger(latest.size) && latest.size>0 && latest.size<2*1024**3) {
      backupPending.complete=true; clearTimeout(backupTimer);
      $('backup-status').textContent='Backup ready ('+(latest.size/1_000_000).toFixed(1)+' MB).';
      $('backup-download').href=BACKUP_DOWNLOAD; $('backup-download').hidden=false;
    } else if (['failed','superseded'].includes(latest?.state)) {
      backupPending.complete=true; clearTimeout(backupTimer);
      $('backup-status').textContent=latest.state==='failed' ?
        'Backup could not be completed. Retry or contact the organizer; previous copies were retained.' :
        'A newer backup replaced this request. Create another backup to refresh the result.';
      $('backup-download').hidden=true; $('backup-download').removeAttribute('href');
    } else {
      $('backup-status').textContent='Preparing backup. Use Check progress if this takes longer.';
      if (++backupPolls<12) backupTimer=setTimeout(checkBackupProgress,5000);
    }
  }
  async function checkBackupProgress() {
    if (busy || !backupPending) return;
    clearTimeout(backupTimer); busy=true; controls(); error();
    try { await backupProgress(); } catch (failure) { error(safe(failure)); }
    finally { busy=false; controls(); }
  }
  $('backup-site').addEventListener('click',async()=>{
    if (busy || !loaded || !account || backupPending && !backupPending.complete || pending && !pending.complete) return;
    if (unsavedHome()) { $('backup-status').textContent='Save Home changes before making a backup.'; return; }
    error(); busy=true; controls();
    try {
      checked(); await verify();
      if (await controlRecord()!==controller) throw problem('The administration record changed. Reload content.');
      resetBackup();
      const id=crypto.randomUUID(), body=BACKUP+'\n```json\n'+JSON.stringify({schema_version:1,request_id:id})+'\n```';
      backupPending={id,body,hash:await memberAPI.fingerprint(body),login:account.login,commentId:null,complete:false};
      $('backup-status').textContent='Submitting backup request…';
      try {
        const result=await api(memberAPI.repo+'/issues/'+controller+'/comments','POST',{body});
        if (!Number.isSafeInteger(result.id) || result.id<1) throw new Error();
        backupPending.commentId=result.id;
      } catch (failure) {
        if (failure.safe || [400,401,403,404,410,422,429].includes(failure.httpStatus)) { backupPending=null; throw failure; }
        // Locate an uncertain POST by its UUID; never post it again blindly.
      }
      await backupProgress();
    } catch (failure) { error(safe(failure)); }
    finally { busy=false; controls(); }
  });
  for (const id of [...Object.values(fields),...Object.values(texts)]) $(id).addEventListener('input',()=>{
    controls();
    if (account && unsavedHome()) $('backup-status').textContent='Save Home changes before making a backup.';
    else if (!backupPending) $('backup-status').textContent='';
  });
  $('talk-form').addEventListener('submit',async event=>{
    event.preventDefault(); if (busy || pending || !loaded || !account) return;
    error(); busy=true; controls();
    try {
      checked(); const value=collect();
      if (JSON.stringify(value)===JSON.stringify({people:loaded.people,content:loaded.content})) { $('submission-status').textContent='No Home changes to save.'; return; }
      await verify();
      if (await controlRecord()!==controller) throw problem('The administration record changed. Reload content.');
      const id=crypto.randomUUID();
      const body=MARKER+'\n```json\n'+JSON.stringify({schema_version:2,request_id:id,base_revision:loaded.revision,base_version:loaded.version,...value})+'\n```';
      if (new TextEncoder().encode(body).length>60000) throw problem('The update request is too large.');
      pending={id,body,hash:await memberAPI.fingerprint(body),login:account.login,commentId:null,complete:false};
      $('submission-status').textContent='Submitting Home update…';
      try {
        const result=await api(memberAPI.repo+'/issues/'+controller+'/comments','POST',{body});
        if (!Number.isSafeInteger(result.id) || result.id<1) throw new Error();
        pending.commentId=result.id;
      } catch (failure) {
        if (failure.safe || [400,401,403,404,410,422,429].includes(failure.httpStatus)) { pending=null; throw failure; }
        // An uncertain POST is located by UUID/GET instead of posting twice.
      }
      await progress();
    } catch (failure) { error(safe(failure)); }
    finally { busy=false; controls(); }
  });
  $('check-admin').addEventListener('click',checkAccess);
  $('check-status').addEventListener('click',()=>backupPending ? checkBackupProgress() : checkProgress());
  $('reload-people').addEventListener('click',async()=>{
    if (busy || pending && !pending.complete) return;
    busy=true; controls(); error();
    try { await verify(); await load(); } catch (failure) { loaded=null; error(safe(failure)); }
    finally { busy=false; controls(); }
  });
  for (const event of ['input','change']) $('admin-token').addEventListener(event,reset);
  addEventListener('pagehide',()=>{
    reset(); $('admin-token').value=''; loaded=null; pending=null;
    for (const id of [...Object.values(texts),...Object.values(fields)]) $(id).value='';
  });
  $('form-status').textContent='';
  controls();
})();
