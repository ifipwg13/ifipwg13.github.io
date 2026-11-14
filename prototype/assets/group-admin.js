/* Unicode public lists; private requests, one checked Admin password per session. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const fields = {current_chairs:'current-chairs', past_chairs:'past-chairs', members:'members', emeriti:'emeriti'};
  const MARKER = '<!-- wg13-group-profile-update -->', STATUS = '<!-- wg13-group-profile-status ';
  const CONTROL = '<!-- wg13-group-administration -->';
  let credential='', account=null, loaded=null, controller=null, pending=null, busy=false, timer=null, polls=0;
  const problem = message => Object.assign(new Error(message),{safe:true});
  function error(message='') { $('form-error').textContent=message; $('form-error').hidden=!message; }
  function safe(failure) { return failure.safe || failure.httpStatus ? failure.message : 'The service could not be reached. Check progress before retrying.'; }
  function password() {
    const value=$('admin-token').value.trim();
    if (!value || !/^[\x21-\x7e]+$/.test(value)) throw problem('Enter the administrator password without spaces.');
    return value;
  }
  function checked() {
    if (!account || !credential || password()!==credential || pending && account.login!==pending.login) throw problem('Check the original administrator credentials before continuing.');
  }
  function api(path,method='GET',body) { checked(); return memberAPI.request(path,method,body,credential); }
  function controls() {
    $('admin-token').readOnly=busy;
    $('check-admin').disabled=busy;
    $('people-fields').disabled=busy || !account || !loaded || !!pending;
    $('save-people').disabled=busy || !account || !loaded || !controller || !!pending;
    $('reload-people').disabled=busy || !account || !!pending && !pending.complete;
    $('check-status').hidden=!pending;
    $('check-status').disabled=busy || !account;
  }
  function reset() { credential=''; account=null; clearTimeout(timer); $('admin-identity').textContent=''; controls(); }
  async function verify() {
    const candidate=password(), user=await memberAPI.administrator(candidate);
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
      return {revision,version,people};
    } catch { throw problem('Home lists could not be loaded. Use Reload lists; saving is disabled until all four lists are available.'); }
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
    loaded=null; controls();
    const snapshot=await homeLists();
    const number=await controlRecord();
    checked();
    for (const [key,id] of Object.entries(fields)) $(id).value=snapshot.people[key].join('\n');
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
    if (new TextEncoder().encode(JSON.stringify(people)).length>50000 || new TextEncoder().encode(JSON.stringify({schema_version:1,version:loaded.version+1,...people},null,2)+'\n').length>60000) throw problem('The name lists are too large; shorten them before saving.');
    return people;
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
      pending.complete=true; clearTimeout(timer); $('submission-status').textContent='Home lists updated. Refresh Home to see the changes.';
    } else if (latest?.state==='conflict') {
      pending.complete=true; clearTimeout(timer); $('submission-status').textContent='The lists changed elsewhere. Reload lists before editing again; your request did not replace the newer lists.';
    } else if (latest?.state==='needs-attention') {
      pending.complete=true; clearTimeout(timer); $('submission-status').textContent='The update needs administrator attention. Its publication is not confirmed. Check progress or reload the current lists before retrying.';
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
  $('talk-form').addEventListener('submit',async event=>{
    event.preventDefault(); if (busy || pending || !loaded || !account) return;
    error(); busy=true; controls();
    try {
      checked(); const people=collect();
      if (JSON.stringify(people)===JSON.stringify(loaded.people)) { $('submission-status').textContent='No list changes to save.'; return; }
      await verify();
      if (await controlRecord()!==controller) throw problem('The administration record changed. Reload lists.');
      const id=crypto.randomUUID();
      const body=MARKER+'\n```json\n'+JSON.stringify({schema_version:1,request_id:id,base_revision:loaded.revision,base_version:loaded.version,people})+'\n```';
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
  $('check-status').addEventListener('click',checkProgress);
  $('reload-people').addEventListener('click',async()=>{
    if (busy || pending && !pending.complete) return;
    busy=true; controls(); error();
    try { await verify(); await load(); } catch (failure) { loaded=null; error(safe(failure)); }
    finally { busy=false; controls(); }
  });
  for (const event of ['input','change']) $('admin-token').addEventListener(event,reset);
  addEventListener('pagehide',()=>{
    reset(); $('admin-token').value=''; loaded=null; pending=null;
    for (const id of Object.values(fields)) $(id).value='';
  });
  $('form-status').textContent='Check administrator credentials to load the current Home lists.';
  controls();
})();
