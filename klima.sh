#!/bin/zsh
# Burkoló az iOS Parancsok appnak — SSH-n hívva egyetlen olvasható sort ad vissza.
#
#   klima.sh allapot
#   klima.sh be                    # az utolsó beállításokkal kapcsol be
#   klima.sh be 23                 # bekapcsol, 23 fokra
#   klima.sh be 23 hutes           # … hűtés módban
#   klima.sh be 23 hutes csendes   # … csendes ventilátorral
#   klima.sh ki
#   klima.sh hofok 22.5
#   klima.sh mod futes
#   klima.sh vent auto
#   klima.sh be 23 proba           # próbamenet: semmi nem megy el
#
# A "be" után a szám a hőfok, az első szó az üzemmód, a második a ventilátor.
# A próbamenet szava bárhol állhat: proba, próba, Proba, --proba.
#
# Amit NEM ért, azt nem dobja el csendben, hanem 64-es kóddal visszautasítja:
# egy félreértett szó (pl. "Próba") különben élesben ment volna ki.

set -u

# A napló a készülék nevét és a teljes előzményt tartalmazza — ne legyen
# olvasható a gép többi felhasználójának.
umask 077

# A script saját könyvtára, így a projekt bárhova áthelyezhető.
MAPPA="${0:A:h}"
[[ -f "$MAPPA/config.sh" ]] && source "$MAPPA/config.sh"

PYTHON="$MAPPA/.venv/bin/python"
NAPLOFAJL="$MAPPA/klima.log"

if [[ -z "${AUX_EMAIL:-}" ]]; then
  echo "Hiányzik az AUX_EMAIL. Futtasd egyszer terminálból: $MAPPA/jelszo_beallitas.sh"
  exit 66
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "Hiba: nincs meg a Python környezet ($PYTHON)"; exit 65
fi

# A napló nem nőhet a végtelenségig (minden koppintás ír bele).
if [[ -f "$NAPLOFAJL" ]] && (( $(stat -f%z "$NAPLOFAJL") > 262144 )); then
  tail -n 2000 "$NAPLOFAJL" > "$NAPLOFAJL.uj" && mv "$NAPLOFAJL.uj" "$NAPLOFAJL"
fi
# Már itt naplózunk, az argumentumok értelmezése ELŐTT: a visszautasított
# parancs (64) különben nyomtalanul maradna, pedig épp azt kell megérteni.
echo "=== $(date '+%Y-%m-%d %H:%M:%S')  parancs=${(j: :)@}" >> "$NAPLOFAJL" 2>/dev/null

hiba() { echo "--- kod=64 $1" >> "$NAPLOFAJL" 2>/dev/null; echo "$1"; exit 64 }

# --- argumentumok szétválogatása -------------------------------------------
KAPCSOLOK=()
SZAVAK=()
for a in "$@"; do
  case "${(L)a}" in
    proba|próba|--proba|--próba) KAPCSOLOK+=(--proba) ;;
    -*) hiba "Ez a szó nem használható itt: '$a'. Használható: allapot, be [hőfok] [mód] [ventilátor], ki, hofok N, mod M, vent V" ;;
    *) [[ -n "$a" ]] && SZAVAK+=("$a") ;;
  esac
done

# Ismeretlen termékazonosítójú klímához a config.sh-ból is kérhető.
[[ "${KLIMA_SZABVANYOS_PROFIL:-}" == "1" ]] && KAPCSOLOK+=(--szabvanyos-profil)

PARANCS="${SZAVAK[1]:-}"
TOBBI=("${(@)SZAVAK[2,-1]}")
PY=("$PARANCS")

case "$PARANCS" in
  allapot|ki)
    (( ${#TOBBI} == 0 )) || hiba "A(z) '$PARANCS' parancs nem kér értéket, ezt kaptam: ${TOBBI[*]}" ;;
  hofok|mod|vent)
    (( ${#TOBBI} == 1 )) || hiba "A(z) '$PARANCS' parancs pontosan egy értéket kér, ezt kaptam: ${TOBBI[*]:-semmit}"
    PY+=("${TOBBI[1]}") ;;
  be)
    # A hőfoknak közvetlenül a "be" után kell állnia (argparse), ezért a
    # kapcsolókat külön gyűjtjük, és a végére tesszük.
    OPCIOK=()
    HOFOK=""
    for a in "${(@)TOBBI}"; do
      if [[ "$a" =~ '^[0-9]+([.,][0-9]+)?$' ]]; then
        [[ -z "$HOFOK" ]] || hiba "Egy hőfokot adj meg, ne többet: $HOFOK és $a"
        HOFOK="$a"
      elif (( ! ${OPCIOK[(I)--mod]} )); then
        OPCIOK+=(--mod "$a")
      elif (( ! ${OPCIOK[(I)--vent]} )); then
        OPCIOK+=(--vent "$a")
      else
        hiba "Túl sok szó a 'be' után: '$a'. Így használd: be [hőfok] [mód] [ventilátor]"
      fi
    done
    [[ -n "$HOFOK" ]] && PY+=("$HOFOK")
    (( ${#OPCIOK} )) && PY+=("${OPCIOK[@]}") ;;
  *)
    hiba "Ismeretlen parancs: '${PARANCS}'. Használható: allapot, be [hőfok] [mód] [ventilátor], ki, hofok N, mod M, vent V" ;;
esac

# --- futtatás ---------------------------------------------------------------
HIBAFAJL="$(mktemp -t klima)"
KIMENET="$("$PYTHON" "$MAPPA/klima.py" "${PY[@]}" "${KAPCSOLOK[@]}" 2>"$HIBAFAJL")"
KOD=$?
NAPLO="$(<"$HIBAFAJL")"
rm -f "$HIBAFAJL"

{
  echo "--- kod=$KOD"
  echo "$NAPLO"
  [[ -n "$KIMENET" ]] && echo "-> $KIMENET"
} >> "$NAPLOFAJL" 2>/dev/null

# A részletes indoklást a Python írja a stderr-re; ebből emeljük ki a lényeget.
INDOK="$(echo "$NAPLO" | grep -E "HIBA|FIGYELEM" | head -2 | sed 's/^ *//; s/^HIBA: //' | tr '\n' ' ')"
# Ha semmi nem illeszkedett (pl. traceback), inkább az utolsó sort mutassuk,
# mint hogy a telefon indoklás nélkül maradjon.
[[ -z "${INDOK// /}" ]] && INDOK="$(echo "$NAPLO" | grep -v '^[[:space:]]*$' | tail -1 | sed 's/^ *//')"

case $KOD in
  0)  echo "$KIMENET" ;;
  1)  echo "Nem sikerült — bejelentkezési hiba, vagy nincs meg a klíma. $INDOK" ;;
  2)  echo "A klíma offline, nincs kapcsolata a felhővel (áram, wifi?). Semmi nem ment el." ;;
  3)  echo "Nem érem el az AUX felhőt, vagy hiányosan válaszolt — semmi nem ment el. $INDOK" ;;
  4)  echo "A klíma elutasította a parancsot, nem állt át. $INDOK" ;;
  5)  echo "Elküldve, de a klíma mást mutat — nézd meg az appban. $INDOK" ;;
  6)  echo "Nem a várt klíma válaszolt (MAC-eltérés) — semmi nem ment el." ;;
  7)  echo "BIZONYTALAN — nem derült ki, átment-e. Ellenőrizd, mielőtt újrapróbálnád! $INDOK" ;;
  8)  echo "Túl sűrű kérések — várj egy percet, és próbáld újra." ;;
  9)  echo "Időtúllépés a felhővel — semmi nem ment el. Próbáld újra." ;;
  64) echo "Hibás parancs: $INDOK" ;;
  65) echo "Hiányzik a Python környezet vagy egy csomag a Macen. $INDOK" ;;
  66) echo "Hiányzik az AUX_EMAIL a config.sh-ból a Macen." ;;
  70) echo "Váratlan hiba a scriptben. $INDOK" ;;
  *)  echo "Ismeretlen hiba (kód $KOD). $INDOK" ;;
esac

exit $KOD
