"""
A simple app to download youtube videos using the pytube module and wxWidgets for the GUI.
"""

import time
import json
import os
import sys
import re
import subprocess
from threading import Thread, Lock

import wx
from wx.dataview import DataViewListCtrl
from wx.lib.mixins.listctrl import ListCtrlAutoWidthMixin, TextEditMixin
from pytube import YouTube, exceptions
import ffmpeg

def filesize_to_string(size: int):
    """Convert a filesize in bytes to a human readable string"""
    if size > 1000000000:
        return f"{float(size/1000000000):.2f} GB"
    elif size > 1000000:
        return f"{float(size/1000000):.2f} MB"
    else:
        return f"{float(size/1000):.2f} kB"

class AutoListCtrl(wx.ListCtrl, ListCtrlAutoWidthMixin, TextEditMixin):
    """A wxWidgets ListCtrl with auto width."""
    def __init__(self, parent, ID, pos=wx.DefaultPosition,
                 size=wx.DefaultSize, style=0):
        wx.ListCtrl.__init__(self, parent, ID, pos, size, style)
        ListCtrlAutoWidthMixin.__init__(self)
        TextEditMixin.__init__(self)

class VideoData():
    """An object storing the state of a loaded video url (available streams and selected parameters)"""
    
    def __init__(self, is_progressive, only_audio):
        # GUI parameters
        self.id = id(self)  # Unique ID
        self.row = -1  # Current row in the queue view
        self.loaded = False  # True if the url was succesfully loaded
        self.error = False  # True if the url failed to load
        self.downloading = False  # True if the video is currently downloading
        self.completed = False  # True if the download has completed
        
        # Download thread parameters
        self.thread = None  # The current download thread for this video
        self.exit = False  # True if the user has requested to delete the item from the queue while it was downloading
        self.stream = None  # The currently downloading stream for this video
        
        # User interaction
        self.custom_filename = ""  # Optional user defined filename
        self.is_progressive = is_progressive  # True if the selected stream is progressive
        self.only_audio = only_audio  # True if the user has chosen to download only audio
        self.selected_astream = 0  # Index of the selected audio stream
        self.selected_vstream = 0  # Index of the selected video stream

        # Data
        self.youtube = None
        self.streams = []
        self.astreams = []
        self.vstreams = []
        """ self.youtube = youtube  # The youutbe object
        self.streams = self.youtube.streams  # The list of available streams
        self.vstreams = self.streams.filter(type="video", file_extension="mp4", progressive=self.is_progressive, adaptive=not self.is_progressive).order_by("resolution").desc()  # The filtered video streams
        self.astreams = self.streams.filter(only_audio=self.only_audio, file_extension="mp4").order_by("abr").desc()  # The filtered audio streams  """

    def set_data(self, youtube):
        self.youtube = youtube  # The youutbe object
        self.streams = self.youtube.streams  # The list of available streams
        self.vstreams = self.streams.filter(type="video", file_extension="mp4", progressive=self.is_progressive, adaptive=not self.is_progressive).order_by("resolution").desc()  # The filtered video streams
        self.astreams = self.streams.filter(only_audio=self.only_audio, file_extension="mp4").order_by("abr").desc()  # The filtered audio streams 

    def update_stream_type(self, is_progressive):
        """Re-filter the list of streams when the user changes the type of stream (progressive/adaptive)"""
        if self.is_progressive != is_progressive:
            self.selected_vstream = 0
        self.is_progressive = is_progressive
        self.vstreams = self.streams.filter(type="video", file_extension="mp4", progressive=self.is_progressive, adaptive=not self.is_progressive).order_by("resolution").desc()

    def get_filesize(self):
        """Compute the size of the file for the selected stream, in bytes"""
        if self.only_audio:
            return self.astreams[self.selected_astream].filesize
        elif self.is_progressive:
            return self.vstreams[self.selected_vstream].filesize
        else:
            return self.vstreams[self.selected_vstream].filesize + self.astreams[self.selected_astream].filesize

    def request_exit(self):
        """Kill the downloading thread associated with this video"""
        if not self.thread is None:
            self.exit = True
            if self.stream.user_data:
                self.stream.user_data["exit"] = True
            self.thread.join()

class MainPanel(wx.Panel):
    """The main app window."""
    def __init__(self, parent):
        wx.Panel.__init__(self, parent)
        self.frame = parent  # Application main frame

        ## Initialize the app settings
        # Directory of the current file
        self.basepath = os.path.dirname(__file__)
        # Absolute path to the settings file
        self.settings_path = os.path.abspath(os.path.join(self.basepath, "settings.json"))
        # The directory to download files to
        self.save_path = ""
        # Wether a directory should be created if the save path is not a valid directory
        self.create_dir = False
        # Download only audio
        self.only_audio = False
        # Convert file to mp3 when saving as audio only
        self.convert_audio = True

        # Load default settings
        self.only_audio_default = False
        self.is_progressive_default = True
        self.load_settings()

        ## Initialize the stream variables
        # The selected video stream object
        self.video = None
        # The selected audio object
        self.audio = None
        # Mutex for the url loading and video downloading threads
        self.loading = Lock()
        # Mutex for deleting items
        self.deleting = Lock()
        
        # VideoData item queue
        self.queue = []
        # Currently selected item in the queue
        self.selected = -1

        ## Initialize the UI
        self.init_ui()

    def load_settings(self):
        """Loads the settings file."""
        with open(self.settings_path, "r") as file:
            settings = json.load(file)
            self.save_path = settings["save_path"]
            self.create_dir = settings["create_dir"]
            self.convert_audio = settings["convert_audio"]
            self.only_audio_default = settings["only_audio"]
            self.is_progressive_default = settings["progressive_stream"]

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
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(3, 5, 5)

        # URL input
        url_label = wx.StaticText(self, label="URL :")
        self.url_input = wx.TextCtrl(self, size=(540,-1), style=wx.TE_PROCESS_ENTER)
        self.url_input.Bind(wx.EVT_TEXT_ENTER, self.on_url_input)
        self.url_input.Bind(wx.EVT_TEXT_PASTE, self.on_url_paste_input)

        self.load_btn = wx.Button(self, label="Load")
        self.load_btn.Bind(wx.EVT_BUTTON, self.on_url_input)
        
        # Save directory input
        save_label = wx.StaticText(self, label="Save to :")
        self.save_input = wx.TextCtrl(self, value=self.save_path, style=wx.TE_PROCESS_ENTER)
        self.save_input.Bind(wx.EVT_TEXT_ENTER, self.on_save_input)
        
        self.browse_btn = wx.Button(self, label="Browse")
        self.browse_btn.Bind(wx.EVT_BUTTON, self.on_browse)
        
        # Download queue
        queue_label = wx.StaticText(self, label="Queue :")
        self.table = DataViewListCtrl(self, wx.ID_ANY, size=(-1, 100))
        self.table.AppendToggleColumn("#", width=20)
        self.table.AppendTextColumn("Title", width=200)
        self.table.AppendTextColumn("Size")
        self.table.AppendTextColumn("Status", width=150)
        self.table.AppendProgressColumn("Progress")
        self.table.Bind(wx.dataview.EVT_DATAVIEW_SELECTION_CHANGED, self.on_item_select)

        # Queue edit controls
        qctrls = wx.BoxSizer(wx.VERTICAL)
        delete = wx.Button(self, label="Delete selected")
        delete.Bind(wx.EVT_BUTTON, self.on_delete_items)
        clear = wx.Button(self, label="Clear completed")
        clear.Bind(wx.EVT_BUTTON, self.on_clear_completed)
        self.download_btn = wx.Button(self, label='Download')
        self.download_btn.Bind(wx.EVT_BUTTON, self.on_download)
        empty_cell = (0,0)
        qctrls.AddMany([(delete, 0, wx.BOTTOM | wx.EXPAND, 5), (clear, 0, wx.BOTTOM | wx.EXPAND, 5), (empty_cell, 1, wx.EXPAND), (self.download_btn, 0, wx.EXPAND)])
        
        # Filename edit box
        self.name_input = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.name_input.Bind(wx.EVT_TEXT_ENTER, self.on_name_input)
        self.name_input.Disable()
        name_label = wx.StaticText(self, label="Title :")
        
        # Video resolution input
        res_label = wx.StaticText(self, label="Resolution :")
        self.res_input = wx.Choice(self, choices=["Enter a valid URL"])
        self.res_input.SetSelection(0)
        self.res_input.Disable()
        self.res_input.Bind(wx.EVT_CHOICE, self.on_quality_select)

        # Audio bitrate input
        bitrate_label = wx.StaticText(self, label="Bitrate :")
        self.bitrate_input = wx.Choice(self, choices=["Enter a valid URL"])
        self.bitrate_input.SetSelection(0)
        self.bitrate_input.Disable()
        self.bitrate_input.Bind(wx.EVT_CHOICE, self.on_quality_select)

        # Stream type input
        type_label = wx.StaticText(self, label="Stream type :")
        type_input = wx.BoxSizer(wx.HORIZONTAL)
        
        self.progressive = wx.RadioButton(self, label="progressive", style=wx.RB_GROUP)
        self.adaptive = wx.RadioButton(self, label="adaptive")
        self.progressive.Bind(wx.EVT_RADIOBUTTON, self.on_type_input)
        self.adaptive.Bind(wx.EVT_RADIOBUTTON, self.on_type_input)
        
        if self.only_audio_default:
            self.progressive.Disable()
            self.adaptive.Disable()
            self.adaptive.SetValue(True)
        self.progressive.SetValue(self.is_progressive_default)
        self.adaptive.SetValue(not self.is_progressive_default)
        
        self.audio_input = wx.CheckBox(self, label="only audio")
        self.audio_input.SetValue(self.only_audio_default)
        self.audio_input.Bind(wx.EVT_CHECKBOX, self.on_audio_input)

        self.save_defaults = wx.Button(self, label="Make default")
        self.save_defaults.Bind(wx.EVT_BUTTON, self.on_save_defaults)

        type_input.Add(self.progressive, 0, wx.TOP, 5)
        type_input.Add(self.adaptive, 0, wx.TOP, 5)
        type_input.Add(self.audio_input, 0, wx.TOP, 5)
        
        # Set up grid
        grid.AddMany([
                    (url_label), (self.url_input, 1, wx.EXPAND), (self.load_btn),
                    (save_label), (self.save_input, 1, wx.EXPAND), (self.browse_btn),
                    (queue_label, 1, wx.TOP, 15), (self.table, 1, wx.TOP | wx.EXPAND, 15), (qctrls, 0, wx.TOP | wx.EXPAND, 15),
                    (name_label), (self.name_input, 1, wx.EXPAND), (empty_cell),
                    (res_label), (self.res_input, 1, wx.EXPAND), (empty_cell),
                    (bitrate_label), (self.bitrate_input, 1, wx.EXPAND), (empty_cell),
                    (type_label, 1, wx.TOP, 5), (type_input, 1, wx.EXPAND), (self.save_defaults)])
        grid.AddGrowableCol(1, 1)
        grid.AddGrowableRow(2, 1)
        self.main_sizer.Add(grid, 1, wx.ALL | wx.EXPAND, 10)

        # Status bar
        self.status_bar = self.frame.CreateStatusBar(style=wx.BORDER_NONE)
        self.status_bar.SetStatusStyles([wx.SB_FLAT])

        # Menu
        menu = wx.Menu()
        menu.Append(wx.ID_ABOUT, "&About"," A simple GUI to quickly download YouTube videos.")
        self.create_dir_menu = menu.Append(wx.ID_APPLY, "Create directory", " Create a directory if the specified one doesn't exist.", kind=wx.ITEM_CHECK)
        self.convert_audio_menu = menu.Append(wx.ID_ANY, "Convert audio", " Convert files to mp3 when saving as audio only.", kind=wx.ITEM_CHECK)
        menu.AppendSeparator()
        menu_exit = menu.Append(wx.ID_EXIT,"&Quit\tCtrl+Q"," Terminate the program")
        self.create_dir_menu.Check(self.create_dir)
        self.convert_audio_menu.Check(self.convert_audio)
        self.Bind(wx.EVT_MENU, self.on_exit, menu_exit)
        self.Bind(wx.EVT_MENU, self.on_create_dir, self.create_dir_menu)
        self.Bind(wx.EVT_MENU, self.on_convert_audio, self.convert_audio_menu)

        menu_bar = wx.MenuBar()
        menu_bar.Append(menu,"&Menu") # Adding the "filemenu" to the MenuBar
        self.frame.SetMenuBar(menu_bar)  # Adding the MenuBar to the Frame content.

        self.SetSizerAndFit(self.main_sizer)
        self.SetMinSize(self.GetSize())

    def on_create_dir(self, event):
        """Updates the create_dir setting on change"""
        self.create_dir = not self.create_dir
        self.update_settings("create_dir", self.create_dir) 

    def on_convert_audio(self, event):
        """Updates the create_dir setting on change"""
        self.convert_audio = not self.convert_audio
        self.update_settings("convert_audio", self.convert_audio)        

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
    
    def on_save_defaults(self, event):
        prog = self.progressive.GetValue()
        audio = self.audio_input.GetValue()

        self.update_settings("progressive_stream", prog)
        self.update_settings("only_audio", audio)
        self.only_audio_default = audio
        self.is_progressive_default = prog
        self.table.SetFocus()

    def on_url_input(self, event):
        """Loads the available streams on url input"""
        url = self.url_input.GetValue()
        if url:
            if self.loading.locked():
                self.frame.SetStatusText(" A video or URL is already loading")
            else:
                load_thread = Thread(target=self.load_url, args=(url,), daemon=True)
                load_thread.start()
        else:
            self.frame.SetStatusText(" You didn't enter anything !")
            self.url_input.SetFocus()
        event.Skip()
    
    def on_url_paste_input(self, event):
        """Directely loads the available streams on url paste"""
        text_data = wx.TextDataObject()
        if wx.TheClipboard.Open():
            success = wx.TheClipboard.GetData(text_data)
            wx.TheClipboard.Close()
        if success:
            url = text_data.GetText()
            if url:
                if self.loading.locked():
                    self.frame.SetStatusText(" A video or URL is already loading")
                else:
                    load_thread = Thread(target=self.load_url, args=(url,), daemon=True)
                    load_thread.start()
            else:
                self.frame.SetStatusText(" You didn't enter anything !")
                self.url_input.SetFocus()
        event.Skip()

    def on_type_input(self, event):
        """Re-filter the currently loaded streams to match the requested stream type"""
        progressive = self.progressive.GetValue()
        if len(self.queue) > 0 and self.selected >= 0: # only apply a filter if a URL has been loaded
            vid = self.queue[self.selected]
            vid.update_stream_type(progressive)
            
            self.res_input.Clear()
            self.res_input.AppendItems([e.resolution for e in vid.vstreams])
            self.res_input.Select(vid.selected_vstream)
            
            if progressive:
                self.bitrate_input.Disable()
            else:
                self.bitrate_input.Enable()
            self.table.SetTextValue(filesize_to_string(vid.get_filesize()), self.selected, 2)
            
    def on_audio_input(self, event):
        """Re-filter currently loaded stream and update settings"""
        only_audio = self.audio_input.GetValue()

        if only_audio:
            self.progressive.Disable()
            self.adaptive.Disable()
            self.res_input.Disable()
            if self.progressive.GetValue():
                self.adaptive.SetValue(True)
                self.on_type_input(None)
        else:
            self.progressive.Enable()
            self.adaptive.Enable()

        if len(self.queue) > 0 and self.selected >= 0:
            vid = self.queue[self.selected]
            vid.only_audio = only_audio
            if only_audio:
                vid.is_progressive = False
            else:
                self.res_input.Enable()
            self.table.SetTextValue(filesize_to_string(vid.get_filesize()), self.selected, 2)
    
    def on_quality_select(self, event):
        """Record the selected video / audio quality"""
        if len(self.queue) > 0 and self.selected >= 0:
            vid = self.queue[self.selected]
            vid.selected_vstream = self.res_input.GetSelection()
            vid.selected_astream = self.bitrate_input.GetSelection()
            self.table.SetTextValue(filesize_to_string(vid.get_filesize()), self.selected, 2)

    def on_item_select(self, event):
        """Update stream parameters to match selected item"""
        self.selected = self.table.GetSelectedRow()

        if self.selected >= 0 and self.queue[self.selected].loaded:
            self.name_input.Enable()
            self.name_input.SetValue(self.table.GetValue(self.selected, 1))
            vid = self.queue[self.selected]

            self.res_input.Clear()
            self.res_input.AppendItems([str(e.resolution) for e in vid.vstreams])
            self.res_input.Select(vid.selected_vstream)

            self.bitrate_input.Clear()
            self.bitrate_input.AppendItems([str(e.abr) + " - " + str(e.subtype) for e in vid.astreams])
            self.bitrate_input.Select(vid.selected_astream)

            self.progressive.SetValue(vid.is_progressive)
            self.adaptive.SetValue(not vid.is_progressive)
            self.audio_input.SetValue(vid.only_audio)

            if vid.only_audio:
                self.res_input.Disable()
                self.progressive.Disable()
                self.adaptive.Disable()
            else:
                self.res_input.Enable()
                self.progressive.Enable()
                self.adaptive.Enable()

            if vid.is_progressive:
                self.bitrate_input.Disable()
            else:
                self.bitrate_input.Enable()
        else:
            self.name_input.Clear()
            self.name_input.Disable()
            self.bitrate_input.Clear()
            self.res_input.Clear()
    
    def on_delete_items(self, event):
        self.deleting.acquire()
        index = 0
        while index < self.table.GetItemCount():
            if self.table.GetToggleValue(index, 0) and self.queue[index].loaded:
                if self.queue[index].downloading:
                    self.queue[index].request_exit()
                self.queue.pop(index)
                self.table.DeleteItem(index)
                if self.selected > index:
                    self.selected -= 1
            else:
                self.queue[index].row = index
                index += 1
        self.deleting.release()
        if self.selected == self.table.GetItemCount():
            self.selected -= 1
        if len(self.queue) == 0:
            self.name_input.Clear()
            self.name_input.Disable()
            self.bitrate_input.Clear()
            self.res_input.Clear()
        else:
            self.table.SelectRow(self.selected)
            self.on_item_select(None)
        self.table.SetFocus()
    
    def on_clear_completed(self, event):
        self.deleting.acquire()
        index = 0
        while index < self.table.GetItemCount():
            if self.queue[index].completed:
                self.queue.pop(index)
                self.table.DeleteItem(index)
                if self.selected > index:
                    self.selected -= 1
            else:
                self.queue[index].row = index
                index += 1
        self.deleting.release()
        if self.selected == self.table.GetItemCount():
            self.selected -= 1
        if len(self.queue) == 0:
            self.name_input.Clear()
            self.name_input.Disable()
            self.bitrate_input.Clear()
            self.res_input.Clear()
        else:
            self.table.SelectRow(self.selected)
            self.on_item_select(None)
        self.table.SetFocus()

    def on_name_input(self, event):
        name = self.name_input.GetValue()
        if name:
            if len(self.queue) > 0 and self.selected >= 0:
                self.table.SetTextValue(name, self.selected, 1)
                self.queue[self.selected].custom_filename = name
                self.table.SetFocus()

    def load_url(self, url):
        """Loads a specified URL (retrieves available streams)"""
        self.loading.acquire()
        error = False
        try:
            self.frame.SetStatusText(f" Processing URL: {url}")
            video_data = VideoData(self.is_progressive_default, self.only_audio_default)
            self.deleting.acquire()
            self.queue.append(video_data)
            self.table.AppendItem([False, "...", "-", "Processing", 0])
            self.queue[-1].row = self.table.GetItemCount() - 1
            self.deleting.release()
            
            youtube = YouTube(url)
            youtube.register_on_complete_callback(self.complete_callback)
            youtube.register_on_progress_callback(self.progress_callback)

            self.deleting.acquire()
            self.queue[-1].set_data(youtube)
            self.table.SetTextValue(self.queue[-1].youtube.title, self.queue[-1].row, 1)
            self.table.SetTextValue(filesize_to_string(self.queue[-1].get_filesize()), self.queue[-1].row, 2)
            self.table.SetTextValue("Processed", self.queue[-1].row, 3)
            self.queue[-1].loaded = True
            self.table.SelectRow(self.table.GetItemCount() - 1)
            self.on_item_select(None)
            self.deleting.release()

            self.frame.SetStatusText(f" Loaded {video_data.youtube.title}")
        
        except exceptions.RegexMatchError:
            self.frame.SetStatusText(f"Failed to extract video id : {url}")
            error = True
        except (exceptions.VideoUnavailable, exceptions.VideoPrivate):
            self.frame.SetStatusText("The video is unavailable or private.")
            error = True
        except exceptions.HTMLParseError:
            self.frame.SetStatusText("The HTML could not be parsed.")
            error = True
        except exceptions.PytubeError as e:
            self.frame.SetStatusText(f"Failed to load URL: {e}")
            error = True
        except KeyError as e:
            self.frame.SetStatusText(f"Key Error: {e}. The provided URL is probably invalid.")
            error = True
        except Exception as e:
            self.frame.SetStatusText("Unexpected error")
            error = True
        finally:
            index = self.table.GetItemCount() - 1
            if error:
                self.deleting.acquire()
                self.table.DeleteItem(index)
                self.queue.pop(index)
                self.deleting.release()
                if self.selected == index:
                    self.on_item_select(None)
            self.loading.release()
        return True

    def on_download(self, event):
        """Attempts to load the requested videos"""
        if (not self.create_dir) and (not os.path.isdir(self.save_path)):
            self.SetStatusText(f" Invalid save path: {self.save_path} is not a directory")
        for vid in self.queue:
            if vid.downloading or not vid.loaded:
                continue
            else:
                vid.downloading = True

            if vid.only_audio:
                target = self.download_audio
            else:
                target = self.download_video

            vid.thread = Thread(target=target, args=(vid,), daemon=True)
            vid.thread.start()

    def on_browse(self, event):
        """Browse for a directory."""
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
        self.Close()
        event.Skip()

    def progress_callback(self, stream, chunk, bytes_remaining):
        """Updates the progress bar."""
        size = stream.filesize
        if stream.user_data:
            if stream.user_data["exit"]:
                sys.exit()
            vidID = stream.user_data["id"]
            progress = int((1 - float(bytes_remaining)/size)*100)
            if progress != stream.user_data["progress"]:
                stream.user_data["progress"] = progress
                if not self.deleting.locked():
                    self.deleting.acquire()
                    row = None
                    for vid in self.queue:
                        if vid.id == vidID:
                            row = vid.row
                            break
                    if not row is None:
                        self.table.SetValue(progress, row, 4)
                    self.deleting.release()

    def complete_callback(self, stream, filepath):
        """Updates the progress bar and status after a file has been downloaded."""
        if stream.user_data:
            vidID = stream.user_data["id"]
            self.deleting.acquire()
            row = None
            for vid in self.queue:
                if vid.id == vidID:
                    row = vid.row
                    break
            if not row is None:
                self.table.SetTextValue("Done", row, 3)
                self.table.SetValue(100, row, 4)
            self.deleting.release()
    
    def probe_duration(self, filepath):
        """Probe estimated ffmpeg conversion duration"""
        duration = 0.0
        try:
            probe = ffmpeg.probe(filepath)
            if 'format' in probe:
                if 'duration' in probe['format']:
                    duration = float(probe['format']['duration'])
        except ffmpeg.Error as err:
            raise(err)
        return duration

    def ffmpeg_execute(self, command, duration, vid):
        """Execute an ffmpeg command"""

        # Startupinfo to hide console on Windows
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        # Start subprocess
        process = subprocess.Popen(
            command,
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
        
        pattern = re.compile(r'time=\d+:\d+:\d+\.\d+') # The time info we are looking for
        last_time = 0
        last_data = ""
        while True:
            if vid.exit:
                process.terminate()
                sys.exit()
            in_bytes = process.stderr.read(128)
            if not in_bytes:
                break
            data = last_data + in_bytes.decode("utf-8").replace("\r", "")
            
           
            match = []
            for m in pattern.finditer(data):
                match.append(m)

            if match:
                timestr = match[-1].group()[5:]
                factor = [3600, 60, 1] # Hours, Minutes, Seconds
                out_time = sum([a*b for a,b in zip(factor, map(float, timestr.split(':')))]) # Time in seconds           
                if out_time - last_time > 1:
                    
                    # Thread(target=self.ffmpeg_progress_callback, args=[out_time, duration, vid]).start()
                    if not self.deleting.locked():
                        self.deleting.acquire()
                        self.table.SetValue(int((float(out_time)/duration) * 100), vid.row, 4)
                        self.deleting.release()

                    last_time = out_time
                last_data = data[match[-1].end():] # Keep the remaining unmatched data
            else:
                last_data = data
           
        process.wait()
        return True

    def download_video(self, vid):
        """Downloads the YouTube video at the requested url."""
        try:
            self.deleting.acquire()
            self.table.SetTextValue("Downloading video", vid.row, 3)
            self.deleting.release()
            video = vid.vstreams[vid.selected_vstream]
            video.user_data = {"id": vid.id, "progress": 0, "exit": False}
            vid.stream = video
            video_prefix = ""
            if not vid.is_progressive:
                video_prefix = "video_"
            if vid.custom_filename == "":
                filename = None
            else:
                filename = vid.custom_filename
            video_path = video.download(self.save_path, filename=filename, filename_prefix=video_prefix)
            
            if not vid.is_progressive:
                self.deleting.acquire()
                self.table.SetTextValue("Downloading audio", vid.row, 3)
                self.deleting.release()
                audio = vid.astreams[vid.selected_astream]
                audio.user_data = {"id": vid.id, "progress": 0, "exit": False}
                vid.stream = audio
                audio_path = audio.download(self.save_path, filename=filename, filename_prefix="audio_")
                self.deleting.acquire()
                self.table.SetTextValue("Merging audio and video", vid.row, 3)
                self.deleting.release()
                outpath = os.path.join(self.save_path, video_path.split(os.path.sep)[-1][6:])
                
                audio = ffmpeg.input(audio_path).audio
                video = ffmpeg.input(video_path).video
                command = (ffmpeg.output(audio, video, outpath, vcodec="copy")
                            .global_args("-hide_banner")
                            .overwrite_output()
                            .compile())
                duration = self.probe_duration(video_path)
                self.ffmpeg_execute(command, duration, vid)
                os.remove(video_path)
                os.remove(audio_path)
                self.deleting.acquire()
                self.table.SetTextValue("Done", vid.row, 3)
                self.deleting.release()
        
        except exceptions.RegexMatchError:
            self.frame.SetStatusText(f" The Regex pattern did not return any match for the video")
        except (exceptions.VideoUnavailable, exceptions.VideoPrivate):
            self.frame.SetStatusText(" The video is unavailable or private.")
        except exceptions.HTMLParseError:
            self.frame.SetStatusText(" The HTML could not be parsed.")
        except exceptions.PytubeError as e:
            self.frame.SetStatusText(f" Download failed: {e}")
        except KeyError as e:
            self.frame.SetStatusText(f" Key Error: {e}. The provided url is probably invalid.")
        vid.completed = True
        vid.downloading = False
        return True

    def download_audio(self, vid):
        """Downloads the audio of the requested youtube video and converts it to mp3 using ffmpeg"""
        try:
            self.deleting.acquire()
            self.table.SetTextValue("Downloading", vid.row, 3)
            self.deleting.release()
            audio = vid.astreams[vid.selected_astream]
            audio.user_data = {"id": vid.id, "progress": 0, "exit": False}
            vid.stream = audio
            if vid.custom_filename == "":
                filename = None
            else:
                filename = vid.custom_filename
            audio_path = audio.download(self.save_path, filename=filename)
            if self.convert_audio:
                self.deleting.acquire()
                self.table.SetTextValue("Converting to mp3", vid.row, 3)
                self.deleting.release()
                path = audio_path.split(".")
                path[-1] = "mp3"
                outpath = ".".join(path)
                audio = ffmpeg.input(audio_path).audio
                command = (ffmpeg.output(audio, outpath)
                            .global_args("-hide_banner")
                            .overwrite_output()
                            .compile())
                duration = self.probe_duration(audio_path)
                self.ffmpeg_execute(command, duration, vid)
                os.remove(audio_path)
                self.deleting.acquire()
                self.table.SetTextValue("Done", vid.row, 3)
                self.deleting.release()
        except exceptions.RegexMatchError:
            self.frame.SetStatusText(f" The Regex pattern did not return any match for the video")
        except (exceptions.VideoUnavailable, exceptions.VideoPrivate):
            self.frame.SetStatusText(" The video is unavailable or private.")
        except exceptions.HTMLParseError:
            self.frame.SetStatusText(" The HTML could not be parsed.")
        except exceptions.PytubeError as e:
            self.frame.SetStatusText(f" Download failed: {e}")
        except KeyError as e:
            self.frame.SetStatusText(f" Key Error: {e}. The provided url is probably invalid.")
        vid.completed = True
        vid.downloading = False
        return True

class MainFrame(wx.Frame):
    """Application main frame"""

    def __init__(self):
        wx.Frame.__init__(self, parent=None, title='ytgui')
        
        # Add main panel
        self.frame_sizer = wx.BoxSizer(wx.VERTICAL)
        main_panel = MainPanel(self)
        self.frame_sizer.Add(main_panel, 1, wx.EXPAND)
        self.SetSizerAndFit(self.frame_sizer)
        
        # Load the icon
        self.SetIcon(wx.Icon(os.path.abspath(os.path.join(os.path.dirname(__file__), "icon.ico"))))
        # Show the GUI
        self.Show()


if __name__ == '__main__':
    app = wx.App()
    frame = MainFrame()
    app.MainLoop()