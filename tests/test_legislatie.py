from pathlib import Path

import pytest

from justitie_mcp import legislatie as L

HTML = (Path(__file__).parent / "fixtures" / "act_mic.html").read_text(encoding="utf-8")


def test_cheie_articol():
    assert L.cheie_articol("Articolul 25^1") == "25^1"
    assert L.cheie_articol("art. 25 ind. 1") == "25^1"
    assert L.cheie_articol("25¹") == "25^1"
    assert L.cheie_articol("Art. 291") == "291"


def test_antet_si_istoric():
    a = L.Act(900002, HTML)
    h = a.antet()
    assert h["id_forma"] == 900002
    assert h["denumire"] == "LEGE nr. 1 din 1 ianuarie 2020"
    assert h["emitent"] == "PARLAMENTUL"
    assert h["consolidare"] == "01.06.2026"
    assert a.istoric == [{"data": "01.06.2026", "id": 900002}, {"data": "01.01.2025", "id": 900001}]
    assert L.forma_la_data(a, "2025-06-30") == 900001
    assert L.forma_la_data(a, "2026-07-01") == 900002
    with pytest.raises(L.LegislatieError):
        L.forma_la_data(a, "2020-01-01")


def test_articole_si_note():
    a = L.Act(900002, HTML)
    assert list(a.articole) == ["1", "1^1", "anexanr.1"]
    art = a.articol("1")
    assert a.articole["1"]["denumire"] == "Obiectul legii"
    assert a.articole["1"]["cale"] == "Capitolul I – Dispoziții generale"
    assert "Cota este de 21%" in art["text"]
    assert "(la 01-08-2025, Alineatul (1) , Articolul 1 a fost modificat de LEGEA nr. 141 din 25 iulie 2025)" in art["text"]
    assert "..." not in art["text"] and "+" not in art["text"]
    fara = a.articol("1", note=False)["text"]
    assert "modificat" not in fara and "a) prima literă;" in fara
    assert a.articol("Anexa nr. 1")["text"].endswith("Formular")
    assert a.articol("99") is None


def test_cauta_in_act_fara_diacritice():
    a = L.Act(900002, HTML)
    r = a.cauta("microintreprinderi")
    assert [x["nr"] for x in r] == ["Articolul 1"]
    assert a.cauta("LEGEA nr. 141") == []  # notele nu intră în căutare


def test_titlu_si_fragment():
    assert L._curata_titlu("﻿   LEGE nr. 1   privind x      EMITENT:   P") == "LEGE nr. 1 privind x"
    assert "Registrul unic" in L._fragment("bla " * 100 + "Registrul unic de control" + " bla" * 100, "registrul unic")
    assert L.id_din_link("https://legislatie.just.ro/Public/DetaliiDocument/1576") == 1576
