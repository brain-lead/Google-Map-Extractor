import React, { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { leadColor } from "./ui.jsx";

export default function ResultsMap({ items = [], onOpen }) {
  const elRef = useRef(null);
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;

  useEffect(() => {
    if (mapRef.current || !elRef.current) return;
    const map = L.map(elRef.current, { zoomControl: true }).setView([39.8, -98.5], 4);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap contributors",
    }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const group = layerRef.current;
    if (!map || !group) return;
    group.clearLayers();
    const coords = [];
    items.forEach((b) => {
      const la = Number(b.latitude);
      const ln = Number(b.longitude);
      if (!Number.isFinite(la) || !Number.isFinite(ln) || (la === 0 && ln === 0)) return;
      coords.push([la, ln]);
      const lc = leadColor(b.lead_grade);
      const marker = L.circleMarker([la, ln], {
        radius: 7,
        color: "#ffffff",
        weight: 1.5,
        fillColor: lc.hex,
        fillOpacity: 0.92,
      });
      const container = document.createElement("div");
      container.className = "min-w-[190px] space-y-1.5 text-xs";
      const title = document.createElement("div");
      title.className = "font-semibold text-zinc-100";
      title.textContent = b.name || "Unnamed business";
      const meta = document.createElement("div");
      meta.className = "text-zinc-400";
      meta.textContent = [b.category, b.rating != null ? `★ ${b.rating}` : null, b.lead_grade ? `${b.lead_score} ${b.lead_grade}` : null]
        .filter(Boolean)
        .join(" · ");
      const addr = document.createElement("div");
      addr.className = "text-[11px] text-zinc-500";
      addr.textContent = b.full_address || b.city_state_zip || "";
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "mt-1 w-full rounded-lg bg-[#0A84FF] px-2.5 py-1 text-[11px] font-medium text-white hover:bg-[#3399ff]";
      btn.textContent = "Inspect Lead";
      btn.onclick = () => onOpenRef.current && onOpenRef.current(b);
      container.append(title, meta, addr, btn);
      marker.bindPopup(container);
      marker.addTo(group);
    });
    if (coords.length === 1) {
      map.setView(coords[0], 14);
    } else if (coords.length > 1) {
      map.fitBounds(coords, { padding: [36, 36], maxZoom: 15 });
    }
  }, [items]);

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-zinc-400">
        <span>Showing coordinates for businesses on this page</span>
        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#FF453A]" />Hot</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#FF9F0A]" />Warm</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-[#0A84FF]" />Cold</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-full bg-zinc-500" />Closed</span>
        </div>
      </div>
      <div
        ref={elRef}
        style={{ height: 460, width: "100%" }}
        className="apple-dark-map z-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-zinc-950"
      />
    </div>
  );
}
