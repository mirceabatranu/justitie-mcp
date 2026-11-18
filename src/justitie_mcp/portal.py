"""Client pentru serviciul SOAP public al Portalului Instanțelor (portalquery.just.ro).

Serviciul e gratuit și nu cere cheie. Particularități observate pe date reale (nov. 2026):

* Textul din baza portalului folosește diacriticele cu sedilă (ş, ţ). O căutare cu ș/ț cu
  virgulă întoarce 0 rezultate, iar una fără diacritice le găsește pe toate. De aceea
  scoatem diacriticele din tot ce trimitem.
* `institutie` poate fi lăsat gol (nil): atunci se caută pe toate instanțele dintr-un apel.
* Portalul întoarce cel mult 1000 de dosare pe cerere. Când primim exact 1000, rezultatul
  e trunchiat și trebuie restrâns (instanță, interval de date, nume mai exact).
* Același număr de dosar apare o dată pentru fiecare instanță prin care a trecut
  (fond, apel, recurs).
"""

from __future__ import annotations

import os
import re
import threading
import time
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date, datetime
from xml.sax.saxutils import escape

import httpx

from .institutii import INSTITUTII

URL = os.environ.get("JUSTITIE_PORTAL_URL", "http://portalquery.just.ro/query.asmx")
NS = "portalquery.just.ro"
LIMITA_PORTAL = 1000
TIMEOUT = float(os.environ.get("JUSTITIE_TIMEOUT", "120"))
CACHE_SECUNDE = int(os.environ.get("JUSTITIE_CACHE_SECUNDE", "600"))
USER_AGENT = "justitie-mcp/0.1 (+client MCP local)"

_T = "{%s}" % NS


class PortalError(RuntimeError):
    pass


# --------------------------------------------------------------------------- text


def fara_diacritice(text: str) -> str:
    """Scoate diacriticele (inclusiv ş/ș, ţ/ț) păstrând restul textului."""
    norm = unicodedata.normalize("NFKD", text)
    return "".join(c for c in norm if not unicodedata.combining(c))


def normalizeaza_nume(text: str) -> str:
    """Formă de comparat pentru nume de părți: fără diacritice, majuscule, fără punctuație."""
    t = fara_diacritice(text or "").upper()
    t = re.sub(r"[^A-Z0-9]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _cheie_institutie(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", fara_diacritice(text).lower())


def rezolva_institutie(text: str | None) -> str | None:
    """Transformă „Tribunalul București”, „tribunalul bucuresti” sau codul în codul portalului."""
    if not text:
        return None
    if text in INSTITUTII:
        return text
    k = _cheie_institutie(text)
    exacte = [c for c, n in INSTITUTII.items() if _cheie_institutie(c) == k or _cheie_institutie(n) == k]
    if len(exacte) == 1:
        return exacte[0]
    partiale = [c for c, n in INSTITUTII.items() if k in _cheie_institutie(n)]
    if len(partiale) == 1:
        return partiale[0]
    if not partiale:
        raise PortalError(f"Instanța „{text}” nu există în lista portalului. Folosește portal_institutii.")
    variante = ", ".join(INSTITUTII[c] for c in partiale[:15])
    raise PortalError(f"„{text}” se potrivește cu mai multe instanțe: {variante}. Precizează.")


def nume_institutie(cod: str | None) -> str | None:
    if not cod:
        return None
    return INSTITUTII.get(cod, cod)


# --------------------------------------------------------------------------- SOAP


def _dt(value: str | date | None, sfarsit_zi: bool = False) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    if isinstance(value, date):
        d = value
    else:
        s = str(value).strip()
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                continue
        else:
            raise PortalError(f"Dată nerecunoscută: „{value}”. Folosește AAAA-LL-ZZ.")
    return d.strftime("%Y-%m-%d") + ("T23:59:59" if sfarsit_zi else "T00:00:00")


def _element(name: str, value: str | None, nillable: bool) -> str:
    if value is None:
        return f'<{name} xsi:nil="true"/>' if nillable else ""
    return f"<{name}>{escape(value)}</{name}>"


def _envelope(op: str, body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        f'<soap:Body><{op} xmlns="{NS}">{body}</{op}></soap:Body></soap:Envelope>'
    ).encode("utf-8")


_cache: dict[tuple, tuple[float, bytes]] = {}
_lock = threading.Lock()


def _post(op: str, body: str) -> bytes:
    key = (op, body)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_SECUNDE:
            return hit[1]
    try:
        r = httpx.post(
            URL,
            content=_envelope(op, body),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{NS}/{op}"',
                "User-Agent": USER_AGENT,
            },
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        raise PortalError(f"Portalul instanțelor nu răspunde ({type(e).__name__}: {e}). Încearcă mai târziu.") from e
    if r.status_code != 200:
        m = re.search(r"<faultstring>(.*?)</faultstring>", r.text, re.S)
        raise PortalError(f"Portalul a răspuns cu eroare {r.status_code}: {m.group(1) if m else r.text[:300]}")
    with _lock:
        if len(_cache) > 200:
            _cache.clear()
        _cache[key] = (now, r.content)
    return r.content


# --------------------------------------------------------------------------- parsare


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _text(el: ET.Element | None, name: str) -> str | None:
    if el is None:
        return None
    child = el.find(_T + name)
    if child is None or child.text is None:
        return None
    t = child.text.strip()
    return t or None


def _data(value: str | None) -> str | None:
    """'2026-01-20T12:58:00' -> '2026-01-20'; păstrează None."""
    if not value or value.startswith("0001-01-01"):
        return None
    return value[:10]


def _items(parent: ET.Element | None, name: str) -> list[ET.Element]:
    if parent is None:
        return []
    return [c for c in parent if _local(c.tag) == name]


def parse_dosare(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    result = root.find(f".//{_T}CautareDosare2Result")
    if result is None:
        result = root.find(f".//{_T}CautareDosareResult")
    dosare = []
    for d in _items(result, "Dosar"):
        parti = [
            {"nume": _text(p, "nume"), "calitate": _text(p, "calitateParte")}
            for p in _items(d.find(_T + "parti"), "DosarParte")
        ]
        sedinte = [
            {
                "data": _data(_text(s, "data")),
                "ora": _text(s, "ora"),
                "complet": _text(s, "complet"),
                "solutie": _text(s, "solutie"),
                "solutie_sumar": _text(s, "solutieSumar"),
                "data_pronuntare": _data(_text(s, "dataPronuntare")),
                "document": _text(s, "documentSedinta"),
                "numar_document": _text(s, "numarDocument"),
                "data_document": _data(_text(s, "dataDocument")),
            }
            for s in _items(d.find(_T + "sedinte"), "DosarSedinta")
        ]
        cai = [
            {
                "data_declarare": _data(_text(c, "dataDeclarare")),
                "parte_declaratoare": _text(c, "parteDeclaratoare"),
                "tip": _text(c, "tipCaleAtac"),
            }
            for c in _items(d.find(_T + "caiAtac"), "DosarCaleAtac")
        ]
        cod = _text(d, "institutie")
        dosare.append(
            {
                "numar": _text(d, "numar"),
                "numar_vechi": _text(d, "numarVechi"),
                "institutie": nume_institutie(cod),
                "institutie_cod": cod,
                "departament": _text(d, "departament"),
                "data_inregistrare": _data(_text(d, "data")),
                "data_modificare": _data(_text(d, "dataModificare")),
                "obiect": _text(d, "obiect"),
                "categorie": _text(d, "categorieCazNume") or _text(d, "categorieCaz"),
                "categorie_cod": _text(d, "categorieCaz"),
                "stadiu": _text(d, "stadiuProcesualNume") or _text(d, "stadiuProcesual"),
                "parti": parti,
                "sedinte": sorted(sedinte, key=lambda s: s["data"] or "", reverse=True),
                "cai_atac": cai,
            }
        )
    return dosare


def parse_sedinte(xml: bytes) -> list[dict]:
    root = ET.fromstring(xml)
    result = root.find(f".//{_T}CautareSedinteResult")
    out = []
    for s in _items(result, "Sedinta"):
        out.append(
            {
                "data": _data(_text(s, "data")),
                "ora": _text(s, "ora"),
                "complet": _text(s, "complet"),
                "departament": _text(s, "departament"),
                "dosare": [
                    {
                        "numar": _text(d, "numar"),
                        "ora": _text(d, "ora"),
                        "categorie": _text(d, "categorieCazNume") or _text(d, "categorieCaz"),
                        "stadiu": _text(d, "stadiuProcesualNume") or _text(d, "stadiuProcesual"),
                    }
                    for d in _items(s.find(_T + "dosare"), "SedintaDosar")
                ],
            }
        )
    return out


# --------------------------------------------------------------------------- operații


def cauta_dosare(
    numar_dosar: str | None = None,
    obiect: str | None = None,
    nume_parte: str | None = None,
    institutie: str | None = None,
    data_start: str | None = None,
    data_stop: str | None = None,
    modificat_de_la: str | None = None,
    modificat_pana_la: str | None = None,
) -> list[dict]:
    """CautareDosare2. Măcar unul dintre numar_dosar / obiect / nume_parte e obligatoriu."""
    if not (numar_dosar or obiect or nume_parte):
        raise PortalError("Dă cel puțin un număr de dosar, un obiect sau un nume de parte.")
    if nume_parte and len(normalizeaza_nume(nume_parte)) < 3:
        raise PortalError("Numele părții e prea scurt (minim 3 caractere).")
    curat = lambda s: fara_diacritice(s.strip()) if s else None  # noqa: E731
    body = "".join(
        [
            _element("numarDosar", numar_dosar.strip() if numar_dosar else None, False),
            _element("obiectDosar", curat(obiect), False),
            _element("numeParte", curat(nume_parte), False),
            _element("institutie", rezolva_institutie(institutie), True),
            _element("dataStart", _dt(data_start), True),
            _element("dataStop", _dt(data_stop, sfarsit_zi=True), True),
            _element("dataUltimaModificareStart", _dt(modificat_de_la), True),
            _element("dataUltimaModificareStop", _dt(modificat_pana_la, sfarsit_zi=True), True),
        ]
    )
    return parse_dosare(_post("CautareDosare2", body))


def cauta_sedinte(institutie: str, data_sedinta: str) -> list[dict]:
    cod = rezolva_institutie(institutie)
    if not cod:
        raise PortalError("Instanța e obligatorie pentru căutarea ședințelor.")
    body = _element("dataSedinta", _dt(data_sedinta), False) + _element("institutie", cod, False)
    return parse_sedinte(_post("CautareSedinte", body))
