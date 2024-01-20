#!/usr/bin/python3

import os
import sys
import time
import subprocess
import json
import gi
import dbus
from dbus.mainloop.glib import DBusGMainLoop

gi.require_version("Gtk", "3.0")                # pylint: disable=wrong-import-position
from gi.repository import Gtk, Gdk, GLib, Gio   # pylint: enable=wrong-import-position

import openvpn3
from openvpn3.constants import StatusMajor, StatusMinor

MAX_LOG_SIZE = 5*1024*1024                      # 5MB

class UserCredDialog(Gtk.Dialog):
    """ A dialog that prompts the user for username/password/OTP credentials. """
    def __init__(self, parent, config, username):
        super().__init__(title="Connect " + config["config_name"], transient_for=parent)
        self.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                         Gtk.STOCK_OK, Gtk.ResponseType.OK)

        ok_button = self.get_widget_for_response(response_id=Gtk.ResponseType.OK)
        ok_button.set_can_default(True)
        ok_button.grab_default()

        self.set_border_width(10)

        box = self.get_content_area()
        box.set_spacing(15)

        label_name = Gtk.Label(label="User name:", xalign=0)
        label_password = Gtk.Label(label="Passsword:", xalign=0)
        label_otp = Gtk.Label(label="OTP code:", xalign=0)

        self.name = Gtk.Entry()
        self.password = Gtk.Entry()
        self.otp = Gtk.Entry()
        self.password.set_visibility(False)
        self.otp.set_activates_default(True)

        grid = Gtk.Grid(column_homogeneous=False, column_spacing=50, row_spacing=10)
        grid.attach(label_name,     0, 0, 1, 1)
        grid.attach(label_password, 0, 1, 1, 1)
        grid.attach(label_otp,      0, 2, 1, 1)
        grid.attach(self.name,      1, 0, 1, 1)
        grid.attach(self.password,  1, 1, 1, 1)
        grid.attach(self.otp,       1, 2, 1, 1)

        box.add(grid)

        if username:
            self.name.set_text(username)
            self.password.grab_focus()
        self.show_all()

class TextFileWindow(Gtk.Window):
    """ Non-modal window to display a contents of a text file with a scroller.
        Used to view OpenVPN configs and logs.
    """
    def __init__(self, title: str, text: str):
        super().__init__(title=title)

        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.get_buffer().set_text(text)

        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.add(tv)

        self.set_border_width(5)
        self.set_default_size(600, 500)
        self.add(scrolled_window)
        self.connect("key_press_event", self.check_escape)

    def check_escape(self, _window: Gtk.Window, event: Gdk.EventKey):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()

class SpinnerWindow(Gtk.MessageDialog):
    """ Modal window with a spinner and a status message to indicate connection progress.
        The user can press Esc to cancel connection.
    """
    def __init__(self, parent, text):
        super().__init__(transient_for=parent,
                         modal=True,
                         destroy_with_parent=True,
                         text=text)
        spinner = Gtk.Spinner()
        box = self.get_content_area()
        box.add(spinner)
        spinner.start()
        self.cancelled_by_user = False
        self.connect("delete_event", self.on_delete_event)
        self.show_all()

    def on_delete_event(self, _window: Gtk.Window, _event: Gdk.Event) -> bool:
        """ GDK_DELETE event is sent when a window manager has requested
            to close the window, usually when the user pressed Esc.
        """
        self.cancelled_by_user = True
        self.props.text = "Terminating..."

        # Return True to prevent the window from being closed
        # and allow for graceful connection shutdown
        return True

class SwitchWithData(Gtk.Switch):               # pylint: disable=too-few-public-methods
    def __init__(self, data):
        super().__init__()
        self.config = data

class ListBoxRowWithData(Gtk.ListBoxRow):       # pylint: disable=too-few-public-methods
    def __init__(self, data):
        super().__init__()
        self.config = data

class EventBoxWithData(Gtk.EventBox):           # pylint: disable=too-few-public-methods
    def __init__(self, data):
        super().__init__()
        self.config = data

def display_error(parent: Gtk.Window, msg1: str, msg2: str):
    err_dlg = Gtk.MessageDialog(transient_for=parent,
                                message_type=Gtk.MessageType.ERROR,
                                buttons=Gtk.ButtonsType.OK,
                                text=msg1)
    err_dlg.format_secondary_text(msg2)
    err_dlg.run()
    err_dlg.destroy()

def flush_gtk_events():
    """ Handle GTK events. Used to run spinner animation and to prevent
        "Application is not reposponding" message during connection.
    """
    while Gtk.events_pending():
        Gtk.main_iteration()

def get_gtk_theme_name() -> str:
    """ Get the name of the currently used GTK theme. """
    settings = Gtk.Settings.get_default()
    return settings.get_property("gtk-theme-name")

def set_gtk_theme_name(gtk_theme_name: str):
    """ Set GTK theme to use. """
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-theme-name", gtk_theme_name)

def gnome_dark_mode_enabled() -> bool:
    """ Returns True if Dark Mode is enabled in GNOME. """
    settings = Gio.Settings.new('org.gnome.desktop.interface')
    return settings.get_string('color-scheme') == "prefer-dark"

def set_gtk_application_prefer_dark_theme(use_dark_theme: bool):
    """ Enable/disable dark mode for the application. """
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-application-prefer-dark-theme", use_dark_theme)

MENU_XML = """
<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <menu id="app-menu">
    <section>
      <item>
        <attribute name="action">app.import-profile</attribute>
        <attribute name="label" translatable="yes">Import Profile</attribute>
      </item>
      <item>
        <attribute name="action">app.view-log</attribute>
        <attribute name="label" translatable="yes">View _Log</attribute>
      </item>
    </section>
    <section>
      <attribute name="label" translatable="yes">Appearance</attribute>
      <item>
        <attribute name="action">app.change-theme</attribute>
        <attribute name="target">light</attribute>
        <attribute name="label" translatable="yes">Light theme</attribute>
      </item>
      <item>
        <attribute name="action">app.change-theme</attribute>
        <attribute name="target">dark</attribute>
        <attribute name="label" translatable="yes">Dark theme</attribute>
      </item>
    </section>
    <section>
      <item>
        <attribute name="action">app.about</attribute>
        <attribute name="label" translatable="yes">_About</attribute>
      </item>
      <item>
        <attribute name="action">app.quit</attribute>
        <attribute name="label" translatable="yes">_Quit</attribute>
        <attribute name="accel">&lt;Primary&gt;q</attribute>
    </item>
    </section>
  </menu>
</interface>
"""


class AppWindow(Gtk.ApplicationWindow):
    """ Main application window. """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.application = kwargs["application"]

        hb = self.__create_header_bar()
        self.set_titlebar(hb)

        # Tweak CSS for better appearance in Dark Mode
        self.__load_custom_css()

        self.configs = []
        self.usernames = {}
        self.f_log = None
        self.set_border_width(10)
        self.set_default_size(300, 400)
        self.set_resizable(False)
        self.load_user_settings()
        self.connect_dbus()
        self.kill_lingering_sessions()
        self.load_connections()
        self.draw_win()
        self.idle_counter = 0
        # Setup timer to increment idle counter every minute
        self.timeout_id = GLib.timeout_add_seconds(60, self.auto_exit, None)

    def __create_header_bar(self) -> Gtk.HeaderBar:
        """ Create window header bar with menu icon in it"""

        button = Gtk.MenuButton()
        image = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.MENU)
        button.add(image)

        builder = Gtk.Builder.new_from_string(MENU_XML, -1)
        button.set_menu_model(builder.get_object("app-menu"))

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "OpenVPN3"
        hb.pack_start(button)

        return hb

    def __load_custom_css(self):
        """ Gtk.Switch inside Gtk.Listbox is not quite readable on some themes
            in Dark Mode. Make listbox transparent to workaround it.
        """
        screen = Gdk.Screen.get_default()
        provider = Gtk.CssProvider()
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        css = b"list { background: transparent; }"
        provider.load_from_data(css)

    def connect_dbus(self):
        """ Connect to the configuration and session manager. """
        self.cmgr = openvpn3.ConfigurationManager(sysbus)
        self.smgr = openvpn3.SessionManager(sysbus)

    def load_connections(self):
        """ Fetch Session and Config objects from OpenVPN3
            and combine them to form a connection list.
        """
        self.configs = [
            { "config_name":  c.GetConfigName(),
              "config_path":  c.GetPath(),
              "session_path": None
            } for c in self.cmgr.FetchAvailableConfigs()]

        # Relate Configs to Sessions. Note that there is no 1:1 relation.
        # A config can have multiple sessions and a session can exist
        # without a config if config was deleted. We handle such cases
        # by adding these stale sessions to the connection list.
        for s in self.smgr.FetchAvailableSessions():
            conf_name = s.GetProperty("config_name")
            conf_path = s.GetProperty("config_path")
            sess_path = s.GetPath()
            attached = False
            for c in self.configs:
                if c["config_path"] == conf_path:
                    c["session_path"] = sess_path
                    attached = True
                    break
            if not attached:
                print("Attaching stale session", conf_name)
                self.configs.append({
                    "config_name": conf_name,
                    "config_path": conf_path,
                    "session_path": sess_path
                })

    def kill_lingering_sessions(self):
        for s in self.smgr.FetchAvailableSessions():
            status = s.GetStatus()
            if (status["major"] == StatusMajor.CONNECTION and
                status["minor"] != StatusMinor.CONN_CONNECTED):
                print("Killing lingering session with status", status)
                s.Disconnect()

    def __ok_to_disconnect(self) -> bool:
        sessions = self.smgr.FetchAvailableSessions()
        if len(sessions) > 0:
            dialog = Gtk.MessageDialog(
                transient_for=self,
                message_type=Gtk.MessageType.QUESTION,
                buttons=Gtk.ButtonsType.YES_NO,
                text="This will disconnect you from other active session. Proceed?",
            )
            response = dialog.run()
            dialog.destroy()
            if response != Gtk.ResponseType.YES:
                return False
            for s in sessions:
                s.Disconnect()
        return True

    def redraw_win(self):
        self.load_connections()
        for k in self.box_outer.get_children():
            k.destroy()
        self.remove(self.box_outer)
        self.draw_win()
        self.show_all()

    def draw_win(self):
        self.box_outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add(self.box_outer)

        listbox = Gtk.ListBox()
        listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        # listbox.connect('row-activated', self.on_row_activated)
        self.box_outer.pack_start(listbox, True, True, 0)

        # Populate listbox with VPN connections (rows). Each row consists of 3 columns:
        #   on/off switch | profile name | delete button
        for c in self.configs:
            row = ListBoxRowWithData(c)
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=50)
            row.add(hbox)

            # Left column: On/Off switch
            switch = SwitchWithData(c)
            switch.set_active(c["session_path"] is not None)
            switch.set_tooltip_text("Connect/Disconnect")
            switch.connect("notify::active", self.on_switch_activated)
            switch.props.valign = Gtk.Align.CENTER
            hbox.pack_start(switch, False, True, 0)

            # Middle column: VPN Profile Name
            # We need EventBox here because Gtk.Box cannot handle double-click
            evbox = EventBoxWithData(c)
            evbox.connect("button-press-event", self.vpn_profile_button_press)
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            evbox.add(vbox)
            hbox.pack_start(evbox, True, True, 0)

            # Top/bottom labels in the middle column
            top_label = Gtk.Label(label="OpenVPN Profile", xalign=0)
            top_label.set_sensitive(False)
            bottom_label = Gtk.Label(label=c["config_name"], xalign=0)
            vbox.pack_start(top_label, True, True, 0)
            vbox.pack_start(bottom_label, True, True, 0)

            # Right column: Delete profile button
            button = Gtk.Button.new_from_icon_name("list-remove-symbolic", Gtk.IconSize.BUTTON)
            button.set_tooltip_text("Delete Profile")
            button.connect("clicked", self.on_delete_profile_clicked, c)
            hbox.pack_start(button, False, False, 0)

            listbox.add(row)

        # Status line and "Add profile" button at the bottom of the window
        label_status = Gtk.Label(label=self.get_connection_status(), xalign=0)
        add_button = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add_button.set_tooltip_text("Import Profile")
        add_button.connect("clicked", self.on_add_profile_clicked)

        # Pack the status label and "Add profile" button into the horizontal box
        bottom_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=50)
        bottom_hbox.pack_start(label_status, False, False, 0)
        bottom_hbox.pack_end(add_button, False, False, 0)

        self.box_outer.pack_end(bottom_hbox, False, False, 0)

    def show_config(self, config):
        config_text = self.cmgr.Retrieve(config["config_path"]).Fetch()
        win = TextFileWindow(title=config["config_name"], text=config_text)
        win.show_all()

    def vpn_profile_button_press(self, ev: EventBoxWithData, eb: Gdk.EventButton):
        self.idle_counter = 0
        if eb.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.show_config(ev.config)

    def on_row_activated(self, _listbox: Gtk.ListBox, row: ListBoxRowWithData):
        self.idle_counter = 0
        print(row.config, "activated")

    def get_connection_status(self) -> str:
        status = "Disconnected"
        for c in self.configs:
            path = c["session_path"]
            if path is not None:
                session = self.smgr.Retrieve(path)
                s = session.GetStatus()
                if (s["major"] == StatusMajor.CONNECTION and
                    s["minor"] == StatusMinor.CONN_CONNECTED):
                    status = "Connected to " + session.GetProperty("session_name")
                else:
                    status = s["message"]
                break
        return status

    def on_switch_activated(self, switch: SwitchWithData, _gparam):
        GLib.timeout_add(0, self.__do_switch_activated, switch)

    def __do_switch_activated(self, switch: SwitchWithData):
        self.idle_counter = 0
        self.connect_dbus()
        if switch.get_active():
            if not self.__connect_vpn(switch.config):
                switch.set_state(False)
        else:
            self.__disconnect_vpn(switch.config)
        self.redraw_win()

    def __get_user_creds(self, config):
        """ Prompts the user for credentials. Saves the username.
            Returns False if the user cancelled the dialog.
        """
        if config["config_name"] in self.usernames:
            saved_user = self.usernames[config["config_name"]]
        else:
            saved_user = ""

        dialog = UserCredDialog(self, config, saved_user)
        response = dialog.run()
        user = dialog.name.get_text()
        password = dialog.password.get_text()
        otp = dialog.otp.get_text()
        dialog.destroy()

        if response != Gtk.ResponseType.OK:
            return False, None, None, None

        if user != saved_user:
            self.usernames[config["config_name"]] = user
            self.save_user_settings()

        return True, user, password, otp

    def __connect_vpn(self, config) -> bool:
        if not self.__ok_to_disconnect():
            return False

        ok, user, password, otp = self.__get_user_creds(config)
        if ok:
            spinner = SpinnerWindow(self, "Connecting to " + config["config_name"] + "...")
            ok, err_msg = self.__do_connect_vpn(config, spinner, user, password, otp)
            spinner.destroy()
            if spinner.cancelled_by_user:
                return False
            if not ok:
                display_error(self, "Error connecting to " + config["config_name"], err_msg)
        return ok

    def __do_connect_vpn(self, config, spinner, user, password, otp):
        session = self.__new_session(config["config_path"])
        print("Session D-Bus path: " + session.GetPath())

        # Start background logging process for this session
        with open(self.application.log_filename, "a", encoding="utf-8") as self.f_log:
            subprocess.Popen(["/usr/bin/openvpn3", "log",
                              "--log-level", "6",
                              "--session-path", session.GetPath()],
                             stdout=self.f_log, stderr=self.f_log)

        # Start VPN connection
        ready = False
        error_msg = None
        while not ready and not error_msg:
            try:
                # Is the backend ready to connect?  If not an exception is thrown
                session.Ready()
                session.Connect()
                ready = True
            except dbus.exceptions.DBusException as e:
                if str(e).find('Backend VPN process is not ready') > 0:
                    time.sleep(0.5)
                elif str(e).find(' Missing user credentials') > 0:
                    error_msg = self.__provide_user_creds(session, user, password, otp)
                else:
                    error_msg = e.get_dbus_message()
            # Now the while-loop will ensure session.Ready() is re-run

        # Wait 15 seconds max for the backend to get a connection
        # If connection is established, return immediately
        if not error_msg:
            ok, error_msg = self.__wait_for_connection(session, spinner, 15)
            if ok:
                return True, None

        # If we are here, we failed to establish a VPN connection.
        # Wait for a couple of seconds before terminating the session
        # to allow log writer to capture the logs
        if not spinner.cancelled_by_user:
            for _ in range(0, 20):
                time.sleep(0.1)
                flush_gtk_events()

        # Perform cleanup
        # Session manager is still trying to establish the session in the background
        # So we need to explicitly terminate it
        # Unfortunately, sometimes OpenVPN3 v21 segfaults here :(
        try:
            session.Disconnect()
        except Exception:
            display_error(self, "Fatal error",
                "Unexpected error occurred. This is typically caused by backend error,\n"
                "such as openvpn3 daemon segfault. Please check system log for details.\n"
                "Session data may be inconsistent, the application will exit now.")
            sys.exit(1)

        return False, error_msg

    def __disconnect_vpn(self, config):
        s_path = config["session_path"]
        if s_path is None:
            return
        session = self.smgr.Retrieve(s_path)
        session.Disconnect()

    def __new_session(self, config_path: str):
        cfg = self.cmgr.Retrieve(config_path)
        session = self.smgr.NewTunnel(cfg)

        # Wait for the backend to settle
        for _ in range(0, 10):
            time.sleep(0.1)
            flush_gtk_events()

        return session

    def __provide_user_creds(self, session, user, password, otp):
        """ Provide credentials to the backend. Try and return user-friendly
            error instead of an ugly D-Bus exception message.
        """
        error_msg = None
        try:
            for u in session.FetchUserInputSlots():
                # We only care about responding to credential requests here
                if u.GetTypeGroup()[0] != openvpn3.ClientAttentionType.CREDENTIALS:
                    continue

                # Send information provided by the user to the backend
                varname = u.GetVariableName()
                if varname == "username":
                    if user:
                        u.ProvideInput(user)
                    else:
                        error_msg = "Username is required, but it was not provided."
                elif varname == "password":
                    if password:
                        u.ProvideInput(password)
                    else:
                        error_msg = "Password is required, but it was not provided."
                elif varname == "static_challenge":
                    if otp:
                        u.ProvideInput(otp)
                    else:
                        error_msg = "OTP Code is required, but it was not provided."
        except dbus.exceptions.DBusException as e:
            error_msg = e.get_dbus_message()

        return error_msg

    def __wait_for_connection(self, session, spinner, seconds):
        """ Wait for the specified number of seconds for the backend to get a connection.
            Process GTK events every 100ms (1/10 of second) to run spinner animation.
            Check the status every second and return as soon as connection is established.
        """
        for i in range(1, seconds*10):
            if i % 10 == 0:
                status = session.GetStatus()
                if (status["major"] == StatusMajor.CONNECTION and
                    status["minor"] == StatusMinor.CONN_CONNECTED):
                    return True, None
                if (status["major"] == StatusMajor.CONNECTION and
                    status["minor"] == StatusMinor.CONN_FAILED):
                    error_msg = "Failed to start the connection"
                    if status["message"]:
                        error_msg += "\n" + status["message"]
                    break
                if (status["major"] == StatusMajor.CONNECTION and
                    status["minor"] == StatusMinor.CONN_AUTH_FAILED):
                    error_msg = "Authentication failed"
                    break
                print(f"[{i}] Status:", str(session.GetStatus()))
            flush_gtk_events()
            time.sleep(0.1)
            if spinner.cancelled_by_user:
                return False, None
        else:
            status = session.GetStatus()
            error_msg = "Connection timed out.\n" + \
                         str(status["major"]) + "\n" + str(status["minor"])
            if status["message"]:
                error_msg += "\nMessage: " + status["message"]
        return False, error_msg

    def on_add_profile_clicked(self, _widget: Gtk.Button):
        self.idle_counter = 0
        dialog = Gtk.FileChooserDialog(title="Import VPN Profile",
                                       parent=self,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)

        self.__add_filters(dialog)

        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            if self.__is_valid_profile(filename):
                self.connect_dbus()
                self.__import_profile(filename)
            else:
                display_error(self, "Failed to import profile", "This profile is not valid.")
            self.redraw_win()

    def __add_filters(self, dialog: Gtk.FileChooserDialog):
        """ Add filename filters to the FileChooserDialog. """
        filter_ovpn = Gtk.FileFilter()
        filter_ovpn.set_name("OpenVPN profiles")
        filter_ovpn.add_pattern("*.ovpn")
        dialog.add_filter(filter_ovpn)

        filter_text = Gtk.FileFilter()
        filter_text.set_name("Text files")
        filter_text.add_mime_type("text/plain")
        dialog.add_filter(filter_text)

        filter_any = Gtk.FileFilter()
        filter_any.set_name("Any files")
        filter_any.add_pattern("*")
        dialog.add_filter(filter_any)

    def __is_valid_profile(self, filename: str) -> bool:
        """ Sanity check of the OpenVPN profile. """
        # OpenVPN3 does not perform any profile validation and allows
        # to import arbitrary data, so we have to do some minimal check
        with open(filename, 'r', encoding="utf-8") as f:
            if "remote" in f.read():
                return True
        return False

    def __import_profile(self, filename: str):
        profile_name = os.path.splitext(os.path.basename(filename))[0]
        with open(filename, 'r', encoding="utf-8") as f:
            self.cmgr.Import(profile_name, f.read(), False, True)

    def on_delete_profile_clicked(self, _button, config):
        self.idle_counter = 0
        dialog = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Do you want to delete this VPN profile?",
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.connect_dbus()
            self.__disconnect_vpn(config)
            self.cmgr.Retrieve(config["config_path"]).Remove()
            self.redraw_win()

    def auto_exit(self, _user_data) -> bool:
        """ Automatically quit the application after 15 minutes of inactivity. """
        self.idle_counter += 1
        if self.idle_counter > 15:
            self.application.quit()
        return True

    def load_user_settings(self):
        if os.path.exists(self.application.settings_filename):
            with open(self.application.settings_filename, 'r', encoding="utf-8") as f:
                self.usernames = json.load(f)

    def save_user_settings(self):
        with open(self.application.settings_filename, 'w', encoding="utf-8") as f:
            json.dump(self.usernames, f, indent=4)

class Application(Gtk.Application):
    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            application_id="ovpn3gui.py",
            **kwargs
        )
        self.window = None
        home_dir = os.path.expanduser("~")
        self.settings_filename = home_dir + "/.ovpn3gui.json"
        self.log_filename = home_dir + "/ovpn3gui.log"
        self.old_log_filename = self.log_filename + '.old'

    def do_startup(self, *args, **kwargs):
        Gtk.Application.do_startup(self)

        set_gtk_theme_name(get_gtk_theme_name())
        if gnome_dark_mode_enabled():
            set_gtk_application_prefer_dark_theme(True)

        action = Gio.SimpleAction.new("import-profile", None)
        action.connect("activate", self.on_import_profile)
        self.add_action(action)

        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about)
        self.add_action(action)

        action = Gio.SimpleAction.new("view-log", None)
        action.connect("activate", self.on_view_log)
        self.add_action(action)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)

        theme_variant = GLib.Variant.new_string("System default")
        action = Gio.SimpleAction.new_stateful("change-theme",
                                               theme_variant.get_type(),
                                               theme_variant)
        action.connect("change-state", self.on_change_theme)
        self.add_action(action)

        self.rotate_log()

    def do_activate(self, *args, **kwargs):
        # We only allow a single window and raise any existing ones
        if not self.window:
            # Windows are associated with the application
            # when the last one is closed the application shuts down
            self.window = AppWindow(application=self, title="OpenVPN3")
            self.window.show_all()
        self.window.present()

    def on_import_profile(self, _action: Gio.SimpleAction, _param):
        if self.window:
            self.window.on_add_profile_clicked(None)

    def on_change_theme(self, action: Gio.SimpleAction, value: GLib.Variant):
        action.set_state(value)
        if value.get_string() == "light":
            set_gtk_theme_name("Adwaita-light")
        else:
            set_gtk_theme_name("Adwaita-dark")

    def rotate_log(self):
        if os.path.exists(self.log_filename):
            file_stat = os.stat(self.log_filename)
            if file_stat.st_size > MAX_LOG_SIZE:
                os.rename(self.log_filename, self.old_log_filename)

    def on_view_log(self, _action, _param):
        log = None
        if os.path.exists(self.log_filename):
            log = self.log_filename
        elif os.path.exists(self.old_log_filename):
            log = self.old_log_filename

        if log:
            with open(log, 'r', encoding="utf-8") as f:
                win = TextFileWindow(log, f.read())
                win.show_all()
        else:
            display_error(self.window, "Log is empty", "There are no records in the log yet")

    def on_about(self, _action, _param):
        about_dialog = Gtk.AboutDialog(transient_for=self.window, modal=True)
        about_dialog.set_name           ("OpenVPN3 Linux Frontend GTK3 Application")
        about_dialog.set_version        ("v1.0")
        about_dialog.set_copyright      ("(c) 2023 trengri")
        about_dialog.set_comments       ("Inspired by OpenVPN Connect client")
        about_dialog.set_license        ("GPLv3")
        about_dialog.set_website        ("https://github.com/trengri/ovpn3gui")
        about_dialog.set_website_label  ("GitHub")
        about_dialog.set_authors        (["trengri"])
        about_dialog.set_documenters    (["Nobody"])
        about_dialog.set_artists        (["Nobody"])
        about_dialog.set_logo_icon_name ("network-transmit-receive")
        about_dialog.set_program_name   ("OpenVPN3 Linux Frontend")
        about_dialog.present()

    def on_quit(self, _action, _param):
        self.quit()


if __name__ == "__main__":
    # Set up the main GLib loop and connect to the system bus
    mainloop = GLib.MainLoop()
    dbusloop = DBusGMainLoop(set_as_default=True)
    sysbus = dbus.SystemBus(mainloop=dbusloop)

    app = Application()
    app.run(sys.argv)
