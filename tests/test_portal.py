from pathlib import Path

import pytest

from justitie_mcp import analiza, portal

FIX = Path(__file__).parent / "fixtures" / "cautare_dosare2.xml"


def test_fara_diacritice_ambele_forme():
    assert portal.fara_diacritice("TIMIŞOARA ȚARA") == "TIMISOARA TARA"
    assert portal.normalizeaza_nume("S.C. Alfa-Construct  S.R.L.") == "S C ALFA CONSTRUCT S R L"


def test_rezolva_institutie():
    assert portal.rezolva_institutie("Tribunalul Timiș") == "TribunalulTIMIS"
    assert portal.rezolva_institutie("TribunalulTIMIS") == "TribunalulTIMIS"
    assert portal.rezolva_institutie("judecatoria sectorul 4 bucuresti") == "JudecatoriaSECTORUL4BUCURESTI"
    assert portal.rezolva_institutie(None) is None
    with pytest.raises(portal.PortalError):
        portal.rezolva_institutie("Tribunalul Atlantida")
    with pytest.raises(portal.PortalError, match="mai multe"):
        portal.rezolva_institutie("bucuresti")


def test_envelope_nil_si_escape():
    body = portal._element("numeParte", "A & B", False) + portal._element("institutie", None, True)
    assert "A &amp; B" in body and 'institutie xsi:nil="true"' in body
    assert portal._dt("05.03.2026") == "2026-03-05T00:00:00"
    assert portal._dt("2026-03-05", sfarsit_zi=True) == "2026-03-05T23:59:59"


def test_parse_dosare_fixture():
    dosare = portal.parse_dosare(FIX.read_bytes())
    assert len(dosare) == 3
    d = dosare[0]
    assert d["numar"] and d["institutie_cod"] and d["parti"]
    assert all(set(p) == {"nume", "calitate"} for p in d["parti"])
    datele = [s["data"] for s in d["sedinte"] if s["data"]]
    assert datele == sorted(datele, reverse=True)


def test_raport_litigii_fixture():
    dosare = portal.parse_dosare(FIX.read_bytes())
    r = analiza.raport_litigii(dosare, "rompetrol rafinare")
    assert r["dosare_retinute"] >= 1
    assert any("ROMPETROL" in v["nume"] for v in r["variante_nume"])
    exclus = analiza.raport_litigii(dosare, "rompetrol rafinare", exclude_nume=["rompetrol"])
    assert exclus["dosare_retinute"] == 0
    rz = analiza.rezumat(dosare[0], "rompetrol rafinare")
    assert len(rz["parti"]) <= analiza.MAX_PARTI_REZUMAT
    assert any("ROMPETROL" in p["nume"] for p in rz["parti"])


def test_csv(tmp_path):
    dosare = portal.parse_dosare(FIX.read_bytes())
    out = analiza.scrie_csv(dosare, str(tmp_path / "x.csv"), "rompetrol")
    text = Path(out).read_text(encoding="utf-8-sig")
    assert text.count("\n") == 4


def test_cerere_fara_criterii():
    with pytest.raises(portal.PortalError):
        portal.cauta_dosare()
