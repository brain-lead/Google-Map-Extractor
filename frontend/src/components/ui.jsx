import React, { useId, useState } from "react";

export function GmeLogo({ size = 38, className = "" }) {
  const uid = useId().replace(/:/g, "");
  const bgId = `gme_bg_${uid}`;
  const glowId = `gme_glow_${uid}`;
  const pinId = `gme_pin_${uid}`;
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 128 128"
      fill="none"
      className={`shrink-0 drop-shadow-[0_6px_18px_rgba(10,132,255,0.35)] ${className}`}
      aria-label="GME Google Map Extractor logo"
    >
      <defs>
        <linearGradient id={bgId} x1="12" y1="8" x2="116" y2="120" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#0A84FF" />
          <stop offset="55%" stopColor="#0055D4" />
          <stop offset="100%" stopColor="#0C2444" />
        </linearGradient>
        <radialGradient
          id={glowId}
          cx="0"
          cy="0"
          r="1"
          gradientUnits="userSpaceOnUse"
          gradientTransform="translate(96 24) rotate(135) scale(88)"
        >
          <stop offset="0%" stopColor="#30D158" stopOpacity="0.72" />
          <stop offset="65%" stopColor="#30D158" stopOpacity="0" />
        </radialGradient>
        <linearGradient id={pinId} x1="64" y1="20" x2="64" y2="94" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#FFFFFF" />
          <stop offset="100%" stopColor="#DCEBFF" />
        </linearGradient>
      </defs>
      <rect x="4" y="4" width="120" height="120" rx="28" fill={`url(#${bgId})`} />
      <rect x="4" y="4" width="120" height="120" rx="28" fill={`url(#${glowId})`} />
      <rect x="4.75" y="4.75" width="118.5" height="118.5" rx="27.25" stroke="rgba(255,255,255,0.28)" strokeWidth="1.5" />
      <circle cx="64" cy="52" r="36" stroke="rgba(255,255,255,0.16)" strokeWidth="1.5" strokeDasharray="4 4" />
      <circle cx="64" cy="52" r="26" stroke="rgba(255,255,255,0.22)" strokeWidth="1.2" />
      <path d="M64 21C47.4 21 34 34.4 34 51C34 71.5 64 96 64 96C64 96 94 71.5 94 51C94 34.4 80.6 21 64 21Z" fill={`url(#${pinId})`} />
      <circle cx="64" cy="50" r="11" fill="#0A84FF" />
      <circle cx="64" cy="50" r="4.5" fill="#30D158" />
      <rect x="33" y="92" width="62" height="22" rx="11" fill="rgba(7,12,24,0.86)" stroke="rgba(255,255,255,0.28)" strokeWidth="1.2" />
      <text
        x="64"
        y="107.2"
        textAnchor="middle"
        fill="#FFFFFF"
        fontFamily="-apple-system, BlinkMacSystemFont, 'SF Pro Display', Inter, sans-serif"
        fontSize="12.5"
        fontWeight="800"
        letterSpacing="1.4"
      >
        GME
      </text>
    </svg>
  );
}

export function tryJson(s, fallback) {
  try {
    const v = JSON.parse(s);
    return v ?? fallback;
  } catch {
    return fallback;
  }
}

export function mapsLink(b) {
  if (b.cid) return `https://www.google.com/maps?cid=${b.cid}`;
  if (b.place_id) return `https://www.google.com/maps/place/?ftid=${b.place_id}`;
  return "https://www.google.com/maps";
}

export function leadColor(grade) {
  if (grade === "Hot") {
    return {
      bg: "bg-[#FF453A]/15",
      text: "text-[#FF6961]",
      ring: "ring-1 ring-[#FF453A]/35",
      hex: "#FF453A",
    };
  }
  if (grade === "Warm") {
    return {
      bg: "bg-[#FF9F0A]/15",
      text: "text-[#FFB340]",
      ring: "ring-1 ring-[#FF9F0A]/35",
      hex: "#FF9F0A",
    };
  }
  if (grade === "Closed") {
    return {
      bg: "bg-zinc-500/20",
      text: "text-zinc-400",
      ring: "ring-1 ring-zinc-500/30",
      hex: "#71717a",
    };
  }
  return {
    bg: "bg-[#0A84FF]/15",
    text: "text-[#64D2FF]",
    ring: "ring-1 ring-[#0A84FF]/35",
    hex: "#0A84FF",
  };
}

export function StatusBadge({ status }) {
  const styles = {
    pending: "bg-[#FF9F0A]/15 text-[#FFB340] border-[#FF9F0A]/30",
    running: "bg-[#0A84FF]/15 text-[#64D2FF] border-[#0A84FF]/35",
    completed: "bg-[#30D158]/15 text-[#30D158] border-[#30D158]/30",
    incomplete: "bg-[#FF9F0A]/15 text-[#FFB340] border-[#FF9F0A]/30",
    failed: "bg-[#FF453A]/15 text-[#FF6961] border-[#FF453A]/30",
    cancelled: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
    cancelling: "bg-zinc-500/15 text-zinc-300 border-zinc-500/30",
    interrupted: "bg-[#FF9F0A]/15 text-[#FFB340] border-[#FF9F0A]/30",
  };
  const live = status === "running" || status === "pending";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium capitalize ${
        styles[status] || "bg-zinc-800 text-zinc-300 border-white/10"
      }`}
    >
      {live && <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />}
      {status}
    </span>
  );
}

export function StarRating({ value }) {
  if (value == null) return <span className="text-xs text-zinc-500">No rating</span>;
  const pct = Math.max(0, Math.min(100, (value / 5) * 100));
  return (
    <span className="relative inline-flex text-xs leading-none tracking-tight">
      <span className="text-zinc-700">★★★★★</span>
      <span className="absolute inset-0 overflow-hidden text-[#FF9F0A]" style={{ width: `${pct}%` }}>
        ★★★★★
      </span>
    </span>
  );
}

const IconBase = ({ children, className = "h-4 w-4", ...props }) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.65"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
    {...props}
  >
    {children}
  </svg>
);

export const Icons = {
  Search: (p) => (
    <IconBase {...p}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </IconBase>
  ),
  History: (p) => (
    <IconBase {...p}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
      <path d="M12 7v5l3 2" />
    </IconBase>
  ),
  Cookie: (p) => (
    <IconBase {...p}>
      <path d="M12 2a10 10 0 1 0 10 10 4 4 0 0 1-5-5 4 4 0 0 1-5-5" />
      <circle cx="8.5" cy="11.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="11" cy="16" r="1" fill="currentColor" stroke="none" />
      <circle cx="15.5" cy="14" r="1" fill="currentColor" stroke="none" />
    </IconBase>
  ),
  Shield: (p) => (
    <IconBase {...p}>
      <path d="M12 3 4 6v6c0 5 3.4 8.7 8 10 4.6-1.3 8-5 8-10V6l-8-3Z" />
      <path d="m9 12 2 2 4-4" />
    </IconBase>
  ),
  Globe: (p) => (
    <IconBase {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M3.6 9h16.8M3.6 15h16.8" />
      <path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z" />
    </IconBase>
  ),
  Sliders: (p) => (
    <IconBase {...p}>
      <path d="M4 7h16M4 17h16M9 4v6M15 14v6" />
    </IconBase>
  ),
  MapPin: (p) => (
    <IconBase {...p}>
      <path d="M12 21s-6-5.3-6-10a6 6 0 1 1 12 0c0 4.7-6 10-6 10Z" />
      <circle cx="12" cy="11" r="2.2" />
    </IconBase>
  ),
  Phone: (p) => (
    <IconBase {...p}>
      <path d="M22 16.9v3a2 2 0 0 1-2.2 2A19.8 19.8 0 0 1 3.1 5.2 2 2 0 0 1 5.1 3h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.6a2 2 0 0 1-.4 2.1L9.1 10.7a16 16 0 0 0 4.2 4.2l1.3-1.3a2 2 0 0 1 2.1-.4c.8.3 1.7.6 2.6.7a2 2 0 0 1 1.7 2Z" />
    </IconBase>
  ),
  Mail: (p) => (
    <IconBase {...p}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </IconBase>
  ),
  Clock: (p) => (
    <IconBase {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </IconBase>
  ),
  Copy: (p) => (
    <IconBase {...p}>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </IconBase>
  ),
  Check: (p) => (
    <IconBase {...p}>
      <path d="m5 12 5 5L20 7" />
    </IconBase>
  ),
  Download: (p) => (
    <IconBase {...p}>
      <path d="M12 3v12m0 0-4-4m4 4 4-4M4 19h16" />
    </IconBase>
  ),
  FileText: (p) => (
    <IconBase {...p}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z" />
      <path d="M14 2v6h6M8 13h8M8 17h5" />
    </IconBase>
  ),
  Bell: (p) => (
    <IconBase {...p}>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </IconBase>
  ),
  Refresh: (p) => (
    <IconBase {...p}>
      <path d="M21 12a9 9 0 0 0-15.5-6.3L3 8" />
      <path d="M3 3v5h5" />
      <path d="M3 12a9 9 0 0 0 15.5 6.3L21 16" />
      <path d="M21 21v-5h-5" />
    </IconBase>
  ),
  Trash: (p) => (
    <IconBase {...p}>
      <path d="M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
    </IconBase>
  ),
  Play: (p) => (
    <IconBase {...p}>
      <polygon points="6 4 20 12 6 20 6 4" fill="currentColor" stroke="none" />
    </IconBase>
  ),
  Square: (p) => (
    <IconBase {...p}>
      <rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor" stroke="none" />
    </IconBase>
  ),
  Sparkles: (p) => (
    <IconBase {...p}>
      <path d="m12 3 1.8 4.5L18.5 9l-4.7 1.5L12 15l-1.8-4.5L5.5 9l4.7-1.5L12 3Z" />
      <path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z" />
    </IconBase>
  ),
  Grid: (p) => (
    <IconBase {...p}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </IconBase>
  ),
  Table: (p) => (
    <IconBase {...p}>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 10h18M9 10v10" />
    </IconBase>
  ),
  Map: (p) => (
    <IconBase {...p}>
      <path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3V6Z" />
      <path d="M9 3v15M15 6v15" />
    </IconBase>
  ),
  Key: (p) => (
    <IconBase {...p}>
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="m21 2-9.6 9.6M15.5 7.5 19 11" />
    </IconBase>
  ),
  X: (p) => (
    <IconBase {...p}>
      <path d="M18 6 6 18M6 6l12 12" />
    </IconBase>
  ),
  ExternalLink: (p) => (
    <IconBase {...p}>
      <path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
    </IconBase>
  ),
  Building: (p) => (
    <IconBase {...p}>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M10 21v-3h4v3" />
    </IconBase>
  ),
  Send: (p) => (
    <IconBase {...p}>
      <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7Z" />
    </IconBase>
  ),
  Bookmark: (p) => (
    <IconBase {...p}>
      <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
    </IconBase>
  ),
  RotateCcw: (p) => (
    <IconBase {...p}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5" />
    </IconBase>
  ),
  Maximize: (p) => (
    <IconBase {...p}>
      <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
    </IconBase>
  ),
  Minimize: (p) => (
    <IconBase {...p}>
      <path d="M4 14h6v6M20 10h-6V4M14 10l7-7M10 14l-7 7" />
    </IconBase>
  ),
  ChevronLeft: (p) => (
    <IconBase {...p}>
      <path d="m15 18-6-6 6-6" />
    </IconBase>
  ),
  ChevronRight: (p) => (
    <IconBase {...p}>
      <path d="m9 18 6-6-6-6" />
    </IconBase>
  ),
};

function renderInlineMarkdown(text) {
  const nodes = [];
  const pattern = /(\[[^\]]+\]\((?:https?:\/\/|\/)[^\s)]+\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*)/g;
  let lastIdx = 0;
  let match;
  let k = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIdx) nodes.push(text.slice(lastIdx, match.index));
    const tok = match[0];
    if (tok.startsWith("[")) {
      const m = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (m) {
        nodes.push(
          <a key={k++} href={m[2]} target="_blank" rel="noreferrer" className="text-[#409CFF] underline decoration-[#409CFF]/40 underline-offset-2 hover:text-[#64D2FF]">
            {m[1]}
          </a>
        );
      } else {
        nodes.push(tok);
      }
    } else if (tok.startsWith("`")) {
      nodes.push(
        <code key={k++} className="rounded bg-white/[0.08] px-1.5 py-0.5 font-mono text-[11px] text-[#64D2FF]">
          {tok.slice(1, -1)}
        </code>
      );
    } else if (tok.startsWith("**")) {
      nodes.push(
        <strong key={k++} className="font-semibold text-white">
          {tok.slice(2, -2)}
        </strong>
      );
    } else if (tok.startsWith("*")) {
      nodes.push(
        <em key={k++} className="italic text-zinc-200">
          {tok.slice(1, -1)}
        </em>
      );
    }
    lastIdx = match.index + tok.length;
  }
  if (lastIdx < text.length) nodes.push(text.slice(lastIdx));
  return nodes.length ? nodes : text;
}

export function MarkdownView({ text = "" }) {
  const src = String(text || "").replace(/\r\n/g, "\n");
  if (!src.trim()) return null;

  const blocks = [];
  const lines = src.split("\n");
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.trim().startsWith("```")) {
      const lang = line.trim().slice(3).trim();
      const buf = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i++;
      }
      i++;
      blocks.push(
        <div key={key++} className="overflow-hidden rounded-xl border border-white/[0.08] bg-black/50">
          {lang && <div className="border-b border-white/[0.06] px-3 py-1 text-[10px] uppercase tracking-wider text-zinc-500">{lang}</div>}
          <pre className="overflow-x-auto p-3 font-mono text-[11px] leading-relaxed text-zinc-200">{buf.join("\n")}</pre>
        </div>
      );
      continue;
    }

    // Markdown table
    if (
      line.trim().startsWith("|") &&
      i + 1 < lines.length &&
      /^\s*\|?[\s:-]+\|/.test(lines[i + 1])
    ) {
      const parseCells = (ln) => ln.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
      const headers = parseCells(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        rows.push(parseCells(lines[i]));
        i++;
      }
      blocks.push(
        <div key={key++} className="overflow-x-auto rounded-xl border border-white/[0.08] bg-black/25">
          <table className="w-full text-left text-[11px]">
            <thead className="border-b border-white/[0.08] bg-white/[0.04] text-zinc-300">
              <tr>
                {headers.map((h, hi) => (
                  <th key={hi} className="px-2.5 py-1.5 font-semibold">{renderInlineMarkdown(h)}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.05]">
              {rows.map((r, ri) => (
                <tr key={ri} className="hover:bg-white/[0.03]">
                  {headers.map((_, ci) => (
                    <td key={ci} className="px-2.5 py-1.5 text-zinc-300">{renderInlineMarkdown(r[ci] || "")}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    if (!line.trim()) {
      i++;
      continue;
    }

    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) {
      blocks.push(<hr key={key++} className="border-white/[0.08]" />);
      i++;
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const lvl = heading[1].length;
      const cls =
        lvl === 1
          ? "text-base font-bold text-white"
          : lvl === 2
          ? "text-sm font-bold text-zinc-100"
          : "text-xs font-semibold text-[#64D2FF]";
      blocks.push(<div key={key++} className={`pt-1 ${cls}`}>{renderInlineMarkdown(heading[2])}</div>);
      i++;
      continue;
    }

    if (line.trim().startsWith(">")) {
      const qLines = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        qLines.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      blocks.push(
        <blockquote key={key++} className="border-l-2 border-[#0A84FF]/60 pl-3 text-zinc-300 italic">
          {renderInlineMarkdown(qLines.join(" "))}
        </blockquote>
      );
      continue;
    }

    if (/^\s*(?:[-*•])\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*(?:[-*•])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*(?:[-*•])\s+/, ""));
        i++;
      }
      blocks.push(
        <ul key={key++} className="list-disc space-y-1 pl-4 text-zinc-200">
          {items.map((it, ii) => (
            <li key={ii} className="leading-relaxed">{renderInlineMarkdown(it)}</li>
          ))}
        </ul>
      );
      continue;
    }

    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      blocks.push(
        <ol key={key++} className="list-decimal space-y-1 pl-4 text-zinc-200">
          {items.map((it, ii) => (
            <li key={ii} className="leading-relaxed">{renderInlineMarkdown(it)}</li>
          ))}
        </ol>
      );
      continue;
    }

    // Paragraph line(s)
    const pLines = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("```") &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*(?:[-*•]|\d+[.)])\s+/.test(lines[i]) &&
      !lines[i].trim().startsWith(">") &&
      !lines[i].trim().startsWith("|")
    ) {
      pLines.push(lines[i]);
      i++;
    }
    blocks.push(
      <p key={key++} className="leading-relaxed text-zinc-200">
        {renderInlineMarkdown(pLines.join(" "))}
      </p>
    );
  }

  return <div className="space-y-2 text-xs">{blocks}</div>;
}

export function aiColor(verdict, score) {
  const v = (verdict || "").toLowerCase();
  if (v.includes("strong") || (score != null && score >= 80)) {
    return { bg: "bg-[#30D158]/15", text: "text-[#30D158]", ring: "ring-1 ring-[#30D158]/35" };
  }
  if (v.includes("good") || (score != null && score >= 55)) {
    return { bg: "bg-[#0A84FF]/15", text: "text-[#64D2FF]", ring: "ring-1 ring-[#0A84FF]/35" };
  }
  if (v.includes("skip") || (score != null && score < 35)) {
    return { bg: "bg-[#FF453A]/15", text: "text-[#FF6961]", ring: "ring-1 ring-[#FF453A]/35" };
  }
  return { bg: "bg-[#FF9F0A]/15", text: "text-[#FFB340]", ring: "ring-1 ring-[#FF9F0A]/35" };
}

export function CopyButton({ text, label, onCopied, className = "" }) {
  const [copied, setCopied] = useState(false);

  async function copy(e) {
    e.stopPropagation();
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (onCopied) onCopied(text);
      setTimeout(() => setCopied(false), 1400);
    } catch {}
  }

  return (
    <button
      type="button"
      onClick={copy}
      title={copied ? "Copied" : "Copy to clipboard"}
      className={`inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] transition-all duration-200 ${
        copied
          ? "bg-[#30D158]/20 text-[#30D158]"
          : "text-zinc-400 hover:bg-white/[0.08] hover:text-zinc-100"
      } ${className}`}
    >
      {copied ? <Icons.Check className="h-3 w-3" /> : <Icons.Copy className="h-3 w-3" />}
      {label && <span>{copied ? "Copied" : label}</span>}
    </button>
  );
}

export function ToastList({ toasts, onDismiss }) {
  if (!toasts.length) return null;
  return (
    <div className="pointer-events-none fixed right-5 top-5 z-[100] flex max-w-sm flex-col gap-2">
      {toasts.map((t) => {
        const tone =
          t.type === "error"
            ? "border-[#FF453A]/35 bg-zinc-900/95 text-[#FF6961]"
            : t.type === "warning"
            ? "border-[#FF9F0A]/35 bg-zinc-900/95 text-[#FFB340]"
            : "border-[#30D158]/35 bg-zinc-900/95 text-[#30D158]";
        return (
          <div
            key={t.id}
            className={`pointer-events-auto animate-toast-enter flex items-center gap-2.5 rounded-2xl border px-4 py-2.5 text-xs font-medium shadow-2xl backdrop-blur-2xl ${tone}`}
          >
            <span className="h-2 w-2 shrink-0 rounded-full bg-current" />
            <span className="flex-1 text-zinc-100">{t.message}</span>
            <button
              onClick={() => onDismiss(t.id)}
              className="text-zinc-500 hover:text-zinc-200"
              aria-label="Dismiss"
            >
              <Icons.X className="h-3.5 w-3.5" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
