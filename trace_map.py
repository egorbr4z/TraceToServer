#!/usr/bin/env python3
"""
TraceToServer v2 — real-time network traffic on a braille world map.
Dependencies: pip3 install psutil requests rich
Run: sudo python3 trace_map.py   (sudo needed on macOS for net_connections)
"""
from __future__ import annotations

import ipaddress, json, sys, threading, time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:
    sys.exit("Run: pip3 install psutil")
try:
    import requests
except ImportError:
    sys.exit("Run: pip3 install requests")
try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich.layout import Layout
    from rich.align import Align
    from rich import box as rbox
except ImportError:
    sys.exit("Run: pip3 install rich")


# ══════════════════════════════════════════════════════════════
#  BRAILLE CANVAS
#  Each character cell = 2 pixels wide × 4 pixels tall
#  → 8× more resolution than plain ASCII
#
#  Dot layout inside one cell:
#    col 0  col 1
#    ●(01)  ●(08)   ← row 0
#    ●(02)  ●(10)   ← row 1
#    ●(04)  ●(20)   ← row 2
#    ●(40)  ●(80)   ← row 3
# ══════════════════════════════════════════════════════════════

_DOTS = [
    (0, 0, 0x01), (0, 1, 0x02), (0, 2, 0x04), (0, 3, 0x40),
    (1, 0, 0x08), (1, 1, 0x10), (1, 2, 0x20), (1, 3, 0x80),
]


class BrailleCanvas:
    """
    Two-layer braille pixel canvas.
    • land  layer: green,        computed once at startup
    • lines layer: bright cyan,  rebuilt every frame
    • marks: single-char overlays (own location, remote servers)
    """

    def __init__(self, cols: int, rows: int):
        self.cols, self.rows = cols, rows
        self.pw, self.ph = cols * 2, rows * 4
        self._land  = bytearray(self.pw * self.ph)
        self._lines = bytearray(self.pw * self.ph)
        self._marks: dict = {}

    def clear_frame(self):
        self._lines = bytearray(len(self._lines))
        self._marks.clear()

    def land(self, px: int, py: int):
        if 0 <= px < self.pw and 0 <= py < self.ph:
            self._land[py * self.pw + px] = 1

    def line_dot(self, px: int, py: int):
        if 0 <= px < self.pw and 0 <= py < self.ph:
            self._lines[py * self.pw + px] = 1

    def mark(self, cx: int, cy: int, ch: str, style: str):
        if 0 <= cx < self.cols and 0 <= cy < self.rows:
            self._marks[(cy, cx)] = (ch, style)

    def _bits(self, buf: bytearray, cx: int, cy: int) -> int:
        b, bx, by = 0, cx * 2, cy * 4
        for dc, dr, bit in _DOTS:
            x, y = bx + dc, by + dr
            if 0 <= x < self.pw and 0 <= y < self.ph and buf[y * self.pw + x]:
                b |= bit
        return b

    def render(self) -> Text:
        t = Text(no_wrap=True, overflow="crop")
        land, lines, marks = self._land, self._lines, self._marks
        for cy in range(self.rows):
            for cx in range(self.cols):
                if (cy, cx) in marks:
                    t.append(*marks[(cy, cx)])
                else:
                    lb = self._bits(lines, cx, cy)
                    gb = self._bits(land,  cx, cy)
                    if lb:
                        t.append(chr(0x2800 + (lb | gb)), "bright_cyan bold")
                    elif gb:
                        t.append(chr(0x2800 + gb), "green")
                    else:
                        t.append(' ')
            t.append('\n')
        return t


# ══════════════════════════════════════════════════════════════
#  GEOMETRY HELPERS
# ══════════════════════════════════════════════════════════════

def _bresenham(x0, y0, x1, y1):
    dx, dy = abs(x1-x0), abs(y1-y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    e = dx - dy
    while True:
        yield x0, y0
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * e
        if e2 > -dy: e -= dy; x0 += sx
        if e2 <  dx: e += dx; y0 += sy


def _ll_px(lat, lon, pw, ph):
    """lat/lon → braille pixel coords."""
    x = int((lon + 180) / 360 * (pw - 1) + .5)
    y = int((90  - lat) / 180 * (ph - 1) + .5)
    return max(0, min(pw-1, x)), max(0, min(ph-1, y))


def _ll_cell(lat, lon, cols, rows):
    """lat/lon → char-cell coords."""
    x = int((lon + 180) / 360 * (cols - 1) + .5)
    y = int((90  - lat) / 180 * (rows - 1) + .5)
    return max(0, min(cols-1, x)), max(0, min(rows-1, y))


# ══════════════════════════════════════════════════════════════
#  GEO DATA  — Natural Earth 110m land polygons (public domain)
# ══════════════════════════════════════════════════════════════

_CACHE_DIR = Path.home() / ".cache" / "tracemap"
_LAND_URL  = (
    "https://raw.githubusercontent.com/nvkelso/"
    "natural-earth-vector/master/geojson/ne_110m_land.geojson"
)


def _load_geojson() -> dict | None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = _CACHE_DIR / "ne_110m_land.geojson"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            pass
    try:
        r = requests.get(_LAND_URL, timeout=15)
        if r.ok:
            f.write_text(r.text)
            return r.json()
    except Exception:
        pass
    return None


def _fill_ring(ring, set_fn, pw, ph):
    """Scanline polygon fill — converts GeoJSON ring to braille pixels."""
    pts = [_ll_px(lat, lon, pw, ph) for lon, lat in ring]
    if len(pts) < 3:
        return
    min_y = max(0, min(p[1] for p in pts))
    max_y = min(ph-1, max(p[1] for p in pts))
    n = len(pts)
    for y in range(min_y, max_y+1):
        xs = []
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i+1) % n]
            if (y1 <= y < y2) or (y2 <= y < y1):
                xs.append(x1 + (y - y1) / (y2 - y1) * (x2 - x1))
        xs.sort()
        for j in range(0, len(xs)-1, 2):
            for x in range(max(0, int(xs[j]+.5)), min(pw-1, int(xs[j+1]+.5))+1):
                set_fn(x, y)


def _land_cache_path(pw, ph):
    return _CACHE_DIR / f"land_{pw}x{ph}.bin"


def rasterize(canvas: BrailleCanvas, geojson: dict | None, status_cb=None):
    """
    Rasterize world map onto canvas.land layer.
    Uses a binary cache so resize is instant on second run.
    """
    pw, ph = canvas.pw, canvas.ph
    cp = _land_cache_path(pw, ph)

    # Try binary cache first
    if cp.exists():
        data = cp.read_bytes()
        if len(data) == pw * ph:
            canvas._land[:] = data
            if status_cb:
                status_cb("map loaded from cache")
            return

    if geojson:
        if status_cb:
            status_cb("rasterizing Natural Earth 110m…")
        for feat in geojson.get("features", []):
            geom = feat.get("geometry", {})
            t    = geom.get("type", "")
            c    = geom.get("coordinates", [])
            polys = [c] if t == "Polygon" else (c if t == "MultiPolygon" else [])
            for poly in polys:
                if poly:
                    _fill_ring(poly[0], canvas.land, pw, ph)
            # Redraw edges for crispness
            for poly in polys:
                for ring in poly:
                    pts = [_ll_px(lat, lon, pw, ph) for lon, lat in ring]
                    for i in range(len(pts)-1):
                        for x, y in _bresenham(*pts[i], *pts[i+1]):
                            canvas.land(x, y)
    else:
        if status_cb:
            status_cb("offline — using built-in outline map")
        for poly in _FALLBACK_OUTLINES:
            pts = [_ll_px(lat, lon, pw, ph) for lat, lon in poly]
            for i in range(len(pts)-1):
                for x, y in _bresenham(*pts[i], *pts[i+1]):
                    canvas.land(x, y)

    # Save binary cache
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(bytes(canvas._land))
    except Exception:
        pass

    if status_cb:
        status_cb("map ready")


# ── Fallback outlines (used when offline) ─────────────────────
_FALLBACK_OUTLINES = [
    [(70,-140),(65,-168),(58,-137),(53,-130),(48,-125),(42,-124),
     (32,-118),(22,-110),(15,-92),(10,-83),(9,-77),(10,-75),(18,-66),
     (23,-82),(25,-80),(32,-80),(35,-75),(41,-70),(45,-66),(47,-53),
     (52,-56),(60,-63),(63,-68),(60,-78),(60,-85),(64,-83),(68,-78),
     (72,-78),(75,-90),(72,-100),(72,-120),(71,-140),(70,-140)],
    [(60,-45),(65,-40),(70,-22),(76,-18),(83,-30),(82,-50),
     (76,-65),(72,-68),(65,-53),(60,-45)],
    [(12,-72),(10,-62),(8,-60),(5,-60),(0,-50),(-5,-35),(-10,-37),
     (-15,-39),(-23,-43),(-30,-51),(-34,-53),(-38,-57),(-42,-64),
     (-50,-69),(-55,-67),(-55,-65),(-52,-70),(-55,-70),(-55,-74),
     (-50,-75),(-42,-73),(-35,-72),(-18,-70),(-5,-80),(0,-80),
     (5,-77),(10,-72),(12,-72)],
    [(36,-6),(44,-9),(44,-8),(48,-4),(51,2),(54,9),(58,10),(58,18),
     (57,22),(60,22),(65,15),(70,25),(68,28),(60,28),(55,22),
     (52,21),(50,22),(48,22),(48,17),(45,17),(42,20),(40,18),
     (38,13),(38,9),(36,6),(36,-6)],
    [(57,5),(58,7),(58,10),(65,15),(70,25),(71,28),(70,30),
     (65,25),(63,20),(60,20),(57,10),(57,5)],
    [(37,10),(37,-6),(14,-17),(5,-10),(4,7),(0,8),(-5,10),(-10,14),
     (-18,13),(-30,17),(-35,20),(-35,26),(-30,31),(-25,33),(-15,37),
     (-10,40),(-5,40),(0,42),(10,44),(12,43),(15,42),(20,40),
     (25,37),(30,33),(37,37),(37,10)],
    [(30,32),(22,37),(12,45),(15,52),(22,59),(26,57),(30,48),
     (30,43),(26,50),(22,56),(12,43),(22,37),(30,32)],
    [(28,77),(22,68),(8,77),(8,80),(12,80),(20,87),(22,89),(28,97),
     (34,76),(28,77)],
    [(28,97),(22,100),(13,100),(10,105),(5,103),(1,104),
     (5,116),(10,124),(20,120),(28,120),(28,97)],
    [(50,87),(28,97),(28,120),(38,121),(40,117),(42,121),(38,124),
     (42,131),(50,141),(55,137),(55,120),(50,87)],
    [(50,87),(55,120),(55,137),(50,141),(50,145),(55,163),(65,170),
     (70,165),(73,155),(75,150),(75,100),(73,80),(72,68),(72,54),
     (68,50),(65,57),(68,50),(68,32),(70,28),(70,25),(55,22),
     (50,30),(50,60),(50,87)],
    [(-10,142),(-14,130),(-20,114),(-34,114),(-38,140),(-38,149),
     (-44,148),(-44,168),(-35,150),(-25,153),(-20,148),(-14,136),(-10,142)],
    [(-65,-180),(-65,-120),(-60,-90),(-65,-60),(-62,0),(-65,60),
     (-62,90),(-65,120),(-65,180),(-90,180),(-90,-180),(-65,-180)],
]


# ══════════════════════════════════════════════════════════════
#  IP HELPERS
# ══════════════════════════════════════════════════════════════

_PRIVATE = [ipaddress.ip_network(n) for n in (
    '10.0.0.0/8','172.16.0.0/12','192.168.0.0/16',
    '127.0.0.0/8','169.254.0.0/16','::1/128','fc00::/7','fe80::/10',
)]


def is_private(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
        return any(a in n for n in _PRIVATE)
    except ValueError:
        return True


# ══════════════════════════════════════════════════════════════
#  GEO CACHE  — IP → (lat, lon, city, country)
# ══════════════════════════════════════════════════════════════

class GeoCache:
    def __init__(self, maxsize=512):
        self._lock    = threading.Lock()
        self._cache: OrderedDict = OrderedDict()
        self._queue:  list = []
        self._pending: set = set()
        self._maxsize = maxsize

    def get(self, ip: str) -> tuple | None:
        with self._lock:
            if ip in self._cache:
                self._cache.move_to_end(ip)
                return self._cache[ip]
            if ip not in self._pending and not is_private(ip):
                self._queue.append(ip)
                self._pending.add(ip)
        return None

    def _store(self, ip: str, data: tuple):
        with self._lock:
            self._pending.discard(ip)
            self._cache[ip] = data
            self._cache.move_to_end(ip)
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def run_worker(self):
        while True:
            time.sleep(1.5)
            with self._lock:
                batch, self._queue = self._queue[:100], self._queue[100:]
            if not batch:
                continue
            try:
                r = requests.post(
                    'http://ip-api.com/batch',
                    json=[{'query': ip,
                           'fields': 'query,lat,lon,city,country,status'}
                          for ip in batch],
                    timeout=5,
                )
                if r.ok:
                    for item in r.json():
                        if item.get('status') == 'success':
                            self._store(item['query'], (
                                item['lat'], item['lon'],
                                item.get('city', ''),
                                item.get('country', ''),
                            ))
            except Exception:
                pass


GEO = GeoCache()


# ══════════════════════════════════════════════════════════════
#  CONNECTION MONITOR
# ══════════════════════════════════════════════════════════════

class ConnMonitor:
    def __init__(self):
        self._lock = threading.Lock()
        self.conns: list = []

    def run(self):
        while True:
            try:
                raw = psutil.net_connections(kind='inet')
            except Exception:
                time.sleep(2)
                continue
            seen = []
            for c in raw:
                if not c.raddr:
                    continue
                rip = c.raddr.ip
                if is_private(rip):
                    continue
                proc = ''
                try:
                    if c.pid:
                        proc = psutil.Process(c.pid).name()
                except Exception:
                    pass
                seen.append({
                    'rip': rip, 'rport': c.raddr.port,
                    'pid': c.pid, 'proc': proc,
                })
            with self._lock:
                self.conns = seen
            time.sleep(1)

    def snapshot(self) -> list:
        with self._lock:
            return list(self.conns)


MONITOR = ConnMonitor()


# ══════════════════════════════════════════════════════════════
#  OWN LOCATION
# ══════════════════════════════════════════════════════════════

_OWN_GEO: tuple | None = None


def _fetch_own_geo():
    global _OWN_GEO
    try:
        d = requests.get('http://ip-api.com/json/', timeout=5).json()
        if d.get('status') == 'success':
            _OWN_GEO = (d['lat'], d['lon'],
                        d.get('city', ''), d.get('country', ''))
            return
    except Exception:
        pass
    _OWN_GEO = (37.77, -122.42, 'Unknown', 'US')


# ══════════════════════════════════════════════════════════════
#  FRAME DRAWING
# ══════════════════════════════════════════════════════════════

def _draw_connections(canvas: BrailleCanvas,
                      conns: list,
                      own_geo: tuple | None) -> list:
    """Render lines + markers onto canvas. Returns [(ip, loc, proc), …]."""
    labels = []
    if own_geo is None:
        return labels

    olat, olon = own_geo[0], own_geo[1]
    opx, opy   = _ll_px(olat, olon, canvas.pw, canvas.ph)
    ocx, ocy   = _ll_cell(olat, olon, canvas.cols, canvas.rows)

    for c in conns[:80]:
        geo = GEO.get(c['rip'])
        if not geo:
            continue
        rlat, rlon, rcity, rcountry = geo
        rpx, rpy = _ll_px(rlat, rlon, canvas.pw, canvas.ph)
        rcx, rcy = _ll_cell(rlat, rlon, canvas.cols, canvas.rows)

        for px, py in _bresenham(opx, opy, rpx, rpy):
            canvas.line_dot(px, py)

        canvas.mark(rcx, rcy, '✦', 'bright_red bold')
        loc = rcity or rcountry or c['rip']
        labels.append((c['rip'], loc, c['proc'] or '—'))

    canvas.mark(ocx, ocy, '◉', 'bright_yellow bold')
    return labels


# ══════════════════════════════════════════════════════════════
#  RICH UI COMPONENTS
# ══════════════════════════════════════════════════════════════

def _header(n_total: int, n_geo: int) -> Panel:
    ts = datetime.now().strftime('%H:%M:%S')
    t = Text(justify="center", no_wrap=True, overflow="crop")
    t.append("⬡ TraceToServer", style="bold bright_cyan")
    t.append(f"  │  {ts}  │  ", style="dim white")
    t.append(str(n_total), style="bold bright_yellow")
    t.append(" connections  │  ", style="dim white")
    t.append(str(n_geo), style="bold bright_green")
    t.append(" geolocated  │  Ctrl-C to quit", style="dim white")
    return Panel(t, style="on grey11", padding=(0, 1), height=3)


def _conn_table(labels: list) -> Panel:
    tbl = Table(
        box=rbox.SIMPLE, expand=True, show_header=True,
        header_style="bold bright_cyan", padding=(0, 1),
    )
    tbl.add_column("IP Address",  style="bright_white", min_width=15)
    tbl.add_column("Location",    style="bright_green",  min_width=22)
    tbl.add_column("Process",     style="yellow",        min_width=10)

    if labels:
        for ip, loc, proc in labels[:8]:
            tbl.add_row(ip, loc, proc)
    else:
        tbl.add_row(
            "[dim]waiting for connections…[/dim]",
            "[dim]make sure you have internet activity[/dim]", ""
        )

    return Panel(
        tbl,
        title="[bold bright_cyan]Active Connections[/bold bright_cyan]",
        border_style="bright_blue",
        style="on grey7",
        height=11,
    )


# ══════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════

def _make_map_panel(map_text: Text) -> Panel:
    return Panel(
        Align(map_text, "left", vertical="top"),
        title="[bold bright_cyan]World Traffic Map[/bold]"
              "  [dim]◉ you  ✦ server[/dim]",
        border_style="blue",
        style="on #050d1a",
    )


def _make_loading_panel(msg: str, dots: int) -> Panel:
    spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[dots % 10]
    t = Text(justify="center")
    t.append(f"\n\n\n{spinner} ", style="bright_cyan bold")
    t.append(msg, style="bright_white")
    return Panel(t, border_style="blue", style="on #050d1a")


def main():
    console = Console()

    # ── Start background threads ────────────────────────────
    for fn in (GEO.run_worker, MONITOR.run, _fetch_own_geo):
        threading.Thread(target=fn, daemon=True).start()

    # ── Sizing ──────────────────────────────────────────────
    tw, th = console.size
    map_rows = max(12, th - 3 - 11 - 5)
    map_cols = max(40, tw - 4)

    # ── Layout (created once, sections updated every frame) ─
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="map"),
        Layout(name="table", size=11),
    )

    # Pre-fill so Live never shows placeholder text
    layout["header"].update(_header(0, 0))
    layout["map"].update(_make_loading_panel("Downloading world map data…", 0))
    layout["table"].update(_conn_table([]))

    # ── Download + rasterize in background ──────────────────
    geo_data:  list = [None]
    canvas_ref: list = [None]
    map_ready  = threading.Event()
    load_msg:  list = ["downloading…"]

    def _build_map():
        geo_data[0] = _load_geojson()
        load_msg[0] = "rasterizing map…"
        c = BrailleCanvas(map_cols, map_rows)
        rasterize(c, geo_data[0])
        canvas_ref[0] = c
        map_ready.set()

    threading.Thread(target=_build_map, daemon=True).start()

    # ── Main render loop ─────────────────────────────────────
    dots = 0
    try:
        with Live(layout, console=console, refresh_per_second=4,
                  screen=True):
            while True:
                dots += 1

                if not map_ready.is_set():
                    # Loading state — update header + spinner, keep table
                    layout["header"].update(_header(0, 0))
                    layout["map"].update(
                        _make_loading_panel(load_msg[0], dots))
                    time.sleep(0.15)
                    continue

                # Map is ready — get canvas (only once)
                canvas = canvas_ref[0]

                canvas.clear_frame()
                conns  = MONITOR.snapshot()
                labels = _draw_connections(canvas, conns, _OWN_GEO)
                map_text = canvas.render()

                layout["header"].update(_header(len(conns), len(labels)))
                layout["map"].update(_make_map_panel(map_text))
                layout["table"].update(_conn_table(labels))

                # Handle terminal resize
                nw, nh = console.size
                if abs(nw - tw) > 4 or abs(nh - th) > 3:
                    tw, th = nw, nh
                    new_rows = max(12, th - 3 - 11 - 5)
                    new_cols = max(40, tw - 4)
                    if new_rows != map_rows or new_cols != map_cols:
                        map_rows, map_cols = new_rows, new_cols
                        new_canvas = BrailleCanvas(map_cols, map_rows)
                        rasterize(new_canvas, geo_data[0])
                        canvas_ref[0] = new_canvas

                time.sleep(0.4)

    except KeyboardInterrupt:
        pass

    console.print("\n[bright_cyan]TraceToServer[/] closed. Bye!")


if __name__ == '__main__':
    main()
