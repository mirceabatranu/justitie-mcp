import io

import openpyxl
import pytest

from justitie_mcp import registre as R


def _xlsx(rows: list[list], titlu: str | None = None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    if titlu:
        ws.append([titlu])
        ws.append([])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


ONG = _xlsx([
    ["Denumire", "Numar inreg Reg National", "Starea actuala", "Judet", "Localitate", "Adresa", "Scopul initial"],
    ["_x000D_\nASOCIATIA CRUCE ROŞIE CLUJ_x000D_", "1/A/2020", "", "CLUJ", "CLUJ-NAPOCA", "Str. X", "ajutor umanitar"],
    ["ASOCIAŢIA ALFA", "2/A/2021", "in lichidare", "BUCURESTI", "Bucureşti", "Bd. Y", "sport"],
])

TRAD = _xlsx([
    ["Nume", "Nr Autorizatie", "Curte de Apel", "Judet", "Limbi", "telefon"],
    ["Ionescu Ana", "123", "CLUJ", "CLUJ", "Engleză, Japoneză", "0700"],
    ["Pop Dan", "456", "IAŞI", "IASI", "Germană", ""],
], titlu="Lista traducatorilor")


def test_citeste_xlsx_curata_si_mapeaza():
    rows = R.citeste_xlsx(ONG)
    assert rows[0]["nume"] == "ASOCIATIA CRUCE ROŞIE CLUJ"
    assert rows[0]["numar"] == "1/A/2020" and rows[0]["detalii"] == "ajutor umanitar"
    assert rows[1]["stare"] == "in lichidare"


def test_traducatori_limbi_inaintea_curtii_de_apel():
    rows = R.citeste_xlsx(TRAD)  # antetul nu e pe primul rând
    assert rows[0]["detalii"] == "Engleză, Japoneză"
    assert rows[0]["extra"] == {"Curte de Apel": "CLUJ", "telefon": "0700"}


def test_incarca_si_cauta(tmp_path):
    db = tmp_path / "r.sqlite"
    con = R.conectare(db)
    R.incarca(con, "ong", "asociatie", R.citeste_xlsx(ONG), {"nume": "Asociatii 06.07.2026", "data": "2026-07-06"})
    R.incarca(con, "traducatori", None, R.citeste_xlsx(TRAD), {"nume": "Traducatori", "data": "2025-01-23"})
    con.close()
    assert R.cauta("ong", nume="cruce rosie", path=db)["total"] == 1
    assert R.cauta("ong", nume="crucea rosie", path=db)["total"] == 0
    assert R.cauta("ong", nume="crucea rosie", path=db, aproximativ=True)["total"] == 1
    assert R.cauta("ong", localitate="cluj napoca", path=db)["total"] == 1
    assert R.cauta("ong", numar="2/A/2021", path=db)["rezultate"][0]["stare"] == "in lichidare"
    assert R.cauta("traducatori", detalii="japoneza", path=db)["rezultate"][0]["nume"] == "Ionescu Ana"
    # reîncărcarea înlocuiește, nu dublează
    con = R.conectare(db)
    R.incarca(con, "ong", "asociatie", R.citeste_xlsx(ONG), {"nume": "x", "data": "2026-07-13"})
    con.close()
    assert R.cauta("ong", judet="cluj", path=db)["total"] == 1
    assert {s["data_sursa"] for s in R.stare(db) if s["registru"] == "ong"} == {"2026-07-13"}


def test_resurse_curente_alege_cea_mai_noua():
    pachete = [
        {"name": "registrul-national-ong-2025", "resources": [
            {"name": "Asociatii 10.03.2025", "url": "https://x/a1.xlsx"}]},
        {"name": "registrul-national-ong-2026", "resources": [
            {"name": "Asociatii 06.07.2026", "url": "https://x/a2.xlsx"},
            {"name": "Fundatii 16.06.2026", "url": "https://x/f1.xlsx"},
            {"name": "Lista Dovezi Disponibilitate 06.07.2026", "url": "https://x/l.xlsx"}]},
        {"name": "situatie-plati", "resources": [{"name": "Asociatii 01.01.2027", "url": "https://x/z.xlsx"}]},
    ]
    alese = {r["categorie"]: r for r in R.resurse_curente("ong", pachete)}
    assert alese["asociatie"]["url"].endswith("a2.xlsx") and alese["asociatie"]["data"] == "2026-07-06"
    assert alese["fundatie"]["url"].endswith("f1.xlsx")
    assert "federatie" not in alese


def test_erori():
    with pytest.raises(R.RegistruError):
        R.cauta("avocati", nume="x")
    with pytest.raises(R.RegistruError):
        R.cauta("ong")
