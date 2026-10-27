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
    window:{devicePixelRatio:1}, URL, Headers, AbortController, Date, WebSocket:Socket, getComputedStyle:()=>({getPropertyValue:()=>""}),
    fetch:fetchImpl || (async()=>new Response(JSON.stringify({connected:true}),{headers:{'Content-Type':'application/json'}})),
    setTimeout:fastTimers ? (fn,ms)=>setTimeout(fn,Math.min(ms,30)) : setTimeout,clearTimeout,setInterval,clearInterval,
  };
  vm.createContext(context);
  const exported = '  render = async () => {}; drawMainHistoryChart = () => {}; drawOverviewHistoryChart = () => {}; renderOverviewAlarms = () => {}; toast = () => {};\n  globalThis.panel = {state, api, fetchSnapshot, checkAuth, recoverAfterAppResume, updateLockButton, loadInitialDataWithRetry, executeWrite, schemeBurnerState, installationSchemeHtml, hysteresisSummaryHtml, loadPowerRuntime, paintLineChart, sectionHtml, overviewHtml, sparklineSvg, appendOverviewTemperatureSample, loadOverviewExtras, editorHtml, historyHtml, chartSeries};';
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


test('H1/H2 cards show accumulated runtime instead of feeder settings',()=>{
  const p=panel();
  p.state.snapshot={values:{heating_target:75,heating_temp:67},parameters:{
    fuel_feeding_work_100:{value:4},fuel_feeding_work_50:{value:4},fuel_feeding_work_30:{value:5}
  }};
  p.state.powerRuntime={seconds:{'100':90061,'50':3605,'30':0},covered_seconds:100000,unknown_work_seconds:12};
  const html=p.hysteresisSummaryHtml();
  for(const text of ['25 h 1 min 1 s','1 h 0 min 5 s','0 h 0 min 0 s','ostatnie 48 godzin'])assert(html.includes(text),text);
  assert(!html.includes('<strong>4 s</strong>'));
  assert(!html.includes('<strong>5 s</strong>'));
});

test('missing runtime is shown as missing rather than feeder time or zero',()=>{
  const p=panel();
  p.state.snapshot={values:{heating_target:75},parameters:{fuel_feeding_work_100:{value:4}}};
  const html=p.hysteresisSummaryHtml();
  assert.equal((html.match(/<strong>—<\/strong>/g)||[]).length,3);
  assert(html.includes('Brak zapisanych danych o czasie pracy'));
});


test('summer mode select preserves Auto as native code 2 and shows all three modes',()=>{
  const p=panel();p.state.unlocked=true;
  const html=p.editorHtml({name:'summer_mode',scope:'ecomax',index:0,kind:'select',risk:'safe',value:2,native_value:2,options:{'0':'Zima','1':'Lato','2':'Auto'}});
  assert.match(html,/<option value="0" >Zima<\/option>/);
  assert.match(html,/<option value="1" >Lato<\/option>/);
  assert.match(html,/<option value="2" selected>Auto<\/option>/);
  assert.equal((html.match(/ selected/g)||[]).length,1);
});

test('installation scheme shows live exhaust temperature between weather and boiler state',()=>{
  const p=panel();p.state.snapshot={connected:true,values:{outside_temp:15.5,exhaust_temp:128.126,state_label:'Postój'}};
  let html=p.installationSchemeHtml();
  assert.match(html, /class="scheme-exhaust" aria-label="Temperatura spalin">SPALINY <b>128,1°C<\/b>/);
  assert(html.indexOf('class="scheme-weather"') < html.indexOf('class="scheme-exhaust"'));
  assert(html.indexOf('class="scheme-exhaust"') < html.indexOf('class="scheme-controller"'));
  p.state.snapshot.values.exhaust_temp=91;
  html=p.installationSchemeHtml();assert.match(html, /SPALINY <b>91,0°C/);
  p.state.snapshot.values.exhaust_temp=0;
  html=p.installationSchemeHtml();assert.match(html, /SPALINY <b>0,0°C/);
  delete p.state.snapshot.values.exhaust_temp;
  html=p.installationSchemeHtml();assert.match(html, /SPALINY <b>—°C/);
});

test('temperature history chart and legend exclude the return series',async()=>{
  const p=panel(async()=>json({rows:[{heating_temp:67,return_temp:55,water_heater_temp:48,mixer_temp:42}]}));
  assert.deepEqual(Array.from(p.chartSeries(),item=>item[0]),['heating_temp','water_heater_temp','mixer_temp']);
  const html=await p.historyHtml();
  assert(!html.includes('return_temp'));assert(!html.includes('Powrót'));
  for(const label of ['Kocioł','CWU','Mieszacz'])assert(html.includes(label));
});


test('runtime cards load persisted totals from API and refresh after 30 seconds',async()=>{
  let calls=0;
  const p=panel(async url=>{assert(String(url).endsWith('/api/power-runtime'));calls++;return json({seconds:{'100':calls*3600,'50':0,'30':0},covered_seconds:7200,unknown_work_seconds:0});});
  p.state.snapshot={values:{heating_target:75},parameters:{}};
  await p.loadPowerRuntime();
  assert(p.hysteresisSummaryHtml().includes('1 h 0 min 0 s'));
  await p.loadPowerRuntime();assert.equal(calls,1);
  p.state.powerRuntimeLoadedAt=Date.now()-31000;
  await p.loadPowerRuntime();assert.equal(calls,2);
  assert(p.hysteresisSummaryHtml().includes('2 h 0 min 0 s'));
});


test('mixer menu shows separate heating curve editors per mixer',()=>{
  const p=panel();p.state.unlocked=true;p.state.activeView='mixer';
  p.state.snapshot={parameters:{},mixers:{}};
  for(const index of [0,2])p.state.snapshot.mixers[index]={parameters:{
    heating_curve:{name:'heating_curve',label:'Krzywa grzewcza mieszacza',section:'mixer',scope:'mixer',index,access:'user',risk:'safe',writable:true,kind:'number',value:1.2,min:0,max:4,step:0.1},
    heating_curve_shift:{name:'heating_curve_shift',label:'Przesunięcie krzywej grzewczej mieszacza',section:'mixer',scope:'mixer',index,access:'user',risk:'safe',writable:true,kind:'number',value:-5,min:-20,max:20,step:1,unit:'°C'}
  }};
  const html=p.sectionHtml('mixer');
  for(const index of [0,2]){
    assert(html.includes(`data-save-parameter="mixer-${index}-heating-curve"`));
    assert(html.includes(`data-save-parameter="mixer-${index}-heating-curve-shift"`));
  }
  assert(html.includes('step="0.1"'));
  assert(html.includes('value="-5"'));
  assert(html.includes('Przesunięcie krzywej grzewczej mieszacza'));
});


test('overview requests 24 hours of persisted history and removes remote footer',async()=>{
  const calls=[];const now=Date.now();
  const p=panel(async url=>{calls.push(String(url));return json(String(url).includes('/api/history?')?{rows:[{ts:new Date(now-13*3600000).toISOString(),heating_temp:67}]}:{})});
  p.state.snapshot={connected:true,timestamp:new Date(now).toISOString(),values:{heating_temp:68},mixers:{}};
  await p.loadOverviewExtras();
  assert(calls.some(url=>url.includes('/api/history?hours=24&limit=3000')));
  assert(p.state.overviewHistory.some(row=>Date.parse(row.ts)<now-12*3600000));
  const html=p.overviewHtml();
  assert(html.includes('HISTORIA TEMPERATUR · OSTATNIE 24 GODZINY'));
  assert.equal((html.match(/Ostatnie 12 godzin/g)||[]).length,6);
  assert(!html.includes('remote-card'));
  assert(!html.includes('DOSTĘP ZDALNY'));
});

test('all six small charts use 12 hour timestamps and retain gaps and zero',()=>{
  const p=panel(),now=Date.now();
  for(const key of ['feeder_temp','boiler_load','fan_power','mixer_temp','water_heater_temp','fuel_level']){
    p.state.overviewHistory=[
      {ts:new Date(now-13*3600000).toISOString(),[key]:999},
      {ts:new Date(now-3600000).toISOString(),[key]:0,connected:1},
      {ts:new Date(now-3570000).toISOString(),[key]:1,connected:1},
      {ts:new Date(now-3540000).toISOString(),[key]:null,connected:1},
      {ts:new Date(now-3510000).toISOString(),[key]:2,connected:1}
    ];
    const svg=p.sparklineSvg(key,'red',30);
    assert.equal((svg.match(/<polyline/g)||[]).length,1);
    assert.equal((svg.match(/<circle/g)||[]).length,1);
    assert(svg.includes('165.0,27.0'),key);
    p.state.overviewHistory=[{ts:new Date(now).toISOString(),[key]:null}];
    assert(p.sparklineSvg(key,'red').includes('Brak historii'));
  }
});

test('live history retains a full day instead of truncating to 400 recent changes',()=>{
  const p=panel(),now=Math.floor(Date.now()/30000)*30000;
  p.state.overviewHistory=Array.from({length:2000},(_,i)=>({ts:new Date(now-(2000-i)*30000).toISOString(),heating_temp:67}));
  p.state.snapshot={connected:true,timestamp:new Date(now).toISOString(),values:{heating_temp:67,fuel_level:0}};
  p.appendOverviewTemperatureSample();
  assert.equal(p.state.overviewHistory.length,2001);
  assert.equal(p.state.overviewHistory.at(-1).fuel_level,0);
  p.state.snapshot.timestamp=new Date(now+1000).toISOString();p.appendOverviewTemperatureSample();
  assert.equal(p.state.overviewHistory.length,2001);
});

test('weather options are in Mixer and lambda options are in CO and boiler',()=>{
  const p=panel();p.state.unlocked=true;
  const mixer=['weather_control','weather_factor','thermostat_operation','summer_work'];
  const lambda=['lambda_control','lambda_correction_range','oxygen_100','oxygen_50','oxygen_30','fuzzy_logic_oxygen_correction'];
  const parameter=(name,scope,section)=>({name,label:name,scope,section,index:0,value:1,native_value:1,min:0,max:100,step:1,risk:scope==='mixer'?'safe':'advanced',kind:name==='weather_factor'||name!=='lambda_control'&&scope==='ecomax'?'number':'switch',writable:true});
  p.state.snapshot={parameters:Object.fromEntries(lambda.map(name=>[name,parameter(name,'ecomax','heating')])),mixers:{'0':{parameters:Object.fromEntries(mixer.map(name=>[name,parameter(name,'mixer','mixer')]))}}};
  const heating=p.sectionHtml('heating'),mix=p.sectionHtml('mixer');
  for(const name of mixer){assert(mix.includes(`data-param-name="${name}"`));assert(!heating.includes(`data-param-name="${name}"`));}
  for(const name of lambda){assert(heating.includes(`data-param-name="${name}"`));assert(!mix.includes(`data-param-name="${name}"`));}
  const index=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
  assert(!index.includes('data-view="notifications"'));
  assert(!index.includes('Powiadomienia na telefon'));
});


test('history canvas draws aligned time labels below plot and reduces density on phones',()=>{
  const p=panel(),rows=Array.from({length:49},(_,i)=>({ts:new Date(Date.UTC(2026,9,26,18)+i*1800000).toISOString(),heating_temp:65+i%6}));
  function draw(width,compact=false){
    const labels=[],context={fillText:(text,x,y)=>labels.push({text,x,y})};
    for(const name of ['setTransform','clearRect','beginPath','moveTo','lineTo','stroke','save','restore'])context[name]=()=>{};
    const canvas={getBoundingClientRect:()=>({width,height:300}),getContext:()=>context,__chartArgs:{rows,series:[['heating_temp','#f80','Kocioł']],compact}};
    p.paintLineChart(canvas,null);
    return {labels:labels.filter(l=>l.y>canvas.__layout.pad.top+canvas.__layout.plotH),layout:canvas.__layout};
  }
  const desktop=draw(736),phone=draw(320);
  const times=labels=>labels.filter(l=>/^\d{2}:\d{2}$/.test(l.text));
  assert.equal(times(desktop.labels).length,7);
  assert.equal(times(phone.labels).length,3);
  assert.equal(times(desktop.labels)[0].text,new Date(rows[0].ts).toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit'}));
  assert.equal(times(desktop.labels).at(-1).text,new Date(rows.at(-1).ts).toLocaleTimeString('pl-PL',{hour:'2-digit',minute:'2-digit'}));
  assert(desktop.labels.some(l=>/^\d{2}\.\d{2}/.test(l.text)));
  assert.equal(times(phone.labels)[0].x,phone.layout.pad.left);
  assert.equal(times(phone.labels).at(-1).x,phone.layout.pad.left+phone.layout.plotW);
  assert.equal(times(draw(320,true).labels).length,0);
});

test('sidebar omits the local V3 Native footer description',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../app/static/index.html'),'utf8');
  assert(!html.includes('Lokalny panel ecoMAX · V3 Native'));
  assert(html.includes('sidebar-version'));
});
