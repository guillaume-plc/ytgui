"""
A simple app to download youtube videos using the pytube module and wxWidgets for the GUI.
"""

import time
import json
from threading import Thread, Lock
from os import path
import wx
from pytube import YouTube, exceptions

class MainFrame(wx.Frame):
    """The main app window."""
    def __init__(self):
        super().__init__(parent=None, title='ytgui')

        ## Initialize the frame attributes.
        # Directory of the current file
        self.basepath = path.dirname(__file__)
        # Absolute path to the settings file
        self.settings_path = path.abspath(path.join(self.basepath, "settings.json"))
        # The directory to download files to
        self.save_path = ""
        # Wether a directory should be created if the save path is not a valid directory
        self.create_dir = False
        # The YouTube object
        self.youtube = None
        # The video object
        self.video = None
        # Mutex for the downloading thread
        self.downloading = Lock()

        # Load default settings
        self.load_settings()

        # Initialize the UI
        self.init_ui()
        # Load the icon
        self.SetIcon(wx.Icon(path.abspath(path.join(self.basepath, "icon.ico"))))
        self.Show()

    def load_settings(self):
        """Loads the settings file."""
        with open(self.settings_path, "r") as file:
            settings = json.load(file)
            self.save_path = settings["save_path"]
            self.create_dir = settings["create_dir"]

    def update_settings(self, key: str, value: str):
        """Updates the settings file."""
        settings = {}
        with open(self.settings_path, "r") as file:
            settings = json.load(file)
        settings[key] = value
        with open(self.settings_path, "w") as file:
            json.dump(settings, file, indent=4)

    def init_ui(self):
        """Initializes the UI of the app."""
        panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(3, 5, 5)
        h_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Setting up inputs
        url_label = wx.StaticText(panel, label="URL :")
        self.url_input = wx.TextCtrl(panel, size=(300,-1))
        save_label = wx.StaticText(panel, label="Save to :")
        self.save_input = wx.TextCtrl(panel, value=self.save_path, style=wx.TE_PROCESS_ENTER)
        self.save_input.Bind(wx.EVT_TEXT_ENTER, self.on_save_input)
        self.browse_btn = wx.Button(panel, label="Browse")
        self.browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        empty_cell = (0,0)

        grid.AddMany([(url_label), (self.url_input, 1, wx.EXPAND), (empty_cell),
                    (save_label), (self.save_input, 1, wx.EXPAND), (self.browse_btn)])
        grid.AddGrowableCol(1, 1)
        main_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 10)

        # Main load button.
        self.load_btn = wx.Button(panel, label='Load video')
        self.load_btn.Bind(wx.EVT_BUTTON, self.on_load)
        # Progress bar
        self.progress_bar = wx.Gauge(panel, range=100)

        h_sizer.Add(self.load_btn, 0, wx.ALL, 5)
        h_sizer.Add(self.progress_bar, -1, wx.ALL | wx.EXPAND, 5)
        main_sizer.Add(h_sizer, 0, wx.ALL | wx.EXPAND, 5)

        # Setting up the status bar
        self.status_bar = self.CreateStatusBar(style=wx.BORDER_NONE)
        self.status_bar.SetStatusStyles([wx.SB_FLAT])

        # Setting up the menu.
        menu = wx.Menu()
        menu.Append(wx.ID_ABOUT, "&About"," A simple GUI to quickly download YouTube videos.")
        self.create_dir_menu = menu.Append(wx.ID_APPLY, "Create directory", " Create a directory if the specified one doesn't exist", kind = wx.ITEM_CHECK)
        menu.AppendSeparator()
        menu_exit = menu.Append(wx.ID_EXIT,"&Quit\tCtrl+Q"," Terminate the program")
        self.create_dir_menu.Check(self.create_dir)
        self.Bind(wx.EVT_MENU, self.on_exit, menu_exit)
        self.Bind(wx.EVT_MENU, self.on_create_dir, self.create_dir_menu)

        # Creating the menubar.
        menu_bar = wx.MenuBar()
        menu_bar.Append(menu,"&Menu") # Adding the "filemenu" to the MenuBar
        self.SetMenuBar(menu_bar)  # Adding the MenuBar to the Frame content.

        panel.SetSizerAndFit(main_sizer)
        self.Fit()
        self.SetMinSize(self.GetSize())

    def on_create_dir(self, event):
        """Updates the create_dir setting on change"""
        del event
        self.create_dir = not self.create_dir
        self.update_settings("create_dir", self.create_dir)        

    def on_save_input(self, event):
        """Updates the save_dir setting on input"""
        del event
        value = self.save_input.GetValue()
        if (path.isdir(value)):
            self.save_path = value
            self.update_settings("save_path", value)
            self.SetStatusText(f" Save path set to {self.save_path}")
            self.load_btn.SetFocus()
        elif self.create_dir:
            self.save_path = value
            self.SetStatusText(f" A new directory will be created: {value}.")
        else:
            self.SetStatusText(f" Unkown directory: {value}")

    def on_load(self, event):
        """Attempts to load the requested URL"""
        del event
        value = self.url_input.GetValue()
        if not value:
            self.SetStatusText(" You didn't enter anything!")
        if (not self.create_dir) and (not path.isdir(self.save_path)):
            self.SetStatusText(f" Invalid save path: {self.save_path} is not a directory")
        else:
            if self.downloading.locked():
                self.SetStatusText(' A video is already loading')
            else:
                download_thread = Thread(target=self.download_video, args=(value,), daemon=True)
                download_thread.start()

    def on_browse(self, event):
        """Browse for a directory."""
        del event
        dlg = wx.DirDialog(self, "Choose a directory:",
                          style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST)
        if dlg.ShowModal() == wx.ID_OK:
            self.save_path = dlg.GetPath()
            self.save_input.SetValue(self.save_path)
            self.update_settings("save_path", self.save_path)
            self.SetStatusText(f" Save path set to {self.save_path}")
        dlg.Destroy()

    def on_exit(self, event):
        """Closes the window."""
        del event
        self.Close()

    def progress_callback(self, stream, chunk, bytes_remaining):
        """Updates the progress bar."""
        del stream, chunk
        size = self.video.filesize
        self.progress_bar.SetValue(int((1 - float(bytes_remaining)/size) * 100))

    def complete_callback(self, stream, filepath):
        """Updates the progress bar and status after a file has been downloaded."""
        del stream
        self.SetStatusText(f" File downloaded to {filepath}")
        self.progress_bar.SetValue(100)
        time.sleep(.75) # Slight delay because its prettier
        self.progress_bar.SetValue(0)

    def download_video(self, url):
        """Downloads the YouTube video at the requested url."""
        self.downloading.acquire()
        try:
            self.SetStatusText(" Processing URL")
            self.youtube = YouTube(url, on_progress_callback=self.progress_callback, on_complete_callback=self.complete_callback)
            self.SetStatusText(f' Loading "{self.youtube.title}"')
            self.video = self.youtube.streams.filter(progressive=True, file_extension='mp4').first()
            self.video.download(self.save_path)
        except exceptions.RegexMatchError:
            self.SetStatusText(f" The Regex pattern did not return any match for the video : {url}")
        except (exceptions.VideoUnavailable, exceptions.VideoPrivate):
            self.SetStatusText(" The video is unavailable or private.")
        except exceptions.HTMLParseError:
            self.SetStatusText(" The HTML could not be parsed.")
        except exceptions.PytubeError as e:
            self.SetStatusText(f" Download failed: {e}")
        except KeyError as e:
            self.SetStatusText(f" Key Error: {e}. The provided url is probably invalid.")
        finally:
            self.downloading.release()
        return True

if __name__ == '__main__':
    app = wx.App()
    frame = MainFrame()
    app.MainLoop()
