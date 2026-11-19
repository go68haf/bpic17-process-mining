"""Readable BPMN export for block-structured process trees (Inductive Miner).

PM4Py's own BPMN conversion creates many redundant gateways and a very wide,
hard-to-read layout. This module converts a process tree directly into
BPMN 2.0 XML with a clean, block-based left-to-right layout that can be opened
in bpmn.io or Signavio, and renders the same layout as SVG for the report.

Main entry point: ``export(tree, bpmn_path, svg_path, ...)``.
"""
from xml.sax.saxutils import escape

from pm4py.objects.process_tree.obj import Operator

TW, TH = 108, 62        # task size
GW = 34                 # gateway size
EV = 30                 # event size
HG = 18                 # horizontal gap
VG = 16                 # vertical gap between branches
CH = 7.0                # approx. width of one label character


class Diagram:
    def __init__(self):
        self.shapes = {}      # id -> dict(type, x, y, w, h, name, kind)
        self.edges = []       # dict(id, src, tgt, pts, name)
        self.n = 0

    def new_id(self, prefix):
        self.n += 1
        return f"{prefix}_{self.n}"

    def shape(self, typ, x, y, w, h, name="", kind=""):
        sid = self.new_id(typ)
        self.shapes[sid] = dict(type=typ, x=x, y=y, w=w, h=h, name=name, kind=kind)
        return sid

    def edge(self, src, tgt, pts, name=""):
        self.edges.append(dict(id=self.new_id("Flow"), src=src, tgt=tgt,
                               pts=[(round(a), round(b)) for a, b in pts], name=name))


def is_tau(n):
    return n.operator is None and n.label is None


def first_label(n):
    """Label of the task a branch directly starts with (task or sequence of tasks)."""
    if n.operator is None:
        return n.label
    if n.operator == Operator.SEQUENCE and n.children[0].operator is None:
        return n.children[0].label
    return None


class Block:
    """Layout block: width w, extent above (up) and below (down) the midline."""

    def place(self, d, x, y):
        """Draw at left x / midline y. Returns (entry_id, exit_id)."""
        raise NotImplementedError


class Task(Block):
    def __init__(self, label, loop=False):
        self.label = label.strip()
        self.loop = loop  # BPMN standard loop marker = task may be repeated
        self.w, self.up, self.down = TW, TH / 2, TH / 2

    def place(self, d, x, y):
        sid = d.shape("Task", x, y - TH / 2, TW, TH, self.label, kind="loop" if self.loop else "")
        return sid, sid


class Seq(Block):
    def __init__(self, children):
        self.ch = children
        self.w = sum(c.w for c in children) + HG * (len(children) - 1)
        self.up = max(c.up for c in children)
        self.down = max(c.down for c in children)

    def place(self, d, x, y):
        first = last = None
        for c in self.ch:
            en, ex = c.place(d, x, y)
            if last is not None:
                d.edge(last, en, [(px, y), (x, y)])
            first = first or en
            last = ex
            x += c.w
            px = x
            x += HG
        return first, last


class Choice(Block):
    def __init__(self, kind, children, labels):
        self.kind = kind  # "X" or "+"
        real = [c for c in children if not is_tau(c)]
        self.has_tau = any(is_tau(c) for c in children)
        self.blocks = [build(c, labels) for c in real]
        self.names = [labels.get(first_label(c), "") if self.kind == "X" else "" for c in real]
        inner = max(b.w for b in self.blocks)
        self.lead = HG + (CH * max(len(n) for n in self.names) if any(self.names) else 0)
        self.w = GW + self.lead + HG + inner + GW
        # lanes: first block on midline, others stacked below, tau bypass above
        self.mids, off = [], 0.0
        for i, b in enumerate(self.blocks):
            if i > 0:
                off += self.blocks[i - 1].down + VG + b.up
            self.mids.append(off)
        self.tau_mid = -(self.blocks[0].up + VG) if self.has_tau else None
        self.up = max(GW / 2, self.blocks[0].up + (VG if self.has_tau else 0))
        self.down = max(GW / 2, self.mids[-1] + self.blocks[-1].down)
        self.inner = inner

    def place(self, d, x, y):
        typ = "ExclusiveGateway" if self.kind == "X" else "ParallelGateway"
        g1 = d.shape(typ, x, y - GW / 2, GW, GW, kind="split")
        jx = x + GW + self.lead + HG + self.inner
        g2 = d.shape(typ, jx, y - GW / 2, GW, GW, kind="join")
        gx1, gx2 = x + GW / 2, jx + GW / 2
        bx = x + GW + self.lead
        for b, m, name in zip(self.blocks, self.mids, self.names):
            ly = y + m
            en, ex = b.place(d, bx, ly)
            if m == 0:
                d.edge(g1, en, [(x + GW, y), (bx, y)], name)
                d.edge(ex, g2, [(bx + b.w, y), (jx, y)])
            else:
                d.edge(g1, en, [(gx1, y + GW / 2), (gx1, ly), (bx, ly)], name)
                d.edge(ex, g2, [(bx + b.w, ly), (gx2, ly), (gx2, y + GW / 2)])
        if self.has_tau:
            ty = y + self.tau_mid
            d.edge(g1, g2, [(gx1, y - GW / 2), (gx1, ty), (gx2, ty), (gx2, y - GW / 2)])
        return g1, g2


class Loop(Block):
    def __init__(self, do, labels):
        self.do = build(do, labels)
        self.w = GW + 2 * HG + self.do.w + GW
        self.up = max(GW / 2, self.do.up)
        self.down = max(GW / 2, self.do.down) + VG

    def place(self, d, x, y):
        g1 = d.shape("ExclusiveGateway", x, y - GW / 2, GW, GW, kind="join")
        bx = x + GW + HG
        en, ex = self.do.place(d, bx, y)
        jx = bx + self.do.w + HG
        g2 = d.shape("ExclusiveGateway", jx, y - GW / 2, GW, GW, kind="split")
        d.edge(g1, en, [(x + GW, y), (bx, y)])
        d.edge(ex, g2, [(bx + self.do.w, y), (jx, y)])
        by = y + max(GW / 2, self.do.down) + VG
        d.edge(g2, g1, [(jx + GW / 2, y + GW / 2), (jx + GW / 2, by),
                        (x + GW / 2, by), (x + GW / 2, y + GW / 2)], "repeat")
        return g1, g2


def build(n, labels):
    if n.operator is None:
        return Task(n.label)
    ch = list(n.children)
    if n.operator == Operator.SEQUENCE:
        return Seq([build(c, labels) for c in ch])
    if n.operator == Operator.XOR:
        return Choice("X", ch, labels)
    if n.operator == Operator.PARALLEL:
        return Choice("+", ch, labels)
    if n.operator == Operator.LOOP:
        if len(ch) == 2 and is_tau(ch[1]) and ch[0].operator is None:
            return Task(ch[0].label, loop=True)
        if len(ch) == 2 and is_tau(ch[1]):
            return Loop(ch[0], labels)
        raise ValueError("only loops with silent redo part are supported")
    raise ValueError(n.operator)


def layout(tree, labels=None, split_at=()):
    """Lay out the tree; a top-level sequence can be wrapped into several rows
    (split_at = indices of the top-level children that start a new row)."""
    labels = labels or {}
    d = Diagram()
    ch = list(tree.children) if tree.operator == Operator.SEQUENCE else [tree]
    cuts = [0] + list(split_at) + [len(ch)]
    rows = [Seq([build(c, labels) for c in ch[a:b]]) for a, b in zip(cuts, cuts[1:])]
    x0, y = 20, 40 + rows[0].up
    xs = x0 + EV + HG
    start = d.shape("StartEvent", x0, y - EV / 2, EV, EV)
    en, ex = rows[0].place(d, xs, y)
    d.edge(start, en, [(x0 + EV, y), (xs, y)])
    row_end_x = xs + rows[0].w
    for prev, row in zip(rows, rows[1:]):
        y2 = y + prev.down + 3 * VG + row.up
        en2, ex2 = row.place(d, xs, y2)
        midy = y + prev.down + 1.5 * VG
        d.edge(ex, en2, [(row_end_x, y), (row_end_x + 12, y), (row_end_x + 12, midy),
                         (x0 + EV / 2, midy), (x0 + EV / 2, y2), (xs, y2)])
        ex, y, row_end_x = ex2, y2, xs + row.w
    end = d.shape("EndEvent", row_end_x + HG, y - EV / 2, EV, EV)
    d.edge(ex, end, [(row_end_x, y), (row_end_x + HG, y)])
    return d


def add_annotation(d, near_label, text, dx=-40, dy=-150, w=330, h=66, attach="top"):
    """Text annotation attached to the split gateway whose branch starts with near_label."""
    for e in d.edges:
        tgt = d.shapes.get(e["tgt"], {})
        if tgt.get("name") == near_label and d.shapes[e["src"]]["type"].endswith("Gateway"):
            g = d.shapes[e["src"]]
            ax, ay = g["x"] + dx, g["y"] + dy
            aid = d.shape("TextAnnotation", ax, ay, w, h, text)
            d.edges.append(dict(id=d.new_id("Assoc"), src=aid, tgt=e["src"], assoc=True,
                                pts=[(g["x"] + GW / 2, ay + h), (g["x"] + GW / 2, g["y"])]
                                if attach == "top" else [(ax, ay + h / 2), (g["x"] + GW / 2, g["y"] + GW)],
                                name=""))
            return aid
    raise KeyError(near_label)


# ---------------------------------------------------------------- BPMN XML
def to_bpmn_xml(d):
    tag = {"Task": "task", "StartEvent": "startEvent", "EndEvent": "endEvent",
           "ExclusiveGateway": "exclusiveGateway", "ParallelGateway": "parallelGateway"}
    inc, out = {}, {}
    flows = [e for e in d.edges if not e.get("assoc")]
    for e in flows:
        out.setdefault(e["src"], []).append(e["id"])
        inc.setdefault(e["tgt"], []).append(e["id"])
    p = ['<?xml version="1.0" encoding="UTF-8"?>',
         '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
         'xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
         'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
         'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" '
         'id="Definitions_1" targetNamespace="http://bpmn.io/schema/bpmn">',
         '  <bpmn:process id="Process_1" isExecutable="false">']
    for sid, s in d.shapes.items():
        if s["type"] == "TextAnnotation":
            p.append(f'    <bpmn:textAnnotation id="{sid}"><bpmn:text>{escape(s["name"])}'
                     f'</bpmn:text></bpmn:textAnnotation>')
            continue
        name = f' name="{escape(s["name"])}"' if s["name"] else ""
        body = "<bpmn:standardLoopCharacteristics />" if s["kind"] == "loop" else ""
        body += "".join(f"<bpmn:incoming>{i}</bpmn:incoming>" for i in inc.get(sid, []))
        body += "".join(f"<bpmn:outgoing>{o}</bpmn:outgoing>" for o in out.get(sid, []))
        p.append(f'    <bpmn:{tag[s["type"]]} id="{sid}"{name}>{body}</bpmn:{tag[s["type"]]}>')
    for e in d.edges:
        if e.get("assoc"):
            p.append(f'    <bpmn:association id="{e["id"]}" sourceRef="{e["src"]}" targetRef="{e["tgt"]}" />')
        else:
            name = f' name="{escape(e["name"])}"' if e["name"] else ""
            p.append(f'    <bpmn:sequenceFlow id="{e["id"]}"{name} sourceRef="{e["src"]}" '
                     f'targetRef="{e["tgt"]}" />')
    p += ['  </bpmn:process>', '  <bpmndi:BPMNDiagram id="BPMNDiagram_1">',
          '    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_1">']
    for sid, s in d.shapes.items():
        extra = ' isMarkerVisible="true"' if s["type"] == "ExclusiveGateway" else ""
        p.append(f'      <bpmndi:BPMNShape id="{sid}_di" bpmnElement="{sid}"{extra}>'
                 f'<dc:Bounds x="{s["x"]:.0f}" y="{s["y"]:.0f}" width="{s["w"]:.0f}" '
                 f'height="{s["h"]:.0f}" /></bpmndi:BPMNShape>')
    for e in d.edges:
        wps = "".join(f'<di:waypoint x="{x}" y="{y}" />' for x, y in e["pts"])
        lab = ""
        if e["name"]:
            lx, ly = label_pos(e)
            lab = (f'<bpmndi:BPMNLabel><dc:Bounds x="{lx:.0f}" y="{ly - 12:.0f}" '
                   f'width="{8 * len(e["name"]):.0f}" height="14" /></bpmndi:BPMNLabel>')
        p.append(f'      <bpmndi:BPMNEdge id="{e["id"]}_di" bpmnElement="{e["id"]}">{wps}{lab}'
                 f'</bpmndi:BPMNEdge>')
    p += ['    </bpmndi:BPMNPlane>', '  </bpmndi:BPMNDiagram>', '</bpmn:definitions>']
    return "\n".join(p)


def label_pos(e):
    """Place a flow label above its last horizontal segment."""
    pts = e["pts"]
    for (x1, y1), (x2, y2) in reversed(list(zip(pts, pts[1:]))):
        if y1 == y2 and abs(x2 - x1) > 10:
            return min(x1, x2) + 4, y1 - 3
    return pts[0][0] + 4, pts[0][1] - 3


# ---------------------------------------------------------------- SVG
def wrap(text, n=14):
    words, lines, cur = text.replace("_", "_​").split(" "), [], ""
    for wd in words:
        if cur and len(cur) + 1 + len(wd) > n:
            lines.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}".strip()
    lines.append(cur)
    return [l.replace("​", "") for l in lines]


def to_svg(d, font=13):
    xs = [s["x"] + s["w"] for s in d.shapes.values()] + [x for e in d.edges for x, _ in e["pts"]]
    ys = [s["y"] + s["h"] for s in d.shapes.values()] + [y for e in d.edges for _, y in e["pts"]]
    miny = min([s["y"] for s in d.shapes.values()] + [y for e in d.edges for _, y in e["pts"]]) - 10
    W, H = max(xs) + 20, max(ys) + 20 - miny
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
         f'viewBox="0 {miny:.0f} {W:.0f} {H:.0f}" font-family="Helvetica, Arial, sans-serif">',
         f'<rect x="0" y="{miny:.0f}" width="{W:.0f}" height="{H:.0f}" fill="white"/>']
    for e in d.edges:
        pts = " ".join(f"{x},{y}" for x, y in e["pts"])
        if e.get("assoc"):
            o.append(f'<polyline points="{pts}" fill="none" stroke="#555" stroke-dasharray="2,3"/>')
            continue
        col = "#b23a48" if e["name"] and e["name"] != "repeat" else "#222"
        o.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.3"/>')
        # explicit arrow head (works in every SVG/PDF converter, unlike SVG markers)
        (x1, y1), (x2, y2) = e["pts"][-2], e["pts"][-1]
        ln = max(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5, 1e-9)
        ux, uy = (x2 - x1) / ln, (y2 - y1) / ln
        bx, by = x2 - 8 * ux, y2 - 8 * uy
        o.append(f'<polygon points="{x2},{y2} {bx - 3.5 * uy:.1f},{by + 3.5 * ux:.1f} '
                 f'{bx + 3.5 * uy:.1f},{by - 3.5 * ux:.1f}" fill="{col}"/>')
        if e["name"] and e["name"] != "repeat":
            lx, ly = label_pos(e)
            o.append(f'<text x="{lx}" y="{ly}" font-size="{font - 1}" fill="#b23a48" '
                     f'font-style="italic">{escape(e["name"])}</text>')
    for s in d.shapes.values():
        x, y, w, h = s["x"], s["y"], s["w"], s["h"]
        if s["type"] == "Task":
            fill = "#eef3fb" if s["name"].startswith("W_") else ("#fdf3e6" if s["name"].startswith("O_") else "#ffffff")
            o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill}" '
                     f'stroke="#222" stroke-width="1.4"/>')
            if s["kind"] == "loop":
                cx, cy, r = x + w / 2, y + h - 8, 4.5
                o.append(f'<path d="M{cx + r * 0.7},{cy + r * 0.7} A{r},{r} 0 1 0 {cx - r * 0.7},{cy + r * 0.7}" '
                         f'fill="none" stroke="#222" stroke-width="1.2"/>')
                o.append(f'<path d="M{cx - r * 0.7 - 2.5},{cy + r * 0.7 - 1} L{cx - r * 0.7},{cy + r * 0.7} '
                         f'L{cx - r * 0.7 + 0.5},{cy + r * 0.7 - 3}" fill="none" stroke="#222" stroke-width="1.2"/>')
            lines = wrap(s["name"])
            y0 = y + h / 2 - (len(lines) - 1) * (font + 1) / 2 + font / 3 - (4 if s["kind"] == "loop" else 0)
            for i, l in enumerate(lines):
                o.append(f'<text x="{x + w / 2}" y="{y0 + i * (font + 1)}" font-size="{font}" '
                         f'text-anchor="middle">{escape(l)}</text>')
        elif s["type"].endswith("Gateway"):
            cx, cy = x + w / 2, y + h / 2
            o.append(f'<polygon points="{cx},{y} {x + w},{cy} {cx},{y + h} {x},{cy}" fill="white" '
                     f'stroke="#222" stroke-width="1.4"/>')
            if s["type"] == "ExclusiveGateway":
                k = w * 0.17
                o.append(f'<path d="M{cx - k},{cy - k} L{cx + k},{cy + k} M{cx + k},{cy - k} '
                         f'L{cx - k},{cy + k}" stroke="#222" stroke-width="3"/>')
            else:
                k = w * 0.24
                o.append(f'<path d="M{cx - k},{cy} L{cx + k},{cy} M{cx},{cy - k} L{cx},{cy + k}" '
                         f'stroke="#222" stroke-width="3"/>')
        elif s["type"] in ("StartEvent", "EndEvent"):
            sw = 1.5 if s["type"] == "StartEvent" else 3.5
            o.append(f'<circle cx="{x + w / 2}" cy="{y + h / 2}" r="{w / 2}" fill="white" '
                     f'stroke="#222" stroke-width="{sw}"/>')
        elif s["type"] == "TextAnnotation":
            o.append(f'<path d="M{x + 12},{y} L{x},{y} L{x},{y + h} L{x + 12},{y + h}" fill="none" '
                     f'stroke="#555" stroke-width="1.3"/>')
            for i, l in enumerate(s["name"].split("\n")):
                o.append(f'<text x="{x + 8}" y="{y + 15 + i * (font + 3)}" font-size="{font}">'
                         f'{escape(l)}</text>')
    o.append("</svg>")
    return "\n".join(o)


def svg_to_pdf(svg_path, pdf_path):
    """Convert the SVG figure to PDF for LaTeX (pure Python, needs: pip install svglib)."""
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF
    renderPDF.drawToFile(svg2rlg(svg_path), pdf_path)


def export(tree, bpmn_path, svg_path, labels=None, split_at=(), annotation=None):
    """annotation: (first label of the annotated branch, text with \\n line breaks)."""
    d = layout(tree, labels, split_at)
    if annotation:
        add_annotation(d, *annotation)
    with open(bpmn_path, "w", encoding="utf-8") as f:
        f.write(to_bpmn_xml(d))
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(to_svg(d))
    return d
