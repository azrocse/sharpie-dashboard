const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const source = fs.readFileSync('src/dashboard/assets/js/user-settings.js','utf8');
const tick = () => new Promise(resolve=>setImmediate(resolve));
function harness(configured=true) {
  const elements = new Map(), events={}, docs=new Map(), listeners=[], writes=[];
  let authListener, state={search:'guest',advancedView:false}, fail=false;
  const node = id => {
    if(!elements.has(id))elements.set(id,{textContent:'',value:'',hidden:false,disabled:false,
      classList:{add(){},toggle(){}},setAttribute(){},addEventListener(){},querySelectorAll:()=>[],
      reportValidity:()=>true,showModal(){},close(){},insertAdjacentElement(){}});
    return elements.get(id);
  };
  const snapshot = path => path.split('/').length===3
    ? {metadata:{fromCache:false,hasPendingWrites:false},docs:[...docs].filter(([k])=>k.startsWith(path+'/')).map(([k,v])=>({id:k.split('/').at(-1),data:()=>v}))}
    : {metadata:{fromCache:false,hasPendingWrites:false},exists:()=>docs.has(path),data:()=>docs.get(path)};
  const emit = path => listeners.filter(l=>l.active && (l.path===path || path.startsWith(l.path+'/'))).forEach(l=>l.fn(snapshot(l.path)));
  const sdk={getApps:()=>[],initializeApp:()=>({}),getAuth:()=>({}),getFirestore:()=>({}),
    setPersistence:async()=>{},browserLocalPersistence:{},GoogleAuthProvider:class {},
    onAuthStateChanged:(a,fn)=>{authListener=fn;fn(null);},
    signInWithPopup:async()=>authListener({uid:'google',email:'google@example.test'}),
    signInWithEmailAndPassword:async(a,email)=>authListener({uid:email,email}),
    createUserWithEmailAndPassword:async(a,email)=>authListener({uid:email,email}),
    sendPasswordResetEmail:async()=>{},signOut:async()=>authListener(null),
    doc:(db,...parts)=>parts.join('/'),collection:(db,...parts)=>parts.join('/'),serverTimestamp:()=>123,
    onSnapshot:(path,opt,fn,error)=>{const l={path,fn,active:true,error};listeners.push(l);queueMicrotask(()=>l.active&&fn(snapshot(path)));return()=>{l.active=false;};},
    setDoc:async(path,value)=>{if(fail)throw {code:'permission-denied'};writes.push(path);docs.set(path,value);emit(path);},
    writeBatch:()=>{const changes=[];return {set:(p,v)=>changes.push([p,v]),delete:p=>changes.push([p,null]),commit:async()=>{
      if(fail)throw {code:'permission-denied'};for(const [p,v]of changes){writes.push(p);if(v)docs.set(p,v);else docs.delete(p);emit(p);}
    }};},
  };
  const timers=new Map();let nextTimer=0;
  const window={SHARPIE_FIREBASE_CONFIG:configured?{apiKey:'test',projectId:'test',appId:'test'}:null,
    SHARPIE_SETTINGS_ADAPTER:{page:'dashboard',defaults:{search:'',advancedView:false},getPreferences:()=>state,
      applyPreferences:p=>{state=p;},getGuestFilters:()=>[{id:'guest',name:'Guest',filters:{search:'guest'}}],refreshFilters(){}},
    addEventListener:(name,fn)=>events[name]=fn};
  const context=vm.createContext({window,document:{createElement:()=>node('root'),getElementById:node,querySelector:()=>node('header'),addEventListener(){}},
    crypto:{randomUUID:()=> 'imported'},console,__sdk:sdk,setTimeout:fn=>{const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id)});
  const replaced=source.replace("await Promise.all([import(base+'firebase-app.js'),import(base+'firebase-auth.js'),import(base+'firebase-firestore.js')])",'[__sdk,__sdk,__sdk]');
  vm.runInContext(replaced,context);
  return {window,node,docs,listeners,writes,get state(){return state;},setState:p=>{state=p;},login:uid=>authListener(uid?{uid,email:uid+'@example.test'}:null),
    fail:value=>{fail=value;},emit,flush:async()=>{const fns=[...timers.values()];timers.clear();fns.forEach(fn=>fn());await tick();}};
}
test('disabled configuration leaves the dashboard and local filters alone',()=>{
  const h=harness(false);assert.equal(h.window.SHARPIE_ACCOUNT,undefined);assert.equal(h.state.search,'guest');
});
test('isolates accounts, restores guest state and ignores callbacks from the previous account',async()=>{
  const h=harness();await tick();
  h.docs.set('users/A/settings/dashboard',{preferences:{search:'A only',advancedView:true}});
  h.docs.set('users/A/filters/one',{name:'A filter',filters:{search:'A'}});
  h.login('A');await tick();assert.equal(h.state.search,'A only');assert.equal(h.window.SHARPIE_ACCOUNT.getFilters().length,1);
  const stale=h.listeners.find(l=>l.path==='users/A/settings/dashboard');
  h.login('B');await tick();assert.equal(h.state.search,'');assert.equal(h.window.SHARPIE_ACCOUNT.getFilters().length,0);
  stale.fn({metadata:{},exists:()=>true,data:()=>({preferences:{search:'leaked'}})});
  assert.equal(h.state.search,'');h.login(null);assert.equal(h.state.search,'guest');
});
test('saves only the signed-in UID; renames in place, deletes and keeps guest filters separate',async()=>{
  const h=harness();await tick();h.login('A');await tick();
  h.setState({search:'saved',advancedView:true});h.window.SHARPIE_ACCOUNT.changed();await h.flush();
  assert.equal(h.docs.get('users/A/settings/dashboard').preferences.search,'saved');
  assert.equal(h.window.SHARPIE_ACCOUNT.saveFilters([{id:'one',name:'First',filters:{search:'A'}}]),true);await tick();
  h.window.SHARPIE_ACCOUNT.saveFilters([{id:'one',name:'Renamed',filters:{search:'B'}}]);await tick();
  assert.equal(h.docs.get('users/A/filters/one').name,'Renamed');
  assert.equal(h.window.SHARPIE_ACCOUNT.getFilters().length,1);
  h.window.SHARPIE_ACCOUNT.saveFilters([]);await tick();assert(!h.docs.has('users/A/filters/one'));
  assert(h.writes.every(path=>path.startsWith('users/A/')));
});
test('failed writes report error, roll back filters and do not claim success',async()=>{
  const h=harness();await tick();h.login('A');await tick();h.fail(true);
  h.window.SHARPIE_ACCOUNT.saveFilters([{id:'one',name:'Failed',filters:{}}]);await tick();
  assert.equal(h.window.SHARPIE_ACCOUNT.getFilters().length,0);assert.equal(h.node('accountRetry').hidden,false);
  assert(!h.node('accountStatus').textContent.includes('guardada'));
});
test('Google and email flows are wired independently of the public feed',async()=>{
  const h=harness();await tick();await h.node('accountGoogle').onclick();await tick();assert.equal(h.window.SHARPIE_ACCOUNT.signedIn,true);
  h.login(null);h.node('accountEmail').value='email@example.test';h.node('accountPassword').value='dummy-test';
  h.node('accountForm').onsubmit({preventDefault(){}});await tick();assert.equal(h.window.SHARPIE_ACCOUNT.signedIn,true);
});
