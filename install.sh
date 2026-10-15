#!/usr/bin/env bash
set -Eeuo pipefail

cd "$(dirname "$(readlink -f "$0")")"

echo "=== CareLog-asennus: Linux ==="

if ! command -v sudo >/dev/null 2>&1; then
    echo "Virhe: sudo-komentoa ei löydy."
    exit 1
fi

if ! command -v apt-get >/dev/null 2>&1; then
    echo "Virhe: tämä asennusskripti tukee Ubuntu/Debian-järjestelmiä."
    exit 1
fi

if ! dpkg -s mysql-server >/dev/null 2>&1; then
    echo "Asennetaan MySQL Server..."
    sudo apt-get update
    sudo apt-get install -y mysql-server
fi

echo "Käynnistetään MySQL-palvelu..."

if command -v systemctl >/dev/null 2>&1; then
    sudo systemctl enable --now mysql \
        || sudo service mysql start
else
    sudo service mysql start
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Asennetaan Python..."
    sudo apt-get install -y python3
fi

if ! python3 -m venv --help >/dev/null 2>&1; then
    echo "Asennetaan Pythonin virtuaaliympäristötyökalut..."
    sudo apt-get install -y python3-venv python3-pip
fi

if [ ! -f requirements.txt ]; then
    echo "Virhe: requirements.txt puuttuu."
    exit 1
fi

if [ ! -f create_database.py ]; then
    echo "Virhe: create_database.py puuttuu."
    exit 1
fi

if [ ! -d .venv ]; then
    echo "Luodaan Python-virtuaaliympäristö..."
    python3 -m venv .venv
fi

echo "Asennetaan Python-riippuvuudet..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "Alustetaan CareLogin tietokanta..."
.venv/bin/python create_database.py

echo
echo "CareLogin asennus on valmis."