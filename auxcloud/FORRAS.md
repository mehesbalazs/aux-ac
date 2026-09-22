# A kiemelt kód forrása

- Projekt: https://github.com/maeek/ha-aux-cloud (MIT licenc, lásd `LICENSE`)
- Verzió: `V2.0.0` tag, commit `85ae111e77e92edd1b104b55a57f81ebe4c75cab` (2026-09-13)
- Átvett fájlok változtatás nélkül, a `custom_components/aux_cloud/` alól:
  `api/`, `dna/`, `devices.py`, `device_metadata.py`
- Saját fájl: az `__init__.py` (csak egy docstring, kód nélkül). Az eredeti
  Home Assistantot importál, ezért nem került át. Az `api/__init__.py` és a
  `dna/__init__.py` viszont az eredeti, változtatás nélkül.

Ezek a fájlok a projekt saját tesztje (`tests/test_architecture.py`) szerint sem
importálnak Home Assistantot. Függőségeik: `aiohttp` és `pycryptodome`.

Frissítéshez az újabb tagből másold át ugyanezeket a fájlokat, és frissítsd
ezt a leírást. Előtte érdemes átnézni a változásokat, mert a kód a jelszóval
jelentkezik be.
