"""Portalul Legislativ (legislatie.just.ro): căutare prin serviciul SOAP oficial gratuit
`FreeWebService` (GetToken + Search) și text consolidat din pagina actului.

Particularități observate pe date reale (nov. 2026):

* Serviciul refuză (403) cererile fără User-Agent de browser.
* `Search` întoarce și textul integral al fiecărui act (Codul fiscal: câțiva MB). Noi îl
  folosim doar pentru fragmente, nu îl trimitem lui Claude.
* `DetaliiDocument/{id}` afișează ultima formă consolidată a actului (id-ul ei e în
  `<input id="id_act">`) și „istoric consolidări”: data -> id pentru fiecare formă.
* Textul e marcat cu clase: S_TTL/S_CAP/S_SEC (titlu, capitol, secțiune), S_ART (articol),
  S_ALN (alineat), S_LIT (literă), S_PCT (punct), S_NTA (notă), S_ANX (anexă). Elementele
  *_SHORT sunt rezumate ascunse („...”) și se ignoră.
"""

from __future__ import annotations

import os
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from xml.sax.saxutils import escape

import httpx

from .portal import fara_diacritice

BASE = os.environ.get("JUSTITIE_LEGISLATIE_URL", "https://legislatie.just.ro")
SOAP_URL = BASE + "/apiws/FreeWebService.svc/SOAP"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) justitie-mcp/0.2"
TIMEOUT = float(os.environ.get("JUSTITIE_TIMEOUT", "120"))
CACHE_ORE = float(os.environ.get("JUSTITIE_LEGISLATIE_CACHE_ORE", "24"))
CACHE_DIR = Path(
    os.environ.get("JUSTITIE_CACHE_DIR")
    or Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "justitie-mcp"
) / "legislatie"

_DC = "http://schemas.datacontract.org/2004/07/FreeWebService"


class LegislatieError(RuntimeError):
    pass


# --------------------------------------------------------------------------- SOAP


_token: dict = {"val": None, "t": 0.0}
_tok_lock = threading.Lock()


def _soap(op: str, body: str) -> str:
    env = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
        f"<s:Body>{body}</s:Body></s:Envelope>"
    )
    try:
        r = httpx.post(
            SOAP_URL,
            content=env.encode("utf-8"),
            headers={
                "User-Agent": UA,
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"http://tempuri.org/IFreeWebService/{op}"',
            },
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise LegislatieError(f"Portalul legislativ nu răspunde ({type(e).__name__}: {e}).") from e
    if r.status_code != 200:
        m = re.search(r"<faultstring[^>]*>(.*?)</faultstring>", r.text, re.S)
        raise LegislatieError(f"Portalul legislativ a răspuns cu eroare {r.status_code}: {m.group(1) if m else r.text[:300]}")
    return r.text


def _get_token(nou: bool = False) -> str:
    with _tok_lock:
        if not nou and _token["val"] and time.monotonic() - _token["t"] < 1800:
            return _token["val"]
        t = _soap("GetToken", '<GetToken xmlns="http://tempuri.org/"/>')
        m = re.search(r"<GetTokenResult>([^<]+)</GetTokenResult>", t)
        if not m:
            raise LegislatieError("Portalul legislativ nu a dat token de acces.")
        _token.update(val=m.group(1), t=time.monotonic())
        return _token["val"]


def _curata_titlu(t: str | None) -> str:
    t = (t or "").replace("﻿", "")
    t = re.split(r"\s+EMITENT\s*:?", t, maxsplit=1)[0]
    return re.sub(r"\s+", " ", t).strip()


def _fragment(text: str, cautat: str, lat: int = 160) -> str | None:
    if not text or not cautat:
        return None
    flat = re.sub(r"\s+", " ", text)
    plain = fara_diacritice(flat).lower()
    words = [w for w in re.findall(r"\w+", fara_diacritice(cautat).lower()) if len(w) > 2] or [cautat.lower()]
    i = plain.find(fara_diacritice(cautat).lower())
    if i < 0:
        i = next((plain.find(w) for w in words if plain.find(w) >= 0), -1)
    if i < 0:
        return None
    a, b = max(0, i - lat), min(len(flat), i + len(cautat) + lat)
    return ("…" if a else "") + flat[a:b].strip() + ("…" if b < len(flat) else "")


def _camp(x: str, name: str) -> str | None:
    m = re.search(rf"<a:{name}>(.*?)</a:{name}>", x, re.S)
    return unescape(m.group(1)).strip() if m else None


def cauta(
    text: str | None = None,
    titlu: str | None = None,
    numar: str | None = None,
    an: str | int | None = None,
    pagina: int = 1,
    rezultate: int = 10,
) -> list[dict]:
    """Search din FreeWebService. `pagina` începe de la 1."""
    if not (text or titlu or numar or an):
        raise LegislatieError("Dă cel puțin un criteriu: text, titlu, număr sau an.")
    camp = lambda n, v: f"<a:{n}>{escape(str(v))}</a:{n}>" if v not in (None, "") else ""  # noqa: E731
    model = (
        f"<a:NumarPagina>{max(1, int(pagina))}</a:NumarPagina>"
        f"<a:RezultatePagina>{max(1, min(int(rezultate), 50))}</a:RezultatePagina>"
        + camp("SearchAn", an) + camp("SearchNumar", numar) + camp("SearchText", text) + camp("SearchTitlu", titlu)
    )

    def body(tok: str) -> str:
        return (
            '<Search xmlns="http://tempuri.org/">'
            f'<SearchModel xmlns:a="{_DC}" xmlns:i="http://www.w3.org/2001/XMLSchema-instance">{model}</SearchModel>'
            f"<tokenKey>{escape(tok)}</tokenKey></Search>"
        )

    try:
        raw = _soap("Search", body(_get_token()))
    except LegislatieError:
        raw = _soap("Search", body(_get_token(nou=True)))
    out = []
    for m in re.finditer(r"<a:Legi>(.*?)</a:Legi>", raw, re.S):
        x = m.group(1)
        link = _camp(x, "LinkHtml") or ""
        idm = re.search(r"/(\d+)\s*$", link)
        titlu_c = _curata_titlu(_camp(x, "Titlu"))
        mo = re.search(r"MONITORUL OFICIAL\s+(?:NR\.|nr\.)\s*([\d.]+(?:\s*bis)?)\s+din\s+([\w ]+?\d{4})", _camp(x, "Titlu") or "", re.I)
        corp = _camp(x, "Text") or ""
        out.append(
            {
                "id": int(idm.group(1)) if idm else None,
                "tip": (_camp(x, "TipAct") or "").strip() or None,
                "numar": _camp(x, "Numar"),
                "data": _camp(x, "DataVigoare"),
                "emitent": _camp(x, "Emitent"),
                "titlu": titlu_c,
                "monitorul_oficial": f"MO nr. {mo.group(1)} din {mo.group(2).strip()}" if mo else _camp(x, "Publicatie"),
                "link": link.replace("http://", "https://"),
                "fragment": _fragment(corp, text) if text else None,
                "lungime_text": len(corp),
            }
        )
    return out


# --------------------------------------------------------------------------- pagina actului


def _cache_path(act_id: int) -> Path:
    return CACHE_DIR / f"{int(act_id)}.html"


def descarca(act_id: int, fortat: bool = False) -> str:
    path = _cache_path(act_id)
    if not fortat and path.exists() and time.time() - path.stat().st_mtime < CACHE_ORE * 3600:
        return path.read_text(encoding="utf-8")
    try:
        r = httpx.get(f"{BASE}/Public/DetaliiDocument/{int(act_id)}", headers={"User-Agent": UA},
                      timeout=TIMEOUT, follow_redirects=True)
    except httpx.HTTPError as e:
        raise LegislatieError(f"Nu pot descărca actul {act_id} ({type(e).__name__}: {e}).") from e
    if r.status_code != 200:
        raise LegislatieError(f"Portalul legislativ a răspuns {r.status_code} pentru actul {act_id}.")
    html = r.text
    if "S_DEN" not in html and "id_act" not in html:
        raise LegislatieError(f"Actul {act_id} nu există pe legislatie.just.ro (sau pagina nu are text).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return html


class Node:
    __slots__ = ("tag", "cls", "id", "hidden", "children", "parent")

    def __init__(self, tag: str, attrs: dict, parent: "Node | None"):
        self.tag = tag
        self.cls = (attrs.get("class") or "").split()
        self.id = attrs.get("id")
        style = (attrs.get("style") or "").replace(" ", "").lower()
        self.hidden = "display:none" in style
        self.children: list = []
        self.parent = parent

    def has(self, c: str) -> bool:
        return c in self.cls


_VOID = {"br", "img", "input", "hr", "meta", "link", "col", "area", "base", "wbr", "source"}


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, dict(attrs), self.cur)
        self.cur.children.append(n)
        if tag == "br":
            return
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, dict(attrs), self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not None and n.tag != tag:
            n = n.parent
        if n is not None and n.parent is not None:
            self.cur = n.parent

    def handle_data(self, data):
        if data:
            self.cur.children.append(data)


_BLOCK = {"S_ART", "S_ALN", "S_LIT", "S_PCT", "S_PAR", "S_LIN", "S_NTA", "S_NTA_PAR", "S_TTL", "S_CAP",
          "S_SEC", "S_SSEC", "S_ANX", "S_PRE", "S_DEN", "S_HDR", "S_PUB", "S_EMT", "S_NTA_TTL",
          "S_ART_TTL", "S_CAP_TTL", "S_TTL_TTL", "S_SEC_TTL", "S_ANX_TTL"}
_BLOCK_TAGS = {"p", "div", "tr", "li", "table", "h1", "h2", "h3", "h4"}


def _skip(n: Node, note: bool) -> bool:
    if n.hidden or n.has("TAG_COLLAPSED") or any(c.endswith("_SHORT") for c in n.cls):
        return True
    return not note and n.has("S_NTA")


def text_nod(n: Node, note: bool = True) -> str:
    parts: list[str] = []

    def walk(x):
        if isinstance(x, str):
            parts.append(x)
            return
        if x.tag in ("script", "style") or _skip(x, note):
            return
        block = x.tag in _BLOCK_TAGS or x.tag == "br" or any(c in _BLOCK for c in x.cls)
        if block:
            parts.append("\n")
        if x.has("S_NTA"):
            parts.append("[")
        for c in x.children:
            walk(c)
        if x.has("S_NTA"):
            parts.append("]")
        if block:
            parts.append("\n")

    walk(n)
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in "".join(parts).split("\n")]
    text = "\n".join(ln for ln in lines if ln).replace("\n]", "]").replace("[\n", "[")
    # Notele de modificare „(la 01-08-2025, Alineatul (1) ... a fost modificat de ...)” vin pe
    # mai multe rânduri: le lipim pe unul singur, sau le scoatem când note=False.
    text = _MODIF.sub(lambda m: "" if not note else
                      "(la %s, %s)" % (m.group(1), re.sub(r"\s*\n\s*", " ", m.group(2)).strip()), text)
    return re.sub(r"\n{2,}", "\n", text).strip()


_MODIF = re.compile(r"\(la (\d\d-\d\d-\d{4}),\s*\n?(.*?)\n?\s*\)(?=\n|$)", re.S)


def _find(n: Node, pred) -> Node | None:
    stack = [n]
    while stack:
        x = stack.pop()
        if isinstance(x, Node):
            if pred(x):
                return x
            stack.extend(reversed(x.children))
    return None


def _child_text(n: Node, cls: str) -> str | None:
    for c in n.children:
        if isinstance(c, Node) and c.has(cls):
            t = text_nod(c, note=False).replace("\n", " ").strip()
            return t or None
    return None


def _denumire_art(art: Node) -> str | None:
    """Codurile pun denumirea articolului („Cotele”) în primul paragraf din corp."""
    bdy = next((c for c in art.children if isinstance(c, Node) and c.has("S_ART_BDY")), None)
    if bdy is None:
        return None
    first = next((c for c in bdy.children if isinstance(c, Node) and not c.hidden), None)
    if first is None or not first.has("S_PAR"):
        return None
    t = text_nod(first, note=False).replace("\n", " ").strip()
    return t if 0 < len(t) <= 120 and not t.startswith("(") else None


def cheie_articol(nr: str) -> str:
    """'Articolul 25^1', 'art. 25 ind. 1', '25¹', '25^1' -> '25^1'."""
    s = str(nr).replace("¹", "^1").replace("²", "^2").replace("³", "^3")
    s = fara_diacritice(s).lower()
    s = re.sub(r"^\s*(articolul|articol|art\.?)\s*", "", s)
    s = re.sub(r"\s*(\^|ind\.?|indice)\s*", "^", s)
    return re.sub(r"\s+", "", s)


class Act:
    """Un act parsat: antet, istoric consolidări, structură și articole."""

    def __init__(self, act_id: int, html: str):
        self.cerut = act_id
        m = re.search(r'id="id_act"[^>]*value="(\d+)"', html)
        self.id = int(m.group(1)) if m else act_id
        self.istoric = []
        for tag in re.findall(r"<a title='Consolidarea din [^>]*>", html):
            d = re.search(r"Consolidarea din ([\d.]+)", tag).group(1)
            h = re.search(r"/DetaliiDocument/(\d+)", tag)
            self.istoric.append({"data": d, "id": int(h.group(1)) if h else self.id})
        b = _Builder()
        b.feed(html)
        cont = _find(b.root, lambda x: x.id == "div_Formaconsolidata") or b.root
        if not _find(cont, lambda x: x.has("S_DEN")):
            cont = b.root
        self.radacina = cont
        g = lambda c: (lambda n: text_nod(n, note=False).replace("\n", " ").strip() if n else None)(  # noqa: E731
            _find(cont, lambda x: x.has(c)))
        self.denumire = g("S_DEN")
        self.subtitlu = g("S_HDR")
        self.emitent = g("S_EMT_BDY")
        self.publicat = g("S_PUB_BDY")
        self.articole: "OrderedDict[str, dict]" = OrderedDict()
        self.structura: list[dict] = []
        self._indexeaza(cont)
        # Unele acte sunt doar „învelișul” (ex. Legea 227/2015 privind Codul fiscal) și trimit
        # la documentul cu textul propriu-zis prin linkuri DetaliiDocumentAfis/<id>.
        self.trimiteri: list[int] = []
        if len(self.articole) <= 3:
            for i in re.findall(r"DetaliiDocumentAfis/(\d+)", html):
                if int(i) != self.id and int(i) not in self.trimiteri:
                    self.trimiteri.append(int(i))
            self.trimiteri = self.trimiteri[:10]

    def _indexeaza(self, cont: Node) -> None:
        heading_cls = {"S_TTL": "TTL", "S_CAP": "CAP", "S_SEC": "SEC", "S_SSEC": "SSEC", "S_ANX": "ANX"}

        def walk(n: Node, cale: list[str]):
            for c in n.children:
                if not isinstance(c, Node) or c.hidden:
                    continue
                kind = next((heading_cls[k] for k in heading_cls if c.has(k)), None)
                if kind:
                    ttl = _child_text(c, f"S_{kind}_TTL") or ""
                    den = _child_text(c, f"S_{kind}_DEN") or ""
                    eticheta = (ttl + (" – " + den if den else "")).strip(" –")
                    self.structura.append({"nivel": kind, "titlu": eticheta, "cale": " > ".join(cale)})
                    if kind == "ANX":
                        key = cheie_articol(ttl or f"anexa{len(self.articole)}")
                        self.articole.setdefault(key, {"nr": ttl, "denumire": den, "cale": " > ".join(cale), "nod": c})
                    walk(c, cale + [eticheta])
                elif c.has("S_ART"):
                    ttl = _child_text(c, "S_ART_TTL") or f"Articolul ?{len(self.articole) + 1}"
                    key = cheie_articol(ttl)
                    if key in self.articole:  # numere repetate (ex. articole citate în note)
                        key = f"{key}#{sum(1 for k in self.articole if k.split('#')[0] == key) + 1}"
                    self.articole[key] = {"nr": ttl, "denumire": _child_text(c, "S_ART_DEN") or _denumire_art(c),
                                          "cale": " > ".join(cale), "nod": c}
                else:
                    walk(c, cale)

        walk(cont, [])

    def antet(self) -> dict:
        return {
            "id_cerut": self.cerut,
            "id_forma": self.id,
            "denumire": self.denumire,
            "subtitlu": self.subtitlu,
            "emitent": self.emitent,
            "publicat": self.publicat,
            "consolidare": self.istoric[0]["data"] if self.istoric else None,
            "link": f"{BASE}/Public/DetaliiDocument/{self.id}",
        }

    def articol(self, nr: str, note: bool = True) -> dict | None:
        a = self.articole.get(cheie_articol(nr))
        if a is None:
            return None
        return {"nr": a["nr"], "denumire": a["denumire"], "cale": a["cale"], "text": text_nod(a["nod"], note=note)}

    def cauta(self, text: str, max_rezultate: int = 30) -> list[dict]:
        k = fara_diacritice(text).lower()
        out = []
        for a in self.articole.values():
            t = text_nod(a["nod"], note=False)
            if k in fara_diacritice(t).lower():
                out.append({"nr": a["nr"], "denumire": a["denumire"], "cale": a["cale"], "fragment": _fragment(t, text)})
                if len(out) >= max_rezultate:
                    break
        return out


_acte: "OrderedDict[int, Act]" = OrderedDict()
_acte_lock = threading.Lock()


def act(act_id: int, fortat: bool = False) -> Act:
    act_id = int(act_id)
    with _acte_lock:
        if not fortat and act_id in _acte:
            _acte.move_to_end(act_id)
            return _acte[act_id]
    a = Act(act_id, descarca(act_id, fortat=fortat))
    with _acte_lock:
        _acte[act_id] = a
        while len(_acte) > 6:
            _acte.popitem(last=False)
    return a


def forma_la_data(a: Act, la_data: str) -> int:
    """Id-ul formei consolidate în vigoare la o dată (cea mai recentă consolidare <= data)."""
    try:
        tinta = datetime.strptime(la_data, "%Y-%m-%d").date()
    except ValueError:
        tinta = datetime.strptime(la_data, "%d.%m.%Y").date()
    for f in a.istoric:  # descrescător
        if datetime.strptime(f["data"], "%d.%m.%Y").date() <= tinta:
            return f["id"]
    raise LegislatieError(f"Nu există o formă consolidată la {la_data} (prima e din {a.istoric[-1]['data']})."
                          if a.istoric else "Actul nu are istoric de consolidări.")


def id_din_link(x: str | int) -> int:
    if isinstance(x, int):
        return x
    m = re.search(r"(\d+)\s*$", str(x).strip())
    if not m:
        raise LegislatieError(f"Nu recunosc id-ul actului din „{x}”.")
    return int(m.group(1))
