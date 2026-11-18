"""Linia de comandă: fără argumente pornește serverul MCP; `test` și `litigii` pentru verificare."""

from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="justitie-mcp", description="Server MCP pentru portal.just.ro")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="pornește serverul MCP (implicit)")
    sub.add_parser("test", help="verifică legătura cu portalul instanțelor")
    lit = sub.add_parser("litigii", help="raport de litigii pentru un nume")
    lit.add_argument("nume")
    lit.add_argument("--csv", help="salvează toate dosarele într-un fișier CSV")
    d = sub.add_parser("dosar", help="detaliile unui dosar")
    d.add_argument("numar")
    args = p.parse_args(argv)

    if args.cmd in (None, "serve"):
        from .server import run

        run()
        return

    from . import analiza, portal

    try:
        if args.cmd == "test":
            dosare = portal.cauta_dosare(numar_dosar="1/2/2020")
            print(f"OK: portalul răspunde ({portal.URL}), {len(dosare)} dosare cu numărul de test 1/2/2020.")
        elif args.cmd == "litigii":
            dosare = portal.cauta_dosare(nume_parte=args.nume)
            r = analiza.raport_litigii(dosare, args.nume)
            toate = r.pop("toate")
            print(f"{r['dosare_retinute']} dosare pentru „{args.nume}”.")
            if r["avertisment"]:
                print("ATENȚIE:", r["avertisment"])
            print("Variante de nume:")
            for v in r["variante_nume"][:20]:
                print(f"  {v['dosare']:4d}  {v['nume']}")
            print("Pe calitate:", json.dumps(r["pe_calitate"], ensure_ascii=False))
            print("Pe categorie:", json.dumps(r["pe_categorie"], ensure_ascii=False))
            print(f"Insolvență ca debitor: {len(r['insolventa_ca_debitor'])}; cu termen viitor: {len(r['cu_termen_viitor'])}")
            if args.csv:
                print("CSV:", analiza.scrie_csv(toate, args.csv, args.nume))
        elif args.cmd == "dosar":
            for x in portal.cauta_dosare(numar_dosar=args.numar):
                print(json.dumps(analiza.rezumat(x), ensure_ascii=False, indent=2))
    except portal.PortalError as e:
        print("Eroare:", e, file=sys.stderr)
        sys.exit(1)
