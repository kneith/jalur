/* JALUR central API integration. This file replaces local-only gates for server-backed areas. */
(() => {
  const $ = (s, r=document) => r.querySelector(s);
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let user = null, csrfToken = '', busy = false, editingGradeId = null;
  const apiBase = (window.JALUR_API_BASE || 'https://jalur-api.vercel.app/api').replace(/\/$/, '');
  const roleNames = {student:'Siswa',school_admin:'Pengelola Sekolah',teacher:'Guru Mata Pelajaran',counselor:'Guru BK',wellbeing_moderator:'Moderator Curhat',platform_admin:'Admin Platform'};
  function cookie(name){ const part=document.cookie.split('; ').find(x=>x.startsWith(name+'=')); return part ? decodeURIComponent(part.slice(name.length+1)) : ''; }
  async function api(path, opts={}) {
    const method=(opts.method||'GET').toUpperCase(), headers={'Content-Type':'application/json',...(opts.headers||{})};
    if(!['GET','HEAD','OPTIONS'].includes(method)){ const token=csrfToken||cookie('jalur_csrf'); if(token) headers['X-CSRF-Token']=token; }
    const response=await fetch(apiBase+path,{...opts,method,headers,credentials:'include',body:opts.body===undefined?undefined:JSON.stringify(opts.body)});
    if(response.status===204)return null;
    const data=await response.json().catch(()=>({}));
    if(!response.ok) throw new Error(data.message||({401:'Sesi tidak aktif atau kredensial salah.',403:'Akses tidak diizinkan atau token keamanan tidak valid.',404:'Data tidak ditemukan.',409:'Data bertentangan dengan data yang sudah ada.',429:'Terlalu banyak permintaan. Coba lagi nanti.'}[response.status])||`Permintaan gagal (${response.status}).`);
    return data;
  }
  function notice(text){ const root=$('#toastRegion'); if(root){root.innerHTML=`<div class="toast">${esc(text)}</div>`;setTimeout(()=>{root.innerHTML=''},4000)}else alert(text); }
  function dismissLoginModal(onDone){
    const root=$('#modalRoot'),backdrop=$('#centralModalBackdrop');
    if(!backdrop){onDone?.();return;}
    backdrop.classList.add('jalur-modal-closing');
    backdrop.querySelector('.modal')?.classList.add('jalur-modal-closing');
    let done=false;
    const finish=()=>{if(done)return;done=true;if(root.contains(backdrop))root.innerHTML='';onDone?.();};
    backdrop.addEventListener('animationend',event=>{if(event.target===backdrop&&event.animationName==='jalurModalBackdropOut')finish();});
    window.setTimeout(finish,420);
  }
  function modal(title, body){
    const root=$('#modalRoot');
    root.innerHTML=`<div class="modal-backdrop" id="centralModalBackdrop"><section class="modal glass" role="dialog" aria-modal="true" aria-labelledby="centralModalTitle"><div class="modal-head"><h2 id="centralModalTitle">${esc(title)}</h2><button type="button" class="icon-btn" id="centralModalClose" aria-label="Tutup">×</button></div><div class="modal-body">${body}</div></section></div>`;
    $('#centralModalClose').onclick=()=>dismissLoginModal();
    $('#centralModalBackdrop').addEventListener('click',event=>{if(event.target.id==='centralModalBackdrop')dismissLoginModal();});
  }
  function login(role){window.JALUR_LOGIN_REQUESTED=true;window.JALUR_GUEST_SELECTED=false;sessionStorage.removeItem('jalur-guest-mode');const expected=role==='school'?'school_admin':role==='bk'?'counselor':role==='moderator'?'wellbeing_moderator':role==='platform'?'platform_admin':role==='teacher'?'teacher':role==='student'?'student':null;modal(role==='school'?'Masuk Portal Pengelola Sekolah':role==='bk'?'Masuk Portal Guru BK':role==='teacher'?'Masuk Portal Guru Mata Pelajaran':role==='moderator'?'Masuk Moderator Curhat':role==='platform'?'Masuk Admin Platform':'Masuk ke JALUR',`<p class="source-line">Gunakan akun yang dibuat oleh administrator sekolah. Pendaftaran siswa dilakukan melalui sekolah agar akun terhubung dengan data sekolah.</p><form id="centralLoginForm" class="form-grid"><div class="field full"><label for="centralEmail">Email</label><input id="centralEmail" type="email" autocomplete="username" required maxlength="254"></div><div class="field full"><label for="centralPassword">Kata sandi</label><input id="centralPassword" type="password" autocomplete="current-password" required maxlength="200"></div><div class="field full"><button class="btn primary" type="submit">Masuk dengan aman</button></div><div class="field full"><small>Peran akun akan diverifikasi oleh server. Tidak ada kode akses lokal.</small></div></form>`);$('#centralLoginForm').addEventListener('submit',async e=>{e.preventDefault();const btn=e.target.querySelector('button');btn.disabled=true;try{const d=await api('/auth/login',{method:'POST',body:{email:$('#centralEmail').value.trim(),password:$('#centralPassword').value}});user=d.user;csrfToken=d.csrfToken||cookie('jalur_csrf');if(user.role==='student')await hydrateStudentWorkspace();if(expected&&user.role!==expected){await api('/auth/logout',{method:'POST'}).catch(()=>{});user=null;throw new Error('Akun ini tidak memiliki peran yang dibutuhkan untuk portal tersebut.');}dismissLoginModal(enterServerApp);notice(`Berhasil masuk sebagai ${roleNames[user.role]||user.role}.`);}catch(err){notice(err.message);btn.disabled=false;}});}
  function enterServerApp(){
    if(user?.role==='student')window.JALUR_SET_ACCOUNT_NAME?.(user.full_name||user.email);
    window.JALUR_WELCOME_REQUESTED=false;window.JALUR_GUEST_SELECTED=false;
    sessionStorage.removeItem('jalur-guest-mode');sessionStorage.setItem('jalur-app-open','1');
    window.JALUR_RESET_SCROLL_TOP?.();window.JALUR_TRANSITION_TO_APP?.();
    const badge=$('.guest-badge');if(badge)badge.textContent=roleNames[user.role]||user.role;
    const chip=$('.profile-chip');if(chip)chip.innerHTML=`<span class="avatar-mini">${esc((user.full_name||'U').slice(0,1).toUpperCase())}</span><span>${esc(user.full_name||user.email)}</span><span>⌄</span>`;
    window.JALUR_APPLY_ROLE_NAV?.(user.role,user);
    const destination=user.role==='student'?'server-home':user.role==='school_admin'?'server-school':user.role==='teacher'?'server-grades':user.role==='counselor'?'server-bk':user.role==='wellbeing_moderator'?'server-vent':user.role==='platform_admin'?'server-platform':'server-school';
    Promise.resolve(serverPage(destination)).catch(err=>notice(err.message||'Halaman akun gagal dimuat.')).finally(()=>{
      window.JALUR_RESET_SCROLL_TOP?.();
      window.requestAnimationFrame?.(()=>window.JALUR_RESET_SCROLL_TOP?.());
    });
  }
  function pageHead(title,sub){return `<div class="page-head"><div><span class="eyebrow">JALUR dan PORTAL TERPUSAT</span><h1>${esc(title)}</h1><p>${esc(sub)}</p></div><button class="btn secondary small" id="centralLogout">Keluar</button></div>`}
  function formField(label,id,placeholder,type='text',required=true){return `<div class="field"><label for="${id}">${esc(label)}</label><input id="${id}" type="${type}" placeholder="${esc(placeholder)}" ${required?'required':''}></div>`}
  async function serverPage(page){
    const root=$('#pageRoot');if(!root)return;
    const permissions={"server-home":["student"],"appointment":["student"],"vent":["student"],"server-school":["school_admin"],"school-users":["school_admin"],"school-classes":["school_admin"],"school-alumni":["school_admin"],"server-grades":["teacher"],"grades":["student","teacher","school_admin"],"server-bk":["counselor"],"server-vent":["wellbeing_moderator"],"server-platform":["platform_admin"]};
    const permitted=permissions[page];
    if(permitted&&!permitted.includes(user?.role)){notice("Halaman ini tidak tersedia untuk peran akun yang sedang digunakan.");return;}
    if(page!=="directory"&&!user&&page!=="vent"){notice("Silakan masuk dengan akun yang sesuai untuk membuka halaman ini.");return;}
    if(page==="directory"){window.navigate?.("Study Program Explorer");return;}
    window.JALUR_ANIMATE_PAGE_TRANSITION?.();const activePage=({'appointment':'BK Consultation','server-bk':'BK Portal','server-school':'School Portal','school-users':'School Portal','school-classes':'School Portal','school-alumni':'School Portal','server-grades':'Academic Profile','grades':'Academic Profile','server-home':'Dashboard','server-vent':'Anonymous Venting','vent':'Anonymous Venting','directory':'Study Program Explorer','server-platform':'Settings'})[page];if(activePage)window.JALUR_SET_ACTIVE_PAGE?.(activePage);root.innerHTML=`<section class="server-loading" role="status" aria-live="polite"><span class="loading-spinner" aria-hidden="true"></span><span>Memuat…</span></section>`;try{
    if(page==='directory'){root.innerHTML=`${pageHead('Direktori Pendidikan','Pencarian server berdasarkan universitas, jurusan, atau program studi. Hasil alfabetis dan dimuat bertahap.')}<section class="panel glass"><form id="directoryForm" class="form-grid"><div class="field"><label for="directoryType">Cari berdasarkan</label><select id="directoryType"><option value="all">Semua</option><option value="institution">Perguruan tinggi</option><option value="program">Program studi / jurusan</option></select></div><div class="field"><label for="directoryQuery">Kata kunci</label><input id="directoryQuery" placeholder="Ketik nama universitas atau prodi…" autocomplete="off"></div></form><p id="directoryMeta" class="source-line">Masukkan sedikitnya dua karakter agar pencarian dapat menampilkan hasil yang sesuai.</p><div id="directoryResults"></div><button class="btn secondary" id="directoryMore" hidden>Muat hasil berikutnya</button></section>`;wireDirectory();return;}
    if(page==='server-platform'){
      root.innerHTML=`${pageHead('Administrasi Platform','Kelola akun lintas sekolah dan akses Moderator Curhat.')}<section class="panel glass"><h2>Buat akun Moderator Curhat</h2><p class="source-line">Akun moderator memiliki akses global ke pesan curhat anonim. Berikan akses hanya kepada petugas yang ditunjuk dan sampaikan kata sandi sementara melalui kanal terpisah.</p><form id="centralCreateModerator" class="form-grid">${formField('Nama lengkap','moderatorFullName','Nama lengkap')}${formField('Email','moderatorEmail','moderator@jalur.id','email')}${formField('Kata sandi sementara (minimal 14 karakter)','moderatorPassword','Kata sandi kuat','password')}<div class="field full"><button class="btn primary">Buat akun Moderator Curhat</button></div></form></section>`;
      const f=$('#centralCreateModerator');
      f.onsubmit=async e=>{e.preventDefault();const btn=f.querySelector('button');btn.disabled=true;try{const d=await api('/platform/users',{method:'POST',body:{full_name:$('#moderatorFullName').value.trim(),email:$('#moderatorEmail').value.trim(),temporary_password:$('#moderatorPassword').value}});notice(d.message||'Akun Moderator Curhat berhasil dibuat.');f.reset();}catch(err){notice(err.message);}finally{btn.disabled=false;}};
      return;
    }
    if(page==='server-home'){const [grades,appts]=await Promise.all([api('/grades').catch(()=>({items:[]})),Promise.resolve(null)]);root.innerHTML=`${pageHead('Ruang Siswa','Informasi pribadi diambil dari server sesuai akun yang sedang masuk.')}<section class="dashboard-welcome panel glass"><div class="dashboard-welcome-copy"><span class="eyebrow">RUANG EKSPLORASI PRIBADIMU</span><h1>Halo, ${esc(user.full_name||user.email||'Siswa')}.</h1><p>Selamat datang kembali. Kamu dapat meninjau catatan akademik, mengajukan konsultasi, dan melanjutkan eksplorasi pendidikan dari sini.</p></div><div class="dashboard-welcome-mark" aria-hidden="true"><span>✳</span><small>KENALI, JELAJAHI, DAN PERTIMBANGKAN</small></div></section><div class="card-grid"><article class="panel glass"><h2>Rapor Saya</h2><p>${grades.items.length} catatan nilai tersedia.</p><button class="btn primary" data-server-page="grades">Buka rapor</button></article><article class="panel glass"><h2>Konsultasi BK</h2><p>Ajukan waktu konsultasi ke sekolah yang terhubung dengan akunmu.</p><button class="btn primary" data-server-page="appointment">Ajukan konsultasi</button></article><article class="panel glass"><h2>Curhat anonim</h2><p>Pesan dikirim tanpa mengaitkannya dengan akun siswa.</p><button class="btn secondary" data-server-page="vent">Tulis curhat anonim</button></article><article class="panel glass"><h2>Direktori pendidikan</h2><p>Cari perguruan tinggi dan program studi dari database terpusat.</p><button class="btn secondary" data-server-page="directory">Cari universitas / prodi</button></article></div>`;return;}
    if(page==='grades'||page==='server-grades'){const d=await api('/grades');const canEdit=user.role==='teacher'||user.role==='school_admin';let roster={classes:[],students:[]};if(canEdit)roster=await api('/grades/roster');root.innerHTML=`${pageHead('Data Rapor','Nilai tersimpan di Supabase dan dibatasi menurut sekolah, akun siswa, serta penugasan guru.')}${gradeTrend(d.items||[])}<section class="panel glass section-gap"><div class="panel-head"><h2>Daftar nilai</h2><span class="data-tag">Server</span></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Siswa</th><th>Mata pelajaran</th><th>Semester</th><th>Tahun ajaran</th><th>Nilai</th>${canEdit?'<th>Aksi</th>':''}</tr></thead><tbody>${d.items.length?d.items.map(x=>`<tr><td>${esc(x.student_name||'Nilai saya')}</td><td>${esc(x.subject_name)}</td><td>${esc(x.semester)}</td><td>${esc(x.academic_year)}</td><td><strong>${esc(x.score)}</strong></td>${canEdit?`<td><button class="text-btn" data-grade-edit="${esc(x.id)}">Edit</button><button class="text-btn" data-grade-delete="${esc(x.id)}">Hapus</button></td>`:''}</tr>`).join(''):`<tr><td colspan="${canEdit?6:5}">Belum ada data rapor yang tersedia.</td></tr>`}</tbody></table></div></section>${canEdit?gradeForm(roster,(d.items||[]).find(x=>x.id===editingGradeId)||null):''}`;const gf=$('#centralGradeForm');if(gf)gf.onsubmit=async e=>{e.preventDefault();const btn=gf.querySelector('button');btn.disabled=true;try{await api(editingGradeId?'/grades/'+encodeURIComponent(editingGradeId):'/grades',{method:editingGradeId?'PATCH':'POST',body:{student_id:$('#gradeStudentId').value,class_id:$('#gradeClassId').value,subject_name:$('#gradeSubject').value.trim(),semester:$('#gradeSemester').value.trim(),academic_year:$('#gradeYear').value.trim(),score:Number($('#gradeScore').value),notes:$('#gradeNotes').value.trim()}});editingGradeId=null;notice('Nilai berhasil disimpan ke database.');serverPage('grades')}catch(err){notice(err.message)}finally{btn.disabled=false}};return;}

    if(page==='appointment'){
      const mine=await api('/bk/appointments/mine');
      root.innerHTML=`${pageHead('Konsultasi BK','Ajukan waktu pilihanmu. Guru BK meninjau permohonan, menyepakati waktu, lalu mengonfirmasi jadwal.')}<section class="panel glass"><form id="centralAppointment" class="form-grid">${formField('Usulan tanggal dan waktu','appointmentDate','','datetime-local')}<div class="field"><label for="appointmentMode">Metode</label><select id="appointmentMode"><option value="in_person">Tatap muka</option><option value="online">Daring</option></select></div><div class="field full"><label for="appointmentTopic">Topik konsultasi</label><select id="appointmentTopic"><option>Perencanaan studi lanjut</option><option>Kesulitan akademik</option><option>Pengembangan diri</option><option>Masalah sosial di sekolah</option><option>Lainnya</option></select></div><div class="field full"><label for="appointmentContext">Keterangan tambahan (opsional)</label><textarea id="appointmentContext" maxlength="1000"></textarea></div><div class="field full"><button class="btn primary">Kirim permohonan</button></div></form></section><section class="panel glass section-gap"><h2>Permohonan saya</h2>${mine.items.length?mine.items.map(a=>`<article class="program-card glass"><span class="program-kicker">${esc(a.status)}</span><h3>${esc(a.topic)}</h3><p>Usulan siswa: ${esc(new Date(a.requested_at).toLocaleString('id-ID'))}</p><p>${esc(a.counselor_note||'Menunggu peninjauan Guru BK.')}</p>${a.scheduled_at?`<p><strong>Penawaran BK: ${esc(new Date(a.scheduled_at).toLocaleString('id-ID'))}</strong></p>`:''}${a.status==='awaiting_confirmation'?`<button class="btn primary" data-bk-student-accept="${esc(a.id)}">Setujui waktu ini</button><button class="btn secondary" data-bk-student-change="${esc(a.id)}">Usulkan waktu lain</button>`:''}</article>`).join(''):'<p>Belum ada permohonan konsultasi.</p>'}</section>`;
      $('#centralAppointment').onsubmit=async e=>{e.preventDefault();const btn=e.target.querySelector('button');btn.disabled=true;try{const dt=new Date($('#appointmentDate').value);if(Number.isNaN(dt.getTime())||dt<=new Date())throw new Error('Pilih waktu di masa mendatang.');await api('/bk/appointments',{method:'POST',body:{requested_at:dt.toISOString(),mode:$('#appointmentMode').value,topic:$('#appointmentTopic').value,student_note:$('#appointmentContext').value}});notice('Permohonan masuk antrean peninjauan Guru BK.');serverPage('appointment');}catch(err){notice(err.message);}finally{btn.disabled=false;}};
      root.querySelectorAll('[data-bk-student-accept]').forEach(b=>b.onclick=async()=>{try{await api('/bk/appointments/'+b.dataset.bkStudentAccept+'/confirm-student',{method:'PATCH'});notice('Persetujuanmu tercatat. Guru BK akan melakukan konfirmasi akhir.');serverPage('appointment');}catch(err){notice(err.message);}});
      root.querySelectorAll('[data-bk-student-change]').forEach(b=>b.onclick=()=>{const raw=prompt('Masukkan waktu alternatif (YYYY-MM-DDTHH:mm)');if(!raw)return;const dt=new Date(raw);if(Number.isNaN(dt.getTime())||dt<=new Date()){notice('Waktu alternatif tidak valid.');return;}api('/bk/appointments/'+b.dataset.bkStudentChange+'/counter-proposal',{method:'PATCH',body:{requested_at:dt.toISOString()}}).then(()=>{notice('Usulan waktu alternatif dikirim.');serverPage('appointment');}).catch(err=>notice(err.message));});
      return;
    }

    if(page==='vent'){
      root.innerHTML=`${pageHead('RASA · Curhat Anonim','RASA (Ruang Aman, Suara, dan Aspirasi) menyediakan ruang untuk bercerita dan memperoleh pendampingan. Chat ini ditangani moderator, bukan chat langsung dengan Guru BK.')}<section class="panel glass"><div class="notice"><strong>Privasi:</strong> percakapan tidak ditautkan ke akun. Simpan kode akses rahasia; kode berlaku 30 hari dan tidak dapat dipulihkan jika hilang.</div><form id="rasaStart" class="form-grid"><div class="field"><label>Topik</label><select id="rasaCategory"><option value="academic">Akademik</option><option value="family">Keluarga</option><option value="friends">Teman</option><option value="future">Masa depan</option><option value="wellbeing">Keadaan diri</option><option value="other">Lainnya</option></select></div><div class="field full"><label for="rasaInitialText">Ceritakan hal yang ingin disampaikan</label><textarea id="rasaInitialText" minlength="3" maxlength="3000" required></textarea></div><div class="field full"><button class="btn primary">Mulai curhat anonim</button></div></form></section><section class="panel glass section-gap"><h2>Percakapan Saya</h2><form id="rasaAccess" class="form-grid"><div class="field full"><label for="rasaAccessCode">Kode akses</label><input id="rasaAccessCode" minlength="20" required autocomplete="off"></div><div class="field full"><button class="btn secondary">Buka percakapan</button></div></form></section><section id="rasaConversation" class="panel glass section-gap" hidden></section><p class="source-line">Jika kamu membutuhkan bantuan segera, hubungi orang dewasa tepercaya atau layanan darurat setempat.</p>`;
      let code='',conversationId='';
      const show=async data=>{conversationId=data.conversation.id;const box=$('#rasaConversation');box.hidden=false;box.innerHTML='<h2>Percakapan anonim</h2><div class="rasa-messages">'+data.messages.map(m=>'<article class="summary-block"><strong>'+(m.sender==='moderator'?'Moderator':'Kamu')+'</strong><p>'+esc(m.text)+'</p><small>'+esc(new Date(m.created_at).toLocaleString('id-ID'))+'</small></article>').join('')+'</div><form id="rasaReply" class="form-grid"><div class="field full"><label>Balas</label><textarea id="rasaReplyText" required maxlength="3000"></textarea></div><div class="field full"><button class="btn primary">Kirim balasan</button></div></form>';$('#rasaReply').onsubmit=async ev=>{ev.preventDefault();const btn=ev.target.querySelector('button');btn.disabled=true;try{const response=await fetch(apiBase+'/rasa/conversations/'+conversationId+'/messages',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json','X-RASA-ACCESS-CODE':code},body:JSON.stringify({text:$('#rasaReplyText').value})});const result=await response.json();if(!response.ok)throw new Error(result.detail||'Balasan gagal dikirim.');const fresh=await api('/rasa/conversations/access',{method:'POST',body:{access_code:code}});show(fresh);}catch(err){notice(err.message);}finally{btn.disabled=false;}};};
      $('#rasaStart').onsubmit=async e=>{e.preventDefault();const btn=e.target.querySelector('button');btn.disabled=true;try{const d=await api('/rasa/conversations',{method:'POST',body:{category:$('#rasaCategory').value,text:$('#rasaInitialText').value}});code=d.access_code;modal('Simpan kode akses rahasia','<p>Kode hanya ditampilkan sekali. Simpan untuk membuka percakapan kembali.</p><input id="rasaCodeOnce" readonly value="'+esc(code)+'"><button type="button" class="btn primary" id="rasaCopyOnce">Salin kode</button>');$('#rasaCopyOnce').onclick=()=>navigator.clipboard?.writeText(code).then(()=>notice('Kode disalin.')).catch(()=>notice('Silakan salin kode secara manual.'));const loaded=await api('/rasa/conversations/access',{method:'POST',body:{access_code:code}});show(loaded);e.target.reset();}catch(err){notice(err.message);}finally{btn.disabled=false;}};
      $('#rasaAccess').onsubmit=async e=>{e.preventDefault();try{code=$('#rasaAccessCode').value.trim();show(await api('/rasa/conversations/access',{method:'POST',body:{access_code:code}}));}catch(err){notice(err.message);}};
      return;
    }

    if(page==='server-bk'){
      const [d,referrals]=await Promise.all([api('/bk/appointments'),api('/rasa/bk/referrals').catch(()=>({items:[]}))]);
      root.innerHTML=`${pageHead('Portal Guru BK','Tinjau semua permohonan, tawarkan waktu, tunggu persetujuan siswa, lalu konfirmasi jadwal. Rujukan moderator tersedia terpisah.')}<section class="panel glass"><h2>Permohonan konsultasi</h2>${d.items.length?d.items.map(a=>`<article class="program-card glass"><span class="program-kicker">${esc(a.status)}</span><h3>${esc(a.student_name)} · ${esc(a.class_name||'Kelas belum diatur')}</h3><p>${esc(a.topic)} · ${esc(a.mode==='online'?'Daring':'Tatap muka')}</p><p>Usulan siswa: ${esc(new Date(a.requested_at).toLocaleString('id-ID'))}</p><p>${esc(a.student_note||'Tanpa catatan tambahan')}</p>${['pending_review','reschedule_requested'].includes(a.status)?`<div class="field"><label>Waktu penawaran BK</label><input type="datetime-local" data-bk-offer-time="${esc(a.id)}"></div><div class="field"><label>Catatan</label><input data-bk-offer-note="${esc(a.id)}" maxlength="1000"></div><button class="btn primary" data-bk-offer="${esc(a.id)}">Kirim penawaran waktu</button>`:''}${a.status==='awaiting_confirmation'?`<p><strong>Menunggu persetujuan siswa:</strong> ${esc(new Date(a.scheduled_at).toLocaleString('id-ID'))}</p>${a.student_accepted?'<p>Siswa sudah menyetujui. Jadwal siap dikonfirmasi.</p>':'<p>Menunggu persetujuan siswa.</p>'}<button class="btn primary" data-bk-final-confirm="${esc(a.id)}" ${a.student_accepted?'':'disabled'}>Konfirmasi jadwal</button>`:''}${a.status==='confirmed'?'<p><strong>Jadwal dikonfirmasi.</strong></p>':''}</article>`).join(''):'<p>Belum ada permohonan konsultasi.</p>'}</section><section class="panel glass section-gap"><h2>Rujukan dari Moderator</h2>${referrals.items.length?referrals.items.map(r=>`<article class="program-card glass"><span class="program-kicker">${r.urgent?'Prioritas keselamatan':'Rujukan pendampingan'}</span><p>${esc(r.summary)}</p><small>${r.consent?'Persetujuan siswa diberikan':'Pengecualian risiko mendesak'}</small></article>`).join(''):'<p>Belum ada rujukan.</p>'}</section>`;
      root.querySelectorAll('[data-bk-offer]').forEach(b=>b.onclick=async()=>{const id=b.dataset.bkOffer,raw=root.querySelector('[data-bk-offer-time="'+id+'"]')?.value;if(!raw){notice('Pilih waktu penawaran.');return;}const dt=new Date(raw);if(Number.isNaN(dt.getTime())||dt<=new Date()){notice('Waktu harus berada di masa mendatang.');return;}try{await api('/bk/appointments/'+id+'/review',{method:'PATCH',body:{decision:'awaiting_confirmation',proposed_at:dt.toISOString(),counselor_note:root.querySelector('[data-bk-offer-note="'+id+'"]')?.value||''}});notice('Penawaran dikirim ke siswa.');serverPage('server-bk');}catch(err){notice(err.message);}});
      root.querySelectorAll('[data-bk-final-confirm]').forEach(b=>b.onclick=async()=>{try{await api('/bk/appointments/'+b.dataset.bkFinalConfirm+'/confirm',{method:'PATCH'});notice('Jadwal berhasil dikonfirmasi.');serverPage('server-bk');}catch(err){notice(err.message);}});
      return;
    }

    if(page==='server-vent'){
      const d=await api('/rasa/moderator/queue');
      root.innerHTML=`${pageHead('RASA · Antrean Curhat','Antrean bersama. Moderator mengambil penugasan agar penanganan terkoordinasi dan tidak tumpang tindih.')}<section class="panel glass"><h2>Antrean bersama</h2>${d.items.length?d.items.map(v=>`<article class="program-card glass"><span class="program-kicker">${esc(v.status)} · ${esc(v.category)}</span><p>${v.message_count} pesan · ${v.assigned_moderator_id?'Sudah ditugaskan':'Belum ditugaskan'}</p><button class="btn primary" data-rasa-open="${esc(v.id)}">${v.assigned_to_me?'Buka percakapan':'Ambil penugasan'}</button></article>`).join(''):'<p>Antrean kosong.</p>'}</section><section id="moderatorConversation" class="panel glass section-gap" hidden></section>`;
      root.querySelectorAll('[data-rasa-open]').forEach(b=>b.onclick=async()=>{try{await api('/rasa/moderator/conversations/'+b.dataset.rasaOpen+'/assign',{method:'POST',body:{}});const data=await api('/rasa/moderator/conversations/'+b.dataset.rasaOpen);const box=$('#moderatorConversation');box.hidden=false;box.innerHTML='<h2>Percakapan</h2>'+data.messages.map(m=>'<article class="summary-block"><strong>'+(m.sender==='moderator'?'Moderator':'Pengunjung')+'</strong><p>'+esc(m.text)+'</p></article>').join('')+'<form id="modReply" class="form-grid"><div class="field full"><label>Balasan</label><textarea id="modReplyText" required maxlength="3000"></textarea></div><div class="field full"><button class="btn primary">Kirim balasan</button></div></form><button class="btn secondary" id="modClose">Tutup percakapan</button><button class="btn secondary" id="modRefer">Rujuk ke BK</button>';$('#modReply').onsubmit=async ev=>{ev.preventDefault();try{await api('/rasa/moderator/conversations/'+b.dataset.rasaOpen+'/messages',{method:'POST',body:{text:$('#modReplyText').value}});notice('Balasan dikirim.');serverPage('server-vent');}catch(err){notice(err.message);}};$('#modClose').onclick=async()=>{try{await api('/rasa/moderator/conversations/'+b.dataset.rasaOpen+'/status',{method:'PATCH',body:{status:'closed'}});serverPage('server-vent');}catch(err){notice(err.message);}};$('#modRefer').onclick=async()=>{const summary=prompt('Ringkasan seperlunya untuk Guru BK (jangan salin seluruh percakapan):');if(!summary)return;const consent=confirm('Siswa menyetujui rujukan?');const urgent=consent?false:confirm('Apakah ada risiko keselamatan mendesak sesuai kebijakan sekolah?');try{await api('/rasa/moderator/conversations/'+b.dataset.rasaOpen+'/referral',{method:'POST',body:{summary,consent,urgent}});notice('Rujukan dikirim.');serverPage('server-vent');}catch(err){notice(err.message);}};}catch(err){notice(err.message);}});
      return;
    }
    if(page==='server-school'){
      const [students,accounts,alumni,grades,classData,teacherData,assignmentData]=await Promise.all([
        api('/school/students').catch(()=>({items:[]})),
        api('/school/users?limit=500').catch(()=>({items:[],total:0})),
        api('/school/alumni').catch(()=>({items:[]})),
        api('/grades').catch(()=>({items:[]})),
        api('/school/classes').catch(()=>({items:[]})),
        api('/school/teachers').catch(()=>({items:[]})),
        api('/school/teacher-assignments').catch(()=>({items:[]}))
      ]);
      const classes=classData.items||[],teachers=teacherData.items||[],assignments=assignmentData.items||[];
      const accountRows=accounts.items||[];
      const studentCount=accountRows.filter(x=>x.role==='student').length;
      const teacherCount=accountRows.filter(x=>x.role==='teacher').length;
      const counselorCount=accountRows.filter(x=>x.role==='counselor').length;
      const classOptions='<option value="">Pilih kelas</option>'+classes.map(x=>'<option value="'+esc(x.id)+'">'+esc(x.name)+' dan '+esc(x.academic_year)+'</option>').join('');
      const teacherOptions='<option value="">Pilih guru</option>'+teachers.map(x=>'<option value="'+esc(x.id)+'">'+esc(x.full_name)+' dan '+esc(x.email)+'</option>').join('');
      const assignmentCards=assignments.length?assignments.map(x=>'<article class="program-card glass"><h3>'+esc(x.teacher_name)+'</h3><p>'+esc(x.class_name)+' dan '+esc(x.academic_year)+'</p><p>'+esc(x.subject_name)+'</p></article>').join(''):'<p>Belum ada penugasan guru. Tambahkan akun guru dan kelas terlebih dahulu.</p>';
      root.innerHTML=pageHead('Portal Pengelola Sekolah','Kelola akun, kelas, penugasan guru, dan data pendidikan. Semua perubahan disimpan ke database pusat.')+
        '<div class="card-grid"><article class="panel glass"><h2>Manajemen akun</h2><p>'+accounts.total+' akun sekolah terdaftar. '+studentCount+' siswa, '+teacherCount+' guru, dan '+counselorCount+' Guru BK tercatat.</p><button class="btn secondary" data-server-page="school-users">Kelola akun & pemulihan</button></article><article class="panel glass"><h2>Kelas</h2><p>'+classes.length+' kelas terdaftar.</p><button class="btn secondary" data-server-page="school-classes">Kelola kelas</button></article><article class="panel glass"><h2>Rapor</h2><p>'+grades.items.length+' catatan nilai dapat diakses peran ini.</p><button class="btn secondary" data-server-page="grades">Lihat rapor</button></article><article class="panel glass"><h2>Alumni</h2><p>'+alumni.items.length+' profil alumni.</p><button class="btn secondary" data-server-page="school-alumni">Kelola alumni</button></article><article class="panel glass"><h2>Direktori pendidikan</h2><button class="btn secondary" data-server-page="directory">Cari direktori</button></article></div>'+
        '<section class="panel glass section-gap"><h2>Buat akun siswa / guru / BK</h2><form id="centralCreateUser" class="form-grid">'+
        formField('Nama lengkap','newUserName','Nama lengkap')+formField('Email','newUserEmail','nama@sekolah.id','email')+formField('Kata sandi sementara (minimal 14 karakter)','newUserPassword','Kata sandi kuat','password')+
        '<div class="field"><label for="newUserRole">Peran</label><select id="newUserRole"><option value="student">Siswa</option><option value="teacher">Guru mata pelajaran</option><option value="counselor">Guru BK</option></select></div>'+
        '<div class="field" id="newStudentNumberField"><label for="newStudentNumber">Nomor induk siswa</label><input id="newStudentNumber" maxlength="40" placeholder="NIS"></div>'+
        '<div class="field" id="newStudentClassField"><label for="newStudentClass">Kelas siswa</label><select id="newStudentClass" required>'+classOptions+'</select></div>'+
        '<div class="field" id="newGradYearField"><label for="newGradYear">Tahun lulus (opsional)</label><input id="newGradYear" type="number" min="1950" max="2100" placeholder="2027"></div>'+
        '<div class="field full"><button class="btn primary">Buat akun</button></div></form></section>'+
        '<section class="panel glass section-gap"><h2>Penugasan guru</h2><p class="source-line">Guru hanya dapat melihat dan mengelola nilai sesuai kelas serta mata pelajaran yang ditugaskan.</p><form id="centralCreateAssignment" class="form-grid">'+
        '<div class="field"><label for="assignmentTeacher">Guru</label><select id="assignmentTeacher" required>'+teacherOptions+'</select></div>'+
        '<div class="field"><label for="assignmentClass">Kelas</label><select id="assignmentClass" required>'+classOptions+'</select></div>'+
        formField('Mata pelajaran','assignmentSubject','Misalnya, Matematika')+
        formField('Tahun ajaran','assignmentYear','2026/2027')+
        '<div class="field full"><button class="btn primary" '+(teachers.length&&classes.length?'':'disabled')+'>Simpan penugasan</button></div></form>'+
        '<h3>Penugasan tersimpan</h3>'+assignmentCards+'</section>';
      const roleSelect=$('#newUserRole');
      const syncStudentFields=()=>{const isStudent=roleSelect.value==='student';$('#newStudentNumberField').hidden=!isStudent;$('#newStudentClassField').hidden=!isStudent;$('#newGradYearField').hidden=!isStudent;$('#newStudentNumber').required=isStudent;$('#newStudentClass').required=isStudent;};
      roleSelect.onchange=syncStudentFields;syncStudentFields();
      $('#centralCreateUser').onsubmit=async e=>{
        e.preventDefault();const role=$('#newUserRole').value;
        try{
          const body={full_name:$('#newUserName').value.trim(),email:$('#newUserEmail').value.trim(),temporary_password:$('#newUserPassword').value,role};
          if(role==='student'){
            body.student_number=$('#newStudentNumber').value.trim();
            body.class_id=$('#newStudentClass').value;
            if($('#newGradYear').value)body.graduation_year=Number($('#newGradYear').value);
          }
          await api('/school/users',{method:'POST',body});
          notice('Akun berhasil dibuat. Sampaikan kata sandi sementara melalui kanal terpisah.');
          serverPage('server-school');
        }catch(err){notice(err.message)}
      };
      $('#centralCreateAssignment').onsubmit=async e=>{
        e.preventDefault();
        try{
          await api('/school/teacher-assignments',{method:'POST',body:{
            teacher_id:$('#assignmentTeacher').value,class_id:$('#assignmentClass').value,
            subject_name:$('#assignmentSubject').value.trim(),academic_year:$('#assignmentYear').value.trim()
          }});
          notice('Penugasan guru berhasil disimpan.');serverPage('server-school');
        }catch(err){notice(err.message)}
      };
      return;
    }
    if(page==='school-users'){
      const [accountData,classData,historyData]=await Promise.all([
        api('/school/users?limit=500'),
        api('/school/classes'),
        api('/school/account-history?limit=100')
      ]);
      const accounts=accountData.items||[],classes=classData.items||[],history=historyData.items||[];
      const roleLabel={student:'Siswa',teacher:'Guru mata pelajaran',counselor:'Guru BK'};
      const statusLabel={active:'Aktif',disabled:'Nonaktif',pending:'Menunggu'};
      const roleOptions='<option value="all">Semua peran</option><option value="student">Siswa</option><option value="teacher">Guru</option><option value="counselor">Guru BK</option>';
      const statusOptions='<option value="all">Semua status</option><option value="active">Aktif</option><option value="disabled">Nonaktif</option><option value="pending">Menunggu</option>';
      const rows=accounts.map(x=>{
        const search=[x.full_name,x.email,x.student_number,x.class_name].filter(Boolean).join(' ').toLowerCase();
        return '<tr data-school-user-row data-role="'+esc(x.role)+'" data-status="'+esc(x.status)+'" data-search="'+esc(search)+'">'+
          '<td><strong>'+esc(x.full_name)+'</strong><br><small>'+esc(x.email)+'</small></td>'+
          '<td>'+esc(roleLabel[x.role]||x.role)+'</td>'+
          '<td>'+(x.role==='student'?esc(x.student_number||'Belum ada NIS')+'<br><small>'+esc(x.class_name||'Belum masuk kelas')+'</small>':'—')+'</td>'+
          '<td><span class="data-tag">'+esc(statusLabel[x.status]||x.status)+'</span></td>'+
          '<td>'+esc(x.created_at?new Date(x.created_at).toLocaleDateString('id-ID'):'—')+'</td>'+
          '<td><div class="table-actions"><button class="btn secondary small" data-school-user-edit="'+esc(x.id)+'">Edit</button><button class="btn secondary small" data-school-user-reset="'+esc(x.id)+'">Reset sandi</button><button class="btn secondary small" data-school-user-status="'+esc(x.id)+'" data-next-status="'+(x.status==='active'?'disabled':'active')+'">'+(x.status==='active'?'Nonaktifkan':'Aktifkan')+'</button></div></td></tr>';
      }).join('');
      const historyRows=history.map(x=>{
        const labels={'school_user.create':'Akun dibuat','school_user.update':'Data akun diubah','school_user.status':'Status akun diubah','school_user.password_reset':'Password direset','school_class.create':'Kelas dibuat','school_class.update':'Data kelas diubah'};
        const target=x.target_name||x.class_name||x.entity_id||'—';
        return '<tr><td>'+esc(labels[x.action]||x.action)+'</td><td>'+esc(target)+'</td><td>'+esc(x.target_email||'—')+'</td><td>'+esc(x.actor_name||'Pengelola')+'</td><td>'+esc(x.created_at?new Date(x.created_at).toLocaleString('id-ID'):'—')+'</td></tr>';
      }).join('');
      root.innerHTML=pageHead('Manajemen Akun Sekolah','Tinjau seluruh akun siswa, guru, dan Guru BK; perbarui data; aktifkan atau nonaktifkan akses; serta bantu pemulihan akun.')+
        '<section class="panel glass"><div class="panel-head"><h2>Daftar akun</h2><span class="data-tag">'+accountData.total+' akun</span></div>'+
        '<p class="notice">Password lama tidak dapat dibaca oleh siapa pun. Pengelola dapat membuat password sementara baru ketika pengguna lupa, lalu menyampaikannya melalui kanal terpisah. Password sementara hanya ditampilkan satu kali.</p>'+
        '<div class="search-row"><input id="schoolUserSearch" class="search-input" placeholder="Cari nama, email, NIS, atau kelas…" autocomplete="off"><select id="schoolUserRoleFilter" class="filter-select">'+roleOptions+'</select><select id="schoolUserStatusFilter" class="filter-select">'+statusOptions+'</select></div>'+
        '<div class="table-wrap"><table class="data-table"><thead><tr><th>Pengguna</th><th>Peran</th><th>Data siswa</th><th>Status</th><th>Terdaftar</th><th>Aksi</th></tr></thead><tbody id="schoolUserRows">'+(rows||'<tr><td colspan="6">Belum ada akun.</td></tr>')+'</tbody></table></div>'+
        (accountData.total>accounts.length?'<p class="source-line">Menampilkan '+accounts.length+' dari '+accountData.total+' akun. Gunakan pencarian untuk mempersempit hasil.</p>':'')+
        '</section><section class="panel glass section-gap"><div class="panel-head"><h2>Riwayat pengelolaan</h2><span class="data-tag">100 terbaru</span></div>'+
        '<p class="source-line">Riwayat memuat pembuatan dan perubahan akun, perubahan status, reset password, serta perubahan kelas. Password dan token tidak pernah dicatat.</p>'+
        (history.length?'<div class="table-wrap"><table class="data-table"><thead><tr><th>Tindakan</th><th>Pengguna / kelas</th><th>Email</th><th>Dilakukan oleh</th><th>Waktu</th></tr></thead><tbody>'+historyRows+'</tbody></table></div>':'<p>Belum ada riwayat perubahan akun yang tercatat.</p>')+
        '</section>';
      const applyFilters=()=>{
        const q=$('#schoolUserSearch').value.trim().toLowerCase(),role=$('#schoolUserRoleFilter').value,status=$('#schoolUserStatusFilter').value;
        $('#schoolUserRows').querySelectorAll('[data-school-user-row]').forEach(row=>{
          row.hidden=!!((q&&!row.dataset.search.includes(q))||(role!=='all'&&row.dataset.role!==role)||(status!=='all'&&row.dataset.status!==status));
        });
      };
      $('#schoolUserSearch').oninput=applyFilters;$('#schoolUserRoleFilter').onchange=applyFilters;$('#schoolUserStatusFilter').onchange=applyFilters;
      return;
    }
    if(page==='school-classes'){
      const [classData,teacherData]=await Promise.all([
        api('/school/classes'),
        api('/school/users?role=teacher&status=active&limit=500')
      ]);
      const classes=classData.items||[],teachers=teacherData.items||[];
      root.innerHTML=pageHead('Pengelolaan Kelas','Buat kelas baru, ubah nama dan tahun ajaran, tetapkan wali kelas, serta tinjau siswa pada setiap kelas.')+
        '<section class="panel glass"><h2>Tambah kelas</h2><form id="centralCreateClass" class="form-grid">'+
        formField('Nama kelas','classNameServer','Contoh: X-1, XI IPA 2, atau XII IPS 1')+
        formField('Tahun ajaran','classYearServer','2026/2027')+
        '<div class="field full"><button class="btn primary">Simpan kelas</button></div></form></section>'+
        '<section class="panel glass section-gap"><div class="panel-head"><h2>Daftar kelas</h2><span class="data-tag">'+classes.length+' kelas</span></div>'+
        (classes.length?'<div class="table-wrap"><table class="data-table"><thead><tr><th>Kelas</th><th>Wali kelas</th><th>Siswa</th><th>Aksi</th></tr></thead><tbody>'+
          classes.map(x=>'<tr><td><strong>'+esc(x.name)+'</strong><br><small>'+esc(x.academic_year)+'</small></td><td>'+esc(x.homeroom_teacher_name||'Belum ditetapkan')+'</td><td>'+Number(x.student_count||0)+'</td><td><div class="table-actions"><button class="btn secondary small" data-school-class-edit="'+esc(x.id)+'">Edit</button><button class="btn secondary small" data-school-class-roster="'+esc(x.id)+'">Lihat siswa</button></div></td></tr>').join('')+
          '</tbody></table></div>':'<p>Belum ada kelas terdaftar. Tambahkan kelas pertama menggunakan formulir di atas.</p>')+'</section>';
      $('#centralCreateClass').onsubmit=async e=>{e.preventDefault();try{
        await api('/school/classes',{method:'POST',body:{name:$('#classNameServer').value.trim(),academic_year:$('#classYearServer').value.trim()}});
        notice('Kelas tersimpan.');serverPage('school-classes');
      }catch(err){notice(err.message)}};
      return;
    }
    if(page==='school-alumni'){const d=await api('/school/alumni');const currentYear=new Date().getFullYear();const yearOptions=Array.from({length:151},(_,i)=>2100-i).map(y=>'<option value="'+y+'">'+y+'</option>').join('');root.innerHTML=`${pageHead('Data Alumni','Catat informasi alumni setelah memperoleh persetujuan yang diperlukan agar informasi yang dibagikan tetap menghormati privasi mereka.')}<section class="panel glass"><form id="centralCreateAlumni" class="form-grid">${formField('Nama alumni','alumniNameServer','Nama lengkap')}<div class="field"><label for="alumniYearServer">Tahun lulus</label><select id="alumniYearServer" required><option value="">Pilih tahun</option>${yearOptions}</select></div><div class="field"><label for="alumniNextServer">Langkah setelah lulus</label><select id="alumniNextServer"><option value="">Belum ditentukan</option><option value="Melanjutkan pendidikan">Melanjutkan pendidikan</option><option value="Bekerja">Bekerja</option><option value="Wirausaha">Wirausaha</option><option value="Gap year">Gap year</option><option value="Lainnya">Lainnya</option></select></div>${formField('Perguruan tinggi / tempat','alumniInstitutionServer','Nama institusi','text',false)}${formField('Program studi','alumniProgramServer','Nama program studi','text',false)}<div class="field full"><label class="choice-check"><input id="alumniConsentServer" type="checkbox"> <span>Alumni menyetujui informasi ini dibagikan</span></label></div><div class="field full"><button class="btn primary" type="submit">Simpan alumni</button></div></form><h2>Alumni tersimpan</h2>${d.items.map(a=>`<article class="program-card glass"><h3>${esc(a.full_name)}</h3><p>${esc(a.graduation_year)} dan ${esc(a.next_step||'Belum ditentukan')}</p><p>${esc(a.institution||'Belum dicantumkan')} dan ${esc(a.program||'Belum dicantumkan')}</p><p>Persetujuan berbagi informasi ${a.consent_to_share?'Diberikan':'Belum diberikan'}</p></article>`).join('')||'<p>Belum ada data alumni.</p>'}</section>`;$('#centralCreateAlumni').onsubmit=async e=>{e.preventDefault();try{const year=Number($('#alumniYearServer').value);if(!Number.isInteger(year)||year<1950||year>2100)throw new Error('Pilih tahun kelulusan yang valid.');await api('/school/alumni',{method:'POST',body:{full_name:$('#alumniNameServer').value.trim(),graduation_year:year,next_step:$('#alumniNextServer').value.trim(),institution:$('#alumniInstitutionServer').value.trim(),program:$('#alumniProgramServer').value.trim(),consent_to_share:$('#alumniConsentServer').checked}});notice('Data alumni berhasil disimpan.');serverPage('school-alumni')}catch(err){notice(err.message)}};$('#alumniYearServer').value=String(currentYear);return;}
  }catch(err){root.innerHTML=`${pageHead('Tidak dapat memuat halaman','Periksa koneksi backend dan izin akun.')}<section class="panel glass"><p role="alert">${esc(err.message)}</p><button class="btn secondary" id="centralRetry">Coba lagi</button></section>`;$('#centralRetry').onclick=()=>serverPage(page);}}
  function gradeForm(roster,existing=null){const classes=roster.classes||[],students=roster.students||[];return `<section class="panel glass section-gap"><h2>${existing?'Edit nilai':'Input nilai'}</h2><p class="source-line">Pilih siswa yang terdaftar di sekolah. Guru hanya dapat mengisi nilai untuk kelas dan mata pelajaran yang termasuk dalam penugasannya.</p><form id="centralGradeForm" class="form-grid"><div class="field"><label for="gradeStudentId">Siswa</label><select id="gradeStudentId" required><option value="">Pilih siswa</option>${students.map(x=>`<option value="${esc(x.id)}" ${existing?.student_id===x.id?'selected':''}>${esc(x.full_name)} dan ${esc(x.student_number||'tanpa NIS')} dan ${esc(x.class_name||'Belum ada kelas')}</option>`).join('')}</select></div><div class="field"><label for="gradeClassId">Kelas</label><select id="gradeClassId" required><option value="">Pilih kelas</option>${classes.map(x=>`<option value="${esc(x.id)}" ${existing?.class_id===x.id?'selected':''}>${esc(x.name)} dan ${esc(x.academic_year)}</option>`).join('')}</select></div><div class="field"><label for="gradeSubject">Mata pelajaran</label><input id="gradeSubject" maxlength="120" required value="${esc(existing?.subject_name||'')}" placeholder="Nama mata pelajaran"></div><div class="field"><label for="gradeSemester">Semester</label><input id="gradeSemester" maxlength="30" required value="${esc(existing?.semester||'')}" placeholder="Semester 1"></div><div class="field"><label for="gradeYear">Tahun ajaran</label><input id="gradeYear" maxlength="20" required value="${esc(existing?.academic_year||'')}" placeholder="2026/2027"></div><div class="field"><label for="gradeScore">Nilai 0–100</label><input id="gradeScore" type="number" min="0" max="100" step=".01" required value="${existing?.score??''}" placeholder="0–100"></div><div class="field full"><label for="gradeNotes">Keterangan nilai (opsional)</label><select id="gradeNotes"><option value="">Tidak ada keterangan</option><option ${existing?.notes==='Nilai remedial'?'selected':''}>Nilai remedial</option><option ${existing?.notes==='Nilai susulan'?'selected':''}>Nilai susulan</option><option ${existing?.notes==='Penilaian proyek'?'selected':''}>Penilaian proyek</option><option ${existing?.notes==='Penilaian praktik'?'selected':''}>Penilaian praktik</option><option ${existing?.notes==='Perlu tindak lanjut'?'selected':''}>Perlu tindak lanjut</option></select></div><div class="field full"><button class="btn primary">${existing?'Perbarui nilai':'Simpan nilai'}</button>${existing?'<button class="btn secondary" type="button" id="cancelGradeEdit">Batal edit</button>':''}</div></form></section>`;}
  function gradeTrend(items){const groups=new Map();for(const g of items){const key=g.academic_year+'|'+g.semester;const x=groups.get(key)||{year:g.academic_year,semester:g.semester,sum:0,count:0};x.sum+=Number(g.score);x.count++;groups.set(key,x)}const rows=[...groups.values()].map(x=>({...x,avg:x.sum/x.count,yearN:Number((String(x.year).match(/\\d{4}/)||[])[0])||0,semN:Number((String(x.semester).match(/\\d+/)||[])[0])||0})).sort((a,b)=>a.yearN-b.yearN||a.semN-b.semN);if(!rows.length)return '<p class="source-line">Belum ada nilai untuk dibuatkan grafik.</p>';const w=700,h=220,L=42,R=18,T=18,B=45,X=i=>rows.length===1?w/2:L+i*(w-L-R)/(rows.length-1),Y=v=>T+(100-v)*(h-T-B)/100,pts=rows.map((r,i)=>[X(i),Y(r.avg)]),path=pts.map((p,i)=>(i?'L':'M')+p[0]+','+p[1]).join(' '),grid=[0,25,50,75,100].map(v=>'<line x1="'+L+'" y1="'+Y(v)+'" x2="'+(w-R)+'" y2="'+Y(v)+'" class="grade-chart-grid"/><text x="'+(L-9)+'" y="'+(Y(v)+4)+'" text-anchor="end" class="grade-chart-axis">'+v+'</text>').join(''),dots=pts.map((p,i)=>{const detail=rows[i].semester+" "+rows[i].year+" · Rata-rata "+rows[i].avg.toFixed(1)+" · "+rows[i].count+" catatan nilai";return '<circle cx="'+p[0]+'" cy="'+p[1]+'" r="6" tabindex="0" role="button" aria-label="'+esc(detail)+'" data-grade-tooltip="'+esc(detail)+'" class="grade-chart-point"><title>'+esc(detail)+'</title></circle>'}).join(''),labels=rows.map((r,i)=>'<text x="'+X(i)+'" y="'+(h-17)+'" text-anchor="middle" class="grade-chart-label">'+esc(r.semester+' dan '+r.year)+'</text>').join(' '),delta=rows[rows.length-1].avg-rows[0].avg,caption=rows.length<2?'Perlu minimal dua semester untuk menghitung tren.':Math.abs(delta)<.05?'Rata-rata stabil.':(delta>0?'Meningkat ':'Menurun ')+Math.abs(delta).toFixed(1)+' poin dari periode pertama.';return '<section class="panel glass section-gap"><div class="panel-head"><div><h2>Grafik perkembangan nilai</h2><p class="panel-sub">Rata-rata berdasarkan rapor tersimpan.</p></div><span class="data-tag">Data server</span></div><div class="grade-chart-wrap"><svg class="grade-trend-svg" viewBox="0 0 '+w+' '+h+'" role="img" aria-label="Tren nilai per semester">'+grid+(rows.length>1?'<path d="'+path+'" class="grade-chart-line"/>':'')+dots+labels+'</svg><div class="grade-chart-tooltip" role="status" aria-live="polite" hidden></div></div><p class="source-line">'+esc(caption)+'</p><button class="btn secondary small" id="printGrades">Cetak / simpan PDF</button></section>';}
function wireDirectory(){let timer,offset=0,requestSeq=0,activeController=null;const query=$('#directoryQuery'),type=$('#directoryType'),results=$('#directoryResults'),meta=$('#directoryMeta'),more=$('#directoryMore');async function run(append=false){const q=query.value.trim(),selectedType=type.value;if(q.length<2){requestSeq++;activeController?.abort();results.innerHTML='';meta.textContent='Masukkan sedikitnya dua karakter agar pencarian dapat menampilkan hasil yang sesuai.';more.hidden=true;return;}if(!append){offset=0;results.innerHTML='<p>Mencari…</p>';more.hidden=true;}const seq=++requestSeq;activeController?.abort();activeController=new AbortController();const controller=activeController;try{const d=await api(`/directory/search?q=${encodeURIComponent(q)}&type=${encodeURIComponent(selectedType)}&limit=25&offset=${offset}`,{signal:controller.signal});if(seq!==requestSeq||q!==query.value.trim()||selectedType!==type.value)return;const rows=d.items||[];meta.textContent=`${Number(d.total||0).toLocaleString('id-ID')} hasil dan urutan alfabetis A–Z`;results.insertAdjacentHTML(append?'beforeend':'afterbegin',rows.map(x=>`<article class="program-card glass"><span class="program-kicker">${esc(x.type==='institution'?'Perguruan tinggi':'Program studi')}${x.level?' dan '+esc(x.level):''}</span><h3>${esc(x.name)}</h3><p>${esc(x.institution_name||x.data?.province||x.data?.lokasi||'')}</p></article>`).join('')||(!append?'<p>Tidak ada hasil yang cocok.</p>':''));offset+=rows.length;more.hidden=offset>=Number(d.total||0)||!rows.length;}catch(err){if(err.name==='AbortError')return;if(seq===requestSeq){meta.textContent=err.message;more.hidden=true;}}}query.addEventListener('input',()=>{clearTimeout(timer);activeController?.abort();timer=setTimeout(()=>run(false),180)});type.addEventListener('change',()=>{clearTimeout(timer);run(false)});more.onclick=()=>run(true);}
  function roleRoute(page,role){
    const studentTools=["Academic Profile","Study Tracer Alumni","Decision Comparison","Plan B Builder","Decision Blind Spot Detector","Decision Summary","Program Study Reality Check","Similarity Explorer","Alternative Pathway Planner","Campus Life Preview","Education Cost Planner","Decision Journal"];
    if(page==="Dashboard")return ({student:"server-home",school_admin:"server-school",teacher:"server-grades",counselor:"server-bk",wellbeing_moderator:"server-vent",platform_admin:"server-platform"})[role]??null;
    if(page==="Study Program Explorer")return undefined;
    if(["Study Tracer Alumni","SNBT Predictor","SNBP Data"].includes(page))return undefined;
    if(page==="School Portal")return role==="school_admin"?"server-school":null;
    if(page==="BK Portal")return role==="counselor"?"server-bk":null;
    if(page==="BK Consultation")return role==="student"?"appointment":null;
    if(page==="Anonymous Venting")return role==="student"||role==="guest"?"vent":role==="wellbeing_moderator"?"server-vent":null;
    if(page==="Academic Profile")return role==="student"?undefined:role==="teacher"?"grades":null;
    if(studentTools.includes(page))return role==="student"||role==="guest"?undefined:null;
    if(page==="Settings")return role==="platform_admin"?"server-platform":undefined;
    if(["Help / About","User Guide","Official Sources"].includes(page))return undefined;
    return null;
  }
  document.addEventListener('click',e=>{
    const p=e.target.closest('[data-server-page]');
    if(p){e.preventDefault();serverPage(p.dataset.serverPage);return;}
    const nav=e.target.closest('[data-page]');
    if(!nav||!user)return;
    const destination=roleRoute(nav.dataset.page,user.role);
    if(destination===undefined)return;
    e.preventDefault();e.stopImmediatePropagation();
    if(destination===null){notice('Akun ini tidak memiliki akses ke halaman tersebut.');return;}
    serverPage(destination);
  },true);
  document.addEventListener('click',async e=>{
    const editUser=e.target.closest('[data-school-user-edit]');
    if(editUser){
      try{
        const [data,classData]=await Promise.all([api('/school/users?limit=500'),api('/school/classes')]);
        const account=(data.items||[]).find(x=>x.id===editUser.dataset.schoolUserEdit);
        if(!account)throw new Error('Akun tidak ditemukan.');
        const isStudent=account.role==='student';
        const classOptions='<option value="">Belum ditetapkan</option>'+(classData.items||[]).map(x=>'<option value="'+esc(x.id)+'" '+(x.id===account.class_id?'selected':'')+'>'+esc(x.name)+' · '+esc(x.academic_year)+'</option>').join('');
        modal('Edit data akun', '<form id="schoolAccountEditForm" class="form-grid">'+
          formField('Nama lengkap','editAccountName','Nama lengkap')+
          formField('Email','editAccountEmail','nama@sekolah.id','email')+
          (isStudent?'<div class="field"><label for="editAccountNis">Nomor induk siswa</label><input id="editAccountNis" maxlength="40" required value="'+esc(account.student_number||'')+'"></div>'+
          '<div class="field"><label for="editAccountClass">Kelas</label><select id="editAccountClass">'+classOptions+'</select></div>'+
          '<div class="field"><label for="editAccountGrad">Tahun lulus (opsional)</label><input id="editAccountGrad" type="number" min="1950" max="2100" value="'+esc(account.graduation_year??'')+'"></div>':'')+
          '<div class="field full"><button class="btn primary" type="submit">Simpan perubahan</button></div></form>');
        $('#editAccountName').value=account.full_name||'';$('#editAccountEmail').value=account.email||'';
        $('#schoolAccountEditForm').onsubmit=async ev=>{
          ev.preventDefault();
          const body={full_name:$('#editAccountName').value.trim(),email:$('#editAccountEmail').value.trim()};
          if(isStudent){
            body.student_number=$('#editAccountNis').value.trim();
            body.class_id=$('#editAccountClass').value||null;
            body.graduation_year=$('#editAccountGrad').value?Number($('#editAccountGrad').value):null;
          }
          try{
            await api('/school/users/'+encodeURIComponent(account.id),{method:'PATCH',body});
            dismissLoginModal();notice('Data akun berhasil diperbarui.');serverPage('school-users');
          }catch(err){notice(err.message);}
        };
      }catch(err){notice(err.message);}
      return;
    }
    const resetUser=e.target.closest('[data-school-user-reset]');
    if(resetUser){
      if(!confirm('Buat password sementara baru untuk akun ini? Password lama akan langsung tidak berlaku dan semua sesi aktif akan dikeluarkan.'))return;
      try{
        const result=await api('/school/users/'+encodeURIComponent(resetUser.dataset.schoolUserReset)+'/reset-password',{method:'POST'});
        modal('Password sementara berhasil dibuat','<p>Password baru ini hanya ditampilkan sekarang. Salin dan sampaikan kepada pemilik akun melalui kanal terpisah.</p>'+
          '<div class="field"><label for="oneTimeResetPassword">Password sementara</label><input id="oneTimeResetPassword" type="text" readonly value="'+esc(result.temporary_password)+'"></div>'+
          '<button class="btn primary" type="button" id="copyOneTimeResetPassword">Salin password</button><p class="source-line">Riwayat hanya mencatat waktu reset dan pengelolanya, bukan isi password.</p>');
        $('#copyOneTimeResetPassword').onclick=async()=>{
          const field=$('#oneTimeResetPassword');
          try{await navigator.clipboard.writeText(result.temporary_password);notice('Password sementara disalin.');}
          catch{field.select();document.execCommand('copy');notice('Password sementara disalin.');}
        };
        serverPage('school-users');
      }catch(err){notice(err.message);}
      return;
    }
    const statusUser=e.target.closest('[data-school-user-status]');
    if(statusUser){
      const next=statusUser.dataset.nextStatus;
      if(!confirm(next==='disabled'?'Nonaktifkan akun ini? Semua sesi aktifnya akan dicabut.':'Aktifkan kembali akun ini?'))return;
      try{
        await api('/school/users/'+encodeURIComponent(statusUser.dataset.schoolUserStatus)+'/status',{method:'PATCH',body:{status:next}});
        notice('Status akun berhasil diperbarui.');serverPage('school-users');
      }catch(err){notice(err.message);}
      return;
    }
    const editClass=e.target.closest('[data-school-class-edit]');
    if(editClass){
      try{
        const [classData,teacherData]=await Promise.all([api('/school/classes'),api('/school/users?role=teacher&status=active&limit=500')]);
        const item=(classData.items||[]).find(x=>x.id===editClass.dataset.schoolClassEdit);
        if(!item)throw new Error('Kelas tidak ditemukan.');
        const teacherOptions='<option value="">Belum ditetapkan</option>'+(teacherData.items||[]).map(t=>'<option value="'+esc(t.id)+'" '+(t.id===item.homeroom_teacher_id?'selected':'')+'>'+esc(t.full_name)+' · '+esc(t.email)+'</option>').join('');
        modal('Edit kelas','<form id="schoolClassEditForm" class="form-grid">'+
          formField('Nama kelas','editClassName','Nama kelas')+
          formField('Tahun ajaran','editClassYear','2026/2027')+
          '<div class="field full"><label for="editClassHomeroom">Wali kelas</label><select id="editClassHomeroom">'+teacherOptions+'</select></div>'+
          '<div class="field full"><button class="btn primary" type="submit">Simpan perubahan kelas</button></div></form>');
        $('#editClassName').value=item.name||'';$('#editClassYear').value=item.academic_year||'';
        $('#schoolClassEditForm').onsubmit=async ev=>{
          ev.preventDefault();
          try{
            await api('/school/classes/'+encodeURIComponent(item.id),{method:'PATCH',body:{name:$('#editClassName').value.trim(),academic_year:$('#editClassYear').value.trim(),homeroom_teacher_id:$('#editClassHomeroom').value||null}});
            dismissLoginModal();notice('Data kelas berhasil diperbarui.');serverPage('school-classes');
          }catch(err){notice(err.message);}
        };
      }catch(err){notice(err.message);}
      return;
    }
    const classRoster=e.target.closest('[data-school-class-roster]');
    if(classRoster){
      try{
        const [classData,students]=await Promise.all([api('/school/classes'),api('/school/users?role=student&status=all&limit=500')]);
        const item=(classData.items||[]).find(x=>x.id===classRoster.dataset.schoolClassRoster);
        if(!item)throw new Error('Kelas tidak ditemukan.');
        const members=(students.items||[]).filter(x=>x.class_id===item.id);
        const rosterRows=members.map(x=>'<tr><td>'+esc(x.full_name)+'</td><td>'+esc(x.student_number||'—')+'</td><td>'+esc(x.email)+'</td><td><button class="btn secondary small" data-school-user-edit="'+esc(x.id)+'">Edit</button></td></tr>').join('');
        modal('Siswa · '+item.name,'<p class="source-line">'+members.length+' siswa terdaftar pada '+esc(item.academic_year)+'. Untuk memindahkan siswa, pilih kelas lain pada menu Edit akun.</p>'+
          (members.length?'<div class="table-wrap"><table class="data-table"><thead><tr><th>Nama</th><th>NIS</th><th>Email</th><th>Aksi</th></tr></thead><tbody>'+rosterRows+'</tbody></table></div>':'<p>Belum ada siswa di kelas ini.</p>'));
      }catch(err){notice(err.message);}
      return;
    }
  });
  document.addEventListener('click',async e=>{const edit=e.target.closest('[data-grade-edit]');if(edit){editingGradeId=edit.dataset.gradeEdit;serverPage('grades');return;}if(e.target.closest('#cancelGradeEdit')){editingGradeId=null;serverPage('grades');return;}const del=e.target.closest('[data-grade-delete]');if(del){if(!confirm('Hapus nilai ini?'))return;try{await api('/grades/'+encodeURIComponent(del.dataset.gradeDelete),{method:'DELETE'});notice('Nilai dihapus.');serverPage('grades')}catch(err){notice(err.message)}return;}if(e.target.closest('#printGrades'))window.print();});
  document.addEventListener('click',e=>{if(e.target.closest('#centralLogout')){api('/auth/logout',{method:'POST'}).catch(()=>{}).finally(()=>{sessionStorage.removeItem('jalur-app-open');sessionStorage.removeItem('jalur-guest-mode');history.replaceState({},'',location.pathname+location.search);user=null;csrfToken='';window.JALUR_APPLY_ROLE_NAV?.('guest',null);$('#app')?.classList.add('hidden');$('#welcome')?.classList.remove('hidden');notice('Kamu sudah keluar.');});}});
  $('#enterSchool')?.addEventListener('click',e=>{e.stopImmediatePropagation();login('school')},true);
  $('#enterBK')?.addEventListener('click',e=>{e.stopImmediatePropagation();login('bk')},true);
  $('#enterTeacher')?.addEventListener('click',e=>{e.stopImmediatePropagation();login('teacher')},true);
  const moderator=document.createElement('button');moderator.type='button';moderator.className='staff-entry';moderator.textContent='Moderator Curhat';moderator.addEventListener('click',()=>login('moderator'));$('.welcome-staff-options')?.append(moderator);
  const platformLogin=document.createElement('button');platformLogin.type='button';platformLogin.className='staff-entry';platformLogin.textContent='Admin Platform';platformLogin.addEventListener('click',()=>login('platform'));$('.welcome-staff-options')?.append(platformLogin);
  $('#enterGuest')?.addEventListener('click',e=>{if(typeof window.JALUR_ENTER_GUEST!=='function')return;e.preventDefault();e.stopImmediatePropagation();user=null;csrfToken='';window.JALUR_GUEST_SELECTED=true;window.JALUR_APPLY_ROLE_NAV?.('guest',null);sessionStorage.setItem('jalur-guest-mode','1');window.JALUR_ENTER_GUEST();},true);
  // Existing student local account controls are intentionally not used for server authentication.
  $('#createAccount')?.addEventListener('click',e=>{
     e.stopImmediatePropagation();
     modal('Cara membuat akun JALUR',`<div class="jalur-account-guide"><p class="source-line">Akun dengan peran sekolah dibuat melalui pengelola agar akses dan data setiap pengguna terhubung dengan sekolah yang benar.</p><div class="jalur-account-step"><span>01</span><div><strong>Hubungi pengelola sekolah</strong><p>Minta pengelola membuat akun melalui Portal Pengelola Sekolah.</p></div></div><div class="jalur-account-step"><span>02</span><div><strong>Terima akses akun</strong><p>Pengelola memasukkan nama, email, peran, dan informasi kelas bila diperlukan, lalu memberikan kata sandi sementara melalui kanal terpisah.</p></div></div><div class="jalur-account-step"><span>03</span><div><strong>Masuk ke JALUR</strong><p>Gunakan email dan kata sandi yang diberikan. Peran akan diperiksa oleh server saat login.</p></div></div><p class="source-line">Belum mempunyai akun? Kamu tetap dapat mencoba fitur umum melalui mode pengunjung.</p><div class="jalur-account-actions"><button type="button" class="btn secondary" id="accountGuideGuest">Coba sebagai pengunjung</button><button type="button" class="btn primary" id="accountGuideLogin">Saya sudah punya akun</button></div></div>`);
     $('#accountGuideLogin').onclick=()=>login('student');
     $('#accountGuideGuest').onclick=()=>{dismissLoginModal(()=>window.JALUR_ENTER_GUEST?.());};
   },true);
  $('#signIn')?.addEventListener('click',e=>{e.stopImmediatePropagation();login('student')},true);
  async function hydrateStudentWorkspace(){if(user?.role!=='student')return;const remote=await api('/workspace');if(remote.workspace)window.JALUR_SET_WORKSPACE?.(remote.workspace);else{const local=window.JALUR_GET_WORKSPACE?.();if(local)await api('/workspace',{method:'POST',body:{workspace:local}});}}
  window.addEventListener('DOMContentLoaded',async()=>{if(sessionStorage.getItem('jalur-guest-mode')==='1'||window.JALUR_GUEST_SELECTED||window.JALUR_LOGIN_REQUESTED)return;try{const d=await api('/auth/me');if(sessionStorage.getItem('jalur-guest-mode')==='1'||window.JALUR_GUEST_SELECTED||window.JALUR_LOGIN_REQUESTED||window.JALUR_WELCOME_REQUESTED)return;user=d.user;csrfToken=d.csrfToken||cookie('jalur_csrf');await hydrateStudentWorkspace();if(window.JALUR_WELCOME_REQUESTED||sessionStorage.getItem('jalur-guest-mode')==='1')return;sessionStorage.setItem('jalur-app-open','1');window.JALUR_TRANSITION_TO_APP?.();const saved=window.JALUR_GET_ACTIVE_PAGE?.()||'Dashboard';window.navigate?.(saved);}catch{/* Pengunjung tetap berada di halaman pembuka jika belum memiliki sesi aktif. Login hanya dibuka melalui pilihan pengguna. */}});
  // Role-aware navigation shortcut is deliberately server-rendered for protected modules.
  const oldNav=window.navigate;
  window.JALUR_API = { request: api, getUser: () => user };
  window.navigate=function(page){
    if(user){
      window.JALUR_SET_ACTIVE_PAGE?.(page);
      const destination=roleRoute(page,user.role);
      if(destination!==undefined){
        if(destination===null){notice('Akun ini tidak memiliki akses ke halaman tersebut.');return;}
        return serverPage(destination);
      }
      if(page==='Decision Journal'){
        window.JALUR_SET_ACTIVE_PAGE?.(page);
        api('/journal').then(d=>window.JALUR_SET_JOURNAL?.(d.items||[])).catch(err=>notice(err.message));
        return oldNav?.(page);
      }
    }else{
      if(page==="BK Consultation"){
        modal("Masuk dengan akun siswa","<p>Konsultasi BK merupakan layanan khusus siswa dengan akun sekolah.</p>");
        return;
      }
      if(page==="Anonymous Venting"){return oldNav?.(page);}
      if(["School Portal","BK Portal","Grades"].includes(page)){
        modal("Login diperlukan","<p>Portal dan data sekolah hanya dapat digunakan melalui akun dengan peran yang sesuai.</p>");
        return;
      }
    }
    return oldNav?.(page);
  };
})();
