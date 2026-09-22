#!/usr/bin/env python3
"""AUX klíma VEZÉRLÉSE az AC Freedom felhőn át.

  klima.py allapot                     # csak olvasás
  klima.py be [HŐFOK] [--mod M] [--vent V]
  klima.py ki
  klima.py hofok 23.5                  # csak a hőfok, be/ki állapotot nem vált
  klima.py mod hutes|futes|szaritas|ventilator|auto
  klima.py vent auto|alacsony|kozepes|magas|turbo|csendes

  --proba              kiírja, mit küldene, de nem küld semmit (írási zár)
  --nincs-ellenorzes   küldés után nem olvas vissza (a 0 ilyenkor nem jelent
                       visszaigazolt átállást)
  --szabvanyos-profil  ismeretlen termékazonosítónál a szabványos AUX profil
  --email, --regio     a config.sh megfelelő értékének felülírása

Az értékeket még a bejelentkezés előtt ellenőrzi, hogy egy elgépelés ne
kerüljön felhőforgalomba. Utána a parancs csak akkor megy ki, ha a klíma
online, a MAC-címe egyezik a config.sh-ban beállítottal, és a felhő
értelmezhető állapotot adott róla. Ha a kért állapot már most is így van, nem
küld semmit. Küldés után visszaigazolást vár: vagy a felhő válaszában, vagy
visszaolvasással.

Kilépési kódok (a klima.sh ezekből ír emberi mondatot):
   0  rendben
   1  bejelentkezési/konfigurációs hiba, vagy nincs meg a készülék
   2  a klíma offline
   3  a felhő nem érhető el vagy hiányosan válaszolt — semmi nem ment el
   4  a felhő elutasította a parancsot (a klíma nem állt át)
   5  elküldve, de a visszaolvasott állapot más
   6  nem a várt készülék válaszolt (MAC-eltérés)
   7  BIZONYTALAN — nem derült ki, átment-e; ellenőrizd, mielőtt újrapróbálod
   8  kéréskorlát — túl sűrű kérések, várj egy kicsit
   9  időtúllépés a felhővel
  64  hibás használat (ismeretlen parancs, érvénytelen érték)
  65  hiányzó Python-csomag (uv pip install -r requirements.txt)
  70  váratlan hiba (a részletek a stderr-en és a klima.log-ban)
"""

import argparse
import asyncio
import sys
import traceback
import unicodedata

# A kiemelt kliens a pycryptodome-ot is húzza (dna/http.py), ezért az egész
# importblokk védett: bármelyik hiányzó csomag ugyanazt a beszédes 65-öt adja,
# nem egy nyers ImportError-t, amit a burkoló „bejelentkezési hibának" fordít.
try:
    import aiohttp

    from auxcloud.api import (
        AuxApiError,
        AuxAuthError,
        AuxDeviceError,
        AuxNetworkError,
        AuxRateLimitError,
        AuxServerError,
        AuxSessionExpired,
    )
    from auxcloud.devices import (
        encode_ac_temperature_command,
        get_device_profile,
        normalize_device_params,
    )
    from auxcloud.dna import DnaClient
except ImportError as e:  # a venv megvan, de a csomagok nincsenek telepítve
    print(f"HIBA: hiányzik egy Python-csomag ({e.name}). Futtasd a projekt mappájában:\n"
          f"  uv pip install -r requirements.txt", file=sys.stderr)
    raise SystemExit(65) from None

import kozos
from kozos import naplo

MOD_NEVEK = {"hutes": 0, "futes": 1, "szaritas": 2, "ventilator": 3, "auto": 4}
VENT_NEVEK = {"auto": 0, "alacsony": 1, "kozepes": 2, "magas": 3, "turbo": 4, "csendes": 5}

# A távirányító tartománya. A felhő ennél szélesebbet is elfogadhat, de a
# telefonos elgépelést (pl. 230) jobb itt megfogni.
HOFOK_MIN, HOFOK_MAX = 16.0, 32.0

# Visszaolvasás: ennyi másodpercet vár az egyes próbák előtt. A felhő és a
# klíma között néhány másodperc, mire az új érték látszik (ha-aux-cloud #82).
VISSZAOLVASAS_VARAKOZAS = (3, 4, 6)

# A teljes futás felső korlátja. A felhő egy-egy kérése 15 s-ot is várhat, és
# a telefon (Parancsok, Siri) előbb feladná — jobb, ha mi adjuk fel előbb, és
# értelmes üzenetet adunk.
TELJES_HATARIDO = 60


class HasznalatiHiba(Exception):
    """Érvénytelen parancs vagy érték — 64-es kilépési kód."""


class Ertelmezo(argparse.ArgumentParser):
    """Az argparse alapból 2-vel lép ki, az viszont nálunk az offline kódja."""

    def error(self, message):
        naplo(f"HIBA: hibás parancs: {message}")
        raise SystemExit(64)


def ekezet_nelkul(s: str) -> str:
    """„Hűtés” → „hutes”, így a telefonon ékezettel és anélkül is megy."""
    return "".join(c for c in unicodedata.normalize("NFD", s.strip().lower())
                   if unicodedata.category(c) != "Mn")


def mod_ertek(nev: str) -> int:
    kulcs = ekezet_nelkul(nev)
    if kulcs not in MOD_NEVEK:
        raise HasznalatiHiba(f"Ismeretlen üzemmód: '{nev}'. Használható: {', '.join(MOD_NEVEK)}")
    return MOD_NEVEK[kulcs]


def vent_ertek(nev: str) -> int:
    kulcs = ekezet_nelkul(nev)
    if kulcs not in VENT_NEVEK:
        raise HasznalatiHiba(f"Ismeretlen ventilátorfokozat: '{nev}'. Használható: {', '.join(VENT_NEVEK)}")
    return VENT_NEVEK[kulcs]


def hofok_ertek(szoveg: str) -> float:
    try:
        t = float(szoveg.replace(",", "."))
    except ValueError:
        raise HasznalatiHiba(f"A hőfok szám legyen, nem '{szoveg}'.") from None
    if not HOFOK_MIN <= t <= HOFOK_MAX:
        raise HasznalatiHiba(f"A hőfok {HOFOK_MIN:g} és {HOFOK_MAX:g} °C között legyen, nem {t:g}.")
    if (t * 2) != int(t * 2):
        raise HasznalatiHiba(f"A hőfok egész vagy fél fok legyen, nem {t:g}.")
    return t


def kivansag(args) -> dict:
    """A parancssor értelmezése — még bejelentkezés és felhőforgalom ELŐTT.

    Így az elgépelés nem kerül egy teljes belépésbe és leltárba, és nem
    „offline” vagy „nem érem el a felhőt” üzenetként jön vissza.
    """
    k: dict = {}
    if args.parancs == "be":
        k["pwr"] = 1
    elif args.parancs == "ki":
        return {"pwr": 0}

    hofok = args.ertek if args.parancs in ("be", "hofok") else None
    if args.parancs == "hofok" and hofok is None:
        raise HasznalatiHiba("Add meg a hőfokot, pl.: klima.py hofok 23")
    if hofok is not None:
        k["hofok"] = hofok_ertek(hofok)

    mod = args.ertek if args.parancs == "mod" else args.mod
    if args.parancs == "mod" and mod is None:
        raise HasznalatiHiba("Add meg az üzemmódot, pl.: klima.py mod hutes")
    if mod is not None:
        k["ac_mode"] = mod_ertek(mod)

    vent = args.ertek if args.parancs == "vent" else args.vent
    if args.parancs == "vent" and vent is None:
        raise HasznalatiHiba("Add meg a fokozatot, pl.: klima.py vent auto")
    if vent is not None:
        k["ac_mark"] = vent_ertek(vent)

    if not k:
        raise HasznalatiHiba("Nincs mit küldeni.")
    return k


def kert_ertekek(kiv: dict, eszkoz: dict) -> dict:
    """A kívánságból a klíma saját formátuma (tizedfok, fél fok, °F)."""
    ertekek = {k: v for k, v in kiv.items() if k != "hofok"}
    if "hofok" in kiv:
        ertekek.update(encode_ac_temperature_command(eszkoz, kiv["hofok"]))

    # A termékprofil is ellenőrzi (pl. van-e az adott klímán auto mód vagy turbó).
    if hibas := get_device_profile(eszkoz).invalid_command_parameter(ertekek):
        raise HasznalatiHiba(f"Ez a klíma nem fogadja el ezt a beállítást: {hibas}={ertekek.get(hibas)}")
    return ertekek


def logikai_ertekek(eszkoz: dict, ertekek: dict) -> dict:
    """A küldendő nyers értékek ugyanabban az alakban, ahogy az állapot látszik.

    A fél fokot jelzőbittel tároló (és a °F-es) klímáknál a nyers `temp` nem
    hasonlítható közvetlenül az állapothoz: ott 23,5 °C = {temp:230,
    ac_tempdec:1}, az állapotban viszont már temp=235 szerepel.
    """
    masolat = {"productId": eszkoz.get("productId"),
               "profile": get_device_profile(eszkoz),
               "params": {**(eszkoz.get("params") or {}), **ertekek}}
    normalize_device_params(masolat)
    return {k: masolat["params"].get(k) for k in ertekek}


def egyezik(kert: dict, kapott: dict) -> bool:
    return all(kapott.get(k) == v for k, v in kert.items())


def eltesek(kert: dict, kapott: dict) -> str:
    return ", ".join(f"{k}: kért {v}, kapott {kapott.get(k, '—')}"
                     for k, v in kert.items() if kapott.get(k) != v)


async def visszaolvasas(kliens: DnaClient, eszkoz: dict, ertekek: dict) -> tuple[bool, dict, bool]:
    """(egyezik?, utolsó állapot, sikerült-e egyáltalán olvasni)"""
    kapott: dict = {}
    volt_olvasas = False
    for var in VISSZAOLVASAS_VARAKOZAS:
        await asyncio.sleep(var)
        try:
            # A teljes állapotot kérjük, ahogy az eredeti integráció is: az
            # egyparaméteres lekérdezésnek külön formátuma van a kliensben.
            kapott = await kliens.get_device_params(eszkoz)
            volt_olvasas = True
        except AuxApiError as e:
            naplo(f"  visszaolvasás sikertelen: {type(e).__name__}: {e}")
            continue
        if egyezik(ertekek, kapott):
            naplo(f"  visszaolvasva, egyezik ({var} s várakozás után)")
            return True, kapott, True
    return False, kapott, volt_olvasas


async def kuldes_es_ellenorzes(kliens: DnaClient, eszkoz: dict, ertekek: dict,
                               ellenoriz: bool) -> tuple[int, dict]:
    """Elküldi a parancsot, és visszaadja a kilépési kódot meg az új állapotot."""
    bizonytalan = None
    try:
        valasz = await kliens.set_device_params(eszkoz, ertekek)
    except AuxRateLimitError as e:
        naplo(f"HIBA: kéréskorlát: {e}")
        return 8, {}
    except AuxDeviceError as e:
        # Ezt maga a készülék utasította el — biztosan nem állt át.
        naplo(f"HIBA: a klíma elutasította a parancsot: {type(e).__name__}: {e}")
        return 4, {}
    except (AuxSessionExpired, AuxAuthError) as e:
        naplo(f"HIBA: bejelentkezés: {e}")
        return 1, {}
    except (AuxNetworkError, AuxServerError, AuxApiError) as e:
        # A kérés már elindult a felhő felé: ettől még átmehetett. Nem
        # mondjuk azt, hogy elutasították — visszaolvasással döntjük el.
        naplo(f"FIGYELEM: bizonytalan hiba küldés közben: {type(e).__name__}: {e}")
        bizonytalan = e
    except Exception as e:  # a kliens váratlan hibája is bizonytalan kimenet
        naplo(f"FIGYELEM: váratlan hiba küldés közben: {type(e).__name__}: {e}")
        bizonytalan = e

    if bizonytalan is None:
        # Ha a felhő üres választ ad, a kliens a küldött értékeket adja vissza
        # ugyanabban az objektumban — az nem visszaigazolás.
        if valasz is not ertekek and egyezik(ertekek, valasz):
            naplo("  a klíma a válaszban visszaigazolta")
            return 0, dict(valasz)
        if not ellenoriz:
            naplo("  elküldve, visszaigazolás nélkül (--nincs-ellenorzes)")
            return 0, {}
    elif not ellenoriz:
        naplo("FIGYELEM: hiba után nincs visszaolvasás (--nincs-ellenorzes).")
        return 7, {}

    rendben, kapott, volt_olvasas = await visszaolvasas(kliens, eszkoz, ertekek)
    if rendben:
        return 0, kapott
    if not volt_olvasas:
        naplo("FIGYELEM: a visszaolvasás sem sikerült — nem tudni, átment-e.")
        return 7, {}
    if bizonytalan is not None:
        naplo("FIGYELEM: a küldés hibára futott, és a klíma állapota nem változott: "
              f"{eltesek(ertekek, kapott)}")
        return 7, kapott
    naplo(f"FIGYELEM: a visszaolvasott állapot eltér: {eltesek(ertekek, kapott)}")
    return 5, kapott


def allapot_frissitese(eszkoz: dict, ertekek: dict, kapott: dict) -> None:
    """Az eszközrekord állapotát hozzáigazítja a küldés eredményéhez."""
    params = eszkoz.setdefault("params", {})
    params.update(kapott or ertekek)
    normalize_device_params(eszkoz)


async def futtatas(args, kliens: DnaClient, hitel, reg: str, kiv: dict) -> int:
    leltar = await kozos.kapcsolodas(kliens, hitel, reg)
    if not leltar.complete:
        naplo("  FIGYELEM: a felhő listája hiányos (nem minden lekérdezés sikerült)")

    try:
        eszkoz = kozos.klima_kivalasztasa(leltar.devices)
    except LookupError as e:
        if not leltar.complete:
            naplo(f"HIBA: a felhő listája hiányos, ezért nem találom a klímát: {e}")
            return 3
        naplo(f"HIBA: {e}")
        return 1

    nev = eszkoz.get("friendlyName", "klíma")
    egyezes, mac_szoveg = kozos.mac_ellenorzes(eszkoz)
    naplo(f"  készülék: „{nev}”, MAC-ellenőrzés: {mac_szoveg}")
    if egyezes is False:
        return 6
    if not leltar.complete and not kozos.rogzitett_valasztas():
        # Hiányos listából a „csak egy klíma van” következtetés hibás lehet:
        # könnyen a szomszéd szobáét kapcsolnánk.
        naplo("HIBA: hiányos a lista, és a config.sh nem jelöli ki a klímát "
              "(KLIMA_NEV vagy KLIMA_MAC). Biztonságból nem csinálok semmit.")
        return 3

    if not kozos.ismert_profil(eszkoz):
        if not args.szabvanyos_profil:
            naplo(f"HIBA: a termékazonosító ({eszkoz.get('productId')}) ismeretlen a kliens "
                  "számára. Lásd a README-t, majd próbáld a --szabvanyos-profil kapcsolóval.")
            return 1
        naplo("  FIGYELEM: ismeretlen termék, a szabványos AUX klímaprofillal megyek tovább")
        await kozos.szabvanyos_profil_ravetele(kliens, eszkoz)

    if eszkoz.get("state") != 1:
        print(kozos.allapot_sor(eszkoz))
        return 2

    if not await kozos.allapot_biztositasa(kliens, eszkoz):
        # Állapot nélkül a hőfok kódolása (°C/°F) is félremehetne.
        naplo("HIBA: a klíma online, de a felhő nem adott róla állapotot.")
        print(kozos.allapot_sor(eszkoz))
        return 3

    if args.parancs == "allapot":
        print(kozos.allapot_sor(eszkoz))
        return 0

    ertekek = kert_ertekek(kiv, eszkoz)
    jelenlegi = eszkoz.setdefault("params", {})
    if egyezik(logikai_ertekek(eszkoz, ertekek), jelenlegi):
        print(f"Már így van: {kozos.allapot_sor(eszkoz)}")
        return 0

    if args.proba:
        naplo(f"  PRÓBA — ezt küldeném: {ertekek}")
        allapot_frissitese(eszkoz, ertekek, {})
        print(f"Próbamenet, semmi nem ment el. Utána így lenne: {kozos.allapot_sor(eszkoz)}")
        return 0

    naplo(f"  küldés: {ertekek}")
    args._kuldes_indult = True
    kod, kapott = await kuldes_es_ellenorzes(kliens, eszkoz, ertekek, not args.nincs_ellenorzes)
    if kod == 0:
        allapot_frissitese(eszkoz, ertekek, kapott)
        print(kozos.allapot_sor(eszkoz))
    return kod


async def main() -> int:
    p = Ertelmezo(description="AUX klíma vezérlése az AC Freedom felhőn át")
    p.add_argument("parancs", choices=["allapot", "be", "ki", "hofok", "mod", "vent"])
    p.add_argument("ertek", nargs="?", help="hőfok (be, hofok), üzemmód (mod) vagy fokozat (vent)")
    p.add_argument("--mod", help="üzemmód a be parancshoz: hutes, futes, szaritas, ventilator, auto")
    p.add_argument("--vent", help="ventilátor a be parancshoz: auto, alacsony, kozepes, magas, turbo, csendes")
    p.add_argument("--proba", action="store_true", help="próbamenet: kiírja, mit küldene, de nem küld")
    p.add_argument("--nincs-ellenorzes", action="store_true", help="küldés után nem olvas vissza")
    p.add_argument("--szabvanyos-profil", action="store_true",
                   help="ismeretlen termékazonosítónál a szabványos AUX klímaprofilt használja")
    p.add_argument("--email", help="AC Freedom fiók e-mail címe")
    p.add_argument("--regio", help="felhőrégió: eu, usa, cn, rus (alap: config.sh vagy eu)")
    args = p.parse_args()
    args._kuldes_indult = False

    if args.parancs in ("allapot", "ki") and args.ertek is not None:
        naplo(f"HIBA: a(z) '{args.parancs}' parancsnak nincs értéke.")
        return 64
    if (args.mod or args.vent) and args.parancs != "be":
        naplo("HIBA: a --mod és --vent csak a 'be' paranccsal használható.")
        return 64

    olvaso = args.parancs == "allapot" or args.proba
    if olvaso:
        kozos.irasi_zar()
        naplo("Biztonsági zár aktív: parancsküldés letiltva"
              f"{' (próbamenet)' if args.proba else ''}.")

    # Előbb az értékek, csak utána a felhő: az elgépelés ne kerüljön forgalomba.
    try:
        kiv = {} if args.parancs == "allapot" else kivansag(args)
    except HasznalatiHiba as e:
        naplo(f"HIBA: {e}")
        return 64

    email = kozos.email_cim(args.email)
    reg = kozos.regio(args.regio)
    hitel = kozos.belepesi_adatok(email)

    async with aiohttp.ClientSession() as munkamenet:
        kliens = DnaClient(region=reg, session=munkamenet)
        try:
            async with asyncio.timeout(TELJES_HATARIDO):
                return await futtatas(args, kliens, hitel, reg, kiv)
        except HasznalatiHiba as e:
            naplo(f"HIBA: {e}")
            return 64
        except AuxRateLimitError as e:
            naplo(f"HIBA: kéréskorlát: {e}")
            return 8
        except (AuxNetworkError, AuxServerError) as e:
            naplo(f"HIBA: a felhő nem érhető el: {type(e).__name__}: {e}")
            return 7 if args._kuldes_indult else 3
        except (AuxSessionExpired, AuxAuthError) as e:
            naplo(f"HIBA: bejelentkezés: {type(e).__name__}: {e}")
            return 1
        except AuxApiError as e:
            naplo(f"HIBA: a felhő hibát adott: {type(e).__name__}: {e}")
            return 7 if args._kuldes_indult else 1
        except TimeoutError:
            naplo(f"HIBA: időtúllépés ({TELJES_HATARIDO} s) a felhővel.")
            return 7 if args._kuldes_indult else 9
        except Exception as e:
            naplo(f"HIBA: váratlan hiba: {type(e).__name__}: {e}")
            traceback.print_exc(file=sys.stderr)
            return 7 if args._kuldes_indult else 70
        finally:
            # A küldés közbeni csendes újrabelépés új munkamenetet adhatott.
            # Ez csak gyorsítótár: hibája nem írhatja felül a kilépési kódot.
            kozos.munkamenet_mentese(kliens, hitel, reg)
            await kliens.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
