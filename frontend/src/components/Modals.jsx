import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { aiColor, CopyButton, GmeLogo, Icons, leadColor, mapsLink, StarRating, tryJson } from "./ui.jsx";

function Section({ title, children }) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">{title}</div>
      {children}
    </div>
  );
}

function Line({ icon, text, copyText }) {
  return (
    <div className="flex items-start justify-between gap-2 text-sm text-zinc-200">
      <div className="flex min-w-0 items-start gap-2.5">
        <span className="mt-1 shrink-0 text-zinc-400">{icon}</span>
        <span className="min-w-0 break-words">{text}</span>
      </div>
      {copyText && <CopyButton text={copyText} />}
    </div>
  );
}

export function BusinessModal({ b, jobId, onClose, onUpdated, notify }) {
  const [lead, setLead] = useState(b);
  const [showRaw, setShowRaw] = useState(false);
  const [aiTab, setAiTab] = useState("verdict");
  const [aiMode, setAiMode] = useState("web_seo");
  const [analyzing, setAnalyzing] = useState(false);
  const [lists, setLists] = useState([]);
  const [pickListId, setPickListId] = useState("");
  const [newListName, setNewListName] = useState("");
  const [savingList, setSavingList] = useState(false);

  useEffect(() => {
    setLead(b);
  }, [b]);

  useEffect(() => {
    api.listShortlists().then((d) => setLists(d?.lists || [])).catch(() => {});
  }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const activeJobId = jobId || lead?.job_id;
  const hoursObj = tryJson(lead.hours, null);
  const emails = tryJson(lead.emails, []);
  const socials = tryJson(lead.socials, []);
  const reviews = tryJson(lead.reviews, []);
  const price = lead.price_level ? "$".repeat(lead.price_level) : lead.price_desc || null;
  const web = lead.website ? (lead.website.startsWith("http") ? lead.website : "https://" + lead.website) : null;
  const webTech = tryJson(lead.web_tech, {});
  const chips = [lead.service_options, lead.popular_for, lead.amenities, lead.highlights].filter(Boolean);
  const aiPainPoints = tryJson(lead.ai_pain_points, []);
  const aiCampaign = tryJson(lead.ai_campaign, {});
  const hasAi = lead.ai_score != null || !!lead.ai_verdict || !!lead.ai_why;
  const ac = hasAi ? aiColor(lead.ai_verdict, lead.ai_score) : null;

  async function runSingleAi() {
    if (!activeJobId || !lead?.cid) return;
    setAnalyzing(true);
    try {
      const res = await api.aiAnalyzeJob(activeJobId, { cids: [lead.cid], mode_id: aiMode });
      if (res?.error) {
        if (notify) notify(res.error, "error");
        return;
      }
      if (res?.items?.length) {
        const up = res.items[0];
        setLead((prev) => ({ ...prev, ...up }));
        if (onUpdated) onUpdated();
        if (notify) notify("AI analysis updated", "success");
      } else if (res?.errors?.length) {
        if (notify) notify(res.errors[0], "error");
      }
    } catch (e) {
      if (notify) notify(String(e), "error");
    } finally {
      setAnalyzing(false);
    }
  }

  async function saveToShortlist() {
    setSavingList(true);
    try {
      let targetId = pickListId;
      if (!targetId) {
        const created = await api.createShortlist({ name: (newListName || "Top Leads").trim() });
        targetId = created?.list?.id;
      }
      if (!targetId) return;
      const res = await api.addShortlistItems(targetId, { leads: [lead] });
      if (notify) notify(`Saved to shortlist (${res.added || 1} added)`, "success");
      setNewListName("");
      const refreshed = await api.listShortlists();
      setLists(refreshed?.lists || []);
      setPickListId(targetId);
    } catch (e) {
      if (notify) notify(String(e), "error");
    } finally {
      setSavingList(false);
    }
  }

  async function softRemove() {
    if (!activeJobId || !lead?.cid) return;
    try {
      await api.removeLeads(activeJobId, [lead.cid], "Removed by user");
      if (notify) notify("Lead removed (use Restore Removed to undo)", "success");
      if (onUpdated) onUpdated();
      onClose();
    } catch (e) {
      if (notify) notify(String(e), "error");
    }
  }

  return (
    <div
      className="animate-backdrop-enter fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/65 p-4 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="animate-modal-enter apple-modal my-8 w-full max-w-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-4 border-b border-white/[0.08] p-5">
          {lead.thumbnail ? (
            <img
              src={`/api/thumb?u=${encodeURIComponent(lead.thumbnail)}`}
              alt=""
              className="h-20 w-20 shrink-0 rounded-2xl object-cover ring-1 ring-white/10"
            />
          ) : (
            <div className="grid h-20 w-20 shrink-0 place-items-center rounded-2xl bg-white/[0.05] text-zinc-400 ring-1 ring-white/10">
              <Icons.Building className="h-8 w-8" />
            </div>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <h2 className="text-lg font-semibold tracking-tight text-zinc-100">{lead.name || "Unnamed business"}</h2>
              <button
                onClick={onClose}
                className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-white/[0.08] hover:text-zinc-100"
                aria-label="Close"
              >
                <Icons.X className="h-4 w-4" />
              </button>
            </div>
            {lead.category && <div className="mt-0.5 truncate text-sm text-[#64D2FF]">{lead.category}</div>}
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <StarRating value={lead.rating} />
              {lead.rating != null && <span className="text-sm font-medium tabular-nums text-zinc-200">{lead.rating}</span>}
              {lead.reviews_count != null && <span className="text-xs tabular-nums text-zinc-500">({lead.reviews_count})</span>}
              {price && (
                <span className="rounded-full bg-[#30D158]/15 px-2 py-0.5 text-[11px] font-medium text-[#30D158]">
                  {price}
                </span>
              )}
              {ac && (
                <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold tabular-nums ${ac.bg} ${ac.text} ${ac.ring}`}>
                  AI {lead.ai_score ?? "—"} · {lead.ai_verdict || "Evaluated"}
                </span>
              )}
              {lead.is_ad ? (
                <span className="rounded-full bg-[#FF9F0A]/15 px-2 py-0.5 text-[10px] font-medium text-[#FFB340]">Ad</span>
              ) : null}
              {lead.closed_status && (
                <span className="rounded-full bg-[#FF453A]/15 px-2 py-0.5 text-[10px] font-medium text-[#FF6961]">
                  {lead.closed_status}
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="max-h-[70vh] space-y-5 overflow-y-auto p-5">
          {/* AI Intelligence & Personalized Outreach */}
          <Section title="AI Copilot Evaluation & Pitch">
            <div className="space-y-3 rounded-2xl border border-[#0A84FF]/25 bg-[#0A84FF]/[0.05] p-3.5 text-xs">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <select
                    className="input h-7 w-auto py-0 text-[11px]"
                    value={aiMode}
                    onChange={(e) => setAiMode(e.target.value)}
                  >
                    <option value="web_seo">Web Design &amp; SEO</option>
                    <option value="reputation_voice">Reputation &amp; AI Voice</option>
                    <option value="b2b_outreach">B2B Cold Outreach</option>
                    <option value="icp_budget">ICP &amp; Budget Qualifier</option>
                    <option value="market_research">Market Research</option>
                  </select>
                  <button
                    type="button"
                    onClick={runSingleAi}
                    disabled={analyzing || !activeJobId}
                    className="btn-primary h-7 px-3 text-[11px]"
                  >
                    <Icons.Sparkles className={`h-3 w-3 ${analyzing ? "animate-spin" : ""}`} />
                    {analyzing ? "Analyzing…" : hasAi ? "Re-run AI" : "AI Analyze Lead"}
                  </button>
                </div>
                {hasAi && (
                  <div className="segmented">
                    {[
                      ["verdict", "Verdict & Proof"],
                      ["outreach", "Outreach Pitch"],
                    ].map(([id, label]) => (
                      <button
                        key={id}
                        type="button"
                        onClick={() => setAiTab(id)}
                        className={`segmented-item text-[11px] ${
                          aiTab === id ? "bg-white/[0.14] text-white" : "text-zinc-400"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                )}
              </div>

              {hasAi ? (
                aiTab === "verdict" ? (
                  <div className="space-y-2.5">
                    <div className="flex flex-wrap gap-2">
                      {lead.ai_affordability && (
                        <span className="rounded-full bg-white/[0.08] px-2.5 py-0.5 text-[11px] text-zinc-200">
                          Affordability: <strong>{lead.ai_affordability}</strong>
                        </span>
                      )}
                      {lead.ai_need && (
                        <span className="rounded-full bg-white/[0.08] px-2.5 py-0.5 text-[11px] text-zinc-200">
                          Urgency/Need: <strong>{lead.ai_need}</strong>
                        </span>
                      )}
                      {lead.ai_owner && (
                        <span className="rounded-full bg-[#30D158]/15 px-2.5 py-0.5 text-[11px] text-[#30D158]">
                          Decision Maker: {lead.ai_owner}
                        </span>
                      )}
                    </div>
                    {lead.ai_why && (
                      <div className="whitespace-pre-line leading-relaxed text-zinc-200">{lead.ai_why}</div>
                    )}
                    {Array.isArray(aiPainPoints) && aiPainPoints.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {aiPainPoints.map((pt, i) => (
                          <span key={i} className="rounded-full border border-[#FF9F0A]/30 bg-[#FF9F0A]/10 px-2.5 py-0.5 text-[11px] text-[#FFB340]">
                            {pt}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    {[
                      ["Email Subject", aiCampaign?.email_subject],
                      ["Email Opener", aiCampaign?.icebreaker],
                      ["Cold Call Opener", aiCampaign?.call_opener],
                      ["Follow-up", aiCampaign?.followup],
                    ].map(([lbl, val]) =>
                      val ? (
                        <div key={lbl} className="rounded-xl border border-white/[0.06] bg-black/30 p-2.5">
                          <div className="mb-1 flex items-center justify-between text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
                            <span>{lbl}</span>
                            <CopyButton text={val} onCopied={() => notify && notify(`${lbl} copied`, "success")} />
                          </div>
                          <div className="text-zinc-200 leading-relaxed">{val}</div>
                        </div>
                      ) : null
                    )}
                    {!aiCampaign?.email_subject && !aiCampaign?.icebreaker && !aiCampaign?.call_opener && (
                      <div className="text-zinc-400">No outreach snippets saved yet. Click Re-run AI to generate.</div>
                    )}
                  </div>
                )
              ) : (
                <div className="text-[11px] text-zinc-400">
                  Run AI analysis on this business (requires an API key in Settings → AI Engine) to score budget fit, extract owner names, spot website/review gaps, and write outreach copy.
                </div>
              )}
            </div>
          </Section>

          {/* Shortlist + Soft Remove Actions */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-white/[0.07] bg-white/[0.02] p-3 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Icons.Bookmark className="h-3.5 w-3.5 text-[#0A84FF]" />
              <select
                className="input h-7 w-40 py-0 text-[11px]"
                value={pickListId}
                onChange={(e) => setPickListId(e.target.value)}
              >
                <option value="">+ New shortlist…</option>
                {lists.map((l) => (
                  <option key={l.id} value={l.id}>{l.name} ({l.item_count})</option>
                ))}
              </select>
              {!pickListId && (
                <input
                  className="input h-7 w-36 py-0 text-[11px]"
                  placeholder="Shortlist name"
                  value={newListName}
                  onChange={(e) => setNewListName(e.target.value)}
                />
              )}
              <button
                type="button"
                onClick={saveToShortlist}
                disabled={savingList}
                className="btn-ghost h-7 px-2.5 text-[11px]"
              >
                {savingList ? "Saving…" : "Save to List"}
              </button>
            </div>
            {activeJobId && (
              <button
                type="button"
                onClick={softRemove}
                className="inline-flex items-center gap-1 rounded-lg px-2.5 py-1 text-[11px] text-[#FF6961] transition hover:bg-[#FF453A]/15"
              >
                <Icons.Trash className="h-3 w-3" /> Remove from Table
              </button>
            )}
          </div>

          <Section title="Contact">
            <div className="space-y-2 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3.5">
              {b.full_address && <Line icon={<Icons.MapPin className="h-3.5 w-3.5" />} text={b.full_address} copyText={b.full_address} />}
              {b.phone && (
                <Line
                  icon={<Icons.Phone className="h-3.5 w-3.5" />}
                  text={
                    <a href={`tel:${b.phone}`} className="text-[#409CFF] hover:underline">
                      {b.phone}
                    </a>
                  }
                  copyText={b.phone}
                />
              )}
              {emails.length > 0 ? (
                emails.map((e, i) => (
                  <Line
                    key={i}
                    icon={<Icons.Mail className="h-3.5 w-3.5" />}
                    text={
                      <a href={`mailto:${e}`} className="break-all text-[#409CFF] hover:underline">
                        {e}
                      </a>
                    }
                    copyText={e}
                  />
                ))
              ) : (
                <Line icon={<Icons.Mail className="h-3.5 w-3.5" />} text={<span className="text-zinc-500">No email found</span>} />
              )}
              <Line
                icon={<Icons.Globe className="h-3.5 w-3.5" />}
                text={
                  web ? (
                    <a href={web} target="_blank" rel="noreferrer" className="break-all text-[#409CFF] hover:underline">
                      {web}
                    </a>
                  ) : (
                    <span className="text-zinc-500">—</span>
                  )
                }
                copyText={web || undefined}
              />
              <Line
                icon={<Icons.Map className="h-3.5 w-3.5" />}
                text={
                  <a href={mapsLink(b)} target="_blank" rel="noreferrer" className="text-[#409CFF] hover:underline">
                    View on Google Maps
                  </a>
                }
              />
              {b.menu_url && (
                <Line
                  icon={<Icons.ExternalLink className="h-3.5 w-3.5" />}
                  text={
                    <a href={b.menu_url} target="_blank" rel="noreferrer" className="text-[#409CFF] hover:underline">
                      Google Menu
                    </a>
                  }
                />
              )}
            </div>
          </Section>

          {webTech &&
          (webTech.ssl !== undefined ||
            webTech.cms?.length ||
            webTech.has_contact_form !== undefined ||
            webTech.has_analytics ||
            webTech.has_fb_pixel ||
            webTech.has_livechat) ? (
            (() => {
              const techChips = [];
              (webTech.cms || []).forEach((c) =>
                techChips.push(
                  c === "wordpress"
                    ? "WordPress"
                    : c === "woocommerce"
                    ? "WooCommerce"
                    : c === "shopify"
                    ? "Shopify"
                    : c === "react"
                    ? "React/Next.js"
                    : c
                )
              );
              if (webTech.has_analytics) techChips.push("Google Analytics");
              if (webTech.has_fb_pixel) techChips.push("FB Pixel");
              if (webTech.has_livechat) techChips.push("Live chat");
              if (webTech.has_contact_form) techChips.push("Contact form");
              return (
                <Section title="Website intelligence">
                  <div className="space-y-2.5 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3.5 text-sm">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-zinc-400">SSL:</span>
                      {webTech.ssl === true ? (
                        <span className="rounded-full bg-[#30D158]/15 px-2.5 py-0.5 text-[11px] font-medium text-[#30D158]">
                          ✓ Secure (HTTPS)
                        </span>
                      ) : webTech.ssl === false ? (
                        <span className="rounded-full bg-[#FF453A]/15 px-2.5 py-0.5 text-[11px] font-medium text-[#FF6961]">
                          ⚠ No SSL
                        </span>
                      ) : (
                        <span className="rounded-full bg-white/[0.07] px-2.5 py-0.5 text-[11px] text-zinc-300">Unknown</span>
                      )}
                      {webTech.domain_age != null && (
                        <span className="rounded-full bg-white/[0.07] px-2.5 py-0.5 text-[11px] text-zinc-300 tabular-nums">
                          Domain ~{webTech.domain_age} yrs
                        </span>
                      )}
                    </div>
                    {techChips.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5">
                        {techChips.map((t, i) => (
                          <span key={i} className="rounded-full bg-white/[0.06] px-2.5 py-0.5 text-[11px] text-zinc-300">
                            {t}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <div className="text-xs text-zinc-500">No CMS or analytics detected.</div>
                    )}
                  </div>
                </Section>
              );
            })()
          ) : null}

          {b.lead_grade ? (
            (() => {
              const lc = leadColor(b.lead_grade);
              const reasons = tryJson(b.lead_reasons, []);
              const tags = tryJson(b.lead_tags, []);
              return (
                <Section title={`Lead score — ${b.lead_score} / 100 (${b.lead_grade})`}>
                  <div className="space-y-2 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3.5 text-sm">
                    {reasons.length ? (
                      reasons.map((r, i) => (
                        <div key={i} className="flex items-start gap-2.5 text-zinc-300">
                          <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${lc.bg} ${lc.ring}`} />
                          <span>{r}</span>
                        </div>
                      ))
                    ) : (
                      <div className="text-zinc-500">No scoring data.</div>
                    )}
                    {tags.length ? (
                      <div className="flex flex-wrap gap-1.5 pt-1">
                        {tags.map((t, i) => (
                          <span key={i} className="rounded-full bg-white/[0.06] px-2.5 py-0.5 text-[11px] text-zinc-400">
                            #{t}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                </Section>
              );
            })()
          ) : null}

          {hoursObj && (
            <Section title="Hours">
              <div className="space-y-1 rounded-2xl border border-white/[0.06] bg-white/[0.02] p-3.5 text-sm text-zinc-300">
                {Object.entries(hoursObj).map(([d, r]) => (
                  <div key={d} className="flex gap-3">
                    <span className="w-24 shrink-0 text-zinc-500">{d}</span>
                    <span>{r.join(", ")}</span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {chips.length > 0 && (
            <Section title="Attributes">
              <div className="flex flex-wrap gap-1.5">
                {chips.map((c, i) => (
                  <span key={i} className="rounded-full bg-white/[0.06] px-2.5 py-0.5 text-[11px] text-zinc-300">
                    {c}
                  </span>
                ))}
              </div>
            </Section>
          )}

          {socials.length > 0 && (
            <Section title="Socials">
              <div className="flex flex-wrap gap-2 text-xs">
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
                      key={i}
                      href={s}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-full border border-white/[0.08] bg-white/[0.05] px-3 py-1 text-[#409CFF] transition hover:bg-white/[0.1]"
                    >
                      <Icons.ExternalLink className="h-3 w-3" />
                      {net}
                    </a>
                  );
                })}
              </div>
            </Section>
          )}

          {reviews.length > 0 && (
            <Section title={`Reviews (${reviews.length})`}>
              <div className="space-y-2.5">
                {reviews.map((rv, i) => (
                  <div key={i} className="rounded-2xl border border-white/[0.06] bg-white/[0.03] p-3 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-zinc-200">{rv.author || "Anonymous"}</span>
                      <span className="text-[#FF9F0A]">{"★".repeat(rv.rating || 0)}{"☆".repeat(5 - (rv.rating || 0))}</span>
                    </div>
                    {rv.time && <div className="text-zinc-500">{rv.time}</div>}
                    {rv.text && <p className="mt-1.5 leading-relaxed text-zinc-300">{rv.text}</p>}
                  </div>
                ))}
              </div>
            </Section>
          )}

          <Section title="Raw data">
            <button onClick={() => setShowRaw((v) => !v)} className="btn-ghost px-3 py-1 text-xs">
              {showRaw ? "Hide JSON" : "Show JSON"}
            </button>
            {showRaw && (
              <pre className="mt-2 max-h-64 overflow-auto rounded-2xl border border-white/[0.06] bg-black/50 p-3 text-[11px] text-zinc-400">
                {JSON.stringify(b, null, 2)}
              </pre>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}

export function ComparePanel({ data, onClose, onOpen }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const base = data.baseline;
  const newList = data.new || [];
  const removedList = data.removed || [];
  const changedList = data.changed || [];

  return (
    <div
      className="animate-backdrop-enter fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/65 p-4 backdrop-blur-md"
      onClick={onClose}
    >
      <div className="animate-modal-enter apple-modal my-8 w-full max-w-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-white/[0.08] p-4">
          <div className="flex items-center gap-2">
            <Icons.Bell className="h-4 w-4 text-[#0A84FF]" />
            <h2 className="text-base font-semibold tracking-tight text-zinc-100">New since last scan</h2>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/[0.08] hover:text-zinc-100" aria-label="Close">
            <Icons.X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] space-y-4 overflow-y-auto p-5 text-sm">
          {data.loading && <div className="text-zinc-500">Comparing with previous run…</div>}
          {data.error && <div className="text-[#FF6961]">Failed: {data.error}</div>}
          {!data.loading && !data.error && !base && (
            <div className="rounded-2xl border border-white/[0.06] bg-white/[0.03] p-4 text-zinc-400">
              No previous run found for this search
              {data.current?.query ? ` (“${data.current.query}”` : ""}
              {data.current?.location ? ` · ${data.current.location}` : ""}). Run this search again later to track new businesses, rating changes, and closures.
            </div>
          )}
          {!data.loading && !data.error && base && (
            <>
              <div className="rounded-2xl border border-white/[0.06] bg-white/[0.03] px-3.5 py-2.5 text-xs text-zinc-400">
                Comparing <span className="text-zinc-200">{data.current?.query}</span> against the run from{" "}
                <span className="text-zinc-200">{base.created_at}</span>.
              </div>
              <div className="grid grid-cols-3 gap-2.5 text-center">
                <div className="rounded-2xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="text-2xl font-bold tabular-nums text-[#30D158]">{newList.length}</div>
                  <div className="text-[11px] uppercase tracking-wider text-zinc-500">New</div>
                </div>
                <div className="rounded-2xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="text-2xl font-bold tabular-nums text-[#FF6961]">{removedList.length}</div>
                  <div className="text-[11px] uppercase tracking-wider text-zinc-500">Removed</div>
                </div>
                <div className="rounded-2xl border border-white/[0.06] bg-white/[0.03] p-3">
                  <div className="text-2xl font-bold tabular-nums text-[#FFB340]">{changedList.length}</div>
                  <div className="text-[11px] uppercase tracking-wider text-zinc-500">Changed</div>
                </div>
              </div>
              {newList.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">New businesses</div>
                  <div className="space-y-1.5">
                    {newList.map((b) => (
                      <button
                        key={b.cid}
                        onClick={() => onOpen && onOpen(b)}
                        className="block w-full rounded-xl border border-white/[0.06] bg-white/[0.03] px-3.5 py-2.5 text-left transition hover:bg-white/[0.07]"
                      >
                        <div className="font-medium text-zinc-200">{b.name}</div>
                        <div className="text-xs text-zinc-500">{b.category} · {b.full_address}</div>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {changedList.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">Rating / review changes</div>
                  <div className="space-y-1.5">
                    {changedList.map((c) => (
                      <div key={c.cid} className="rounded-xl border border-white/[0.06] bg-white/[0.03] px-3.5 py-2.5">
                        <div className="font-medium text-zinc-200">{c.name}</div>
                        <div className="text-xs tabular-nums text-zinc-400">
                          ★ {c.rating_a ?? "—"} → {c.rating_b ?? "—"} · {c.reviews_a} → {c.reviews_b} reviews
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {removedList.length > 0 && (
                <div>
                  <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">No longer listed</div>
                  <div className="space-y-1.5">
                    {removedList.map((b) => (
                      <div key={b.cid} className="rounded-xl border border-white/[0.06] bg-white/[0.03] px-3.5 py-2 text-zinc-400">
                        {b.name}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ReportStat({ label, value }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <div className="text-2xl font-bold tabular-nums text-slate-900">{value}</div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500">{label}</div>
    </div>
  );
}

export function ReportModal({ data, onClose }) {
  const [brief, setBrief] = useState(null);
  const [briefLoading, setBriefLoading] = useState(false);
  const [briefErr, setBriefErr] = useState("");

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const job = data.job || {};
  const facets = data.facets || {};
  const counts = facets.counts || {};
  const top = data.top_leads || [];

  async function genBrief() {
    if (!job.id) return;
    setBriefLoading(true);
    setBriefErr("");
    try {
      const res = await api.aiMarketBrief(job.id);
      if (res?.error) setBriefErr(res.error);
      else setBrief(res?.brief || null);
    } catch (e) {
      setBriefErr(String(e));
    } finally {
      setBriefLoading(false);
    }
  }

  return (
    <div
      className="animate-backdrop-enter fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/65 p-4 backdrop-blur-md"
      onClick={onClose}
    >
      <div
        className="animate-modal-enter report-print my-8 w-full max-w-3xl rounded-2xl border border-white/15 bg-white text-slate-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 p-4 print:hidden">
          <h2 className="text-lg font-semibold">Market Report</h2>
          <div className="flex gap-2">
            {job.id && (
              <button
                onClick={genBrief}
                disabled={briefLoading}
                className="inline-flex items-center gap-1.5 rounded-xl border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100"
              >
                <Icons.Sparkles className={`h-3.5 w-3.5 ${briefLoading ? "animate-spin" : ""}`} />
                {briefLoading ? "Writing Brief…" : brief ? "Refresh AI Brief" : "AI Executive Brief"}
              </button>
            )}
            <button onClick={() => window.print()} className="btn-primary text-xs">
              Print / Save PDF
            </button>
            <button onClick={onClose} className="rounded-xl border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-100">
              Close
            </button>
          </div>
        </div>
        <div className="p-8">
          <div className="mb-6 border-b border-slate-200 pb-4">
            <h1 className="text-2xl font-bold tracking-tight">{job.query || "Extraction"} Report</h1>
            <div className="text-sm text-slate-500">{job.location ? job.location + " · " : ""}{job.created_at}</div>
            <div className="mt-1 text-sm tabular-nums text-slate-500">{counts.total || 0} businesses · {job.scraped}/{job.total} scraped</div>
          </div>
          {briefErr && (
            <div className="mb-4 rounded-xl border border-red-200 bg-red-50 px-4 py-2.5 text-xs text-red-700 print:hidden">
              {briefErr}
            </div>
          )}
          {brief && (
            <div className="mb-6 space-y-2 rounded-2xl border border-blue-200 bg-blue-50/60 p-4 text-sm text-slate-800">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold uppercase tracking-wider text-blue-700">AI Executive Market Brief</span>
                {brief.saturation_level && (
                  <span className="rounded-full bg-white px-2.5 py-0.5 text-xs font-semibold text-slate-700">
                    Saturation: {brief.saturation_level}
                  </span>
                )}
              </div>
              {brief.headline && <p className="font-semibold text-slate-900">{brief.headline}</p>}
              {brief.digital_maturity && <p className="text-xs text-slate-600">{brief.digital_maturity}</p>}
              {Array.isArray(brief.top_opportunities) && brief.top_opportunities.length > 0 && (
                <ul className="list-disc space-y-1 pl-5 text-xs text-slate-700">
                  {brief.top_opportunities.map((op, i) => (
                    <li key={i}>{op}</li>
                  ))}
                </ul>
              )}
              {brief.recommended_pitch && (
                <p className="pt-1 text-xs font-medium text-blue-900">Recommended pitch: {brief.recommended_pitch}</p>
              )}
            </div>
          )}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <ReportStat label="Avg rating" value={counts.avg_rating != null ? counts.avg_rating : "—"} />
            <ReportStat label="Avg reviews" value={counts.avg_reviews != null ? counts.avg_reviews : "—"} />
            <ReportStat label="With website" value={counts.with_website || 0} />
            <ReportStat label="No website" value={counts.without_website || 0} />
            <ReportStat label="With email" value={counts.with_email || 0} />
            <ReportStat label="No email" value={counts.without_email || 0} />
            <ReportStat label="With social" value={counts.with_social || 0} />
            <ReportStat label="With reviews" value={counts.with_reviews || 0} />
          </div>
          {top.length > 0 && (
            <div className="mt-8">
              <h3 className="mb-2 text-lg font-semibold">Top leads</h3>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-left text-slate-500">
                    <th className="py-1.5">#</th><th>Business</th><th>Category</th><th>Rating</th><th>Website</th><th>Email</th><th>Score</th>
                  </tr>
                </thead>
                <tbody>
                  {top.map((b, i) => {
                    let email = "—";
                    try {
                      const es = JSON.parse(b.emails || "[]");
                      if (es.length) email = es[0];
                    } catch {}
                    const site = b.website ? (b.website.startsWith("http") ? b.website : "https://" + b.website) : null;
                    return (
                      <tr key={b.cid} className="border-b border-slate-100">
                        <td className="py-1.5 tabular-nums">{i + 1}</td>
                        <td className="py-1.5 font-medium">{b.name}</td>
                        <td className="py-1.5 text-slate-500">{b.category}</td>
                        <td className="py-1.5 tabular-nums">{b.rating != null ? b.rating : "—"}</td>
                        <td className="py-1.5">{site ? <a href={site} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">site</a> : "—"}</td>
                        <td className="py-1.5">{email}</td>
                        <td className="py-1.5 tabular-nums">{b.lead_score} {b.lead_grade}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="mt-8 text-xs text-slate-400">Generated by GME · Google Map Extractor · {new Date().toLocaleString()}</div>
        </div>
      </div>
    </div>
  );
}

export function SplashScreen() {
  return (
    <div className="apple-canvas grid h-screen w-screen place-items-center text-zinc-100">
      <div className="animate-modal-enter flex flex-col items-center text-center">
        <GmeLogo size={64} className="mb-4" />
        <div className="text-xl font-bold tracking-tight">GME</div>
        <div className="text-xs font-medium text-zinc-400">Google Map Extractor</div>
        <div className="mt-2 text-[11px] text-zinc-500">Initializing local engine…</div>
      </div>
    </div>
  );
}

export function ActivateScreen({ auth, branding, onActivated, onClose }) {
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(auth?.message || "");
  const [err, setErr] = useState(Boolean(auth?.status === "unauthorized" && auth?.message));
  const [bindingConflict, setBindingConflict] = useState(Boolean(auth?.binding_conflict));
  const isConflict =
    bindingConflict ||
    /already bound|already being used|device limit/i.test(msg || "");
  const showBranding = branding?.notink !== "Maker";
  const buyUrl = branding?.buy_license_url || "https://t.me/BrainLeadBot";
  const personalTg = branding?.telegram_personal || "https://t.me/brain_lead";
  const personalHandle = branding?.telegram_personal_handle || "@brain_lead";
  const botHandle = branding?.telegram_bot_handle || "@brainleadbot";

  useEffect(() => {
    if (auth?.message) setMsg(auth.message);
    setErr(Boolean(auth?.status === "unauthorized" && auth?.message));
    setBindingConflict(
      Boolean(
        auth?.binding_conflict ||
          /already bound|already being used|device limit/i.test(auth?.message || "")
      )
    );
  }, [auth]);

  const submit = async () => {
    setBusy(true);
    setMsg("");
    setErr(false);
    try {
      const res = await api.activate(key);
      if (res && res.status === "authorized") {
        setBindingConflict(false);
        setMsg("Activated! Loading…");
        onActivated();
      } else {
        setErr(true);
        setBindingConflict(Boolean(res?.binding_conflict));
        setMsg(res?.message || "Activation failed.");
      }
    } catch {
      setErr(true);
      setMsg("Network error during activation.");
    } finally {
      setBusy(false);
    }
  };

  const resetAndActivate = async () => {
    setBusy(true);
    setMsg("");
    setErr(false);
    try {
      const res = await api.resetBinding(key);
      if (res && res.status === "authorized") {
        setBindingConflict(false);
        setMsg(res.message || "Device binding reset and activated!");
        onActivated();
      } else {
        setErr(true);
        setBindingConflict(Boolean(res?.binding_conflict));
        setMsg(res?.message || "Could not reset license binding.");
      }
    } catch {
      setErr(true);
      setMsg("Network error while resetting binding.");
    } finally {
      setBusy(false);
    }
  };

  const switchToFree = async () => {
    setBusy(true);
    try {
      await api.useFreeTier();
      onActivated();
    } catch {
      setErr(true);
      setMsg("Could not switch to Free Tier.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="animate-backdrop-enter fixed inset-0 z-50 grid place-items-center bg-black/75 p-4 backdrop-blur-xl">
      <div className="animate-modal-enter apple-modal w-full max-w-md p-6">
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <GmeLogo size={44} />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-base font-bold tracking-tight text-zinc-100">GME</span>
                <span className="rounded-full border border-white/[0.08] bg-white/[0.05] px-2 py-0.5 text-[10px] font-medium text-zinc-300">
                  Google Map Extractor
                </span>
              </div>
              <div className="text-xs text-zinc-500">{showBranding ? "Brain Lead Licensing" : "License Activation"}</div>
            </div>
          </div>
          {onClose && (
            <button onClick={onClose} className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/[0.08] hover:text-zinc-100">
              <Icons.X className="h-4 w-4" />
            </button>
          )}
        </div>

        <h2 className="mb-1 text-xl font-semibold tracking-tight">
          {isConflict ? "Device Binding Conflict" : "Activate Full Version"}
        </h2>
        <p className="mb-4 text-sm text-zinc-400">
          {isConflict
            ? "This license key is currently bound to another machine. Reset its binding below to transfer it to this PC."
            : auth?.status === "unreachable"
            ? "We couldn't reach the license server. Retry, or enter a license key."
            : "Unlock unlimited results per search and unlimited area-scan tiles."}
        </p>

        {isConflict && (
          <div className="mb-4 space-y-2.5 rounded-2xl border border-[#FF9F0A]/35 bg-[#FF9F0A]/10 p-3.5 text-xs text-[#FFD180]">
            <div className="font-semibold text-[#FFB340]">License bound to another system</div>
            <p className="leading-relaxed text-zinc-300">
              {auth?.has_saved_license && !key.trim()
                ? "Your saved license key is bound to a previous machine. Click below to transfer it to this computer."
                : "Click below to release the previous machine binding and activate on this computer."}
            </p>
            <button
              type="button"
              onClick={resetAndActivate}
              disabled={busy}
              className="btn w-full bg-[#FF9F0A] text-xs font-semibold text-black hover:bg-[#FFB340]"
            >
              <Icons.Refresh className={`h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />
              {busy ? "Resetting Binding…" : "Reset Device Binding & Activate"}
            </button>
          </div>
        )}

        <input
          value={key}
          onChange={(e) => setKey(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !busy && submit()}
          placeholder={auth?.has_saved_license ? "Enter a different license key (optional)…" : "XXXX-XXXX-XXXX-XXXX"}
          className="input font-mono text-sm tracking-wider"
        />
        {msg && <p className={`mt-2.5 text-xs font-medium leading-relaxed ${err ? "text-[#FF6961]" : "text-[#30D158]"}`}>{msg}</p>}

        <button onClick={submit} disabled={busy || !key.trim()} className="btn-primary mt-4 w-full">
          <Icons.Key className="h-4 w-4" />
          {busy ? "Verifying…" : "Activate License"}
        </button>

        {!isConflict && (key.trim() || auth?.has_saved_license) && (
          <button
            type="button"
            onClick={resetAndActivate}
            disabled={busy}
            className="mt-2.5 w-full rounded-xl border border-white/[0.08] bg-white/[0.03] py-2 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.07]"
          >
            Bound to another PC? Reset Device Binding
          </button>
        )}

        {showBranding && (
          <div className="mt-3 flex flex-col gap-2">
            <a
              href={buyUrl}
              target="_blank"
              rel="noreferrer"
              className="btn border border-[#2AABEE]/30 bg-[#2AABEE]/15 text-xs font-semibold text-[#64D2FF] hover:bg-[#2AABEE]/25"
            >
              Buy License via {botHandle}
            </a>
            <a href={personalTg} target="_blank" rel="noreferrer" className="btn-ghost text-xs">
              Message {personalHandle}
            </a>
          </div>
        )}

        {(auth?.has_saved_license || isConflict) && !onClose && (
          <button
            type="button"
            onClick={switchToFree}
            disabled={busy}
            className="mt-3 w-full py-1.5 text-xs text-zinc-400 hover:text-zinc-200"
          >
            Or continue in Free Tier (50 results cap)
          </button>
        )}

        {onClose && (
          <button onClick={onClose} className="mt-3 w-full py-1.5 text-xs text-zinc-400 hover:text-zinc-200">
            Maybe later — keep using free version
          </button>
        )}
      </div>
    </div>
  );
}

export function AgreementModal({ onAccept, onShowTerms, onShowDisclaimer }) {
  const [checked, setChecked] = useState(false);
  const [err, setErr] = useState(false);

  const accept = () => {
    if (!checked) {
      setErr(true);
      return;
    }
    onAccept();
  };

  return (
    <div className="animate-backdrop-enter fixed inset-0 z-50 grid place-items-center bg-black/75 p-4 backdrop-blur-xl">
      <div className="animate-modal-enter apple-modal w-full max-w-lg p-6">
        <h2 className="mb-2 text-xl font-semibold tracking-tight">Accept Terms to Continue</h2>
        <p className="mb-4 text-sm text-zinc-300">
          By using GME (Google Map Extractor) you agree to be solely responsible for how you use the tool. The developer is not liable for any misuse.
        </p>
        <div className="mb-4 flex gap-3">
          <button onClick={onShowTerms} className="btn-ghost flex-1 text-xs">
            <Icons.FileText className="h-3.5 w-3.5" /> Terms &amp; Agreement
          </button>
          <button onClick={onShowDisclaimer} className="btn-ghost flex-1 text-xs">
            <Icons.Shield className="h-3.5 w-3.5" /> Disclaimer
          </button>
        </div>
        <label className="mt-2 flex cursor-pointer items-start gap-2.5 rounded-xl border border-white/[0.06] bg-white/[0.03] p-3 text-sm text-zinc-300">
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => {
              setChecked(e.target.checked);
              if (e.target.checked) setErr(false);
            }}
            className="mt-1 accent-[#0A84FF]"
          />
          <span>I have read and agree to the Terms &amp; Agreement and Disclaimer. I accept full responsibility for my use of this software.</span>
        </label>
        {err && <p className="mt-2 text-xs font-medium text-[#FF6961]">Please check the box to continue.</p>}
        <button onClick={accept} className="btn-primary mt-4 w-full">
          Accept &amp; Continue
        </button>
      </div>
    </div>
  );
}

export function LegalModal({ title, body, onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="animate-backdrop-enter fixed inset-0 z-[60] grid place-items-center bg-black/75 p-4 backdrop-blur-md"
      onClick={onClose}
    >
      <div className="animate-modal-enter apple-modal max-h-[80vh] w-full max-w-2xl overflow-y-auto p-6" onClick={(e) => e.stopPropagation()}>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
          <button onClick={onClose} className="rounded-lg p-1.5 text-zinc-400 hover:bg-white/[0.08] hover:text-zinc-100">
            <Icons.X className="h-4 w-4" />
          </button>
        </div>
        <div className="whitespace-pre-line text-sm leading-relaxed text-zinc-300">{body}</div>
      </div>
    </div>
  );
}
