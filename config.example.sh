# Saját beállítások — MINTA
#
# Másold `config.sh` néven, és töltsd ki a saját adataiddal:
#     cp config.example.sh config.sh
# (A jelszo_beallitas.sh ezt meg is csinálja helyetted.)
#
# A config.sh verziókövetésen kívül van (lásd .gitignore), a minta viszont
# a repóban marad. A formátum szándékosan egyszerű: a klima.sh source-olja,
# a Python scriptek pedig kiolvassák belőle az export sorokat.

# Az AC Freedom fiók e-mail címe — ugyanaz, mint a mobilappban.
export AUX_EMAIL="pelda@example.com"

# A felhő régiója: eu (Európa), usa („Other Areas”), cn vagy rus.
# Ugyanaz kell, amit az AC Freedom app a belépésnél mutat.
export AUX_REGIO="eu"

# A klíma neve az appban. Csak akkor kell, ha a fiókban több készülék van.
export KLIMA_NEV=""

# A klíma wifi-moduljának MAC-címe. A vezérlő ezzel veti össze, hogy tényleg a
# te klímád válaszol-e, mielőtt bármit küldene. Üresen hagyva ez az
# ellenőrzés kimarad. Honnan tudod meg: a lekerdez.py kiírja.
export KLIMA_MAC=""

# Ha a lekerdez.py szerint a klíma termékazonosítója ISMERETLEN, ezzel kérheted,
# hogy a szabványos AUX klímaprofillal próbálkozzon (a telefonról is).
export KLIMA_SZABVANYOS_PROFIL="0"

# A Mac SSH-elérése, amire a telefonos Parancsok csatlakoznak.
# Csak akkor kell, ha a parancs_keszito.py-val generálsz parancsfájlokat.
# Üresen hagyva a parancs_keszito.py beszédes hibát ad — töltsd ki előtte.
export SSH_HOST=""
export SSH_PORT="22"
export SSH_USER=""
