"""A lekérdező és a vezérlő közös része: belépés, munkamenet, készülékválasztás.

Jelszókezelés: a script SOHA nem tárol jelszót. Sorrendben próbálja:
  1. AUX_PASSWORD környezeti változó
  2. macOS Kulcskarika (security find-generic-password -s auxcloud)
  3. ~/.config/aux/jelszo fájl (600) — SSH-munkamenethez, ahol a Kulcskarika
     36-os kóddal elbukik, mert nincs, aki a hozzáférést megerősítse
  4. interaktív bekérés (getpass), de csak valódi terminálban

Munkamenet: a sikeres belépés után a loginsession/userid pár a
~/.config/aux/munkamenet.json fájlba kerül (600). Így nem kell minden egyes
telefonos koppintásnál újra belépni: a felhőnek van kéréskorlátja (-2001,
-1036), és a sűrű belépés az app munkamenetét is kiléptetheti. Ha a mentett
munkamenet lejárt, a kliens magától újra belép.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from getpass import getpass
from pathlib import Path
from typing import Any

from auxcloud.api import AuxApiError, AuxAuthError, AuxCredentials, AuxSessionExpired
from auxcloud.devices import (
    DEFAULT_PROFILE,
    STANDARD_AC_PROFILE,
    DeviceType,
    get_device_profile,
    normalize_device_params,
)
from auxcloud.dna import DnaClient

import konfig

konfig.betoltes()

KONFIG_MAPPA = Path.home() / ".config" / "aux"
JELSZOFAJL = KONFIG_MAPPA / "jelszo"
MUNKAMENET_FAJL = KONFIG_MAPPA / "munkamenet.json"
KULCSKARIKA = "auxcloud"
REGIOK = ("eu", "usa", "cn", "rus")

MODOK = {0: "hűtés", 1: "fűtés", 2: "szárítás", 3: "ventilátor", 4: "auto"}
VENTILATOR = {
    0: "auto", 1: "alacsony", 2: "közepes", 3: "magas", 4: "turbó",
    5: "csendes", 6: "közepes-alacsony", 7: "közepes-magas",
}

# Ezek a mezők a felhő titkai (a cookie-ban van a készülék AES-kulcsa is), a
# MAC pedig azonosítja a készüléket — a --json kimenetet épp hibabejelentésbe
# szokás bemásolni, ezért mindet kitakarjuk. A MAC a sima kimenetben ott van.
TITKOS_MEZOK = ("cookie", "devSession", "aeskey", "key", "profile", "mac")


def naplo(uzenet: str) -> None:
    """Folyamatüzenet a stderr-re — a stdout a végeredménynek marad."""
    print(uzenet, file=sys.stderr)


def irasi_zar() -> None:
    """Fizikailag lehetetlenné teszi az írást ebben a folyamatban."""

    async def tiltva(*_args, **_kwargs):
        raise RuntimeError(
            "BIZTONSÁGI ZÁR: parancsküldés letiltva (csak olvasás vagy próbamenet)."
        )

    DnaClient.set_device_params = tiltva
    DnaClient.set_device_params_http = tiltva
    DnaClient._act_websocket = tiltva

    # A tényleges szűk keresztmetszet: minden HTTP-s készülékművelet ezen megy
    # ki, az olvasás is. Csak a "get"-et engedjük tovább.
    eredeti = DnaClient._act_http

    async def csak_olvasas(self, device, act, params, vals=None):
        if act != "get":
            await tiltva()
        return await eredeti(self, device, act, params, vals)

    DnaClient._act_http = csak_olvasas


def email_cim(email_arg: str | None) -> str:
    email = (email_arg or os.environ.get("AUX_EMAIL", "")).strip()
    if email:
        return email
    if not sys.stdin.isatty():
        raise SystemExit("HIBA: hiányzik az AUX_EMAIL, és nincs interaktív terminál a bekéréséhez.")
    return input("AC Freedom fiók e-mail címe: ").strip()


def regio(regio_arg: str | None) -> str:
    r = (regio_arg or os.environ.get("AUX_REGIO", "") or "eu").strip().lower()
    if r not in REGIOK:
        raise SystemExit(f"HIBA: ismeretlen régió: '{r}'. Használható: {', '.join(REGIOK)}")
    return r


def belepesi_adatok(email: str) -> AuxCredentials:
    jelszo = os.environ.get("AUX_PASSWORD", "")
    forras = "AUX_PASSWORD környezeti változó"

    if not jelszo:
        try:
            r = subprocess.run(
                ["security", "find-generic-password", "-s", KULCSKARIKA, "-a", email, "-w"],
                capture_output=True, text=True, timeout=10,
            )
            # Csak a záró újsort vágjuk le: a jelszó elején/végén lehet szóköz.
            jelszo = r.stdout.rstrip("\n") if r.returncode == 0 else ""
            forras = "macOS Kulcskarika"
            # A 44-es kód azt jelenti, hogy nincs ilyen tétel — ez nem hiba,
            # a jelszófájl a várt út. A többi kódot (pl. 36, SSH-ból) kiírjuk.
            if r.returncode not in (0, 44):
                naplo(f"  Kulcskarika nem elérhető (kód {r.returncode}): "
                      f"{r.stderr.strip()[:200]}")
        except Exception as e:
            naplo(f"  Kulcskarika hiba: {type(e).__name__}: {e}")
            jelszo = ""

    fajlbol = ""
    if JELSZOFAJL.is_file():
        mod = JELSZOFAJL.stat().st_mode & 0o777
        if mod & 0o077:
            naplo(f"  FIGYELEM: {JELSZOFAJL} jogosultsága {oct(mod)}, legyen 600 "
                  f"(chmod 600 {JELSZOFAJL})")
        fajlbol = JELSZOFAJL.read_text(encoding="utf-8").rstrip("\n")

    if not jelszo and fajlbol:
        jelszo = fajlbol
        forras = str(JELSZOFAJL)
    elif jelszo and fajlbol and jelszo != fajlbol and forras == "macOS Kulcskarika":
        # Terminálból a Kulcskarika nyer, SSH-n a fájl — ha a kettő eltér, a
        # két útvonal máshogy viselkedne. Ez jelszócsere után fordul elő.
        naplo("  FIGYELEM: a Kulcskarikában és a jelszófájlban MÁS jelszó van. "
              "Most a Kulcskarikáé megy; SSH-n a fájlé menne. "
              "Futtasd újra: ./jelszo_beallitas.sh")

    if not jelszo:
        if not sys.stdin.isatty():
            raise SystemExit(
                "HIBA: nincs mentett jelszó, és nincs interaktív terminál a bekéréséhez. "
                "Futtasd egyszer terminálból: ./jelszo_beallitas.sh"
            )
        jelszo = getpass(f"AC Freedom jelszó ({email}): ")
        forras = "interaktív bekérés"

    naplo(f"  jelszó forrása: {forras}")
    return AuxCredentials.email(email, jelszo)


def _munkamenet_betoltese(kliens: DnaClient, hitel: AuxCredentials, reg: str) -> bool:
    try:
        adat = json.loads(MUNKAMENET_FAJL.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if adat.get("email") != hitel.username or adat.get("regio") != reg:
        return False
    sess, uid = adat.get("loginsession"), adat.get("userid")
    if not isinstance(sess, str) or not isinstance(uid, str):
        return False
    # A kiemelt kliensnek nincs nyilvános módja munkamenetet visszatölteni,
    # ezért a DnaHttp mezőit állítjuk be közvetlenül (a V2.0.0-hoz rögzítve).
    kliens._session.loginsession = sess
    kliens._session.userid = uid
    return True


def munkamenet_mentese(kliens: DnaClient, hitel: AuxCredentials, reg: str) -> None:
    """A munkamenet mentése. Csak gyorsítótár: hiba esetén sem borítja a futást."""
    http = kliens._session
    if not http.is_logged_in():
        return
    adat = {"email": hitel.username, "regio": reg,
            "loginsession": http.loginsession, "userid": http.userid}
    ideiglenes = None
    try:
        KONFIG_MAPPA.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Egyedi átmeneti név: két egyidejű futás (dupla koppintás) különben
        # ugyanazt a fájlt írná, és az egyik átnevezése FileNotFoundError-t adna.
        # Az mkstemp eleve 600-as és O_EXCL, így symlinkre sem futhat rá.
        fd, nev = tempfile.mkstemp(dir=KONFIG_MAPPA, prefix=".munkamenet.", suffix=".tmp")
        ideiglenes = Path(nev)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(adat, f)
        os.replace(ideiglenes, MUNKAMENET_FAJL)
        ideiglenes = None
    except OSError as e:
        naplo(f"  FIGYELEM: a munkamenet nem menthető ({type(e).__name__}: {e})")
        if ideiglenes is not None:
            try:
                ideiglenes.unlink()
            except OSError:
                pass


def munkamenet_torlese() -> None:
    """Elavult munkamenet eldobása (pl. hibás jelszó után)."""
    try:
        MUNKAMENET_FAJL.unlink()
    except OSError:
        pass


async def kapcsolodas(kliens: DnaClient, hitel: AuxCredentials, reg: str):
    """Belép (vagy visszatölti a mentett munkamenetet), és lekéri a készülékeket."""
    # A kliens ebből lép be újra, ha a felhő lejártnak jelzi a munkamenetet.
    kliens._session._credentials = hitel

    mentett = _munkamenet_betoltese(kliens, hitel, reg)
    if mentett:
        naplo("  mentett munkamenet használata")
    else:
        naplo(f"Bejelentkezés az AUX felhőbe ({reg})…")
        await kliens.login(hitel)
        munkamenet_mentese(kliens, hitel, reg)

    try:
        leltar = await kliens.scan_devices()
    except AuxSessionExpired:
        if not mentett:
            raise
        naplo("  a mentett munkamenet lejárt, újra belépek")
        await kliens.login(hitel)
        leltar = await kliens.scan_devices()
    except AuxAuthError:
        # A jelszó rossz (pl. megváltozott az appban). Újrapróbálkozás helyett
        # eldobjuk a munkamenetet, különben minden koppintás két hibás
        # belépést jelentene a felhő felé.
        munkamenet_torlese()
        raise

    # Ha közben csendes újrabelépés történt, az új munkamenetet mentjük el.
    munkamenet_mentese(kliens, hitel, reg)
    return leltar


def mac_norm(m: str | None) -> str:
    return "".join(c for c in (m or "").upper() if c in "0123456789ABCDEF")


def mac_szep(m: str | None) -> str:
    h = mac_norm(m)
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2)) if len(h) == 12 else (m or "?")


def klimak(eszkozok) -> list[dict[str, Any]]:
    """A fiók készülékei közül azok, amik nem hőszivattyúk (ismeretlen is ide tartozik)."""
    return [e for e in eszkozok if get_device_profile(e).device_type is not DeviceType.HEAT_PUMP]


def klima_kivalasztasa(eszkozok) -> dict[str, Any]:
    """A config.sh KLIMA_NEV-je szerint, vagy ha csak egy klíma van, azt."""
    nev = os.environ.get("KLIMA_NEV", "").strip()
    jeloltek = klimak(eszkozok)
    if nev:
        talalat = [e for e in jeloltek if (e.get("friendlyName") or "").strip() == nev]
        if len(talalat) != 1:
            nevek = ", ".join(f"„{e.get('friendlyName')}”" for e in jeloltek) or "nincs"
            raise LookupError(f"Nincs pontosan egy „{nev}” nevű klíma. A fiókban: {nevek}")
        return talalat[0]
    if len(jeloltek) == 1:
        return jeloltek[0]
    if not jeloltek:
        raise LookupError("A fiókhoz nem tartozik klíma.")
    nevek = ", ".join(f"„{e.get('friendlyName')}”" for e in jeloltek)
    raise LookupError(f"Több klíma van a fiókban ({nevek}) — add meg a KLIMA_NEV-et a config.sh-ban.")


def rogzitett_valasztas() -> bool:
    """Igaz, ha a config.sh név vagy MAC alapján egyértelműen kijelöli a klímát."""
    return bool(os.environ.get("KLIMA_NEV", "").strip()
                or os.environ.get("KLIMA_MAC", "").strip())


async def allapot_biztositasa(kliens: DnaClient, eszkoz: dict[str, Any]) -> bool:
    """Pótolja a hiányzó állapotot, ha a leltár részlekérdezései elbuktak.

    A kiemelt kliens indulása elnézi az egyes lekérdezések hibáját, így a
    params üres vagy hiányos maradhat. Ilyenkor a klíma kikapcsoltnak
    látszana, a hőfok kódolása pedig a hiányzó tempunit miatt téves lehetne.
    Visszatérés: van-e (már) értelmezhető állapot.
    """
    if "pwr" in (eszkoz.get("params") or {}):
        return True
    naplo("  a leltár nem hozott teljes állapotot, újrakérdezem")
    ujak = await kliens.get_device_params(eszkoz)
    try:
        ujak.update(await kliens.get_device_params(eszkoz, ["mode"]))
    except AuxApiError as e:
        naplo(f"  a szobahőmérséklet nem kérdezhető le ({type(e).__name__})")
    if ujak:
        eszkoz["params"] = {**(eszkoz.get("params") or {}), **ujak}
        normalize_device_params(eszkoz)
    return "pwr" in (eszkoz.get("params") or {})


def mac_ellenorzes(eszkoz: dict[str, Any]) -> tuple[bool | None, str]:
    """(egyezik?, szöveg). None, ha nincs beállítva KLIMA_MAC."""
    vart = os.environ.get("KLIMA_MAC", "").strip()
    if not vart:
        return None, "kihagyva (nincs KLIMA_MAC a config.sh-ban)"
    if mac_norm(eszkoz.get("mac")) == mac_norm(vart):
        return True, "EGYEZIK a beállított készülékkel"
    return False, f"NEM egyezik — a várt cím {mac_szep(vart)}, a felhő szerint {mac_szep(eszkoz.get('mac'))}"


def ismert_profil(eszkoz: dict[str, Any]) -> bool:
    return get_device_profile(eszkoz) is not DEFAULT_PROFILE


def ismeretlen_volt(eszkoz: dict[str, Any]) -> bool:
    """Ismeretlen volt-e a termék, mielőtt ráhúztuk a szabványos profilt."""
    return bool(eszkoz.get("_ismeretlen_termek")) or not ismert_profil(eszkoz)


async def szabvanyos_profil_ravetele(kliens: DnaClient, eszkoz: dict[str, Any]) -> None:
    """Ismeretlen termékazonosítóhoz a szabványos AUX klímaprofilt használjuk.

    A kiemelt kliens ismeretlen termékre nem kérdez le állapotot, és írni sem
    enged. Ez csak kifejezett kérésre (--szabvanyos-profil) fut: a
    szabványos klímák paramétereit (pwr, temp, ac_mode, ac_mark) küldi.
    """
    # Megjegyezzük, hogy eredetileg ismeretlen volt: a profil felülírása után
    # a lekérdezés különben azt mutatná, hogy minden rendben.
    eszkoz["_ismeretlen_termek"] = True
    eszkoz["profile"] = STANDARD_AC_PROFILE
    if eszkoz.get("state") != 1:
        return
    params = await kliens.get_device_params(eszkoz)
    # A "mode" különleges lekérdezés: erre adja vissza a klíma a
    # szobahőmérsékletet. Nem minden termék ismeri (-49025), ezért puha hiba:
    # a kiemelt kliens saját indulása is elnézi az egyes lekérdezések bukását.
    try:
        params.update(await kliens.get_device_params(eszkoz, ["mode"]))
    except AuxApiError as e:
        naplo(f"  a szobahőmérséklet nem kérdezhető le ({type(e).__name__})")
    eszkoz["params"] = params
    normalize_device_params(eszkoz)


def fok(x10: Any) -> str:
    """A felhő tizedfokban adja a hőmérsékletet: 235 → „23,5 °C”."""
    if not isinstance(x10, (int, float)) or isinstance(x10, bool):
        return "?"
    ertek = x10 / 10
    szoveg = f"{ertek:.1f}".rstrip("0").rstrip(".")
    return f"{szoveg.replace('.', ',')} °C"


def allapot_sor(eszkoz: dict[str, Any]) -> str:
    """Egy sor a telefonra: „BE · hűtés · cél 23 °C · szoba 26,5 °C · ventilátor auto”."""
    if eszkoz.get("state") != 1:
        return "A klíma OFFLINE (nincs kapcsolata a felhővel)."
    if get_device_profile(eszkoz).device_type is DeviceType.HEAT_PUMP:
        # A hőszivattyú más paraméterneveket és más módkódokat használt (1 =
        # hűtés, 4 = fűtés), a klíma-jelentések félrevezetnének.
        return "Hőszivattyú — a részleteket a `lekerdez.py --mind` mutatja."
    p = eszkoz.get("params") or {}
    if not p:
        return "A klíma online, de nem adott vissza állapotot."
    if "pwr" not in p:
        reszek = ["ISMERETLEN állapot (a klíma nem adta vissza)"]
    else:
        reszek = ["BE" if p.get("pwr") == 1 else "KI"]
    if "ac_mode" in p:
        reszek.append(MODOK.get(p["ac_mode"], f"mód {p['ac_mode']}"))
    if "temp" in p:
        reszek.append(f"cél {fok(p['temp'])}")
    # A szobahőmérséklet néha 0-t ad (ha-aux-cloud #58) — azt nem írjuk ki.
    if p.get("envtemp"):
        reszek.append(f"szoba {fok(p['envtemp'])}")
    if "ac_mark" in p:
        reszek.append(f"ventilátor {VENTILATOR.get(p['ac_mark'], p['ac_mark'])}")
    return " · ".join(reszek)


def kitakart(eszkoz: dict[str, Any]) -> dict[str, Any]:
    """A készülékrekord a titkos mezők nélkül, JSON-kiíráshoz."""
    return {k: ("<kitakarva>" if k in TITKOS_MEZOK else v) for k, v in eszkoz.items()}
