/* Account preferences are independent of the public picks feed. */
(() => {
    'use strict';
    const config = window.SHARPIE_FIREBASE_CONFIG;
    if (window.SHARPIE_FIREBASE_ENABLED === false) return;
    if (!config?.apiKey || !config?.projectId || !config?.appId) return;
    let adapter, sdk, auth, db, user = null, epoch = 0, ready = false, applying = false;
    let unsubscribers = [], filters = [], remotePreferences = {}, timer, pending = 0, failed = false;
    let guestPreferences, guestFilters, lastPreferences = '', initialized = false;
    let latestFilters = null;
    let failedFilters = null, lastSyncError = '';
    const clean = value => JSON.parse(JSON.stringify(value));
    const el = id => document.getElementById(id);
    const status = text => { el('accountStatus').textContent = text; };
    const same = (a,b) => JSON.stringify(a) === JSON.stringify(b);
    const errorText = error => ({
        'auth/invalid-credential': 'El correo o la contraseña no son correctos.',
        'auth/email-already-in-use': 'Este correo ya tiene una cuenta. Inicia sesión o recupera la contraseña.',
        'auth/weak-password': 'Usa una contraseña más segura, de al menos 6 caracteres.',
        'auth/invalid-email': 'Revisa el correo electrónico.',
        'auth/popup-blocked': 'Permite la ventana de acceso de Google y vuelve a intentar.',
        'auth/popup-closed-by-user': 'Se canceló el acceso con Google.',
        'auth/account-exists-with-different-credential': 'Este correo usa otro método de acceso. Inicia sesión con ese método.',
        'auth/too-many-requests': 'Demasiados intentos. Espera unos minutos.',
        'auth/network-request-failed': 'No hay conexión. Inténtalo de nuevo.',
        'auth/unauthorized-domain': 'El acceso aún no está habilitado para este dominio. Contacta al administrador.',
        'auth/operation-not-allowed': 'Este método de acceso todavía no está habilitado. Contacta al administrador.',
        'permission-denied': 'Firebase rechazó el acceso a tu configuración. Deben publicarse las reglas de permisos para settings y filters. Tus filtros locales siguen intactos.',
        'unavailable': 'No hay conexión con Firebase. Tus filtros locales siguen intactos; vuelve a intentar cuando haya conexión.',
    }[error.code] || 'No se pudo completar la operación. Inténtalo de nuevo.');

    function mount() {
        const root = document.createElement('section');
        root.className = 'account-panel';
        root.setAttribute('aria-label', 'Tu cuenta y configuración');
        root.innerHTML = `<div><strong id="accountIdentity">Tu configuración, en todos tus dispositivos</strong><p id="accountStatus" role="status">Conectando…</p></div>
          <div class="account-actions"><button type="button" id="accountLogin" class="btn-chip">Iniciar sesión</button><button type="button" id="accountImport" class="btn-chip" hidden>Importar filtros de este navegador</button><button type="button" id="accountRetry" class="btn-chip" hidden>Reintentar sincronización</button><button type="button" id="accountLogout" class="btn-chip" hidden>Cerrar sesión</button></div>
          <dialog id="accountDialog"><form id="accountForm"><h2>Tu cuenta Sharpie</h2><p>Guarda tus filtros y preferencias para usarlos en otros dispositivos.</p><button type="button" id="accountGoogle" class="btn-chip">Continuar con Google</button><label>Correo<input id="accountEmail" type="email" autocomplete="username" required maxlength="254"></label><label>Contraseña<input id="accountPassword" type="password" autocomplete="current-password" minlength="6" required></label><p id="accountError" role="alert"></p><div class="account-actions"><button type="submit" class="btn-chip">Entrar</button><button type="button" id="accountRegister" class="btn-chip">Crear cuenta</button><button type="button" id="accountReset" class="btn-chip">Recuperar contraseña</button><button type="button" id="accountClose" class="btn-chip">Cancelar</button></div></form></dialog>`;
        document.querySelector('.header')?.insertAdjacentElement('afterend', root);
        el('accountLogin').onclick = () => { el('accountError').textContent = ''; el('accountDialog').showModal(); };
        el('accountClose').onclick = () => el('accountDialog').close();
        el('accountDialog').addEventListener('close', () => { el('accountPassword').value = ''; });
        async function run(operation) {
            if (!sdk) return;
            el('accountError').textContent = '';
            el('accountForm').querySelectorAll('button').forEach(b => b.disabled = true);
            try { await operation(); }
            catch (error) { el('accountError').textContent = errorText(error); }
            finally { el('accountForm').querySelectorAll('button').forEach(b => b.disabled = false); }
        }
        el('accountForm').onsubmit = event => { event.preventDefault(); run(() => sdk.signInWithEmailAndPassword(auth, el('accountEmail').value.trim(), el('accountPassword').value)); };
        el('accountRegister').onclick = () => { if (el('accountForm').reportValidity()) run(() => sdk.createUserWithEmailAndPassword(auth, el('accountEmail').value.trim(), el('accountPassword').value)); };
        el('accountGoogle').onclick = () => run(() => sdk.signInWithPopup(auth, new sdk.GoogleAuthProvider()));
        el('accountReset').onclick = () => {
            if (!el('accountEmail').reportValidity()) return;
            run(async () => { await sdk.sendPasswordResetEmail(auth, el('accountEmail').value.trim()); el('accountError').textContent = 'Si existe una cuenta con ese correo, recibirás instrucciones para recuperar el acceso.'; });
        };
        el('accountLogout').onclick = async () => {
            clearTimeout(timer);
            // Flush pending preference changes before leaving the account.
            if (ready) await savePreferences();
            if (pending || (failed && ready)) { status('Hay cambios sin guardar. Reintenta antes de cerrar sesión.'); return; }
            try { await sdk.signOut(auth); } catch { status('No se pudo cerrar sesión. Inténtalo de nuevo.'); }
        };
        el('accountRetry').onclick = () => {
            if (user && ready) {
                failed=false;lastSyncError='';
                if (failedFilters) { const retry=failedFilters;failedFilters=null;saveFilters(retry.list,retry.importCount); }
                else savePreferences();
            }
            else if(user) connectUser(user);
            else initializeSdk();
        };
        el('accountImport').onclick = () => {
            if (!ready || failed) { status(lastSyncError || 'Todavía no se ha podido leer tu cuenta. Primero reintenta la conexión; tus filtros locales no se han borrado.');return; }
            if (!guestFilters?.length) { status('No hay filtros locales para importar en este navegador.');return; }
            if (pending) { status('Espera a que termine el guardado actual antes de importar.');return; }
            const merged = [...filters];
            guestFilters.forEach(p => {
                if (!merged.some(q => q.name === p.name && same(q.filters,p.filters))) merged.push({...p, id: crypto.randomUUID()});
            });
            const count=merged.length-filters.length;
            if(!count) { status('Tus filtros locales ya están en esta cuenta. No se crearon duplicados.');return; }
            saveFilters(merged,count);
        };
    }

    function applyPreferences(value) {
        applying = true;
        try { adapter.applyPreferences(clean(value)); lastPreferences = JSON.stringify(adapter.getPreferences()); }
        finally { applying = false; }
    }
    function refreshFilters() { applying = true; try { adapter.refreshFilters?.(); } finally { applying = false; } }
    function ref(kind, id) { return sdk.doc(db, 'users', user.uid, kind, id); }
    async function write(operation) {
        const generation = epoch;
        pending++; status('Guardando…');
        try {
            await operation();
            if (generation === epoch) { failed = false;lastSyncError=''; el('accountRetry').hidden = true; }
            return true;
        } catch (error) {
            if (generation === epoch) { failed = true;lastSyncError=errorText(error); status(lastSyncError); el('accountRetry').hidden = false; }
            return false;
        } finally {
            if (generation === epoch) {
                pending--;
                if (!pending && !failed) {
                    if (latestFilters) { filters=latestFilters;latestFilters=null;refreshFilters(); }
                    status('Configuración guardada en tu cuenta');
                }
            }
        }
    }
    async function savePreferences() {
        if (!user || !ready || applying || failed) return;
        if (pending) { clearTimeout(timer);timer=setTimeout(()=>{timer=null;savePreferences();},600);return; }
        const preferences = clean(adapter.getPreferences());
        if (same(preferences, remotePreferences)) { el('accountRetry').hidden=true;status('Configuración sincronizada');return; }
        const target = ref('settings', adapter.page), generation = epoch;
        const ok = await write(() => sdk.setDoc(target, {schemaVersion:1, preferences, updatedAt:sdk.serverTimestamp()}));
        if (ok && generation === epoch) remotePreferences = preferences;
    }
    function changed() {
        if (applying) return;
        if (!user) { adapter.saveGuestPreferences?.(adapter.getPreferences()); return; }
        const signature = JSON.stringify(adapter.getPreferences());
        if (!ready || signature === lastPreferences) return;
        lastPreferences = signature;
        clearTimeout(timer); timer = setTimeout(() => {timer=null;savePreferences();}, 600);
    }
    function saveFilters(list, importCount=0) {
        if (!user) return null;
        if (!ready || pending || failed) { status('Espera a que termine la sincronización y vuelve a guardar.'); return false; }
        const old = clean(filters), next = clean(list), batch = sdk.writeBatch(db), generation = epoch;
        if (next.length > 200 || next.some(p=>!/^[\w-]{1,128}$/.test(p.id) || typeof p.name!=='string' || !p.name.trim() || p.name.length>100)) {
            status('Usa nombres de hasta 100 caracteres y un máximo de 200 filtros.');return false;
        }
        next.forEach(p => {
            const previous = old.find(q => q.id === p.id);
            if (!same(previous,p)) batch.set(ref('filters',p.id),{schemaVersion:1,name:p.name,filters:p.filters,updatedAt:sdk.serverTimestamp()});
        });
        old.filter(p=>!next.some(q=>q.id===p.id)).forEach(p=>batch.delete(ref('filters',p.id)));
        filters = next; refreshFilters();
        write(()=>batch.commit()).then(ok=>{
            if(generation!==epoch)return;
            if (!ok) { failedFilters={list:next,importCount};filters=old; refreshFilters(); }
            else { failedFilters=null;if(importCount)status(`${importCount} filtro(s) importado(s) a tu cuenta. Los originales siguen en este navegador.`); }
        });
        return true;
    }
    function connectUser(nextUser) {
        epoch++; const generation = epoch;
        clearTimeout(timer); timer=null; unsubscribers.forEach(fn=>fn()); unsubscribers=[];
        ready=false; pending=0; failed=false;failedFilters=null;lastSyncError=''; filters=[]; latestFilters=null;remotePreferences={};
        if (!user && nextUser) { guestPreferences=clean(adapter.getPreferences()); guestFilters=clean(adapter.getGuestFilters?.() || []); }
        user=nextUser;
        el('accountLogin').hidden=Boolean(user); el('accountLogout').hidden=!user;
        el('accountImport').hidden=!user || !guestFilters?.length;
        el('accountRetry').hidden=true;
        el('accountIdentity').textContent=user ? (user.displayName || user.email || 'Tu cuenta') : 'Tu configuración, en todos tus dispositivos';
        applyPreferences(user ? adapter.defaults : (guestPreferences || adapter.defaults)); refreshFilters();
        if (!user) { status('Modo local · inicia sesión para sincronizar'); return; }
        el('accountDialog').close(); status('Cargando tu configuración…');
        let prefsLoaded=false, filtersLoaded=!adapter.getGuestFilters;
        const check=()=>{ ready=prefsLoaded && filtersLoaded; if(ready && !pending && !failed) status('Configuración sincronizada'); };
        const onError=error=>{ if(generation!==epoch)return;ready=false;failed=true;lastSyncError=errorText(error);status(lastSyncError);el('accountRetry').hidden=false; };
        unsubscribers.push(sdk.onSnapshot(ref('settings',adapter.page), {includeMetadataChanges:true}, snapshot=>{
            if(generation!==epoch || snapshot.metadata.fromCache || snapshot.metadata.hasPendingWrites)return;
            const value=snapshot.exists() ? snapshot.data().preferences : adapter.defaults;
            remotePreferences=clean(value || adapter.defaults);
            if(!pending && !timer) applyPreferences(remotePreferences);
            prefsLoaded=true;check();
        },onError));
        if(adapter.getGuestFilters) unsubscribers.push(sdk.onSnapshot(sdk.collection(db,'users',user.uid,'filters'),{includeMetadataChanges:true},snapshot=>{
            if(generation!==epoch || snapshot.metadata.fromCache || snapshot.metadata.hasPendingWrites)return;
            const incoming=snapshot.docs.map(d=>({id:d.id,name:d.data().name,filters:d.data().filters}))
                .filter(p=>/^[\w-]{1,128}$/.test(p.id) && typeof p.name==='string' && p.filters && typeof p.filters==='object');
            if(!pending) { filters=incoming;refreshFilters(); } else latestFilters=incoming;
            filtersLoaded=true;check();
        },onError));
    }
    async function initializeSdk() {
        try {
            const base='https://www.gstatic.com/firebasejs/12.19.0/';
            const [app,authModule,store]=await Promise.all([import(base+'firebase-app.js'),import(base+'firebase-auth.js'),import(base+'firebase-firestore.js')]);
            sdk={...authModule,...store};
            const application=app.getApps().find(a=>a.name==='sharpie-preferences') || app.initializeApp(config,'sharpie-preferences');
            auth=sdk.getAuth(application);db=sdk.getFirestore(application);
            await sdk.setPersistence(auth,sdk.browserLocalPersistence);
            sdk.onAuthStateChanged(auth,connectUser);
        } catch { status('No se pudo conectar tu cuenta. Los picks siguen disponibles.');el('accountRetry').hidden=false; }
    }
    function start() {
        if(initialized || !window.SHARPIE_SETTINGS_ADAPTER)return;
        initialized=true;adapter=window.SHARPIE_SETTINGS_ADAPTER;
        guestPreferences=clean(adapter.getPreferences());guestFilters=clean(adapter.getGuestFilters?.() || []);
        mount();
        window.SHARPIE_ACCOUNT={get signedIn(){return Boolean(user);},getFilters:()=>clean(filters),saveFilters,changed};
        document.addEventListener('input',event=>{if(!event.target.closest('.account-panel'))setTimeout(changed,0);});
        document.addEventListener('change',event=>{if(!event.target.closest('.account-panel'))setTimeout(changed,0);});
        document.addEventListener('click',event=>{if(!event.target.closest('.account-panel'))setTimeout(changed,0);});
        initializeSdk();
    }
    window.addEventListener('sharpie:settings-ready',start);start();
})();
