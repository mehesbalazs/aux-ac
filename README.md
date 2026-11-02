# Klíma távvezérlés (AUX, AC Freedom)

AUX klíma lekérdezése és vezérlése (be/ki, hőfok, üzemmód, ventilátor) az
AC Freedom felhőn keresztül — terminálból és iPhone-ról egyaránt.

Az újabb AUX klímák Broadlink-alapú wifi-modulja **nem fogad helyi
vezérlést**. Az UDP 80-as port nyitva van, de a modul sem a Broadlink
felderítésre, sem a hitelesítésre nem válaszol, a TCP-portok pedig mind
zártak. Ezt 2023 óta sokan jelentik az AUX-ra és a rokon márkákra (Rinnai,
Tornado, Naitec stb.). A felhő ezért az egyetlen szoftveres út. A régebbi
modulok még válaszoltak helyben, ezeknél a `broadlink` könyvtár működik.

> **Nem hivatalos projekt.** A felhőkliens visszafejtett API-ra épül (az AC
> Freedom app azonosítóival jelentkezik be), és a gyártó bármikor
> megváltoztathatja. Semmilyen kapcsolatban nem áll az AUX-szal vagy a
> Broadlinkkel. Saját felelősségre használd.

## Felépítés

```
  iPhone (Parancsok app)
        │  SSH
        ▼
  klima.sh  ─────────▶  klima.log
        │
        ▼
  klima.py, lekerdez.py  ──▶  kozos.py + konfig.py  ──▶  auxcloud/ (kiemelt kliens)
        │
        ▼
  AUX felhő (EU)  ─────▶  klíma
```

| fájl | szerep | mikor fut |
|---|---|---|
| `lekerdez.py` | lekérdezés, csak olvas | kézzel, első beállításkor és hibakereséskor |
| `klima.py` | vezérlés, ellenőrzésekkel | kézzel vagy a burkolón át |
| `kozos.py` | belépés, munkamenet, készülékválasztás | importként |
| `konfig.py` | a config.sh export sorainak beolvasása, shell nélkül | importként |
| `klima.sh` | telefonos burkoló, naplózás | minden SSH-hívásnál |
| `jelszo_beallitas.sh` | config.sh és jelszófájl létrehozása | csak beállításkor |
| `parancs_keszito.py` | a Parancsok-fájlok generálása | csak beállításkor |
| `auxcloud/` | a felhőkliens, változtatás nélkül | importként |

## A felhőkliens — `auxcloud/`

A [maeek/ha-aux-cloud](https://github.com/maeek/ha-aux-cloud) Home Assistant
integráció V2.0.0-s kiadásából kiemelt, **változtatás nélküli** fájlok (MIT
licenc). Ez a projekt nem használ Home Assistantot: az integráció felhőkliense
(`api/`, `dna/`, `devices.py`, `device_metadata.py`) a projekt saját tesztje
szerint sem importálja azt. Egyedül az `__init__.py` saját, mert az eredeti
Home Assistantot tölt be. A pontos forrás és a frissítés módja:
[auxcloud/FORRAS.md](auxcloud/FORRAS.md).

Önálló PyPI-csomag ehhez a felhőhöz nincs: az ismert kliensek mind ennek a
kódnak a portjai.

## Előfeltételek

- **macOS.** A jelszó a Kulcskarikából is jöhet (`security`), a Parancsok-fájlokat
  a `shortcuts` írja alá, és a burkoló a BSD `stat`-ot használja. Terminálból a
  lekérdezés és a vezérlés Linuxon is menne, a telefonos rész nem.
- **Python 3.11 vagy újabb** (a kliens `StrEnum`-ot és `datetime.UTC`-t, a
  vezérlő `asyncio.timeout`-ot használ). A projekt 3.12-vel készült.
- Egy **AC Freedom-fiók**, amihez a klíma már hozzá van adva.
- A telefonos részhez: bekapcsolt **Távoli bejelentkezés** (SSH) a Macen.

## Beállítás

```
uv venv --python 3.12                    # vagy: python3.12 -m venv .venv
uv pip install -r requirements.txt       # vagy: .venv/bin/pip install -r requirements.txt
./jelszo_beallitas.sh
```

A `jelszo_beallitas.sh` terminálból futtatva:

1. létrehozza a `config.sh`-t a mintából, az e-mail címeddel;
2. a jelszót a `~/.config/aux/jelszo` fájlba menti (600);
3. kérésre a macOS Kulcskarikába is menti (`auxcloud` szolgáltatásnéven), majd
   visszaolvassa: ha nem ugyanaz a jelszó került oda, mint a fájlba, a
   bejegyzést törli, mert terminálból az elsőbbséget kapna.

A jelszó nem jelenik meg a képernyőn, és parancssori argumentumba sem kerül.

A `config.sh` verziókövetésen kívül van, és ezeket adja meg:

| beállítás | mire való |
|---|---|
| `AUX_EMAIL` | a fiók e-mail címe (ezt a beállító tölti ki) |
| `AUX_REGIO` | `eu`, `usa` (= „Other Areas”), `cn` vagy `rus` |
| `KLIMA_NEV` | csak ha több klíma van a fiókban |
| `KLIMA_MAC` | a wifi-modul MAC-címe — **üresen hagyva nincs ellenőrzés** |
| `KLIMA_SZABVANYOS_PROFIL` | `1`, ha ismeretlen a termékazonosító (lásd lentebb) |
| `SSH_HOST`, `SSH_PORT`, `SSH_USER` | csak a Parancsok-fájlok generálásához |

A `KLIMA_MAC`-et a `lekerdez.py` írja ki; ha kitöltöd, a vezérlő minden
küldés előtt összeveti vele, amit a felhő mond — így egy másik készülék
sosem kap parancsot. Üresen ez az ellenőrzés kimarad.

Ha egy későbbi verzióban új beállítás kerül a mintába, a
`jelszo_beallitas.sh` újrafuttatása a meglévő `config.sh`-ba is bemásolja.

**Csak AC Freedom-fiók működik.** Az újabb „AUX Home” app fiókjai egy másik
Broadlink-bérlőben vannak, ezekkel a belépés `-1006`/`-1008` hibával elbukik.
Apple-gombos vagy csak SMS-kódos fiókhoz előbb jelszót kell beállítani (az
appban: elfelejtett jelszó).

## Jelszó és munkamenet

A script a jelszót ebben a sorrendben keresi:

1. `AUX_PASSWORD` környezeti változó;
2. macOS Kulcskarika (`security find-generic-password -s auxcloud`);
3. `~/.config/aux/jelszo` (600);
4. interaktív bekérés, de csak valódi terminálban.

SSH-munkamenetből a Kulcskarika elérhetetlen (`security` 36-os kód: „interakció
nem engedélyezett”, mert nincs, aki a hozzáférést megerősítse), ezért kell a
jelszófájl. A telefonos parancsok emiatt mindig a fájlból lépnek be.

A sikeres belépés után a munkamenet a `~/.config/aux/munkamenet.json` fájlba
kerül (600), így nem kell minden koppintásnál újra belépni. A felhőnek van
kéréskorlátja (`-2001`, `-1036`), és a sűrű belépés az app munkamenetét is
kiléptetheti. Ha a mentett munkamenet lejárt, a script magától újra belép.

## Biztonsági zár

A `lekerdez.py`, a `klima.py allapot` és a `--proba` induláskor letiltja a
kliens **négy** író útvonalát: a `set_device_params`, a
`set_device_params_http` és a `_act_websocket` metódust, valamint a tényleges
szűk keresztmetszetet, a `_act_http`-t (ebből csak a `get` megy tovább). Ezek
a futások **képtelenek** parancsot küldeni a klímának.

## Használat

Első lépésként nézd meg, mit lát a felhő:

```
.venv/bin/python lekerdez.py            # név, termékazonosító, MAC, állapot
.venv/bin/python lekerdez.py --mind     # az összes paraméter
.venv/bin/python lekerdez.py --json     # nyers adat, a felhő titkai kitakarva
```

A `--json` kitakarja a felhő titkait (eszköz-cookie, `devSession`, AES-kulcs)
és a MAC-címet is, mert épp ezt a kimenetet szokás hibabejelentésbe bemásolni.
A fiókazonosítók (`endpointId`, `familyId`) benne maradnak, úgyhogy megosztás
előtt akkor is nézd át. Mindkét scripten van `--email` és `--regio` kapcsoló
is, ha a `config.sh` értékét egy futásra felül akarod írni.

Ha a termékazonosító mellett az áll, hogy **ISMERETLEN**, akkor a kliens nem
ismeri a típust. Ilyenkor nem kérdez le állapotot, és írni sem enged. A
`--szabvanyos-profil` kapcsoló a szabványos AUX klímaprofillal próbálja
(`pwr`, `temp`, `ac_mode`, `ac_mark`). Előbb a `lekerdez.py`-jal érdemes
megnézni, hogy így értelmes állapotot ad-e. Telefonról ugyanez a `config.sh`
`KLIMA_SZABVANYOS_PROFIL="1"` beállításával kérhető.

## Vezérlés — `klima.py`

```
.venv/bin/python klima.py allapot
.venv/bin/python klima.py be                       # az utolsó beállításokkal
.venv/bin/python klima.py be 23 --mod hutes --vent auto
.venv/bin/python klima.py ki
.venv/bin/python klima.py hofok 22.5               # be/ki állapotot nem vált
.venv/bin/python klima.py mod futes                # hutes futes szaritas ventilator auto
.venv/bin/python klima.py vent csendes             # auto alacsony kozepes magas turbo csendes
.venv/bin/python klima.py be 23 --proba            # próbamenet, semmi nem megy el
.venv/bin/python klima.py ki --nincs-ellenorzes    # küldés után nem olvas vissza
```

A `--nincs-ellenorzes` megváltoztatja a 0-s kód jelentését: ilyenkor annyit
tudunk, hogy a parancs elment, nem azt, hogy a klíma át is állt.

Küldés előtt a vezérlő ezeket ellenőrzi:

- **még bejelentkezés előtt:** érvényes-e az érték (16–32 °C, egész vagy fél
  fok, ismert mód és fokozat) — így egy elgépelés nem kerül felhőforgalomba,
  és nem „offline” üzenetként jön vissza;
- online-e a klíma, és adott-e róla a felhő értelmezhető állapotot;
- egyezik-e a MAC-címe a `config.sh`-ban beállítottal (csak ha a `KLIMA_MAC`
  ki van töltve — üresen ez az ellenőrzés kimarad);
- ismert-e a termékprofil, és elfogadja-e az adott módot vagy fokozatot;
- teljes-e a felhő listája — ha hiányos, és a `config.sh` nem jelöli ki
  névvel vagy MAC-cel a klímát, inkább nem csinál semmit.

Ha a kért állapot már most is így van, **nem küld semmit**. Küldés után
visszaigazolást vár: vagy már a felhő válaszában, vagy legfeljebb három
visszaolvasással, összesen kb. 13 másodpercen belül. A teljes futásra 60
másodperces határidő van, hogy a telefon ne maradjon válasz nélkül.

Ha a küldés bizonytalan hibára fut (átjáróhiba, hálózati hiba), **nem**
mondja azt, hogy elutasították: visszaolvasással dönti el, átment-e. Ha a
visszaolvasás nem sikerül, vagy sikerül ugyan, de a klíma nem állt át, a 7-es
kóddal jelzi, hogy nem tudni. Az 5-ös kód csak akkor jön, ha maga a küldés
hibátlanul lefutott, és utána mutat mást a klíma.

### Kilépési kódok

A 0–9, 64 és 70 a `klima.py` kódja; a 65 és 66 a burkolóé, ezeknél a Python el
sem indul.

| kód | jelentés |
|---|---|
| 0 | rendben (vagy már így volt) |
| 1 | bejelentkezési/konfigurációs hiba, vagy nincs meg a klíma |
| 2 | a klíma offline |
| 3 | a felhő nem érhető el vagy hiányosan válaszolt, semmi nem ment el |
| 4 | a klíma elutasította a parancsot (biztosan nem állt át) |
| 5 | a küldés hibátlan volt, de a visszaolvasott állapot más |
| 6 | nem a várt klíma válaszolt (MAC-eltérés) |
| 7 | **bizonytalan**: nem derült ki, átment-e — ellenőrizd újrapróbálás előtt |
| 8 | kéréskorlát, túl sűrű kérések |
| 9 | időtúllépés a felhővel |
| 64 | hibás használat |
| 65 | *(burkoló vagy import)* nincs meg a `.venv` Pythonja, vagy hiányzik egy csomag |
| 66 | *(burkoló)* nincs `AUX_EMAIL` — hiányzó vagy kitöltetlen `config.sh` |
| 70 | váratlan hiba (a részletek a klima.log-ban) |

## iPhone — Parancsok app

A burkolót a Parancsok app „Szkript futtatása SSH-n” műveletével hívod: a
telefon SSH-val belép a Macre, lefuttatja a `klima.sh`-t, és megmutatja az
egysoros választ. Minden futás a `klima.log`-ba kerül.

Hat parancs készül:

| parancs | mit csinál |
|---|---|
| **Klíma - Kikapcsolás** | `klima.sh ki` |
| **Klíma - Állapot** | `klima.sh allapot` — csak olvas |
| **Klíma - Hűtés 26 Csendes** | `klima.sh be 26 hutes csendes` |
| **Klíma - Hűtés 16 Magas** | `klima.sh be 16 hutes magas` |
| **Klíma - Szárítás 16 Alacsony** | `klima.sh be 16 szaritas alacsony` |
| **Klíma - Fűtés 26 Csendes** | `klima.sh be 26 futes csendes` |

Megerősítést egyik sem kér: a klíma állítása visszafordítható, és a telefonon
a megerősítés csak útban lenne. A határokat a `klima.sh` őrzi: a próbamenet
szava (`proba`, `próba`, `--proba`) bárhol állhat, amit pedig nem ért — fölös
szó, kapcsolónak látszó argumentum, két hőfok —, azt **nem dobja el csendben**,
hanem 64-es kóddal visszautasítja, mielőtt bármi elmenne a felhőbe. A
`klima.log` csak a tulajdonos számára olvasható (600), és 256 KB fölött
magától megrövidül.

A parancsfájlok legenerálása és aláírása. **Előbb töltsd ki a `config.sh`
`SSH_HOST` és `SSH_USER` sorát** (a Mac címe és felhasználóneve) — enélkül a
generátor hibával áll meg:

```
.venv/bin/python parancs_keszito.py          # -> parancsok/*.shortcut
open "parancsok/Klíma - Állapot.shortcut"    # importálás (Hozzáadás gomb)
```

Importálás után iCloudon át átszinkronizál az iPhone-ra. A parancs
felépítése: **Szkript futtatása SSH-n** (gép, port, felhasználó a `config.sh`-ból,
hitelesítés SSH-kulccsal, a szkript `<projekt>/klima.sh <parancs>`), majd
**Értesítés megjelenítése** a válasszal.

Kitétel: kezdőképernyő-widget, Zárolási képernyő, Művelet gomb vagy Siri — a
parancs neve lesz a kimondandó szöveg.

### Ami az iPhone-on és a Macen egyszer beállítandó

1. **Távoli bejelentkezés** a Macen: Rendszerbeállítások → Általános →
   Megosztás → Távoli bejelentkezés. A macOS alkalmazás-tűzfala külön
   engedélyt kérhet az `sshd`-nek; enélkül a kapcsolat kívülről nem jön létre,
   loopbackon viszont igen — ez a különbség árulja el.
2. **SSH-kulcs.** A Parancsok appban a művelet Hitelesítés mezőjében válaszd
   az SSH-kulcsot; az app generál egyet, és a *Nyilvános kulcs megosztása*
   gombbal kiadja. Ezt fűzd hozzá a Mac `~/.ssh/authorized_keys` fájljához. A
   telefon és a Mac **külön kulcsot** használ, mindkettőt hozzá kell fűzni.
   Ha a Parancsok appban már van kulcs, az új parancsok maguktól azt
   használják, és nincs több teendő.
3. **iCloud-szinkron** a Parancsok appban, különben a Macen készült parancsok
   meg sem jelennek a telefonon.
4. **Szkriptek futtatásának engedélyezése** az iPhone-on: Beállítások →
   Alkalmazások → Parancsok → Speciális. Alapból ki van kapcsolva; enélkül
   „a Parancsok biztonsági beállításai nem teszik lehetővé” hibát kapsz.
5. **Helyi hálózat** engedély az első futtatáskor (felugró kérdés).

Otthonról kívülről a Mac belső címe nem érhető el: erre VPN a megoldás
(például a routeren beállított WireGuard). SSH-t ne nyiss ki az internet felé.

Ellenőrzésnek a Macről is futtatható: `shortcuts run "Klíma - Állapot"`. A
naplóban a „jelszó forrása: …/.config/aux/jelszo” sor mutatja, hogy a futás
tényleg SSH-munkamenetben történt (terminálból a Kulcskarika lenne a forrás).
Ha van Kulcskarika-bejegyzés, mellette a „Kulcskarika nem elérhető (kód 36)”
sor is megjelenik.

A burkoló közvetlenül is hívható, ugyanezekkel a szavakkal:

```
klima.sh allapot
klima.sh be 23               # a szám a hőfok
klima.sh be 23 hutes         # az első szó az üzemmód
klima.sh be 23 hutes csendes # a második a ventilátor
klima.sh ki
klima.sh hofok 22.5
klima.sh mod futes
klima.sh vent auto
klima.sh be 23 proba         # próbamenet
```

## Hardveres alternatíva

Ha a felhő megbízhatatlannak bizonyul, vagy teljesen helyi vezérlés kell, a
gyári wifi-modul helyére ESP-modul tehető a
[GrKoR/esphome_aux_ac_component](https://github.com/GrKoR/esphome_aux_ac_component)
komponenssel. Ez a beltéri egység UART-csatlakozójára kerül, és Home Assistant
nélkül, helyben vezérelhető. Ára kb. 30–45 € kész modulként, vagy 10–15 €
saját építésben. Az AC Freedom app ezzel elvész. Előtte ellenőrizni kell a
csatlakozó típusát és a gyártási évet, mert a kiosztás 2022–23-ban megváltozott.

## Licenc

A saját kód MIT licencű: [LICENSE](LICENSE).

A kiemelt `auxcloud/` kliens szintén MIT, de **saját szerzői jogi
közleménnyel**: [auxcloud/LICENSE](auxcloud/LICENSE). Ezt a közleményt a
kóddal együtt meg kell tartani, ezért maradt a mappájában.
