/**
 * ADVANCED AI RESEARCH STUDIO - MATURE WORKSTATION CONTROLLER v6.0
 * Clean Everyday UX • Persistent Settings & Health • Drag-and-Drop Multi-Doc • Offline Markdown Fallback
 */

// Global State
let currentEventSource = null;
let currentReportMarkdown = "";
let currentReportFilename = "";
let currentReportTitle = "";
let currentReportStarred = false;
let currentAttachedPdfPath = null;
let currentSources = [];
let currentResearchDepth = "deep";
let currentReportViewMode = localStorage.getItem("stellar_report_mode") || "doc";
let currentSlides = [];
let currentSlideIndex = 0;
let currentDeckViewStyle = "stage";
let executionTimerInterval = null;
let executionStartTime = null;
let allLoadedReports = [];
let autoPlayDeckInterval = null;
let streamCompletedCleanly = false;
let lastRenderedChatTopicKey = "";
let chatWebAugment = false;
let chatHistory = [];
let cachedProviderPresets = {};

const SUPPORTED_DOC_EXTENSIONS = [".pdf", ".docx", ".txt", ".md", ".csv", ".json"];

// ==========================================
// Resilient Offline Icon & Markdown Fallbacks
// ==========================================
const FALLBACK_SVG_MAP = {
  "plus": "+", "play": "▶", "square": "■", "search": "🔍", "copy": "❐",
  "star": "★", "settings": "⚙", "sun": "☀", "moon": "☾", "sidebar": "☰",
  "globe": "🌐", "send": "➤", "trash-2": "🗑", "refresh-cw": "↻",
};

function safeReplaceIcons() {
  if (window.feather && typeof window.feather.replace === "function") {
    try {
      window.feather.replace();
      return;
    } catch (e) { }
  }
  document.querySelectorAll("i[data-feather]").forEach((el) => {
    const name = el.getAttribute("data-feather") || "";
    if (!el.textContent.trim()) {
      el.textContent = FALLBACK_SVG_MAP[name] || "•";
      el.style.fontStyle = "normal";
      el.style.fontSize = "0.85em";
    }
  });
}

function fallbackMarkdownToHtml(md) {
  if (!md) return "";
  const lines = String(md).split("\n");
  const out = [];
  let inList = false;
  let inTable = false;

  const fmtInline = (s) => escapeHtml(s)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trim = line.trim();

    if (trim.startsWith("|") && trim.endsWith("|")) {
      if (inList) { out.push("</ul>"); inList = false; }
      if (/^\|[\s\-:|]+\|$/.test(trim)) continue;
      const cells = trim.slice(1, -1).split("|").map((c) => c.trim());
      if (!inTable) {
        out.push("<table><thead><tr>" + cells.map((c) => `<th>${fmtInline(c)}</th>`).join("") + "</tr></thead><tbody>");
        inTable = true;
      } else {
        out.push("<tr>" + cells.map((c) => `<td>${fmtInline(c)}</td>`).join("") + "</tr>");
      }
      continue;
    } else if (inTable) {
      out.push("</tbody></table>");
      inTable = false;
    }

    if (!trim) {
      if (inList) { out.push("</ul>"); inList = false; }
      continue;
    }
    if (trim.startsWith("# ")) {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<h1>${fmtInline(trim.slice(2))}</h1>`);
    } else if (trim.startsWith("## ")) {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<h2>${fmtInline(trim.slice(3))}</h2>`);
    } else if (trim.startsWith("### ")) {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<h3>${fmtInline(trim.slice(4))}</h3>`);
    } else if (trim.startsWith("> ")) {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<blockquote>${fmtInline(trim.slice(2))}</blockquote>`);
    } else if (/^[-*•]\s+/.test(trim) || /^\d+\.\s+/.test(trim)) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${fmtInline(trim.replace(/^(?:[-*•]|\d+\.)\s+/, ""))}</li>`);
    } else {
      if (inList) { out.push("</ul>"); inList = false; }
      out.push(`<p>${fmtInline(trim)}</p>`);
    }
  }
  if (inList) out.push("</ul>");
  if (inTable) out.push("</tbody></table>");
  return out.join("\n");
}

function renderMarkdownSafe(md) {
  if (window.marked && typeof window.marked.parse === "function") {
    return window.marked.parse(md);
  }
  return fallbackMarkdownToHtml(md);
}

// ==========================================
// Audio Engine (Opt-In Subtle Feedback)
// ==========================================
let audioEnabled = localStorage.getItem("stellar_audio") === "true";
let audioCtx = null;

function getAudioContext() {
  if (!audioCtx) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) audioCtx = new AudioContext();
  }
  if (audioCtx && audioCtx.state === "suspended") {
    audioCtx.resume().catch(() => { });
  }
  return audioCtx;
}

function toggleAudio() {
  audioEnabled = !audioEnabled;
  localStorage.setItem("stellar_audio", audioEnabled ? "true" : "false");
  updateAudioIcon();
  if (audioEnabled) {
    playBlipSound(620, 0.06);
    showToast("Sound FX enabled", "info");
  } else {
    showToast("Sound FX muted", "info");
  }
}

function updateAudioIcon() {
  const icon = document.getElementById("audio-icon");
  const btn = document.getElementById("btn-audio-toggle");
  if (icon) {
    icon.setAttribute("data-feather", audioEnabled ? "volume-2" : "volume-x");
    safeReplaceIcons();
  }
  if (btn) btn.style.opacity = audioEnabled ? "1" : "0.65";
}

function playBlipSound(freq = 600, duration = 0.05) {
  if (!audioEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(freq, ctx.currentTime);
    gain.gain.setValueAtTime(0.035, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + duration);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + duration);
  } catch (e) { }
}

function playLaunchSound() {
  if (!audioEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(240, ctx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(760, ctx.currentTime + 0.25);
    gain.gain.setValueAtTime(0.045, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.25);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start();
    osc.stop(ctx.currentTime + 0.25);
  } catch (e) { }
}

function playSuccessChime() {
  if (!audioEnabled) return;
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    const notes = [523.25, 659.25, 783.99, 1046.50];
    notes.forEach((freq, idx) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, ctx.currentTime + idx * 0.07);
      gain.gain.setValueAtTime(0.04, ctx.currentTime + idx * 0.07);
      gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + idx * 0.07 + 0.3);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(ctx.currentTime + idx * 0.07);
      osc.stop(ctx.currentTime + idx * 0.07 + 0.3);
    });
  } catch (e) { }
}

function triggerCelebrationParticles() {
  const canvas = document.getElementById("celebration-canvas");
  if (!canvas) return;
  canvas.style.display = "block";
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const particles = [];
  const colors = ["#38bdf8", "#818cf8", "#10b981", "#f59e0b", "#ffffff"];
  for (let i = 0; i < 65; i++) {
    particles.push({
      x: canvas.width / 2 + (Math.random() - 0.5) * 240,
      y: canvas.height * 0.42,
      vx: (Math.random() - 0.5) * 14,
      vy: -Math.random() * 12 - 3,
      size: Math.random() * 5 + 3,
      color: colors[Math.floor(Math.random() * colors.length)],
      alpha: 1,
      decay: Math.random() * 0.018 + 0.015,
      rotation: Math.random() * 360,
      vRot: (Math.random() - 0.5) * 10,
    });
  }

  function frame() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    let activeCount = 0;
    particles.forEach((p) => {
      if (p.alpha > 0) {
        activeCount++;
        p.x += p.vx;
        p.y += p.vy;
        p.vy += 0.35;
        p.alpha -= p.decay;
        p.rotation += p.vRot;
        ctx.save();
        ctx.globalAlpha = Math.max(0, p.alpha);
        ctx.translate(p.x, p.y);
        ctx.rotate((p.rotation * Math.PI) / 180);
        ctx.fillStyle = p.color;
        ctx.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.7);
        ctx.restore();
      }
    });
    if (activeCount > 0) requestAnimationFrame(frame);
    else {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.style.display = "none";
    }
  }
  requestAnimationFrame(frame);
}

// ==========================================
// Topic Inspiration Generator
// ==========================================
const INSPIRED_TOPICS = [
  "DeepSeek-R1 vs Llama 3.3 70B: Reasoning efficiency, architecture, and RL cold-start",
  "Solid-State Lithium-Metal Batteries: Energy density, dendrite mitigation, and commercial scaling",
  "Post-Quantum Cryptography: Lattice-based Kyber and Dilithium NIST standardization bottlenecks",
  "Neuromorphic Computing: Spiking Neural Networks, energy efficiency vs GPUs, and event-based vision",
  "Room-Temperature Superconductivity Candidates: Hydride high-pressure physics and ambient claims",
  "Non-Invasive Diagnostic AI: Multi-modal palm and retinal imaging biomarkers for early triage",
  "Liquid Neural Networks & Continuous-Time Models: Adaptive inference and robotics control",
  "Mixture-of-Depths (MoD) and Dynamic Compute Allocation in Modern LLM Inference",
];
let lastInspireIndex = -1;

function inspireMeTopic() {
  playBlipSound(720, 0.06);
  let nextIdx;
  do {
    nextIdx = Math.floor(Math.random() * INSPIRED_TOPICS.length);
  } while (nextIdx === lastInspireIndex && INSPIRED_TOPICS.length > 1);
  lastInspireIndex = nextIdx;

  const topicInput = document.getElementById("research-topic-input");
  if (topicInput) {
    topicInput.value = INSPIRED_TOPICS[nextIdx];
    topicInput.focus();
    showToast("Loaded curated research topic", "success");
  }
}

// ==========================================
// Sidebar & Session Controls
// ==========================================
function toggleSidebar(forceOpen = null) {
  const shell = document.querySelector(".app-shell");
  if (!shell) return;
  if (forceOpen === true) shell.classList.remove("sidebar-collapsed");
  else if (forceOpen === false) shell.classList.add("sidebar-collapsed");
  else shell.classList.toggle("sidebar-collapsed");

  const isCollapsed = shell.classList.contains("sidebar-collapsed");
  localStorage.setItem("stellar_sidebar_collapsed", isCollapsed ? "true" : "false");
}

function initSidebarState() {
  const shell = document.querySelector(".app-shell");
  if (!shell) return;
  const saved = localStorage.getItem("stellar_sidebar_collapsed");
  if (saved === "true" || window.innerWidth < 860) {
    shell.classList.add("sidebar-collapsed");
  }
  window.addEventListener("resize", () => {
    if (window.innerWidth < 860) {
      shell.classList.add("sidebar-collapsed");
    }
  });
}

function startNewResearchSession() {
  playBlipSound(580, 0.05);
  if (autoPlayDeckInterval) toggleAutoPlayDeck();

  currentReportMarkdown = "";
  currentReportFilename = "";
  currentReportTitle = "";
  currentReportStarred = false;
  currentSources = [];
  lastRenderedChatTopicKey = "";
  chatHistory = [];

  const topicInput = document.getElementById("research-topic-input");
  const canvas = document.getElementById("react-execution-canvas");
  const reportStudio = document.getElementById("report-studio-container");
  const select = document.getElementById("repo-quick-select");
  const pill = document.getElementById("active-dossier-pill");

  if (canvas) canvas.style.display = "none";
  if (reportStudio) reportStudio.style.display = "none";
  if (select) select.value = "";
  if (pill) pill.style.display = "none";
  if (topicInput) topicInput.value = "";

  document.querySelectorAll(".sidebar-dossier-item").forEach((el) => el.classList.remove("active"));
  switchView("studio");
  if (topicInput) topicInput.focus();
}

function toggleTraceCollapse(forceCollapse = null) {
  const body = document.getElementById("trace-collapsible-body");
  const icon = document.getElementById("trace-chevron-icon");
  if (!body) return;

  const shouldCollapse = forceCollapse !== null ? forceCollapse : !body.classList.contains("collapsed");
  if (shouldCollapse) {
    body.classList.add("collapsed");
    if (icon) icon.setAttribute("data-feather", "chevron-down");
  } else {
    body.classList.remove("collapsed");
    if (icon) icon.setAttribute("data-feather", "chevron-up");
  }
  safeReplaceIcons();
}

function toggleAutoPlayDeck() {
  const btn = document.getElementById("btn-autoplay-deck");
  const icon = document.getElementById("autoplay-icon");
  if (autoPlayDeckInterval) {
    clearInterval(autoPlayDeckInterval);
    autoPlayDeckInterval = null;
    if (btn) btn.classList.remove("autoplay-active");
    if (icon) icon.setAttribute("data-feather", "play");
    safeReplaceIcons();
    showToast("Auto-Play paused", "info");
    playBlipSound(440, 0.05);
  } else {
    if (!currentSlides.length) {
      showToast("No slides available to play", "info");
      return;
    }
    if (currentReportViewMode !== "deck") switchReportMode("deck");
    setDeckViewStyle("stage");
    if (btn) btn.classList.add("autoplay-active");
    if (icon) icon.setAttribute("data-feather", "pause");
    safeReplaceIcons();
    showToast("Auto-Play running (5s/slide)", "success");
    playBlipSound(880, 0.07);

    autoPlayDeckInterval = setInterval(() => {
      if (currentSlideIndex >= currentSlides.length - 1) jumpToSlide(0);
      else navigateSlide(1);
    }, 5000);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initSidebarState();
  updateAudioIcon();
  safeReplaceIcons();
  configureMarkdownRenderer();
  fetchSystemStatus();
  loadReportsArchive();
  setupPdfDropZones();
  setupKeyboardNavigation();

  ["source-modal", "shortcuts-modal", "settings-modal"].forEach((id) => {
    const m = document.getElementById(id);
    if (m) {
      m.addEventListener("click", (e) => {
        if (e.target === m) m.style.display = "none";
      });
    }
  });

  setInterval(fetchSystemStatus, 12000);
});

// ==========================================
// Text Cleaning & Sanitization
// ==========================================
function cleanClientLLMText(text) {
  if (!text) return "";
  let cleaned = String(text).trim();

  cleaned = cleaned.replace(/<think>[\s\S]*?<\/think>/gi, "");
  cleaned = cleaned.replace(/<thought>[\s\S]*?<\/thought>/gi, "");
  cleaned = cleaned.replace(/\[THOUGHT\][\s\S]*?\[\/THOUGHT\]/gi, "");
  if (/<(?:think|thought)>/i.test(cleaned) && !/<\/(?:think|thought)>/i.test(cleaned)) {
    const hdr = cleaned.search(/\n+#\s+/);
    cleaned = hdr !== -1 ? cleaned.substring(hdr).trim() : cleaned.replace(/^<(?:think|thought)>[\s\S]*/i, "").trim();
  }

  cleaned = cleaned.replace(/<\/?(?:answer|output|response|result|report|final_answer|markdown)>\s*/gi, "");
  cleaned = cleaned.replace(/^\s*```(?:markdown|md|text)?\s*\n([\s\S]*?)\n\s*```\s*$/i, "$1");
  cleaned = cleaned.replace(/^\s*```(?:markdown|md|text)?\s*\n/i, "");
  cleaned = cleaned.replace(/\n\s*```\s*$/i, "");

  const preambles = [
    /^(?:Here (?:is|are) (?:the|a|your|my) (?:comprehensive |final |detailed |exhaustive )?(?:research )?(?:report|analysis|summary|document|overview)[\s\S]*?:)\s*/i,
    /^(?:Sure(?:thing)?[,!.]?\s*(?:(?:Here is|I have|below is|in this)[\s\S]*?:)?)\s*/i,
    /^(?:Certainly(?:,!.)?\s*(?:(?:Here is|I have|below is|in this)[\s\S]*?:)?)\s*/i,
    /^(?:Of course(?:,!.)?\s*(?:(?:Here is|I have|below is)[\s\S]*?:)?)\s*/i,
    /^(?:Understood(?:,!.)?\s*(?:(?:Here is|I have|below is)[\s\S]*?:)?)\s*/i,
    /^(?:Based on (?:the provided|the gathered|the indexed|your) (?:research|notes|sources|evidence|data|documents)[\s\S]*?:)\s*/i,
    /^(?:In this (?:technical )?(?:report|analysis|document),? (?:we will|we examine|we provide|we explore)[\s\S]*?:)\s*/i,
    /^(?:As an AI (?:research assistant|language model)[\s\S]*?:)\s*/i,
    /^(?:Below is (?:the|a) (?:final |comprehensive |detailed )?(?:research )?report[\s\S]*?:)\s*/i,
    /^(?:I have (?:thoroughly )?synthesized (?:the|your) (?:research|findings)[\s\S]*?:)\s*/i,
    /^(?:To answer your question:?\s*)/i,
    /^(?:Here (?:is|are) (?:the|a) (?:summary|breakdown|answer):?\s*)/i,
  ];
  for (let pass = 0; pass < 4; pass++) {
    const prev = cleaned;
    for (const p of preambles) cleaned = cleaned.replace(p, "").trim();
    if (cleaned === prev) break;
  }

  const postscripts = [
    /\n+(?:I hope this (?:(?:report|information|analysis) )?(?:helps|is useful|meets your expectations|answers your question)[\s\S]*$)/i,
    /\n+(?:Hope this (?:helps|is useful)[\s\S]*$)/i,
    /\n+(?:Let me know if you (?:need|would like|require|have)[\s\S]*$)/i,
    /\n+(?:Please let me know if (?:you need|there is)[\s\S]*$)/i,
    /\n+(?:Feel free to ask (?:any )?(?:further|follow-up|more) questions[\s\S]*$)/i,
    /\n+(?:If you have any (?:questions|further inquiries)[\s\S]*$)/i,
    /\n+\*(?:Note|Disclaimer):[\s\S]*$/i,
    /\n+\*\*(?:Note|Disclaimer):\*\*[\s\S]*$/i,
  ];
  for (const p of postscripts) cleaned = cleaned.replace(p, "");

  cleaned = cleaned.replace(/^(#{1,6}\s+)\*\*(.*?)\*\*:?$/gm, "$1$2");

  const lines = cleaned.split("\n");
  if (lines.length >= 3 && lines[0].startsWith("# ") && lines[1] === "" && lines[2].startsWith("# ")) {
    lines.shift();
    lines.shift();
    cleaned = lines.join("\n");
  }

  return cleaned.replace(/\n{3,}/g, "\n\n").trim();
}

// ==========================================
// Theme Engine (Light / Dark)
// ==========================================
function initTheme() {
  const savedTheme = localStorage.getItem("stellar_theme") || "dark";
  setTheme(savedTheme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  setTheme(current === "dark" ? "light" : "dark");
}

function setTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("stellar_theme", theme);
  const themeIcon = document.getElementById("theme-icon");
  if (themeIcon) {
    themeIcon.setAttribute("data-feather", theme === "dark" ? "sun" : "moon");
    safeReplaceIcons();
  }
}

function configureMarkdownRenderer() {
  if (window.marked) {
    marked.setOptions({
      highlight: function (code, lang) {
        if (window.hljs) {
          const language = hljs.getLanguage(lang) ? lang : "plaintext";
          return hljs.highlight(code, { language }).value;
        }
        return code;
      },
      breaks: true,
      gfm: true,
    });
  }
}

// ==========================================
// View & Depth Controls
// ==========================================
function switchView(viewName) {
  playBlipSound(520, 0.04);
  const tabs = ["studio", "memory", "reports", "tools"];
  tabs.forEach((tab) => {
    const btn = document.getElementById(`nav-${tab}-btn`);
    const panel = document.getElementById(`view-${tab}`);
    if (btn && panel) {
      if (tab === viewName) {
        btn.classList.add("active");
        panel.style.display = "flex";
      } else {
        btn.classList.remove("active");
        panel.style.display = "none";
      }
    }
  });

  if (window.innerWidth < 860) toggleSidebar(false);
  if (viewName === "memory") loadMemoryExplorer();
  if (viewName === "reports") loadReportsArchive();
  safeReplaceIcons();
}

function setResearchDepth(depth) {
  currentResearchDepth = depth;
  document.querySelectorAll(".depth-pill").forEach((pill) => {
    pill.classList.toggle("active", pill.getAttribute("data-depth") === depth);
  });
}

function toggleCustomUrls() {
  const drawer = document.getElementById("custom-urls-drawer");
  if (drawer) {
    const isHidden = drawer.style.display === "none";
    drawer.style.display = isHidden ? "flex" : "none";
    if (isHidden) document.getElementById("custom-urls-input")?.focus();
  }
}

// ==========================================
// System Status, Settings Modal & Model Management
// ==========================================
async function fetchSystemStatus() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) throw new Error("Status endpoint error");
    const data = await res.json();

    const badge = document.getElementById("system-status-badge");
    const memCount = document.getElementById("hud-memory-count");
    const repCount = document.getElementById("hud-reports-count");

    if (memCount) memCount.textContent = data.memory_chunks_count || 0;
    if (repCount) repCount.textContent = data.saved_reports_count || 0;

    if (badge) {
      const label = data.engine_label || (data.status === "ready" ? `${data.active_model} Ready` : "Offline Fact Engine");
      const dotClass = data.status === "ready" ? "online" : "warning";
      badge.innerHTML = `<span class="status-dot ${dotClass}"></span><span class="status-text" id="system-status-text">${escapeHtml(label)}</span>`;
      badge.title = `${data.engine_detail || data.ollama_health} — Click to configure AI Engine & Health`;
    }

    const jobBanner = document.getElementById("active-job-banner");
    if (jobBanner) {
      if ((data.active_jobs_count || 0) > 0 && !currentEventSource && data.active_jobs && data.active_jobs.length) {
        const activeJob = data.active_jobs[0];
        document.getElementById("active-job-topic").textContent = activeJob.topic;
        document.getElementById("active-job-steps").textContent = ` (Step ${activeJob.step_count || 0})`;
        jobBanner.style.display = "flex";
      } else {
        jobBanner.style.display = "none";
      }
    }

    const select = document.getElementById("model-select");
    if (select && data.available_models && data.available_models.length > 0) {
      select.innerHTML = "";
      data.available_models.forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m;
        opt.textContent = m + (m === data.active_model ? " (Active)" : "");
        if (m === data.active_model) opt.selected = true;
        select.appendChild(opt);
      });
    }
  } catch (err) {
    console.warn("Failed to fetch status:", err);
  }
}

async function onModelChange(modelName) {
  try {
    const res = await fetch("/api/model", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: modelName }),
    });
    const data = await res.json();
    if (res.ok) {
      playBlipSound(660, 0.05);
      showToast(`Model switched to ${data.active_model}`, "success");
      fetchSystemStatus();
    } else {
      showToast(data.detail || "Failed to switch model", "error");
    }
  } catch (err) {
    showToast("Error connecting to server", "error");
  }
}

async function openSettingsModal() {
  const modal = document.getElementById("settings-modal");
  if (!modal) return;
  modal.style.display = "flex";
  const resBox = document.getElementById("settings-test-result");
  if (resBox) resBox.style.display = "none";

  try {
    const [cfgRes, healthRes, netRes] = await Promise.all([
      fetch("/api/settings"),
      fetch("/api/health"),
      fetch("/api/network-info"),
    ]);

    if (cfgRes.ok) {
      const cfgData = await cfgRes.json();
      const s = cfgData.settings || {};
      cachedProviderPresets = cfgData.presets || {};
      document.getElementById("cfg-provider-mode").value = s.provider_mode || "auto";
      document.getElementById("cfg-ollama-host").value = s.ollama_host || "http://127.0.0.1:11434";
      document.getElementById("cfg-openai-preset").value = s.openai_preset || "groq";
      document.getElementById("cfg-openai-base-url").value = s.openai_base_url || "";
      document.getElementById("cfg-openai-model").value = s.openai_model || "";
      const keyInput = document.getElementById("cfg-openai-api-key");
      if (keyInput) keyInput.value = "";
      const keyStat = document.getElementById("cfg-api-key-status");
      if (keyStat) {
        keyStat.textContent = s.has_api_key ? `• Saved: ${s.openai_api_key_masked}` : "• Not configured";
      }
    }

    if (healthRes.ok) {
      const h = await healthRes.json();
      const grid = document.getElementById("settings-health-grid");
      if (grid) {
        grid.innerHTML = `
          <div class="health-stat-card">
            <span class="health-stat-label">Active Engine</span>
            <span class="health-stat-val">${escapeHtml(h.active_engine?.label || "Ready")}</span>
          </div>
          <div class="health-stat-card">
            <span class="health-stat-label">Vector Memory</span>
            <span class="health-stat-val">${escapeHtml(h.vector_store?.backend)} (${h.vector_store?.chunks || 0} chunks)</span>
          </div>
          <div class="health-stat-card">
            <span class="health-stat-label">Disk Cache</span>
            <span class="health-stat-val">${h.cache?.search_entries || 0} searches • ${h.cache?.scraped_pages || 0} pages</span>
          </div>
          <div class="health-stat-card">
            <span class="health-stat-label">Saved Workspace</span>
            <span class="health-stat-val">${h.storage?.reports || 0} dossiers • ${h.storage?.uploads || 0} uploads</span>
          </div>
        `;
      }
    }

    if (netRes.ok) {
      const n = await netRes.json();
      document.getElementById("lan-local-url").textContent = n.local_url || "http://127.0.0.1:8080";
      document.getElementById("lan-wifi-url").textContent = n.lan_url || "Unavailable";
    }
  } catch (err) {
    showToast(`Could not load settings: ${err.message}`, "error");
  }
  safeReplaceIcons();
}

function closeSettingsModal() {
  const modal = document.getElementById("settings-modal");
  if (modal) modal.style.display = "none";
}

function onProviderPresetChange(presetKey) {
  const preset = cachedProviderPresets[presetKey];
  if (!preset) return;
  document.getElementById("cfg-openai-base-url").value = preset.base_url || "";
  document.getElementById("cfg-openai-model").value = preset.default_model || "";
}

async function testProviderConnectionFromModal() {
  const mode = document.getElementById("cfg-provider-mode").value;
  const ollamaHost = document.getElementById("cfg-ollama-host").value.trim();
  const baseUrl = document.getElementById("cfg-openai-base-url").value.trim();
  const model = document.getElementById("cfg-openai-model").value.trim();
  const apiKey = document.getElementById("cfg-openai-api-key").value.trim();
  const box = document.getElementById("settings-test-result");

  if (box) {
    box.style.display = "block";
    box.className = "settings-test-result";
    box.textContent = "Testing connection...";
  }

  try {
    const res = await fetch("/api/settings/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider_mode: mode === "auto" && apiKey ? "openai_compatible" : mode,
        ollama_host: ollamaHost,
        openai_base_url: baseUrl,
        openai_model: model,
        openai_api_key: apiKey || null,
      }),
    });
    const data = await res.json();
    if (box) {
      box.className = `settings-test-result ${data.ok ? "ok" : "fail"}`;
      box.textContent = data.message || (data.ok ? "Connected!" : "Connection failed");
    }
  } catch (err) {
    if (box) {
      box.className = "settings-test-result fail";
      box.textContent = `Test error: ${err.message}`;
    }
  }
}

async function saveSettingsFromModal() {
  const payload = {
    provider_mode: document.getElementById("cfg-provider-mode").value,
    ollama_host: document.getElementById("cfg-ollama-host").value.trim(),
    openai_preset: document.getElementById("cfg-openai-preset").value,
    openai_base_url: document.getElementById("cfg-openai-base-url").value.trim(),
    openai_model: document.getElementById("cfg-openai-model").value.trim(),
  };
  const keyVal = document.getElementById("cfg-openai-api-key").value.trim();
  if (keyVal) payload.openai_api_key = keyVal;

  try {
    const res = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error("Failed to save settings");
    playBlipSound(720, 0.06);
    showToast("AI Engine settings saved!", "success");
    closeSettingsModal();
    fetchSystemStatus();
  } catch (err) {
    showToast(`Save error: ${err.message}`, "error");
  }
}

async function clearSavedApiKey() {
  try {
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clear_api_key: true }),
    });
    document.getElementById("cfg-openai-api-key").value = "";
    document.getElementById("cfg-api-key-status").textContent = "• Cleared";
    showToast("Saved API key removed", "info");
    fetchSystemStatus();
  } catch (err) {
    showToast(`Error clearing key: ${err.message}`, "error");
  }
}

async function pullOllamaModelFromModal() {
  const inp = document.getElementById("cfg-pull-model-name");
  const model = inp ? inp.value.trim() : "";
  if (!model) {
    showToast("Enter an Ollama model tag first (e.g. qwen2.5:7b)", "error");
    return;
  }
  showToast(`Pulling '${model}' from Ollama...`, "info");
  try {
    const res = await fetch("/api/ollama/pull", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_name: model }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Pull failed");
    showToast(`Pulled '${model}' successfully!`, "success");
    fetchSystemStatus();
  } catch (err) {
    showToast(err.message, "error");
  }
}

async function clearDiskCacheFromModal() {
  try {
    const res = await fetch("/api/cache/clear", { method: "POST" });
    if (res.ok) {
      showToast("Cleared cached web searches & pages", "success");
      openSettingsModal();
    }
  } catch (err) {
    showToast(`Failed to clear cache: ${err.message}`, "error");
  }
}

function copyLanAccessUrl() {
  const txt = document.getElementById("lan-wifi-url")?.textContent?.trim();
  if (!txt) return;
  navigator.clipboard?.writeText(txt)
    .then(() => showToast("LAN URL copied to clipboard!", "success"))
    .catch(() => showToast("Copy failed", "error"));
}

function fillPrompt(text) {
  const input = document.getElementById("research-topic-input");
  if (input) {
    input.value = text;
    input.focus();
  }
}

// ==========================================
// Universal Document Attachment & Drag-and-Drop
// ==========================================
function _isSupportedDocName(name) {
  const lower = (name || "").toLowerCase();
  return SUPPORTED_DOC_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function _bindDropTarget(el, targetContext) {
  if (!el) return;
  const activeCls = el.id === "composer-input-capsule" ? "dragover-capsule" : "dragover";
  ["dragenter", "dragover"].forEach((evName) => {
    el.addEventListener(evName, (e) => {
      e.preventDefault();
      el.classList.add(activeCls);
    });
  });
  ["dragleave", "drop"].forEach((evName) => {
    el.addEventListener(evName, (e) => {
      e.preventDefault();
      el.classList.remove(activeCls);
    });
  });
  el.addEventListener("drop", (e) => {
    const files = e.dataTransfer?.files;
    if (files && files.length > 0 && _isSupportedDocName(files[0].name)) {
      uploadDocumentFile(files[0], targetContext);
    } else if (files && files.length > 0) {
      showToast(`Supported files: ${SUPPORTED_DOC_EXTENSIONS.join(", ")}`, "error");
    }
  });
}

function setupPdfDropZones() {
  const dropZone = document.getElementById("pdf-drop-zone");
  if (dropZone) {
    dropZone.addEventListener("click", () => {
      document.getElementById("direct-pdf-input")?.click();
    });
    _bindDropTarget(dropZone, "direct");
  }
  const capsule = document.getElementById("composer-input-capsule");
  if (capsule) {
    _bindDropTarget(capsule, "hero");
  }
}

function handlePdfSelect(e) {
  const file = e.target.files[0];
  if (file) uploadDocumentFile(file, "hero");
}

function uploadDirectPdf(e) {
  const file = e.target.files[0];
  if (file) uploadDocumentFile(file, "direct");
}

async function uploadDocumentFile(file, targetContext) {
  const formData = new FormData();
  formData.append("file", file);
  showToast(`Indexing ${file.name}...`, "info");

  try {
    const res = await fetch("/api/upload-doc", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload failed");

    showToast(`Indexed ${data.chunks_extracted} chunks from ${data.filename}`, "success");
    fetchSystemStatus();

    if (targetContext === "hero") {
      currentAttachedPdfPath = data.file_path;
      const row = document.getElementById("attached-file-row");
      const badge = document.getElementById("attached-file-badge");
      const nameSpan = document.getElementById("attached-filename");
      if (row) row.style.display = "flex";
      if (badge && nameSpan) {
        nameSpan.textContent = `${data.filename} (${data.chunks_extracted} chunks)`;
        badge.style.display = "inline-flex";
      }
    } else if (targetContext === "direct") {
      const out = document.getElementById("direct-pdf-output");
      if (out) {
        out.innerHTML = `<strong>File:</strong> ${escapeHtml(data.filename)} (${escapeHtml(data.doc_type?.toUpperCase() || "DOC")})<br>` +
          `<strong>Pages / Sections:</strong> ${data.total_pages}<br>` +
          `<strong>Chunks Indexed:</strong> ${data.chunks_indexed}<br><br>` +
          `<strong>Preview:</strong><br>${escapeHtml(data.preview)}...`;
      }
    }
  } catch (err) {
    showToast(err.message, "error");
  }
}

function removeAttachment() {
  currentAttachedPdfPath = null;
  const row = document.getElementById("attached-file-row");
  const badge = document.getElementById("attached-file-badge");
  const fileInput = document.getElementById("pdf-file-input");
  if (row) row.style.display = "none";
  if (badge) badge.style.display = "none";
  if (fileInput) fileInput.value = "";
  showToast("Attachment removed", "info");
}

// ==========================================
// Autonomous Research Execution via SSE
// ==========================================
function startResearch() {
  const input = document.getElementById("research-topic-input");
  const topic = input ? input.value.trim() : "";

  if (!topic) {
    showToast("Please enter a research topic or question", "error");
    input?.focus();
    return;
  }

  const sourceScope = document.getElementById("source-scope-select")?.value || "all";
  const reportStyle = document.getElementById("report-style-select")?.value || "brief";
  if (sourceScope === "pdf_only" && !currentAttachedPdfPath) {
    showToast("Attach a PDF/DOCX/TXT/CSV file first when using 'Attached File Only' mode", "error");
    return;
  }

  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }
  if (autoPlayDeckInterval) toggleAutoPlayDeck();

  streamCompletedCleanly = false;
  const canvas = document.getElementById("react-execution-canvas");
  const streamContainer = document.getElementById("steps-stream-container");
  const reportStudio = document.getElementById("report-studio-container");
  const startBtn = document.getElementById("btn-start-research");
  const topicDisplay = document.getElementById("canvas-topic-display");
  const counterBadge = document.getElementById("step-counter-badge");
  const statusTitle = document.getElementById("canvas-status-title");
  const spinner = document.getElementById("agent-spinner");
  const activeDossierPill = document.getElementById("active-dossier-pill");
  const abortBtn = document.getElementById("btn-abort-research");
  const jobBanner = document.getElementById("active-job-banner");

  if (jobBanner) jobBanner.style.display = "none";
  if (activeDossierPill) activeDossierPill.style.display = "none";
  if (canvas) canvas.style.display = "flex";
  if (reportStudio) reportStudio.style.display = "none";
  if (streamContainer) streamContainer.innerHTML = "";
  if (startBtn) startBtn.disabled = true;
  if (topicDisplay) topicDisplay.textContent = topic;
  if (counterBadge) counterBadge.textContent = "Step 0";
  if (statusTitle) statusTitle.textContent = "Autonomous Multi-Source Research Deploying...";
  if (spinner) spinner.classList.remove("done");
  if (abortBtn) abortBtn.style.display = "inline-flex";

  toggleTraceCollapse(false);
  startExecutionTimer();
  playLaunchSound();
  resetStepper();
  updateStepper("plan");

  canvas?.scrollIntoView({ behavior: "smooth", block: "start" });

  const model = document.getElementById("model-select")?.value || "";
  const customUrls = document.getElementById("custom-urls-input")?.value.trim() || "";

  let url = `/api/stream-research?topic=${encodeURIComponent(topic)}&depth=${encodeURIComponent(currentResearchDepth)}&source_scope=${encodeURIComponent(sourceScope)}&report_style=${encodeURIComponent(reportStyle)}`;
  if (model) url += `&model_name=${encodeURIComponent(model)}`;
  if (currentAttachedPdfPath) url += `&pdf_path=${encodeURIComponent(currentAttachedPdfPath)}`;
  if (customUrls) url += `&custom_urls=${encodeURIComponent(customUrls)}`;

  currentEventSource = new EventSource(url);

  currentEventSource.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      handleAgentEvent(msg);
    } catch (e) {
      console.error("Failed to parse SSE event:", e);
    }
  };

  currentEventSource.addEventListener("close", () => {
    streamCompletedCleanly = true;
    stopExecutionTimer();
    if (startBtn) startBtn.disabled = false;
    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }
  });

  currentEventSource.onerror = () => {
    stopExecutionTimer();
    if (startBtn) startBtn.disabled = false;
    if (!streamCompletedCleanly && statusTitle) {
      statusTitle.textContent = "Research Connection Closed";
    }
    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }
  };
}

function startExecutionTimer() {
  stopExecutionTimer();
  executionStartTime = Date.now();
  const timerEl = document.getElementById("canvas-timer");
  if (timerEl) timerEl.textContent = "00:00";

  executionTimerInterval = setInterval(() => {
    if (!executionStartTime) return;
    const elapsedSec = Math.floor((Date.now() - executionStartTime) / 1000);
    const m = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
    const s = String(elapsedSec % 60).padStart(2, "0");
    if (timerEl) timerEl.textContent = `${m}:${s}`;
  }, 1000);
}

function stopExecutionTimer() {
  if (executionTimerInterval) {
    clearInterval(executionTimerInterval);
    executionTimerInterval = null;
  }
}

function handleAgentEvent(event) {
  const streamContainer = document.getElementById("steps-stream-container");
  const counterBadge = document.getElementById("step-counter-badge");
  const statusTitle = document.getElementById("canvas-status-title");
  const startBtn = document.getElementById("btn-start-research");
  const spinner = document.getElementById("agent-spinner");
  const abortBtn = document.getElementById("btn-abort-research");

  if (event.type === "start") {
    if (statusTitle) statusTitle.textContent = `Researching with ${event.model} (${event.depth})...`;
  } else if (event.type === "step") {
    const stepData = event.data;
    const stepNum = stepData.step;
    const action = stepData.action || "analyzing";
    const thought = stepData.thought || "";
    const obs = stepData.observation || "";

    if (counterBadge) counterBadge.textContent = `Step ${stepNum}`;
    if (action === "web_search") updateStepper("search");
    else if (action === "scrape_page") updateStepper("scrape");
    else if (action === "load_pdf" || action === "vector_search") updateStepper("memory");
    else if (action === "finish_research") updateStepper("synthesize");

    const card = document.createElement("div");
    card.className = "step-card";
    card.innerHTML = `
      <div class="step-card-header">
        <div class="step-card-meta">
          <span class="step-num-pill">Step ${stepNum}</span>
          <span class="action-pill">${escapeHtml(action)}</span>
        </div>
      </div>
      <div class="step-thought">${escapeHtml(thought)}</div>
      <div class="step-observation">${escapeHtml(obs)}</div>
    `;
    if (streamContainer) {
      streamContainer.appendChild(card);
      streamContainer.scrollTop = streamContainer.scrollHeight;
      playBlipSound(480, 0.03);
    }
  } else if (event.type === "complete") {
    streamCompletedCleanly = true;
    stopExecutionTimer();
    updateStepper("synthesize");
    if (statusTitle) statusTitle.textContent = "Research Complete • Dossier Ready";
    if (spinner) spinner.classList.add("done");
    if (startBtn) startBtn.disabled = false;
    if (abortBtn) abortBtn.style.display = "none";

    toggleTraceCollapse(true);

    currentReportMarkdown = event.report;
    currentReportFilename = event.filename;
    currentReportStarred = false;
    currentSources = event.sources || [];

    renderReportStudio(event.report, event.filename, currentSources, false);
    loadReportsArchive();
    fetchSystemStatus();

    playSuccessChime();
    triggerCelebrationParticles();
    showToast("Research dossier synthesized!", "success");

    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }
  } else if (event.type === "error") {
    streamCompletedCleanly = true;
    stopExecutionTimer();
    showToast(`Error: ${event.message}`, "error");
    if (statusTitle) statusTitle.textContent = "Execution Interrupted";
    if (startBtn) startBtn.disabled = false;
    if (abortBtn) abortBtn.style.display = "none";
    if (spinner) spinner.classList.add("done");
    if (currentEventSource) {
      currentEventSource.close();
      currentEventSource = null;
    }
  }
}

function abortResearch() {
  streamCompletedCleanly = true;
  fetch("/api/cancel-research", { method: "POST" }).catch((e) => console.warn("Cancel signal error:", e));
  if (currentEventSource) {
    currentEventSource.close();
    currentEventSource = null;
  }
  stopExecutionTimer();
  showToast("Research stopped", "info");
  const statusTitle = document.getElementById("canvas-status-title");
  const startBtn = document.getElementById("btn-start-research");
  const spinner = document.getElementById("agent-spinner");
  const abortBtn = document.getElementById("btn-abort-research");
  const jobBanner = document.getElementById("active-job-banner");
  if (jobBanner) jobBanner.style.display = "none";
  if (statusTitle) statusTitle.textContent = "Research Stopped by User";
  if (spinner) spinner.classList.add("done");
  if (startBtn) startBtn.disabled = false;
  if (abortBtn) abortBtn.style.display = "none";
}

function resetStepper() {
  ["plan", "search", "scrape", "memory", "synthesize"].forEach((p) => {
    document.getElementById(`phase-${p}`)?.classList.remove("active", "completed");
  });
  for (let i = 1; i <= 4; i++) {
    document.getElementById(`line-${i}`)?.classList.remove("active");
  }
}

function updateStepper(activePhase) {
  const phases = ["plan", "search", "scrape", "memory", "synthesize"];
  const activeIdx = phases.indexOf(activePhase);
  phases.forEach((p, idx) => {
    const el = document.getElementById(`phase-${p}`);
    if (el) {
      el.classList.toggle("completed", idx < activeIdx);
      el.classList.toggle("active", idx === activeIdx);
    }
    if (idx < phases.length - 1) {
      document.getElementById(`line-${idx + 1}`)?.classList.toggle("active", idx < activeIdx);
    }
  });
}

// ==========================================
// Report Studio, Star / Rename & Slide Deck
// ==========================================
function syncStarButton(starred) {
  currentReportStarred = Boolean(starred);
  const btn = document.getElementById("btn-star-dossier");
  if (!btn) return;
  btn.classList.toggle("starred", currentReportStarred);
  btn.innerHTML = `<i data-feather="star"></i> <span>${currentReportStarred ? "Starred" : "Star"}</span>`;
  safeReplaceIcons();
}

async function toggleCurrentReportStar() {
  if (!currentReportFilename) {
    showToast("Load or generate a dossier first", "info");
    return;
  }
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(currentReportFilename)}/star`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (!res.ok) throw new Error("Failed to bookmark dossier");
    const data = await res.json();
    syncStarButton(data.starred);
    loadReportsArchive();
    showToast(data.starred ? "Dossier starred!" : "Removed star", "success");
  } catch (err) {
    showToast(`Star error: ${err.message}`, "error");
  }
}

async function toggleReportCardStar(filename, event) {
  if (event) event.stopPropagation();
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(filename)}/star`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (res.ok) {
      const data = await res.json();
      if (filename === currentReportFilename) syncStarButton(data.starred);
      loadReportsArchive();
    }
  } catch (err) {
    showToast(`Error updating star: ${err.message}`, "error");
  }
}

async function renameCurrentReportPrompt() {
  if (!currentReportFilename) return;
  const proposed = prompt("Enter a clean title for this dossier:", currentReportTitle || "");
  if (!proposed || !proposed.trim() || proposed.trim() === currentReportTitle) return;
  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(currentReportFilename)}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_title: proposed.trim() }),
    });
    if (!res.ok) throw new Error("Rename failed");
    const data = await res.json();
    currentReportTitle = data.title;
    const titleEl = document.getElementById("report-display-title");
    if (titleEl) titleEl.textContent = data.title;
    const pillTitle = document.getElementById("active-dossier-title");
    if (pillTitle) pillTitle.textContent = data.title;
    loadReportsArchive();
    showToast("Dossier renamed!", "success");
  } catch (err) {
    showToast(`Rename error: ${err.message}`, "error");
  }
}

function resetChatForDossier(title) {
  chatHistory = [];
  const container = document.getElementById("chat-messages-container");
  if (!container) return;
  const cleanTitle = (title || "this research topic").replace(
    /^(?:Research\s+(?:Intelligence\s+)?Report|In-Depth\s+Research\s+Report|Executive\s+Research\s+Dossier|Academic\s+Literature\s+Review|Comparative\s+Benchmark\s+Matrix|Structured\s+Study\s+Guide|Technical\s+Decision\s+Memo)\s*:\s*/i,
    ""
  );
  container.innerHTML = `
    <div class="chat-msg assistant">
      <div class="msg-avatar"><i data-feather="cpu"></i></div>
      <div class="msg-content">
        <div class="msg-text-content">Ask any question about <strong>${escapeHtml(cleanTitle)}</strong> to see verified findings here.</div>
      </div>
    </div>
  `;
  safeReplaceIcons();
}

function renderDocOutlineBar(docEl) {
  const bar = document.getElementById("doc-outline-bar");
  if (!bar || !docEl) return;
  const headings = Array.from(docEl.querySelectorAll("h2"));
  if (headings.length < 2) {
    bar.style.display = "none";
    bar.innerHTML = "";
    return;
  }
  bar.innerHTML = "";
  headings.forEach((h, i) => {
    h.id = `doc-sec-${i}`;
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = "outline-pill";
    const label = h.textContent.replace(/[\u{1F300}-\u{1FAFF}\u2600-\u27BF]/gu, "").trim();
    pill.textContent = label || h.textContent.trim();
    pill.onclick = () => {
      h.scrollIntoView({ behavior: "smooth", block: "start" });
      playBlipSound(620, 0.03);
    };
    bar.appendChild(pill);
  });
  bar.style.display = "flex";
}

function renderReportStudio(markdownContent, filename, sources = [], starred = false) {
  const container = document.getElementById("report-studio-container");
  const docArticle = document.getElementById("rendered-markdown-output");
  const titleEl = document.getElementById("report-display-title");
  const timestampEl = document.getElementById("report-meta-timestamp");
  const citationsList = document.getElementById("citations-list-container");
  const citationsCount = document.getElementById("citations-count");

  if (!container || !docArticle) return;

  markdownContent = cleanClientLLMText(markdownContent);

  let docTitle = "Autonomous Research Report";
  for (const l of markdownContent.split("\n")) {
    if (l.startsWith("# ")) {
      docTitle = l.replace("# ", "").trim();
      break;
    }
  }
  currentReportTitle = docTitle;
  syncStarButton(starred);

  const topicKey = `${filename || ""}::${docTitle}`;
  if (topicKey !== lastRenderedChatTopicKey) {
    lastRenderedChatTopicKey = topicKey;
    resetChatForDossier(docTitle);
  }

  if (titleEl) titleEl.textContent = docTitle;
  if (timestampEl) timestampEl.textContent = `${new Date().toLocaleDateString()} • ${filename || "report.md"}`;

  const words = markdownContent.split(/\s+/).filter(Boolean).length;
  const readMin = Math.max(1, Math.round(words / 200));
  const readTimeEl = document.getElementById("report-read-time");
  const slideCountEl = document.getElementById("report-slide-count");
  const groundScoreEl = document.getElementById("report-grounding-score");

  if (readTimeEl) readTimeEl.innerHTML = `<i data-feather="clock"></i> ${readMin} min read (${words.toLocaleString()} words)`;

  let html = renderMarkdownSafe(markdownContent);
  html = html.replace(/\[(\d+)\]/g, (match, num) => {
    return `<a class="citation-ref" href="#citation-card-${num}" onclick="highlightCitationCard(${num}, event)">[${num}]</a>`;
  });
  docArticle.innerHTML = html;
  renderDocOutlineBar(docArticle);

  const csvBtn = document.getElementById("btn-export-csv");
  if (csvBtn) csvBtn.style.display = docArticle.querySelector("table") ? "inline-flex" : "none";

  renderSlideDeck(markdownContent);

  if (citationsList) {
    citationsList.innerHTML = "";
    let activeSources = Array.isArray(sources) ? [...sources] : [];

    if (activeSources.length === 0 && markdownContent) {
      for (const line of markdownContent.split("\n")) {
        const numMatch = line.match(/(?:`?\[(\d+)\]`?)/);
        const urlMatch = line.match(/(https?:\/\/[^\s\)\>\]]+)/);
        if (numMatch && urlMatch) {
          const titleMatch = line.match(/\*\*([^*]+)\*\*/);
          activeSources.push({
            title: titleMatch ? titleMatch[1].trim() : `Reference [${numMatch[1]}]`,
            url: urlMatch[1].replace(/[\)\]]+$/, ""),
            type: "Citation",
          });
        }
      }
      if (activeSources.length === 0) {
        const linkRegex = /\[(.*?)\]\((https?:\/\/[^\s\)]+)\)/g;
        let m;
        while ((m = linkRegex.exec(markdownContent)) !== null) {
          if (!m[2].includes("advanced_logo")) {
            activeSources.push({ title: m[1].trim() || "Web Source", url: m[2].trim(), type: "Web" });
          }
        }
      }
    }

    currentSources = activeSources;
    const uniqueSources = [];
    const seen = new Set();
    activeSources.forEach((s) => {
      const key = s.url || s.title;
      if (key && !seen.has(key)) {
        seen.add(key);
        uniqueSources.push(s);
      }
    });

    if (citationsCount) citationsCount.textContent = uniqueSources.length;
    if (slideCountEl) slideCountEl.innerHTML = `<i data-feather="airplay"></i> ${currentSlides.length || 1} Slides`;
    if (groundScoreEl) groundScoreEl.innerHTML = `<i data-feather="shield-check"></i> ${uniqueSources.length} Grounded Sources`;

    if (uniqueSources.length === 0) {
      citationsList.innerHTML = `<div class="dim-text" style="padding: 1.5rem; text-align: center;">No external URLs recorded.</div>`;
    } else {
      uniqueSources.forEach((src, idx) => {
        const citeNum = idx + 1;
        const card = document.createElement("div");
        card.className = "citation-card";
        card.id = `citation-card-${citeNum}`;
        card.innerHTML = `
          <div class="citation-card-top">
            <span class="citation-badge">[${citeNum}]</span>
            <span class="citation-type">${escapeHtml(src.type || "Web")}</span>
          </div>
          <div class="citation-title">${escapeHtml(src.title || "Source Reference")}</div>
          <div class="citation-card-actions">
            <a class="citation-url" href="${escapeHtml(src.url)}" target="_blank" rel="noopener noreferrer" title="${escapeHtml(src.url)}">
              ${escapeHtml(src.url)}
            </a>
            <button type="button" class="btn-inspect-src" onclick="inspectSourceContent('${escapeHtml(src.url)}', '${escapeHtml(src.title)}')">View Text</button>
          </div>
        `;
        citationsList.appendChild(card);
      });
    }
  }

  document.querySelectorAll(".sidebar-dossier-item").forEach((el) => {
    el.classList.toggle("active", el.getAttribute("data-filename") === filename);
  });

  container.style.display = "flex";
  switchReportMode(currentReportViewMode);
  safeReplaceIcons();
  container.scrollIntoView({ behavior: "smooth", block: "start" });
}

function switchReportMode(mode) {
  currentReportViewMode = mode;
  if (mode === "doc" || mode === "deck") localStorage.setItem("stellar_report_mode", mode);

  const docBtn = document.getElementById("btn-view-doc");
  const deckBtn = document.getElementById("btn-view-deck");
  const editBtn = document.getElementById("btn-view-edit");
  const docEl = document.getElementById("rendered-markdown-output");
  const outlineBar = document.getElementById("doc-outline-bar");
  const deckEl = document.getElementById("slide-deck-wrapper");
  const editEl = document.getElementById("report-editor-wrapper");
  const editTxt = document.getElementById("report-editor-textarea");

  docBtn?.classList.remove("active");
  deckBtn?.classList.remove("active");
  editBtn?.classList.remove("active");
  if (docEl) docEl.style.display = "none";
  if (outlineBar) outlineBar.style.display = "none";
  if (deckEl) deckEl.style.display = "none";
  if (editEl) editEl.style.display = "none";

  if (mode === "deck") {
    deckBtn?.classList.add("active");
    if (deckEl) deckEl.style.display = "flex";
  } else if (mode === "edit") {
    if (autoPlayDeckInterval) toggleAutoPlayDeck();
    editBtn?.classList.add("active");
    if (editTxt) editTxt.value = currentReportMarkdown || "";
    if (editEl) editEl.style.display = "flex";
    editTxt?.focus();
  } else {
    if (autoPlayDeckInterval) toggleAutoPlayDeck();
    docBtn?.classList.add("active");
    if (docEl) docEl.style.display = "block";
    if (outlineBar && outlineBar.children.length >= 2) outlineBar.style.display = "flex";
  }
}

async function saveEditedReport() {
  const editTxt = document.getElementById("report-editor-textarea");
  const newContent = editTxt ? editTxt.value.trim() : "";
  if (!newContent) {
    showToast("Report content cannot be empty", "error");
    return;
  }

  if (!currentReportFilename) {
    currentReportMarkdown = newContent;
    currentReportViewMode = "doc";
    renderReportStudio(newContent, "", currentSources, currentReportStarred);
    showToast("Preview updated locally", "success");
    return;
  }

  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(currentReportFilename)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: newContent }),
    });
    if (!res.ok) throw new Error("Failed to save dossier");
    currentReportMarkdown = newContent;
    currentReportViewMode = "doc";
    renderReportStudio(newContent, currentReportFilename, currentSources, currentReportStarred);
    loadReportsArchive();
    playBlipSound(720, 0.06);
    showToast("Dossier changes saved!", "success");
  } catch (err) {
    showToast(`Save error: ${err.message}`, "error");
  }
}

function renderSlideDeck(markdown) {
  const sections = markdown.split(/(?=^##\s+)/m);
  currentSlides = [];
  let slideIndex = 1;

  sections.forEach((sec) => {
    const trimmed = sec.trim();
    if (!trimmed) return;
    let tag = "RESEARCH PILLAR";
    let headline = "Analysis Overview";
    const contentLines = [];

    for (const l of trimmed.split("\n")) {
      if (l.startsWith("# ")) {
        tag = "EXECUTIVE BRIEFING";
        headline = l.replace("# ", "").trim();
      } else if (l.startsWith("## ")) {
        headline = l.replace("## ", "").trim();
        const hLow = headline.toLowerCase();
        if (hLow.includes("executive summary")) tag = "EXECUTIVE SUMMARY";
        else if (hLow.includes("quantitative") || hLow.includes("benchmark") || hLow.includes("metric")) tag = "KEY METRICS & DATA";
        else if (hLow.includes("architecture") || hLow.includes("deep-dive")) tag = "ARCHITECTURE";
        else if (hLow.includes("comparative") || hLow.includes("trade-off")) tag = "TRADE-OFFS";
        else if (hLow.includes("limitation") || hLow.includes("bottleneck")) tag = "LIMITATIONS";
        else if (hLow.includes("trajectory") || hLow.includes("outlook")) tag = "FUTURE OUTLOOK";
        else if (hLow.includes("reference") || hLow.includes("source")) tag = "VERIFIED SOURCES";
      } else {
        contentLines.push(l);
      }
    }

    const rawBody = contentLines.join("\n").trim();
    let htmlBody = renderMarkdownSafe(rawBody);
    htmlBody = htmlBody.replace(/\[(\d+)\]/g, (match, num) => {
      return `<a class="citation-ref" href="#citation-card-${num}" onclick="highlightCitationCard(${num}, event)">[${num}]</a>`;
    });

    currentSlides.push({
      index: slideIndex,
      tag: tag,
      headline: headline,
      htmlBody: htmlBody,
      isMag: slideIndex % 2 === 0,
    });
    slideIndex++;
  });

  if (currentSlides.length === 0) {
    currentSlides.push({
      index: 1,
      tag: "EXECUTIVE BRIEFING",
      headline: "Research Summary",
      htmlBody: `<p>${escapeHtml(markdown)}</p>`,
      isMag: false,
    });
  }

  currentSlideIndex = 0;
  renderCurrentSlide();
  renderGridSlides();
}

function renderCurrentSlide() {
  const stage = document.getElementById("slide-stage-screen");
  const trackerLabel = document.getElementById("slide-tracker-label");
  const stageBadge = document.getElementById("slide-stage-badge");
  const prevBtn = document.getElementById("btn-slide-prev");
  const nextBtn = document.getElementById("btn-slide-next");
  const dotsContainer = document.getElementById("slide-progress-dots");

  if (!stage || !currentSlides.length) return;
  const slide = currentSlides[currentSlideIndex];

  if (trackerLabel) trackerLabel.textContent = `Slide ${currentSlideIndex + 1} of ${currentSlides.length}`;
  if (stageBadge) stageBadge.textContent = `✦ ${slide.tag}`;
  if (prevBtn) prevBtn.disabled = currentSlideIndex === 0;
  if (nextBtn) nextBtn.disabled = currentSlideIndex === currentSlides.length - 1;

  stage.innerHTML = `
    <div class="stellar-slide-card ${slide.isMag ? "mag" : ""} slide-stage-card slide-transition-in">
      <div class="slide-top-bar">
        <div class="slide-brand-watermark">
          <img src="/static/assets/advanced_logo.png" alt="advanced" class="micro-advanced-logo" onerror="this.style.display='none'">
          <span>advanced</span>
        </div>
        <span class="slide-tag">✦ ${escapeHtml(slide.tag)}</span>
        <span class="slide-number">Slide ${slide.index} / ${currentSlides.length}</span>
      </div>
      <div class="slide-headline">${escapeHtml(slide.headline)}</div>
      <div class="slide-body-content">${slide.htmlBody}</div>
    </div>
  `;

  if (dotsContainer) {
    dotsContainer.innerHTML = "";
    currentSlides.forEach((s, idx) => {
      const dot = document.createElement("button");
      dot.type = "button";
      dot.className = `slide-dot-pill ${idx === currentSlideIndex ? "active" : ""}`;
      dot.title = `Slide ${idx + 1}: ${s.headline}`;
      dot.onclick = () => jumpToSlide(idx);
      dot.innerHTML = `<span>${idx + 1}</span>`;
      dotsContainer.appendChild(dot);
    });
  }

  safeReplaceIcons();
}

function renderGridSlides() {
  const gridContainer = document.getElementById("slide-grid-container");
  if (!gridContainer || !currentSlides.length) return;

  gridContainer.innerHTML = "";
  currentSlides.forEach((slide, idx) => {
    const card = document.createElement("div");
    card.className = `stellar-slide-card ${slide.isMag ? "mag" : ""} grid-slide-card ${idx === currentSlideIndex ? "selected-grid-slide" : ""}`;
    card.onclick = () => {
      jumpToSlide(idx);
      setDeckViewStyle("stage");
    };
    card.innerHTML = `
      <div class="slide-top-bar">
        <span class="slide-tag">✦ ${escapeHtml(slide.tag)}</span>
        <span class="slide-number">#${slide.index}</span>
      </div>
      <div class="slide-headline grid-headline">${escapeHtml(slide.headline)}</div>
      <div class="slide-body-content grid-body">${slide.htmlBody}</div>
      <div class="grid-slide-hover-action">
        <i data-feather="play"></i> <span>Open Slide ${slide.index}</span>
      </div>
    `;
    gridContainer.appendChild(card);
  });
}

function navigateSlide(direction) {
  if (!currentSlides.length) return;
  const newIndex = currentSlideIndex + direction;
  if (newIndex >= 0 && newIndex < currentSlides.length) jumpToSlide(newIndex);
}

function jumpToSlide(index) {
  if (index < 0 || index >= currentSlides.length) return;
  playBlipSound(650, 0.04);
  currentSlideIndex = index;
  renderCurrentSlide();
}

function setDeckViewStyle(style) {
  currentDeckViewStyle = style;
  const stageBtn = document.getElementById("btn-stage-view");
  const gridBtn = document.getElementById("btn-grid-view");
  const stageContainer = document.getElementById("slide-stage-container");
  const stageFooter = document.getElementById("slide-stage-footer");
  const gridContainer = document.getElementById("slide-grid-container");

  if (style === "grid") {
    stageBtn?.classList.remove("active");
    gridBtn?.classList.add("active");
    if (stageContainer) stageContainer.style.display = "none";
    if (stageFooter) stageFooter.style.display = "none";
    if (gridContainer) gridContainer.style.display = "grid";
  } else {
    stageBtn?.classList.add("active");
    gridBtn?.classList.remove("active");
    if (stageContainer) stageContainer.style.display = "flex";
    if (stageFooter) stageFooter.style.display = "flex";
    if (gridContainer) gridContainer.style.display = "none";
  }
}

function toggleFullscreenDeck() {
  const wrapper = document.getElementById("slide-deck-wrapper");
  if (!wrapper) return;
  if (!document.fullscreenElement) {
    if (wrapper.requestFullscreen) wrapper.requestFullscreen().catch(() => { });
  } else if (document.exitFullscreen) {
    document.exitFullscreen().catch(() => { });
  }
}

function toggleShortcutsModal() {
  const modal = document.getElementById("shortcuts-modal");
  if (modal) {
    const isVisible = modal.style.display === "flex";
    modal.style.display = isVisible ? "none" : "flex";
    safeReplaceIcons();
  }
}

function closeShortcutsModal() {
  const modal = document.getElementById("shortcuts-modal");
  if (modal) modal.style.display = "none";
}

function setupKeyboardNavigation() {
  window.addEventListener("keydown", (e) => {
    const isTyping = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);

    if ((e.ctrlKey && e.key.toLowerCase() === "k") || (e.key === "/" && !isTyping)) {
      e.preventDefault();
      switchView("studio");
      const inp = document.getElementById("research-topic-input");
      if (inp) {
        inp.focus();
        inp.select();
      }
      return;
    }

    if (e.key === "?" && !isTyping) {
      e.preventDefault();
      toggleShortcutsModal();
      return;
    }

    if (e.key === "Escape") {
      closeSourceModal();
      closeShortcutsModal();
      closeSettingsModal();
      if (document.fullscreenElement && document.exitFullscreen) {
        document.exitFullscreen().catch(() => { });
      }
      return;
    }

    if (isTyping) return;

    if (["1", "2", "3", "4"].includes(e.key)) {
      e.preventDefault();
      const views = { "1": "studio", "2": "reports", "3": "memory", "4": "tools" };
      switchView(views[e.key]);
      return;
    }

    const reportStudio = document.getElementById("report-studio-container");
    const isReportVisible = reportStudio && reportStudio.style.display !== "none";

    if (isReportVisible && currentReportViewMode === "deck") {
      if (e.key === "ArrowLeft") {
        e.preventDefault();
        navigateSlide(-1);
      } else if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        navigateSlide(1);
      } else if (e.key === "Home") {
        e.preventDefault();
        jumpToSlide(0);
      } else if (e.key === "End") {
        e.preventDefault();
        jumpToSlide(currentSlides.length - 1);
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        toggleFullscreenDeck();
      }
    }
  });
}

let citationFilterTimeout = null;
function filterCitationsList(query) {
  clearTimeout(citationFilterTimeout);
  citationFilterTimeout = setTimeout(() => {
    const q = (query || "").toLowerCase().trim();
    document.querySelectorAll(".citation-card").forEach((card) => {
      card.style.display = !q || card.textContent.toLowerCase().includes(q) ? "flex" : "none";
    });
  }, 120);
}

function fillChatQuestion(text) {
  const input = document.getElementById("chat-question-input");
  if (input) {
    input.value = text;
    sendFollowUpQuestion();
  }
}

function highlightCitationCard(num, event) {
  if (event) event.preventDefault();
  const card = document.getElementById(`citation-card-${num}`);
  if (card) {
    document.querySelectorAll(".citation-card").forEach((c) => c.classList.remove("highlighted"));
    card.classList.add("highlighted");
    card.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

// ==========================================
// Interactive Questioning (Clean Results Only)
// ==========================================
function toggleChatWebAugment() {
  chatWebAugment = !chatWebAugment;
  const btn = document.getElementById("chat-web-augment-toggle");
  if (btn) {
    btn.classList.toggle("active", chatWebAugment);
    btn.innerHTML = `<i data-feather="globe"></i> <span>Web Augment: ${chatWebAugment ? "On" : "Off"}</span>`;
    safeReplaceIcons();
  }
  playBlipSound(chatWebAugment ? 720 : 480, 0.05);
}

function clearChatThread() {
  resetChatForDossier(currentReportTitle || "this topic");
  showToast("Chat cleared", "info");
}

async function sendFollowUpQuestion() {
  const input = document.getElementById("chat-question-input");
  const sendBtn = document.querySelector(".btn-chat-send");
  const question = input ? input.value.trim() : "";
  const container = document.getElementById("chat-messages-container");

  if (!question || !container) return;

  const userMsg = document.createElement("div");
  userMsg.className = "chat-msg user";
  userMsg.innerHTML = `
    <div class="msg-avatar"><i data-feather="user"></i></div>
    <div class="msg-content">${escapeHtml(question)}</div>
  `;
  container.appendChild(userMsg);
  input.value = "";
  input.disabled = true;
  if (sendBtn) sendBtn.disabled = true;
  input.placeholder = chatWebAugment ? "Searching topic & live web sources..." : "Searching researched topic...";
  safeReplaceIcons();
  userMsg.scrollIntoView({ behavior: "smooth", block: "nearest" });

  const botMsg = document.createElement("div");
  botMsg.className = "chat-msg assistant";
  botMsg.innerHTML = `
    <div class="msg-avatar"><i data-feather="cpu"></i></div>
    <div class="msg-content">
      <div class="chat-typing-row">
        <span>${chatWebAugment ? "Checking topic & live web..." : "Extracting findings..."}</span>
        <span class="chat-typing-dots"><span></span><span></span><span></span></span>
      </div>
    </div>
  `;
  container.appendChild(botMsg);
  safeReplaceIcons();
  botMsg.scrollIntoView({ behavior: "smooth", block: "nearest" });

  try {
    const topicInput = document.getElementById("research-topic-input");
    const activeDossierEl = document.getElementById("active-dossier-title");
    const activeTopic = currentReportTitle ||
      (activeDossierEl && activeDossierEl.textContent !== "None" ? activeDossierEl.textContent.trim() : "") ||
      (topicInput ? topicInput.value.trim() : "");

    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question,
        topic: activeTopic || null,
        report_filename: currentReportFilename || null,
        report_text: currentReportMarkdown || null,
        web_augment: chatWebAugment,
        chat_history: chatHistory.slice(-4),
      }),
    });
    const data = await res.json();

    const cleanAnswer = cleanClientLLMText(data.answer);
    const formattedAnswer = renderMarkdownSafe(cleanAnswer);

    chatHistory.push({ role: "user", content: question });
    chatHistory.push({ role: "assistant", content: cleanAnswer });

    botMsg.querySelector(".msg-content").innerHTML = `
      <div class="msg-text-content">${formattedAnswer}</div>
      <div class="chat-copy-corner">
        <button type="button" class="btn-copy-chat" onclick="copyChatAnswer(this)" title="Copy Answer">
          <i data-feather="copy" style="width:12px; height:12px;"></i> Copy
        </button>
      </div>
    `;
    safeReplaceIcons();
    playBlipSound(580, 0.06);
    botMsg.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (err) {
    botMsg.querySelector(".msg-content").innerHTML = `<span style="color: var(--accent-rose);">Error retrieving answer: ${escapeHtml(err.message)}</span>`;
  } finally {
    input.disabled = false;
    if (sendBtn) sendBtn.disabled = false;
    input.placeholder = "Ask a follow-up question about this dossier...";
    input.focus();
  }
}

function copyChatAnswer(btn) {
  const card = btn.closest(".chat-msg.assistant");
  if (!card) return;
  const contentEl = card.querySelector(".msg-text-content");
  const text = contentEl ? contentEl.innerText.trim() : "";
  if (!text) return;

  navigator.clipboard.writeText(text).then(() => {
    const origHtml = btn.innerHTML;
    btn.innerHTML = `<i data-feather="check" style="width:12px; height:12px;"></i> Copied!`;
    safeReplaceIcons();
    playBlipSound(880, 0.06);
    showToast("Answer copied to clipboard", "success");
    setTimeout(() => {
      btn.innerHTML = origHtml;
      safeReplaceIcons();
    }, 2000);
  }).catch(() => showToast("Clipboard copy failed", "error"));
}

// ==========================================
// Source Content Inspector Modal
// ==========================================
async function inspectSourceContent(url, title) {
  const modal = document.getElementById("source-modal");
  const titleEl = document.getElementById("modal-source-title");
  const urlEl = document.getElementById("modal-source-url");
  const bodyEl = document.getElementById("modal-source-body");

  if (!modal) return;
  if (titleEl) titleEl.textContent = title || "Source Document";
  if (urlEl) urlEl.innerHTML = `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>`;
  if (bodyEl) bodyEl.textContent = "Loading extracted text...";

  modal.style.display = "flex";

  try {
    const res = await fetch(`/api/source-content?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    if (bodyEl) {
      const text = data.text || "No text content extracted for this source.";
      const wordCount = text.split(/\s+/).filter(Boolean).length;
      bodyEl.innerHTML = `
        <div class="modal-content-meta">
          <span><strong>Length:</strong> ${text.length.toLocaleString()} chars (${wordCount.toLocaleString()} words)</span>
          <button type="button" class="btn-secondary-sm" onclick="copyModalText()">
            <i data-feather="copy"></i> Copy Text
          </button>
        </div>
        <div class="modal-text-content" id="modal-text-content">${escapeHtml(text)}</div>
      `;
      safeReplaceIcons();
    }
  } catch (err) {
    if (bodyEl) bodyEl.textContent = `Error loading source content: ${err.message}`;
  }
}

function copyModalText() {
  const textEl = document.getElementById("modal-text-content");
  if (!textEl) return;
  navigator.clipboard?.writeText(textEl.textContent)
    .then(() => showToast("Source text copied!", "success"))
    .catch(() => showToast("Clipboard permission denied", "info"));
}

function closeSourceModal() {
  const modal = document.getElementById("source-modal");
  if (modal) modal.style.display = "none";
}

// ==========================================
// Export Actions (.docx, .pdf, .csv, .md, Rich-Text, HTML, JSON)
// ==========================================
function copyReportMarkdown() {
  if (!currentReportMarkdown) return;
  navigator.clipboard?.writeText(currentReportMarkdown)
    .then(() => { playBlipSound(880, 0.05); showToast("Markdown copied!", "success"); })
    .catch(() => showToast("Clipboard permission denied", "info"));
}

async function copyReportRichText() {
  const doc = document.getElementById("rendered-markdown-output");
  if (!doc || !currentReportMarkdown) {
    showToast("No active report to copy", "info");
    return;
  }
  try {
    const htmlBlob = new Blob([doc.innerHTML], { type: "text/html" });
    const textBlob = new Blob([currentReportMarkdown], { type: "text/plain" });
    if (navigator.clipboard && window.ClipboardItem && navigator.clipboard.write) {
      await navigator.clipboard.write([
        new ClipboardItem({ "text/html": htmlBlob, "text/plain": textBlob }),
      ]);
      playBlipSound(880, 0.05);
      showToast("Rich-Text copied for Word / Docs!", "success");
      return;
    }
  } catch (err) {
    console.debug("ClipboardItem fallback:", err);
  }
  copyReportMarkdown();
}

function downloadReportMarkdown() {
  if (!currentReportMarkdown) return;
  const blob = new Blob([currentReportMarkdown], { type: "text/markdown;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = currentReportFilename || "research_report.md";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("Downloaded Markdown", "success");
}

async function _exportBinaryReport(endpoint, ext, label) {
  if (!currentReportMarkdown) {
    showToast("No active dossier to export", "info");
    return;
  }
  showToast(`Generating formatted ${label}...`, "info");
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content: currentReportMarkdown,
        title: currentReportTitle || "Research Report",
        filename: currentReportFilename || "research_report",
      }),
    });
    if (!res.ok) throw new Error(`Export failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const base = (currentReportFilename || "research_report").replace(/\.md$/, "");
    a.download = `${base}.${ext}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    playBlipSound(880, 0.06);
    showToast(`Exported ${label} document!`, "success");
  } catch (err) {
    showToast(`${label} export failed: ${err.message}`, "error");
  }
}

function downloadReportDocx() {
  return _exportBinaryReport("/api/export/docx", "docx", "Word (.docx)");
}

function downloadReportPdf() {
  return _exportBinaryReport("/api/export/pdf", "pdf", "PDF");
}

function downloadTablesCsv() {
  const doc = document.getElementById("rendered-markdown-output");
  if (!doc) return;
  const tables = doc.querySelectorAll("table");
  if (!tables.length) {
    showToast("No quantitative tables found in this dossier", "info");
    return;
  }

  const csvRows = [];
  tables.forEach((tbl, tIdx) => {
    if (tIdx > 0) csvRows.push("");
    tbl.querySelectorAll("tr").forEach((tr) => {
      const cells = Array.from(tr.querySelectorAll("th, td")).map((cell) => {
        const txt = (cell.innerText || "").replace(/\s+/g, " ").trim().replace(/"/g, '""');
        return `"${txt}"`;
      });
      if (cells.length) csvRows.push(cells.join(","));
    });
  });

  const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (currentReportFilename || "benchmarks").replace(/\.md$/, "") + "_tables.csv";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  playBlipSound(820, 0.05);
  showToast("Extracted tables to CSV!", "success");
}

function downloadReportByName(filename, event) {
  if (event) event.stopPropagation();
  fetch(`/api/reports/${encodeURIComponent(filename)}`)
    .then((r) => r.json())
    .then((data) => {
      const blob = new Blob([data.content || ""], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showToast(`Downloaded ${filename}`, "success");
    })
    .catch((err) => showToast(`Download failed: ${err.message}`, "error"));
}

function downloadReportHTML() {
  const doc = document.getElementById("rendered-markdown-output");
  if (!doc) return;
  const fullHtml = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>${escapeHtml(currentReportTitle || "Research Deliverable")}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.65; max-width: 880px; margin: 40px auto; padding: 24px; color: #0f172a; background: #ffffff; }
    h1, h2, h3 { color: #0f172a; }
    table { width: 100%; border-collapse: collapse; margin: 20px 0; }
    th, td { border: 1px solid #cbd5e1; padding: 10px 14px; text-align: left; }
    th { background: #f1f5f9; font-weight: 700; }
    blockquote { border-left: 4px solid #0284c7; margin: 0; padding-left: 16px; color: #334155; }
    code { background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-family: monospace; }
  </style>
</head>
<body>${doc.innerHTML}</body>
</html>`;

  const blob = new Blob([fullHtml], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (currentReportFilename || "report").replace(/\.md$/, ".html");
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("Exported HTML report", "success");
}

function downloadReportJSON() {
  if (!currentReportMarkdown) {
    showToast("No active report to export", "info");
    return;
  }
  const payload = {
    title: currentReportTitle || "Research Deliverable",
    filename: currentReportFilename,
    exported_at: new Date().toISOString(),
    depth: currentResearchDepth,
    model: document.getElementById("model-select")?.value || "llama3.2:3b",
    total_slides: currentSlides ? currentSlides.length : 0,
    total_sources: currentSources ? currentSources.length : 0,
    sources: currentSources || [],
    slides: (currentSlides || []).map((s) => ({
      index: s.index,
      tag: s.tag,
      headline: s.headline,
      content_snippet: s.htmlBody ? s.htmlBody.replace(/<[^>]+>/g, "").trim().slice(0, 300) : "",
    })),
    raw_markdown: currentReportMarkdown,
  };

  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = (currentReportFilename || "research_report").replace(/\.md$/, ".json");
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast("Exported JSON intelligence file", "success");
}

// ==========================================
// Vector Memory Explorer
// ==========================================
async function loadMemoryExplorer() {
  const grid = document.getElementById("memory-chunks-grid");
  if (!grid) return;
  grid.innerHTML = `<div class="empty-state"><p>Loading stored memory chunks...</p></div>`;

  try {
    const res = await fetch("/api/memory");
    const data = await res.json();
    renderMemoryChunks(data.results || []);
  } catch (err) {
    grid.innerHTML = `<div class="empty-state"><p>Error loading vector memory: ${escapeHtml(err.message)}</p></div>`;
  }
}

async function searchMemory() {
  const input = document.getElementById("memory-search-input");
  const query = input ? input.value.trim() : "";
  const grid = document.getElementById("memory-chunks-grid");
  if (!grid) return;

  grid.innerHTML = `<div class="empty-state"><p>Searching memory for '${escapeHtml(query)}'...</p></div>`;

  try {
    const res = await fetch(`/api/memory?q=${encodeURIComponent(query)}`);
    const data = await res.json();
    renderMemoryChunks(data.results || []);
  } catch (err) {
    grid.innerHTML = `<div class="empty-state"><p>Error searching vector memory</p></div>`;
  }
}

function renderMemoryChunks(chunks) {
  const grid = document.getElementById("memory-chunks-grid");
  if (!grid) return;

  if (chunks.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <i data-feather="inbox"></i>
        <p>No memory chunks found in local vector store.</p>
      </div>
    `;
    safeReplaceIcons();
    return;
  }

  grid.innerHTML = "";
  chunks.forEach((c) => {
    const meta = c.metadata || {};
    const source = meta.source || meta.title || "Local Memory";
    const dist = c.distance !== null && c.distance !== undefined ? (1 - c.distance).toFixed(2) : "1.0";

    const card = document.createElement("div");
    card.className = "memory-chunk-card";

    const header = document.createElement("div");
    header.className = "chunk-card-header";
    header.innerHTML = `
      <span class="chunk-source-tag" title="${escapeHtml(source)}">${escapeHtml(source)}</span>
      <div class="chunk-card-actions">
        <span class="dim-text" style="font-size: 0.72rem;">Score: ${dist}</span>
      </div>
    `;

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "btn-copy-chunk";
    copyBtn.title = "Copy Chunk Text";
    copyBtn.innerHTML = `<i data-feather="copy"></i>`;
    copyBtn.onclick = (e) => {
      e.stopPropagation();
      navigator.clipboard.writeText(c.text).then(() => showToast("Chunk copied!", "success"));
    };
    header.querySelector(".chunk-card-actions").appendChild(copyBtn);

    const body = document.createElement("div");
    body.className = "chunk-text-body";
    body.textContent = c.text;

    card.appendChild(header);
    card.appendChild(body);
    grid.appendChild(card);
  });
  safeReplaceIcons();
}

async function clearMemoryConfirm() {
  if (confirm("Are you sure you want to clear all stored vector memory? This cannot be undone.")) {
    try {
      const res = await fetch("/api/memory/clear", { method: "POST" });
      if (res.ok) {
        showToast("Vector memory cleared", "success");
        loadMemoryExplorer();
        fetchSystemStatus();
      }
    } catch (err) {
      showToast("Failed to clear memory", "error");
    }
  }
}

// ==========================================
// Past Reports & Knowledge Repository + Sidebar Feed
// ==========================================
async function loadReportsArchive() {
  const grid = document.getElementById("reports-archive-grid");
  if (grid && grid.children.length === 0) {
    grid.innerHTML = `<div class="empty-state"><p>Loading knowledge repository...</p></div>`;
  }

  try {
    const res = await fetch("/api/reports");
    allLoadedReports = await res.json();
    if (grid) renderReportsGrid(allLoadedReports);
    populateRepoQuickSelect(allLoadedReports);
    renderSidebarRecentDossiers(allLoadedReports);
  } catch (err) {
    if (grid) grid.innerHTML = `<div class="empty-state"><p>Error loading repository</p></div>`;
  }
}

function renderSidebarRecentDossiers(reports) {
  const listEl = document.getElementById("sidebar-recent-dossiers");
  if (!listEl) return;

  if (!reports || reports.length === 0) {
    listEl.innerHTML = `<div class="sidebar-empty-hint">No saved dossiers yet. Run your first query above.</div>`;
    return;
  }

  listEl.innerHTML = "";
  reports.slice(0, 12).forEach((rep) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `sidebar-dossier-item ${rep.filename === currentReportFilename ? "active" : ""}`;
    item.setAttribute("data-filename", rep.filename);
    item.onclick = () => selectRepositoryReport(rep.filename);
    const dateStr = rep.created_at ? rep.created_at.split(" ")[0] : "";
    const readInfo = rep.reading_time_min ? ` • ${rep.reading_time_min}m` : "";
    const starPrefix = rep.starred ? `<span class="sidebar-star-badge">★</span>` : "";
    item.innerHTML = `
      <span class="sidebar-dossier-title" title="${escapeHtml(rep.title)}">${starPrefix}${escapeHtml(rep.title)}</span>
      <span class="sidebar-dossier-date">${escapeHtml(dateStr + readInfo)}</span>
    `;
    listEl.appendChild(item);
  });
}

function populateRepoQuickSelect(reports) {
  const select = document.getElementById("repo-quick-select");
  if (!select) return;
  const currentVal = select.value;
  select.innerHTML = '<option value="">-- Open Saved Dossier --</option>';
  if (!reports || reports.length === 0) return;
  reports.forEach((rep) => {
    const opt = document.createElement("option");
    opt.value = rep.filename;
    const dateStr = rep.created_at ? rep.created_at.split(" ")[0] : "";
    const starTag = rep.starred ? "★ " : "";
    opt.textContent = `${starTag}${rep.title} (${dateStr})`;
    if (rep.filename === currentVal || rep.filename === currentReportFilename) opt.selected = true;
    select.appendChild(opt);
  });
}

function onRepoQuickSelect(filename) {
  if (!filename) {
    clearActiveDossier();
    return;
  }
  selectRepositoryReport(filename);
}

function clearActiveDossier() {
  const select = document.getElementById("repo-quick-select");
  if (select) select.value = "";
  const pill = document.getElementById("active-dossier-pill");
  if (pill) pill.style.display = "none";
  currentReportFilename = "";
  document.querySelectorAll(".sidebar-dossier-item").forEach((el) => el.classList.remove("active"));
  showToast("Dossier selection cleared", "info");
}

async function selectRepositoryReport(filename) {
  if (!filename) return;
  try {
    const res = await fetch("/api/repository/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: filename }),
    });
    if (!res.ok) throw new Error("Could not load dossier from repository");
    const data = await res.json();

    switchView("studio");
    currentReportMarkdown = data.content;
    currentReportFilename = data.filename;
    currentReportTitle = data.title;
    currentReportStarred = Boolean(data.starred);

    const select = document.getElementById("repo-quick-select");
    if (select) select.value = filename;

    const pill = document.getElementById("active-dossier-pill");
    const titleEl = document.getElementById("active-dossier-title");
    if (pill && titleEl) {
      pill.style.display = "inline-flex";
      titleEl.textContent = data.title;
    }

    renderReportStudio(data.content, data.filename, data.sources || [], Boolean(data.starred));
    playBlipSound(640, 0.05);
    showToast(`Loaded: ${data.title}`, "success");
    fetchSystemStatus();
  } catch (err) {
    showToast(`Failed to load dossier: ${err.message}`, "error");
  }
}

async function openPastReport(filename) {
  await selectRepositoryReport(filename);
}

function inspectReportRaw(filename) {
  const rep = (allLoadedReports || []).find((r) => r.filename === filename);
  if (!rep) return;
  const modal = document.getElementById("source-modal");
  const titleEl = document.getElementById("modal-source-title");
  const urlEl = document.getElementById("modal-source-url");
  const bodyEl = document.getElementById("modal-source-body");

  if (!modal) return;
  if (titleEl) titleEl.textContent = rep.title;
  if (urlEl) urlEl.textContent = `File: data/outputs/${filename}`;
  if (bodyEl) bodyEl.textContent = "Loading...";

  modal.style.display = "flex";

  fetch(`/api/reports/${encodeURIComponent(filename)}`)
    .then((r) => r.json())
    .then((data) => {
      if (bodyEl) {
        bodyEl.innerHTML = `
          <div class="modal-content-meta">
            <span><strong>Size:</strong> ${(data.size_bytes / 1024).toFixed(1)} KB</span>
            <button type="button" class="btn-card-select" onclick="closeSourceModal(); selectRepositoryReport('${escapeHtml(filename)}')">
              <i data-feather="play-circle"></i> Load into Studio
            </button>
          </div>
          <div class="modal-text-content" id="modal-text-content">${escapeHtml(data.content)}</div>
        `;
        safeReplaceIcons();
      }
    })
    .catch((err) => {
      if (bodyEl) bodyEl.textContent = "Error: " + err.message;
    });
}

let reportsFilterTimeout = null;
function filterReportsArchive(query) {
  clearTimeout(reportsFilterTimeout);
  reportsFilterTimeout = setTimeout(() => {
    const q = (query || "").toLowerCase().trim();
    if (!allLoadedReports) return;
    const filtered = allLoadedReports.filter((rep) => {
      return !q || rep.title.toLowerCase().includes(q) || (rep.preview && rep.preview.toLowerCase().includes(q));
    });
    renderReportsGrid(filtered);
  }, 120);
}

function filterReportsCategory(category) {
  document.querySelectorAll(".repo-tag-pill").forEach((pill) => {
    pill.classList.toggle("active", pill.getAttribute("data-filter") === category);
  });

  if (!allLoadedReports || allLoadedReports.length === 0) return;

  if (category === "all") {
    renderReportsGrid(allLoadedReports);
  } else if (category === "starred") {
    const filtered = allLoadedReports.filter((r) => Boolean(r.starred));
    renderReportsGrid(filtered);
  } else if (category === "recent") {
    renderReportsGrid(allLoadedReports.slice(0, 5));
  } else if (category === "comparative") {
    const filtered = allLoadedReports.filter((r) =>
      r.title.toLowerCase().includes("vs") ||
      r.title.toLowerCase().includes("benchmark") ||
      r.title.toLowerCase().includes("comparison")
    );
    renderReportsGrid(filtered.length ? filtered : allLoadedReports);
  } else if (category === "technical") {
    const filtered = allLoadedReports.filter((r) =>
      r.title.toLowerCase().includes("architecture") ||
      r.title.toLowerCase().includes("deepseek") ||
      r.title.toLowerCase().includes("technical") ||
      r.title.toLowerCase().includes("training")
    );
    renderReportsGrid(filtered.length ? filtered : allLoadedReports);
  }
}

function renderReportsGrid(reports) {
  const grid = document.getElementById("reports-archive-grid");
  if (!grid) return;

  if (reports.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <i data-feather="folder"></i>
        <p>No matching reports in the knowledge repository.</p>
      </div>
    `;
    safeReplaceIcons();
    return;
  }

  grid.innerHTML = "";
  reports.forEach((rep) => {
    const card = document.createElement("div");
    card.className = "report-archive-card";
    card.onclick = () => selectRepositoryReport(rep.filename);

    const isComp = rep.title.toLowerCase().includes("vs") || rep.title.toLowerCase().includes("benchmark");
    const isTech = rep.title.toLowerCase().includes("architecture") || rep.title.toLowerCase().includes("model");
    const tag = isComp ? "⚖️ Comparative" : isTech ? "🔬 Architectural" : "📑 Deep Research";
    const metaExtra = rep.reading_time_min ? ` • ${rep.reading_time_min} min read` : "";
    const starLabel = rep.starred ? "★" : "☆";

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="slide-tag">${tag}</span>
        <span class="report-file-size">${(rep.size_bytes / 1024).toFixed(1)} KB${metaExtra}</span>
      </div>
      <div class="report-archive-title">${escapeHtml(rep.title)}</div>
      <div class="report-archive-date"><i data-feather="calendar" style="width:12px; height:12px;"></i> ${escapeHtml(rep.created_at)}</div>
      <div class="report-archive-preview">${escapeHtml(cleanClientLLMText(rep.preview))}...</div>
      <div class="report-card-footer">
        <button type="button" class="btn-card-select" onclick="event.stopPropagation(); selectRepositoryReport('${escapeHtml(rep.filename)}')">
          <i data-feather="play-circle"></i> Open in Studio
        </button>
        <div class="report-card-actions">
          <button type="button" class="btn-card-icon ${rep.starred ? "starred" : ""}" onclick="toggleReportCardStar('${escapeHtml(rep.filename)}', event)" title="Bookmark Dossier">
            ${starLabel}
          </button>
          <button type="button" class="btn-card-icon" onclick="event.stopPropagation(); inspectReportRaw('${escapeHtml(rep.filename)}')" title="Preview Raw Content">
            <i data-feather="eye"></i>
          </button>
          <button type="button" class="btn-card-icon" onclick="downloadReportByName('${escapeHtml(rep.filename)}', event)" title="Download Markdown">
            <i data-feather="download"></i>
          </button>
          <button type="button" class="btn-card-icon delete" onclick="deleteReport('${escapeHtml(rep.filename)}', event)" title="Delete Report">
            <i data-feather="trash-2"></i>
          </button>
        </div>
      </div>
    `;
    grid.appendChild(card);
  });
  safeReplaceIcons();
}

async function deleteReport(filename, event) {
  if (event) event.stopPropagation();
  if (!confirm(`Permanently delete report '${filename}'?`)) return;

  try {
    const res = await fetch(`/api/reports/${encodeURIComponent(filename)}`, { method: "DELETE" });
    if (res.ok) {
      showToast(`Deleted ${filename}`, "success");
      if (filename === currentReportFilename) startNewResearchSession();
      loadReportsArchive();
      fetchSystemStatus();
    } else {
      showToast("Failed to delete report", "error");
    }
  } catch (err) {
    showToast(`Error deleting report: ${err.message}`, "error");
  }
}

// ==========================================
// Direct Tools Sandbox
// ==========================================
async function testDirectSearch() {
  const input = document.getElementById("direct-search-input");
  const query = input ? input.value.trim() : "";
  const output = document.getElementById("direct-search-output");
  if (!query || !output) return;

  output.textContent = `Searching multi-engine index for '${query}'...`;
  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query }),
    });
    const data = await res.json();
    const content = data.formatted || "No results found.";
    output.innerHTML = `
      <div style="display:flex; justify-content:space-between; margin-bottom:0.6rem;">
        <span class="dim-text">Results for: <strong>${escapeHtml(query)}</strong></span>
        <button type="button" class="btn-copy-chunk" onclick="copyToolOutput('direct-search-output')" title="Copy Results">
          <i data-feather="copy"></i> Copy Output
        </button>
      </div>
      <pre style="white-space:pre-wrap; font-family:var(--font-mono);">${escapeHtml(content)}</pre>
    `;
    safeReplaceIcons();
  } catch (err) {
    output.textContent = `Error: ${err.message}`;
  }
}

async function testDirectScrape() {
  const input = document.getElementById("direct-scrape-input");
  const url = input ? input.value.trim() : "";
  const output = document.getElementById("direct-scrape-output");
  if (!url || !output) return;

  output.textContent = `Fetching and scraping ${url}...`;
  try {
    const res = await fetch("/api/scrape", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: url }),
    });
    const data = await res.json();
    const fullText = `Title: ${data.title}\nStatus: ${data.status}\nLength: ${data.text ? data.text.length : 0} chars\n\n${data.text}`;
    output.innerHTML = `
      <div style="display:flex; justify-content:space-between; margin-bottom:0.6rem;">
        <span class="dim-text">Extracted: <strong>${escapeHtml(data.title)}</strong></span>
        <button type="button" class="btn-copy-chunk" onclick="copyToolOutput('direct-scrape-output')" title="Copy Scraped Content">
          <i data-feather="copy"></i> Copy Output
        </button>
      </div>
      <pre style="white-space:pre-wrap; font-family:var(--font-mono);">${escapeHtml(fullText)}</pre>
    `;
    safeReplaceIcons();
  } catch (err) {
    output.textContent = `Error: ${err.message}`;
  }
}

function copyToolOutput(elementId) {
  const el = document.getElementById(elementId);
  if (!el) return;
  const pre = el.querySelector("pre") || el;
  navigator.clipboard?.writeText(pre.textContent)
    .then(() => showToast("Output copied!", "success"))
    .catch(() => showToast("Clipboard permission denied", "info"));
}

function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  while (container.children.length >= 4) {
    container.firstElementChild.remove();
  }

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.innerHTML = `
    <i data-feather="${type === "success" ? "check-circle" : type === "error" ? "alert-circle" : "info"}"></i>
    <span>${escapeHtml(message)}</span>
  `;
  container.appendChild(toast);
  safeReplaceIcons();

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px)";
    setTimeout(() => toast.remove(), 250);
  }, 3500);
}

function escapeHtml(text) {
  if (!text) return "";
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
