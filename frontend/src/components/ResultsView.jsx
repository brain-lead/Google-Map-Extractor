import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { aiColor, CopyButton, Icons, leadColor, mapsLink, StarRating, tryJson } from "./ui.jsx";
import { BusinessModal, ComparePanel, ReportModal } from "./Modals.jsx";
import ResultsMap from "./ResultsMap.jsx";

const DEFAULT_FILTERS = {
  q: "",
  min_rating: "",
  min_reviews: "",
  min_ai_score: "",
  affordability: "",
  ai_verdict: "",
  removed_only: false,
  location: [],
  country: [],
  has_email: false,
  has_social: false,
  has_website: false,
  has_phone: false,
  has_hours: false,
  has_menu: false,
  has_reviews: false,
  hot_only: false,
  sort: "lead_desc",
};

function loadSavedFilters() {
  try {
    return JSON.parse(localStorage.getItem("mge.savedFilters")) || [];
  } catch {
    return [];
  }
}

function pageWindow(cur, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const out = [1];
  const s = Math.max(2, cur - 1);
  const e = Math.min(total - 1, cur + 1);
  if (s > 2) out.push("…");
  for (let i = s; i <= e; i++) out.push(i);
  if (e < total - 1) out.push("…");
  out.push(total);
  return out;
}

export default function ResultsView({ jobId, refreshSignal = 0, notify, externalView = null, onNavigateSettings }) {
  const [filters, setFilters] = useState({ ...DEFAULT_FILTERS });
  const [viewMode, setViewMode] = useState("cards"); // cards | table | map
  const [areas, setAreas] = useState([]);
  const [countries, setCountries] = useState([]);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(24);
  const [data, setData] = useState({ items: [], total: 0, removed_count: 0 });
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [saved, setSaved] = useState(loadSavedFilters());
  const [compare, setCompare] = useState(null);
  const [report, setReport] = useState(null);
  const [rescoring, setRescoring] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // Inline AI Co-Pilot state
  const [aiConfigured, setAiConfigured] = useState(false);
  const [modes, setModes] = useState([]);
  const [offers, setOffers] = useState([]);
  const [aiMode, setAiMode] = useState("web_seo");
  const [offerId, setOfferId] = useState("");
  const [aiCmd, setAiCmd] = useState("");
  const [aiBusy, setAiBusy] = useState(false);
  const [cmdSummary, setCmdSummary] = useState("");
  const [highlightCids, setHighlightCids] = useState([]);

  const filterSig = JSON.stringify(filters);

  useEffect(() => {
    api.aiConfig().then((d) => {
      setAiConfigured(!!d?.configured);
      setModes(d?.modes || []);
    }).catch(() => {});
    api.listOffers().then((d) => setOffers(d?.offers || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!externalView) return;
    setPage(1);
    setHighlightCids(Array.isArray(externalView.highlight_cids) ? externalView.highlight_cids : []);
    const { highlight_cids, ...rest } = externalView;
    setFilters((prev) => ({ ...DEFAULT_FILTERS, ...prev, ...rest }));
  }, [externalView]);

  useEffect(() => {
    if (!jobId) {
      setAreas([]);
      setCountries([]);
      return;
    }
    api
      .facets(jobId)
      .then((f) => {
        setAreas(f.areas || []);
        setCountries(f.countries || []);
      })
      .catch(() => {
        setAreas([]);
        setCountries([]);
      });
  }, [jobId, refreshSignal, reloadKey]);

  useEffect(() => {
    if (!jobId) {
      setData({ items: [], total: 0 });
      return;
    }
    let active = true;
    setLoading(true);
    api
      .results(jobId, filters, pageSize, (page - 1) * pageSize)
      .then((d) => {
        if (active) {
          setData(d && d.items ? d : { items: [], total: 0 });
          setLoading(false);
        }
      })
      .catch(() => {
        if (active) {
          setData({ items: [], total: 0 });
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [jobId, filterSig, page, pageSize, refreshSignal, reloadKey]);

  function patch(p) {
    setPage(1);
    setFilters((f) => ({ ...f, ...p }));
  }
  function clearAll() {
    setPage(1);
    setFilters({ ...DEFAULT_FILTERS });
  }
  function applyPreset(p) {
    setPage(1);
    setFilters({ ...DEFAULT_FILTERS, ...p });
  }
  function removePreset(i) {
    const next = saved.filter((_, j) => j !== i);
    setSaved(next);
    try {
      localStorage.setItem("mge.savedFilters", JSON.stringify(next));
    } catch {}
  }
  function savePreset() {
    const name = window.prompt("Name this filter view", "Filter " + (saved.length + 1));
    if (!name) return;
    const next = [...saved, { name, filters: { ...filters } }];
    setSaved(next);
    try {
      localStorage.setItem("mge.savedFilters", JSON.stringify(next));
      if (notify) notify(`Saved filter "${name}"`, "success");
    } catch {}
  }

  async function openCompare() {
    setCompare({ loading: true });
    try {
      const d = await api.compareJobs(jobId);
      setCompare(d);
    } catch (e) {
      setCompare({ error: String(e) });
    }
  }

  async function openReport() {
    setReport({ loading: true });
    try {
      const d = await api.jobReport(jobId);
      setReport(d);
    } catch (e) {
      setReport({ error: String(e) });
    }
  }

  async function rescore() {
    if (!jobId) return;
    setRescoring(true);
    try {
      const r = await api.rescoreJob(jobId);
      if (notify) notify(`Re-scored ${r.updated} leads`, "success");
      setReloadKey((k) => k + 1);
    } catch {
      if (notify) notify("Re-score failed", "error");
    } finally {
      setRescoring(false);
    }
  }

  async function runAiAnalyze() {
    if (!jobId) return;
    setAiBusy(true);
    setCmdSummary("");
    try {
      const r = await api.aiAnalyzeJob(jobId, { mode_id: aiMode, offer_id: offerId, limit: 25 });
      if (r?.error) {
        if (notify) notify(r.error, "error");
      } else {
        if (notify) notify(`AI analyzed ${r.analyzed || 0} leads`, "success");
        setFilters((f) => ({ ...f, sort: "ai_desc" }));
        setReloadKey((k) => k + 1);
      }
    } catch (e) {
      if (notify) notify(String(e), "error");
    } finally {
      setAiBusy(false);
    }
  }

  async function runAiCommand(e) {
    e && e.preventDefault();
    if (!jobId || !aiCmd.trim()) return;
    setAiBusy(true);
    setCmdSummary("");
    try {
      const r = await api.aiCommandJob(jobId, { command: aiCmd.trim(), mode_id: aiMode, offer_id: offerId });
      if (r?.error) {
        if (notify) notify(r.error, "error");
        return;
      }
      if (r?.summary) setCmdSummary(r.summary);
      if (r?.view) {
        const { highlight_cids, ...rest } = r.view;
        setHighlightCids(Array.isArray(highlight_cids) ? highlight_cids : []);
        setFilters((prev) => ({ ...DEFAULT_FILTERS, ...prev, ...rest }));
      }
      setAiCmd("");
      setReloadKey((k) => k + 1);
      if (notify) notify(r?.summary || "Command executed", "success");
    } catch (err) {
      if (notify) notify(String(err), "error");
    } finally {
      setAiBusy(false);
    }
  }

  async function restoreAllRemoved() {
    if (!jobId) return;
    try {
      const r = await api.restoreRemoved(jobId);
      setFilters((f) => ({ ...f, removed_only: false }));
      setReloadKey((k) => k + 1);
      if (notify) notify(`Restored ${r?.restored || 0} removed lead(s)`, "success");
    } catch (e) {
      if (notify) notify(String(e), "error");
    }
  }

  async function softRemoveLead(cid) {
    if (!jobId || !cid) return;
    try {
      await api.removeLeads(jobId, [cid], "Removed from results");
      setReloadKey((k) => k + 1);
      if (notify) notify("Lead hidden (use Restore pill to undo)", "success");
    } catch {}
  }

  const total = data.total || 0;
  const removedCount = data.removed_count || 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const start = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(total, page * pageSize);
  const pages = pageWindow(page, totalPages);
  const isFiltered = filterSig !== JSON.stringify(DEFAULT_FILTERS);

  return (
    <div className="space-y-4">
      {jobId && (
        <div className="card space-y-2.5 border-[#0A84FF]/20 bg-gradient-to-r from-[#0A84FF]/[0.06] via-white/[0.02] to-transparent">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-zinc-200">
              <Icons.Sparkles className="h-3.5 w-3.5 text-[#64D2FF]" />
              <span>AI Quick Co-Pilot</span>
              <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${aiConfigured ? "bg-[#30D158]/15 text-[#30D158]" : "bg-white/[0.07] text-zinc-400"}`}>
                {aiConfigured ? "Ready" : "Optional · Add AI key in Settings"}
              </span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="input h-7 w-auto py-0 text-[11px]"
                value={aiMode}
                onChange={(e) => setAiMode(e.target.value)}
                title="AI Analysis Mode"
              >
                {(modes.length ? modes : [
                  { id: "web_seo", label: "Web Design & SEO" },
                  { id: "reputation_voice", label: "Reputation & AI Voice" },
                  { id: "b2b_outreach", label: "B2B Cold Outreach" },
                  { id: "icp_budget", label: "ICP & Budget" },
                  { id: "market_research", label: "Market Research" },
                  { id: "custom", label: "Custom Rules" },
                ]).map((m) => (
                  <option key={m.id} value={m.id}>{m.label}</option>
                ))}
              </select>
              {offers.length > 0 && (
                <select
                  className="input h-7 w-auto py-0 text-[11px]"
                  value={offerId}
                  onChange={(e) => setOfferId(e.target.value)}
                >
                  <option value="">No saved offer</option>
                  {offers.map((o) => (
                    <option key={o.id} value={o.id}>{o.name}</option>
                  ))}
                </select>
              )}
              <button
                type="button"
                onClick={runAiAnalyze}
                disabled={aiBusy || !aiConfigured}
                title={aiConfigured ? "Score & generate outreach for top 25 leads" : "Configure AI key in Settings first"}
                className="btn-primary h-7 px-3 text-[11px]"
              >
                <Icons.Sparkles className={`h-3 w-3 ${aiBusy ? "animate-spin" : ""}`} />
                {aiBusy ? "Working…" : "AI Analyze Top 25"}
              </button>
              {!aiConfigured && onNavigateSettings && (
                <button type="button" onClick={onNavigateSettings} className="btn-ghost h-7 px-2.5 text-[11px] text-[#409CFF]">
                  Setup AI
                </button>
              )}
            </div>
          </div>

          <form onSubmit={runAiCommand} className="flex flex-wrap items-center gap-2">
            <input
              className="input h-8 flex-1 min-w-[220px] text-xs"
              placeholder={
                aiConfigured
                  ? 'Command AI on this table: e.g. "remove chains & sort by best web redesign leads" or "undo"'
                  : "Configure an AI key in Settings → AI Engine to run plain-English table commands"
              }
              value={aiCmd}
              onChange={(e) => setAiCmd(e.target.value)}
              disabled={aiBusy || !aiConfigured}
            />
            <button type="submit" disabled={aiBusy || !aiConfigured || !aiCmd.trim()} className="btn-ghost h-8 px-3 text-xs">
              <Icons.Send className="h-3.5 w-3.5" /> Run
            </button>
          </form>

          {cmdSummary && (
            <div className="flex items-center justify-between gap-2 rounded-xl border border-[#30D158]/25 bg-[#30D158]/10 px-3 py-1.5 text-xs text-zinc-200">
              <span>{cmdSummary}</span>
              <button type="button" onClick={() => setCmdSummary("")} className="text-zinc-400 hover:text-white">
                <Icons.X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      )}
      {saved.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-zinc-500">Saved filters:</span>
          {saved.map((p, i) => (
            <span
              key={i}
              className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.05] px-3 py-1 text-xs text-zinc-300 transition hover:bg-white/[0.09]"
            >
              <button onClick={() => applyPreset(p.filters)} className="hover:text-white">
                {p.name}
              </button>
              <button onClick={() => removePreset(i)} className="opacity-55 hover:opacity-100" title="Remove">
                <Icons.X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <FilterBar filters={filters} patch={patch} clearAll={clearAll} savePreset={savePreset} areas={areas} countries={countries} />

      <div className="card space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="text-sm font-semibold tracking-tight text-zinc-100">
              {filters.removed_only ? "Removed Leads" : "Results"}{" "}
              {total > 0 && <span className="tabular-nums text-zinc-400">· {total} businesses</span>}
            </div>
            {removedCount > 0 && (
              <div className="inline-flex items-center gap-1 rounded-full border border-[#FF9F0A]/30 bg-[#FF9F0A]/10 px-2.5 py-0.5 text-[11px] text-[#FFB340]">
                <button
                  type="button"
                  onClick={() => patch({ removed_only: !filters.removed_only })}
                  className="hover:underline"
                  title="Inspect removed leads"
                >
                  {filters.removed_only ? "← Back to Active" : `Removed (${removedCount})`}
                </button>
                <span className="opacity-40">·</span>
                <button type="button" onClick={restoreAllRemoved} className="inline-flex items-center gap-1 font-semibold hover:text-white">
                  <Icons.RotateCcw className="h-3 w-3" /> Restore
                </button>
              </div>
            )}
            <div className="segmented">
              {[
                ["cards", "Cards", Icons.Grid],
                ["table", "Table", Icons.Table],
                ["map", "Map", Icons.Map],
              ].map(([id, label, Icon]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setViewMode(id)}
                  className={`segmented-item inline-flex items-center gap-1.5 ${
                    viewMode === id ? "bg-white/[0.14] text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={openCompare} disabled={!jobId}>
              <Icons.Bell className="h-3.5 w-3.5" /> New since last scan
            </button>
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={openReport} disabled={!jobId}>
              <Icons.FileText className="h-3.5 w-3.5" /> Report
            </button>
            <button className="btn-ghost px-3 py-1.5 text-xs" onClick={rescore} disabled={!jobId || rescoring}>
              <Icons.Refresh className={`h-3.5 w-3.5 ${rescoring ? "animate-spin" : ""}`} />
              {rescoring ? "Re-scoring…" : "Re-score"}
            </button>
            <ExportMenu jobId={jobId} filters={filters} notify={notify} />
          </div>
        </div>

        {!jobId ? (
          <div className="py-14 text-center text-sm text-zinc-500">Start an extraction above to inspect live leads.</div>
        ) : loading && data.items.length === 0 ? (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="shimmer-bar h-52 rounded-2xl border border-white/[0.06] bg-white/[0.03]" />
            ))}
          </div>
        ) : data.items.length === 0 ? (
          <div className="py-14 text-center text-sm text-zinc-500">
            {isFiltered ? "No businesses match these filters." : "Waiting for first businesses…"}
          </div>
        ) : viewMode === "map" ? (
          <ResultsMap items={data.items} onOpen={setSelected} />
        ) : viewMode === "table" ? (
          <ResultsTable items={data.items} onOpen={setSelected} notify={notify} onRemove={softRemoveLead} highlightCids={highlightCids} />
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.items.map((r, idx) => (
              <BusinessCard
                key={r.cid}
                b={r}
                index={idx}
                onOpen={setSelected}
                notify={notify}
                onRemove={softRemoveLead}
                highlighted={highlightCids.includes(r.cid)}
              />
            ))}
          </div>
        )}

        {total > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.08] pt-3.5 text-xs text-zinc-400">
            <div className="tabular-nums">
              Showing {start}–{end} of {total}
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
                {[24, 48, 96].map((s) => (
                  <option key={s} value={s}>
                    {s} / page
                  </option>
                ))}
              </select>
              <div className="flex items-center gap-1">
                <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page <= 1} onClick={() => setPage(1)}>
                  «
                </button>
                <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                  ‹
                </button>
                {pages.map((p, i) =>
                  p === "…" ? (
                    <span key={i} className="px-1 text-zinc-600">
                      …
                    </span>
                  ) : (
                    <button
                      key={i}
                      className={`rounded-lg px-2.5 py-1 text-xs tabular-nums transition ${
                        p === page ? "bg-[#0A84FF] font-semibold text-white" : "btn-ghost"
                      }`}
                      onClick={() => setPage(p)}
                    >
                      {p}
                    </button>
                  )
                )}
                <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
                  ›
                </button>
                <button className="btn-ghost px-2.5 py-1 text-xs" disabled={page >= totalPages} onClick={() => setPage(totalPages)}>
                  »
                </button>
              </div>
            </div>
          </div>
        )}

        {selected && (
          <BusinessModal
            b={selected}
            jobId={jobId}
            onClose={() => setSelected(null)}
            onUpdated={() => setReloadKey((k) => k + 1)}
            notify={notify}
          />
        )}
        {compare && <ComparePanel data={compare} onClose={() => setCompare(null)} onOpen={setSelected} />}
        {report && <ReportModal data={report} onClose={() => setReport(null)} />}
      </div>
    </div>
  );
}

function FilterBar({ filters, patch, clearAll, savePreset, areas, countries = [] }) {
  const flags = [
    ["hot_only", "Hot leads only"],
    ["has_email", "Has email"],
    ["has_social", "Has social"],
    ["has_website", "Has website"],
    ["has_phone", "Has phone"],
    ["has_hours", "Has hours"],
    ["has_menu", "Has menu"],
    ["has_reviews", "Has reviews"],
  ];
  const [countryOpen, setCountryOpen] = useState(false);

  function toggleLoc(a) {
    const has = filters.location.includes(a);
    patch({ location: has ? filters.location.filter((x) => x !== a) : [...filters.location, a] });
  }

  function toggleCountry(c) {
    const has = filters.country.includes(c);
    patch({ country: has ? filters.country.filter((x) => x !== c) : [...filters.country, c] });
  }

  return (
    <div className="card space-y-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <div className="relative flex-1 min-w-[220px] max-w-xs">
          <Icons.Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-zinc-500" />
          <input
            className="input pl-9"
            placeholder="Search name, address, phone…"
            value={filters.q}
            onChange={(e) => patch({ q: e.target.value })}
          />
        </div>
        <select className="input h-[38px] w-auto" value={filters.min_rating} onChange={(e) => patch({ min_rating: e.target.value })}>
          <option value="">Any rating</option>
          <option value="3">3★+</option>
          <option value="3.5">3.5★+</option>
          <option value="4">4★+</option>
          <option value="4.5">4.5★+</option>
        </select>
        <input
          className="input h-[38px] w-28"
          type="number"
          min="0"
          placeholder="Min reviews"
          value={filters.min_reviews}
          onChange={(e) => patch({ min_reviews: e.target.value })}
        />
        <select className="input h-[38px] w-auto" value={filters.sort} onChange={(e) => patch({ sort: e.target.value })}>
          <option value="default">Sort: default</option>
          <option value="ai_desc">AI score: high → low</option>
          <option value="ai_asc">AI score: low → high</option>
          <option value="lead_desc">Lead score: high → low</option>
          <option value="lead_asc">Lead score: low → high</option>
          <option value="rating_desc">Rating: high → low</option>
          <option value="rating_asc">Rating: low → high</option>
          <option value="reviews_desc">Reviews: most → least</option>
        </select>
        <select
          className="input h-[38px] w-auto"
          value={filters.affordability || ""}
          onChange={(e) => patch({ affordability: e.target.value })}
          title="Filter by AI budget fit"
        >
          <option value="">Any affordability</option>
          <option value="High">AI Affordability: High</option>
          <option value="Medium">AI Affordability: Medium</option>
          <option value="Low">AI Affordability: Low</option>
        </select>

        <div className="relative">
          <button type="button" className="btn-ghost h-[38px] text-xs" onClick={() => setCountryOpen((o) => !o)}>
            <Icons.Globe className="h-3.5 w-3.5" />
            Country{filters.country.length ? ` (${filters.country.length})` : ""} ▾
          </button>
          {countryOpen && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setCountryOpen(false)} />
              <div className="animate-modal-enter apple-modal absolute left-0 z-30 mt-1.5 max-h-72 w-64 overflow-auto py-1.5 text-xs">
                {countries.length === 0 && <div className="px-3.5 py-2 text-zinc-500">No country data in this job</div>}
                {countries.map((c) => (
                  <label key={c.value} className="flex cursor-pointer items-center justify-between gap-2 px-3.5 py-1.5 hover:bg-white/[0.06]">
                    <span className="flex min-w-0 items-center gap-2">
                      <input
                        type="checkbox"
                        className="accent-[#0A84FF]"
                        checked={filters.country.includes(c.value)}
                        onChange={() => toggleCountry(c.value)}
                      />
                      <span className="truncate text-zinc-200">{c.value}</span>
                    </span>
                    <span className="shrink-0 tabular-nums text-zinc-500">({c.count})</span>
                  </label>
                ))}
              </div>
            </>
          )}
        </div>

        <button className="btn-ghost h-[38px] text-xs" onClick={clearAll}>
          Clear
        </button>
        <button className="btn-ghost h-[38px] text-xs" onClick={savePreset}>
          <Icons.Sparkles className="h-3.5 w-3.5 text-[#FF9F0A]" /> Save filter
        </button>
      </div>

      {areas.length > 0 && (
        <div>
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Area / locality</div>
          <div className="flex flex-wrap gap-1.5">
            {areas.map((a) => (
              <button
                key={a.value}
                onClick={() => toggleLoc(a.value)}
                className={`rounded-full px-3 py-1 text-xs transition-all duration-150 ${
                  filters.location.includes(a.value)
                    ? "bg-[#0A84FF] text-white shadow-sm"
                    : "border border-white/[0.07] bg-white/[0.04] text-zinc-300 hover:bg-white/[0.09]"
                }`}
              >
                {a.value} <span className="tabular-nums opacity-65">({a.count})</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-x-4 gap-y-2">
        {flags.map(([k, label]) => (
          <label key={k} className="flex cursor-pointer items-center gap-1.5 text-xs text-zinc-300 hover:text-white">
            <input
              type="checkbox"
              className="accent-[#0A84FF]"
              checked={filters[k]}
              onChange={(e) => patch({ [k]: e.target.checked })}
            />
            {label}
          </label>
        ))}
      </div>
    </div>
  );
}

function ExportMenu({ jobId, filters, notify }) {
  const [open, setOpen] = useState(false);
  const [crmOpen, setCrmOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  async function exp(fmt, crm) {
    setOpen(false);
    setCrmOpen(false);
    if (fmt === "sheets") {
      setExporting(true);
      try {
        const res = await api.exportSheets(jobId, filters);
        if (res?.url) {
          window.open(res.url, "_blank");
          if (notify) notify("Google Sheet created and opened", "success");
        } else {
          if (notify) notify(res?.error || "Google Sheets export failed", "error");
        }
      } catch (e) {
        if (notify) notify("Google Sheets export failed: " + (e?.message || e), "error");
      } finally {
        setExporting(false);
      }
      return;
    }
    const url = api.exportUrl(jobId, fmt, filters, crm);
    window.open(url, "_blank");
  }

  return (
    <div className="relative">
      <button className="btn-primary px-3.5 py-1.5 text-xs" onClick={() => setOpen((o) => !o)} disabled={!jobId || exporting}>
        <Icons.Download className="h-3.5 w-3.5" />
        {exporting ? "Exporting…" : "Export"}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-20" onClick={() => setOpen(false)} />
          <div className="animate-modal-enter apple-modal absolute right-0 z-30 mt-1.5 w-48 py-1.5 text-xs">
            {["csv", "xlsx", "json", "sheets"].map((f) => (
              <button
                key={f}
                className="block w-full px-3.5 py-2 text-left text-zinc-200 transition hover:bg-white/[0.08]"
                onClick={() => exp(f)}
              >
                {f === "sheets" ? "Google Sheets" : f.toUpperCase()}
              </button>
            ))}
            <div className="relative" onMouseEnter={() => setCrmOpen(true)} onMouseLeave={() => setCrmOpen(false)}>
              <button className="flex w-full items-center justify-between px-3.5 py-2 text-left text-zinc-200 transition hover:bg-white/[0.08]">
                <span>CRM Import</span>
                <span className="text-zinc-500">▸</span>
              </button>
              {crmOpen && (
                <div className="apple-modal absolute right-full top-0 mr-1 w-40 py-1.5">
                  {[
                    ["hubspot", "HubSpot"],
                    ["salesforce", "Salesforce"],
                    ["zoho", "Zoho"],
                  ].map(([k, label]) => (
                    <button
                      key={k}
                      className="block w-full px-3.5 py-2 text-left text-zinc-200 transition hover:bg-white/[0.08]"
                      onClick={() => exp("crm", k)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function ResultsTable({ items, onOpen, notify, onRemove, highlightCids = [] }) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-white/[0.07] bg-white/[0.02]">
      <table className="w-full text-left text-xs">
        <thead className="border-b border-white/[0.07] bg-white/[0.03] text-[11px] uppercase tracking-wider text-zinc-400">
          <tr>
            <th className="px-3.5 py-2.5">Business</th>
            <th className="px-3 py-2.5">Score / AI</th>
            <th className="px-3 py-2.5">Rating</th>
            <th className="px-3 py-2.5">Phone</th>
            <th className="px-3 py-2.5">Email</th>
            <th className="px-3 py-2.5">Website</th>
            <th className="px-3.5 py-2.5 text-right">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/[0.05]">
          {items.map((b) => {
            const emails = tryJson(b.emails, []);
            const email = b.email || emails[0] || "";
            const web = b.website ? (b.website.startsWith("http") ? b.website : "https://" + b.website) : null;
            const lc = b.lead_grade ? leadColor(b.lead_grade) : null;
            const ac = b.ai_score != null || b.ai_verdict ? aiColor(b.ai_verdict, b.ai_score) : null;
            const isHi = highlightCids.includes(b.cid);
            return (
              <tr
                key={b.cid}
                onClick={() => onOpen(b)}
                className={`cursor-pointer transition hover:bg-white/[0.04] ${isHi ? "bg-[#30D158]/[0.07]" : ""}`}
              >
                <td className="px-3.5 py-2.5">
                  <div className="max-w-[220px] truncate font-medium text-zinc-100">{b.name}</div>
                  <div className="max-w-[220px] truncate text-[11px] text-zinc-500">{b.category || b.full_address}</div>
                </td>
                <td className="px-3 py-2.5">
                  <div className="flex flex-wrap items-center gap-1">
                    {lc ? (
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${lc.bg} ${lc.text} ${lc.ring}`}>
                        {b.lead_score} · {b.lead_grade}
                      </span>
                    ) : (
                      "—"
                    )}
                    {ac && (
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${ac.bg} ${ac.text} ${ac.ring}`}>
                        AI {b.ai_score ?? "—"}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2.5 tabular-nums text-zinc-300">
                  {b.rating != null ? `★ ${b.rating} (${b.reviews_count ?? 0})` : "—"}
                </td>
                <td className="px-3 py-2.5 tabular-nums text-zinc-300" onClick={(e) => e.stopPropagation()}>
                  {b.phone ? (
                    <span className="inline-flex items-center gap-1">
                      <span>{b.phone}</span>
                      <CopyButton text={b.phone} onCopied={() => notify && notify("Phone copied", "success")} />
                    </span>
                  ) : (
                    <span className="text-zinc-600">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-zinc-300" onClick={(e) => e.stopPropagation()}>
                  {email ? (
                    <span className="inline-flex max-w-[200px] items-center gap-1">
                      <span className="truncate text-[#409CFF]">{email}</span>
                      <CopyButton text={email} onCopied={() => notify && notify("Email copied", "success")} />
                    </span>
                  ) : (
                    <span className="text-zinc-600">—</span>
                  )}
                </td>
                <td className="px-3 py-2.5" onClick={(e) => e.stopPropagation()}>
                  {web ? (
                    <a href={web} target="_blank" rel="noreferrer" className="text-[#409CFF] hover:underline">
                      Visit
                    </a>
                  ) : (
                    <span className="text-zinc-600">—</span>
                  )}
                </td>
                <td className="px-3.5 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                  <div className="inline-flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => onOpen(b)}
                      className="btn-ghost px-2.5 py-1 text-[11px]"
                    >
                      Details
                    </button>
                    {onRemove && (
                      <button
                        type="button"
                        onClick={() => onRemove(b.cid)}
                        title="Hide from active results"
                        className="rounded-lg p-1 text-zinc-500 transition hover:bg-[#FF453A]/15 hover:text-[#FF6961]"
                      >
                        <Icons.Trash className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function BusinessCard({ b, index = 0, onOpen, notify, onRemove, highlighted = false }) {
  const web = b.website ? (b.website.startsWith("http") ? b.website : "https://" + b.website) : null;
  const [showReviews, setShowReviews] = useState(false);
  const hoursObj = tryJson(b.hours, null);
  const emails = tryJson(b.emails, []);
  const socials = tryJson(b.socials, []);
  const reviews = tryJson(b.reviews, []);
  const price = b.price_level ? "$".repeat(b.price_level) : b.price_desc || null;
  const hoursText = hoursObj
    ? Object.entries(hoursObj)
        .slice(0, 3)
        .map(([d, r]) => `${d}: ${r.join(", ")}`)
        .join(" · ")
    : null;
  const chips = [b.service_options, b.popular_for, b.amenities, b.highlights].filter(Boolean);
  const lc = b.lead_grade ? leadColor(b.lead_grade) : null;
  const ac = b.ai_score != null || b.ai_verdict ? aiColor(b.ai_verdict, b.ai_score) : null;
  const delay = Math.min(index * 22, 240);

  return (
    <div
      style={{ animationDelay: `${delay}ms` }}
      className={`animate-card-enter group flex flex-col overflow-hidden rounded-[20px] border bg-white/[0.03] transition-all duration-300 ease-spring hover:-translate-y-0.5 hover:border-[#0A84FF]/40 hover:bg-white/[0.05] hover:shadow-[0_18px_40px_-20px_rgba(10,132,255,0.28)] ${
        highlighted ? "border-[#30D158]/50 ring-1 ring-[#30D158]/30" : "border-white/[0.08]"
      }`}
    >
      <div className="flex items-start gap-3 p-4">
        {b.thumbnail ? (
          <img
            src={`/api/thumb?u=${encodeURIComponent(b.thumbnail)}`}
            alt=""
            className="h-14 w-14 shrink-0 rounded-xl object-cover ring-1 ring-white/10"
            loading="lazy"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <div className="grid h-14 w-14 shrink-0 place-items-center rounded-xl bg-white/[0.05] text-zinc-400 ring-1 ring-white/10">
            <Icons.Building className="h-6 w-6" />
          </div>
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="truncate text-sm font-semibold tracking-tight text-zinc-100" title={b.name}>
              {b.name || "Unnamed business"}
            </h3>
            <div className="flex shrink-0 flex-wrap items-center justify-end gap-1">
              {ac ? (
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${ac.bg} ${ac.text} ${ac.ring}`}>
                  AI {b.ai_score ?? "—"}
                </span>
              ) : null}
              {lc ? (
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold tabular-nums ${lc.bg} ${lc.text} ${lc.ring}`}>
                  {b.lead_score} · {b.lead_grade}
                </span>
              ) : null}
              {b.is_ad ? (
                <span className="rounded-full bg-[#FF9F0A]/15 px-2 py-0.5 text-[10px] font-medium text-[#FFB340]">Ad</span>
              ) : null}
              {b.closed_status ? (
                <span className="rounded-full bg-[#FF453A]/15 px-2 py-0.5 text-[10px] font-medium text-[#FF6961]">{b.closed_status}</span>
              ) : null}
            </div>
          </div>
          {b.category && (
            <div className="mt-0.5 truncate text-xs text-[#64D2FF]" title={b.category}>
              {b.category}
            </div>
          )}
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <StarRating value={b.rating} />
            {b.rating != null && <span className="text-xs font-medium tabular-nums text-zinc-200">{b.rating}</span>}
            {b.reviews_count != null && <span className="text-[11px] tabular-nums text-zinc-500">({b.reviews_count})</span>}
            {price && <span className="rounded-full bg-[#30D158]/15 px-1.5 py-0.5 text-[10px] font-medium text-[#30D158]">{price}</span>}
          </div>
        </div>
      </div>

      <div className="space-y-1.5 px-4 pb-3 text-xs text-zinc-300">
        {(b.full_address || b.street || b.city_state_zip) && (
          <div className="flex items-start gap-2">
            <Icons.MapPin className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-500" />
            <span className="min-w-0 break-words text-zinc-300">
              {b.full_address || [b.street, b.city_state_zip].filter(Boolean).join(", ")}
            </span>
          </div>
        )}
        {b.phone && (
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Icons.Phone className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
              <span className="tabular-nums">{b.phone}</span>
            </div>
            <CopyButton text={b.phone} onCopied={() => notify && notify("Phone copied", "success")} />
          </div>
        )}
        {hoursText && (
          <div className="flex items-start gap-2 text-zinc-400">
            <Icons.Clock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-zinc-500" />
            <span className="line-clamp-2">{hoursText}</span>
          </div>
        )}
        {b.menu_url && (
          <div className="flex items-center gap-2">
            <Icons.ExternalLink className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
            <a href={b.menu_url} target="_blank" rel="noreferrer" className="text-[#409CFF] hover:underline">
              Google Menu
            </a>
          </div>
        )}
      </div>

      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-4 pb-3">
          {chips.map((c, i) => (
            <span key={i} className="rounded-full bg-white/[0.05] px-2.5 py-0.5 text-[11px] text-zinc-300">
              {c.length > 56 ? c.slice(0, 56) + "…" : c}
            </span>
          ))}
        </div>
      )}

      {(emails.length > 0 || socials.length > 0) && (
        <div className="space-y-1.5 px-4 pb-3 text-xs">
          {emails.slice(0, 2).map((e, i) => (
            <div key={"e" + i} className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <Icons.Mail className="h-3.5 w-3.5 shrink-0 text-zinc-500" />
                <a href={`mailto:${e}`} className="truncate text-[#409CFF] hover:underline">
                  {e}
                </a>
              </div>
              <CopyButton text={e} onCopied={() => notify && notify("Email copied", "success")} />
            </div>
          ))}
          {socials.length > 0 && (
            <div className="flex flex-wrap gap-1.5 pt-0.5">
              {socials.map((s, i) => {
                const net = s.includes("facebook")
                  ? "Facebook"
                  : s.includes("instagram")
                  ? "Instagram"
                  : s.includes("linkedin")
                  ? "LinkedIn"
                  : s.includes("twitter") || s.includes("x.com")
                  ? "X"
                  : s.includes("youtube")
                  ? "YouTube"
                  : s.includes("tiktok")
                  ? "TikTok"
                  : "Social";
                return (
                  <a
                    key={"s" + i}
                    href={s}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-full border border-white/[0.07] bg-white/[0.04] px-2 py-0.5 text-[11px] text-[#409CFF] hover:bg-white/[0.09]"
                  >
                    {net}
                  </a>
                );
              })}
            </div>
          )}
        </div>
      )}

      {reviews.length > 0 && (
        <div className="border-t border-white/[0.06] px-4 py-2.5">
          <button
            onClick={() => setShowReviews((v) => !v)}
            className="text-xs font-medium text-zinc-300 transition hover:text-[#409CFF]"
          >
            {showReviews ? "▾ Hide" : "▸"} {reviews.length} review{reviews.length > 1 ? "s" : ""}
          </button>
          {showReviews && (
            <div className="mt-2 space-y-2">
              {reviews.slice(0, 5).map((rv, i) => (
                <div key={i} className="rounded-xl bg-white/[0.03] p-2.5 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-zinc-200">{rv.author || "Anonymous"}</span>
                    <span className="text-[#FF9F0A]">{"★".repeat(rv.rating || 0)}{"☆".repeat(5 - (rv.rating || 0))}</span>
                  </div>
                  {rv.time && <div className="text-[11px] text-zinc-500">{rv.time}</div>}
                  {rv.text && <p className="mt-1 text-zinc-300">{rv.text}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {b.ai_why && (
        <div className="mx-4 mb-3 rounded-xl border border-[#0A84FF]/20 bg-[#0A84FF]/[0.05] px-3 py-2 text-[11px] text-zinc-300">
          <div className="mb-0.5 flex flex-wrap items-center gap-1.5 font-semibold text-[#64D2FF]">
            <span>{b.ai_verdict || "AI Fit"}</span>
            {b.ai_affordability && <span className="text-zinc-400">· Budget: {b.ai_affordability}</span>}
            {b.ai_owner && <span className="text-[#30D158]">· {b.ai_owner}</span>}
          </div>
          <div className="line-clamp-2 leading-relaxed text-zinc-300">{b.ai_why}</div>
        </div>
      )}

      <div className="mt-auto flex border-t border-white/[0.06] text-xs font-medium">
        <button
          onClick={() => onOpen && onOpen(b)}
          className="flex-1 py-2.5 text-center text-zinc-300 transition hover:bg-white/[0.06] hover:text-white"
        >
          Details
        </button>
        <a
          href={mapsLink(b)}
          target="_blank"
          rel="noreferrer"
          className="flex-1 border-l border-white/[0.06] py-2.5 text-center text-zinc-300 transition hover:bg-white/[0.06] hover:text-white"
        >
          Maps
        </a>
        {web && (
          <a
            href={web}
            target="_blank"
            rel="noreferrer"
            className="flex-1 border-l border-white/[0.06] py-2.5 text-center text-zinc-300 transition hover:bg-white/[0.06] hover:text-white"
          >
            Website
          </a>
        )}
        {onRemove && (
          <button
            type="button"
            onClick={() => onRemove(b.cid)}
            title="Hide from active results"
            className="border-l border-white/[0.06] px-3 py-2.5 text-zinc-500 transition hover:bg-[#FF453A]/15 hover:text-[#FF6961]"
          >
            <Icons.Trash className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}
