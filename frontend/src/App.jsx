import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, connectWS } from "./api.js";
import AreaMap from "./AreaMap.jsx";
import { GmeLogo, Icons, StatusBadge, ToastList } from "./components/ui.jsx";
import { ActivateScreen, AgreementModal, LegalModal, SplashScreen } from "./components/Modals.jsx";
import ResultsView from "./components/ResultsView.jsx";
import CopilotView from "./components/CopilotView.jsx";

const NAV = [
  { id: "dashboard", label: "Extract", Icon: Icons.Search },
  { id: "copilot", label: "AI Copilot", Icon: Icons.Sparkles },
  { id: "history", label: "History", Icon: Icons.History },
  { id: "proxies", label: "Proxies", Icon: Icons.Globe },
  { id: "settings", label: "Settings", Icon: Icons.Sliders },
];

const ACTIVE_JOB_KEY = "mge.activeJobId";
function saveActiveJob(id, running) {
  try {
    localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify({ id, running }));
  } catch {}
}
function loadActiveJob() {
  try {
    return JSON.parse(localStorage.getItem(ACTIVE_JOB_KEY));
  } catch {
    return null;
  }
}

const TERMS_TEXT = `TERMS & AGREEMENT

1. GRANT OF LICENSE. Subject to your purchase of a valid license key and acceptance of this Agreement, the Provider grants you a non-exclusive, non-transferable, revocable license to use the Software.

2. RESTRICTIONS. You shall not: (a) reverse-engineer, decompile, or circumvent license protections; (b) resell or redistribute the Software without written permission; (c) use the Software to violate any law or third-party right; (d) share your license key beyond the permitted activation count.

3. FREE / TRIAL TIER. The free tier is provided for evaluation only and is limited (e.g., results per search and area-scan restrictions). Continued or commercial use requires a paid license obtained from the official channels (@brainleadbot / @BrainLead).

4. DATA & PRIVACY. You are responsible for the lawful handling of any personal data you process. The Software transmits a hardware identifier (HWID) and username to the license server solely for activation and anti-piracy. No extracted business data is sent to the Provider.

5. DISCLAIMER OF WARRANTY. The Software is provided "AS IS" without warranty of any kind.

6. LIMITATION OF LIABILITY. In no event shall the Provider be liable for indirect, incidental, or consequential damages, or for any use of the Software that violates applicable law. The user assumes all risk and full responsibility.

7. ACCOUNTABILITY. By using the Software you identify yourself (username/Telegram) and accept personal accountability for your actions. The Provider is not a party to, and accepts no liability for, any unlawful act performed with this tool.

8. MODIFICATION. The Provider may update these terms; continued use constitutes acceptance of the updated terms.`;

const DISCLAIMER_TEXT = `DISCLAIMER — READ CAREFULLY

1. ACCEPTANCE OF RISK. GME — Google Map Extractor ("the Software") is provided "AS IS" and "AS AVAILABLE" without warranties of any kind, express or implied.

2. LAWFUL USE ONLY. You agree to use the Software solely for lawful purposes and in compliance with all applicable local, national, and international laws, including but not limited to data-protection and privacy regulations (e.g., GDPR, CCPA), anti-spam laws, and the terms of service of any third-party platform.

3. USER RESPONSIBILITY. You, and you alone, are solely responsible for any data you collect, store, process, or transmit using the Software, and for the purposes for which you use it. The developer does not collect, control, or monitor your extracted data.

4. NO LIABILITY FOR MISUSE. The developer, contributors, and affiliates (collectively, "the Provider") are NOT responsible, and shall NOT be held liable, for any unlawful, abusive, harassing, fraudulent, discriminatory, or otherwise illegal use of the Software by any user. Any such use is a violation of these terms and may result in license revocation.

5. INDEMNIFICATION. You agree to indemnify and hold harmless the Provider from any claims, damages, losses, liabilities, fines, or expenses (including legal fees) arising out of your use of the Software or your violation of any law or third-party right.

6. NO ENDORSEMENT. The Software is a neutral technical tool. Its availability does not constitute encouragement or endorsement of any particular use.

7. TERMINATION. The Provider may revoke any license, without refund, if the Software is used in a manner the Provider reasonably believes to be unlawful or harmful.

If you do not agree with any part of this Disclaimer, you must not use the Software.`;

const SEED_CATEGORIES = [
  "plumber", "electrician", "hvac", "roofer", "contractor", "handyman",
  "lawyer", "attorney", "law firm", "accountant", "real estate", "realtor",
  "dentist", "doctor", "clinic", "veterinarian", "pharmacy", "chiropractor",
  "restaurant", "cafe", "coffee", "bar", "bakery", "pizzeria", "bistro",
  "salon", "spa", "barber", "hair salon", "nail salon", "gym", "fitness",
  "yoga studio", "photographer", "wedding planner", "event planner",
  "cleaning service", "maid service", "landscaping", "auto repair",
  "mechanic", "car dealer", "insurance agency", "mortgage broker",
  "travel agency", "marketing agency", "web design", "consultant",
  "boutique", "jewelry", "florist", "pet store", "daycare", "tutor",
];

export default function App() {
  const [view, setView] = useState("dashboard");
  const [copilotJobId, setCopilotJobId] = useState("");
  const [settings, setSettings] = useState({ default_proxy: "", gl: "us", hl: "en", threads: 2, max_results: 100 });
  const [auth, setAuth] = useState(null);
  const [branding, setBranding] = useState(null);
  const [showActivate, setShowActivate] = useState(false);
  const [showTerms, setShowTerms] = useState(false);
  const [showDisclaimer, setShowDisclaimer] = useState(false);
  const [toasts, setToasts] = useState([]);
  const [notif, setNotif] = useState(null);
  const [agreed, setAgreed] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem("brainlead.agreed") || "null");
    } catch {
      return null;
    }
  });

  const notify = useCallback((message, type = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-3), { id, message, type }]);
    setTimeout(() => {
      setToasts((t) => t.filter((x) => x.id !== id));
    }, 3200);
  }, []);

  useEffect(() => {
    api.getSettings().then(setSettings).catch(() => {});
    api.branding().then(setBranding).catch(() => {});
    api.notifications().then((d) => setNotif(d?.notification || null)).catch(() => {});
    api
      .authStatus()
      .then(setAuth)
      .catch(() => setAuth({ status: "unreachable", message: "Auth service error" }));
  }, []);

  const refreshAuth = () =>
    api
      .authStatus()
      .then(setAuth)
      .catch(() => setAuth({ status: "unreachable", message: "Auth service error" }));

  if (auth === null) return <SplashScreen />;
  if (auth.status !== "authorized") {
    return <ActivateScreen auth={auth} branding={branding} onActivated={refreshAuth} />;
  }

  return (
    <div className="apple-canvas flex h-screen flex-col text-zinc-100">
      <ToastList toasts={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          view={view}
          setView={setView}
          plan={auth.plan}
          onOpenActivate={() => setShowActivate(true)}
        />
        <main className="flex-1 overflow-y-auto">
          {notif?.message && (
            <div className="mx-6 mt-5 flex items-center justify-between gap-3 rounded-2xl border border-[#0A84FF]/30 bg-[#0A84FF]/10 px-4 py-2.5 text-xs text-zinc-200">
              <div className="flex min-w-0 items-center gap-2.5">
                <Icons.Bell className="h-3.5 w-3.5 shrink-0 text-[#409CFF]" />
                <span className="truncate">{notif.message}</span>
                {notif.url && (
                  <a href={notif.url} target="_blank" rel="noreferrer" className="shrink-0 font-medium text-[#409CFF] hover:underline">
                    Learn more →
                  </a>
                )}
              </div>
              <button onClick={() => setNotif(null)} className="shrink-0 text-zinc-400 hover:text-white" aria-label="Dismiss notice">
                <Icons.X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          {view === "dashboard" && (
            <Dashboard
              settings={settings}
              setView={setView}
              notify={notify}
              onRequireActivation={() => setShowActivate(true)}
            />
          )}
          {view === "copilot" && (
            <CopilotView
              notify={notify}
              onOpenSettings={() => setView("settings")}
              initialJobId={copilotJobId}
            />
          )}
          {view === "history" && (
            <History
              setView={setView}
              notify={notify}
              onOpenCopilot={(jid) => {
                setCopilotJobId(jid);
                setView("copilot");
              }}
            />
          )}
          {view === "proxies" && <Proxies notify={notify} />}
          {view === "settings" && <Settings settings={settings} setSettings={setSettings} notify={notify} />}
        </main>
      </div>
      <AppFooter
        branding={branding}
        agreed={agreed}
        onShowTerms={() => setShowTerms(true)}
        onShowDisclaimer={() => setShowDisclaimer(true)}
      />
      {!agreed && (
        <AgreementModal
          onAccept={() => {
            const rec = { ts: Date.now() };
            try {
              localStorage.setItem("brainlead.agreed", JSON.stringify(rec));
            } catch {}
            setAgreed(rec);
          }}
          onShowTerms={() => setShowTerms(true)}
          onShowDisclaimer={() => setShowDisclaimer(true)}
        />
      )}
      {showTerms && <LegalModal title="Terms & Agreement" body={TERMS_TEXT} onClose={() => setShowTerms(false)} />}
      {showDisclaimer && <LegalModal title="Disclaimer" body={DISCLAIMER_TEXT} onClose={() => setShowDisclaimer(false)} />}
      {showActivate && auth?.limited && (
        <ActivateScreen
          auth={auth}
          branding={branding}
          onActivated={() => {
            setShowActivate(false);
            refreshAuth();
            notify("License activated — full access unlocked", "success");
          }}
          onClose={() => setShowActivate(false)}
        />
      )}
    </div>
  );
}

function Sidebar({ view, setView, plan, onOpenActivate }) {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("gme.navCollapsed") === "1";
    } catch {
      return false;
    }
  });

  function toggleNav() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem("gme.navCollapsed", next ? "1" : "0");
      } catch {}
      return next;
    });
  }

  return (
    <aside
      className={`flex shrink-0 flex-col border-r border-white/[0.07] bg-zinc-950/60 backdrop-blur-2xl transition-all duration-200 ${
        collapsed ? "w-[72px] p-3" : "w-64 p-4"
      }`}
    >
      <div className={`mb-5 ${collapsed ? "flex flex-col items-center gap-2" : "px-1.5"}`}>
        <div className={`flex items-center ${collapsed ? "flex-col gap-2" : "justify-between gap-2"}`}>
          <div className="flex min-w-0 items-center gap-3">
            <GmeLogo size={collapsed ? 34 : 38} />
            {!collapsed && (
              <div className="min-w-0">
                <div className="truncate text-sm font-bold tracking-tight text-zinc-100">GME</div>
                <div className="truncate text-[11px] text-zinc-400">Google Map Extractor</div>
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={toggleNav}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-white/[0.08] hover:text-zinc-100"
          >
            {collapsed ? <Icons.ChevronRight className="h-4 w-4" /> : <Icons.ChevronLeft className="h-4 w-4" />}
          </button>
        </div>

        {!collapsed && plan === "free" && (
          <button
            onClick={onOpenActivate}
            title="Activate or upgrade your license"
            className="mt-3 flex w-full items-center justify-between rounded-xl border border-[#FF9F0A]/30 bg-[#FF9F0A]/12 px-3 py-2 text-[11px] font-medium text-[#FFB340] transition hover:bg-[#FF9F0A]/20 active:scale-[0.98]"
          >
            <span>Free · 50 cap</span>
            <span className="font-semibold text-white">Activate →</span>
          </button>
        )}
        {!collapsed && plan === "licensed" && (
          <div className="mt-3 flex items-center gap-2 rounded-xl border border-[#30D158]/25 bg-[#30D158]/10 px-3 py-1.5 text-[11px] font-medium text-[#30D158]">
            <span className="h-1.5 w-1.5 rounded-full bg-[#30D158]" />
            Licensed · Full Version
          </div>
        )}
      </div>

      <nav className="flex flex-col gap-1">
        {NAV.map(({ id, label, Icon }) => {
          const active = view === id;
          return (
            <button
              key={id}
              onClick={() => setView(id)}
              title={label}
              className={`flex items-center rounded-xl py-2.5 text-sm font-medium transition-all duration-200 ease-spring ${
                collapsed ? "justify-center px-0" : "gap-3 px-3 text-left"
              } ${
                active
                  ? "bg-[#0A84FF] text-white shadow-[0_4px_16px_rgba(10,132,255,0.35),inset_0_1px_0_rgba(255,255,255,0.2)]"
                  : "text-zinc-400 hover:bg-white/[0.06] hover:text-zinc-100"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span>{label}</span>}
            </button>
          );
        })}
      </nav>
    </aside>
  );
}

/* ----------------------------- Dashboard ----------------------------- */
function Dashboard({ settings, setView, notify, onRequireActivation }) {
  const [form, setForm] = useState({
    query: "",
    location: "",
    max_results: 100,
    area_scan: false,
    country: "US",
    lat: "",
    lng: "",
    radius_km: 5,
    polygon: [],
    area_points: 400,
    threads: 2,
  });
  const [proxyInfo, setProxyInfo] = useState({ total: 0, working: 0 });
  const [countries, setCountries] = useState([]);
  const [countryMap, setCountryMap] = useState({});
  const countryTouchedRef = useRef(false);

  useEffect(() => {
    api
      .listProxies()
      .then((p) => setProxyInfo({ total: p.length, working: p.filter((x) => x.status === "working").length }))
      .catch(() => {});
  }, []);

  useEffect(() => {
    api
      .countries()
      .then((d) => {
        const list = d.countries || [];
        setCountries(list);
        const m = {};
        list.forEach((c) => {
          m[c.code] = c;
        });
        setCountryMap(m);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    setForm((f) => {
      const next = { ...f };
      if (!countryTouchedRef.current && settings?.gl) {
        next.country = settings.gl.toUpperCase();
      }
      if (settings?.threads) next.threads = settings.threads;
      if (settings?.max_results) next.max_results = settings.max_results;
      return next;
    });
  }, [settings.gl, settings.threads, settings.max_results]);

  const [catSuggestions, setCatSuggestions] = useState(SEED_CATEGORIES);
  useEffect(() => {
    const t = setTimeout(() => {
      const q = form.query.trim();
      if (!q || q.includes(",")) {
        setCatSuggestions(SEED_CATEGORIES);
        return;
      }
      api
        .categories(q)
        .then((d) => {
          const merged = Array.from(
            new Set([
              ...(d.categories || []),
              ...SEED_CATEGORIES.filter((c) => c.toLowerCase().includes(q.toLowerCase())),
            ])
          );
          setCatSuggestions(merged.slice(0, 25));
        })
        .catch(() => setCatSuggestions(SEED_CATEGORIES));
    }, 250);
    return () => clearTimeout(t);
  }, [form.query]);

  const [jobId, setJobId] = useState(null);
  const [job, setJob] = useState(null);
  const [log, setLog] = useState([]);
  const [running, setRunning] = useState(false);
  const [refreshSignal, setRefreshSignal] = useState(0);
  const [searchProg, setSearchProg] = useState({ done: 0, total: 0, found: 0 });
  const [tiles, setTiles] = useState(null);
  const wsRef = useRef(null);
  const lastRefreshRef = useRef(0);
  const refreshTimerRef = useRef(null);

  function set(k, v) {
    setForm((f) => ({ ...f, [k]: v }));
  }

  const scheduleResultsRefresh = useCallback((immediate = false) => {
    const now = Date.now();
    if (immediate || now - lastRefreshRef.current >= 1200) {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
      lastRefreshRef.current = now;
      setRefreshSignal((s) => s + 1);
      return;
    }
    if (!refreshTimerRef.current) {
      refreshTimerRef.current = setTimeout(() => {
        refreshTimerRef.current = null;
        lastRefreshRef.current = Date.now();
        setRefreshSignal((s) => s + 1);
      }, 1200 - (now - lastRefreshRef.current));
    }
  }, []);

  async function refreshJob(id) {
    try {
      const j = await api.getJob(id);
      if (j && !j.error) setJob(j);
      return j;
    } catch {
      return null;
    }
  }

  const connect = useCallback(
    (id) => {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {}
      }
      wsRef.current = connectWS(id, (msg) => {
        if (msg.type !== "ws_close") {
          setLog((l) => [...l.slice(-199), msg]);
        }
        if (msg.type === "tiles") setTiles(msg);
        if (msg.type === "progress") scheduleResultsRefresh(false);
        if (msg.type === "search") {
          setSearchProg((p) => ({
            done: msg.queries_done ?? p.done,
            total: msg.queries_total ?? p.total,
            found: p.found + (msg.found || 0),
          }));
        }
        if (msg.type === "done" || msg.type === "error") {
          setRunning(false);
          saveActiveJob(id, false);
          refreshJob(id);
          scheduleResultsRefresh(true);
        }
      });
    },
    [scheduleResultsRefresh]
  );

  useEffect(() => {
    return () => {
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {}
      }
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  async function start() {
    if (!form.query.trim()) return;
    if (form.area_scan && (!form.polygon || form.polygon.length < 3) && (!form.lat || !form.lng)) {
      notify("Draw an area on the map (or enter center Lat/Lng) first", "warning");
      return;
    }
    setLog([]);
    setRefreshSignal(0);
    setSearchProg({ done: 0, total: 0, found: 0 });
    setTiles(null);

    const sel = countryMap[form.country];
    const payload = {
      ...form,
      max_results: form.max_results ?? settings.max_results ?? 100,
      threads: form.threads ?? settings.threads ?? 2,
      country: form.country,
      gl: sel ? sel.gl : settings.gl || "us",
      hl: sel ? sel.hl : settings.hl || "en",
      proxy: settings.default_proxy || "",
    };

    try {
      const res = await api.createJob(payload);
      if (res?.error === "activation_required") {
        notify(res.message || "Activation required", "warning");
        onRequireActivation();
        return;
      }
      if (!res?.job_id) {
        notify(res?.error || "Failed to start extraction", "error");
        return;
      }
      setJobId(res.job_id);
      setRunning(true);
      saveActiveJob(res.job_id, true);
      connect(res.job_id);
      refreshJob(res.job_id);
    } catch (e) {
      notify("Could not create extraction job: " + (e?.message || e), "error");
    }
  }

  async function stop() {
    if (jobId) {
      await api.cancelJob(jobId);
      saveActiveJob(jobId, false);
      notify("Stopping extraction…", "warning");
    }
    setRunning(false);
  }

  useEffect(() => {
    const saved = loadActiveJob();
    if (!saved || !saved.id) return;
    let active = true;
    setJobId(saved.id);
    refreshJob(saved.id).then((j) => {
      if (!active || !j) return;
      const isLive = j.status === "pending" || j.status === "running" || j.status === "cancelling";
      if (isLive) {
        setRunning(true);
        connect(saved.id);
      } else {
        setRunning(false);
        saveActiveJob(saved.id, false);
      }
    });
    return () => {
      active = false;
    };
  }, [connect]);

  const progress = job && job.total ? Math.round((job.scraped / job.total) * 100) : 0;

  return (
    <div className="animate-view-enter space-y-6 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Header title="New Extraction" subtitle="Discover Google Maps businesses, crawl websites, and score leads automatically" />
        <div className="segmented">
          <button
            type="button"
            onClick={() => set("area_scan", false)}
            className={`segmented-item ${!form.area_scan ? "bg-white/[0.14] text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200"}`}
          >
            Keyword &amp; City
          </button>
          <button
            type="button"
            onClick={() => set("area_scan", true)}
            className={`segmented-item ${form.area_scan ? "bg-white/[0.14] text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200"}`}
          >
            Area Map Scan
          </button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Search form */}
        <div className="card space-y-4 lg:col-span-2">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Keyword / Category</label>
              <input
                className="input"
                placeholder="e.g. plumber, electrician, HVAC"
                value={form.query}
                onChange={(e) => set("query", e.target.value)}
                list="category-suggestions"
                autoComplete="off"
              />
              <datalist id="category-suggestions">
                {catSuggestions.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
              <p className="mt-1 text-[11px] text-zinc-500">Comma-separated for multiple categories.</p>
            </div>
            <div>
              <label className="label">Location</label>
              <input
                className="input"
                placeholder={form.area_scan ? "Optional (area polygon sets location)" : "e.g. New York, Toronto"}
                disabled={form.area_scan}
                value={form.location}
                onChange={(e) => set("location", e.target.value)}
              />
              <p className="mt-1 text-[11px] text-zinc-500">Comma-separated cities for multi-city batch scans.</p>
            </div>
            <div>
              <label className="label">Market Country</label>
              <select
                className="input"
                value={form.country}
                disabled={form.area_scan}
                onChange={(e) => {
                  countryTouchedRef.current = true;
                  set("country", e.target.value);
                }}
                title={
                  form.area_scan
                    ? "For area scans the country is detected automatically from the drawn area"
                    : "Pick the country/market to search in"
                }
              >
                {countries.length === 0 && <option value="US">United States</option>}
                {countries.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[11px] text-zinc-500">
                {form.area_scan ? "Auto-detected from drawn map area." : "Sets Google region & language automatically."}
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Threads (1–16)</label>
                <input
                  className="input tabular-nums"
                  type="number"
                  min="1"
                  max="16"
                  value={form.threads}
                  onChange={(e) => set("threads", Math.max(1, Math.min(16, +e.target.value || 1)))}
                />
              </div>
              <div>
                <label className="label">Max / Search</label>
                <input
                  className="input tabular-nums"
                  type="number"
                  min="10"
                  max="1000"
                  value={form.max_results}
                  onChange={(e) => set("max_results", Math.max(10, Math.min(1000, +e.target.value || 100)))}
                />
              </div>
            </div>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.025] px-3.5 py-2.5 text-xs">
            <div className="flex items-center gap-2 text-zinc-300">
              <Icons.Globe className="h-4 w-4 text-[#0A84FF]" />
              <span>
                Proxy pool:{" "}
                <b className={proxyInfo.working > 0 ? "text-[#30D158]" : "text-zinc-400"}>
                  {proxyInfo.working > 0 ? `${proxyInfo.working} working` : settings.default_proxy ? "Using default proxy" : "Direct IP"}
                </b>
                {proxyInfo.total > proxyInfo.working ? ` (${proxyInfo.total - proxyInfo.working} dead)` : ""}
              </span>
            </div>
            <button type="button" className="text-xs font-medium text-[#409CFF] hover:underline" onClick={() => setView("proxies")}>
              Manage Proxies →
            </button>
          </div>

          {form.area_scan && (
            <div className="animate-view-enter space-y-3 rounded-2xl border border-white/[0.07] bg-white/[0.02] p-4">
              <AreaMap
                center={[40.7128, -74.006]}
                initialPolygon={form.polygon}
                onChange={(p) => set("polygon", p)}
                onCenter={(lat, lng) => {
                  set("lat", lat.toFixed(5));
                  set("lng", lng.toFixed(5));
                }}
                areaPoints={form.area_points}
              />
              <div className="grid gap-3 pt-1 md:grid-cols-4">
                <div>
                  <label className="label">Center Lat</label>
                  <input className="input tabular-nums" value={form.lat} onChange={(e) => set("lat", e.target.value)} placeholder="40.7128" />
                </div>
                <div>
                  <label className="label">Center Lng</label>
                  <input className="input tabular-nums" value={form.lng} onChange={(e) => set("lng", e.target.value)} placeholder="-74.0060" />
                </div>
                <div>
                  <label className="label">Radius (km)</label>
                  <input className="input tabular-nums" type="number" min="1" value={form.radius_km} onChange={(e) => set("radius_km", +e.target.value)} />
                </div>
                <div>
                  <label className="label">Max tiles</label>
                  <input className="input tabular-nums" type="number" min="1" value={form.area_points} onChange={(e) => set("area_points", +e.target.value)} />
                </div>
              </div>
              <p className="text-[11px] text-zinc-500">
                Draw a polygon above or specify center + radius. Tiles are spaced ~1.2 km apart up to the max tile cap.
              </p>
            </div>
          )}

          <div className="flex items-center gap-3 pt-1">
            {!running ? (
              <button className="btn-primary px-5 py-2.5" onClick={start} disabled={!form.query.trim()}>
                <Icons.Play className="h-3.5 w-3.5" />
                Start Extraction
              </button>
            ) : (
              <button className="btn-danger px-5 py-2.5" onClick={stop}>
                <Icons.Square className="h-3.5 w-3.5" />
                Stop Extraction
              </button>
            )}
            {job && <StatusBadge status={job.status} />}
          </div>
        </div>

        {/* Live progress */}
        <div className="card flex flex-col space-y-3.5">
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold tracking-tight text-zinc-100">Live Progress</div>
            {running && <span className="text-[11px] font-medium text-[#64D2FF]">Streaming</span>}
          </div>

          {tiles && (
            <div className="space-y-2 rounded-2xl border border-white/[0.07] bg-white/[0.03] p-3">
              <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                <Step label="Geocoding" active={tiles.phase === "geocoding"} />
                <Step label="Searching" active={tiles.phase === "searching" || searchProg.total > 0} />
                <Step label="Enriching" active={!!(job && job.total > 0)} />
              </div>
              <div>
                <div className="flex justify-between text-[11px] text-zinc-400">
                  <span>
                    Districts: <b className="tabular-nums text-[#30D158]">{tiles.geocoded}/{tiles.total}</b>
                  </span>
                  <span className="tabular-nums text-[#FFB340]">{tiles.fallback} coords</span>
                </div>
                <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
                  <div className="h-full bg-[#30D158] transition-all duration-300" style={{ width: `${tiles.total ? (tiles.geocoded / tiles.total) * 100 : 0}%` }} />
                  <div className="h-full bg-[#FF9F0A] transition-all duration-300" style={{ width: `${tiles.total ? (tiles.fallback / tiles.total) * 100 : 0}%` }} />
                </div>
              </div>
              {(tiles.blocked || tiles.rate_limited) && (
                <div className="rounded-xl border border-[#FF453A]/30 bg-[#FF453A]/10 p-2 text-[11px] leading-relaxed text-[#FF8A80]">
                  Reverse geocoder {tiles.blocked ? "blocked (403)" : "rate-limited (429)"}. Remaining tiles fell back to coordinates.
                </div>
              )}
            </div>
          )}

          {job && (
            <div className="space-y-1.5">
              {job.total > 0 ? (
                <>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.07]">
                    <div
                      className={`h-full rounded-full bg-gradient-to-r from-[#0A84FF] to-[#30D158] transition-all duration-300 ${
                        running ? "shimmer-bar" : ""
                      }`}
                      style={{ width: `${progress}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-xs tabular-nums text-zinc-400">
                    <span>
                      {job.status === "completed" || job.status === "cancelled" || job.status === "interrupted"
                        ? `Done · ${job.scraped}/${job.total} businesses`
                        : `Enriching ${job.scraped}/${job.total}…`}
                    </span>
                    <span className="font-medium text-zinc-200">{progress}%</span>
                  </div>
                </>
              ) : searchProg.total > 0 ? (
                <>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-white/[0.07]">
                    <div
                      className="shimmer-bar h-full rounded-full bg-[#FF9F0A] transition-all duration-300"
                      style={{ width: `${searchProg.total ? Math.round((searchProg.done / searchProg.total) * 100) : 0}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-xs tabular-nums text-zinc-400">
                    <span>
                      Tiles {searchProg.done}/{searchProg.total} · {searchProg.found} hits
                    </span>
                    <span>{searchProg.total ? Math.round((searchProg.done / searchProg.total) * 100) : 0}%</span>
                  </div>
                </>
              ) : (
                <div className="text-xs text-zinc-500">Preparing extraction…</div>
              )}
            </div>
          )}

          <div className="h-44 flex-1 overflow-y-auto rounded-2xl border border-white/[0.06] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-zinc-400">
            {log.length === 0 && <div className="text-zinc-600">Waiting for activity…</div>}
            {log.map((m, i) => (
              <div key={i} className={m.type === "error" ? "text-[#FF6961]" : m.type === "warning" ? "text-[#FFB340]" : ""}>
                <span className="text-zinc-600">{m.type}:</span> {m.name || m.query || m.message || m.status || ""}
              </div>
            ))}
          </div>
        </div>
      </div>

      <ResultsView
        jobId={jobId}
        refreshSignal={refreshSignal}
        notify={notify}
        onNavigateSettings={() => setView("settings")}
      />
    </div>
  );
}

function Step({ label, active }) {
  return (
    <span
      className={`rounded-full px-2.5 py-0.5 transition ${
        active ? "bg-[#0A84FF]/20 text-[#64D2FF]" : "bg-white/[0.05] text-zinc-500"
      }`}
    >
      {active ? "● " : "○ "}
      {label}
    </span>
  );
}

const GL_LABEL = {
  us: "United States", ng: "Nigeria", gb: "United Kingdom", gh: "Ghana",
  ke: "Kenya", ca: "Canada", au: "Australia", de: "Germany", fr: "France",
  in: "India", za: "South Africa", ae: "UAE",
};

function JobSummary({ job }) {
  if (!job) return null;
  const meta = job.scan_meta ? (typeof job.scan_meta === "string" ? JSON.parse(job.scan_meta) : job.scan_meta) : null;
  const market = job.country || (job.gl && GL_LABEL[job.gl]) || job.gl || "—";
  const total = job.total || job.scraped || 0;
  const isArea = !!job.area_scan;
  const tilesTotal = meta?.tiles_total ?? (isArea ? "—" : 1);
  const geocoded = meta?.geocoded ?? 0;
  const fallback = meta?.fallback ?? 0;

  return (
    <div className="mb-4 space-y-2 rounded-2xl border border-white/[0.07] bg-white/[0.03] p-4 text-xs text-zinc-300">
      <div className="flex flex-wrap gap-x-5 gap-y-1">
        <span><b className="text-zinc-100">Market:</b> {market}</span>
        <span><b className="text-zinc-100">Type:</b> {isArea ? `Area scan · ${tilesTotal} tiles` : "Keyword search"}</span>
        <span className="tabular-nums"><b className="text-zinc-100">Businesses:</b> {total}</span>
      </div>
      {isArea && meta && (
        <div>
          <div className="flex justify-between text-zinc-400">
            <span>Tile geocoding: <b className="tabular-nums text-[#30D158]">{geocoded}/{tilesTotal}</b> districts</span>
            <span className="tabular-nums text-[#FFB340]">{fallback} coordinates</span>
          </div>
          <div className="mt-1.5 flex h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]">
            <div className="h-full bg-[#30D158]" style={{ width: `${tilesTotal ? (geocoded / tilesTotal) * 100 : 0}%` }} />
            <div className="h-full bg-[#FF9F0A]" style={{ width: `${tilesTotal ? (fallback / tilesTotal) * 100 : 0}%` }} />
          </div>
        </div>
      )}
    </div>
  );
}

/* ----------------------------- History ----------------------------- */
function History({ setView, notify, onOpenCopilot }) {
  const [jobs, setJobs] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [openId, setOpenId] = useState(null);
  const [confirmId, setConfirmId] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);

  const load = useCallback(() => {
    setLoadingJobs(true);
    api
      .listJobs(pageSize, (page - 1) * pageSize)
      .then((d) => {
        setJobs(d.jobs || []);
        setTotal(d.total || 0);
      })
      .catch(() => {
        setJobs([]);
        setTotal(0);
      })
      .finally(() => setLoadingJobs(false));
  }, [page, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  async function rescoreJob(id) {
    setBusyId(id);
    try {
      const r = await api.rescoreJob(id);
      notify(`Re-scored ${r.updated} leads`, "success");
    } catch {
      notify("Re-score failed", "error");
    } finally {
      setBusyId(null);
    }
  }

  async function runAgain(j) {
    setBusyId(j.id);
    try {
      const poly = j.polygon ? (Array.isArray(j.polygon) ? j.polygon : JSON.parse(j.polygon)) : [];
      let st = {};
      try {
        st = await api.getSettings();
      } catch {}
      const res = await api.createJob({
        query: j.query || "",
        location: j.location || "",
        max_results: st.max_results ?? j.max_results ?? 100,
        threads: st.threads ?? 2,
        area_scan: !!j.area_scan,
        country: j.country || "",
        gl: j.gl || "us",
        hl: j.hl || "en",
        proxy: j.proxy || st.default_proxy || "",
        polygon: poly,
        area_points: j.area_points,
        lat: j.lat ?? "",
        lng: j.lng ?? "",
        radius_km: j.radius_km ?? 5,
      });
      if (res && res.job_id) {
        saveActiveJob(res.job_id, true);
        setView("dashboard");
      } else {
        notify(res?.error || "Failed to re-run job", "error");
      }
    } catch (e) {
      notify("Failed to re-run search: " + (e?.message || e), "error");
    } finally {
      setBusyId(null);
    }
  }

  async function del(id) {
    setBusyId(id);
    try {
      await api.deleteJob(id);
      if (openId === id) setOpenId(null);
      setConfirmId(null);
      const remaining = total - 1;
      const maxPage = Math.max(1, Math.ceil(remaining / pageSize));
      if (page > maxPage) setPage(maxPage);
      load();
      notify("Job deleted", "success");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="animate-view-enter space-y-5 p-6">
      <Header title="Job History" subtitle="Inspect past runs, re-score leads, or re-run extractions" />

      <div className="grid gap-3 md:grid-cols-2">
        {loadingJobs && <div className="text-sm text-zinc-500 md:col-span-2">Loading jobs…</div>}
        {!loadingJobs && jobs.length === 0 && (
          <div className="card text-center text-sm text-zinc-500 md:col-span-2">No extraction runs yet.</div>
        )}
        {jobs.map((j, idx) => (
          <div
            key={j.id}
            style={{ animationDelay: `${Math.min(idx * 24, 200)}ms` }}
            onClick={() => setOpenId(openId === j.id ? null : j.id)}
            className={`animate-card-enter group relative flex cursor-pointer flex-col gap-2 rounded-[20px] border p-4 text-left transition-all duration-200 ease-spring ${
              openId === j.id
                ? "border-[#0A84FF]/60 bg-white/[0.06] ring-1 ring-[#0A84FF]/30"
                : "border-white/[0.08] bg-white/[0.03] hover:border-white/[0.15] hover:bg-white/[0.05]"
            }`}
          >
            <div className="flex w-full items-center justify-between gap-2 pr-8">
              <div className="min-w-0 truncate text-sm font-semibold text-zinc-100">
                {j.query || "Untitled"}
                {j.location ? <span className="font-normal text-zinc-400"> · {j.location}</span> : ""}
              </div>
              <StatusBadge status={j.status} />
            </div>
            <div className="flex w-full items-center justify-between text-xs text-zinc-500">
              <span className="truncate font-mono text-[11px]">{j.id}</span>
              <span className="shrink-0 tabular-nums">
                {j.scraped}/{j.total} · {j.created_at}
              </span>
            </div>

            <div className="absolute right-3 top-3" onClick={(e) => e.stopPropagation()}>
              {confirmId === j.id ? (
                <div className="flex items-center gap-1">
                  <button
                    className="rounded-lg bg-[#FF453A]/20 px-2 py-0.5 text-[11px] font-medium text-[#FF6961] hover:bg-[#FF453A]/30"
                    disabled={busyId === j.id}
                    onClick={() => del(j.id)}
                  >
                    Delete
                  </button>
                  <button
                    className="rounded-lg bg-white/[0.08] px-2 py-0.5 text-[11px] text-zinc-300 hover:bg-white/[0.14]"
                    onClick={() => setConfirmId(null)}
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  className="rounded-lg p-1.5 text-zinc-600 opacity-0 transition group-hover:opacity-100 hover:bg-white/[0.06] hover:text-[#FF6961]"
                  title="Delete job"
                  onClick={() => setConfirmId(j.id)}
                >
                  <Icons.Trash className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </div>
        ))}
      </div>

      {total > pageSize && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="text-xs tabular-nums text-zinc-500">
            Showing {start}–{end} of {total} jobs
          </div>
          <div className="flex items-center gap-2">
            <select
              className="input h-8 w-auto py-0 text-xs"
              value={pageSize}
              onChange={(e) => {
                setPageSize(+e.target.value);
                setPage(1);
              }}
            >
              {[10, 25, 50, 100].map((s) => (
                <option key={s} value={s}>
                  {s} / page
                </option>
              ))}
            </select>
            <div className="flex items-center gap-1">
              <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page <= 1} onClick={() => setPage(1)}>«</button>
              <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page <= 1} onClick={() => setPage(page - 1)}>‹</button>
              <span className="px-2 text-xs tabular-nums text-zinc-400">
                Page {page} / {totalPages}
              </span>
              <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>›</button>
              <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page >= totalPages} onClick={() => setPage(totalPages)}>»</button>
            </div>
          </div>
        </div>
      )}

      {openId &&
        (() => {
          const j = jobs.find((x) => x.id === openId);
          return (
            <div className="animate-view-enter pt-2">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <div className="text-sm font-semibold text-zinc-200">Results for {openId}</div>
                <div className="flex flex-wrap items-center gap-2">
                  {onOpenCopilot && (
                    <button
                      className="btn-primary px-3 py-1.5 text-xs"
                      onClick={() => onOpenCopilot(openId)}
                    >
                      <Icons.Sparkles className="h-3.5 w-3.5" /> Open in AI Copilot
                    </button>
                  )}
                  <button
                    className="btn-primary px-3 py-1.5 text-xs"
                    disabled={busyId === openId}
                    onClick={() => j && runAgain(j)}
                  >
                    <Icons.Refresh className="h-3.5 w-3.5" /> Run again
                  </button>
                  <button
                    className="btn-ghost px-3 py-1.5 text-xs"
                    disabled={busyId === openId}
                    onClick={() => rescoreJob(openId)}
                  >
                    Re-score
                  </button>
                  <button className="btn-ghost px-3 py-1.5 text-xs" onClick={() => setOpenId(null)}>
                    Close
                  </button>
                </div>
              </div>
              {j && <JobSummary job={j} />}
              <ResultsView
                jobId={openId}
                notify={notify}
                onNavigateSettings={() => setView("settings")}
              />
            </div>
          );
        })()}
    </div>
  );
}

/* ----------------------------- Proxies ----------------------------- */
function Proxies({ notify }) {
  const [text, setText] = useState("");
  const [rows, setRows] = useState([]);
  const [busy, setBusy] = useState(false);

  async function refresh() {
    setRows(await api.listProxies());
  }
  useEffect(() => {
    refresh();
  }, []);

  async function add() {
    setBusy(true);
    try {
      const r = await api.addProxies(text);
      notify(`Added ${r.added} proxies (total ${r.total})`, "success");
      setText("");
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  async function upload(e) {
    const f = e.target.files[0];
    if (!f) return;
    setBusy(true);
    try {
      const r = await api.uploadProxies(f);
      notify(`Added ${r.added} proxies (total ${r.total})`, "success");
      await refresh();
    } finally {
      setBusy(false);
    }
  }
  async function test() {
    setBusy(true);
    notify("Testing all proxies…", "warning");
    try {
      const list = await api.testProxies();
      setRows(list);
      const ok = list.filter((p) => p.status === "working").length;
      notify(`${ok}/${list.length} proxies working`, ok > 0 ? "success" : "warning");
    } finally {
      setBusy(false);
    }
  }
  async function clear() {
    await api.clearProxies();
    setRows([]);
    notify("Proxy pool cleared", "success");
  }

  const working = rows.filter((r) => r.status === "working").length;
  return (
    <div className="animate-view-enter mx-auto max-w-3xl space-y-5 p-6">
      <Header title="Proxy Pool" subtitle="Rotate verified HTTP / SOCKS5 proxies across search & details requests." />
      <div className="card space-y-3.5">
        <textarea
          className="input h-32 font-mono text-xs"
          placeholder={"1.2.3.4:8080\n1.2.3.4:8080:user:pass\nuser:pass@5.6.7.8:3128"}
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <div className="flex flex-wrap items-center gap-2.5">
          <button className="btn-primary text-xs" onClick={add} disabled={busy || !text.trim()}>
            Add Proxies
          </button>
          <label className="btn-ghost cursor-pointer text-xs">
            Upload File
            <input type="file" accept=".txt,.csv,.lst" className="hidden" onChange={upload} />
          </label>
          <button className="btn-ghost text-xs" onClick={test} disabled={busy || rows.length === 0}>
            <Icons.Refresh className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} /> Auto-Test All
          </button>
          <button className="btn-danger text-xs" onClick={clear} disabled={busy || rows.length === 0}>
            Clear
          </button>
          <span className="ml-auto text-xs tabular-nums text-zinc-400">
            <b className="text-[#30D158]">{working}</b> working / {rows.length} total
          </span>
        </div>
      </div>

      {rows.length > 0 && (
        <div className="card overflow-x-auto p-0">
          <table className="w-full text-xs">
            <thead className="border-b border-white/[0.07] bg-white/[0.03] text-zinc-400">
              <tr>
                <th className="px-4 py-2.5 text-left">Proxy</th>
                <th className="px-4 py-2.5 text-left">Status</th>
                <th className="px-4 py-2.5 text-left">Latency</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {rows.map((r, i) => (
                <tr key={i} className="hover:bg-white/[0.03]">
                  <td className="px-4 py-2.5 font-mono text-zinc-200">{r.raw}</td>
                  <td className="px-4 py-2.5">
                    <span
                      className={
                        r.status === "working"
                          ? "text-[#30D158]"
                          : r.status === "failed"
                          ? "text-[#FF6961]"
                          : "text-zinc-400"
                      }
                    >
                      {r.status}
                      {r.error ? ` (${r.error})` : ""}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-zinc-400">{r.latency != null ? r.latency + " ms" : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ----------------------------- Settings ----------------------------- */
function normalizeSettings(s) {
  return {
    ...s,
    threads: s.threads ?? 2,
    max_results: s.max_results ?? 100,
    scoring: s.scoring || { preset: "needs_help" },
  };
}

function Settings({ settings, setSettings, notify }) {
  const [local, setLocal] = useState(() => normalizeSettings(settings));
  const [meta, setMeta] = useState(null);

  useEffect(() => setLocal(normalizeSettings(settings)), [settings]);
  useEffect(() => {
    api.scoringMeta().then(setMeta).catch(() => {});
  }, []);

  async function save() {
    try {
      const updated = await api.saveSettings(local);
      setSettings(updated);
      notify("Settings saved", "success");
    } catch {
      notify("Failed to save settings", "error");
    }
  }

  async function uploadCreds(e) {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const res = await api.uploadCreds(file);
      if (res?.ok) {
        setSettings((prev) => ({ ...prev, has_google_creds: true }));
        setLocal((prev) => ({ ...prev, has_google_creds: true }));
        notify("Google Sheets credentials uploaded", "success");
      } else {
        notify(res?.error || "Invalid credentials JSON", "error");
      }
    } catch {
      notify("Failed to upload credentials", "error");
    }
  }

  const scoring = local.scoring || { preset: "needs_help" };
  function resolveWeights() {
    if (!meta) return {};
    if (scoring.preset === "custom" && scoring.weights) return scoring.weights;
    return meta.presets[scoring.preset]?.weights || {};
  }
  function setPreset(p) {
    const next = { preset: p };
    if (meta?.presets?.[p]) next.use_domain_age = meta.presets[p].use_domain_age;
    if (p === "custom") next.weights = { ...resolveWeights() };
    setLocal({ ...local, scoring: next });
  }
  function setWeight(id, val) {
    const cur = scoring.preset === "custom" ? { ...scoring } : { preset: "custom", weights: { ...resolveWeights() }, use_domain_age: scoring.use_domain_age };
    cur.weights = { ...(cur.weights || {}), [id]: Number(val) };
    setLocal({ ...local, scoring: cur });
  }
  function toggleDomainAge() {
    setLocal({ ...local, scoring: { ...scoring, use_domain_age: !scoring.use_domain_age } });
  }
  async function rescoreAll() {
    try {
      await api.saveSettings(local);
      setSettings(local);
      const r = await api.rescoreAll();
      notify(`Re-scored ${r.updated} leads across all jobs`, "success");
    } catch (e) {
      notify("Re-score failed: " + (e?.message || e), "error");
    }
  }

  const weights = resolveWeights();

  return (
    <div className="animate-view-enter mx-auto max-w-3xl space-y-5 p-6">
      <Header title="Settings" subtitle="Defaults, concurrency, Google Sheets credentials, and lead scoring" />

      <div className="card space-y-4">
        <div className="grid gap-4 md:grid-cols-3">
          <div>
            <label className="label">Default Market (gl)</label>
            <input className="input" value={local.gl} onChange={(e) => setLocal({ ...local, gl: e.target.value })} />
          </div>
          <div>
            <label className="label">Language (hl)</label>
            <input className="input" value={local.hl} onChange={(e) => setLocal({ ...local, hl: e.target.value })} />
          </div>
          <div>
            <label className="label">Fallback Proxy</label>
            <input
              className="input"
              placeholder="http://host:port"
              value={local.default_proxy}
              onChange={(e) => setLocal({ ...local, default_proxy: e.target.value })}
            />
          </div>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="label">Concurrent Threads (1–16)</label>
            <input
              className="input tabular-nums"
              type="number"
              min="1"
              max="16"
              value={local.threads ?? 2}
              onChange={(e) => setLocal({ ...local, threads: Math.max(1, Math.min(16, +e.target.value || 1)) })}
            />
          </div>
          <div>
            <label className="label">Max Results per Search</label>
            <input
              className="input tabular-nums"
              type="number"
              min="10"
              max="1000"
              value={local.max_results ?? 100}
              onChange={(e) => setLocal({ ...local, max_results: Math.max(10, Math.min(1000, +e.target.value || 100)) })}
            />
          </div>
        </div>

        <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-xs font-semibold text-zinc-200">Google Sheets Service Account JSON</div>
              <div className="text-[11px] text-zinc-500">Required only when exporting directly to Google Sheets.</div>
            </div>
            <span
              className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                local.has_google_creds ? "bg-[#30D158]/15 text-[#30D158]" : "bg-white/[0.06] text-zinc-400"
              }`}
            >
              {local.has_google_creds ? "✓ Configured" : "Not uploaded"}
            </span>
          </div>
          <label className="btn-ghost mt-3 cursor-pointer text-xs">
            {local.has_google_creds ? "Replace Credentials JSON" : "Upload Credentials JSON"}
            <input type="file" accept=".json" onChange={uploadCreds} className="hidden" />
          </label>
        </div>

        <div>
          <button className="btn-primary text-xs" onClick={save}>
            Save Settings
          </button>
        </div>
      </div>

      {/* Lead Scoring configuration */}
      <div className="card space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-zinc-100">Lead Scoring System</h2>
          <p className="mt-0.5 text-xs text-zinc-400">
            Choose an explainable scoring preset or customize factor weights.
          </p>
        </div>

        <div className="segmented flex-wrap">
          {meta &&
            Object.entries(meta.presets).map(([k, v]) => (
              <button
                key={k}
                type="button"
                className={`segmented-item ${
                  scoring.preset === k ? "bg-[#0A84FF] text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200"
                }`}
                onClick={() => setPreset(k)}
              >
                {v.label}
              </button>
            ))}
          <button
            type="button"
            className={`segmented-item ${
              scoring.preset === "custom" ? "bg-[#0A84FF] text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200"
            }`}
            onClick={() => setPreset("custom")}
          >
            Custom
          </button>
        </div>

        <label className="flex cursor-pointer items-center gap-2 text-xs text-zinc-300">
          <input type="checkbox" className="accent-[#0A84FF]" checked={!!scoring.use_domain_age} onChange={toggleDomainAge} />
          Use domain age (WHOIS) — rewards older, established businesses
        </label>

        {scoring.preset === "custom" && meta && (
          <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-4">
            <div className="mb-3 text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
              Factor weights (positive = reward, negative = penalise)
            </div>
            <div className="grid gap-x-6 gap-y-2.5 sm:grid-cols-2">
              {meta.factors.map((f) => (
                <div key={f.id} className="flex items-center gap-2.5">
                  <span className="w-36 shrink-0 truncate text-xs text-zinc-400" title={f.label}>
                    {f.label}
                  </span>
                  <input
                    type="range"
                    min={-40}
                    max={40}
                    step={1}
                    value={weights[f.id] || 0}
                    onChange={(e) => setWeight(f.id, e.target.value)}
                    className="flex-1 accent-[#0A84FF]"
                  />
                  <span className="w-8 shrink-0 text-right text-xs tabular-nums text-zinc-200">{weights[f.id] || 0}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2.5">
          <button className="btn-primary text-xs" onClick={save}>
            Save Scoring
          </button>
          <button className="btn-ghost text-xs" onClick={rescoreAll} disabled={!meta}>
            <Icons.Refresh className="h-3.5 w-3.5" /> Re-score All Jobs Now
          </button>
        </div>
      </div>

      <AiSettingsSection notify={notify} />
    </div>
  );
}

function AiSettingsSection({ notify }) {
  const [cfg, setCfg] = useState(null);
  const [provider, setProvider] = useState("gemini");
  const [tier, setTier] = useState("fast");
  const [customModel, setCustomModel] = useState("");
  const [selectedModelsMap, setSelectedModelsMap] = useState({});
  const [modelsByProvider, setModelsByProvider] = useState({});
  const [modelsMetaInfo, setModelsMetaInfo] = useState({});
  const [fetchingModels, setFetchingModels] = useState(false);
  const [manualCustomMode, setManualCustomMode] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [guardrails, setGuardrails] = useState({ max_searches: 3, max_scrapes: 100, max_deep_leads: 25, max_steps: 18 });
  const [savingAi, setSavingAi] = useState(false);
  const [testingAi, setTestingAi] = useState(false);
  const [testResult, setTestResult] = useState(null);

  const [offers, setOffers] = useState([]);
  const [offerForm, setOfferForm] = useState({
    id: "",
    name: "",
    service_type: "",
    min_budget: "",
    target_niche: "",
    pitch_notes: "",
    mode_id: "custom",
  });

  const fetchProviderModels = useCallback(async (prov, { keyOverride, baseOverride, refresh = false, silent = false } = {}) => {
    setFetchingModels(true);
    try {
      const payload = { provider: prov, refresh };
      if (keyOverride && keyOverride.trim()) payload.api_key = keyOverride.trim();
      if (baseOverride !== undefined && baseOverride !== "") payload.base_url = baseOverride;
      const d = await api.aiModels(payload);
      if (d?.models?.length) {
        setModelsByProvider((prev) => ({ ...prev, [prov]: d.models }));
        setModelsMetaInfo((prev) => ({ ...prev, [prov]: { source: d.source, live_count: d.live_count, note: d.note, error: d.error } }));
        if (!silent && notify) {
          if (d.source === "live") notify(`Loaded ${d.live_count} live models (Small → Big)`, "success");
          else if (d.error) notify(`Live fetch warning: ${d.error}`, "warning");
        }
      }
    } catch {}
    finally {
      setFetchingModels(false);
    }
  }, [notify]);

  const refreshAi = useCallback(() => {
    api.aiConfig().then((d) => {
      setCfg(d);
      const prov = d.provider || "gemini";
      setProvider(prov);
      setTier(d.tier || "fast");
      setCustomModel(d.selected_model || d.custom_model || "");
      setSelectedModelsMap(d.selected_models || {});
      setBaseUrl(d.base_url || "");
      if (d.curated_models) {
        setModelsByProvider((prev) => ({ ...d.curated_models, ...prev }));
      }
      if (d.guardrails) setGuardrails(d.guardrails);
      if (d.keys_status?.[prov]?.configured || prov === "ollama") {
        fetchProviderModels(prov, { baseOverride: d.base_url, silent: true });
      }
    }).catch(() => {});
    api.listOffers().then((d) => setOffers(d?.offers || [])).catch(() => {});
  }, [fetchProviderModels]);

  useEffect(() => {
    refreshAi();
  }, [refreshAi]);

  const modelsMeta = cfg?.provider_models || {};
  const maskedKey = cfg?.keys?.[provider] || "";
  const activeModelsList = modelsByProvider[provider] || cfg?.curated_models?.[provider] || [];
  const activeMeta = modelsMetaInfo[provider];
  const effectiveModelId = customModel.trim() || selectedModelsMap[provider] || modelsMeta?.[provider]?.balanced || modelsMeta?.[provider]?.fast || "";
  const inModelsList = activeModelsList.some((m) => m.id === effectiveModelId);

  function switchProviderTab(nextProv) {
    setProvider(nextProv);
    setTestResult(null);
    setManualCustomMode(false);
    const savedForProv = selectedModelsMap[nextProv] || modelsMeta?.[nextProv]?.balanced || modelsMeta?.[nextProv]?.fast || "";
    setCustomModel(savedForProv);
    if (cfg?.keys_status?.[nextProv]?.configured || nextProv === "ollama") {
      fetchProviderModels(nextProv, { silent: true });
    }
  }

  async function saveAi(extra = {}) {
    setSavingAi(true);
    try {
      const chosenModel = customModel.trim() || effectiveModelId;
      const found = activeModelsList.find((m) => m.id === chosenModel);
      const inferredTier = found?.tier === "large" ? "best" : found?.tier === "balanced" ? "balanced" : "fast";
      const payload = {
        provider,
        tier: extra.tier || inferredTier || tier,
        model: chosenModel,
        custom_model: chosenModel,
        base_url: baseUrl,
        guardrails,
        ...extra,
      };
      if (apiKeyInput.trim()) {
        payload.api_keys = { [provider]: apiKeyInput.trim() };
      }
      const d = await api.saveAiConfig(payload);
      setCfg(d);
      setSelectedModelsMap(d.selected_models || {});
      const hadNewKey = Boolean(apiKeyInput.trim());
      setApiKeyInput("");
      notify("AI configuration saved (encrypted at rest)", "success");
      if (hadNewKey) {
        fetchProviderModels(provider, { refresh: true, baseOverride: baseUrl, silent: true });
      }
    } catch {
      notify("Failed to save AI settings", "error");
    } finally {
      setSavingAi(false);
    }
  }

  async function clearProviderKey() {
    await saveAi({ api_keys: { [provider]: "" } });
    setTestResult(null);
  }

  async function testConnection() {
    setTestingAi(true);
    setTestResult(null);
    try {
      const payload = {
        provider,
        tier,
        model: effectiveModelId,
        custom_model: effectiveModelId,
        base_url: baseUrl,
      };
      if (apiKeyInput.trim()) payload.api_key = apiKeyInput.trim();
      const res = await api.testAiConnection(payload);
      setTestResult(res);
      if (res?.ok) {
        notify(`Connected to ${res.model} (${res.latency_ms}ms)`, "success");
        fetchProviderModels(provider, {
          keyOverride: apiKeyInput.trim() || undefined,
          baseOverride: baseUrl,
          refresh: true,
          silent: true,
        });
      } else {
        notify(res?.error || "Connection test failed", "error");
      }
    } catch (e) {
      setTestResult({ ok: false, error: String(e) });
    } finally {
      setTestingAi(false);
    }
  }

  async function submitOffer(e) {
    e.preventDefault();
    if (!offerForm.name.trim()) return;
    try {
      await api.saveOffer(offerForm);
      setOfferForm({ id: "", name: "", service_type: "", min_budget: "", target_niche: "", pitch_notes: "", mode_id: "custom" });
      api.listOffers().then((d) => setOffers(d?.offers || [])).catch(() => {});
      notify("Offer profile saved", "success");
    } catch {
      notify("Failed to save offer", "error");
    }
  }

  async function delOffer(id) {
    await api.deleteOffer(id);
    api.listOffers().then((d) => setOffers(d?.offers || [])).catch(() => {});
  }

  return (
    <>
      <div className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-zinc-100">
              <Icons.Sparkles className="h-4 w-4 text-[#64D2FF]" />
              AI Engine (Optional BYOK)
            </h2>
            <p className="mt-0.5 text-xs text-zinc-400">
              Bring your own key for Gemini, Claude, ChatGPT, or local Ollama. Stored encrypted on this machine.
            </p>
          </div>
          <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${cfg?.configured ? "bg-[#30D158]/15 text-[#30D158]" : "bg-white/[0.06] text-zinc-400"}`}>
            {cfg?.configured ? "✓ AI Ready" : "Not configured (optional)"}
          </span>
        </div>

        <div className="segmented flex-wrap">
          {[
            ["gemini", "Google Gemini"],
            ["claude", "Anthropic Claude"],
            ["openai", "OpenAI / ChatGPT"],
            ["ollama", "Local Ollama / Custom"],
          ].map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => switchProviderTab(id)}
              className={`segmented-item ${
                provider === id ? "bg-[#0A84FF] text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          {provider !== "ollama" ? (
            <div>
              <label className="label">
                {modelsMeta?.[provider]?.label || provider} API Key{" "}
                {maskedKey && <span className="text-[#30D158]">(Saved: {maskedKey})</span>}
              </label>
              <input
                type="password"
                className="input"
                placeholder={maskedKey ? "Enter new key to replace saved key…" : "Paste your API key…"}
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
              />
            </div>
          ) : (
            <div>
              <label className="label">Ollama / OpenAI-Compatible Base URL</label>
              <input
                className="input"
                placeholder="http://127.0.0.1:11434/v1"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </div>
          )}

          <div>
            <div className="mb-1.5 flex items-center justify-between gap-2">
              <label className="label mb-0">
                AI Model <span className="text-zinc-500">(Small → Big)</span>
              </label>
              <button
                type="button"
                onClick={() =>
                  fetchProviderModels(provider, {
                    keyOverride: apiKeyInput.trim() || undefined,
                    baseOverride: baseUrl,
                    refresh: true,
                  })
                }
                disabled={fetchingModels}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-[#409CFF] hover:underline disabled:opacity-50"
              >
                <Icons.Refresh className={`h-3 w-3 ${fetchingModels ? "animate-spin" : ""}`} />
                {fetchingModels ? "Fetching…" : "Fetch Live Models"}
              </button>
            </div>
            <select
              className="input text-xs"
              value={manualCustomMode || (!inModelsList && effectiveModelId) ? "__custom__" : effectiveModelId}
              onChange={(e) => {
                const v = e.target.value;
                if (v === "__custom__") {
                  setManualCustomMode(true);
                } else {
                  setManualCustomMode(false);
                  setCustomModel(v);
                  setSelectedModelsMap((prev) => ({ ...prev, [provider]: v }));
                }
              }}
            >
              {[
                ["small", "Small · Fast & Low Cost"],
                ["balanced", "Balanced · Everyday Quality"],
                ["large", "Big · Flagship & Deep Reasoning"],
              ].map(([tKey, tLabel]) => {
                const group = activeModelsList.filter((m) => m.tier === tKey);
                if (!group.length) return null;
                return (
                  <optgroup key={tKey} label={tLabel}>
                    {group.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name !== m.id ? `${m.name} (${m.id})` : m.id}
                        {m.note && m.note !== m.tier_label ? ` — ${m.note}` : ""}
                      </option>
                    ))}
                  </optgroup>
                );
              })}
              <option value="__custom__">
                {!inModelsList && effectiveModelId ? `Custom: ${effectiveModelId}` : "Enter custom model ID manually…"}
              </option>
            </select>
            <div className="mt-1 text-[10px] text-zinc-500">
              {activeMeta?.source === "live" ? (
                <span className="text-[#30D158]">✓ {activeMeta.note}</span>
              ) : (
                <span>{activeMeta?.note || `Ordered smallest → biggest (${activeModelsList.length} available)`}</span>
              )}
            </div>
          </div>
        </div>

        {(manualCustomMode || (!inModelsList && effectiveModelId)) && (
          <div>
            <label className="label">Custom Model ID</label>
            <input
              className="input text-xs"
              placeholder="e.g. gemini-2.5-flash or preview model ID"
              value={customModel}
              onChange={(e) => {
                setCustomModel(e.target.value);
                setSelectedModelsMap((prev) => ({ ...prev, [provider]: e.target.value }));
              }}
            />
          </div>
        )}

        <details className="rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3 text-xs">
          <summary className="cursor-pointer font-medium text-zinc-300">Advanced Gateway &amp; Safety Guardrails</summary>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            {provider !== "ollama" && (
              <div className="sm:col-span-2">
                <label className="label">Custom OpenAI-Compatible Base URL (optional)</label>
                <input
                  className="input text-xs"
                  placeholder="Optional custom gateway URL (e.g. OpenRouter / Azure / LiteLLM)"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                />
              </div>
            )}
            <div>
              <label className="label">Max Searches / Mission</label>
              <input
                type="number"
                min="1"
                max="15"
                className="input text-xs tabular-nums"
                value={guardrails.max_searches}
                onChange={(e) => setGuardrails({ ...guardrails, max_searches: +e.target.value || 3 })}
              />
            </div>
            <div>
              <label className="label">Max Scrapes / Search</label>
              <input
                type="number"
                min="10"
                max="500"
                className="input text-xs tabular-nums"
                value={guardrails.max_scrapes}
                onChange={(e) => setGuardrails({ ...guardrails, max_scrapes: +e.target.value || 100 })}
              />
            </div>
            <div>
              <label className="label">Max Deep Website Inspections</label>
              <input
                type="number"
                min="5"
                max="100"
                className="input text-xs tabular-nums"
                value={guardrails.max_deep_leads}
                onChange={(e) => setGuardrails({ ...guardrails, max_deep_leads: +e.target.value || 25 })}
              />
            </div>
            <div>
              <label className="label">Max Agent Tool Steps</label>
              <input
                type="number"
                min="4"
                max="40"
                className="input text-xs tabular-nums"
                value={guardrails.max_steps}
                onChange={(e) => setGuardrails({ ...guardrails, max_steps: +e.target.value || 18 })}
              />
            </div>
          </div>
        </details>

        <div className="flex flex-wrap items-center gap-2.5">
          <button type="button" onClick={() => saveAi()} disabled={savingAi} className="btn-primary text-xs">
            {savingAi ? "Saving…" : "Save AI Settings"}
          </button>
          <button type="button" onClick={testConnection} disabled={testingAi} className="btn-ghost text-xs">
            <Icons.Refresh className={`h-3.5 w-3.5 ${testingAi ? "animate-spin" : ""}`} />
            {testingAi ? "Testing…" : "Test Connection"}
          </button>
          {maskedKey && (
            <button type="button" onClick={clearProviderKey} className="btn-ghost text-xs text-[#FF6961]">
              Clear {provider} Key
            </button>
          )}
          {testResult && (
            <span className={`text-xs ${testResult.ok ? "text-[#30D158]" : "text-[#FF6961]"}`}>
              {testResult.ok ? `Connected · ${testResult.model} (${testResult.latency_ms}ms)` : testResult.error}
            </span>
          )}
        </div>
      </div>

      {/* Reusable Saved Offers */}
      <div className="card space-y-4">
        <div>
          <h2 className="text-sm font-semibold text-zinc-100">Saved Offer Profiles</h2>
          <p className="mt-0.5 text-xs text-zinc-400">
            Save your services, pricing, and ideal client rules once so AI Copilot remembers what you sell on every mission.
          </p>
        </div>

        {offers.length > 0 && (
          <div className="grid gap-2.5 sm:grid-cols-2">
            {offers.map((o) => (
              <div key={o.id} className="flex items-start justify-between gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.02] p-3 text-xs">
                <div className="min-w-0">
                  <div className="font-semibold text-zinc-100">{o.name}</div>
                  {o.min_budget && <div className="text-[11px] text-[#30D158]">Budget: {o.min_budget}</div>}
                  {o.service_type && <div className="truncate text-[11px] text-zinc-400">{o.service_type}</div>}
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setOfferForm(o)}
                    className="btn-ghost px-2 py-1 text-[10px]"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => delOffer(o.id)}
                    className="rounded-lg p-1 text-zinc-500 hover:bg-[#FF453A]/15 hover:text-[#FF6961]"
                  >
                    <Icons.Trash className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={submitOffer} className="space-y-3 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3.5">
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="label">Offer Name</label>
              <input
                className="input text-xs"
                placeholder="e.g. Dental Website & AI Booking Package"
                value={offerForm.name}
                onChange={(e) => setOfferForm({ ...offerForm, name: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Target Budget / Minimum Price</label>
              <input
                className="input text-xs"
                placeholder="e.g. $2,000 setup + $500/mo"
                value={offerForm.min_budget}
                onChange={(e) => setOfferForm({ ...offerForm, min_budget: e.target.value })}
              />
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="label">What You Sell</label>
              <input
                className="input text-xs"
                placeholder="e.g. High-converting website redesign + local SEO"
                value={offerForm.service_type}
                onChange={(e) => setOfferForm({ ...offerForm, service_type: e.target.value })}
              />
            </div>
            <div>
              <label className="label">Ideal Client / Exclusion Rules</label>
              <input
                className="input text-xs"
                placeholder="e.g. Independent clinics, 30+ reviews, skip chains"
                value={offerForm.target_niche}
                onChange={(e) => setOfferForm({ ...offerForm, target_niche: e.target.value })}
              />
            </div>
          </div>
          <div>
            <label className="label">Pitch Notes / Tone</label>
            <textarea
              rows={2}
              className="input resize-none text-xs"
              placeholder="e.g. Friendly, consultative tone; mention how many calls or bookings they lose."
              value={offerForm.pitch_notes}
              onChange={(e) => setOfferForm({ ...offerForm, pitch_notes: e.target.value })}
            />
          </div>
          <div className="flex items-center gap-2">
            <button type="submit" disabled={!offerForm.name.trim()} className="btn-primary text-xs">
              {offerForm.id ? "Update Offer Profile" : "Save Offer Profile"}
            </button>
            {offerForm.id && (
              <button
                type="button"
                onClick={() => setOfferForm({ id: "", name: "", service_type: "", min_budget: "", target_niche: "", pitch_notes: "", mode_id: "custom" })}
                className="btn-ghost text-xs"
              >
                Cancel Edit
              </button>
            )}
          </div>
        </form>
      </div>
    </>
  );
}

function Header({ title, subtitle }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">{title}</h1>
      {subtitle && <p className="mt-0.5 text-sm text-zinc-400">{subtitle}</p>}
    </div>
  );
}

function AppFooter({ branding, agreed, onShowTerms, onShowDisclaimer }) {
  return (
    <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-white/[0.07] bg-zinc-950/80 px-5 py-2 text-[11px] text-zinc-500 backdrop-blur-xl">
      <div className="flex items-center gap-3">
        <button onClick={onShowTerms} className="hover:text-zinc-200 hover:underline underline-offset-2">
          Terms &amp; Agreement
        </button>
        <button onClick={onShowDisclaimer} className="hover:text-zinc-200 hover:underline underline-offset-2">
          Disclaimer
        </button>
        {agreed && <span className="text-zinc-600">Terms accepted</span>}
      </div>
      <div className="flex items-center gap-3">
        <a href={branding?.telegram_personal || "https://t.me/brain_lead"} target="_blank" rel="noreferrer" className="hover:text-zinc-200">
          {branding?.telegram_personal_handle || "@brain_lead"}
        </a>
        <a href={branding?.telegram_bot || "https://t.me/BrainLeadBot"} target="_blank" rel="noreferrer" className="hover:text-zinc-200">
          {branding?.telegram_bot_handle || "@brainleadbot"}
        </a>
        <span>© GME · Google Map Extractor</span>
      </div>
    </footer>
  );
}
