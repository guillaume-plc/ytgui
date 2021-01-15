# ytgui

A simple GUI to quickly download youtube videos.

## Usage

- Install the required packages : `pip install -r requirements.txt`
- Then run the main script in /src : `python app.py`

## Releases

The app can be bundled into an executable using pyinstaller:

`pip install pyinstaller`

`pyinstaller -n ytgui --add-data "src/settings.json;." --add-data "src/icon.ico;." --icon "src/icon.ico" src/app.py`

The dist folder contains a bundled version for windows (64 bit).
