const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
function panel(fetchImpl, fastTimers = false) {
  const elements = new Map();
  const storage = new Map();
  const editors = [{ disabled: false }];
  function element(id) {
    if (!elements.has(id)) elements.set(id, { textContent: '', disabled: false, open: false,
      classList: { toggle() {} }, listeners: {}, addEventListener(name, callback) { this.listeners[name] = callback; }, setAttribute() {}, close() { this.open = false; }, showModal() { this.open = true; } });
    const node = elements.get(id);
    if (!Object.getOwnPropertyDescriptor(node, 'innerHTML')) Object.defineProperty(node, 'innerHTML', {
      get() { return this._html || ''; },
      set(value) { this._html = value; this.textContent = value.replace(/<[^>]*>/g, ''); }
    });
    return node;
  }
  const sockets = [];
  class Socket {
    static OPEN = 1; static CONNECTING = 0;
    constructor() { this.readyState = 1; this.listeners = {}; sockets.push(this); }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    close() { this.readyState = 3; this.listeners.close?.({code:1000}); }
    send() {}
  }
  const context = {
    localStorage: {getItem:k=>storage.get(k)||null, setItem:(k,v)=>storage.set(k,v), removeItem:k=>storage.delete(k)},
    document: {getElementById:element, querySelectorAll:()=>editors, visibilityState:'visible'},
    location:{href:'https://ha.example/api/hassio_ingress/abc/',protocol:'https:'},
    URL, Headers, AbortController, Date, WebSocket:Socket,
    fetch:fetchImpl || (async()=>new Response(JSON.stringify({connected:true}),{headers:{'Content-Type':'application/json'}})),
    setTimeout:fastTimers ? (fn,ms)=>setTimeout(fn,Math.min(ms,30)) : setTimeout,clearTimeout,setInterval,clearInterval,
  };
  vm.createContext(context);
  const exported = '  render = async () => {}; updateSparks = () => {}; appendOverviewTemperatureSample = () => {}; toast = () => {};\n  globalThis.panel = {state, api, fetchSnapshot, checkAuth, recoverAfterAppResume, updateLockButton, loadInitialDataWithRetry, executeWrite, schemeBurnerState, installationSchemeHtml, hysteresisSummaryHtml, editorHtml};';
  assert(source.includes('  init();'));
  vm.runInContext(source.replace('  init();', exported), context);
  context.panel.state.uiReady=true;
  context.panel.state.role='admin';
  return {...context.panel, element, editors, sockets, storage};
}
function json(body,status=200) {return new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});}

test('resume replaces stale OPEN websocket before successful HTTP can mask it', async()=>{
  const p=panel(async url=>json(String(url).endsWith('auth/status')?{unlocked:false,role:'admin'}:{connected:true}));
  p.state.websocket={readyState:1,close(){}};
  p.state.lastWebsocketAt=Date.now()-60000;
  await p.recoverAfterAppResume();
  assert.equal(p.sockets.length,1);
  assert.equal(p.state.recoveryInFlight,null);
});

test('snapshot timeout releases both locks and reconnect does not await HTTP', async()=>{
  let aborted=0;
  const p=panel((_url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>{aborted++;reject(Object.assign(new Error('timeout'),{name:'AbortError'}));})),true);
  p.state.websocket={readyState:1,close(){}};p.state.lastWebsocketAt=Date.now()-60000;
  const recovery=p.recoverAfterAppResume();
  assert.equal(p.sockets.length,1);
  await recovery;
  assert.equal(aborted,2);
  assert.equal(p.state.snapshotFetchInFlight,null);
  assert.equal(p.state.recoveryInFlight,null);
});

test('expired login disables controls and presents login under ingress prefix', async()=>{
  const p=panel(async()=>json({detail:'Zaloguj się do PlumBox.',code:'auth_required'},401));
  p.state.unlocked=true;p.state.token='old';p.state.pendingWrite={value:1};
  await assert.rejects(p.api('/api/snapshot'));
  assert.equal(p.state.authExpired,true);
  assert.equal(p.state.unlocked,false);
  assert.equal(p.state.pendingWrite,null);
  assert.equal(p.editors[0].disabled,true);
  assert.equal(p.element('sessionExpiredDialog').open,true);
  let cancelPrevented=false;p.element('sessionExpiredDialog').listeners.cancel({preventDefault(){cancelPrevented=true;}});assert.equal(cancelPrevented,true);
  assert.equal(p.element('loginAgainLink').href,'https://ha.example/api/hassio_ingress/abc/login');
});

test('PIN failure does not claim login expired', async()=>{
  const p=panel(async()=>json({detail:'Odblokuj sterowanie kodem PIN.'},401));
  p.state.unlocked=true;p.state.token='old';
  await assert.rejects(p.api('/api/set',{method:'POST',body:'{}'}));
  assert.equal(p.state.authExpired,false);
  assert.equal(p.state.token,'');
});

test('temporary network failure retains token for revalidation but locks controls', async()=>{
  let available=false;
  const p=panel(async()=>{if(!available)throw new Error('network');return json({unlocked:true,role:'admin',expires_at:new Date(Date.now()+60000).toISOString()});});
  p.state.token='valid';p.state.unlocked=true;
  assert.equal(await p.checkAuth(),false);
  assert.equal(p.state.token,'valid');assert.equal(p.state.unlocked,false);
  available=true;assert.equal(await p.checkAuth(),true);assert.equal(p.state.unlocked,true);
});

test('top and sidebar locks stay synchronized',()=>{
  const p=panel();p.state.unlocked=true;p.updateLockButton();
  assert.match(p.element('topLockButton').textContent,/Admin/);
  assert.match(p.element('lockButton').textContent,/odblokowane/);
  p.state.unlocked=false;p.updateLockButton();
  assert.match(p.element('lockButton').textContent,/Odblokuj/);
});

test('bootstrap stops on expired login instead of retrying forever',async()=>{
  let calls=0;const p=panel(async()=>{calls++;return json({code:'auth_required',detail:'expired'},401);});
  await p.loadInitialDataWithRetry();assert.equal(p.state.authExpired,true);assert.equal(p.state.initialized,false);assert.equal(calls,3);
});

test('an expired session never automatically replays a pending write',async()=>{
  let writes=0;const p=panel(async(url,options)=>{if(options.method==='POST')writes++;return json({code:'auth_required',detail:'expired'},401);});
  p.state.unlocked=true;
  await p.executeWrite({parameter:{name:'heating_target_temp'},value:70},true);
  assert.equal(writes,0);assert.equal(p.state.authExpired,true);
});

function cycleViews() {
  const context={window:{}};vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/boiler_views.js'),'utf8'),context);
  return context.window.PlumBoxBoilerViews;
}
test('cycle duration is formatted including seconds',()=>{
  const views=cycleViews();assert.equal(views.duration(3661),'1 h 1 min 1 s');assert.equal(views.duration(null),'—');
});
test('cycle view clearly identifies incomplete data',async()=>{
  const views=cycleViews();const c={started_at:null,observed_since:'now',duration_seconds:null,observed_seconds:15,has_gap:true};
  const html=await views.statistics({api:async()=>({current:c,last:null,cycles:[],fresh:false,starts_today:0,starts_month:0,observed_today_seconds:15,observed_month_seconds:15,timezone:'UTC'}),escapeHtml:String,formatDate:x=>x||'—'});
  assert.match(html,/Początek nieznany/);assert.match(html,/lukę w odczytach/);
});
test('notification view shows selected phone and disabled custom threshold',async()=>{
  const views=cycleViews();const html=await views.notifications({api:async()=>({settings:{enabled:false,target:'mobile_app_iphone',start:true,extinguishing:true,finished:true,alarms:true,temperature_threshold:null,threshold_hold_seconds:10,temperature_hysteresis:3},targets:['mobile_app_iphone'],available:true,recent:[]}),escapeHtml:String,formatDate:String});
  assert.match(html,/value="mobile_app_iphone" checked/);assert.match(html,/Puste = bez własnego progu/);assert.match(html,/Wyślij test na wybrane telefony/);
});


test('boiler photo animation follows controller phase and stops when disconnected', () => {
  const p=panel(async()=>json({}));
  assert.equal(p.schemeBurnerState('Rozpalanie', false, true).phase, 'igniting');
  assert.equal(p.schemeBurnerState('Praca', false, true).phase, 'burning');
  assert.equal(p.schemeBurnerState('Nadzór', false, true).phase, 'burning');
  assert.equal(p.schemeBurnerState('Wygaszanie', false, true).phase, 'extinguishing');
  assert.equal(p.schemeBurnerState('Postój', false, true).phase, 'idle');
  assert.equal(p.schemeBurnerState('Nieznany', null, true).phase, 'idle');
  assert.equal(p.schemeBurnerState('Praca', true, false).phase, 'offline');
  assert.equal(p.schemeBurnerState('Nieznany', true, true).phase, 'igniting');
});

test('photo readouts update from snapshot and preserve missing sensor values', () => {
  const p=panel(async()=>json({}));
  p.state.snapshot={connected:true,values:{state_label:'Rozpalanie',heating_temp:67,heating_target:70,feeder_temp:29,feeder:true,lighter:true}};
  let html=p.installationSchemeHtml();
  assert.match(html, /burner-igniting/);
  assert.match(html, /sf11130.jpg/);
  assert.match(html, /<b>67<small>°C<\/small><\/b>/);
  assert.match(html, /Temp. podajnika/);
  assert.match(html, /Podawanie pelletu/);
  p.state.snapshot={connected:true,values:{state_label:'Postój'}};
  html=p.installationSchemeHtml();
  assert.match(html, /burner-idle/);
  assert.match(html, /Podawanie: brak odczytu/);
  assert.doesNotMatch(html, /67|29/);
});


test('H1/H2 cards show feeder work times in seconds rather than unavailable boiler kW',()=>{
  const p=panel();
  p.state.snapshot={values:{heating_target:75,heating_temp:67},parameters:{
    fuel_feeding_work_100:{value:7.5},fuel_feeding_work_50:{value:5},fuel_feeding_work_30:{value:2},
    boiler_power_100:{value:99},boiler_power_50:{value:88},boiler_power_30:{value:77}
  }};
  const html=p.hysteresisSummaryHtml();
  for(const text of ['CZAS PRACY · MOC MAX','CZAS PRACY · MOC ŚREDNIA','CZAS PRACY · MOC MINIMALNA','7,5 s','5 s','2 s'])assert(html.includes(text),text);
  assert(!html.includes(' kW'));
  assert(!html.includes('99 s'));
});

test('missing feeder times stay missing and a zero time is preserved',()=>{
  const p=panel();
  p.state.snapshot={values:{heating_target:75},parameters:{fuel_feeding_work_100:{value:0},boiler_power_50:{value:11}}};
  const html=p.hysteresisSummaryHtml();
  assert(html.includes('<strong>0 s</strong>'));
  assert.equal((html.match(/<strong>— s<\/strong>/g)||[]).length,2);
  assert(!html.includes('11 s'));
});


test('summer mode select preserves Auto as native code 2 and shows all three modes',()=>{
  const p=panel();p.state.unlocked=true;
  const html=p.editorHtml({name:'summer_mode',scope:'ecomax',index:0,kind:'select',risk:'safe',value:2,native_value:2,options:{'0':'Zima','1':'Lato','2':'Auto'}});
  assert.match(html,/<option value="0" >Zima<\/option>/);
  assert.match(html,/<option value="1" >Lato<\/option>/);
  assert.match(html,/<option value="2" selected>Auto<\/option>/);
  assert.equal((html.match(/ selected/g)||[]).length,1);
});
