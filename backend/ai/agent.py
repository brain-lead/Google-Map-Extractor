"""AI Autopilot & Co-Pilot orchestration: multi-turn tool loop, batch analyzer, NL command bar."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from fastapi import WebSocket

from backend import db
from backend import config as cfg
from backend.ai import config_store, modes, providers, tools
from backend.scraper import enrich

_AI_LOGGER: logging.Logger | None = None
_AI_LOG_PATH: str = ""


def get_ai_logger() -> logging.Logger:
    """Append-only file logger (ai_runs.log) tracking every AI step, function call & outcome."""
    global _AI_LOGGER, _AI_LOG_PATH
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = str(cfg.DATA_DIR / "ai_runs.log")
    if _AI_LOGGER is None or _AI_LOG_PATH != target:
        logger = logging.getLogger("ai_runs")
        for h in list(logger.handlers):
            logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass
        fh = logging.FileHandler(target, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        _AI_LOGGER = logger
        _AI_LOG_PATH = target
    return _AI_LOGGER


def _summarize_tool_result(tool_name: str, res: dict) -> str:
    if not isinstance(res, dict):
        return str(res)[:160]
    if res.get("error"):
        return f"error: {str(res['error'])[:140]}"
    if tool_name == "query_results":
        return f"{len(res.get('items') or [])} returned (total active={res.get('total', 0)}, removed={res.get('removed_count', 0)})"
    if tool_name == "list_jobs":
        return f"{len(res.get('jobs') or [])} job(s)"
    if tool_name == "read_reviews":
        return f"{len(res.get('reviews') or [])} review(s) for {res.get('name', res.get('cid', ''))}"
    if tool_name == "inspect_website":
        st = res.get("site_text") or ""
        return f"{len(st)} chars scraped for {res.get('name', res.get('cid', ''))}"
    if tool_name == "update_lead_intelligence":
        return f"updated {res.get('updated', 0)} lead(s)"
    if tool_name == "remove_leads":
        return f"removed {res.get('removed', 0)} lead(s) (total removed={res.get('total_removed_in_job', 0)})"
    if tool_name == "restore_leads":
        return f"restored {res.get('restored', 0)} lead(s)"
    if tool_name == "apply_table_view":
        return f"view updated (sort={(res.get('view') or {}).get('sort', 'default')})"
    if tool_name in ("start_keyword_search", "start_area_scan"):
        return f"started {res.get('job_id', '')} (max={res.get('max_results', '')})"
    if tool_name == "wait_for_job":
        return f"{res.get('status', '')} ({res.get('scraped', 0)}/{res.get('total', 0)} scraped)"
    if tool_name == "save_to_shortlist":
        return f"saved {res.get('added', 0)} lead(s) to '{res.get('name', '')}'"
    if tool_name == "export_leads":
        return f"ready: {res.get('download_url', '')}"
    return json.dumps(res, ensure_ascii=False)[:140]


class MissionStreamManager:
    """In-memory WebSocket broadcaster + bounded replay for AI missions."""

    def __init__(self, max_history: int = 300):
        self.subscribers: dict[str, set[asyncio.Queue]] = {}
        self.history: dict[str, deque] = {}
        self.max_history = max_history

    def _ensure_hist(self, mission_id: str) -> deque:
        if mission_id not in self.history:
            self.history[mission_id] = deque(maxlen=self.max_history)
        return self.history[mission_id]

    async def send(self, mission_id: str, msg: dict) -> None:
        self._ensure_hist(mission_id).append(msg)
        for q in list(self.subscribers.get(mission_id, ())):
            await q.put(msg)

    async def stream(self, mission_id: str, ws: WebSocket) -> None:
        q: asyncio.Queue = asyncio.Queue()
        subs = self.subscribers.setdefault(mission_id, set())
        subs.add(q)
        try:
            for msg in list(self.history.get(mission_id, ())):
                await ws.send_text(json.dumps(msg, ensure_ascii=False))
            while True:
                msg = await q.get()
                await ws.send_text(json.dumps(msg, ensure_ascii=False))
        finally:
            subs.discard(q)
            if not subs:
                self.subscribers.pop(mission_id, None)


mission_ws = MissionStreamManager()
_CANCEL_FLAGS: dict[str, bool] = {}
_ACTIVE_TASKS: dict[str, asyncio.Task] = {}


def _require_configured() -> None:
    if not config_store.is_configured():
        raise providers.AIProviderError(
            "No AI provider configured yet. Add an API key in Settings → AI Engine to enable AI Autopilot."
        )


def _normalize_why(val) -> str:
    if isinstance(val, list):
        return "\n".join(f"• {str(x).strip()}" for x in val if str(x).strip())
    return str(val or "").strip()


def _normalize_eval_result(raw: dict, mode_id: str) -> dict:
    campaign = {
        "email_subject": str(raw.get("ai_subject") or raw.get("email_subject") or "").strip(),
        "icebreaker": str(raw.get("ai_icebreaker") or raw.get("icebreaker") or "").strip(),
        "call_opener": str(raw.get("ai_call_script") or raw.get("call_opener") or "").strip(),
        "followup": str(raw.get("ai_followup") or raw.get("followup") or "").strip(),
        "opportunity": str(raw.get("ai_opportunity") or raw.get("opportunity") or "").strip(),
    }
    return {
        "ai_score": raw.get("ai_score"),
        "ai_affordability": raw.get("ai_affordability") or "Medium",
        "ai_need": raw.get("ai_need") or "Medium",
        "ai_verdict": raw.get("ai_verdict") or "Good Fit",
        "ai_owner": str(raw.get("ai_owner") or "").strip(),
        "ai_why": _normalize_why(raw.get("ai_why")),
        "ai_pain_points": raw.get("ai_pain_points") or [],
        "ai_campaign": campaign,
        "ai_mode": mode_id,
    }


def _build_mission_system_prompt(mission: dict, mode_id: str, offer: dict | None) -> str:
    mode = modes.BUILTIN_MODES.get(mode_id, modes.BUILTIN_MODES["custom"])
    offer_txt = ""
    if offer:
        svc = offer.get("service_type") or offer.get("service") or ""
        budget = offer.get("min_budget") or offer.get("price") or ""
        niche = offer.get("target_niche") or offer.get("icp_rules") or ""
        notes = offer.get("pitch_notes") or offer.get("tone") or ""
        offer_txt = (
            f"\nACTIVE SAVED OFFER PROFILE ('{offer.get('name', '')}'):\n"
            f"- Service: {svc}\n"
            f"- Target Budget/Retainer: {budget}\n"
            f"- Target Niche / ICP: {niche}\n"
            f"- Pitch Notes: {notes}\n"
        )
    active_job = mission.get("job_id") or ""
    if active_job:
        try:
            f = db.get_facets(active_job).get("counts") or {}
            tot = int(f.get("total") or 0)
            ana = int(f.get("ai_analyzed") or 0)
            rem_unscored = max(0, tot - ana)
            removed = int(f.get("removed_count") or 0)
            job_txt = (
                f"\nCURRENT ATTACHED DATASET JOB ID: {active_job} "
                f"(active leads={tot}, ai_analyzed={ana}, remaining_unanalyzed={rem_unscored}, removed={removed})"
            )
        except Exception:
            job_txt = f"\nCURRENT ATTACHED DATASET JOB ID: {active_job}"
    else:
        job_txt = "\nCURRENT DATASET JOB ID: None yet."
    return (
        "You are GME AI Copilot, an intelligent assistant and autonomous operator inside Google Map Extractor (GME).\n\n"
        f"ACTIVE MODE: {mode['label']} ({mode['id']})\n"
        f"FOCUS: {mode['focus']}\n"
        f"{offer_txt}{job_txt}\n\n"
        "HOW TO DECIDE WHAT TO DO:\n"
        "- Decide naturally on every message whether the user is asking a conversational/follow-up question "
        "(e.g. 'why do you recommend these?', 'list those again', 'clarify X') OR giving you a task to execute.\n"
        "- For conversational questions about work already done, simply answer directly and clearly using what you know — "
        "do NOT call tools or re-scrape unnecessarily unless you actually lack facts from the database.\n"
        "- When the user gives you a task (finding, researching, cleaning, scoring, ranking, shortlisting, or exporting leads), "
        "plan and run the needed tools on your own without asking permission.\n"
        "- Broad/open-sector requests (e.g. 'best local businesses needing a mobile app/website in Nigeria' with no specific category): "
        "think carefully across 4–6 diverse high-affordability local sectors for that service and search them together via a "
        "comma-separated `query` in `start_keyword_search` (e.g. 'private hospital clinic, boutique hotel, car dealership, "
        "fitness studio, salon spa, real estate agency') so all sectors land in one table for fair comparison.\n"
        "- Ground every claim in real evidence from `inspect_website` / `read_reviews` / database fields (never invent facts). "
        "Whenever you qualify or filter leads during a task, persist your scores with `update_lead_intelligence`, hide non-fits "
        "with `remove_leads`, and update the live view (`apply_table_view`) so the user's Results table reflects your work.\n"
        "- Reply in clean, readable Markdown."
    )


def _load_history_for_llm(mission_id: str, limit: int = 16) -> list[dict]:
    """Convert persisted chat turns cleanly into alternating user/assistant messages."""
    rows = db.list_mission_messages(mission_id, limit=250)
    convo: list[dict] = []
    pending_tools: list[str] = []
    touched_cids: list[str] = []

    def _synthesize_interrupted_tools():
        if not pending_tools:
            return
        lines = pending_tools[-10:]
        cid_line = f"\nAlready handled CIDs ({len(touched_cids)}): {', '.join(touched_cids[-20:])}" if touched_cids else ""
        convo.append({
            "role": "assistant",
            "content": "Completed prior tool calls (run ended before final reply):\n" + "\n".join(lines) + cid_line,
        })
        pending_tools.clear()

    for r in rows:
        role = r.get("role")
        if role == "tool":
            tname = r.get("tool_name") or "tool"
            jid = r.get("job_id") or ""
            try:
                args_obj = json.loads(r.get("tool_args") or "{}")
            except Exception:
                args_obj = {}
            if isinstance(args_obj, dict):
                if args_obj.get("cid") and args_obj["cid"] not in touched_cids:
                    touched_cids.append(str(args_obj["cid"]))
                for u in args_obj.get("updates") or []:
                    if isinstance(u, dict) and u.get("cid") and u["cid"] not in touched_cids:
                        touched_cids.append(str(u["cid"]))
            summary = (r.get("content") or "").strip() or (r.get("tool_result") or "")[:200]
            pending_tools.append(f"- {tname}{' job=' + jid if jid else ''}: {summary}")
        elif role == "user":
            _synthesize_interrupted_tools()
            txt = r.get("content") or ""
            if convo and convo[-1]["role"] == "user":
                convo.append({"role": "assistant", "content": "(Continuing from previous user request.)"})
            convo.append({"role": "user", "content": txt})
        elif role == "assistant":
            # A finished assistant reply already summarizes its preceding tools cleanly; discard raw noise.
            pending_tools.clear()
            txt = (r.get("content") or "").strip()
            if convo and convo[-1]["role"] == "assistant":
                convo[-1]["content"] = (convo[-1]["content"] + "\n" + txt).strip()
            else:
                convo.append({"role": "assistant", "content": txt})

    _synthesize_interrupted_tools()
    return convo[-limit:]


async def _run_mission_turn(mission_id: str, user_message: str) -> None:
    _CANCEL_FLAGS[mission_id] = False
    try:
        _require_configured()
        mission = db.get_mission(mission_id)
        if not mission:
            return
        db.update_mission(mission_id, status="running", error="")
        await mission_ws.send(mission_id, {"type": "status", "status": "running", "mission_id": mission_id})

        mode_id = mission.get("mode_id") or "custom"
        mission_model = (mission.get("model") or "").strip() or None
        offer = db.get_offer(mission.get("offer_id") or "")
        _t_mission_start = time.time()
        rt = config_store.get_runtime_config()
        guardrails = rt.get("guardrails") or dict(config_store.DEFAULT_GUARDRAILS)
        max_steps = max(2, min(40, int(guardrails.get("max_steps", 18))))
        log = get_ai_logger()
        log.info(
            "[%s] MISSION_START mode=%s model=%s offer=%s job=%s goal=%r",
            mission_id, mode_id, mission_model or rt.get("selected_models", {}).get(rt.get("provider", ""), "") or rt.get("tier"),
            mission.get("offer_id") or "-", mission.get("job_id") or "-", user_message[:300],
        )

        async def _emit(payload: dict) -> None:
            await mission_ws.send(mission_id, payload)

        ctx = tools.MissionContext(
            mission_id=mission_id,
            active_job_id=mission.get("job_id") or "",
            mode_id=mode_id,
            offer=offer,
            guardrails=guardrails,
            is_cancelled=lambda: bool(_CANCEL_FLAGS.get(mission_id)),
            emit=_emit,
        )

        system_prompt = _build_mission_system_prompt(mission, mode_id, offer)
        turn_messages = _load_history_for_llm(mission_id)
        if not turn_messages or turn_messages[-1]["role"] != "user":
            turn_messages.append({"role": "user", "content": user_message})

        final_text = ""
        final_status = "completed"
        usage_totals = {"input_tokens": 0, "cached_tokens": 0, "output_tokens": 0}
        for step in range(max_steps):
            if _CANCEL_FLAGS.get(mission_id):
                db.update_mission(mission_id, status="cancelled")
                log.info("[%s] MISSION_CANCELLED step=%d", mission_id, step + 1)
                await mission_ws.send(mission_id, {"type": "done", "status": "cancelled", "mission_id": mission_id, "usage": usage_totals})
                return

            await mission_ws.send(mission_id, {
                "type": "step",
                "step": step + 1,
                "max_steps": max_steps,
                "message": "Thinking and planning next action…" if step == 0 else "Reviewing findings…",
                "usage": usage_totals,
            })

            _t_llm = time.time()
            res = await providers.run_tool_turn(
                turn_messages,
                tools=tools.TOOL_DEFS,
                system_prompt=system_prompt,
                model=mission_model,
            )
            llm_ms = int((time.time() - _t_llm) * 1000)
            u = res.get("usage") or {}
            usage_totals["input_tokens"] += int(u.get("input_tokens") or 0)
            usage_totals["cached_tokens"] += int(u.get("cached_tokens") or 0)
            usage_totals["output_tokens"] += int(u.get("output_tokens") or 0)

            tcalls = res.get("tool_calls") or []
            text = (res.get("text") or "").strip()
            log.info(
                "[%s] LLM_TURN step=%d ms=%d in=%d cached=%d out=%d calls=%s",
                mission_id, step + 1, llm_ms,
                int(u.get("input_tokens") or 0), int(u.get("cached_tokens") or 0),
                int(u.get("output_tokens") or 0), [tc["name"] for tc in tcalls],
            )

            if not tcalls:
                final_text = text or "Task finished."
                break

            turn_msg = {"role": "assistant", "content": text, "tool_calls": tcalls}
            if res.get("gemini_parts"):
                turn_msg["gemini_parts"] = res["gemini_parts"]
            turn_messages.append(turn_msg)

            for tc in tcalls:
                if _CANCEL_FLAGS.get(mission_id):
                    db.update_mission(mission_id, status="cancelled")
                    log.info("[%s] MISSION_CANCELLED during_tool=%s", mission_id, tc["name"])
                    await mission_ws.send(mission_id, {"type": "done", "status": "cancelled", "mission_id": mission_id, "usage": usage_totals})
                    return

                tname = tc["name"]
                targs = tc.get("arguments") or {}
                call_id = tc["id"]
                log.info("[%s] TOOL_CALL step=%d call=%s fn=%s args=%s",
                         mission_id, step + 1, call_id, tname, json.dumps(targs, ensure_ascii=False)[:800])
                await mission_ws.send(mission_id, {
                    "type": "tool_call",
                    "call_id": call_id,
                    "step": step + 1,
                    "tool": tname,
                    "args": targs,
                })

                _t_tool = time.time()
                try:
                    tresult = await tools.execute_tool(tname, targs, ctx)
                except Exception as exc:
                    tresult = {"error": str(exc)}
                tool_ms = int((time.time() - _t_tool) * 1000)
                summary = _summarize_tool_result(tname, tresult)
                log.info("[%s] TOOL_DONE step=%d call=%s fn=%s ms=%d ok=%s summary=%s",
                         mission_id, step + 1, call_id, tname, tool_ms,
                         not (isinstance(tresult, dict) and tresult.get("error")), summary)

                # Annotate metadata on stored result cleanly so audit history shows duration & summary
                stored_res = dict(tresult) if isinstance(tresult, dict) else {"value": tresult}
                stored_res["_meta"] = {"step": step + 1, "duration_ms": tool_ms, "summary": summary}

                res_json = json.dumps(tresult, ensure_ascii=False)
                db.add_mission_message(
                    mission_id,
                    role="tool",
                    content=summary,
                    tool_name=tname,
                    tool_args=targs,
                    tool_result=stored_res,
                    job_id=ctx.active_job_id,
                )
                await mission_ws.send(mission_id, {
                    "type": "tool_result",
                    "call_id": call_id,
                    "step": step + 1,
                    "tool": tname,
                    "args": targs,
                    "result": tresult,
                    "summary": summary,
                    "duration_ms": tool_ms,
                    "active_job_id": ctx.active_job_id,
                })

                # Cap huge tool outputs so token limits aren't blown
                llm_content = res_json if len(res_json) <= 18000 else res_json[:18000] + '... [truncated]"}'
                turn_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "name": tname,
                    "content": llm_content,
                })
        else:
            # Hit max_steps: ask for final summary without tools and mark status='incomplete' so UI shows Continue!
            final_status = "incomplete"
            turn_messages.append({
                "role": "user",
                "content": "Maximum tool steps reached for this turn. Summarize everything found, cleaned, scored, and recommended so far, and note what remains if the user asks to continue.",
            })
            wrap = await providers.run_tool_turn(
                turn_messages, tools=None, system_prompt=system_prompt, model=mission_model
            )
            wu = wrap.get("usage") or {}
            usage_totals["input_tokens"] += int(wu.get("input_tokens") or 0)
            usage_totals["cached_tokens"] += int(wu.get("cached_tokens") or 0)
            usage_totals["output_tokens"] += int(wu.get("output_tokens") or 0)
            final_text = (wrap.get("text") or "").strip() or "Reached the step limit for this turn. Click Continue to process the remaining leads."

        db.add_mission_message(mission_id, role="assistant", content=final_text, job_id=ctx.active_job_id)
        db.update_mission(
            mission_id,
            status=final_status,
            job_id=ctx.active_job_id,
            summary=final_text[:500],
        )
        log.info(
            "[%s] MISSION_DONE status=%s sec=%.2f in=%d cached=%d out=%d job=%s",
            mission_id, final_status, time.time() - _t_mission_start,
            usage_totals["input_tokens"], usage_totals["cached_tokens"], usage_totals["output_tokens"],
            ctx.active_job_id or "-",
        )
        await mission_ws.send(mission_id, {
            "type": "assistant_message",
            "content": final_text,
            "job_id": ctx.active_job_id,
            "usage": usage_totals,
        })
        await mission_ws.send(mission_id, {
            "type": "done",
            "status": final_status,
            "mission_id": mission_id,
            "job_id": ctx.active_job_id,
            "last_view": ctx.last_view,
            "usage": usage_totals,
        })

    except Exception as exc:
        err = str(exc)
        try:
            get_ai_logger().error("[%s] MISSION_FAILED err=%s", mission_id, err)
        except Exception:
            pass
        db.update_mission(mission_id, status="failed", error=err)
        db.add_mission_message(mission_id, role="assistant", content=f"Error: {err}")
        await mission_ws.send(mission_id, {"type": "error", "message": err, "mission_id": mission_id})
    finally:
        _ACTIVE_TASKS.pop(mission_id, None)


async def start_mission(goal: str, mode_id: str = "custom", offer_id: str = "",
                        job_id: str = "", title: str = "", model: str = "") -> dict:
    _require_configured()
    mission = db.create_mission(goal=goal, mode_id=mode_id, offer_id=offer_id, job_id=job_id, title=title, model=model)
    db.add_mission_message(mission["id"], role="user", content=goal, job_id=job_id)
    mission_ws.history[mission["id"]] = deque(maxlen=mission_ws.max_history)
    task = asyncio.create_task(_run_mission_turn(mission["id"], goal))
    _ACTIVE_TASKS[mission["id"]] = task
    return mission


async def send_mission_message(mission_id: str, message: str, mode_id: str | None = None,
                               offer_id: str | None = None, job_id: str | None = None,
                               model: str | None = None) -> dict:
    _require_configured()
    mission = db.get_mission(mission_id)
    if not mission:
        raise ValueError("Mission not found")
    existing = _ACTIVE_TASKS.get(mission_id)
    if existing and not existing.done():
        raise RuntimeError("This mission is currently running a step. Stop it or wait for completion.")
    upd = {}
    if mode_id is not None:
        upd["mode_id"] = mode_id
    if offer_id is not None:
        upd["offer_id"] = offer_id
    if job_id is not None:
        upd["job_id"] = job_id
    if model is not None:
        upd["model"] = model
    if upd:
        db.update_mission(mission_id, **upd)
    db.add_mission_message(mission_id, role="user", content=message, job_id=job_id or mission.get("job_id") or "")
    # Reset live WS buffer for the new turn so old turn steps are never replayed as current progress
    mission_ws.history[mission_id] = deque(maxlen=mission_ws.max_history)
    task = asyncio.create_task(_run_mission_turn(mission_id, message))
    _ACTIVE_TASKS[mission_id] = task
    return db.get_mission(mission_id) or mission


async def cancel_mission(mission_id: str) -> dict:
    _CANCEL_FLAGS[mission_id] = True
    mission = db.get_mission(mission_id) or {}
    if mission.get("job_id"):
        from backend import jobs as job_runner
        await job_runner.cancel_job(mission["job_id"])
    db.update_mission(mission_id, status="cancelled")
    return {"mission_id": mission_id, "status": "cancelling"}


# ─── Inline Co-Pilot Actions (ResultsView / BusinessModal / ReportModal) ──────

async def analyze_job_leads(job_id: str, mode_id: str = "web_seo", offer_id: str = "",
                            custom_instruction: str = "", cids: list[str] | None = None,
                            limit: int = 25, model: str | None = None) -> dict:
    """Evaluate top leads (or specific CIDs) in a job using the active AI provider."""
    _require_configured()
    job = db.get_job(job_id)
    if not job:
        raise ValueError("Job not found")
    offer = db.get_offer(offer_id) if offer_id else None

    if cids:
        rows = [db.get_result_by_cid(job_id, c) for c in cids]
        targets = [r for r in rows if r]
    else:
        targets = db.get_results(job_id, limit=max(1, min(60, int(limit or 25))),
                                 filters={"sort": "lead_desc"})["items"]

    sem = asyncio.Semaphore(4)
    analyzed = 0
    errors: list[str] = []
    updated_items: list[dict] = []

    async def _eval_one(lead: dict):
        nonlocal analyzed
        async with sem:
            cid = lead.get("cid")
            if not cid:
                return
            work_lead = dict(lead)
            # Scrape website text on demand if missing and URL exists
            website = (work_lead.get("website") or "").strip()
            if website.startswith("http") and not (work_lead.get("site_text") or "").strip():
                try:
                    enr = await asyncio.to_thread(enrich.enrich_website, website)
                    st = (enr.get("site_text") or "").strip()
                    extra = {}
                    if enr.get("emails"):
                        extra["emails"] = json.dumps(enr["emails"])
                        if not work_lead.get("email"):
                            extra["email"] = enr["emails"][0]
                    if enr.get("socials"):
                        extra["socials"] = json.dumps(enr["socials"])
                    if enr.get("web"):
                        extra["web_tech"] = json.dumps(enr["web"])
                    db.update_result_site_text(job_id, cid, st, extra=extra)
                    work_lead["site_text"] = st
                    if extra.get("web_tech"):
                        work_lead["web_tech"] = extra["web_tech"]
                except Exception:
                    pass

            sys_p, user_p = modes.build_lead_eval_prompt(
                work_lead, mode_id=mode_id, offer=offer, custom_instruction=custom_instruction
            )
            try:
                raw = await providers.complete_json(sys_p, user_p, model=model or None)
                if isinstance(raw, dict):
                    norm = _normalize_eval_result(raw, mode_id)
                    db.update_lead_ai(job_id, cid, norm)
                    analyzed += 1
                    updated_items.append({"cid": cid, **norm})
            except Exception as e:
                errors.append(f"{lead.get('name', cid)}: {e}")

    await asyncio.gather(*(_eval_one(l) for l in targets))
    return {"job_id": job_id, "analyzed": analyzed, "errors": errors[:5], "items": updated_items}


COMMAND_TOOLS = [
    t for t in tools.TOOL_DEFS
    if t["name"] in {
        "query_results", "read_reviews", "inspect_website", "apply_table_view",
        "remove_leads", "restore_leads", "update_lead_intelligence",
        "rescore_job", "save_to_shortlist", "list_shortlists", "export_leads",
    }
]


async def parse_and_run_command(job_id: str, command_text: str, mode_id: str = "custom",
                                offer_id: str = "", model: str | None = None) -> dict:
    """Execute a natural-language command directly against an existing job's table."""
    _require_configured()
    job = db.get_job(job_id)
    if not job:
        raise ValueError("Job not found")
    cmd = (command_text or "").strip()
    if not cmd:
        raise ValueError("Command cannot be empty")

    # Fast local shortcut for unambiguous Undo/Restore commands
    if re.fullmatch(r"(undo|restore|restore\s+all|undo\s+all|undo\s+remove[d]?)", cmd, re.I):
        restored = db.restore_leads(job_id)
        return {
            "summary": f"Restored {restored} removed lead(s) back into the table.",
            "view": {"sort": "default"},
            "removed": 0,
            "restored": restored,
        }

    facets = db.get_facets(job_id)
    offer = db.get_offer(offer_id) if offer_id else None
    mode = modes.BUILTIN_MODES.get(mode_id, modes.BUILTIN_MODES["custom"])

    events: dict = {"removed": 0, "restored": 0, "view": None, "shortlists": [], "exports": []}

    async def _collect(payload: dict) -> None:
        tp = payload.get("type")
        if tp == "ui_view":
            events["view"] = payload.get("view")
        elif tp == "ui_table_changed":
            if payload.get("action") == "removed":
                events["removed"] += int(payload.get("count") or 0)
            elif payload.get("action") == "restored":
                events["restored"] += int(payload.get("count") or 0)
        elif tp == "ui_shortlist_updated":
            events["shortlists"].append(payload)
        elif tp == "ui_export_ready":
            events["exports"].append(payload)

    ctx = tools.MissionContext(
        mission_id=f"cmd_{job_id}",
        active_job_id=job_id,
        mode_id=mode_id,
        offer=offer,
        emit=_collect,
    )

    sys_p = (
        f"You are GME Table Command Assistant operating on job '{job_id}' "
        f"({job.get('query')} in {job.get('location')}). "
        f"Active Mode: {mode['label']} — {mode['focus']}. "
        f"Dataset summary: {json.dumps(facets.get('counts') or {})}.\n"
        "Inspect matching leads with `query_results`, execute the requested action(s) "
        "(such as `remove_leads`, `restore_leads`, `update_lead_intelligence`, `apply_table_view`, "
        "`rescore_job`, `save_to_shortlist`, or `export_leads`), and respond with a 1-2 sentence summary."
    )
    log = get_ai_logger()
    log.info("[%s] INLINE_CMD cmd=%r", job_id, cmd[:300])
    msgs: list[dict] = [{"role": "user", "content": cmd}]
    final_summary = ""
    for _ in range(6):
        res = await providers.run_tool_turn(msgs, tools=COMMAND_TOOLS, system_prompt=sys_p, model=model or None)
        tcalls = res.get("tool_calls") or []
        txt = (res.get("text") or "").strip()
        if not tcalls:
            final_summary = txt
            break
        am = {"role": "assistant", "content": txt, "tool_calls": tcalls}
        if res.get("gemini_parts"):
            am["gemini_parts"] = res["gemini_parts"]
        msgs.append(am)
        for tc in tcalls:
            try:
                tres = await tools.execute_tool(tc["name"], tc.get("arguments") or {}, ctx)
            except Exception as e:
                tres = {"error": str(e)}
            log.info("[%s] INLINE_TOOL fn=%s args=%s -> %s",
                     job_id, tc["name"], json.dumps(tc.get("arguments") or {}, ensure_ascii=False)[:400],
                     _summarize_tool_result(tc["name"], tres))
            raw_json = json.dumps(tres, ensure_ascii=False)
            msgs.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": tc["name"],
                "content": raw_json if len(raw_json) <= 16000 else raw_json[:16000] + '..."}',
            })

    return {
        "job_id": job_id,
        "summary": final_summary or "Table command completed.",
        "view": events["view"],
        "removed": events["removed"],
        "restored": events["restored"],
        "shortlists": events["shortlists"],
        "exports": events["exports"],
    }


def read_ai_log_tail(mission_id: str = "", limit: int = 250) -> list[str]:
    """Read tail lines of DATA_DIR/ai_runs.log (optionally filtered to one mission_id)."""
    p = cfg.DATA_DIR / "ai_runs.log"
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    if mission_id:
        tag = f"[{mission_id}]"
        lines = [ln for ln in lines if tag in ln]
    return lines[-max(1, min(1000, int(limit or 250))):]


async def generate_job_market_brief(job_id: str, mode_id: str = "market_research") -> dict:
    _require_configured()
    job = db.get_job(job_id)
    if not job:
        raise ValueError("Job not found")
    facets = db.get_facets(job_id)
    top_leads = db.get_results(job_id, limit=20, filters={"sort": "lead_desc"})["items"]
    sys_p, user_p = modes.build_market_brief_prompt(job, facets, top_leads, mode_id=mode_id)
    brief = await providers.complete_json(sys_p, user_p)
    return {"job_id": job_id, "brief": brief if isinstance(brief, dict) else {"headline": str(brief)}}
