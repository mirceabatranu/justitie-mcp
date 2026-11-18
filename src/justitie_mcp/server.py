"""Uneltele MCP pentru datele publice ale instanțelor din România."""

from __future__ import annotations

from datetime import date

from mcp.server.fastmcp import FastMCP

from . import analiza, portal
from .institutii import INSTITUTII

mcp = FastMCP(
    "justitie",
    instructions=(
        "Date publice din Portalul Instanțelor (portal.just.ro): dosare, părți, termene, "
        "soluții pe scurt și ședințe, pentru toate judecătoriile, tribunalele și curțile de "
        "apel. NU conține dosarele ICCJ. Totul e doar citire. Portalul nu are CUI: identificarea "
        "e după denumirea părții, prin potrivire de text. La o verificare de firmă, folosește "
        "portal_litigii_firma, arată utilizatorului variante_nume și întreabă care sunt firma lui "
        "înainte de concluzii. Diacriticele nu contează (sunt scoase automat). Datele de pe portal "
        "sunt informative; pentru acte oficiale contează dosarul de la instanță."
    ),
)


def _eroare(e: Exception) -> dict:
    return {"eroare": str(e)}


@mcp.tool()
def portal_cauta_dosare(
    nume_parte: str | None = None,
    numar_dosar: str | None = None,
    obiect: str | None = None,
    institutie: str | None = None,
    data_inregistrare_de_la: str | None = None,
    data_inregistrare_pana_la: str | None = None,
    modificat_de_la: str | None = None,
    modificat_pana_la: str | None = None,
    doar_cu_termen_viitor: bool = False,
    limita: int = 30,
) -> dict:
    """Caută dosare pe portal.just.ro, pe toate instanțele (sau doar pe una).

    Dă cel puțin unul dintre nume_parte, numar_dosar sau obiect. Numele părții se caută ca
    text conținut („ALFA CONSTRUCT” găsește și „SC ALFA CONSTRUCT SRL”). Datele în format
    AAAA-LL-ZZ. `institutie` acceptă denumirea („Tribunalul Cluj”) sau codul portalului.
    `modificat_de_la` e util pentru a vedea ce s-a schimbat recent (termene, soluții noi).
    Întoarce rezumate ordonate după ultima modificare; detaliile complete cu portal_dosar.
    """
    try:
        dosare = portal.cauta_dosare(
            numar_dosar=numar_dosar, obiect=obiect, nume_parte=nume_parte, institutie=institutie,
            data_start=data_inregistrare_de_la, data_stop=data_inregistrare_pana_la,
            modificat_de_la=modificat_de_la, modificat_pana_la=modificat_pana_la,
        )
    except portal.PortalError as e:
        return _eroare(e)
    total = len(dosare)
    if doar_cu_termen_viitor:
        dosare = [d for d in dosare if analiza.termen_viitor(d)]
    dosare = analiza.ordoneaza(dosare)
    limita = max(1, min(limita, 300))
    return {
        "total_portal": total,
        "dupa_filtre": len(dosare),
        "afisate": min(limita, len(dosare)),
        "avertisment": analiza.avertisment_limita(total),
        "dosare": [analiza.rezumat(d, nume_parte) for d in dosare[:limita]],
    }


@mcp.tool()
def portal_dosar(numar_dosar: str, institutie: str | None = None, max_parti: int = 200) -> dict:
    """Detaliile complete ale unui dosar: părți și calități, toate ședințele cu soluțiile pe scurt,
    căile de atac.

    Același număr poate exista la mai multe instanțe (fond, apel, recurs); fără `institutie`
    le primești pe toate. Dosarele de insolvență pot avea sute de creditori: lista părților se
    oprește la `max_parti`.
    """
    try:
        dosare = portal.cauta_dosare(numar_dosar=numar_dosar, institutie=institutie)
    except portal.PortalError as e:
        return _eroare(e)
    if not dosare:
        return {"gasit": False, "mesaj": f"Niciun dosar cu numărul {numar_dosar} pe portal."}
    out = []
    for d in dosare:
        d = dict(d)
        d["nr_parti"] = len(d["parti"])
        if len(d["parti"]) > max_parti:
            d["parti"] = d["parti"][:max_parti]
            d["parti_trunchiate"] = True
        d["termen_viitor"] = analiza.termen_viitor(d)
        d["insolventa"] = analiza.e_insolventa(d)
        out.append(d)
    return {"gasit": True, "instante": len(out), "dosare": out}


@mcp.tool()
def portal_litigii_firma(
    nume: str,
    institutie: str | None = None,
    doar_nume: list[str] | None = None,
    exclude_nume: list[str] | None = None,
    modificat_de_la: str | None = None,
    salveaza_csv: str | None = None,
    limita: int = 40,
) -> dict:
    """Raport de litigii pentru o firmă sau persoană: în câte dosare apare, cu ce calitate
    (reclamant, pârât, creditor, debitor...), pe categorii și instanțe, dosare de insolvență
    în care e DEBITOR, dosare cu termen viitor.

    Pas 1: rulează cu `nume` și arată utilizatorului `variante_nume` (portalul potrivește text,
    deci apar și firme cu nume asemănător). Pas 2: rulează din nou cu `doar_nume` (denumirile
    exacte confirmate) sau `exclude_nume`. `salveaza_csv`: calea unui fișier .csv cu toate
    dosarele reținute (se deschide în Excel).
    """
    try:
        dosare = portal.cauta_dosare(nume_parte=nume, institutie=institutie, modificat_de_la=modificat_de_la)
    except portal.PortalError as e:
        return _eroare(e)
    raport = analiza.raport_litigii(dosare, nume, doar_nume=doar_nume, exclude_nume=exclude_nume)
    toate = raport.pop("toate")
    limita = max(1, min(limita, 200))
    raport["dosare"] = [analiza.rezumat(d, nume) for d in toate[:limita]]
    raport["dosare_afisate"] = len(raport["dosare"])
    raport["cu_termen_viitor"] = raport["cu_termen_viitor"][:limita]
    if salveaza_csv:
        try:
            raport["csv"] = analiza.scrie_csv(toate, salveaza_csv, nume)
        except OSError as e:
            raport["csv_eroare"] = str(e)
    return raport


@mcp.tool()
def portal_sedinte(
    institutie: str,
    data: str | None = None,
    complet: str | None = None,
    limita_dosare: int = 300,
) -> dict:
    """Ședințele de judecată ale unei instanțe într-o zi (implicit azi): complete, ore și
    dosarele de pe rol. `complet` filtrează după numele completului (text conținut).
    """
    try:
        sedinte = portal.cauta_sedinte(institutie, data or date.today().isoformat())
    except portal.PortalError as e:
        return _eroare(e)
    if complet:
        k = portal.normalizeaza_nume(complet)
        sedinte = [s for s in sedinte if k in portal.normalizeaza_nume(s["complet"] or "")]
    ramase = max(1, min(limita_dosare, 2000))
    for s in sedinte:
        s["nr_dosare"] = len(s["dosare"])
        if len(s["dosare"]) > ramase:
            s["dosare"] = s["dosare"][:ramase]
            s["dosare_trunchiate"] = True
        ramase = max(0, ramase - len(s["dosare"]))
    return {
        "institutie": portal.nume_institutie(portal.rezolva_institutie(institutie)),
        "data": data or date.today().isoformat(),
        "sedinte": len(sedinte),
        "dosare_total": sum(s["nr_dosare"] for s in sedinte),
        "lista": sedinte,
    }


@mcp.tool()
def portal_institutii(filtru: str | None = None) -> dict:
    """Instanțele de pe portal (judecătorii, tribunale, curți de apel), cu codul folosit de
    portal. `filtru`: text din denumire, de ex. „cluj” sau „tribunalul”.
    """
    k = portal._cheie_institutie(filtru) if filtru else ""
    lista = [{"cod": c, "denumire": n} for c, n in INSTITUTII.items() if k in portal._cheie_institutie(n)]
    return {"total": len(lista), "institutii": sorted(lista, key=lambda x: x["denumire"])}


def run() -> None:
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()
