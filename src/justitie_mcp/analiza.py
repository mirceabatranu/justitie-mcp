"""Rezumate compacte și raportul de litigii pentru o firmă/persoană, peste datele portalului."""

from __future__ import annotations

import csv
import re
from collections import Counter
from datetime import date
from pathlib import Path

from .portal import LIMITA_PORTAL, normalizeaza_nume

_INSOLVENTA = re.compile(r"INSOLVEN|FALIMENT|REORGANIZAR|LICHIDAR|LEGEA 85|L 85|CONCORDAT", re.I)
_CATEGORII_INSOLVENTA = {"Faliment", "Insolventapersoaneifizice"}
MAX_PARTI_REZUMAT = 8


def _azi() -> str:
    return date.today().isoformat()


def potriveste(nume_parte: str | None, cautat: str) -> bool:
    return bool(nume_parte) and normalizeaza_nume(cautat) in normalizeaza_nume(nume_parte)


def e_insolventa(dosar: dict) -> bool:
    return dosar.get("categorie_cod") in _CATEGORII_INSOLVENTA or bool(_INSOLVENTA.search(dosar.get("obiect") or ""))


def termen_viitor(dosar: dict) -> dict | None:
    azi = _azi()
    viitoare = [s for s in dosar["sedinte"] if s["data"] and s["data"] >= azi]
    if not viitoare:
        return None
    s = min(viitoare, key=lambda s: (s["data"], s["ora"] or ""))
    return {"data": s["data"], "ora": s["ora"], "complet": s["complet"]}


def ultima_solutie(dosar: dict) -> dict | None:
    azi = _azi()
    for s in dosar["sedinte"]:  # deja sortate descrescător
        if s["data"] and s["data"] <= azi and (s["solutie"] or s["solutie_sumar"]):
            sumar = s["solutie_sumar"] or ""
            return {
                "data": s["data"],
                "solutie": s["solutie"],
                "sumar": sumar if len(sumar) <= 600 else sumar[:600] + "…",
                "document": s["document"],
                "numar_document": s["numar_document"],
            }
    return None


def rezumat(dosar: dict, cautat: str | None = None) -> dict:
    """Varianta scurtă a unui dosar, potrivită pentru liste."""
    parti = dosar["parti"]
    if cautat:
        potrivite = [p for p in parti if potriveste(p["nume"], cautat)]
    else:
        potrivite = []
    if len(parti) <= MAX_PARTI_REZUMAT:
        afisate = parti
    else:
        restul = [p for p in parti if p not in potrivite]
        afisate = (potrivite + restul)[:MAX_PARTI_REZUMAT]
    out = {
        "numar": dosar["numar"],
        "institutie": dosar["institutie"],
        "data_inregistrare": dosar["data_inregistrare"],
        "data_modificare": dosar["data_modificare"],
        "obiect": dosar["obiect"],
        "categorie": dosar["categorie"],
        "stadiu": dosar["stadiu"],
        "parti": afisate,
        "nr_parti": len(parti),
        "termen_viitor": termen_viitor(dosar),
        "ultima_solutie": ultima_solutie(dosar),
        "cai_atac": len(dosar["cai_atac"]),
    }
    if cautat:
        out["calitate_parte_cautata"] = sorted({p["calitate"] or "?" for p in potrivite})
    if e_insolventa(dosar):
        out["insolventa"] = True
    return out


def ordoneaza(dosare: list[dict]) -> list[dict]:
    return sorted(dosare, key=lambda d: (d["data_modificare"] or "", d["data_inregistrare"] or ""), reverse=True)


def avertisment_limita(n: int) -> str | None:
    if n >= LIMITA_PORTAL:
        return (
            f"Portalul a întors {n} dosare, adică limita lui maximă: rezultatul e TRUNCHIAT. "
            "Restrânge căutarea (instanță, interval de date, nume mai exact)."
        )
    return None


def raport_litigii(
    dosare: list[dict],
    nume: str,
    doar_nume: list[str] | None = None,
    exclude_nume: list[str] | None = None,
) -> dict:
    """Grupează dosarele în care apare `nume` ca parte.

    `doar_nume`: păstrează doar părțile cu exact aceste denumiri (după normalizare).
    `exclude_nume`: elimină părțile care conțin oricare dintre aceste texte.
    """
    doar = {normalizeaza_nume(x) for x in (doar_nume or [])}
    excl = [normalizeaza_nume(x) for x in (exclude_nume or []) if x.strip()]

    def parte_ok(p: dict) -> bool:
        if not potriveste(p["nume"], nume):
            return False
        n = normalizeaza_nume(p["nume"])
        if doar and n not in doar:
            return False
        return not any(e in n for e in excl)

    variante: Counter[str] = Counter()
    pastrate: list[tuple[dict, list[dict]]] = []
    for d in dosare:
        ale_noastre = [p for p in d["parti"] if potriveste(p["nume"], nume)]
        for p in ale_noastre:
            variante[p["nume"]] += 1
        bune = [p for p in ale_noastre if parte_ok(p)]
        if bune:
            pastrate.append((d, bune))

    calitati: Counter[str] = Counter()
    categorii: Counter[str] = Counter()
    instante: Counter[str] = Counter()
    insolventa_debitor, insolventa_creditor, cu_termen = [], [], []
    for d, bune in pastrate:
        roluri = {(p["calitate"] or "?") for p in bune}
        for r in roluri:
            calitati[r] += 1
        categorii[d["categorie"] or "?"] += 1
        instante[d["institutie"] or "?"] += 1
        if e_insolventa(d):
            if any("DEBITOR" in normalizeaza_nume(r) for r in roluri):
                insolventa_debitor.append(d)
            else:
                insolventa_creditor.append(d)
        if termen_viitor(d):
            cu_termen.append(d)

    rez = lambda lst: [rezumat(d, nume) for d in ordoneaza(lst)]  # noqa: E731
    return {
        "nume_cautat": nume,
        "dosare_gasite_portal": len(dosare),
        "dosare_retinute": len(pastrate),
        "avertisment": avertisment_limita(len(dosare)),
        "variante_nume": [{"nume": n, "dosare": c} for n, c in variante.most_common()],
        "pe_calitate": dict(calitati.most_common()),
        "pe_categorie": dict(categorii.most_common()),
        "pe_instanta": dict(instante.most_common(15)),
        "insolventa_ca_debitor": rez(insolventa_debitor),
        "insolventa_ca_creditor_sau_alt_rol": len(insolventa_creditor),
        "cu_termen_viitor": rez(cu_termen),
        "toate": ordoneaza([d for d, _ in pastrate]),
        "nota": (
            "Portalul caută după text în numele părților: verifică variante_nume și exclude "
            "firmele cu nume asemănător (doar_nume / exclude_nume). Portalul nu conține "
            "dosarele ICCJ și nu are CUI, deci identificarea e după denumire."
        ),
    }


def scrie_csv(dosare: list[dict], cale: str, cautat: str | None = None) -> str:
    path = Path(cale).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(
            ["Număr dosar", "Instanță", "Data înregistrării", "Ultima modificare", "Categorie", "Stadiu",
             "Obiect", "Calitate parte căutată", "Termen viitor", "Ultima soluție (data)", "Ultima soluție",
             "Insolvență", "Nr. părți"]
        )
        for d in ordoneaza(dosare):
            r = rezumat(d, cautat)
            t, s = r["termen_viitor"], r["ultima_solutie"]
            w.writerow([
                r["numar"], r["institutie"], r["data_inregistrare"], r["data_modificare"], r["categorie"],
                r["stadiu"], r["obiect"], ", ".join(r.get("calitate_parte_cautata", [])),
                f'{t["data"]} {t["ora"] or ""}'.strip() if t else "",
                s["data"] if s else "", (s["solutie"] or "") + (f' – {s["sumar"]}' if s and s["sumar"] else "") if s else "",
                "da" if r.get("insolventa") else "", r["nr_parti"],
            ])
    return str(path)
