#!/usr/bin/env python3
"""AUX klíma LEKÉRDEZÉSE az AC Freedom felhőn át — kizárólag olvasás.

A script szándékosan képtelen parancsot küldeni a klímának: induláskor letiltja
a kliens összes író útját (lásd: kozos.irasi_zar). Első futtatásra ezzel érdemes
megnézni, mit lát a felhő: a készülék nevét, termékazonosítóját, MAC-címét és
az állapotát.
"""

import argparse
import asyncio
import json
import sys

try:
    import aiohttp

    from auxcloud.api import AuxApiError
    from auxcloud.dna import DnaClient
except ImportError as e:  # lásd a klima.py azonos védelmét
    print(f"HIBA: hiányzik egy Python-csomag ({e.name}). Futtasd a projekt mappájában:\n"
          f"  uv pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(65) from None

import kozos
from kozos import naplo


def keret(cim: str) -> None:
    print()
    print("=" * 66)
    print(f" {cim}")
    print("=" * 66)


KIEMELT = [
    ("pwr", "Bekapcsolva"),
    ("ac_mode", "Üzemmód"),
    ("temp", "Beállított hőfok"),
    ("envtemp", "Szobahőmérséklet"),
    ("ac_mark", "Ventilátor"),
    ("ac_vdir", "Függőleges légterelés"),
    ("ac_hdir", "Vízszintes légterelés"),
    ("ecomode", "Eco"),
    ("ac_slp", "Alvás mód"),
    ("scrdisp", "Kijelző"),
    ("ac_health", "Health (ionizáló)"),
    ("mldprf", "Penészgátló"),
    ("childlock", "Gyerekzár"),
    ("err_flag", "Hibajelző"),
    ("ac_errcode1", "Hibakód"),
]


def ertek_szoveg(kulcs: str, v) -> str:
    if kulcs in ("temp", "envtemp"):
        return kozos.fok(v)
    if kulcs == "ac_mode":
        return f"{v}  →  {kozos.MODOK.get(v, 'ismeretlen')}"
    if kulcs == "ac_mark":
        return f"{v}  →  {kozos.VENTILATOR.get(v, 'ismeretlen')}"
    if kulcs == "pwr":
        return "IGEN" if v == 1 else "nem"
    return str(v)


def eszkoz_kiirasa(e: dict, mind: bool) -> None:
    profil = kozos.get_device_profile(e)
    keret(f"„{e.get('friendlyName', '?')}”  —  {profil.model_name}")
    print(f"  Termékazonosító : {e.get('productId', '?')}"
          f"{'  (ISMERETLEN a kliens számára — lásd README)' if kozos.ismeretlen_volt(e) else ''}")
    print(f"  MAC-cím         : {kozos.mac_szep(e.get('mac'))}")
    _, mac_szoveg = kozos.mac_ellenorzes(e)
    print(f"  MAC-ellenőrzés  : {mac_szoveg}")
    print(f"  Kapcsolat       : {'online' if e.get('state') == 1 else 'OFFLINE'}")

    params = e.get("params") or {}
    keret("Állapot")
    print(f"  {kozos.allapot_sor(e)}\n")
    # A KIEMELT lista és a hozzá tartozó szöveges feloldás klímára szól; a
    # hőszivattyú paraméterei mást jelentenek, ott csak a nyers értékek mennek.
    klima = profil.device_type is not kozos.DeviceType.HEAT_PUMP
    if klima:
        for kulcs, cimke in KIEMELT:
            if kulcs in params:
                print(f"  {cimke:<24}: {ertek_szoveg(kulcs, params[kulcs])}")

    if (mind or not klima) and params:
        keret("Összes paraméter")
        for k in sorted(params):
            print(f"  {k:<24}: {params[k]}")

    if e.get("_aux_query_failures"):
        print("\n  Sikertelen részlekérdezések:", e["_aux_query_failures"])


async def main() -> int:
    p = argparse.ArgumentParser(description="AUX klíma lekérdezése (csak olvasás)")
    p.add_argument("--email", help="AC Freedom fiók e-mail címe")
    p.add_argument("--regio", help="felhőrégió: eu, usa, cn, rus (alap: config.sh vagy eu)")
    p.add_argument("--mind", action="store_true", help="az összes állapotparaméter kiírása")
    p.add_argument("--json", action="store_true", help="nyers JSON (a titkos mezők kitakarva)")
    p.add_argument("--szabvanyos-profil", action="store_true",
                   help="ismeretlen termékazonosítónál a szabványos klímaprofillal kérdez le")
    args = p.parse_args()

    kozos.irasi_zar()
    naplo("Biztonsági zár aktív: parancsküldés letiltva, csak olvasás.")

    email = kozos.email_cim(args.email)
    reg = kozos.regio(args.regio)
    hitel = kozos.belepesi_adatok(email)

    async with aiohttp.ClientSession() as munkamenet:
        kliens = DnaClient(region=reg, session=munkamenet)
        try:
            leltar = await kozos.kapcsolodas(kliens, hitel, reg)
            if args.szabvanyos_profil:
                for e in leltar.devices:
                    if not kozos.ismert_profil(e):
                        try:
                            await kozos.szabvanyos_profil_ravetele(kliens, e)
                        except AuxApiError as hiba:
                            # Egy készülék hibája ne vigye el az egész listát.
                            naplo(f"  „{e.get('friendlyName', '?')}” lekérdezése nem sikerült: "
                                  f"{type(hiba).__name__}: {hiba}")
        except AuxApiError as e:
            naplo(f"\nHIBA: {type(e).__name__}: {e}")
            return 1
        finally:
            await kliens.close()

    if not leltar.devices:
        naplo("\nA fiókhoz nem tartozik készülék.")
        return 1
    if not leltar.complete:
        naplo("  FIGYELEM: nem minden felhőlekérdezés sikerült, a lista hiányos lehet.")

    if args.json:
        print(json.dumps([kozos.kitakart(e) for e in leltar.devices],
                         ensure_ascii=False, indent=2, default=str))
    else:
        print(f"\n{len(leltar.devices)} készülék a fiókban.")
        for e in leltar.devices:
            eszkoz_kiirasa(e, args.mind)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
