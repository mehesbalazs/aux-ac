#!/usr/bin/env python3
"""iOS/macOS Parancsok (Shortcuts) fájlok generálása a klíma vezérléséhez.

A kész .shortcut fájlt a `shortcuts sign` írja alá, az `open` importálja a
Parancsok appba, onnan pedig iCloudon át átszinkronizál az iPhone-ra.

Minden parancs ugyanazt csinálja: SSH-n meghívja a klima.sh-t a Macen, és
megmutatja az egysoros választ. Megerősítést egyik sem kér — a klíma be- és
kikapcsolása visszafordítható, és a lassú megerősítés a telefonon csak útban
lenne. A klima.sh maga őrzi a határokat (MAC-ellenőrzés, értékellenőrzés).

Az SSH-paraméterkulcsok a rendszerből származnak:
/System/Library/PrivateFrameworks/WorkflowKit.framework/.../Localizable.loctable
"""

import os
import plistlib
import subprocess
import sys
import uuid

import konfig

konfig.betoltes()

MAPPA = konfig.PROJEKT
HOST = konfig.kell("SSH_HOST", "a Mac címe, amire a telefon csatlakozik")
PORT = os.environ.get("SSH_PORT", "22")
USER = konfig.kell("SSH_USER", "a Mac felhasználóneve az SSH-hoz")

# U+FFFC — ide illeszti be a Parancsok az előző művelet kimenetét.
HELYORZO = "￼"

# A Parancsok ikonszínei. A glif száma mindenhol ugyanaz (a Parancsok appban
# egy koppintással átállítható, ha más képet szeretnél).
SZURKE, LILA, KEK, ZOLD, PIROS = 2071128575, 4274264319, 4282601983, 4258869503, 4251333119
GLIF = 59511

PARANCSOK = [
    {"nev": "Klíma - Kikapcsolás", "args": "ki", "szin": SZURKE},
    {"nev": "Klíma - Állapot", "args": "allapot", "szin": LILA},
    {"nev": "Klíma - Hűtés 26 Csendes", "args": "be 26 hutes csendes", "szin": KEK},
    {"nev": "Klíma - Hűtés 16 Magas", "args": "be 16 hutes magas", "szin": KEK},
    {"nev": "Klíma - Szárítás 16 Alacsony", "args": "be 16 szaritas alacsony", "szin": ZOLD},
    {"nev": "Klíma - Fűtés 26 Csendes", "args": "be 26 futes csendes", "szin": PIROS},
]


def valtozo_hivatkozas(uuid_str: str, nev: str = "Shell Script Result") -> dict:
    """Az előző művelet kimenetére mutató 'magic variable'."""
    return {
        "Value": {
            "attachmentsByRange": {
                "{0, 1}": {
                    "Type": "ActionOutput",
                    "OutputUUID": uuid_str,
                    "OutputName": nev,
                }
            },
            "string": HELYORZO,
        },
        "WFSerializationType": "WFTextTokenString",
    }


def parancs(p: dict) -> dict:
    ssh_uuid = str(uuid.uuid4()).upper()
    szkript = f"{MAPPA}/klima.sh {p['args']}"

    muveletek = [
        # 1. A burkoló futtatása a Macen SSH-n át.
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.runsshscript",
            "WFWorkflowActionParameters": {
                "UUID": ssh_uuid,
                "WFSSHHost": HOST,
                "WFSSHPort": PORT,
                "WFSSHUser": USER,
                "WFSSHAuthenticationType": "SSH Key",
                "WFSSHScript": szkript,
            },
        },
        # 2. A burkoló egysoros válaszának megmutatása.
        {
            "WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
            "WFWorkflowActionParameters": {
                "Text": valtozo_hivatkozas(ssh_uuid),
            },
        },
    ]

    return {
        "WFWorkflowClientVersion": "2605.0.5",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": p["szin"],
            "WFWorkflowIconGlyphNumber": GLIF,
        },
        "WFWorkflowImportQuestions": [],
        "WFWorkflowTypes": ["NCWidget", "WatchKit"],
        "WFWorkflowInputContentItemClasses": [
            "WFAppStoreAppContentItem", "WFArticleContentItem",
            "WFContactContentItem", "WFDateContentItem",
            "WFEmailAddressContentItem", "WFGenericFileContentItem",
            "WFImageContentItem", "WFiTunesProductContentItem",
            "WFLocationContentItem", "WFDCMapsLinkContentItem",
            "WFAVAssetContentItem", "WFPDFContentItem",
            "WFPhoneNumberContentItem", "WFRichTextContentItem",
            "WFSafariWebPageContentItem", "WFStringContentItem",
            "WFURLContentItem",
        ],
        "WFWorkflowActions": muveletek,
    }


def main() -> int:
    kimenet = MAPPA / "parancsok"
    kimenet.mkdir(exist_ok=True)

    for p in PARANCSOK:
        nyers = kimenet / f"{p['nev']}-alairatlan.shortcut"
        kesz = kimenet / f"{p['nev']}.shortcut"

        nyers.write_bytes(plistlib.dumps(parancs(p), fmt=plistlib.FMT_BINARY))

        r = subprocess.run(
            ["shortcuts", "sign", "-m", "anyone", "-i", str(nyers), "-o", str(kesz)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"HIBA az aláírásnál ({p['nev']}): {r.stderr.strip()}", file=sys.stderr)
            return 1
        nyers.unlink()
        print(f"  kész: {kesz.name}  ({kesz.stat().st_size} bájt)  →  klima.sh {p['args']}")

    print(f"\nA fájlok itt vannak: {kimenet}")
    print("Importálás: open '<fájl>'  — a Parancsok appban rá kell bökni a Hozzáadásra.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
