import React, { useCallback, useEffect, useRef, useState } from "react";
import { api, connectMissionWS } from "../api.js";
import { aiColor, CopyButton, Icons, MarkdownView, StatusBadge, tryJson } from "./ui.jsx";
import ResultsView from "./ResultsView.jsx";

function formatToolLabel(tool, args = {}) {
  switch (tool) {
    case "geocode_place":
      return `Looking up coordinates for "${args.place_name || "location"}"`;
    case "start_keyword_search":
      return `Searching "${args.query || ""}" in ${args.location || "target area"}`;
    case "start_area_scan":
      return `Starting area grid scan for "${args.query || ""}"`;
    case "wait_for_job":
      return "Waiting for extraction & website enrichment to finish";
    case "list_jobs":
      return "Checking existing scraped datasets";
    case "compare_jobs":
      return "Comparing against previous scan for changes";
    case "query_results":
      return "Querying & filtering matching leads";
    case "read_reviews":
      return "Reading customer reviews & owner replies";
    case "inspect_website":
      return "Reading website content, tech stack & contact details";
    case "update_lead_intelligence":
      return `Scoring & writing AI insights for ${(args.updates || []).length || 1} lead(s)`;
    case "remove_leads":
      return `Filtering out ${(args.cids || []).length || 0} non-matching lead(s) (${args.reason || "clean"})`;
    case "restore_leads":
      return "Restoring removed leads";
    case "apply_table_view":
      return `Updating table view (${args.sort || "sorted"})`;
    case "rescore_job":
      return `Re-scoring leads (${args.preset || "balanced"})`;
    case "save_offer_profile":
      return `Saving offer profile "${args.name || ""}"`;
    case "save_to_shortlist":
      return `Saving ${(args.cids || []).length || 0} lead(s) to shortlist "${args.list_name || ""}"`;
    case "list_shortlists":
      return "Checking saved shortlists";
    case "export_leads":
      return `Preparing ${String(args.crm || args.format || "CSV").toUpperCase()} download`;
    case "check_health":
      return "Checking plan limits, proxy pool & session health";
    default:
      return tool;
  }
}

export default function CopilotView({ notify, onOpenSettings, initialJobId = "" }) {
  const [aiCfg, setAiCfg] = useState(null);
  const [offers, setOffers] = useState([]);
  const [jobsList, setJobsList] = useState([]);
  const [missions, setMissions] = useState([]);
  const [shortlists, setShortlists] = useState([]);

  const [modeId, setModeId] = useState("web_seo");
  const [offerId, setOfferId] = useState("");
  const [attachedJobId, setAttachedJobId] = useState(initialJobId || "");
  const [modelOverride, setModelOverride] = useState("");
  const [availableModels, setAvailableModels] = useState([]);

  const [activeMission, setActiveMission] = useState(null);
  const [messages, setMessages] = useState([]);
  const [liveSteps, setLiveSteps] = useState([]);
  const [exportsReady, setExportsReady] = useState([]);
  const [prompt, setPrompt] = useState("");
  const [sending, setSending] = useState(false);
  const [running, setRunning] = useState(false);
  const [usageStats, setUsageStats] = useState(null);

  const [rightTab, setRightTab] = useState("leads"); // leads | shortlists | history | logs
  const [paneLayout, setPaneLayout] = useState("split"); // split | chat | workspace
  const [missionLog, setMissionLog] = useState({ tool_calls: [], log_lines: [], log_file: "" });
  const [activeJobId, setActiveJobId] = useState(initialJobId || "");
  const [liveView, setLiveView] = useState(null);
  const [resultsRefresh, setResultsRefresh] = useState(0);

  const [selectedListId, setSelectedListId] = useState("");
  const [selectedList, setSelectedList] = useState(null);
  const [newListName, setNewListName] = useState("");

  const wsRef = useRef(null);
  const chatEndRef = useRef(null);
  const lastRefreshRef = useRef(0);

  const loadMeta = useCallback(() => {
    api.aiConfig().then((d) => {
      setAiCfg(d);
      const prov = d?.provider || "gemini";
      const curList = d?.curated_models?.[prov] || [];
      if (curList.length) setAvailableModels(curList);
      if (d?.configured) {
        api.aiModels({ provider: prov }).then((m) => {
          if (m?.models?.length) setAvailableModels(m.models);
        }).catch(() => {});
      }
    }).catch(() => {});
    api.listOffers().then((d) => setOffers(d?.offers || [])).catch(() => {});
    api.listJobs(30, 0).then((d) => setJobsList(d?.jobs || [])).catch(() => {});
    api.listMissions(40).then((d) => setMissions(d?.missions || [])).catch(() => {});
    api.listShortlists().then((d) => {
      const lists = d?.lists || [];
      setShortlists(lists);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    loadMeta();
  }, [loadMeta]);

  useEffect(() => {
    if (initialJobId && !activeJobId) {
      setActiveJobId(initialJobId);
      setAttachedJobId(initialJobId);
    }
  }, [initialJobId, activeJobId]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, liveSteps, running]);

  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  const loadShortlistDetail = useCallback((lid) => {
    if (!lid) {
      setSelectedList(null);
      return;
    }
    api.getShortlist(lid).then((d) => setSelectedList(d?.list || null)).catch(() => {});
  }, []);

  useEffect(() => {
    if (selectedListId) loadShortlistDetail(selectedListId);
  }, [selectedListId, loadShortlistDetail]);

  const attachWS = useCallback((missionId) => {
    if (wsRef.current) wsRef.current.close();
    wsRef.current = connectMissionWS(missionId, (ev) => {
      if (!ev || ev.type === "ws_close") return;
      if (ev.type === "status") {
        setRunning(ev.status === "running");
      } else if (ev.type === "step") {
        setLiveSteps((s) => [
          ...s,
          { id: `step-${ev.step}-${Date.now()}`, kind: "step", text: `Step ${ev.step}: ${ev.message}`, status: "info" },
        ]);
        if (ev.usage) setUsageStats(ev.usage);
      } else if (ev.type === "tool_call") {
        setLiveSteps((s) => [
          ...s,
          {
            id: ev.call_id || `call-${Date.now()}-${Math.random()}`,
            call_id: ev.call_id,
            kind: "tool",
            tool: ev.tool,
            args: ev.args || {},
            text: formatToolLabel(ev.tool, ev.args),
            status: "running",
          },
        ]);
      } else if (ev.type === "tool_result") {
        setLiveSteps((s) => {
          const idx = ev.call_id ? s.findIndex((x) => x.call_id === ev.call_id) : -1;
          const isErr = Boolean(ev.result?.error);
          if (idx >= 0) {
            const copy = [...s];
            copy[idx] = {
              ...copy[idx],
              status: isErr ? "error" : "ok",
              summary: ev.summary || "",
              duration_ms: ev.duration_ms,
              result: ev.result,
            };
            return copy;
          }
          return [
            ...s,
            {
              id: ev.call_id || `res-${Date.now()}`,
              kind: "tool",
              tool: ev.tool,
              args: ev.args || {},
              text: formatToolLabel(ev.tool, ev.args),
              status: isErr ? "error" : "ok",
              summary: ev.summary || "",
              duration_ms: ev.duration_ms,
              result: ev.result,
            },
          ];
        });
      } else if (ev.type === "job_started") {
        setActiveJobId(ev.job_id);
        setAttachedJobId(ev.job_id);
        setRightTab("leads");
        setLiveSteps((s) => [...s.slice(-40), { kind: "info", text: `Extraction started (${ev.query})` }]);
        api.listJobs(30, 0).then((d) => setJobsList(d?.jobs || [])).catch(() => {});
      } else if (ev.type === "job_progress") {
        const now = Date.now();
        if (now - lastRefreshRef.current >= 1500) {
          lastRefreshRef.current = now;
          setResultsRefresh((n) => n + 1);
        }
      } else if (ev.type === "ui_view") {
        if (ev.job_id) setActiveJobId(ev.job_id);
        if (ev.view) setLiveView({ ...ev.view, _ts: Date.now() });
        setRightTab("leads");
      } else if (ev.type === "ui_table_changed") {
        if (ev.job_id) setActiveJobId(ev.job_id);
        setResultsRefresh((n) => n + 1);
      } else if (ev.type === "ui_shortlist_updated") {
        api.listShortlists().then((d) => {
          setShortlists(d?.lists || []);
          if (ev.list_id) {
            setSelectedListId(ev.list_id);
            loadShortlistDetail(ev.list_id);
          }
        }).catch(() => {});
        if (notify) notify(`Saved ${ev.added || 0} lead(s) to "${ev.name}"`, "success");
      } else if (ev.type === "ui_offers_updated") {
        api.listOffers().then((d) => setOffers(d?.offers || [])).catch(() => {});
      } else if (ev.type === "ui_export_ready") {
        setExportsReady((e) => [...e.slice(-5), ev]);
      } else if (ev.type === "assistant_message") {
        setMessages((m) => [...m, { id: "live-" + Date.now(), role: "assistant", content: ev.content }]);
        if (ev.job_id) setActiveJobId(ev.job_id);
        setResultsRefresh((n) => n + 1);
      } else if (ev.type === "done") {
        setRunning(false);
        if (ev.job_id) setActiveJobId(ev.job_id);
        if (ev.last_view) setLiveView({ ...ev.last_view, _ts: Date.now() });
        if (ev.usage) setUsageStats(ev.usage);
        setActiveMission((prev) =>
          prev ? { ...prev, status: ev.status || "completed", job_id: ev.job_id || prev.job_id } : prev
        );
        setResultsRefresh((n) => n + 1);
        api.getMission(missionId).then((d) => {
          if (d?.messages) setMessages(d.messages);
          if (d?.mission) setActiveMission(d.mission);
        }).catch(() => {});
        api.aiMissionLog(missionId).then(setMissionLog).catch(() => {});
        api.listMissions(40).then((d) => setMissions(d?.missions || [])).catch(() => {});
      } else if (ev.type === "error") {
        setRunning(false);
        setActiveMission((prev) => (prev ? { ...prev, status: "failed" } : prev));
        setMessages((m) => [...m, { id: "err-" + Date.now(), role: "assistant", content: `Error: ${ev.message}` }]);
        if (notify) notify(ev.message, "error");
        api.listMissions(40).then((d) => setMissions(d?.missions || [])).catch(() => {});
      }
    });
  }, [notify, loadShortlistDetail]);

  async function openMission(missionId) {
    try {
      const d = await api.getMission(missionId);
      if (!d?.mission) return;
      setActiveMission(d.mission);
      setModeId(d.mission.mode_id || "custom");
      setOfferId(d.mission.offer_id || "");
      setModelOverride(d.mission.model || "");
      if (d.mission.job_id) {
        setActiveJobId(d.mission.job_id);
        setAttachedJobId(d.mission.job_id);
      }
      setMessages(d.messages || []);
      setLiveSteps([]);
      setExportsReady([]);
      setUsageStats(null);
      api.aiMissionLog(missionId).then(setMissionLog).catch(() => {});
      setRunning(d.mission.status === "running");
      if (d.mission.status === "running") attachWS(d.mission.id);
    } catch {}
  }

  function startNewMission() {
    if (wsRef.current) wsRef.current.close();
    setActiveMission(null);
    setMessages([]);
    setLiveSteps([]);
    setExportsReady([]);
    setUsageStats(null);
    setMissionLog({ tool_calls: [], log_lines: [], log_file: "" });
    setRunning(false);
  }

  async function submitPrompt(e, customText) {
    e && e.preventDefault();
    const text = (customText !== undefined ? customText : prompt).trim();
    if (!text || sending || running) return;
    if (!aiCfg?.configured) {
      if (notify) notify("Add an AI API key in Settings → AI Engine first", "warning");
      return;
    }
    setSending(true);
    setPrompt("");
    setLiveSteps([]);
    setMessages((m) => [...m, { id: "u-" + Date.now(), role: "user", content: text }]);
    try {
      if (!activeMission) {
        const res = await api.createMission({
          goal: text,
          mode_id: modeId,
          offer_id: offerId,
          job_id: attachedJobId,
          model: modelOverride,
        });
        if (res?.error) {
          if (notify) notify(res.error, "error");
          setMessages((m) => m.slice(0, -1));
          return;
        }
        setActiveMission(res.mission);
        setRunning(true);
        attachWS(res.mission.id);
        api.listMissions(40).then((d) => setMissions(d?.missions || [])).catch(() => {});
      } else {
        const res = await api.sendMissionMessage(activeMission.id, {
          message: text,
          mode_id: modeId,
          offer_id: offerId,
          job_id: attachedJobId || undefined,
          model: modelOverride || undefined,
        });
        if (res?.error) {
          if (notify) notify(res.error, "error");
          return;
        }
        setActiveMission(res.mission);
        setRunning(true);
        attachWS(activeMission.id);
      }
    } catch (err) {
      if (notify) notify(String(err), "error");
    } finally {
      setSending(false);
    }
  }

  async function stopMission() {
    if (!activeMission) return;
    try {
      await api.cancelMission(activeMission.id);
      setRunning(false);
      if (notify) notify("Stopping AI Autopilot…", "warning");
    } catch {}
  }

  async function createNewList(e) {
    e.preventDefault();
    if (!newListName.trim()) return;
    try {
      const d = await api.createShortlist({ name: newListName.trim() });
      setNewListName("");
      const refreshed = await api.listShortlists();
      setShortlists(refreshed?.lists || []);
      if (d?.list?.id) setSelectedListId(d.list.id);
      if (notify) notify(`Created shortlist "${d?.list?.name}"`, "success");
    } catch {}
  }

  async function removeList(id) {
    if (!window.confirm("Delete this saved shortlist?")) return;
    await api.deleteShortlist(id);
    if (selectedListId === id) {
      setSelectedListId("");
      setSelectedList(null);
    }
    api.listShortlists().then((d) => setShortlists(d?.lists || [])).catch(() => {});
  }

  async function patchListItem(itemId, fields) {
    if (!selectedListId) return;
    await api.updateShortlistItem(selectedListId, itemId, fields);
    loadShortlistDetail(selectedListId);
  }

  async function removeListItem(itemId) {
    if (!selectedListId) return;
    await api.deleteShortlistItem(selectedListId, itemId);
    loadShortlistDetail(selectedListId);
    api.listShortlists().then((d) => setShortlists(d?.lists || [])).catch(() => {});
  }

  const visibleMessages = messages.filter((m) => m.role === "user" || m.role === "assistant" || m.role === "tool");
  const starterMissions = aiCfg?.starter_missions || [];
  const modesList = aiCfg?.modes || [];

  return (
    <div className="animate-view-enter flex h-full flex-col gap-4 p-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight text-zinc-100">
            <Icons.Sparkles className="h-5 w-5 text-[#64D2FF]" />
            AI Copilot
          </h1>
          <p className="text-xs text-zinc-400">
            Describe your ideal customer &amp; budget — AI searches Maps, reads sites &amp; reviews, cleans the table, and ranks winners.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="segmented">
            {[
              ["split", "Split"],
              ["chat", "Expand Chat"],
              ["workspace", "Expand Table"],
            ].map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setPaneLayout(id)}
                className={`segmented-item text-[11px] ${
                  paneLayout === id ? "bg-white/[0.14] text-white" : "text-zinc-400 hover:text-zinc-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          {aiCfg?.configured ? (
            <span className="rounded-full border border-[#30D158]/30 bg-[#30D158]/10 px-3 py-1 text-[11px] font-medium text-[#30D158]">
              ● {aiCfg.provider_models?.[aiCfg.provider]?.label || aiCfg.provider} · {modelOverride || aiCfg.selected_model || aiCfg.tier}
            </span>
          ) : (
            <button onClick={onOpenSettings} className="btn-primary px-3.5 py-1.5 text-xs">
              Setup AI Key in Settings →
            </button>
          )}
          <button onClick={startNewMission} className="btn-ghost px-3 py-1.5 text-xs">
            + New Mission
          </button>
        </div>
      </div>

      {!aiCfg?.configured && aiCfg !== null && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[#FF9F0A]/30 bg-[#FF9F0A]/10 px-4 py-3 text-xs text-zinc-200">
          <div>
            <strong className="text-[#FFB340]">AI Key Not Configured (Optional):</strong> All normal Google Maps extraction, enrichment, and exports still work normally. Add your own Gemini, Claude, ChatGPT, or Ollama key to let AI take the wheel.
          </div>
          <button onClick={onOpenSettings} className="btn-primary px-3 py-1.5 text-xs">
            Configure AI Engine
          </button>
        </div>
      )}

      {/* Adaptive Split / Focus Workspace */}
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-12">
        {/* Left: Chat + Timeline */}
        {paneLayout !== "workspace" && (
          <div className={`card flex min-h-[540px] flex-col gap-3 ${paneLayout === "chat" ? "lg:col-span-12" : "lg:col-span-5"}`}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Copilot Chat {activeMission?.status ? `· ${activeMission.status}` : ""}
              </span>
              <button
                type="button"
                onClick={() => setPaneLayout(paneLayout === "chat" ? "split" : "chat")}
                title={paneLayout === "chat" ? "Restore split view" : "Expand chat full width"}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-zinc-400 transition hover:bg-white/[0.07] hover:text-zinc-100"
              >
                {paneLayout === "chat" ? <Icons.Minimize className="h-3.5 w-3.5" /> : <Icons.Maximize className="h-3.5 w-3.5" />}
                <span>{paneLayout === "chat" ? "Split View" : "Expand"}</span>
              </button>
            </div>
            {/* Controls bar */}
          <div className="grid gap-2 border-b border-white/[0.07] pb-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Mode</label>
              <select className="input h-8 py-0 text-xs" value={modeId} onChange={(e) => setModeId(e.target.value)}>
                {(modesList.length ? modesList : [
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
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Model (Small → Big)</label>
              <select
                className="input h-8 py-0 text-xs"
                value={modelOverride}
                onChange={(e) => setModelOverride(e.target.value)}
              >
                <option value="">Default ({aiCfg?.selected_model || "auto"})</option>
                {[
                  ["small", "Small · Fast"],
                  ["balanced", "Balanced"],
                  ["large", "Big · Powerful"],
                ].map(([tKey, tLabel]) => {
                  const grp = availableModels.filter((m) => m.tier === tKey);
                  if (!grp.length) return null;
                  return (
                    <optgroup key={tKey} label={tLabel}>
                      {grp.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name !== m.id ? `${m.name} (${m.id})` : m.id}
                        </option>
                      ))}
                    </optgroup>
                  );
                })}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Saved Offer</label>
              <select className="input h-8 py-0 text-xs" value={offerId} onChange={(e) => setOfferId(e.target.value)}>
                <option value="">None</option>
                {offers.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Dataset</label>
              <select
                className="input h-8 py-0 text-xs"
                value={attachedJobId}
                onChange={(e) => {
                  setAttachedJobId(e.target.value);
                  if (e.target.value) setActiveJobId(e.target.value);
                }}
              >
                <option value="">Auto / Search New</option>
                {jobsList.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.query} ({j.scraped})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Messages Feed */}
          <div className="flex-1 space-y-3 overflow-y-auto pr-1 text-xs">
            {visibleMessages.length === 0 && (
              <div className="space-y-3 py-4">
                <div className="text-center text-zinc-400">
                  Tell AI Copilot who your ideal paying clients are and what you sell.
                </div>
                {starterMissions.length > 0 && (
                  <div className="space-y-2">
                    <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                      Quick Starter Missions
                    </div>
                    {starterMissions.map((sm) => (
                      <button
                        key={sm.id}
                        type="button"
                        onClick={() => {
                          setModeId(sm.mode || "custom");
                          setPrompt(sm.prompt);
                        }}
                        className="block w-full rounded-2xl border border-white/[0.08] bg-white/[0.03] p-3 text-left transition hover:border-[#0A84FF]/40 hover:bg-white/[0.06]"
                      >
                        <div className="font-semibold text-zinc-100">{sm.title}</div>
                        <div className="mt-1 line-clamp-2 text-[11px] text-zinc-400">{sm.prompt}</div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {visibleMessages.map((m, idx) => {
              if (m.role === "user") {
                return (
                  <div key={m.id || idx} className="flex justify-end">
                    <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-[#0A84FF] px-3.5 py-2.5 text-white shadow-sm">
                      <div className="whitespace-pre-wrap leading-relaxed">{m.content}</div>
                    </div>
                  </div>
                );
              }
              if (m.role === "tool") {
                const parsedArgs = tryJson(m.tool_args, {});
                const parsedRes = tryJson(m.tool_result, {});
                const meta = parsedRes?._meta || {};
                const isErr = Boolean(parsedRes?.error);
                const summaryTxt = m.content || meta.summary || "";
                return (
                  <details key={m.id || idx} className="group rounded-xl border border-white/[0.06] bg-white/[0.02] px-2.5 py-1.5 text-[11px] text-zinc-400">
                    <summary className="flex cursor-pointer list-none items-center justify-between gap-2">
                      <span className="flex min-w-0 items-center gap-2">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${isErr ? "bg-[#FF453A]" : "bg-[#30D158]"}`} />
                        <code className="shrink-0 rounded bg-white/[0.06] px-1.5 py-0.5 text-[10px] text-[#64D2FF]">{m.tool_name}</code>
                        <span className="truncate text-zinc-300">{formatToolLabel(m.tool_name, parsedArgs)}</span>
                      </span>
                      <span className="flex shrink-0 items-center gap-1.5 text-[10px] text-zinc-500">
                        {summaryTxt && <span className={`max-w-[140px] truncate ${isErr ? "text-[#FF6961]" : "text-zinc-400"}`}>{summaryTxt}</span>}
                        {meta.duration_ms != null && <span className="tabular-nums">{meta.duration_ms}ms</span>}
                      </span>
                    </summary>
                    <div className="mt-2 space-y-1.5 border-t border-white/[0.06] pt-2 text-[10px] font-mono">
                      <div>
                        <div className="text-zinc-500">Arguments:</div>
                        <pre className="mt-0.5 max-h-28 overflow-auto rounded bg-black/40 p-1.5 text-zinc-300">{JSON.stringify(parsedArgs, null, 2)}</pre>
                      </div>
                      <div>
                        <div className="text-zinc-500">Result:</div>
                        <pre className="mt-0.5 max-h-36 overflow-auto rounded bg-black/40 p-1.5 text-zinc-300">{JSON.stringify(parsedRes, null, 2)}</pre>
                      </div>
                    </div>
                  </details>
                );
              }
              return (
                <div key={m.id || idx} className="flex justify-start">
                  <div className="max-w-[95%] rounded-2xl rounded-bl-sm border border-white/[0.08] bg-white/[0.04] px-3.5 py-2.5 text-zinc-200">
                    <MarkdownView text={m.content} />
                  </div>
                </div>
              );
            })}

            {liveSteps.length > 0 && running && (
              <div className="space-y-1.5 rounded-2xl border border-[#0A84FF]/25 bg-black/40 p-3 text-[11px] text-zinc-300">
                <div className="mb-1 flex items-center justify-between gap-2 font-semibold text-[#64D2FF]">
                  <span className="flex items-center gap-2">
                    <span className="h-2 w-2 animate-ping rounded-full bg-[#0A84FF]" />
                    Autopilot Working…
                  </span>
                  <span className="text-[10px] text-zinc-500 tabular-nums">{liveSteps.length} event(s)</span>
                </div>
                <div className="max-h-56 space-y-1 overflow-y-auto pr-1">
                  {liveSteps.map((s) => (
                    <details key={s.id} className="rounded-lg bg-white/[0.03] px-2 py-1">
                      <summary className="flex cursor-pointer list-none items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-2">
                          <span
                            className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                              s.status === "error"
                                ? "bg-[#FF453A]"
                                : s.status === "ok"
                                ? "bg-[#30D158]"
                                : s.status === "running"
                                ? "animate-pulse bg-[#FF9F0A]"
                                : "bg-[#64D2FF]"
                            }`}
                          />
                          {s.tool && (
                            <code className="shrink-0 rounded bg-white/[0.07] px-1 py-0.5 text-[10px] text-[#64D2FF]">{s.tool}</code>
                          )}
                          <span className="truncate">{s.text}</span>
                        </span>
                        <span className="flex shrink-0 items-center gap-1.5 text-[10px] text-zinc-500">
                          {s.summary && <span className={`max-w-[140px] truncate ${s.status === "error" ? "text-[#FF6961]" : "text-zinc-400"}`}>{s.summary}</span>}
                          {s.duration_ms != null && <span className="tabular-nums">{s.duration_ms}ms</span>}
                        </span>
                      </summary>
                      {s.kind === "tool" && (
                        <div className="mt-1.5 space-y-1 border-t border-white/[0.06] pt-1.5 text-[10px] font-mono text-zinc-400">
                          <div>Args: {JSON.stringify(s.args || {})}</div>
                          {s.result !== undefined && (
                            <pre className="max-h-32 overflow-auto rounded bg-black/50 p-1.5 text-zinc-300">
                              {JSON.stringify(s.result, null, 2)}
                            </pre>
                          )}
                        </div>
                      )}
                    </details>
                  ))}
                </div>
              </div>
            )}

            {exportsReady.map((ex, i) => (
              <div key={i} className="flex items-center justify-between rounded-xl border border-[#30D158]/30 bg-[#30D158]/10 px-3 py-2 text-xs">
                <span className="text-[#30D158]">Export ready ({String(ex.format || "csv").toUpperCase()})</span>
                <a href={ex.download_url} target="_blank" rel="noreferrer" className="btn-primary h-7 px-3 text-[11px]">
                  <Icons.Download className="h-3 w-3" /> Download
                </a>
              </div>
            ))}
            <div ref={chatEndRef} />
          </div>

          {/* Input Composer */}
          <form onSubmit={submitPrompt} className="space-y-2 border-t border-white/[0.07] pt-3">
            {activeMission && !running && aiCfg?.configured &&
              ["interrupted", "cancelled", "failed", "incomplete"].includes(activeMission.status) && (
                <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[#FF9F0A]/30 bg-[#FF9F0A]/10 px-3 py-1.5 text-[11px] text-[#FFB340]">
                  <span>Task paused/incomplete ({activeMission.status}).</span>
                  <button
                    type="button"
                    onClick={() =>
                      submitPrompt(null, "Continue right where you left off without repeating completed work, and finish remaining steps.")
                    }
                    className="inline-flex items-center gap-1 rounded-full bg-[#30D158]/20 px-3 py-1 text-[11px] font-semibold text-[#30D158] transition hover:bg-[#30D158]/30"
                  >
                    <Icons.Play className="h-2.5 w-2.5" /> Continue Mission
                  </button>
                </div>
              )}
            <textarea
              rows={3}
              className="input resize-none text-xs leading-relaxed"
              placeholder={
                activeMission
                  ? 'Follow up: e.g. "remove anyone without email", "undo", or "save top 5 to Best Leads"'
                  : 'Ask AI to find & research leads: e.g. "Find 15 dental clinics in Austin that need a website redesign and can pay $2k/mo"'
              }
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submitPrompt(e);
                }
              }}
              disabled={sending}
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-[10px] text-zinc-500">
                {usageStats && (usageStats.input_tokens > 0 || usageStats.output_tokens > 0)
                  ? `Tokens: ${usageStats.input_tokens.toLocaleString()} in${
                      usageStats.cached_tokens > 0 ? ` (${usageStats.cached_tokens.toLocaleString()} cached)` : ""
                    } · ${usageStats.output_tokens.toLocaleString()} out`
                  : "Enter to send · Shift+Enter for new line"}
              </span>
              <div className="flex items-center gap-2">
                {running ? (
                  <button type="button" onClick={stopMission} className="btn-danger h-8 px-3.5 text-xs">
                    <Icons.Square className="h-3 w-3" /> Stop
                  </button>
                ) : (
                  <button
                    type="submit"
                    disabled={sending || !prompt.trim() || !aiCfg?.configured}
                    className="btn-primary h-8 px-4 text-xs"
                  >
                    <Icons.Send className="h-3.5 w-3.5" />
                    {activeMission ? "Send Follow-up" : "Start AI Mission"}
                  </button>
                )}
              </div>
            </div>
          </form>
        </div>
        )}

        {/* Right: Live Leads / Shortlists / History / Action Log */}
        {paneLayout !== "chat" && (
        <div className={`flex min-h-[540px] flex-col gap-3 ${paneLayout === "workspace" ? "lg:col-span-12" : "lg:col-span-7"}`}>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-white/[0.08] bg-white/[0.03] px-3 py-2">
            <div className="segmented flex-wrap">
              {[
                ["leads", "Live Results"],
                ["shortlists", `Shortlists (${shortlists.length})`],
                ["history", `Missions (${missions.length})`],
                ["logs", "Action Log"],
              ].map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => {
                    setRightTab(id);
                    if (id === "logs") {
                      if (activeMission?.id) api.aiMissionLog(activeMission.id).then(setMissionLog).catch(() => {});
                      else api.aiLogs(200).then((d) => setMissionLog({ tool_calls: [], log_lines: d?.lines || [], log_file: d?.log_file || "" })).catch(() => {});
                    }
                  }}
                  className={`segmented-item text-xs ${
                    rightTab === id ? "bg-white/[0.14] text-white" : "text-zinc-400 hover:text-zinc-200"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="flex items-center gap-2">
              {rightTab === "leads" && (
                <select
                  className="input h-7 w-52 py-0 text-xs"
                  value={activeJobId}
                  onChange={(e) => setActiveJobId(e.target.value)}
                >
                  <option value="">Select job dataset…</option>
                  {jobsList.map((j) => (
                    <option key={j.id} value={j.id}>
                      {j.query} — {j.location || j.country || "Area"} ({j.scraped})
                    </option>
                  ))}
                </select>
              )}
              <button
                type="button"
                onClick={() => setPaneLayout(paneLayout === "workspace" ? "split" : "workspace")}
                title={paneLayout === "workspace" ? "Restore split view" : "Expand workspace full width"}
                className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] text-zinc-400 transition hover:bg-white/[0.07] hover:text-zinc-100"
              >
                {paneLayout === "workspace" ? <Icons.Minimize className="h-3.5 w-3.5" /> : <Icons.Maximize className="h-3.5 w-3.5" />}
                <span>{paneLayout === "workspace" ? "Split View" : "Expand"}</span>
              </button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto pr-1">
            {rightTab === "leads" ? (
              activeJobId ? (
                <ResultsView
                  jobId={activeJobId}
                  refreshSignal={resultsRefresh}
                  externalView={liveView}
                  notify={notify}
                  onNavigateSettings={onOpenSettings}
                />
              ) : (
                <div className="card py-20 text-center text-xs text-zinc-500">
                  Start an AI Mission on the left or pick an existing dataset above to inspect live AI-ranked results.
                </div>
              )
            ) : rightTab === "shortlists" ? (
              <div className="space-y-4">
                <form onSubmit={createNewList} className="card flex flex-wrap items-center gap-2">
                  <input
                    className="input h-8 flex-1 min-w-[200px] text-xs"
                    placeholder="New shortlist name (e.g. 'Austin Dental Hot Leads')"
                    value={newListName}
                    onChange={(e) => setNewListName(e.target.value)}
                  />
                  <button type="submit" className="btn-primary h-8 px-3.5 text-xs" disabled={!newListName.trim()}>
                    Create Shortlist
                  </button>
                </form>

                {shortlists.length === 0 ? (
                  <div className="card py-14 text-center text-xs text-zinc-500">
                    No shortlists yet. Ask AI Copilot to save top leads, or save individual businesses from any Details modal.
                  </div>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {shortlists.map((l) => (
                      <div
                        key={l.id}
                        onClick={() => setSelectedListId(l.id)}
                        className={`card cursor-pointer space-y-2 transition hover:border-[#0A84FF]/40 ${
                          selectedListId === l.id ? "border-[#0A84FF]/60 bg-[#0A84FF]/[0.06]" : ""
                        }`}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <div>
                            <div className="text-sm font-semibold text-zinc-100">{l.name}</div>
                            <div className="text-[11px] text-zinc-400">{l.item_count || 0} saved lead(s)</div>
                          </div>
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              removeList(l.id);
                            }}
                            className="rounded-lg p-1 text-zinc-500 hover:bg-[#FF453A]/15 hover:text-[#FF6961]"
                          >
                            <Icons.Trash className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <div className="flex flex-wrap gap-1.5 pt-1" onClick={(e) => e.stopPropagation()}>
                          {["csv", "xlsx", "json"].map((fmt) => (
                            <a
                              key={fmt}
                              href={api.shortlistExportUrl(l.id, fmt)}
                              target="_blank"
                              rel="noreferrer"
                              className="btn-ghost px-2 py-0.5 text-[10px]"
                            >
                              {fmt.toUpperCase()}
                            </a>
                          ))}
                          <a
                            href={api.shortlistExportUrl(l.id, "crm", "hubspot")}
                            target="_blank"
                            rel="noreferrer"
                            className="btn-ghost px-2 py-0.5 text-[10px]"
                          >
                            HubSpot CSV
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {selectedList && (
                  <div className="card space-y-3">
                    <div className="flex items-center justify-between">
                      <h3 className="text-sm font-semibold text-zinc-100">{selectedList.name}</h3>
                      <span className="text-xs text-zinc-400">{selectedList.items?.length || 0} leads</span>
                    </div>
                    {(selectedList.items || []).length === 0 ? (
                      <div className="py-6 text-center text-xs text-zinc-500">This shortlist is empty.</div>
                    ) : (
                      <div className="space-y-2.5">
                        {selectedList.items.map((item) => {
                          const ac = item.ai_score != null || item.ai_verdict ? aiColor(item.ai_verdict, item.ai_score) : null;
                          const camp = tryJson(item.ai_campaign, {});
                          return (
                            <div key={item.id} className="rounded-2xl border border-white/[0.07] bg-white/[0.02] p-3 text-xs space-y-2">
                              <div className="flex flex-wrap items-start justify-between gap-2">
                                <div>
                                  <div className="font-semibold text-zinc-100">{item.name}</div>
                                  <div className="text-[11px] text-zinc-400">
                                    {item.category} · {item.phone || "No phone"} · {item.email || "No email"}
                                  </div>
                                </div>
                                <div className="flex items-center gap-2">
                                  {ac && (
                                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${ac.bg} ${ac.text} ${ac.ring}`}>
                                      AI {item.ai_score ?? "—"} · {item.ai_verdict || "Fit"}
                                    </span>
                                  )}
                                  <select
                                    className="input h-7 w-auto py-0 text-[11px]"
                                    value={item.status || "New"}
                                    onChange={(e) => patchListItem(item.id, { status: e.target.value })}
                                  >
                                    {["New", "Contacted", "Replied", "Won", "Skip"].map((st) => (
                                      <option key={st} value={st}>{st}</option>
                                    ))}
                                  </select>
                                  <button
                                    type="button"
                                    onClick={() => removeListItem(item.id)}
                                    className="rounded-lg p-1 text-zinc-500 hover:bg-[#FF453A]/15 hover:text-[#FF6961]"
                                  >
                                    <Icons.Trash className="h-3.5 w-3.5" />
                                  </button>
                                </div>
                              </div>
                              {item.ai_why && <div className="text-zinc-300 leading-relaxed">{item.ai_why}</div>}
                              {camp?.icebreaker && (
                                <div className="flex items-center justify-between gap-2 rounded-xl bg-black/30 px-2.5 py-1.5 text-[11px] text-zinc-300">
                                  <span className="truncate">Pitch: {camp.icebreaker}</span>
                                  <CopyButton text={camp.icebreaker} label="Copy" onCopied={() => notify && notify("Opener copied", "success")} />
                                </div>
                              )}
                              <input
                                className="input h-7 text-[11px]"
                                placeholder="Add sales notes…"
                                defaultValue={item.notes || ""}
                                onBlur={(e) => {
                                  if ((e.target.value || "") !== (item.notes || "")) {
                                    patchListItem(item.id, { notes: e.target.value });
                                  }
                                }}
                              />
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ) : rightTab === "logs" ? (
              <div className="space-y-4">
                <div className="card flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div>
                    <div className="font-semibold text-zinc-100">AI Function Audit Log</div>
                    <div className="text-[11px] text-zinc-500">
                      Every function called, parameters passed, returned output, timing, and persisted file log (`ai_runs.log`).
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        if (activeMission?.id) api.aiMissionLog(activeMission.id).then(setMissionLog).catch(() => {});
                        else api.aiLogs(250).then((d) => setMissionLog({ tool_calls: [], log_lines: d?.lines || [], log_file: d?.log_file || "" })).catch(() => {});
                      }}
                      className="btn-ghost px-3 py-1 text-xs"
                    >
                      <Icons.Refresh className="h-3.5 w-3.5" /> Refresh
                    </button>
                    {(missionLog.log_lines?.length > 0 || missionLog.tool_calls?.length > 0) && (
                      <CopyButton
                        text={JSON.stringify(missionLog, null, 2)}
                        label="Copy Audit JSON"
                        onCopied={() => notify && notify("Audit log copied", "success")}
                      />
                    )}
                  </div>
                </div>

                {missionLog.tool_calls?.length > 0 && (
                  <div className="card space-y-2.5">
                    <div className="text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                      Tool Calls ({missionLog.tool_calls.length})
                    </div>
                    <div className="space-y-2">
                      {missionLog.tool_calls.map((tc, i) => {
                        const argsObj = tryJson(tc.tool_args, {});
                        const resObj = tryJson(tc.tool_result, {});
                        const meta = resObj?._meta || {};
                        const isErr = Boolean(resObj?.error);
                        return (
                          <details key={tc.id || i} className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-2.5 text-xs">
                            <summary className="flex cursor-pointer list-none items-center justify-between gap-2">
                              <div className="flex min-w-0 items-center gap-2">
                                <span className="tabular-nums text-zinc-500">#{i + 1}</span>
                                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${isErr ? "bg-[#FF453A]" : "bg-[#30D158]"}`} />
                                <code className="rounded bg-white/[0.07] px-1.5 py-0.5 text-[11px] text-[#64D2FF]">{tc.tool_name}</code>
                                <span className="truncate text-zinc-300">{tc.content || meta.summary || formatToolLabel(tc.tool_name, argsObj)}</span>
                              </div>
                              <div className="flex shrink-0 items-center gap-2 text-[10px] text-zinc-500 tabular-nums">
                                {meta.duration_ms != null && <span>{meta.duration_ms}ms</span>}
                                <span>{tc.created_at}</span>
                              </div>
                            </summary>
                            <div className="mt-2 grid gap-2 border-t border-white/[0.06] pt-2 text-[10px] font-mono sm:grid-cols-2">
                              <div>
                                <div className="mb-1 text-zinc-500">Arguments</div>
                                <pre className="max-h-40 overflow-auto rounded bg-black/50 p-2 text-zinc-300">
                                  {JSON.stringify(argsObj, null, 2)}
                                </pre>
                              </div>
                              <div>
                                <div className="mb-1 text-zinc-500">Output</div>
                                <pre className="max-h-40 overflow-auto rounded bg-black/50 p-2 text-zinc-300">
                                  {JSON.stringify(resObj, null, 2)}
                                </pre>
                              </div>
                            </div>
                          </details>
                        );
                      })}
                    </div>
                  </div>
                )}

                <div className="card space-y-2">
                  <div className="flex items-center justify-between text-[11px] text-zinc-400">
                    <span className="font-semibold uppercase tracking-wider text-zinc-500">Saved Server Log</span>
                    <span className="truncate font-mono text-[10px] text-zinc-500">{missionLog.log_file || "backend/data/ai_runs.log"}</span>
                  </div>
                  <pre className="max-h-80 overflow-auto rounded-xl border border-white/[0.06] bg-black/60 p-3 font-mono text-[10px] leading-relaxed text-zinc-300">
                    {missionLog.log_lines?.length ? missionLog.log_lines.join("\n") : "No AI log lines recorded for this mission yet."}
                  </pre>
                </div>
              </div>
            ) : (
              <div className="space-y-2.5">
                {missions.length === 0 ? (
                  <div className="card py-14 text-center text-xs text-zinc-500">No saved missions yet.</div>
                ) : (
                  missions.map((m) => (
                    <div
                      key={m.id}
                      onClick={() => {
                        openMission(m.id);
                        setRightTab("leads");
                      }}
                      className={`card cursor-pointer space-y-1.5 transition hover:border-[#0A84FF]/40 ${
                        activeMission?.id === m.id ? "border-[#0A84FF]/60" : ""
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <div className="truncate text-sm font-semibold text-zinc-100">{m.title || m.goal}</div>
                        <div className="flex items-center gap-2">
                          <StatusBadge status={m.status} />
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              api.deleteMission(m.id).then(() => {
                                if (activeMission?.id === m.id) startNewMission();
                                api.listMissions(40).then((d) => setMissions(d?.missions || [])).catch(() => {});
                              });
                            }}
                            className="rounded-lg p-1 text-zinc-500 hover:bg-[#FF453A]/15 hover:text-[#FF6961]"
                          >
                            <Icons.Trash className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      </div>
                      <div className="line-clamp-2 text-xs text-zinc-400">{m.summary || m.goal}</div>
                      <div className="text-[10px] text-zinc-500">
                        Mode: {m.mode_id} · {m.created_at}
                      </div>
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        </div>
        )}
      </div>
    </div>
  );
}
