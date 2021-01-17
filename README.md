# ytgui

A simple GUI to quickly download youtube videos.

## Usage

### As a python program

- Install the required packages : `pip install -r requirements.txt`
- Then run the main script in /src : `python src/app.py`

### As an executable

The app can be bundled into an executable using pyinstaller (after installing the required packages):

- Install pyinstaller: `pip install pyinstaller`

- Then from the main directory run: 
`pyinstaller -n ytgui --add-data "src/settings.json;." --add-data "src/icon.ico;." --icon "src/icon.ico" --noconsole src/app.py`
(The executable will be placed in the dist/ytgui folder, along with necessary files and dlls)

The dist folder contains a bundled version for windows (64 bit).
