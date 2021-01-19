"""
A simple app to download youtube videos using the pytube module and wxWidgets for the GUI.
"""

import time
import json
import os
import re
import subprocess
from threading import Thread, Lock

import wx
from pytube import YouTube, exceptions
import ffmpeg

class MainFrame(wx.Frame):
    """The main app window."""
    def __init__(self):
        super().__init__(parent=None, title='ytgui')

        ## Initialize the app settings
        # Directory of the current file
        self.basepath = os.path.dirname(__file__)
        # Absolute path to the settings file
        self.settings_path = os.path.abspath(os.path.join(self.basepath, "settings.json"))
        # The directory to download files to
        self.save_path = ""
        # Wether a directory should be created if the save path is not a valid directory
        self.create_dir = False
        
        # Load default settings
        self.load_settings()

        ## Initialize the stream variables
        # The YouTube object
        self.youtube = None
        # The streams associated with the object
        self.streams = []
        # The filtered video streams
        self.vstreams = []
        # The audio streams associated with the object
        self.astreams = []
        # The selected video stream object
        self.video = None
        # The selected audio object
        self.audio = None
        # Wether to use progressive stream
        self.is_progressive = True
        # Mutex for the url loading and video downloading threads
        self.loading = Lock()

        ## Initialize the UI
        self.init_ui()
        # Load the icon
        self.SetIcon(wx.Icon(os.path.abspath(os.path.join(self.basepath, "icon.ico"))))
        # Show the GUI
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
        self.url_input = wx.TextCtrl(panel, size=(300,-1), style=wx.TE_PROCESS_ENTER)
        self.url_input.Bind(wx.EVT_TEXT_ENTER, self.on_url_input)
        self.load_btn = wx.Button(panel, label="Load")
        self.load_btn.Bind(wx.EVT_BUTTON, self.on_url_input)

        save_label = wx.StaticText(panel, label="Save to :")
        self.save_input = wx.TextCtrl(panel, value=self.save_path, style=wx.TE_PROCESS_ENTER)
        self.save_input.Bind(wx.EVT_TEXT_ENTER, self.on_save_input)
        
        self.browse_btn = wx.Button(panel, label="Browse")
        self.browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        
        res_label = wx.StaticText(panel, label="Resolution :")
        self.res_input = wx.Choice(panel, choices=["Enter a valid URL"])
        self.res_input.SetSelection(0)
        self.res_input.Disable()

        bitrate_label = wx.StaticText(panel, label="Bitrate :")
        self.bitrate_input = wx.Choice(panel, choices=["Enter a valid URL"])
        self.bitrate_input.SetSelection(0)
        self.bitrate_input.Disable()

        type_label = wx.StaticText(panel, label="Stream type :")
        type_input = wx.BoxSizer(wx.HORIZONTAL)
        self.progressive = wx.RadioButton(panel, label="progressive", style=wx.RB_GROUP)
        self.adaptive = wx.RadioButton(panel, label="adaptive")
        type_input.Add(self.progressive, 0, wx.ALL)
        type_input.Add(self.adaptive, 0, wx.ALL)
        self.progressive.Bind(wx.EVT_RADIOBUTTON, self.on_type_input)
        self.adaptive.Bind(wx.EVT_RADIOBUTTON, self.on_type_input)
        
        empty_cell = (0,0)

        grid.AddMany([(url_label), (self.url_input, 1, wx.EXPAND), (self.load_btn),
                    (save_label), (self.save_input, 1, wx.EXPAND), (self.browse_btn),
                    (res_label), (self.res_input, 1, wx.EXPAND), (empty_cell),
                    (bitrate_label), (self.bitrate_input, 1, wx.EXPAND), (empty_cell),
                    (type_label), (type_input, 1, wx.EXPAND), (empty_cell)])
        grid.AddGrowableCol(1, 1)
        main_sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 10)

        # Main load button.
        self.download_btn = wx.Button(panel, label='Download')
        self.download_btn.Bind(wx.EVT_BUTTON, self.on_download)
        # Progress bar
        self.progress_bar = wx.Gauge(panel, range=100)

        h_sizer.Add(self.download_btn, 0, wx.ALL, 5)
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
        if os.path.isdir(value):
            self.save_path = value
            self.update_settings("save_path", value)
            self.SetStatusText(f" Save path set to {self.save_path}")
            self.download_btn.SetFocus()
        elif self.create_dir:
            self.save_path = value
            self.SetStatusText(f" A new directory will be created: {value}.")
        else:
            self.SetStatusText(f" Unkown directory: {value}")

    def on_url_input(self, event):
        """Loads the available streams on url input"""
        del event
        url = self.url_input.GetValue()
        if url:
            if self.loading.locked():
                self.SetStatusText(" A video or URL is already loading")
            else:
                load_thread = Thread(target=self.load_url, args=(url,), daemon=True)
                load_thread.start()
        else:
            self.SetStatusText(" You didn't enter anything !")
            self.url_input.SetFocus()

    def on_type_input(self, event):
        """Re-filter the currently loaded streams to match the requested stream type"""
        if self.streams: # only apply a filter if a URL has been loaded
            self.update_stream_type()
            self.vstreams = self.streams.filter(type="video", file_extension="mp4", progressive=self.is_progressive, adaptive=not self.is_progressive).order_by("resolution").desc()
            self.res_input.Clear()
            self.res_input.AppendItems([e.resolution for e in self.vstreams])
            self.res_input.Select(0)
            self.SetStatusText(f" Loaded {self.youtube.title}")

    def update_stream_type(self):
        self.is_progressive = self.progressive.GetValue()
        if self.is_progressive:
            self.bitrate_input.Disable()
        elif self.streams:
            self.bitrate_input.Enable()

    def load_url(self, url):
        """Loads a specified URL (retrieves available streams)"""
        self.loading.acquire()
        try:
            self.SetStatusText(" Processing URL")
            self.progressive.Disable()
            self.adaptive.Disable()
            self.update_stream_type()
            self.youtube = YouTube(url, on_progress_callback=self.progress_callback, on_complete_callback=self.complete_callback)
            self.streams = self.youtube.streams
            self.vstreams = self.streams.filter(type="video", file_extension="mp4", progressive=self.is_progressive, adaptive=not self.is_progressive).order_by("resolution").desc()
            self.astreams = self.streams.filter(only_audio=True).order_by("abr").desc()

            self.res_input.Clear()
            self.res_input.AppendItems([e.resolution for e in self.vstreams])
            self.res_input.Select(0)
            self.res_input.Enable()

            self.bitrate_input.Clear()
            self.bitrate_input.AppendItems([str(e.abr) + " - " + str(e.subtype) for e in self.astreams])
            self.bitrate_input.Select(0)
            if not self.is_progressive: self.bitrate_input.Enable()

            self.progressive.Enable()
            self.adaptive.Enable()
            self.SetStatusText(f" Loaded {self.youtube.title}")

        except exceptions.RegexMatchError:
            self.SetStatusText(f" The Regex pattern did not return any match for the video : {url}")
        except (exceptions.VideoUnavailable, exceptions.VideoPrivate):
            self.SetStatusText(" The video is unavailable or private.")
        except exceptions.HTMLParseError:
            self.SetStatusText(" The HTML could not be parsed.")
        except exceptions.PytubeError as e:
            self.SetStatusText(f" Faild to load URL: {e}")
        except KeyError as e:
            self.SetStatusText(f" Key Error: {e}. The provided URL is probably invalid.")
        
        finally:
            self.loading.release()
        
        return True

    def on_download(self, event):
        """Attempts to load the requested URL"""
        del event
        value = self.url_input.GetValue()
        if not value:
            self.SetStatusText(" You didn't enter anything!")
        if (not self.create_dir) and (not os.path.isdir(self.save_path)):
            self.SetStatusText(f" Invalid save path: {self.save_path} is not a directory")
        else:
            if self.loading.locked():
                self.SetStatusText(' A video or URL is already loading')
            elif self.streams:
                download_thread = Thread(target=self.download_video, args=(value,), daemon=True)
                download_thread.start()
            else:
                self.SetStatusText(' Please load the URL data before downloading')

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
    
    def ffmpeg_progress_callback(self, time_elapsed, duration):
        self.progress_bar.SetValue(int((float(time_elapsed)/duration) * 100))

    def ffmpeg_merge(self, audio_path, video_path, outpath):
        audio = ffmpeg.input(audio_path).audio
        video = ffmpeg.input(video_path).video
        duration = self.get_merge_duration(video_path)

        # Startupinfo to hide console on Windows
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        process = subprocess.Popen(
            (ffmpeg
                .output(audio, video, outpath, vcodec="copy")
                .global_args("-hide_banner")
                .overwrite_output()
                .compile()
            ),
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
        )
            
        """
        Hacky parsing of ffmpeg's stderr to retrieve the time information.
        The use of carriage returns (\r) in ffmpeg's output prevents us from
        directely using readline(), so we read some bytes, and if we don't get a
        regex match for the time string we keep the data to append it to the next
        read. The number of bytes read each time is purely empirical, and might
        be suboptimal for large videos (because more frames means longer lines...)
        
        Another solution would be to use sockets along with the -process option
        of ffmpeg, but older versions of windows do not support AF_UNIX sockets,
        so we would have to use TCP and trigger a Windows firewall warning,
        which is fine, but looks shady.
        """
        
        p = re.compile('time=\d+:\d+:\d+\.\d+') # The time info we are looking for
        last_time = 0
        last_data = ""
        while True:
            
            in_bytes = process.stderr.read(128)
            if not in_bytes:
                break
            data = last_data + in_bytes.decode("utf-8").replace("\r", "")
            
           
            match = []
            for m in p.finditer(data):
                match.append(m)

            if match:
                timestr = match[-1].group()[5:]
                factor = [3600, 60, 1] # Hours, Minutes, Seconds
                out_time = sum([a*b for a,b in zip(factor, map(float, timestr.split(':')))]) # Time in seconds           
                if out_time - last_time > 1:
                    
                    Thread(target=self.ffmpeg_progress_callback, args=[out_time, duration]).start()
                    
                    last_time = out_time
                last_data = data[match[-1].end():] # Keep the remaining unmatched data
            else:
                last_data = data
           
        process.wait()
        return True
    
    def get_merge_duration(self, video_path):
        duration = 0.0
        probe = ffmpeg.probe(video_path)
        if 'format' in probe:
            if 'duration' in probe['format']:
                duration = float(probe['format']['duration'])
        return duration

    def complete_callback(self, stream, filepath):
        """Updates the progress bar and status after a file has been downloaded."""
        del stream
        self.SetStatusText(f" File downloaded to {filepath}")
        self.progress_bar.SetValue(100)
        time.sleep(.75) # Slight delay because its prettier
        self.progress_bar.SetValue(0)

    def download_video(self, url):
        """Downloads the YouTube video at the requested url."""
        self.loading.acquire()
        try:
            self.SetStatusText(f' Downloading video')
            self.video = self.vstreams[self.res_input.GetSelection()]
            video_prefix = ""
            if not self.is_progressive:
                video_prefix = "video_"
            self.video.download(self.save_path, filename_prefix=video_prefix)
            if not self.is_progressive:
                self.SetStatusText(" Downloading audio")
                self.audio = self.astreams[self.bitrate_input.GetSelection()]
                self.audio.download(self.save_path, filename_prefix="audio_")
                self.SetStatusText(" Merging audio and video ...")
                audio_path = os.path.join(self.save_path, "audio_" + self.audio.default_filename)
                video_path = os.path.join(self.save_path, "video_" + self.video.default_filename)
                outpath = os.path.join(self.save_path, self.video.default_filename)

                self.ffmpeg_merge(audio_path, video_path, outpath)
                os.remove(video_path)
                os.remove(audio_path)
                self.complete_callback(None, outpath)
                # self.SetStatusText(f" Audio and video merged at {outpath}")
        
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
            self.loading.release()
        return True

if __name__ == '__main__':
    app = wx.App()
    frame = MainFrame()
    app.MainLoop()
