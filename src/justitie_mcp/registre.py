"""Registre publice ale Ministerului Justiției de pe data.gov.ro (API CKAN), copiate local în
SQLite pentru căutare rapidă.

Observații pe date reale (nov. 2026):

* Registrul Național ONG se actualizează aproape săptămânal (un set de fișiere .xlsx pe
  categorie: asociații, fundații, federații, uniuni, persoane juridice străine). Asociațiile
  au ~130.000 de rânduri (fișier de ~34 MB).
* Experți judiciari, traducători și interpreți, notari, executori judecătorești: ultima
  publicare e din ianuarie 2025. Le aducem, dar raportăm data sursei.
* Celulele conțin artefacte `_x000D_` (CR-uri din Excel) pe care le curățăm.
* Registrele nu au CUI. Căutarea e după denumire/nume, fără diacritice.
"""

from __future__ import annotations

import io
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx

from .portal import fara_diacritice, normalizeaza_nume

CKAN = os.environ.get("JUSTITIE_CKAN_URL", "https://data.gov.ro/api/3/action")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) justitie-mcp/0.3"
TIMEOUT = float(os.environ.get("JUSTITIE_TIMEOUT", "120"))
DB_PATH = Path(
    os.environ.get("JUSTITIE_CACHE_DIR")
    or Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "justitie-mcp"
) / "registre.sqlite"


class RegistruError(RuntimeError):
    pass


# registru -> (regex nume pachet CKAN, categorii {cheie: cuvânt din numele resursei} sau None,
#              zile după care se reîmprospătează automat, descriere)
REGISTRE: dict[str, dict] = {
    "ong": {
        "pachet": r"^registrul-national-ong(-\d{4})?$",
        "categorii": {"asociatie": "asociatii", "fundatie": "fundatii", "federatie": "federatii",
                      "uniune": "uniuni", "persoana_juridica_straina": "pjs"},
        "zile": 7,
        "descriere": "Registrul Național ONG: asociații, fundații, federații, uniuni, persoane juridice străine",
    },
    "experti": {"pachet": r"^experti-judiciari(-\d{4})?$", "categorii": None, "zile": 30,
                "descriere": "Experți tehnici judiciari (legitimație, județ, specializare)"},
    "traducatori": {"pachet": r"^traducatori-si-interpreti(-\d{4})?$", "categorii": None, "zile": 30,
                    "descriere": "Traducători și interpreți autorizați (limbi, curte de apel)"},
    "notari": {"pachet": r"^notari-publici(-\d{4})?$", "categorii": None, "zile": 30,
               "descriere": "Notari publici (cameră, localitate)"},
    "executori": {"pachet": r"^executori-judecatoresti(-\d{4})?$", "categorii": None, "zile": 30,
                  "descriere": "Executori judecătorești (adresă, telefon, cameră)"},
}

# antet normalizat -> câmp standard
_CAMPURI = {
    "nume": ("denumire", "nume", "executor"),
    "numar": ("numar inreg reg national", "nr autorizatie", "legitimatie"),
    "stare": ("starea actuala",),
    "judet": ("judet",),
    "localitate": ("localitate",),
    "adresa": ("adresa", "adresa sediu"),
    "detalii": ("specializare", "limbi", "scopul initial", "camera", "cej", "curte de apel"),
}


def _norm_antet(h) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fara_diacritice(str(h or "")).lower()).strip()


def curata(v) -> str:
    if v is None:
        return ""
    s = str(v).replace("_x000D_", " ").replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------- CKAN


def _get_json(action: str, **params) -> dict:
    try:
        r = httpx.get(f"{CKAN}/{action}", params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        d = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise RegistruError(f"data.gov.ro nu răspunde ({type(e).__name__}: {e}).") from e
    if not d.get("success"):
        raise RegistruError(f"data.gov.ro a refuzat cererea {action}.")
    return d["result"]


def _data_resursa(r: dict) -> datetime:
    m = re.search(r"(\d{1,2})[._ ](\d{1,2})[._ ](\d{4})", r.get("name") or "")
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    s = (r.get("created") or r.get("last_modified") or "")[:19]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime(1970, 1, 1)


def resurse_curente(registru: str, pachete: list[dict] | None = None) -> list[dict]:
    """Cel mai nou fișier .xlsx pentru fiecare categorie a registrului."""
    cfg = REGISTRE[registru]
    if pachete is None:
        pachete = _get_json("package_search", fq="organization:mj", rows=500)["results"]
    potrivite = [p for p in pachete if re.match(cfg["pachet"], p["name"])]
    if not potrivite:
        raise RegistruError(f"Nu găsesc pe data.gov.ro setul de date pentru registrul „{registru}”.")
    toate = [r for p in potrivite for r in p.get("resources", [])
             if (r.get("url") or "").lower().endswith((".xlsx", ".xlsm"))]
    alese = []
    for cat, cuvant in (cfg["categorii"] or {None: None}).items():
        cand = [r for r in toate if cuvant is None or _norm_antet(r.get("name")).startswith(cuvant)]
        if cand:
            best = max(cand, key=_data_resursa)
            alese.append({"categorie": cat, "url": best["url"], "nume": best.get("name"),
                          "data": _data_resursa(best).date().isoformat()})
    return alese


# --------------------------------------------------------------------------- Excel -> rânduri


_IGNORA = {"nr crt", "nr", "crt"}


def citeste_xlsx(continut: bytes) -> list[dict]:
    """Întoarce rândurile ca dict cu câmpuri standard + `extra` (restul coloanelor)."""
    import warnings

    with warnings.catch_warnings():
        # openpyxl avertizează la antete/subsoluri de pagină nestandard; nu ne interesează
        warnings.simplefilter("ignore")
        return _citeste_xlsx(continut)


def _citeste_xlsx(continut: bytes) -> list[dict]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(continut), read_only=True, data_only=True)
    best: list[dict] = []
    for ws in wb.worksheets:
        rows = ws.iter_rows(values_only=True)
        antet, harta = None, {}
        out: list[dict] = []
        for i, row in enumerate(rows):
            if antet is None:
                if i > 15:
                    break
                hs = [_norm_antet(c) for c in row]
                if any(h in _CAMPURI["nume"] for h in hs):
                    antet = [curata(c) for c in row]
                    # ordinea aliasurilor dă prioritatea (ex. la traducători „limbi” înaintea
                    # „curte de apel”, deși coloana Curte de Apel vine prima)
                    for camp, alias in _CAMPURI.items():
                        for a in alias:
                            if a in hs and hs.index(a) not in harta.values():
                                harta[camp] = hs.index(a)
                                break
                continue
            vals = [curata(c) for c in row]
            if not any(vals):
                continue
            rec = {camp: (vals[j] if j < len(vals) else "") for camp, j in harta.items()}
            if not rec.get("nume"):
                continue
            rec["extra"] = {antet[j]: v for j, v in enumerate(vals)
                            if v and j < len(antet) and antet[j] and j not in harta.values()
                            and _norm_antet(antet[j]) not in _IGNORA}
            out.append(rec)
        if len(out) > len(best):
            best = out
    wb.close()
    return best


# --------------------------------------------------------------------------- SQLite

_db_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS inregistrari (
    registru TEXT, categorie TEXT, nume TEXT, nume_norm TEXT, numar TEXT, stare TEXT,
    judet TEXT, judet_norm TEXT, localitate TEXT, localitate_norm TEXT, adresa TEXT,
    detalii TEXT, detalii_norm TEXT, extra TEXT
);
CREATE INDEX IF NOT EXISTS ix_reg ON inregistrari(registru, categorie);
CREATE TABLE IF NOT EXISTS surse (
    registru TEXT, categorie TEXT, nume_fisier TEXT, data_sursa TEXT, url TEXT, randuri INTEGER,
    actualizat TEXT
);
"""


def conectare(path: Path | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=60)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def _norm(s: str) -> str:
    return normalizeaza_nume(s or "")


def incarca(con: sqlite3.Connection, registru: str, categorie: str | None, randuri: list[dict], sursa: dict) -> int:
    with con:
        con.execute("DELETE FROM inregistrari WHERE registru=? AND categorie IS ?", (registru, categorie))
        con.execute("DELETE FROM surse WHERE registru=? AND categorie IS ?", (registru, categorie))
        con.executemany(
            "INSERT INTO inregistrari VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (registru, categorie, r.get("nume"), _norm(r.get("nume")), r.get("numar"), r.get("stare"),
                 r.get("judet"), _norm(r.get("judet")), r.get("localitate"), _norm(r.get("localitate")),
                 r.get("adresa"), r.get("detalii"), _norm(r.get("detalii")),
                 json.dumps(r.get("extra") or {}, ensure_ascii=False))
                for r in randuri
            ],
        )
        con.execute("INSERT INTO surse VALUES (?,?,?,?,?,?,?)",
                    (registru, categorie, sursa.get("nume"), sursa.get("data"), sursa.get("url"), len(randuri),
                     datetime.now().isoformat(timespec="seconds")))
    return len(randuri)


def actualizeaza(registre: list[str] | None = None, path: Path | None = None) -> list[dict]:
    registre = registre or list(REGISTRE)
    for r in registre:
        if r not in REGISTRE:
            raise RegistruError(f"Registru necunoscut: {r}. Disponibile: {', '.join(REGISTRE)}.")
    pachete = _get_json("package_search", fq="organization:mj", rows=500)["results"]
    raport = []
    with _db_lock:
        con = conectare(path)
        try:
            for reg in registre:
                for s in resurse_curente(reg, pachete):
                    t0 = time.monotonic()
                    try:
                        resp = httpx.get(s["url"], headers={"User-Agent": UA}, timeout=600, follow_redirects=True)
                        resp.raise_for_status()
                        randuri = citeste_xlsx(resp.content)
                    except Exception as e:  # noqa: BLE001 - raportăm și continuăm cu restul
                        raport.append({"registru": reg, "categorie": s["categorie"], "eroare": f"{type(e).__name__}: {e}"})
                        continue
                    if not randuri:
                        raport.append({"registru": reg, "categorie": s["categorie"],
                                       "eroare": "fișierul nu are coloanele așteptate; nu am înlocuit datele vechi"})
                        continue
                    n = incarca(con, reg, s["categorie"], randuri, s)
                    raport.append({"registru": reg, "categorie": s["categorie"], "randuri": n,
                                   "data_sursa": s["data"], "secunde": round(time.monotonic() - t0, 1)})
        finally:
            con.close()
    return raport


def stare(path: Path | None = None) -> list[dict]:
    con = conectare(path)
    try:
        return [dict(r) for r in con.execute("SELECT * FROM surse ORDER BY registru, categorie")]
    finally:
        con.close()


def trebuie_actualizat(registru: str, path: Path | None = None) -> bool:
    surse = [s for s in stare(path) if s["registru"] == registru]
    if not surse:
        return True
    cel_vechi = min(datetime.fromisoformat(s["actualizat"]) for s in surse)
    return (datetime.now() - cel_vechi).days >= REGISTRE[registru]["zile"]


def cauta(
    registru: str,
    nume: str | None = None,
    judet: str | None = None,
    localitate: str | None = None,
    detalii: str | None = None,
    categorie: str | None = None,
    numar: str | None = None,
    limita: int = 30,
    path: Path | None = None,
    aproximativ: bool = False,
) -> dict:
    """`aproximativ`: compară doar rădăcina cuvintelor din nume („crucea” -> „cruc”), pentru
    forme articulate/nearticulate („Crucea Roșie” vs. „Cruce Roșie”)."""
    if registru not in REGISTRE:
        raise RegistruError(f"Registru necunoscut: {registru}. Disponibile: {', '.join(REGISTRE)}.")
    if not any([nume, judet, localitate, detalii, numar]):
        raise RegistruError("Dă cel puțin un criteriu: nume, județ, localitate, detalii sau număr.")
    where, args = ["registru = ?"], [registru]
    for col, val in (("nume_norm", nume), ("judet_norm", judet), ("localitate_norm", localitate),
                     ("detalii_norm", detalii)):
        if val:
            for cuv in _norm(val).split():
                if aproximativ and col == "nume_norm" and len(cuv) > 4:
                    cuv = cuv[: max(4, len(cuv) - 2)]
                where.append(f"{col} LIKE ?")
                args.append(f"%{cuv}%")
    if categorie:
        where.append("categorie = ?")
        args.append(categorie)
    if numar:
        where.append("REPLACE(numar,' ','') LIKE ?")
        args.append(f"%{numar.replace(' ', '')}%")
    con = conectare(path)
    try:
        sql = " AND ".join(where)
        total = con.execute(f"SELECT COUNT(*) FROM inregistrari WHERE {sql}", args).fetchone()[0]
        rows = con.execute(f"SELECT * FROM inregistrari WHERE {sql} ORDER BY nume LIMIT ?",
                           args + [max(1, min(int(limita), 500))]).fetchall()
    finally:
        con.close()
    rezultate = []
    for r in rows:
        d = {k: r[k] for k in ("categorie", "nume", "numar", "stare", "judet", "localitate", "adresa", "detalii")
             if r[k]}
        extra = json.loads(r["extra"] or "{}")
        if extra:
            d["alte_campuri"] = {k: (v if len(v) <= 300 else v[:300] + "…") for k, v in extra.items()}
        rezultate.append(d)
    return {"total": total, "afisate": len(rezultate), "rezultate": rezultate}
