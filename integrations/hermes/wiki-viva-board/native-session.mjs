/** Native session glue only: no tool dispatcher, model loop or provider reader. */
export function createNativeSessionAccess({host, native, live, activity=()=>{}}) {
  const leases = new Map();
  const retaining = new Map();
  let closed = false;
  const watched=new Map();
  const outcome = payload => {
    let result=payload?.result;
    if(typeof result==='string'){try{result=JSON.parse(result);}catch{return 'unknown';}}
    if(result && typeof result==='object' && (result.success===false || result.isError===true || Boolean(result.error)))return 'reported_failure';
    return 'unknown'; // A generic completion cannot certify provider/resource success.
  };
  const validId = value => typeof value === 'string' && /^[\w:.-]{1,200}$/.test(value);
  const request = (route, method, params) => host.requestProfile(route, method, params, 30000, {spawnPriority:'foreground'});
  const publicRow = row => {
    const {prompt, request_sha256, ...result} = row;
    return {...result, status:result.status === 'submitted' ? 'pending' : result.status,
      identity:{status:'unknown'}, read_verified:false, write_verified:false, grants_verified:false};
  };
  const assertOpen = () => { if (closed) throw new Error('source_host_closed'); };
  async function retain(route) {
    assertOpen();
    const key = JSON.stringify([route.connectionId, route.profile, route.targetProfile]);
    if (!leases.has(key) && !retaining.has(key)) {
      const pending=(async()=>{
      if (closed || typeof host.retainProfile !== 'function' || typeof host.onEvent !== 'function') throw new Error('executor_unavailable');
      const release = await host.retainProfile(route, {spawnPriority:'foreground'});
      if (closed) { release(); throw new Error('source_host_closed'); }
      const state = {release, sessions:new Set(), events:new Map(), journal:new Map(), off:null};
      state.off = host.onEvent('*', event => {
        if (closed) return;
        // Never accept ambient events from another connection/profile. Live events
        // are hints only; terminal tracking always rechecks native history below.
        if (event.connectionId !== route.connectionId || event.profile !== route.profile || !state.sessions.has(event.session_id)) return;
        if (!Number.isSafeInteger(event.seq) || event.seq < 1) return;
        state.events.set(event.session_id, Math.max(state.events.get(event.session_id) || 0, event.seq));
        const entry={session_id:event.session_id,type:event.type,seq:event.seq};
        if(event.type==='tool.complete')entry.payload={tool_id:event.payload?.tool_id,name:event.payload?.name,outcome:event.payload?.outcome || outcome(event.payload)};
        if(event.type==='message.complete')entry.payload={persisted_turn:event.payload?.persisted_turn};
        const journal=state.journal.get(event.session_id) || [];journal.push(entry);if(journal.length>2048)journal.shift();state.journal.set(event.session_id,journal);
        for(const watch of watched.values())if(watch.row.runtime_session_id===event.session_id){
          if(['tool.start','tool.complete','message.complete','request','connection.request'].includes(event.type))activity(route,watch.ref);
          if(event.type==='message.complete' && !watch.busy){
            watch.busy=true;
            void reconcile(route,watch.ref,watch.row,watch.token).then(result=>{
              if(['native_trace_observed','native_trace_failed'].includes(result.status)){watched.delete(watch.row.request_id);activity(route,watch.ref);}
            }).catch(()=>{}).finally(()=>{watch.busy=false;});
          }
        }
        if (state.events.size > 128) state.events.delete(state.events.keys().next().value);
      });
      leases.set(key, state);
      })();
      retaining.set(key,pending);
    }
    try {await retaining.get(key);} finally {retaining.delete(key);}
    return leases.get(key);
  }
  async function resume(route, execution) {
    const lease=await retain(route); assertOpen();
    // A new source test mounts the acknowledged canonical tip lazily. Unlike a
    // cold/eager resume this does not auto-continue an unrelated interrupted
    // human turn. Native prompt.submit owns any later agent/tool hydration.
    const value = await request(route, 'session.resume', {session_id:execution.stored_session_id, omit_messages:true, inline_images:false,
      ...(execution.method==='profile_bot'?{lazy:true}:{})});
    assertOpen();
    if (!validId(value?.session_id) || ![value.stored_session_id, value.resumed, value.session_key].includes(execution.stored_session_id)) throw new Error('native_session_mismatch');
    lease.sessions.add(value.session_id);
    return value;
  }
  const track = (route, ref, row, tracking) => native(route, 'source-intent-track', 'POST', {...ref, request_id:row.request_id, tracking});
  const ownerExecution = row => {
    if(row.execution.method!=='profile_bot')return row.execution;
    if(!validId(row.owner_stored_session_id))throw new Error('native_owner_unresolved');
    return {...row.execution,stored_session_id:row.owner_stored_session_id};
  };
  async function canonicalOwner(route) {
    const result=await request(route,'session.list',{title:'Bot Chat'});
    const rows=result?.sessions;
    if(!Array.isArray(rows) || rows.length!==1 || rows[0].title!=='Bot Chat' || !validId(rows[0].id))throw new Error('native_bot_context_unavailable');
    return rows[0];
  }
  async function assertBotIdle(route, storedId, resolvedId=storedId) {
    const result=await request(route,'session.active_list',{});
    if(!Array.isArray(result?.sessions))throw new Error('native_trace_unavailable');
    const live=result.sessions.filter(row=>[storedId,resolvedId].includes(row.session_key));
    if(live.some(row=>row.status!=='idle'))throw new Error('native_session_busy');
  }
  function assertIdle(session) {
    if(session.pending_approval)throw new Error('native_operation_approval_pending');
    if(session.open_requests?.length || session.pending_connection)throw new Error('native_context_waiting');
    if(session.running || session.info?.running || session.hydrating || session.queued || session.auto_continue || session.inflight ||
       session.status && session.status!=='idle')throw new Error('native_session_busy');
  }
  async function reconcile(route, ref, row, token) {
    live(token); assertOpen();
    // Recovery never performs another canonical-title lookup or adopts the
    // latest chat. A missing acknowledged owner remains unresolved.
    if(row.execution.method==='profile_bot' && !row.owner_stored_session_id)return publicRow(row);
    const session = await resume(route, ownerExecution(row)); live(token);
    const replaySession=row.runtime_session_id || session.session_id;
    const replay = await request(route, 'session.events.since', {session_id:replaySession, last_seen:row.submit_after_seq || 0}); live(token);
    if (!validId(replay.epoch) || !Number.isSafeInteger(replay.latest_seq)) throw new Error('native_trace_unavailable');
    // History is the authority for intent ownership; epoch changes/truncation
    // must never attach the new replay tail to an old source operation.
    const history = await request(route, 'session.history', {session_id:session.session_id}); live(token);
    const messages = Array.isArray(history.messages) ? history.messages : [];
    const anchors = messages.map((m,i)=>({m,i})).filter(({m})=>m.role === 'user' &&
      (m.text ?? m.content) === row.prompt && (row.user_row_id === undefined || m.row_id === row.user_row_id));
    const tracking = {runtime_session_id:replaySession, epoch:replay.epoch, last_seen:replay.latest_seq, status:row.status === 'not_submitted' ? 'not_submitted' : 'submitted'};
    if (anchors.length === 1) {
      const {m,i} = anchors[0];
      if (Number.isSafeInteger(m.row_id) && m.row_id > 0) tracking.user_row_id = m.row_id;
      const next = messages.findIndex((m,j)=>j>i && m.role === 'user');
      const turn = messages.slice(i+1,next<0 ? messages.length : next);
      const historyRefs=turn.filter(m=>m.role==='tool' && validId(m.tool_call_id) && validId(m.name))
        .map(m=>({id:m.tool_call_id,name:m.name})).slice(0,64);
      let segment=[],started=false,owned=[];
      const lease=leases.get(JSON.stringify([route.connectionId,route.profile,route.targetProfile]));
      const journal=lease?.journal.get(replaySession) || [];
      const events=[...new Map([...(replay.events || []),...journal].map(event=>[event.seq,event])).values()].sort((a,b)=>a.seq-b.seq);
      if (row.epoch===replay.epoch && (!replay.truncated || journal.some(event=>event.type==='message.start'))) {
        for (const event of events) {
          if(event.session_id!==replaySession || !Number.isSafeInteger(event.seq))continue;
          if(event.type==='message.start'){segment=[];started=true;}
          if(started && event.type==='tool.complete' && validId(event.payload?.tool_id) && validId(event.payload?.name))segment.push({id:event.payload.tool_id,name:event.payload.name,outcome:event.payload?.outcome || outcome(event.payload)});
          const persisted=event.payload?.persisted_turn;
          if(started && event.type==='message.complete' && persisted?.complete===true && persisted.user_row_id===m.row_id){owned=segment;break;}
        }
      }
      const refs=historyRefs.map(ref=>owned.find(event=>event.id===ref.id && event.name===ref.name)).filter(Boolean);
      const completed = !session.running && !session.hydrating && refs.length>0;
      if (completed) {tracking.status=refs.some(ref=>ref.outcome==='reported_failure')?'native_trace_failed':'native_trace_observed';tracking.tool_refs=refs;}
    }
    const result = await track(route, ref, row, tracking); live(token);
    return publicRow(result);
  }
  return {
    async inspect(route,execution) {
      const session=await resume(route,execution);
      const result=await request(route,'tools.list',{session_id:session.session_id});
      return (result.toolsets || []).map(row=>({name:row.name,enabled:row.enabled,tools:row.tools || []}));
    },
    async read(route, ref, requestId, token) {
      // Exclusive durable claim happens BEFORE any native prompt submission.
      live(token); assertOpen();
      const claim = await native(route, 'source-intent-claim', 'POST', {...ref,request_id:requestId});
      const row = claim.intent;
      if (!claim.created) {
        live(token); assertOpen();
        return ['native_trace_observed','native_trace_failed','not_submitted'].includes(row.status)?publicRow(row):reconcile(route,ref,row,token);
      }
      let submitted = false;
      try {
        live(token); assertOpen();
        if(row.execution.method==='profile_bot' && !row.owner_stored_session_id) {
          await retain(route);live(token);
          const owner=await canonicalOwner(route);live(token);
          const stored=owner.resolved_id || owner.id;
          if(!validId(stored))throw new Error('native_owner_unresolved');
          await assertBotIdle(route,owner.id,stored);live(token);
          const pinned=await track(route,ref,row,{owner_stored_session_id:stored,status:'pending'});live(token);
          if(pinned.owner_stored_session_id!==stored)throw new Error('native_owner_unresolved');
          row.owner_stored_session_id=stored;
        }
        const execution=ownerExecution(row);
        const session = await resume(route,execution); live(token);
        assertIdle(session);
        if(row.execution.method==='profile_bot' && session.running!==false && session.status!=='idle')throw new Error('native_trace_unavailable');
        const replay = await request(route,'session.events.since',{session_id:session.session_id,last_seen:0}); live(token);
        if (!validId(replay.epoch) || !Number.isSafeInteger(replay.latest_seq)) throw new Error('native_trace_unavailable');
        if(replay.open_requests?.length)throw new Error('native_context_waiting');
        Object.assign(row,{runtime_session_id:session.session_id,epoch:replay.epoch,last_seen:replay.latest_seq,submit_after_seq:replay.latest_seq});
        await track(route,ref,row,{runtime_session_id:session.session_id,epoch:replay.epoch,last_seen:replay.latest_seq,submit_after_seq:replay.latest_seq,status:'pending'}); live(token);
        // Recheck the canonical owner/config after all preflight awaits. Tracking
        // deliberately accepts old receipts for recovery; it is not dispatch authority.
        const binding=await native(route,'source-binding/'+encodeURIComponent(ref.source_id)+'?binding_sha256='+ref.binding_sha256); live(token); assertOpen();
        if(binding.source_id!==ref.source_id || binding.binding_sha256!==ref.binding_sha256)throw new Error('source_binding_changed');
        if(binding.config_sha256!==ref.config_sha256)throw new Error('source_configuration_changed');
        if(binding.execution_hold)throw new Error(binding.execution_hold);
        if(row.execution.method==='profile_bot') {await assertBotIdle(route,execution.stored_session_id,session.session_id);live(token);}
        watched.set(row.request_id,{ref,row,token,busy:false});
        submitted = true; // From this boundary a timeout is UNKNOWN, never a retry.
        const ack = await request(route,'prompt.submit',{session_id:session.session_id,text:row.prompt,queued:true});
        live(token);
        const tracking={runtime_session_id:session.session_id,status:'submitted',native_submission_status:ack?.status==='queued'?'queued':'submitted'};
        if (Number.isSafeInteger(ack?.user_row_id) && ack.user_row_id > 0) {tracking.user_row_id=ack.user_row_id;row.user_row_id=ack.user_row_id;}
        const result=await track(route,ref,row,tracking);live(token);
        return publicRow(result);
      } catch (error) {
        if (!submitted) await track(route,ref,row,{status:'not_submitted'}).catch(()=>{});
        if (submitted) throw new Error('source_read_result_unknown');
        throw error;
      }
    },
    async receipts(route,ref,token,hold='') {
      const result=await native(route,'source-read-receipts','POST',ref);live(token);
      const rows=[];
      for (const row of result.receipts || []) {
        if (hold || ['not_submitted','native_trace_observed','native_trace_failed'].includes(row.status)) rows.push(publicRow(row));
        else {
          if(row.execution.connection_id!==route.connectionId || row.execution.profile!==route.profile || row.execution.target_profile!==route.targetProfile)throw new Error('executor_profile_mismatch');
          rows.push(await reconcile(route,{source_id:row.source_id,binding_sha256:row.binding_sha256,config_sha256:row.config_sha256},row,token));
        }
      }
      return {receipts:rows,...(hold?{execution_hold:hold}:{}),...(rows.find(row=>['pending','submitted'].includes(row.status))?{unresolved_request:rows.find(row=>['pending','submitted'].includes(row.status)).request_id}:{})};
    },
    async open(route,execution,ref,token) {
      if (typeof host.openSession !== 'function') throw new Error('executor_unavailable');
      let stored=execution.stored_session_id;
      if(execution.method==='profile_bot') {
        const result=await native(route,'source-read-receipts','POST',ref);live(token);
        const pending=(result.receipts || []).find(row=>['pending','submitted'].includes(row.status));
        if(pending) {
          if(pending.execution.connection_id!==route.connectionId || pending.execution.profile!==route.profile || pending.execution.target_profile!==route.targetProfile)throw new Error('executor_profile_mismatch');
          stored=ownerExecution(pending).stored_session_id;
        } else {stored=(await canonicalOwner(route)).id;live(token);}
      }
      await host.openSession(stored,{route,awaitHydration:true,forceResume:true});
      return {status:'native_session_opened'};
    },
    dispose() {closed=true;watched.clear();for(const state of leases.values()){state.off();state.release();}leases.clear();}
  };
}
