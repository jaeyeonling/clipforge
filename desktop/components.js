// 런타임 구성요소 관리 (PRODUCT_ARCHITECTURE §9.2): 첫 실행 설치와 앱 내 업데이트가 같은 코드를 쓴다.
//   runtime/ (= %LOCALAPPDATA%\clipforge\runtime)  ← 엔진 코드(층 A) + 구성요소(층 B)가 모두 여기. 사용자 쓰기 가능 → 업데이트에 UAC 불필요
//   매니페스트 latest.json: { engine_code: {version,url,sha256,size}, components: {name: {version,url,sha256,size,label,optional,paths}} }
//   흐름: plan() → 빠졌거나 버전이 다른 것 → download(이어받기, sha256) → install(7za 로 _staging 에 풀고 경로 교체, 실패 시 _prev 복원) → VERSION.json 갱신
//   URL 은 https:// 또는 file:// (로컬 릴리스 폴더로 테스트).
"use strict";
const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const fsp = require("node:fs/promises");
const http = require("node:http");
const https = require("node:https");
const path = require("node:path");
const { pathToFileURL, fileURLToPath } = require("node:url");

const CODE_PATHS = ["clipforge", "games", "data", "assets", "app"];
const COMPONENT_PATHS = {                       // 설치/교체 시 지우고 새로 놓는 경로 (zip 안 경로와 같다)
  "python-base": null,                          // 특수: 루트의 파일들 + Lib (Lib/site-packages/nvidia 는 cuda 소유라 보존)
  cuda: ["Lib/site-packages/nvidia"],
  ffmpeg: ["bin"],
  whisper: ["models"],
};

function sevenZip() {
  // 개발: node_modules/7zip-bin, 배포: resources/7za.exe (electron-builder extraResources)
  const cands = [path.join(process.resourcesPath || "", "7za.exe"), path.join(__dirname, "node_modules", "7zip-bin", "win", "x64", "7za.exe")];
  const p = cands.find((c) => c && fs.existsSync(c));
  if (!p) throw new Error("7za.exe 를 찾지 못했습니다");
  return p;
}

// ---------- GitHub private 저장소 지원 ----------
// 비공개 저장소의 릴리스 자산은 브라우저 URL(github.com/.../releases/download/...)로 받을 수 없다.
// 토큰이 있으면 API 로 릴리스를 조회해 자산의 API URL 을 얻고 Accept: application/octet-stream 으로 받는다 (S3 로 리다이렉트).
// 토큰: CLIPFORGE_GH_TOKEN 환경변수 또는 %LOCALAPPDATA%\clipforge\github-token.txt (fine-grained PAT, 해당 저장소 Contents: read-only).
function githubToken() {
  if (process.env.CLIPFORGE_GH_TOKEN) return process.env.CLIPFORGE_GH_TOKEN.trim();
  try { return fs.readFileSync(path.join(process.env.LOCALAPPDATA || "", "clipforge", "github-token.txt"), "utf8").trim() || null; } catch { return null; }
}
const GH_RE = /^https:\/\/github\.com\/([^/]+)\/([^/]+)\/releases\/(?:latest\/download|download\/([^/]+))\/([^/?#]+)$/;

function httpGetJson(url, headers) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { "user-agent": "clipforge", accept: "application/vnd.github+json", ...headers } }, (res) => {
      let body = ""; res.setEncoding("utf8"); res.on("data", (c) => (body += c));
      res.on("end", () => { if (res.statusCode !== 200) return reject(new Error(`GitHub API ${res.statusCode} ${url}: ${body.slice(0, 120)}`)); try { resolve(JSON.parse(body)); } catch (e) { reject(e); } });
    }).on("error", reject);
  });
}

/** github.com 릴리스 자산 URL → {url, headers}. 토큰이 없거나 GitHub 가 아니면 그대로. */
async function resolveAsset(url) {
  const m = GH_RE.exec(url); const token = githubToken();
  if (!m || !token) return { url, headers: {} };
  const [, owner, repo, tag, name] = m;
  const api = tag ? `https://api.github.com/repos/${owner}/${repo}/releases/tags/${tag}` : `https://api.github.com/repos/${owner}/${repo}/releases/latest`;
  const rel = await httpGetJson(api, { authorization: `Bearer ${token}` });
  const asset = (rel.assets || []).find((a) => a.name === name);
  if (!asset) throw new Error(`릴리스 ${rel.tag_name} 에 자산 ${name} 이 없습니다`);
  return { url: asset.url, headers: { authorization: `Bearer ${token}`, accept: "application/octet-stream", "user-agent": "clipforge" } };
}

// ---------- 매니페스트·버전 ----------
async function fetchText(url) {
  if (url.startsWith("file:")) return fsp.readFile(fileURLToPath(url), "utf8");
  const r = await resolveAsset(url);
  return new Promise((resolve, reject) => {
    const get = (u, headers, n) => {
      const mod = u.startsWith("https") ? https : http;
      mod.get(u, { headers: { "cache-control": "no-cache", "user-agent": "clipforge", ...headers } }, (res) => {
        if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && n < 5) {
          res.resume(); const next = new URL(res.headers.location, u).toString();
          return get(next, new URL(next).host === new URL(u).host ? headers : {}, n + 1);          // 다른 호스트(S3)로 가면 Authorization 제거
        }
        if (res.statusCode !== 200) { res.resume(); return reject(new Error(`HTTP ${res.statusCode} ${u}`)); }
        let body = ""; res.setEncoding("utf8"); res.on("data", (c) => (body += c)); res.on("end", () => resolve(body));
      }).on("error", reject);
    };
    get(r.url, r.headers, 0);
  });
}

async function fetchManifest(baseUrl) {
  const url = baseUrl.replace(/\/+$/, "") + "/latest.json";
  const m = JSON.parse(await fetchText(url));
  // 상대 url 은 baseUrl 기준으로
  const abs = (u) => (/^(https?|file):/.test(u) ? u : baseUrl.replace(/\/+$/, "") + "/" + u.replace(/^\/+/, ""));
  if (m.engine_code?.url) m.engine_code.url = abs(m.engine_code.url);
  for (const c of Object.values(m.components || {})) if (c.url) c.url = abs(c.url);
  return m;
}

function readLocalVersion(runtimeDir) {
  try { return JSON.parse(fs.readFileSync(path.join(runtimeDir, "VERSION.json"), "utf8")); } catch { return null; }
}

function writeLocalVersion(runtimeDir, v) {
  fs.writeFileSync(path.join(runtimeDir, "VERSION.json"), JSON.stringify(v, null, 1), "utf8");
}

/** 설치 여부를 파일로 판정 (VERSION.json 만 믿지 않는다 — 폴더를 지웠을 수 있다) */
function present(runtimeDir, name) {
  const has = (rel) => fs.existsSync(path.join(runtimeDir, rel));
  if (name === "engine_code") return has("clipforge/app.py") && has("app/dist/index.html");
  if (name === "python-base") return has("python.exe") && has("Lib/site-packages/fastapi");
  if (name === "cuda") return has("Lib/site-packages/nvidia/cublas/bin");
  if (name === "ffmpeg") return has("bin/ffmpeg.exe");
  if (name === "whisper") return has("models/faster-whisper-large-v3-turbo/model.bin");
  return false;
}

/** 할 일 목록: [{name, kind: "engine_code"|"component", reason: "missing"|"update", entry}] */
function plan(runtimeDir, manifest, { wantOptional = {} } = {}) {
  const local = readLocalVersion(runtimeDir) || {};
  const lv = local.component_versions || {};
  const out = [];
  if (manifest.engine_code) {
    const reason = !present(runtimeDir, "engine_code") ? "missing" : (local.engine_version !== manifest.engine_code.version ? "update" : null);
    if (reason) out.push({ name: "engine_code", kind: "engine_code", reason, entry: manifest.engine_code });
  }
  for (const [name, entry] of Object.entries(manifest.components || {})) {
    if (!entry.url) continue;
    if (entry.optional && wantOptional[name] === false) continue;
    const reason = !present(runtimeDir, name) ? "missing" : (lv[name] !== entry.version ? "update" : null);
    if (reason) out.push({ name, kind: "component", reason, entry });
  }
  return out;
}

// ---------- 다운로드 (이어받기 + sha256) ----------
function sha256File(p) {
  return new Promise((resolve, reject) => {
    const h = crypto.createHash("sha256");
    fs.createReadStream(p).on("data", (d) => h.update(d)).on("end", () => resolve(h.digest("hex"))).on("error", reject);
  });
}

async function download(entry, dest, onProgress, signal) {
  await fsp.mkdir(path.dirname(dest), { recursive: true });
  if (fs.existsSync(dest) && fs.statSync(dest).size === entry.size && (await sha256File(dest)) === entry.sha256) {
    onProgress?.({ done: entry.size, total: entry.size, cached: true }); return dest;
  }
  const part = dest + ".part";
  if (entry.url.startsWith("file:")) {
    const src = fileURLToPath(entry.url);
    await copyWithProgress(src, part, entry.size, onProgress, signal);
  } else {
    let have = fs.existsSync(part) ? fs.statSync(part).size : 0;
    if (have > entry.size) { await fsp.unlink(part); have = 0; }
    const r = await resolveAsset(entry.url);
    await httpDownload(r.url, part, have, entry.size, onProgress, signal, 0, r.headers);
  }
  const sum = await sha256File(part);
  if (sum !== entry.sha256) { await fsp.unlink(part); throw new Error(`해시 불일치: ${path.basename(dest)} (다운로드가 손상됨 — 다시 시도)`); }
  await fsp.rename(part, dest);
  return dest;
}

function copyWithProgress(src, dst, total, onProgress, signal) {
  return new Promise((resolve, reject) => {
    let done = 0;
    const r = fs.createReadStream(src), w = fs.createWriteStream(dst);
    signal?.addEventListener("abort", () => { r.destroy(new Error("취소")); });
    r.on("data", (d) => { done += d.length; onProgress?.({ done, total }); });
    r.on("error", reject); w.on("error", reject); w.on("finish", resolve);
    r.pipe(w);
  });
}

function httpDownload(url, part, have, total, onProgress, signal, redirects = 0, extraHeaders = {}) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith("https") ? https : http;
    const headers = { "user-agent": "clipforge", ...extraHeaders, ...(have > 0 ? { range: `bytes=${have}-` } : {}) };
    const req = mod.get(url, { headers }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && redirects < 5) {
        res.resume();
        const next = new URL(res.headers.location, url).toString();
        const keep = new URL(next).host === new URL(url).host ? extraHeaders : {};        // 다른 호스트(S3)로 가면 Authorization 제거
        return resolve(httpDownload(next, part, have, total, onProgress, signal, redirects + 1, keep));
      }
      if (res.statusCode === 416) { res.resume(); return resolve(); }                    // 이미 다 받음
      if (res.statusCode !== 200 && res.statusCode !== 206) { res.resume(); return reject(new Error(`HTTP ${res.statusCode} ${url}`)); }
      const append = res.statusCode === 206 && have > 0;
      let done = append ? have : 0;
      const w = fs.createWriteStream(part, { flags: append ? "a" : "w" });
      res.on("data", (d) => { done += d.length; onProgress?.({ done, total }); });
      res.on("error", reject); w.on("error", reject); w.on("finish", resolve);
      res.pipe(w);
    });
    req.on("error", reject);
    signal?.addEventListener("abort", () => req.destroy(new Error("취소")));
  });
}

// ---------- 설치 (풀기 → 교체 → 롤백) ----------
function run7z(args, onLine) {
  return new Promise((resolve, reject) => {
    const p = spawn(sevenZip(), args, { windowsHide: true });
    let err = "";
    p.stdout.on("data", (d) => onLine?.(String(d)));
    p.stderr.on("data", (d) => (err += String(d)));
    p.on("error", reject);
    p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`7za exit ${code}: ${err.slice(-300)}`))));
  });
}

async function rmrf(p) { await fsp.rm(p, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); }

async function install(runtimeDir, item, zipPath, onProgress) {
  const staging = path.join(runtimeDir, "_staging", item.name);
  const prev = path.join(runtimeDir, "_prev", item.name);
  await rmrf(staging); await fsp.mkdir(staging, { recursive: true });
  onProgress?.({ phase: "extract" });
  await run7z(["x", "-y", "-bd", "-bsp1", `-o${staging}`, zipPath], (line) => {
    const m = line.match(/(\d+)%/); if (m) onProgress?.({ phase: "extract", pct: Number(m[1]) });
  });
  // 교체 대상 경로
  let rels;
  if (item.name === "engine_code") rels = CODE_PATHS;
  else if (item.name === "python-base") rels = (await fsp.readdir(staging)).filter((n) => n !== "Lib").concat(["Lib"]);
  else rels = COMPONENT_PATHS[item.name] || (await fsp.readdir(staging));
  onProgress?.({ phase: "swap" });
  await rmrf(prev); await fsp.mkdir(prev, { recursive: true });
  const moved = [];
  try {
    for (const rel of rels) {
      const cur = path.join(runtimeDir, rel), bak = path.join(prev, rel), neu = path.join(staging, rel);
      if (!fs.existsSync(neu)) continue;
      if (item.name === "python-base" && rel === "Lib") {
        // Lib 는 통째로 바꾸되 cuda 소유 폴더(site-packages/nvidia)는 새 Lib 로 옮겨 보존
        const nv = path.join(cur, "site-packages", "nvidia"), nvNew = path.join(neu, "site-packages", "nvidia");
        if (fs.existsSync(nv) && !fs.existsSync(nvNew)) { await fsp.mkdir(path.dirname(nvNew), { recursive: true }); await fsp.rename(nv, nvNew); }
      }
      if (fs.existsSync(cur)) { await fsp.mkdir(path.dirname(bak), { recursive: true }); await fsp.rename(cur, bak); moved.push(rel); }
      await fsp.mkdir(path.dirname(cur), { recursive: true });
      await fsp.rename(neu, cur);
    }
  } catch (e) {
    // 롤백
    for (const rel of moved) {
      const cur = path.join(runtimeDir, rel), bak = path.join(prev, rel);
      try { await rmrf(cur); await fsp.rename(bak, cur); } catch { /* best effort */ }
    }
    throw new Error(`교체 실패(복원함): ${e.message}`);
  }
  await rmrf(staging); await rmrf(prev);
  for (const d of [path.dirname(staging), path.dirname(prev)]) { try { await fsp.rmdir(d); } catch { /* 다른 구성요소가 쓰는 중이면 남긴다 */ } }
  // VERSION.json
  const v = readLocalVersion(runtimeDir) || { component_versions: {} };
  v.component_versions = v.component_versions || {};
  if (item.kind === "engine_code") v.engine_version = item.entry.version; else v.component_versions[item.name] = item.entry.version;
  v.updated = new Date().toISOString();
  writeLocalVersion(runtimeDir, v);
}

/** 설치본에 동봉된 엔진 코드(resources/engine)를 런타임 폴더에 심는다 (첫 실행, 네트워크 없이 층 A 확보) */
async function seedFromResources(runtimeDir, seedDir) {
  if (!seedDir || !fs.existsSync(path.join(seedDir, "clipforge", "app.py"))) return false;
  await fsp.mkdir(runtimeDir, { recursive: true });
  for (const rel of CODE_PATHS) {
    const src = path.join(seedDir, rel), dst = path.join(runtimeDir, rel);
    if (!fs.existsSync(src)) continue;
    await rmrf(dst); await fsp.cp(src, dst, { recursive: true });
  }
  const seedVer = (() => { try { return JSON.parse(fs.readFileSync(path.join(seedDir, "VERSION.json"), "utf8")); } catch { return {}; } })();
  const v = readLocalVersion(runtimeDir) || { component_versions: {} };
  v.engine_version = seedVer.engine_version || v.engine_version; v.seeded = new Date().toISOString();
  writeLocalVersion(runtimeDir, v);
  for (const f of ["THIRD_PARTY_NOTICES.md"]) if (fs.existsSync(path.join(seedDir, f))) await fsp.copyFile(path.join(seedDir, f), path.join(runtimeDir, f));
  return true;
}

/** 전체 계획 실행. onEvent({type, name, ...}) 로 진행 상황을 화면에 보낸다. */
async function apply(runtimeDir, items, { downloadDir, onEvent, signal }) {
  for (const item of items) {
    const zip = path.join(downloadDir, path.basename(new URL(item.entry.url).pathname));
    onEvent({ type: "start", name: item.name, size: item.entry.size, reason: item.reason });
    await download(item.entry, zip, (p) => onEvent({ type: "download", name: item.name, ...p }), signal);
    await install(runtimeDir, item, zip, (p) => onEvent({ type: "install", name: item.name, ...p }));
    onEvent({ type: "done", name: item.name });
    try { await fsp.unlink(zip); } catch { /* keep */ }
  }
}

function fileUrl(p) { return pathToFileURL(p).toString(); }

module.exports = { fetchManifest, readLocalVersion, present, plan, download, install, apply, seedFromResources, fileUrl, githubToken, CODE_PATHS };
