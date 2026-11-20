import React, { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Freehand polygon area selector built on Leaflet + OpenStreetMap (no API key).
export default function AreaMap({ center = [40.7128, -74.0060], initialPolygon = [], onChange, onCenter, areaPoints = 400 }) {
  const mapEl = useRef(null);
  const mapRef = useRef(null);
  const vertsRef = useRef([]);
  const markersRef = useRef([]);
  const lineRef = useRef(null);
  const polyRef = useRef(null);
  const doneRef = useRef(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [count, setCount] = useState(0);
  const [done, setDone] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [query, setQuery] = useState("");
  const [geoMsg, setGeoMsg] = useState("");
  const [tileCount, setTileCount] = useState(0);
  const previewRef = useRef([]);

  function clearOverlays() {
    const map = mapRef.current;
    if (!map) return;
    markersRef.current.forEach((m) => map.removeLayer(m));
    markersRef.current = [];
    if (lineRef.current) { map.removeLayer(lineRef.current); lineRef.current = null; }
    if (polyRef.current) { map.removeLayer(polyRef.current); polyRef.current = null; }
  }

  function emit() {
    const pts = vertsRef.current;
    onChangeRef.current(pts.length >= 3 ? pts.slice() : []);
  }

  function clearAll() {
    clearOverlays();
    vertsRef.current = [];
    doneRef.current = false;
    setCount(0);
    setDone(false);
    onChangeRef.current([]);
    clearPreview();
  }

  function clearPreview() {
    const map = mapRef.current;
    previewRef.current.forEach((m) => map && map.removeLayer(m));
    previewRef.current = [];
    setTileCount(0);
  }

  async function previewTiles() {
    const pts = vertsRef.current;
    if (pts.length < 3) { clearPreview(); return; }
    try {
      const res = await fetch("/api/preview-tiles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ polygon: pts, area_points: areaPoints }),
      });
      const data = await res.json();
      const map = mapRef.current;
      if (!map) return;
      clearPreview();
      (data.points || []).forEach(([la, ln]) => {
        const m = L.circleMarker([la, ln], {
          radius: 3.5, color: "#FF9F0A", fillColor: "#FF9F0A", fillOpacity: 0.9, weight: 1,
        }).addTo(map);
        previewRef.current.push(m);
      });
      setTileCount(data.count || 0);
    } catch {
      clearPreview();
    }
  }

  function reopenIfDone() {
    if (!doneRef.current) return;
    if (polyRef.current) { mapRef.current.removeLayer(polyRef.current); polyRef.current = null; }
    doneRef.current = false;
    setDone(false);
  }

  function addVertex(lat, lng) {
    if (doneRef.current) return;
    const map = mapRef.current;
    vertsRef.current.push([lat, lng]);
    const m = L.circleMarker([lat, lng], {
      radius: 5, color: "#0A84FF", fillColor: "#0A84FF", fillOpacity: 1, weight: 2,
    }).addTo(map);
    m._pt = [lat, lng];
    m.on("contextmenu", (e) => { L.DomEvent.stop(e); removeVertex([lat, lng]); });
    markersRef.current.push(m);
    redraw();
    setCount(vertsRef.current.length);
  }

  function redraw() {
    const map = mapRef.current;
    const pts = vertsRef.current;
    if (lineRef.current) { map.removeLayer(lineRef.current); lineRef.current = null; }
    if (pts.length >= 2) {
      lineRef.current = L.polyline(pts, { color: "#0A84FF", weight: 2, dashArray: "5,5" }).addTo(map);
    }
  }

  function removeMarkerFor(pt) {
    const map = mapRef.current;
    const mi = markersRef.current.findIndex(
      (m) => m._pt && m._pt[0] === pt[0] && m._pt[1] === pt[1]
    );
    if (mi !== -1) {
      map.removeLayer(markersRef.current[mi]);
      markersRef.current.splice(mi, 1);
    }
    const vi = vertsRef.current.findIndex((v) => v[0] === pt[0] && v[1] === pt[1]);
    if (vi !== -1) vertsRef.current.splice(vi, 1);
  }

  function removeVertex(pt) {
    reopenIfDone();
    removeMarkerFor(pt);
    redraw();
    setCount(vertsRef.current.length);
    emit();
    if (vertsRef.current.length >= 3) previewTiles();
    else clearPreview();
  }

  function undoLast() {
    const map = mapRef.current;
    if (!map || vertsRef.current.length === 0) return;
    reopenIfDone();
    const pt = vertsRef.current.pop();
    if (pt) removeMarkerFor(pt);
    redraw();
    setCount(vertsRef.current.length);
    emit();
    if (vertsRef.current.length >= 3) previewTiles();
    else clearPreview();
  }

  function finish() {
    const pts = vertsRef.current;
    if (pts.length < 3) return;
    const map = mapRef.current;
    if (lineRef.current) { map.removeLayer(lineRef.current); lineRef.current = null; }
    polyRef.current = L.polygon(pts, {
      color: "#0A84FF", weight: 2, fillColor: "#0A84FF", fillOpacity: 0.16,
    }).addTo(map);
    doneRef.current = true;
    setDone(true);
    onChangeRef.current(pts.slice());
    previewTiles();
  }

  function flyTo(lat, lng, zoom = 13) {
    const map = mapRef.current;
    if (map) map.flyTo([lat, lng], zoom, { duration: 0.7 });
  }

  async function geocode() {
    const q = query.trim();
    if (!q) return;
    setGeoMsg("Searching…");
    try {
      const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(q)}`;
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      const data = await res.json();
      if (Array.isArray(data) && data.length) {
        const lat = parseFloat(data[0].lat);
        const lng = parseFloat(data[0].lon);
        flyTo(lat, lng, 13);
        if (onCenter) onCenter(lat, lng);
        const name = (data[0].display_name || "").slice(0, 70);
        setGeoMsg(`→ ${name}`);
      } else {
        setGeoMsg("No match found.");
      }
    } catch {
      setGeoMsg("Search failed (network/CORS).");
    }
  }

  function toggleExpand() {
    setExpanded((v) => {
      const next = !v;
      setTimeout(() => { if (mapRef.current) mapRef.current.invalidateSize(); }, 180);
      return next;
    });
  }

  useEffect(() => {
    if (mapRef.current || !mapEl.current) return;
    const map = L.map(mapEl.current, { zoomControl: true }).setView(center, 11);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "© OpenStreetMap contributors",
    }).addTo(map);
    map.on("click", (e) => addVertex(e.latlng.lat, e.latlng.lng));
    map.on("contextmenu", (e) => {
      if (e.originalEvent && e.originalEvent.preventDefault) e.originalEvent.preventDefault();
      undoLast();
    });
    mapRef.current = map;
    if (initialPolygon && initialPolygon.length >= 3) {
      initialPolygon.forEach(([la, ln]) => addVertex(la, ln));
      finish();
    }
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (vertsRef.current.length >= 3) previewTiles();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [areaPoints]);

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input flex-1 min-w-[180px]"
          placeholder="Jump to a city or neighborhood (e.g. Manhattan, London)…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              geocode();
            }
          }}
        />
        <button type="button" className="btn-ghost px-3.5 py-2 text-xs" onClick={geocode}>Go</button>
        <button type="button" className="btn-ghost px-3.5 py-2 text-xs" onClick={toggleExpand}>
          {expanded ? "Minimize" : "Enlarge"}
        </button>
      </div>

      <div
        ref={mapEl}
        style={{ height: expanded ? "70vh" : 320, width: "100%" }}
        className="apple-dark-map z-0 overflow-hidden rounded-2xl border border-white/[0.08] bg-zinc-950 transition-[height] duration-300 ease-spring"
      />

      <div className="flex flex-wrap items-center gap-2.5 text-xs text-zinc-400">
        <span>Click to drop points · <b className="tabular-nums text-zinc-200">{count}</b> placed</span>
        <button
          type="button"
          className="btn-ghost px-2.5 py-1 text-xs"
          onClick={undoLast}
          disabled={count === 0}
        >
          Undo
        </button>
        <button
          type="button"
          className="btn-primary px-3 py-1 text-xs"
          onClick={finish}
          disabled={count < 3}
        >
          Finish Area
        </button>
        <button
          type="button"
          className="btn-ghost px-2.5 py-1 text-xs"
          onClick={clearAll}
        >
          Clear
        </button>
        {done && <span className="rounded-full bg-[#30D158]/15 px-2.5 py-0.5 text-[11px] font-medium text-[#30D158]">✓ Area set ({count} pts)</span>}
        {tileCount > 0 && <span className="rounded-full bg-[#FF9F0A]/15 px-2.5 py-0.5 text-[11px] font-medium text-[#FFB340] tabular-nums">{tileCount} tiles</span>}
        <span className="ml-auto text-[11px] text-zinc-500">Right-click to undo / delete point</span>
      </div>
      {geoMsg && <div className="text-xs text-zinc-400">{geoMsg}</div>}
    </div>
  );
}
