"""Uneltele MCP pentru datele publice ale instanțelor din România."""

from __future__ import annotations

from datetime import date

from mcp.server.fastmcp import FastMCP

from . import analiza, legislatie, portal, registre
from .institutii import INSTITUTII

mcp = FastMCP(
    "justitie",
    instructions=(
        "Registre MJ de pe data.gov.ro (registru_*): Registrul Național ONG (actualizat "
        "săptămânal), experți judiciari, traducători, notari, executori; spune utilizatorului "
        "data sursei. "
        "Legislație (legislatie.just.ro, uneltele lege_*): caută actul cu lege_cauta, apoi "
        "citește doar articolele necesare cu lege_articol sau caută în el cu lege_cauta_in_act; "
        "nu cere tot cuprinsul unui cod mare fără filtru. Textul e forma consolidată cea mai "
        "recentă, sau cea de la o dată cu la_data; citează articolul și data consolidării. "
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


# --------------------------------------------------------------------------- legislație


def _act_la_data(act: str | int, la_data: str | None) -> "legislatie.Act":
    a = legislatie.act(legislatie.id_din_link(act))
    if la_data:
        fid = legislatie.forma_la_data(a, la_data)
        if fid != a.id:
            a = legislatie.act(fid)
    return a


def _antet(a: "legislatie.Act") -> dict:
    h = a.antet()
    h["articole"] = len(a.articole)
    if a.trimiteri:
        h["vezi_textul_in"] = a.trimiteri
        h["nota"] = ("Documentul are puțin text propriu și trimite la alt document (de ex. legea care "
                     "aprobă un cod). Pentru text, folosește id-urile din vezi_textul_in.")
    return h


@mcp.tool()
def lege_cauta(
    titlu: str | None = None,
    text: str | None = None,
    numar: str | None = None,
    an: int | None = None,
    tip: str | None = None,
    pagina: int = 1,
    rezultate: int = 10,
) -> dict:
    """Caută acte normative pe legislatie.just.ro (legi, OUG, OG, HG, ordine, decizii CCR,
    decizii ICCJ RIL/HP publicate în Monitorul Oficial...).

    `titlu`: cuvinte din titlu (cel mai precis, ex. „Codul fiscal”, „contabilitatii”);
    `text`: cuvinte din corpul actului (întoarce și un fragment); `numar` + `an` pentru un act
    anume (ex. numar=82, an=1991). `tip` filtrează după tipul actului (LEGE, ORDONANȚĂ DE
    URGENȚĂ, HOTĂRÂRE, ORDIN...). Întoarce id-ul de folosit în lege_cuprins / lege_articol.
    """
    try:
        rez = legislatie.cauta(text=text, titlu=titlu, numar=numar, an=an, pagina=pagina, rezultate=rezultate)
    except legislatie.LegislatieError as e:
        return _eroare(e)
    if an:  # portalul nu aplică strict filtrul de an
        rez = [r for r in rez if (r["data"] or "").startswith(str(an)) or f" {an}" in r["titlu"]]
    if tip:
        k = portal.fara_diacritice(tip).upper()
        rez = [r for r in rez if k in portal.fara_diacritice(r["tip"] or r["titlu"]).upper()]
    for r in rez:
        if not r["fragment"]:
            r.pop("fragment")
    return {"pagina": pagina, "rezultate": len(rez), "acte": rez,
            "nota": "Portalul nu ordonează după relevanță: verifică titlul și data fiecărui act."}


@mcp.tool()
def lege_cuprins(
    act: str,
    la_data: str | None = None,
    cu_articole: bool = False,
    filtru: str | None = None,
) -> dict:
    """Antetul și cuprinsul unui act, în forma consolidată (implicit cea mai recentă).

    `act`: id-ul (din lege_cauta) sau linkul legislatie.just.ro. `la_data` (AAAA-LL-ZZ): forma
    consolidată în vigoare la acea dată. `cu_articole`: listează și articolele (număr +
    denumire); la coduri mari restrânge cu `filtru` (text din titlu/capitol/denumire, ex. „TVA”,
    „microîntreprinderi”). Include ultimele consolidări (istoricul).
    """
    try:
        a = _act_la_data(act, la_data)
    except (legislatie.LegislatieError, ValueError) as e:
        return _eroare(e)
    out = _antet(a)
    out["istoric_consolidari"] = a.istoric[:12]
    out["istoric_total"] = len(a.istoric)
    k = portal.fara_diacritice(filtru).lower() if filtru else None
    potriveste = lambda s: not k or k in portal.fara_diacritice(s or "").lower()  # noqa: E731
    out["structura"] = [s["titlu"] for s in a.structura
                        if s["nivel"] != "ANX" and (potriveste(s["titlu"]) or potriveste(s["cale"]))][:300]
    if cu_articole:
        arts = [{"nr": v["nr"].replace("Articolul ", "Art. "), "denumire": v["denumire"], "cale": v["cale"]}
                for v in a.articole.values()
                if potriveste(v["cale"]) or potriveste(v["denumire"]) or potriveste(v["nr"])]
        if len(arts) > 400:
            out["articole_trunchiate"] = len(arts)
            arts = arts[:400]
        # calea se repetă: o păstrăm doar când se schimbă
        prev = None
        for x in arts:
            if x["cale"] == prev:
                x.pop("cale")
            else:
                prev = x["cale"]
        out["lista_articole"] = arts
    return out


@mcp.tool()
def lege_articol(
    act: str,
    articole: list[str],
    la_data: str | None = None,
    note: bool = True,
    max_caractere: int = 15000,
) -> dict:
    """Textul consolidat al unor articole (ex. ["291", "25^1", "Anexa 1"]).

    `note`: include notele de modificare „(la 01-08-2025, ... a fost modificat de Legea ...)”,
    utile ca să știi de când se aplică textul. `la_data`: textul în vigoare la o dată anume.
    """
    try:
        a = _act_la_data(act, la_data)
    except (legislatie.LegislatieError, ValueError) as e:
        return _eroare(e)
    gasite, lipsa = [], []
    for nr in articole[:30]:
        x = a.articol(nr, note=note)
        if x is None:
            lipsa.append(nr)
            continue
        if len(x["text"]) > max_caractere:
            x["text"] = x["text"][:max_caractere] + "\n[… trunchiat]"
            x["trunchiat"] = True
        gasite.append(x)
    out = {"act": _antet(a), "articole": gasite}
    if lipsa:
        out["negasite"] = lipsa
        out["sugestie"] = "Verifică numerotarea cu lege_cuprins(cu_articole=True) sau lege_cauta_in_act."
    return out


@mcp.tool()
def lege_cauta_in_act(act: str, text: str, la_data: str | None = None, max_rezultate: int = 30) -> dict:
    """Caută un text în articolele unui act (ex. „plafonul de 100.000 euro” în Codul fiscal) și
    întoarce articolele în care apare, cu fragmente. Diacriticele nu contează. Notele de
    modificare nu sunt incluse în căutare.
    """
    try:
        a = _act_la_data(act, la_data)
    except (legislatie.LegislatieError, ValueError) as e:
        return _eroare(e)
    rez = a.cauta(text, max_rezultate=max(1, min(max_rezultate, 100)))
    return {"act": _antet(a), "gasite": len(rez), "articole": rez}


# --------------------------------------------------------------------------- registre data.gov.ro

_SENS_DETALII = {
    "ong": "scopul inițial al organizației",
    "experti": "specializarea (ex. „contabilitate”, „construcții”)",
    "traducatori": "limbile (ex. „germană”)",
    "notari": "camera notarilor",
    "executori": "camera executorilor (curtea de apel)",
}


@mcp.tool()
def registru_cauta(
    registru: str,
    nume: str | None = None,
    judet: str | None = None,
    localitate: str | None = None,
    detalii: str | None = None,
    categorie: str | None = None,
    numar: str | None = None,
    limita: int = 30,
) -> dict:
    """Caută în registrele publice ale Ministerului Justiției (de pe data.gov.ro, copiate local).

    `registru`: „ong” (Registrul Național ONG: asociații, fundații, federații, uniuni, persoane
    juridice străine; `categorie` = asociatie / fundatie / federatie / uniune /
    persoana_juridica_straina), „experti” (experți judiciari), „traducatori”, „notari”,
    „executori”. `detalii` caută în: ONG – scop; experți – specializare; traducători – limbi;
    notari/executori – camera. `numar`: nr. în Registrul ONG (ex. „1039/A/2023”), nr. autorizație
    sau legitimație. Toate criteriile: cuvinte conținute, fără diacritice.

    Prima căutare într-un registru îl descarcă (ONG: ~1 minut, ~150.000 de înregistrări);
    apoi se reîmprospătează singur (ONG la 7 zile, restul la 30).
    """
    registru = (registru or "").strip().lower()
    out: dict = {}
    try:
        if registru in registre.REGISTRE and registre.trebuie_actualizat(registru):
            out["actualizare"] = registre.actualizeaza([registru])
        crit = dict(nume=nume, judet=judet, localitate=localitate, detalii=detalii,
                    categorie=categorie, numar=numar, limita=limita)
        rez = registre.cauta(registru, **crit)
        if rez["total"] == 0 and nume:
            rez = registre.cauta(registru, aproximativ=True, **crit)
            if rez["total"]:
                rez["potrivire_aproximativa"] = ("Nimic exact; acestea se potrivesc după rădăcina cuvintelor "
                                                 "(ex. „Crucea” ~ „Cruce”). Verifică denumirea.")
    except registre.RegistruError as e:
        return _eroare(e)
    surse = [s for s in registre.stare() if s["registru"] == registru]
    out.update(rez)
    out["sursa"] = [{"categorie": s["categorie"], "fisier": s["nume_fisier"], "data_sursa": s["data_sursa"],
                     "inregistrari": s["randuri"]} for s in surse]
    out["campul_detalii"] = _SENS_DETALII.get(registru)
    vechi = [s["data_sursa"] for s in surse if s["data_sursa"] and s["data_sursa"] < "2026-01-01"]
    if vechi:
        out["atentie"] = (f"Ministerul Justiției a publicat ultima dată acest registru pe data.gov.ro la {max(vechi)}. "
                          "Pentru confirmare, verifică pe site-ul organizației profesionale.")
    if registru == "ong":
        out["nota"] = "Registrul ONG nu are CUI; starea goală înseamnă de regulă organizație activă."
    return out


@mcp.tool()
def registru_actualizeaza(registre_de_actualizat: list[str] | None = None) -> dict:
    """Descarcă din nou registrele de pe data.gov.ro (implicit toate: ong, experti, traducatori,
    notari, executori) și înlocuiește copia locală. Durează ~1–2 minute pentru toate.
    """
    try:
        return {"rezultat": registre.actualizeaza(registre_de_actualizat)}
    except registre.RegistruError as e:
        return _eroare(e)


@mcp.tool()
def registru_stare() -> dict:
    """Ce registre sunt descărcate local, din ce dată e sursa și când s-au actualizat."""
    return {
        "registre": {k: v["descriere"] for k, v in registre.REGISTRE.items()},
        "local": registre.stare(),
        "baza_de_date": str(registre.DB_PATH),
    }


def run() -> None:
    import logging

    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()
