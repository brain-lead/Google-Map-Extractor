const BASE = "";

async function req(method, path, body, isForm = false) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    if (isForm) {
      opts.body = body;
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(BASE + path, opts);
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res;
}

function appendFilters(p, filters) {
  const f = filters || {};
  if (f.q) p.set("q", f.q);
  if (f.min_rating !== "" && f.min_rating != null) p.set("min_rating", f.min_rating);
  if (f.min_reviews !== "" && f.min_reviews != null) p.set("min_reviews", f.min_reviews);
  if (f.min_ai_score !== "" && f.min_ai_score != null) p.set("min_ai_score", f.min_ai_score);
  if (f.affordability) p.set("affordability", f.affordability);
  if (f.ai_verdict) p.set("ai_verdict", f.ai_verdict);
  if (f.removed_only) p.set("removed_only", "true");
  if (f.location && f.location.length) f.location.forEach((l) => p.append("location", l));
  if (f.country && f.country.length) f.country.forEach((c) => p.append("country", c));
  if (f.has_email) p.set("has_email", "true");
  if (f.has_social) p.set("has_social", "true");
  if (f.has_website) p.set("has_website", "true");
  if (f.has_phone) p.set("has_phone", "true");
  if (f.has_hours) p.set("has_hours", "true");
  if (f.has_menu) p.set("has_menu", "true");
  if (f.has_reviews) p.set("has_reviews", "true");
  if (f.hot_only) p.set("hot_only", "true");
  if (f.sort && f.sort !== "default") p.set("sort", f.sort);
}

export const api = {
  health: () => req("GET", "/api/health"),
  cookiesStatus: () => req("GET", "/api/cookies"),
  saveCookies: (cookies) => req("POST", "/api/cookies", { cookies }),
  testCookies: (cookies) => req("POST", "/api/cookies/test", { cookies }),
  importCapture: () => req("POST", "/api/cookies/import-capture", {}),
  autoGenerate: () => req("POST", "/api/cookies/auto-generate", {}),
  clearCookies: () => req("DELETE", "/api/cookies"),
  listProxies: () => req("GET", "/api/proxies"),
  addProxies: (text) => req("POST", "/api/proxies", { proxies: text }),
  testProxies: () => req("POST", "/api/proxies/test"),
  clearProxies: () => req("DELETE", "/api/proxies"),
  uploadProxies: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return req("POST", "/api/proxies/upload", fd, true);
  },
  getSettings: () => req("GET", "/api/settings"),
  saveSettings: (s) => req("POST", "/api/settings", s),
  createJob: (p) => req("POST", "/api/jobs", p),
  listJobs: (limit, offset) => {
    const p = new URLSearchParams();
    if (limit != null) p.set("limit", limit);
    if (offset != null) p.set("offset", offset);
    const qs = p.toString();
    return req("GET", `/api/jobs${qs ? `?${qs}` : ""}`);
  },
  categories: (q) => req("GET", "/api/categories?q=" + encodeURIComponent(q || "")),
  countries: () => req("GET", "/api/countries"),
  scoringMeta: () => req("GET", "/api/scoring"),
  rescoreJob: (id) => req("POST", `/api/jobs/${id}/rescore`),
  rescoreAll: () => req("POST", "/api/rescore-all"),
  getJob: (id) => req("GET", `/api/jobs/${id}`),
  deleteJob: (id) => req("DELETE", `/api/jobs/${id}`),
  cancelJob: (id) => req("POST", `/api/jobs/${id}/cancel`),
  results: (id, filters, limit, offset) => {
    const p = new URLSearchParams();
    appendFilters(p, filters);
    if (limit != null) p.set("limit", limit);
    if (offset != null) p.set("offset", offset);
    const qs = p.toString();
    return req("GET", `/api/jobs/${id}/results` + (qs ? `?${qs}` : ""));
  },
  facets: (id) => req("GET", `/api/jobs/${id}/facets`),
  compareJobs: (jobId, baseline) =>
    req("GET", `/api/jobs/compare?job=${encodeURIComponent(jobId)}` +
      (baseline ? `&baseline=${encodeURIComponent(baseline)}` : "")),
  jobReport: (id) => req("GET", `/api/jobs/${id}/report`),
  exportUrl: (id, format, filters, crm) => {
    const p = new URLSearchParams();
    p.set("format", format);
    if (crm) p.set("crm", crm);
    appendFilters(p, filters);
    return `/api/jobs/${id}/export?${p.toString()}`;
  },
  exportSheets: (id, filters) => {
    const url = api.exportUrl(id, "sheets", filters);
    return req("GET", url);
  },
  uploadCreds: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return req("POST", "/api/settings/google_creds", fd, true);
  },
  authStatus: () => req("GET", "/api/auth/status"),
  activate: (key) => req("POST", "/api/auth/activate", { key }),
  resetBinding: (key = "") => req("POST", "/api/auth/reset-binding", { key }),
  useFreeTier: () => req("POST", "/api/auth/free-tier", {}),
  notifications: () => req("GET", "/api/auth/notifications"),
  branding: () => req("GET", "/api/auth/branding"),

  // AI Engine, Models, Offers, Missions & Inline Commands
  aiConfig: () => req("GET", "/api/ai/config"),
  saveAiConfig: (p) => req("PUT", "/api/ai/config", p),
  aiModels: (p) => req("POST", "/api/ai/models", p || {}),
  testAiConnection: (p) => req("POST", "/api/ai/test", p || {}),
  aiModes: () => req("GET", "/api/ai/modes"),
  listOffers: () => req("GET", "/api/ai/offers"),
  saveOffer: (p) => req("POST", "/api/ai/offers", p),
  deleteOffer: (id) => req("DELETE", `/api/ai/offers/${id}`),
  listMissions: (limit = 40) => req("GET", `/api/ai/missions?limit=${limit}`),
  createMission: (p) => req("POST", "/api/ai/missions", p),
  getMission: (id) => req("GET", `/api/ai/missions/${id}`),
  aiMissionLog: (id) => req("GET", `/api/ai/missions/${id}/log`),
  aiLogs: (limit = 200) => req("GET", `/api/ai/logs?limit=${limit}`),
  sendMissionMessage: (id, p) => req("POST", `/api/ai/missions/${id}/message`, p),
  cancelMission: (id) => req("POST", `/api/ai/missions/${id}/cancel`, {}),
  deleteMission: (id) => req("DELETE", `/api/ai/missions/${id}`),
  aiAnalyzeJob: (id, p) => req("POST", `/api/jobs/${id}/ai-analyze`, p || {}),
  aiCommandJob: (id, p) => req("POST", `/api/jobs/${id}/ai-command`, p),
  aiMarketBrief: (id, p) => req("POST", `/api/jobs/${id}/ai-market-brief`, p || {}),
  removeLeads: (id, cids, reason) => req("POST", `/api/jobs/${id}/remove-leads`, { cids, reason }),
  restoreRemoved: (id, cids) => req("POST", `/api/jobs/${id}/restore-removed`, { cids: cids || null }),

  // Saved Shortlists
  listShortlists: () => req("GET", "/api/lists"),
  createShortlist: (p) => req("POST", "/api/lists", p),
  getShortlist: (id) => req("GET", `/api/lists/${id}`),
  deleteShortlist: (id) => req("DELETE", `/api/lists/${id}`),
  addShortlistItems: (id, p) => req("POST", `/api/lists/${id}/items`, p),
  updateShortlistItem: (listId, itemId, p) => req("PATCH", `/api/lists/${listId}/items/${itemId}`, p),
  deleteShortlistItem: (listId, itemId) => req("DELETE", `/api/lists/${listId}/items/${itemId}`),
  shortlistExportUrl: (listId, format = "csv", crm) => {
    const p = new URLSearchParams({ format });
    if (crm) p.set("crm", crm);
    return `/api/lists/${listId}/export?${p.toString()}`;
  },
};

export function connectWS(jobId, onMessage) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/jobs/${jobId}/ws`);
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch {}
  };
  ws.onclose = () => onMessage({ type: "ws_close" });
  return ws;
}

export function connectMissionWS(missionId, onMessage) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/api/ai/missions/${missionId}/ws`);
  ws.onmessage = (e) => {
    try {
      onMessage(JSON.parse(e.data));
    } catch {}
  };
  ws.onclose = () => onMessage({ type: "ws_close" });
  return ws;
}
