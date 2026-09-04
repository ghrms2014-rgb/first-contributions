/* 캡컷 자동 편집기 — 화면 동작 */
"use strict";

const STEP_LABELS = {
  setup: "설정 확인", sources: "원본 영상", calibration: "캘리브레이션",
  transcribe: "분석·전사", align: "대본·자막", edit: "컷 편집",
  build: "드래프트", publish: "마케팅",
};
const STEP_ORDER = Object.keys(STEP_LABELS);

const state = {
  session: null,
  picked: [],
  candidates: [],
  browsePath: "",
  logSeq: 0,
};

const $ = (id) => document.getElementById(id);

/* ----------------------------------------------------------------- 통신 */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  const text = await res.text();
  let data;
  try { data = text ? JSON.parse(text) : {}; } catch { data = { detail: text }; }
  if (!res.ok) throw new Error(data.detail || `요청 실패 (${res.status})`);
  return data;
}

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = kind;
  el.textContent = message;
  $("toast").appendChild(el);
  setTimeout(() => el.remove(), 5200);
}

async function guard(fn) {
  try { await fn(); }
  catch (err) { toast(err.message, "error"); }
}

const fmtTime = (s) => {
  const t = Math.max(0, s || 0);
  const m = Math.floor(t / 60);
  return `${String(m).padStart(2, "0")}:${(t % 60).toFixed(1).padStart(4, "0")}`;
};
const fmtSize = (b) => (b > 1e9 ? (b / 1e9).toFixed(1) + "GB"
  : b > 1e6 ? (b / 1e6).toFixed(1) + "MB" : Math.round(b / 1024) + "KB");

/* ------------------------------------------------------------- 단계 표시 */
function renderSteps() {
  const done = state.session ? state.session.completed : [];
  const current = state.session ? (state.session.next_step || "publish") : "setup";
  $("stepList").innerHTML = STEP_ORDER.map((step, i) => {
    const isDone = done.includes(step);
    const isActive = step === current;
    const locked = !state.session && step !== "setup";
    return `<li class="${isDone ? "done" : ""} ${isActive ? "active" : ""} ${locked ? "locked" : ""}"
      data-goto="${step}"><span class="num">${isDone ? "✓" : i + 1}</span>${STEP_LABELS[step]}</li>`;
  }).join("");

  $("stepList").querySelectorAll("li[data-goto]").forEach((li) => {
    li.onclick = () => showPanel(li.dataset.goto);
  });
  $("sessionLabel").textContent = state.session
    ? `${state.session.name} · 다음: ${STEP_LABELS[current] || "완료"}`
    : "세션 없음";
}

function showPanel(step) {
  document.querySelectorAll(".panel").forEach((p) => {
    p.classList.toggle("hidden", p.dataset.step !== step);
  });
  const loaders = {
    calibration: loadCalibration, edit: loadCandidates,
    align: loadCues, build: loadAssets, publish: loadPublishOptions,
  };
  if (loaders[step]) guard(loaders[step]);
}

/* ---------------------------------------------------------------- 세션 */
async function loadSessions(selectId) {
  const { sessions } = await api("/api/sessions");
  $("sessionSelect").innerHTML =
    `<option value="">— 세션 선택 —</option>` +
    sessions.map((s) => `<option value="${s.id}">${s.name}</option>`).join("");
  const target = selectId || (state.session && state.session.id) || (sessions[0] && sessions[0].id);
  if (target) {
    $("sessionSelect").value = target;
    await selectSession(target);
  } else {
    state.session = null;
    renderSteps();
  }
}

async function selectSession(id) {
  if (!id) { state.session = null; renderSteps(); return; }
  state.session = await api(`/api/sessions/${id}`);
  const tl = (state.session.data.sources || {}).timeline;
  state.picked = tl ? tl.clips.map((c) => c.path) : [];
  renderPicked();
  renderSteps();
  showPanel(state.session.next_step || "publish");
}

/* -------------------------------------------------------------- 1. 설정 */
async function loadStatus() {
  const status = await api("/api/setup/status");
  $("statusChecks").innerHTML = status.checks.map((c) => `
    <div class="check">
      <span class="dot ${c.ok ? "ok" : ""}"></span>
      <div class="body">
        <div class="label">${c.label}</div>
        <div class="value">${c.value}</div>
        ${c.ok ? "" : `<div class="hint">${c.hint}</div>`}
      </div>
    </div>`).join("");

  const s = status.settings;
  $("draftFolder").value = s.draft_folder || "";
  ["silence_db", "min_silence_sec", "keep_padding_sec", "subtitle_max_chars",
   "whisper_model", "whisper_chunk_sec"].forEach((k) => { $("s_" + k).value = s[k]; });
}

async function loadDictionary() {
  const entries = await api("/api/setup/dictionary");
  $("dictionary").value = Object.entries(entries).map(([k, v]) => `${k} = ${v}`).join("\n");
}

/* ------------------------------------------------------------ 2. 원본 */
async function browse(path) {
  const data = await api(`/api/files/list?path=${encodeURIComponent(path)}&kinds=video`);
  state.browsePath = data.path;
  $("browsePath").value = data.path;
  const up = data.parent
    ? `<div class="item dir"><span class="name" data-dir="${data.parent}">⬆ 상위 폴더</span></div>` : "";
  $("browseList").innerHTML = up + data.entries.map((e) => e.is_dir
    ? `<div class="item dir"><span class="name" data-dir="${e.path}">📁 ${e.name}</span></div>`
    : `<div class="item"><span class="name">🎬 ${e.name}</span>
         <span class="meta">${fmtSize(e.size)}</span>
         <button data-add="${e.path}">추가</button></div>`).join("");

  $("browseList").querySelectorAll("[data-dir]").forEach((el) => {
    el.onclick = () => guard(() => browse(el.dataset.dir));
  });
  $("browseList").querySelectorAll("[data-add]").forEach((el) => {
    el.onclick = () => addPicked([el.dataset.add]);
  });
}

function addPicked(paths) {
  paths.forEach((p) => { if (p && !state.picked.includes(p)) state.picked.push(p); });
  renderPicked();
}

function renderPicked() {
  $("pickedCount").textContent = `${state.picked.length}개`;
  $("pickedList").innerHTML = state.picked.map((p, i) => `
    <div class="item">
      <span class="meta">${i + 1}</span>
      <span class="name" title="${p}">${p.split(/[\\/]/).pop()}</span>
      <button data-up="${i}" ${i === 0 ? "disabled" : ""}>▲</button>
      <button data-down="${i}" ${i === state.picked.length - 1 ? "disabled" : ""}>▼</button>
      <button data-del="${i}">✕</button>
    </div>`).join("") || `<div class="item muted">아직 선택한 영상이 없습니다.</div>`;

  const swap = (a, b) => {
    [state.picked[a], state.picked[b]] = [state.picked[b], state.picked[a]];
    renderPicked();
  };
  $("pickedList").querySelectorAll("[data-up]").forEach((el) => {
    el.onclick = () => swap(+el.dataset.up, +el.dataset.up - 1);
  });
  $("pickedList").querySelectorAll("[data-down]").forEach((el) => {
    el.onclick = () => swap(+el.dataset.down, +el.dataset.down + 1);
  });
  $("pickedList").querySelectorAll("[data-del]").forEach((el) => {
    el.onclick = () => { state.picked.splice(+el.dataset.del, 1); renderPicked(); };
  });
}

/* ------------------------------------------------------ 3. 캘리브레이션 */
async function loadCalibration() {
  const { drafts } = await api("/api/calibration/candidates");
  $("calDraft").innerHTML = drafts.length
    ? drafts.map((d) => `<option value="${d.name}">${d.name}</option>`).join("")
    : `<option value="">— 드래프트 없음 —</option>`;
}

/* --------------------------------------------------------- 5. 자막 목록 */
async function loadCues() {
  if (!state.session) return;
  const { cues } = await api(`/api/editing/${state.session.id}/cues`);
  const list = $("cueList");
  list.classList.toggle("hidden", cues.length === 0);
  list.innerHTML = cues.map((c) =>
    `<div class="item"><span class="meta">${fmtTime(c.start)}</span>
     <span class="name">${c.text}</span></div>`).join("");
}

/* --------------------------------------------------------- 6. 컷 목록 */
async function loadCandidates() {
  if (!state.session) return;
  const data = await api(`/api/editing/${state.session.id}/candidates`);
  state.candidates = data.candidates;
  renderCandidates(data.summary);
}

function renderCandidates(summary) {
  if (summary) {
    $("cutSummary").textContent =
      `${summary.kept}/${summary.total_candidates}구간 유지 · ` +
      `${fmtTime(summary.source_duration)} → ${fmtTime(summary.edited_duration)} ` +
      `(${Math.round(summary.saved_ratio * 100)}% 단축)`;
  }
  $("cutList").innerHTML = state.candidates.map((c) => `
    <label class="cut ${c.keep ? "" : "dropped"}">
      <input type="checkbox" data-cut="${c.index}" ${c.keep ? "checked" : ""}>
      <span class="meta">${fmtTime(c.start)} → ${fmtTime(c.end)}</span>
      <span class="name">${c.duration.toFixed(2)}초</span>
    </label>`).join("");

  $("cutList").querySelectorAll("[data-cut]").forEach((el) => {
    el.onchange = () => {
      const c = state.candidates.find((x) => x.index === +el.dataset.cut);
      c.keep = el.checked;
      el.closest(".cut").classList.toggle("dropped", !c.keep);
      pushToggles();
    };
  });
}

let toggleTimer = null;
function pushToggles() {
  clearTimeout(toggleTimer);
  toggleTimer = setTimeout(() => guard(async () => {
    const toggles = {};
    state.candidates.forEach((c) => { toggles[c.index] = c.keep; });
    const res = await api(`/api/editing/${state.session.id}/candidates`,
      { method: "POST", body: { toggles } });
    renderCandidates(res.summary);
  }), 400);
}

/* --------------------------------------------------------- 7·8 부가 정보 */
async function loadAssets() {
  const { bg } = await api("/api/setup/assets");
  $("bgmSelect").innerHTML = `<option value="">— 없음 —</option>` +
    bg.map((f) => `<option value="${f.path}">${f.name}</option>`).join("");
}

async function loadPublishOptions() {
  const { platforms, tones } = await api("/api/publishing/options");
  $("pubPlatform").innerHTML = platforms.map((p) => `<option value="${p.key}">${p.label}</option>`).join("");
  $("pubTone").innerHTML = tones.map((t) => `<option value="${t.key}">${t.label}</option>`).join("");
}

/* ------------------------------------------------------------ 작업/로그 */
function renderJob(job) {
  const cls = { done: "ok", failed: "error", running: "run" }[job.status] || "";
  const label = { pending: "대기", running: "진행 중", done: "완료",
                  failed: "실패", cancelled: "취소됨" }[job.status] || job.status;
  $("jobArea").innerHTML = `
    <div class="row" style="justify-content:space-between">
      <strong style="font-size:13px">${job.name}</strong>
      <span class="badge ${cls}">${label}</span>
    </div>
    <div class="progress"><i style="width:${Math.round(job.progress * 100)}%"></i></div>
    <div class="muted">${job.error || job.message || ""}</div>
    ${job.status === "running"
      ? `<button data-cancel="${job.id}" style="margin-top:8px">취소</button>` : ""}`;
  const btn = $("jobArea").querySelector("[data-cancel]");
  if (btn) btn.onclick = () => guard(() =>
    api(`/api/jobs/${btn.dataset.cancel}/cancel`, { method: "POST" }));
}

function connectEvents() {
  const es = new EventSource("/api/events");
  es.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.job) renderJob(data.job);
    if (data.type === "finished") {
      const j = data.job;
      if (j.status === "done") {
        toast(`${j.name} 완료`, "ok");
        guard(async () => {
          await selectSession(state.session ? state.session.id : null);
        });
      } else if (j.status === "failed") {
        toast(`${j.name} 실패: ${j.error}`, "error");
      }
    }
  };
  es.onerror = () => { /* EventSource 가 알아서 다시 붙는다 */ };
}

async function pollLogs() {
  try {
    const { logs } = await api(`/api/logs?after=${state.logSeq}`);
    if (logs.length) {
      state.logSeq = logs[logs.length - 1].seq;
      const box = $("logs");
      const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
      box.insertAdjacentHTML("beforeend", logs.map((l) =>
        `<div class="l ${l.level}"><span class="t">${l.time}</span> ${l.message}</div>`).join(""));
      while (box.childElementCount > 400) box.removeChild(box.firstChild);
      if (atBottom) box.scrollTop = box.scrollHeight;
    }
  } catch { /* 서버가 잠깐 안 뜬 것뿐이면 다음 주기에 다시 */ }
  setTimeout(pollLogs, 1500);
}

/* --------------------------------------------------------------- 이벤트 */
function bind() {
  const sid = () => {
    if (!state.session) throw new Error("먼저 세션을 만들거나 선택해 주세요.");
    return state.session.id;
  };

  $("sessionSelect").onchange = (e) => guard(() => selectSession(e.target.value));
  $("newSession").onclick = () => guard(async () => {
    const name = prompt("세션 이름", new Date().toLocaleString("ko-KR"));
    if (name === null) return;
    const res = await api("/api/sessions", { method: "POST", body: { name } });
    await loadSessions(res.session.id);
    toast("새 세션을 만들었습니다.", "ok");
  });
  $("deleteSession").onclick = () => guard(async () => {
    if (!state.session || !confirm(`'${state.session.name}' 세션을 지울까요?`)) return;
    await api(`/api/sessions/${state.session.id}`, { method: "DELETE" });
    state.session = null;
    await loadSessions();
  });

  /* 1. 설정 */
  $("recheck").onclick = () => guard(loadStatus);
  $("detectFolder").onclick = () => guard(async () => {
    const res = await api("/api/setup/detect-draft-folder", { method: "POST" });
    toast(`찾았습니다: ${res.draft_folder}`, "ok");
    await loadStatus();
  });
  $("pickDraftFolder").onclick = () => guard(async () => {
    const res = await api("/api/files/pick", { method: "POST", body: { mode: "folder" } });
    if (res.paths[0]) $("draftFolder").value = res.paths[0];
  });
  $("saveDraftFolder").onclick = () => guard(async () => {
    await api("/api/setup/settings", { method: "POST", body: { draft_folder: $("draftFolder").value.trim() } });
    toast("저장했습니다.", "ok");
    await loadStatus();
  });
  $("saveSettings").onclick = () => guard(async () => {
    await api("/api/setup/settings", { method: "POST", body: {
      silence_db: +$("s_silence_db").value,
      min_silence_sec: +$("s_min_silence_sec").value,
      keep_padding_sec: +$("s_keep_padding_sec").value,
      subtitle_max_chars: +$("s_subtitle_max_chars").value,
      whisper_model: $("s_whisper_model").value,
      whisper_chunk_sec: +$("s_whisper_chunk_sec").value,
    }});
    toast("설정을 저장했습니다.", "ok");
  });
  $("saveDictionary").onclick = () => guard(async () => {
    const entries = {};
    $("dictionary").value.split("\n").forEach((line) => {
      const i = line.indexOf("=");
      if (i > 0) entries[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    });
    const res = await api("/api/setup/dictionary", { method: "POST", body: { entries } });
    toast(`용어 ${res.count}개를 저장했습니다.`, "ok");
  });

  /* 2. 원본 */
  $("browseGo").onclick = () => guard(() => browse($("browsePath").value.trim()));
  $("browsePath").onkeydown = (e) => { if (e.key === "Enter") $("browseGo").click(); };
  $("pickFiles").onclick = () => guard(async () => {
    const res = await api("/api/files/pick", { method: "POST", body: { mode: "files" } });
    addPicked(res.paths);
  });
  $("pickFolder").onclick = () => guard(async () => {
    const res = await api("/api/files/pick", { method: "POST", body: { mode: "folder" } });
    if (res.paths[0]) await browse(res.paths[0]);
  });
  $("clearPicked").onclick = () => { state.picked = []; renderPicked(); };
  $("saveSources").onclick = () => guard(async () => {
    const res = await api(`/api/sessions/${sid()}/sources`,
      { method: "POST", body: { paths: state.picked } });
    toast(`${res.timeline.count}개 · 총 ${fmtTime(res.timeline.duration)}`, "ok");
    await selectSession(sid());
  });

  /* 3. 캘리브레이션 */
  $("runCalibration").onclick = () => guard(async () => {
    const res = await api("/api/calibration/run", { method: "POST", body: {
      draft_name: $("calDraft").value, profile_name: $("calProfileName").value.trim() || "default" }});
    $("calResult").classList.remove("hidden");
    $("calResult").textContent = JSON.stringify(res.profile, null, 2);
    if (res.warning) toast(res.warning);
    else toast("캘리브레이션을 읽었습니다.", "ok");
  });
  $("applyCalibration").onclick = () => guard(async () => {
    await api(`/api/calibration/${sid()}/apply`, { method: "POST",
      body: { profile_name: $("calProfileName").value.trim() || "default" } });
    toast("프로파일을 적용했습니다.", "ok");
    await selectSession(sid());
  });
  $("skipCalibration").onclick = () => guard(async () => {
    await api(`/api/calibration/${sid()}/skip`, { method: "POST" });
    toast("기본값으로 진행합니다.", "ok");
    await selectSession(sid());
  });

  /* 4. 분석 · 전사 */
  $("runAnalyze").onclick = () => guard(async () => {
    await api(`/api/editing/${sid()}/analyze`, { method: "POST" });
    toast("오디오 분석을 시작했습니다.");
  });
  $("runTranscribe").onclick = () => guard(async () => {
    await api(`/api/editing/${sid()}/transcribe`, { method: "POST",
      body: { force: $("forceTranscribe").checked } });
    toast("음성 전사를 시작했습니다.");
  });

  /* 5. 자막 */
  $("runAlign").onclick = () => guard(async () => {
    const res = await api(`/api/editing/${sid()}/align`, { method: "POST", body: {
      script: $("scriptText").value, use_dictionary: $("useDictionary").checked }});
    toast(`자막 ${res.count}줄을 만들었습니다.`, "ok");
    await loadCues();
    await selectSession(sid());
  });

  /* 6. 컷 */
  $("keepAll").onclick = () => {
    state.candidates.forEach((c) => { c.keep = true; });
    renderCandidates(); pushToggles();
  };
  $("dropShort").onclick = () => {
    state.candidates.forEach((c) => { if (c.duration < 1) c.keep = false; });
    renderCandidates(); pushToggles();
  };
  $("confirmCut").onclick = () => guard(async () => {
    const res = await api(`/api/editing/${sid()}/confirm`, { method: "POST" });
    toast(`컷 확정 · 자막 ${res.cues}줄`, "ok");
    await selectSession(sid());
  });

  /* 7. 빌드 */
  $("runBuild").onclick = () => guard(async () => {
    const res = await api(`/api/editing/${sid()}/build`, { method: "POST", body: {
      draft_name: $("buildName").value.trim(),
      bgm_path: $("bgmSelect").value || null,
      bgm_volume: +$("bgmVolume").value,
      allow_replace: $("allowReplace").checked,
    }});
    toast(`'${res.draft_name}' 생성을 시작했습니다.`);
  });

  /* 8. 마케팅 */
  $("runPrompt").onclick = () => guard(async () => {
    const res = await api(`/api/publishing/${sid()}/prompt`, { method: "POST", body: {
      platform: $("pubPlatform").value, tone: $("pubTone").value,
      keywords: $("pubKeywords").value.split(",").map((s) => s.trim()).filter(Boolean),
      audience: $("pubAudience").value, cta: $("pubCta").value,
      video_title: $("pubTitle").value,
    }});
    $("promptResult").classList.remove("hidden");
    $("promptResult").textContent = res.prompt;
    await selectSession(sid());
  });
  $("copyPrompt").onclick = () => {
    navigator.clipboard.writeText($("promptResult").textContent || "")
      .then(() => toast("복사했습니다.", "ok"))
      .catch(() => toast("복사에 실패했습니다.", "error"));
  };
  $("downloadSrt").onclick = () => {
    if (!state.session) return toast("먼저 세션을 선택해 주세요.", "error");
    window.open(`/api/publishing/${state.session.id}/srt/file`, "_blank");
  };
}

/* ----------------------------------------------------------------- 시작 */
async function boot() {
  bind();
  connectEvents();
  pollLogs();
  await guard(loadStatus);
  await guard(loadDictionary);
  await guard(async () => {
    const { shortcuts } = await api("/api/files/shortcuts");
    $("shortcutRow").innerHTML = shortcuts.map((s) =>
      `<button data-short="${s.path}">${s.label}</button>`).join("");
    $("shortcutRow").querySelectorAll("[data-short]").forEach((el) => {
      el.onclick = () => guard(() => browse(el.dataset.short));
    });
    if (shortcuts[0]) await browse(shortcuts[0].path);
  });
  await guard(() => loadSessions());
}

boot();
