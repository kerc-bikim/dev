const NAV_LATER = [
  ["dashboard", "대시보드"],
  ["foundation", "기반 설정"],
  ["modules", "모듈 설정"],
  ["variables", "통합 변수"],
  ["files", "파일 편집"],
  ["logs", "로그"],
  ["sniff", "링 모니터"],
  ["diagnostics", "진단"],
  ["settings", "설정"],
];

const DEFAULT_RINGS = [
  { name: "STATUS_RING", key: 1040, size: 128, inStartstop: true },
  { name: "WAVE_RING", key: 1000, size: 1024, inStartstop: true },
  { name: "PICK_RING", key: 1005, size: 1024, inStartstop: true },
  { name: "HYPO_RING", key: 1015, size: 1024, inStartstop: true },
  { name: "BINDER_RING", key: 1020, size: 256, inStartstop: false },
];

const DEFAULT_MODULES = [
  { id: "statmgr", binary: "statmgr", param: "statmgr.d", desc: "statmgr.desc", moduleId: "MOD_STATMGR", enabled: true, pid: 2201, status: "Alive", hb: "ok", restartMe: true, locked: true },
  { id: "pick_ew", binary: "pick_ew", param: "pick_ew.d", desc: "pick_ew.desc", moduleId: "MOD_PICK_EW", enabled: false, pid: null, status: "—", hb: "off", restartMe: true },
  { id: "binder_ew", binary: "binder_ew", param: "binder_ew.d", desc: "binder_ew.desc", moduleId: "MOD_BINDER_EW", enabled: false, pid: null, status: "—", hb: "off", restartMe: true },
  { id: "eqproc", binary: "eqproc", param: "eqproc.d", desc: "eqproc.desc", moduleId: "MOD_EQPROC", enabled: false, pid: null, status: "—", hb: "off", restartMe: false },
  { id: "slink2ew", binary: "slink2ew", param: "slink2ew.d", desc: null, moduleId: "MOD_SLINK2EW", enabled: false, pid: null, status: "—", hb: "off", restartMe: false, noDesc: true },
  { id: "tankplayer", binary: "tankplayer", param: "tankplayer.d", desc: "tankplayer.desc", moduleId: "MOD_TANKPLAYER", enabled: false, pid: null, status: "—", hb: "off", restartMe: false },
];

const FILES = {
  "params/startstop_unix.d": `# 미리보기 목 파일\nRing   STATUS_RING  128\nRing   WAVE_RING    1024\nProcess          "statmgr statmgr.d"\n Class/Priority    OTHER 0\n# Process          "pick_ew pick_ew.d"\n`,
  "params/earthworm.d": `Ring   WAVE_RING        1000\nRing   PICK_RING        1005\nRing   HYPO_RING        1015\nRing   STATUS_RING      1040\nRing   FLAG_RING        2000\nModule   MOD_STATMGR        10\nModule   MOD_PICK_EW        20\n`,
  "params/earthworm_commonvars.d": `SetEnvVariable EW_INST_ID INST_UNKNOWN\nSetEnvVariable HEARTBEAT_INT 30\n`,
  "environment/ew_linux.bash": `export EW_HOME=/opt/earthworm\nexport EW_VERSION=earthworm_8.0\nEW_RUN_DIR=/opt/earthworm/run_working\nexport EW_PARAMS="${EW_RUN_DIR}/params/"\nexport EW_LOG="${EW_RUN_DIR}/log/"\n`,
};

const state = {
  preview: true,
  setupComplete: false,
  wizardStep: 0,
  page: "setup",
  ew: "stopped",
  toast: null,
  modal: null,
  sniffing: false,
  sniffLines: [],
  sniffTimer: null,
  dirs: {
    EW_HOME: "/opt/earthworm",
    EW_VERSION: "earthworm_8.0",
    EW_RUN_DIR: "/opt/earthworm/run_working",
    retention: 14,
  },
  inst: "INST_UNKNOWN",
  rings: structuredClone(DEFAULT_RINGS),
  modules: structuredClone(DEFAULT_MODULES),
  vars: { EW_INST_ID: "INST_UNKNOWN", HEARTBEAT_INT: "30", STATIONFILE: "${EW_PARAMS}/stations.hinv", LogFile: "1" },
  file: "params/startstop_unix.d",
  logModule: "statmgr",
  sniff: { tool: "sniffwave", ring: "WAVE_RING", sta: "wild", cmp: "wild", net: "wild", loc: "wild", flag: "n", verbose: false },
};

function toast(msg) {
  state.toast = msg;
  render();
  setTimeout(() => { if (state.toast === msg) { state.toast = null; render(); } }, 2400);
}

function confirmModal(title, body, onOk) {
  state.modal = { title, body, onOk };
  render();
}

function nextPid() {
  return 2300 + state.modules.filter((m) => m.pid).length;
}

function startEw() {
  if (!state.setupComplete) return toast("초기 설정을 먼저 완료하세요");
  state.ew = "running";
  state.modules.forEach((m) => {
    if (m.enabled) {
      m.pid = m.pid || nextPid();
      m.status = "Alive";
      m.hb = m.desc ? "ok" : "no-desc";
    }
  });
  toast("startstop 기동 (미리보기)");
  render();
}

function stopEw() {
  state.ew = "stopped";
  state.modules.forEach((m) => {
    if (m.id !== "statmgr" || !m.enabled) {
      m.pid = null;
      m.status = m.enabled ? "—" : "—";
    }
    if (!m.enabled) m.hb = "off";
  });
  toast("pau 로 전체 종료 (미리보기)");
  render();
}

function pauseEw() {
  state.ew = "paused";
  state.modules.forEach((m) => {
    if (m.locked) return;
    if (m.enabled && m.pid) {
      m.status = "Stop";
      m.hb = "off";
    }
  });
  toast("업무 모듈 stopmodule (미리보기)");
  render();
}

function resumeEw() {
  state.ew = "running";
  state.modules.forEach((m) => {
    if (m.status === "Stop") {
      m.status = "Alive";
      m.hb = m.desc ? "ok" : "no-desc";
    }
  });
  toast("Stop 모듈 restart (미리보기)");
  render();
}

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content;
}

function esc(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function render() {
  const app = document.getElementById("app");
  app.replaceChildren();
  app.append(el(`
    <div class="banner">
      <span>미리보기 — 백엔드·Earthworm 없이 <strong>목 데이터</strong>로 화면만 확인합니다. 실제 startstop 은 호출하지 않습니다.</span>
      <button class="ghost" data-act="reset">초기 설정부터 다시</button>
    </div>
    <header class="topbar">
      <div class="brand">
        <h1>Earthworm Web Control</h1>
        <small>v8.0b17 · ${esc(state.dirs.EW_VERSION)}</small>
      </div>
      <div class="controls">
        ${badge()}
        <button data-act="start" ${state.setupComplete && state.ew === "stopped" ? "" : "disabled"}>시작</button>
        <button data-act="pause" ${state.ew === "running" ? "" : "disabled"}>일시중지</button>
        <button data-act="resume" ${state.ew === "paused" ? "" : "disabled"}>재개</button>
        <button class="danger" data-act="stop" ${state.ew !== "stopped" ? "" : "disabled"}>종료</button>
      </div>
    </header>
    <aside class="sidebar">${navHtml()}</aside>
    <main class="main">${pageHtml()}</main>
    ${state.toast ? `<div class="toast">${esc(state.toast)}</div>` : ""}
    ${state.modal ? modalHtml() : ""}
  `));
  bind(app);
}

function badge() {
  if (!state.setupComplete) return `<span class="badge warn"><span class="dot"></span>초기 설정 필요</span>`;
  if (state.ew === "running") return `<span class="badge ok"><span class="dot"></span>startstop Alive</span>`;
  if (state.ew === "paused") return `<span class="badge warn"><span class="dot"></span>일시중지</span>`;
  return `<span class="badge bad"><span class="dot"></span>중지됨</span>`;
}

function navHtml() {
  const setupBtn = `<button class="nav-btn ${state.page === "setup" ? "active" : ""}" data-page="setup">초기 설정 마법사</button>`;
  const later = NAV_LATER.map(([id, label]) => {
    const dis = state.setupComplete ? "" : "disabled";
    return `<button class="nav-btn ${state.page === id ? "active" : ""}" data-page="${id}" ${dis}>${label}</button>`;
  }).join("");
  return `
    <div class="nav-label">초기</div>
    ${setupBtn}
    <div class="nav-label">이후 설정</div>
    ${later}
  `;
}

function pageHtml() {
  if (!state.setupComplete || state.page === "setup") return wizardHtml();
  switch (state.page) {
    case "dashboard": return dashboardHtml();
    case "foundation": return foundationHtml();
    case "modules": return modulesHtml();
    case "variables": return variablesHtml();
    case "files": return filesHtml();
    case "logs": return logsHtml();
    case "sniff": return sniffHtml();
    case "diagnostics": return diagHtml();
    case "settings": return settingsHtml();
    default: return dashboardHtml();
  }
}

function wizardHtml() {
  const steps = ["디렉터리", "설치 ID", "링 구성", "검증"];
  const s = state.wizardStep;
  return `
    <p class="kicker">초기 설정</p>
    <h2>Earthworm 기반 구성</h2>
    <p class="lead">디렉터리와 링을 먼저 만듭니다. 완료 전에는 모듈 기동 메뉴가 잠깁니다.</p>
    <div class="steps">${steps.map((n, i) => `<span class="step ${i === s ? "on" : ""} ${i < s ? "done" : ""}">${i + 1}. ${n}</span>`).join("")}</div>
    ${s === 0 ? wizardDirs() : ""}
    ${s === 1 ? wizardInst() : ""}
    ${s === 2 ? wizardRings() : ""}
    ${s === 3 ? wizardValidate() : ""}
  `;
}

function wizardDirs() {
  const d = state.dirs;
  return `<div class="card">
    <h3>단계 A — 기본 디렉터리</h3>
    <div class="grid cols-2">
      ${field("EW_HOME", "ew_home", d.EW_HOME)}
      ${field("EW_VERSION", "ew_ver", d.EW_VERSION)}
      ${field("EW_RUN_DIR", "ew_run", d.EW_RUN_DIR)}
      ${field("로그 보관 일수", "ret", d.retention, "number")}
    </div>
    <p class="lead">생성: <code>${esc(d.EW_RUN_DIR)}/params</code> · <code>log</code> · <code>data</code></p>
    <button class="primary" data-act="wiz-next">다음</button>
  </div>`;
}

function wizardInst() {
  return `<div class="card">
    <h3>단계 B — 설치 ID 와 테이블 파일</h3>
    <label>EW_INSTALLATION</label>
    <select id="inst">
      <option ${state.inst === "INST_UNKNOWN" ? "selected" : ""}>INST_UNKNOWN</option>
      <option ${state.inst === "INST_MENLO" ? "selected" : ""}>INST_MENLO</option>
      <option ${state.inst === "INST_KERC" ? "selected" : ""}>INST_KERC</option>
    </select>
    <p class="lead" style="margin-top:12px">복사 예정: earthworm.d, earthworm_global.d, earthworm_commonvars.d → EW_PARAMS. GetUtil 은 params 만 읽습니다.</p>
    <div class="row">
      <button data-act="wiz-prev">이전</button>
      <button class="primary" data-act="wiz-next">다음</button>
    </div>
  </div>`;
}

function wizardRings() {
  const rows = state.rings.map((r, i) => `<tr>
    <td>${i === 0 && r.inStartstop ? "첫 줄" : i + 1}</td>
    <td><input data-ring="${i}" data-k="name" value="${esc(r.name)}" /></td>
    <td><input data-ring="${i}" data-k="key" type="number" value="${r.key}" /></td>
    <td><input data-ring="${i}" data-k="size" type="number" value="${r.size}" /></td>
    <td><input data-ring="${i}" data-k="inStartstop" type="checkbox" ${r.inStartstop ? "checked" : ""} /></td>
  </tr>`).join("");
  return `<div class="card">
    <h3>단계 C — 링 이름 · 키 · 크기 · 순서</h3>
    <p class="lead">첫 startstop 링은 제어 메시지용입니다. 기본값은 STATUS_RING. FLAG_RING 은 목록에 넣지 않습니다.</p>
    <table>
      <thead><tr><th>순서</th><th>이름</th><th>키</th><th>KiB</th><th>startstop</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="lead">WAVE 권장: 관측소 적으면 1024–5120, 많으면 16384–32768 KiB</p>
    <div class="row">
      <button data-act="wiz-prev">이전</button>
      <button class="primary" data-act="wiz-next">다음</button>
    </div>
  </div>`;
}

function wizardValidate() {
  const first = state.rings.find((r) => r.inStartstop);
  const items = [
    ["bin/startstop 존재", true],
    ["EW_PARAMS 테이블 3종", true],
    [`설치 ID ${state.inst}`, true],
    [`첫 링 ${first?.name || "?"}`, first?.name === "STATUS_RING"],
    ["FLAG_RING 미포함", !state.rings.some((r) => r.name === "FLAG_RING" && r.inStartstop)],
    ["log/ 쓰기", true],
  ];
  return `<div class="card">
    <h3>단계 D — 검증</h3>
    <ul>${items.map(([n, ok]) => `<li class="${ok ? "hb-ok" : "hb-bad"}">${ok ? "통과" : "경고"} — ${esc(n)}</li>`).join("")}</ul>
    <p class="lead">완료해도 startstop 은 자동 기동하지 않습니다. 대시보드에서 시작하세요. 최소 모듈은 statmgr 만 활성입니다.</p>
    <div class="row">
      <button data-act="wiz-prev">이전</button>
      <button class="primary" data-act="setup-done">초기 설정 완료</button>
    </div>
  </div>`;
}

function field(label, id, value, type = "text") {
  return `<div><label>${esc(label)}</label><input id="${id}" type="${type}" value="${esc(value)}" /></div>`;
}

function dashboardHtml() {
  const rings = state.rings.filter((r) => r.inStartstop).map((r) => `
    <div class="card"><div class="kicker">${esc(r.name)}</div><strong>${r.size} KiB</strong><div class="lead">key ${r.key}</div></div>
  `).join("");
  const rows = state.modules.map((m) => `<tr>
    <td>${esc(m.binary)}</td>
    <td>${m.pid ?? "—"}</td>
    <td>${esc(m.status)}</td>
    <td class="${m.hb === "ok" ? "hb-ok" : m.hb === "off" ? "hb-off" : "hb-bad"}">${m.hb === "ok" ? "정상" : m.hb === "off" ? "꺼짐" : m.hb === "no-desc" ? "Descriptor 없음" : m.hb}</td>
    <td>${m.enabled ? "켜짐" : "꺼짐"}</td>
    <td>
      <button data-mod="${m.id}" data-act="mod-restart" ${m.pid && state.ew !== "stopped" ? "" : "disabled"}>재시작</button>
      <button data-mod="${m.id}" data-act="mod-stop" ${m.pid && !m.locked && state.ew !== "stopped" ? "" : "disabled"}>중지</button>
    </td>
  </tr>`).join("");
  return `
    <h2>대시보드</h2>
    <p class="lead">프로세스 상태와 하트비트를 분리해 표시합니다. Disk 18.2 GB · NTP 미리보기 양호.</p>
    <div class="grid cols-4">${rings}
      <div class="card"><div class="kicker">디스크</div><strong>18.2 GB</strong><div class="lead">avail</div></div>
    </div>
    <div class="card">
      <h3>모듈</h3>
      <table>
        <thead><tr><th>이름</th><th>pid</th><th>process</th><th>heartbeat</th><th>활성</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function foundationHtml() {
  const locked = state.ew !== "stopped";
  return `
    <h2>기반 설정</h2>
    <p class="lead">${locked ? "startstop 이 실행 중이면 링 크기·순서는 잠깁니다. 종료 후 수정하세요." : "초기 마법사와 같은 폼입니다."}</p>
    <div class="card">
      <h3>디렉터리</h3>
      <div class="grid cols-2">
        ${field("EW_HOME", "f_home", state.dirs.EW_HOME)}
        ${field("EW_RUN_DIR", "f_run", state.dirs.EW_RUN_DIR)}
        ${field("EW_LOG", "f_log", state.dirs.EW_RUN_DIR + "/log/")}
      </div>
    </div>
    <div class="card">
      <h3>링</h3>
      <table>
        <thead><tr><th>이름</th><th>키</th><th>KiB</th><th>startstop</th></tr></thead>
        <tbody>${state.rings.map((r) => `<tr><td>${esc(r.name)}</td><td>${r.key}</td><td>${r.size}</td><td>${r.inStartstop ? "예" : "아니오"}</td></tr>`).join("")}</tbody>
      </table>
      <button class="primary" ${locked ? "disabled" : ""} data-act="save-found">저장 (전체 재시작 필요)</button>
    </div>
  `;
}

function modulesHtml() {
  const rows = state.modules.map((m) => `<tr>
    <td>${esc(m.binary)}</td>
    <td>${esc(m.param)}</td>
    <td>${esc(m.moduleId)}</td>
    <td>${m.desc ? esc(m.desc) : "<span class='hb-bad'>없음</span>"}</td>
    <td><button class="toggle ${m.enabled ? "on" : ""}" data-act="toggle" data-mod="${m.id}" ${m.locked ? "disabled" : ""} title="활성"></button></td>
    <td><button data-act="clone" data-mod="${m.id}">복제</button></td>
  </tr>`).join("");
  return `
    <h2>모듈 설정</h2>
    <p class="lead">토글은 startstop_unix.d Process 주석입니다. 복제는 bin 복사 + 새 Module ID + .desc + Descriptor.</p>
    <div class="card">
      <table>
        <thead><tr><th>bin</th><th>params</th><th>MyModuleId</th><th>.desc</th><th>활성</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function variablesHtml() {
  return `
    <h2>통합 변수</h2>
    <p class="lead">저장 위치는 earthworm_commonvars.d 의 SetEnvVariable. HeartbeatInt 변경 시 .desc tsec 도 같이 올립니다.</p>
    <div class="card grid cols-2">
      ${field("EW_INST_ID", "v_inst", state.vars.EW_INST_ID)}
      ${field("HEARTBEAT_INT", "v_hb", state.vars.HEARTBEAT_INT)}
      ${field("STATIONFILE", "v_sta", state.vars.STATIONFILE)}
      ${field("LogFile", "v_log", state.vars.LogFile)}
    </div>
    <button class="primary" data-act="apply-vars">적용 미리보기</button>
  `;
}

function filesHtml() {
  const names = Object.keys(FILES);
  return `
    <h2>파일 편집</h2>
    <p class="lead">params / environment 트리. earthworm_global.d 는 기본 읽기 전용입니다.</p>
    <div class="grid cols-2">
      <div class="card file-tree">
        ${names.map((n) => `<button class="${state.file === n ? "active" : ""}" data-act="open-file" data-file="${esc(n)}">${esc(n)}</button>`).join("")}
      </div>
      <div class="card">
        <textarea id="filebody">${esc(FILES[state.file])}</textarea>
        <button class="primary" data-act="save-file" style="margin-top:8px">저장 (미리보기)</button>
      </div>
    </div>
  `;
}

function logsHtml() {
  return `
    <h2>로그</h2>
    <p class="lead">${esc(state.dirs.EW_RUN_DIR)}/log · 보관 ${state.dirs.retention}일 · *.lock 과 EW_DATA_DIR 은 삭제하지 않습니다.</p>
    <div class="card row">
      <select id="logmod">${state.modules.map((m) => `<option ${state.logModule === m.id ? "selected" : ""}>${esc(m.id)}</option>`).join("")}</select>
      <span class="lead">${esc(state.logModule)}_20260819.log</span>
    </div>
    <div class="logbox">2026-08-19 12:00:01  statmgr: startstop heartbeat ok
2026-08-19 12:00:31  statmgr: startstop heartbeat ok
2026-08-19 12:01:01  statmgr: startstop heartbeat ok</div>
  `;
}

function sniffHtml() {
  const s = state.sniff;
  return `
    <h2>링 모니터</h2>
    <p class="lead">sniffwave / sniffring stdout 을 WebSocket 으로 중계하는 화면 미리보기입니다.</p>
    <div class="card grid cols-2">
      <div>
        <label>도구</label>
        <select id="stool"><option ${s.tool === "sniffwave" ? "selected" : ""}>sniffwave</option><option ${s.tool === "sniffring" ? "selected" : ""}>sniffring</option></select>
      </div>
      <div>
        <label>링</label>
        <select id="sring">${state.rings.map((r) => `<option ${s.ring === r.name ? "selected" : ""}>${esc(r.name)}</option>`).join("")}</select>
      </div>
      <div><label>Sta</label><input id="ssta" value="${esc(s.sta)}" /></div>
      <div><label>Comp</label><input id="scmp" value="${esc(s.cmp)}" /></div>
      <div><label>Net</label><input id="snet" value="${esc(s.net)}" /></div>
      <div><label>Loc</label><input id="sloc" value="${esc(s.loc)}" /></div>
      <div>
        <label>데이터 플래그</label>
        <select id="sflag">
          <option value="n" ${s.flag === "n" ? "selected" : ""}>n 헤더만</option>
          <option value="s" ${s.flag === "s" ? "selected" : ""}>s 통계</option>
          <option value="y" ${s.flag === "y" ? "selected" : ""}>y 샘플 (폭주 주의)</option>
        </select>
      </div>
    </div>
    <div class="row">
      <button class="primary" data-act="sniff-start" ${state.sniffing ? "disabled" : ""}>시작</button>
      <button data-act="sniff-stop" ${state.sniffing ? "" : "disabled"}>중지</button>
    </div>
    <div class="logbox" id="sniffbox">${esc(state.sniffLines.join("\n") || "대기 중")}</div>
  `;
}

function diagHtml() {
  const lock = state.ew !== "stopped";
  return `
    <h2>진단</h2>
    <p class="lead">락파일과 잔류 IPC. 자동 ipcrm 은 하지 않습니다.</p>
    <div class="grid cols-2">
      <div class="card">
        <h3>락파일</h3>
        <p><code>${esc(state.dirs.EW_RUN_DIR)}/log/startstop_unix.d.lock</code></p>
        <p>${lock ? "잠김 (미리보기: startstop 실행 중)" : "없음"}</p>
        <button class="danger" data-act="unlock" ${lock ? "" : "disabled"}>확인 후 강제 해제</button>
      </div>
      <div class="card">
        <h3>IPC</h3>
        <p class="lead">사용자 earthworm 소유 shm 요약 (목)</p>
        <pre>key 0x00000410  STATUS_RING  nattch 3
key 0x000003e8  WAVE_RING    nattch 2</pre>
      </div>
    </div>
  `;
}

function settingsHtml() {
  return `
    <h2>설정</h2>
    <div class="card grid cols-2">
      ${field("상태 주기(초)", "st_int", "2")}
      ${field("sniff 세션 상한", "st_sniff", "2")}
      ${field("로그 보관 일수", "st_ret", String(state.dirs.retention))}
      <div><label>NTP</label><div class="hb-ok">동기화됨 (미리보기)</div></div>
    </div>
  `;
}

function modalHtml() {
  return `<div class="modal-bg"><div class="modal">
    <h3>${esc(state.modal.title)}</h3>
    <p class="lead">${esc(state.modal.body)}</p>
    <div class="row">
      <button data-act="modal-cancel">취소</button>
      <button class="primary" data-act="modal-ok">확인</button>
    </div>
  </div></div>`;
}

function bind(root) {
  root.querySelectorAll("[data-page]").forEach((b) => {
    b.addEventListener("click", () => {
      if (b.disabled) return;
      state.page = b.dataset.page;
      if (state.page === "setup") state.wizardStep = state.setupComplete ? 3 : state.wizardStep;
      render();
    });
  });
  root.querySelector("[data-act=reset]")?.addEventListener("click", () => {
    Object.assign(state, {
      setupComplete: false, wizardStep: 0, page: "setup", ew: "stopped",
      modules: structuredClone(DEFAULT_MODULES), rings: structuredClone(DEFAULT_RINGS),
    });
    stopSniff(false);
    render();
  });
  root.querySelector("[data-act=start]")?.addEventListener("click", () => {
    confirmModal("Earthworm 시작", "startstop 을 백그라운드로 기동합니다. (미리보기)", startEw);
  });
  root.querySelector("[data-act=stop]")?.addEventListener("click", () => {
    confirmModal("전체 종료", "pau 를 보냅니다. (미리보기)", stopEw);
  });
  root.querySelector("[data-act=pause]")?.addEventListener("click", pauseEw);
  root.querySelector("[data-act=resume]")?.addEventListener("click", resumeEw);
  root.querySelector("[data-act=wiz-next]")?.addEventListener("click", () => {
    saveWizardFields();
    state.wizardStep = Math.min(3, state.wizardStep + 1);
    render();
  });
  root.querySelector("[data-act=wiz-prev]")?.addEventListener("click", () => {
    state.wizardStep = Math.max(0, state.wizardStep - 1);
    render();
  });
  root.querySelector("[data-act=setup-done]")?.addEventListener("click", () => {
    state.setupComplete = true;
    state.page = "dashboard";
    toast("초기 설정 완료. 이후 메뉴가 열렸습니다.");
    render();
  });
  root.querySelectorAll("[data-ring]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const r = state.rings[Number(inp.dataset.ring)];
      const k = inp.dataset.k;
      r[k] = k === "inStartstop" ? inp.checked : (k === "name" ? inp.value : Number(inp.value));
    });
  });
  root.querySelectorAll("[data-act=toggle]").forEach((b) => {
    b.addEventListener("click", () => {
      const m = state.modules.find((x) => x.id === b.dataset.mod);
      if (!m || m.locked) return;
      m.enabled = !m.enabled;
      if (state.ew === "running") {
        if (m.enabled) {
          m.pid = nextPid();
          m.status = "Alive";
          m.hb = m.desc ? "ok" : "no-desc";
          toast("reconfigure: 새 모듈 기동, statmgr 재시작 (미리보기)");
        } else {
          m.pid = null;
          m.status = "Stop";
          m.hb = "off";
          toast("stopmodule pid (미리보기)");
        }
      }
      render();
    });
  });
  root.querySelectorAll("[data-act=clone]").forEach((b) => {
    b.addEventListener("click", () => {
      const src = state.modules.find((x) => x.id === b.dataset.mod);
      const name = `${src.id}_b`;
      if (state.modules.some((m) => m.id === name)) return toast("이미 복제본이 있습니다");
      state.modules.push({
        ...src,
        id: name,
        binary: name,
        param: `${name}.d`,
        desc: src.desc ? `${name}.desc` : null,
        moduleId: `${src.moduleId}_B`,
        enabled: false,
        pid: null,
        status: "—",
        hb: "off",
        locked: false,
      });
      toast(`${src.binary} → ${name} 복제 (Module ID 신규)`);
      render();
    });
  });
  root.querySelector("[data-act=apply-vars]")?.addEventListener("click", () => {
    confirmModal("변수 적용", "변경될 파일 3개: earthworm_commonvars.d, statmgr.d, pick_ew.desc (tsec)", () => toast("적용됨 (미리보기)"));
  });
  root.querySelectorAll("[data-act=open-file]").forEach((b) => {
    b.addEventListener("click", () => { state.file = b.dataset.file; render(); });
  });
  root.querySelector("[data-act=save-file]")?.addEventListener("click", () => {
    FILES[state.file] = document.getElementById("filebody").value;
    toast("저장됨 (미리보기, 디스크 미기록)");
  });
  document.getElementById("logmod")?.addEventListener("change", (e) => {
    state.logModule = e.target.value;
    render();
  });
  root.querySelector("[data-act=sniff-start]")?.addEventListener("click", startSniff);
  root.querySelector("[data-act=sniff-stop]")?.addEventListener("click", () => stopSniff(true));
  root.querySelector("[data-act=unlock]")?.addEventListener("click", () => {
    confirmModal("락 강제 해제", "startstop 가 살아 있으면 안 됩니다. 미리보기에서는 배너만 바꿉니다.", () => toast("락 해제 (미리보기)"));
  });
  root.querySelector("[data-act=save-found]")?.addEventListener("click", () => toast("기반 설정 저장 (미리보기)"));
  root.querySelectorAll("[data-act=mod-restart]").forEach((b) => {
    b.addEventListener("click", () => toast(`restart ${b.dataset.mod} pid (미리보기)`));
  });
  root.querySelectorAll("[data-act=mod-stop]").forEach((b) => {
    b.addEventListener("click", () => {
      const m = state.modules.find((x) => x.id === b.dataset.mod);
      if (!m) return;
      m.status = "Stop";
      m.hb = "off";
      toast(`stopmodule ${m.pid} (미리보기)`);
      render();
    });
  });
  root.querySelector("[data-act=modal-cancel]")?.addEventListener("click", () => { state.modal = null; render(); });
  root.querySelector("[data-act=modal-ok]")?.addEventListener("click", () => {
    const fn = state.modal?.onOk;
    state.modal = null;
    fn?.();
    render();
  });
}

function saveWizardFields() {
  const home = document.getElementById("ew_home");
  if (home) {
    state.dirs.EW_HOME = home.value;
    state.dirs.EW_VERSION = document.getElementById("ew_ver").value;
    state.dirs.EW_RUN_DIR = document.getElementById("ew_run").value;
    state.dirs.retention = Number(document.getElementById("ret").value);
  }
  const inst = document.getElementById("inst");
  if (inst) {
    state.inst = inst.value;
    state.vars.EW_INST_ID = inst.value;
  }
}

function startSniff() {
  if (document.getElementById("sflag")?.value === "y") {
    confirmModal("샘플 덤프", "y 플래그는 출력이 매우 많습니다. 미리보기에서는 헤더 한 줄만 추가합니다.", () => beginSniff());
    return;
  }
  beginSniff();
}

function beginSniff() {
  const stool = document.getElementById("stool");
  if (stool) {
    state.sniff.tool = stool.value;
    state.sniff.ring = document.getElementById("sring").value;
    state.sniff.flag = document.getElementById("sflag").value;
  }
  state.sniffing = true;
  state.sniffLines = [`$ ${state.sniff.tool} ${state.sniff.ring} wild wild wild wild ${state.sniff.flag}`];
  state.sniffTimer = setInterval(() => {
    const t = new Date().toISOString().slice(11, 19);
    state.sniffLines.push(`${t}  STA.HHZ.IU.--  100.0 sps  D: 1.2s F: 0.1s  (미리보기)`);
    if (state.sniffLines.length > 40) state.sniffLines.shift();
    const box = document.getElementById("sniffbox");
    if (box) box.textContent = state.sniffLines.join("\n");
    else render();
  }, 700);
  render();
}

function stopSniff(rerender) {
  state.sniffing = false;
  if (state.sniffTimer) clearInterval(state.sniffTimer);
  state.sniffTimer = null;
  if (rerender) render();
}

render();
