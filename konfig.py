"""Beállítások betöltése a config.sh fájlból.

Egyetlen konfigfájl szolgálja ki a shell scriptet és a Python scripteket is:
a `klima.sh` source-olja, ezt a parser pedig kiolvassa belőle az `export`
sorokat. Nem futtat shellt — csak `KULCS="érték"` alakú sorokat fogad el,
így egy elgépelt konfigfájl nem tud kódot végrehajtani.

A környezeti változó mindig erősebb: ami már be van állítva, azt nem írja felül.
Így a `klima.sh` által exportált értékek érvényben maradnak.
"""

# A modern típusjelölések így a rendszer Pythonján (3.9) is értelmezhetők.
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent


def betoltes(fajl: Path | None = None) -> Path | None:
    """Betölti a config.sh-t, ha létezik. Visszaadja a betöltött fájl útvonalát."""
    f = fajl or PROJEKT / "config.sh"
    if not f.is_file():
        return None

    for sor in f.read_text(encoding="utf-8").splitlines():
        sor = sor.strip()
        if not sor.startswith("export "):
            # A `K=V` és a `K=V; export K` alakot a shell érti, a parser nem —
            # némán átugorva a beállítás hiányára csak később derülne fény.
            if re.match(r"^(AUX_|KLIMA_|SSH_)\w*=", sor):
                print(f"FIGYELEM: {f} — a Python csak az `export KULCS=ERTEK` alakot "
                      f"olvassa, ezt a sort kihagyom: {sor[:60]}", file=sys.stderr)
            continue
        kulcs, jel, ertek = sor[len("export "):].partition("=")
        if not jel:
            continue
        kulcs = kulcs.strip()
        # Az értéket a shell idézőjel- és megjegyzésszabályai szerint bontjuk,
        # így a `export K="v"   # megjegyzés` alak is ugyanazt adja, mint a
        # source. (Korábban ilyenkor bent maradtak az idézőjelek.)
        try:
            darabok = shlex.split(ertek, comments=True)
        except ValueError:
            darabok = [ertek.strip()]
        ertek = darabok[0] if darabok else ""
        if kulcs and kulcs not in os.environ:
            os.environ[kulcs] = ertek
    return f


def kell(kulcs: str, mire: str) -> str:
    """Kötelező beállítás kiolvasása, beszédes hibával, ha hiányzik."""
    ertek = os.environ.get(kulcs, "").strip()
    if not ertek:
        raise SystemExit(
            f"Hiányzik a(z) {kulcs} beállítás ({mire}).\n"
            f"Másold a config.example.sh-t config.sh néven, és töltsd ki:\n"
            f"  cp {PROJEKT}/config.example.sh {PROJEKT}/config.sh"
        )
    return ertek
