#!/usr/bin/python3

import os
import sys
import time
import datetime
import subprocess
import json
import gi
import dbus
from dbus.mainloop.glib import DBusGMainLoop

import openvpn3
from openvpn3.constants import (
  StatusMajor, StatusMinor, ClientAttentionType, ClientAttentionGroup, SessionManagerEventType
)

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GObject, GLib, Gio

MAX_LOG_SIZE = 10*1024*1024        # 10MB

class UserCredDialog(Gtk.Dialog):
    def __init__(self, parent, config, username):
        super().__init__(title="Connect " + config["config_name"], transient_for=parent)
        self.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OK, Gtk.ResponseType.OK
        )

        ok_button = self.get_widget_for_response(response_id=Gtk.ResponseType.OK)
        ok_button.set_can_default(True)
        ok_button.grab_default()

        self.set_border_width(10)

        box = self.get_content_area()
        box.set_spacing(15)

        label_name = Gtk.Label(label="User name:", xalign=0)
        label_password = Gtk.Label(label="Passsword:", xalign=0)
        label_otp = Gtk.Label(label="OTP code:", xalign=0)

        self.entry_name = Gtk.Entry()
        self.entry_password = Gtk.Entry()
        self.entry_password.set_visibility(False)
        self.entry_otp = Gtk.Entry()
        self.entry_otp.set_activates_default(True)

        grid = Gtk.Grid(column_homogeneous=False, column_spacing=50, row_spacing=10)
        grid.attach(label_name,          0, 0, 1, 1)
        grid.attach(label_password,      0, 1, 1, 1)
        grid.attach(label_otp,           0, 2, 1, 1)
        grid.attach(self.entry_name,     1, 0, 1, 1)
        grid.attach(self.entry_password, 1, 1, 1, 1)
        grid.attach(self.entry_otp,      1, 2, 1, 1)

        box.add(grid)

        if username:
            self.entry_name.set_text(username)
            self.entry_password.grab_focus()
        self.show_all()

class TextFileWindow(Gtk.Window):
    def __init__(self, title: str, text: str):
        super().__init__(title=title)

        tv = Gtk.TextView()
        tv.set_editable(False)
        tv.set_monospace(True)
        tv.get_buffer().set_text(text)

        scrolled_window =  Gtk.ScrolledWindow()
        scrolled_window.add(tv)

        self.set_border_width(5)
        self.set_default_size(600, 500)
        self.add(scrolled_window)
        self.connect("key_press_event", self.check_escape)

    def check_escape(self, window: Gtk.Window, event: Gdk.EventKey):
        if event.keyval == Gdk.KEY_Escape:
            self.destroy()

class SwitchWithData(Gtk.Switch):
    config = GObject.Property(type=object, default=None)
    def __init__(self):
        super().__init__()

class ListBoxRowWithData(Gtk.ListBoxRow):
    def __init__(self, data):
        super().__init__()
        self.config = data

class EventBoxWithData(Gtk.EventBox):
    def __init__(self, data):
        super().__init__()
        self.config = data

def get_gtk_theme_name():
    """Get the name of the currently used GTK theme.
    :rtype: str
    """
    settings = Gtk.Settings.get_default()
    return settings.get_property("gtk-theme-name")

def set_gtk_theme_name(gtk_theme_name):
    """Set the GTK theme to use.
    :param str gtk_theme_name: The name of the theme to use (e.g.
                               ``"Adwaita"``).
    """
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-theme-name", gtk_theme_name)

def set_gtk_application_prefer_dark_theme(use_dark_theme: bool):
    """Defines whether the dark variant of the GTK theme should be used or
    not.
    :param bool use_dark_theme: If ``True`` the dark variant of the theme will
                                be used (if available).
    """
    settings = Gtk.Settings.get_default()
    settings.set_property("gtk-application-prefer-dark-theme", use_dark_theme)


# This would typically be its own file
MENU_XML = """
<?xml version="1.0" encoding="UTF-8"?>
<interface>
  <menu id="app-menu">
    <section>
      <item>
        <attribute name="action">win.import-profile</attribute>
        <attribute name="label" translatable="yes">Import Profile</attribute>
      </item>
    </section>
    <section>
      <item>
        <attribute name="action">win.dark-mode</attribute>
        <attribute name="label" translatable="yes">Dark Mode</attribute>
      </item>
    </section>
    <section>
      <item>
        <attribute name="action">app.view-log</attribute>
        <attribute name="label" translatable="yes">View _Log</attribute>
      </item>
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
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.application = kwargs["application"]

        # This will be in the windows group and have the "win" prefix
        import_profile_action = Gio.SimpleAction.new("import-profile", None)
        import_profile_action.connect("activate", self.on_import_profile_action)
        self.add_action(import_profile_action)

        dark_mode_action = Gio.SimpleAction.new_stateful(
            "dark-mode", None, GLib.Variant.new_boolean(False)
        )
        dark_mode_action.connect("change-state", self.on_dark_mode_toggle)
        self.add_action(dark_mode_action)

        hb = Gtk.HeaderBar()
        hb.set_show_close_button(True)
        hb.props.title = "OpenVPN3"
        self.set_titlebar(hb)

        button = Gtk.MenuButton()
        image = Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.MENU)
        button.add(image)

        builder = Gtk.Builder.new_from_string(MENU_XML, -1)
        button.set_menu_model(builder.get_object("app-menu"))

        hb.pack_start(button)

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
#        Gtk.Settings.get_default().connect("notify::gtk-theme-name", self._on_theme_name_changed)
#        Gtk.Settings.get_default().connect("notify::gtk-application-prefer-dark-theme", self._on_theme_name_changed)
        self.draw_win()
        self.idle_counter = 0
        # Increment idle counter every minute
        self.timeout_id = GLib.timeout_add_seconds(60, self.auto_exit, None)

    # Connect to the configuration and session manager
    def connect_dbus(self):
        self.cmgr = openvpn3.ConfigurationManager(sysbus)
        self.smgr = openvpn3.SessionManager(sysbus)

    def load_connections(self):
        self.configs = [
            { "config_name":  c.GetConfigName(),
              "config_path":  c.GetPath(),
              "session_path": None
            } for c in self.cmgr.FetchAvailableConfigs()
        ]

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
                self.configs.append({"config_name": conf_name,
                                     "config_path": conf_path,
                                     "session_path": sess_path})

    def kill_lingering_sessions(self):
        for s in self.smgr.FetchAvailableSessions():
            status = s.GetStatus()
            if status["major"] == StatusMajor.CONNECTION and status["minor"] != StatusMinor.CONN_CONNECTED:
                print("Killing lingering session with status", status)
                s.Disconnect()

    def ok_to_disconnect(self) -> bool:
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
            if response == Gtk.ResponseType.YES:
                for s in sessions:
                    s.Disconnect()
            else:
                return False
        return True

    @staticmethod
    def _on_theme_name_changed(settings, gparam):
        print("Theme name:", settings.get_property("gtk-theme-name"))

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
        self.box_outer.pack_start(listbox, True, True, 0)

        label_status = Gtk.Label(label=self.get_connection_status(), xalign=0)
        add_button = Gtk.Button.new_from_icon_name("list-add-symbolic", 4)
        add_button.connect("clicked", self.on_import_profile_clicked)
        bottom_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=50)
        bottom_hbox.pack_start(label_status, False, False, 0)
        bottom_hbox.pack_end(add_button, False, False, 0)
        self.box_outer.pack_end(bottom_hbox, False, False, 0)

        for c in self.configs:
            row = ListBoxRowWithData(c)
            hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=50)
            row.add(hbox)

            switch = SwitchWithData()
            switch.set_active(c["session_path"] is not None)
            switch.connect("notify::active", self.on_switch_activated)
            switch.config = c
            switch.props.valign = Gtk.Align.CENTER
            hbox.pack_start(switch, False, True, 0)

            evbox = EventBoxWithData(c)
            evbox.connect("button-press-event", self.vpn_profile_button_press)
            vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            evbox.add(vbox)
            hbox.pack_start(evbox, True, True, 0)

            label1 = Gtk.Label(label="OpenVPN Profile", xalign=0)
            label1.set_sensitive(False)
            label2 = Gtk.Label(label=c["config_name"], xalign=0)
            vbox.pack_start(label1, True, True, 0)
            vbox.pack_start(label2, True, True, 0)

            button = Gtk.Button.new_from_icon_name("list-remove-symbolic", 1)
            button.connect("clicked", self.on_delete_profile_clicked, c)
            hbox.pack_start(button, False, False, 0)

            listbox.add(row)

        row = Gtk.ListBoxRow()
        listbox.add(row)
#        listbox.connect('row-activated', self.on_row_activated)
        listbox.show_all()

    def show_config(self, config):
        config_text = self.cmgr.Retrieve(config["config_path"]).Fetch()
        win = TextFileWindow(title=config["config_name"], text=config_text)
        win.show_all()

    def vpn_profile_button_press(self, ev: EventBoxWithData, eb: Gdk.EventButton):
        self.idle_counter = 0
        if eb.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.show_config(ev.config)

    def on_row_activated(self, listbox: Gtk.ListBox, row: ListBoxRowWithData):
        self.idle_counter = 0
        print(row.config, "activated")

    def get_connection_status(self) -> str:
        status = "Disconnected"
        for c in self.configs:
            path = c["session_path"]
            if path is not None:
                session = self.smgr.Retrieve(path)
                s = session.GetStatus()
                if s["major"] == StatusMajor.CONNECTION and s["minor"] == StatusMinor.CONN_CONNECTED:
                    status = "Connected to " + session.GetProperty("session_name")
                else:
                    status = s["message"]
                break
        return status

    def display_error(self, msg1: str, msg2: str):
        err_dlg = Gtk.MessageDialog(
            transient_for=self,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=msg1,
        )
        err_dlg.format_secondary_text(msg2)
        err_dlg.run()
        err_dlg.destroy()

    def new_spinner(self, text: str) -> Gtk.MessageDialog:
        spinner_window = Gtk.MessageDialog(transient_for = self,
                                           modal=True,
                                           destroy_with_parent=True,
                                           text = text)
        box_content_area = spinner_window.get_content_area()
        spinner = Gtk.Spinner()
        box_content_area.add(spinner)
        spinner.start()
        spinner_window.show_all()
        return spinner_window

    def on_switch_activated(self, switch, gparam):
        GLib.timeout_add(0, self.do_switch_activated, switch)

    def do_switch_activated(self, switch: SwitchWithData):
        self.idle_counter = 0
        self.connect_dbus()
        if switch.get_active():
            if switch.config["config_name"] in self.usernames:
                saved_user = self.usernames[switch.config["config_name"]]
            else:
                saved_user = ""
            if not self.ok_to_disconnect():
                switch.set_state(False)
                return
            dialog = UserCredDialog(self, switch.config, saved_user)
            response = dialog.run()
            user = dialog.entry_name.get_text()
            password = dialog.entry_password.get_text()
            otp = dialog.entry_otp.get_text()
            dialog.destroy()

            if response != Gtk.ResponseType.OK:
                switch.set_state(False)
                return
            if user != saved_user:
                self.usernames[switch.config["config_name"]] = user
                self.save_user_settings()

            spinner = self.new_spinner("Connecting to " + switch.config["config_name"] + "...")
            ok, err_msg = self.connect_vpn(switch.config, user, password, otp)
            spinner.destroy()

            if not ok:
                self.display_error("Error connecting to " + switch.config["config_name"], err_msg)
                switch.set_state(False)
        else:
            self.disconnect_vpn(switch.config)

#        print(f"Switch was turned {switch.get_active()} for", switch.config["config_name"])
        self.redraw_win()

    def connect_vpn(self, config, user, password, otp):
        while Gtk.events_pending():
            Gtk.main_iteration()
        cfg = self.cmgr.Retrieve(config["config_path"])
        session = self.smgr.NewTunnel(cfg)
        print("Session D-Bus path: " + session.GetPath())
        while Gtk.events_pending():
            Gtk.main_iteration()

#        Set up signal callback handlers and the proper log level
#        session.LogCallback(self._LogHandler)
#        self.__session.StatusChangeCallback(self._StatusHandler)

        # Wait for the backends to settle
        # The GetStatus() method will throw an exception
        # if the backend is not yet ready
        ready = False
        while not ready:
            while Gtk.events_pending():
                Gtk.main_iteration()
            try:
                print("+ Status: " + str(session.GetStatus()))
                ready = True
            except dbus.exceptions.DBusException:
                # If no status is available yet, wait and retry
                time.sleep(1)
                while Gtk.events_pending():
                    Gtk.main_iteration()
        print("Starting connection...")

        # This will run in the background
        with open(self.application.log_filename, "a") as self.f_log:
            subprocess.Popen(["/usr/bin/openvpn3", "log", "--log-level", "6", "--session-path", session.GetPath()],
                             stdout=self.f_log, stderr=self.f_log)

        # Start the VPN connection
        ready = False
        error_msg = None
        while not ready and not error_msg:
            try:
                # Is the backend ready to connect?  If not an exception is thrown
                session.Ready()
                session.Connect()
                ready = True
            except dbus.exceptions.DBusException as e:
                # If this is not about user credentials missing, exit the loop
                if str(e).find(' Missing user credentials') < 1:
                    error_msg = e.get_dbus_message()
                    break
                try:
                    # Query the user for all information the backend has requested
                    for u in session.FetchUserInputSlots():
                        # We only care about responding to credential requests here
                        if u.GetTypeGroup()[0] != openvpn3.ClientAttentionType.CREDENTIALS:
                            continue

                        # Query the user for the information and
                        # send it back to the backend
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
                except dbus.exceptions.DBusException as e2:
                    error_msg = e2.get_dbus_message()
            # Now the while-loop will ensure session.Ready() is re-run

        if not error_msg:
            print("Wait 15 seconds for the backend to get a connection")
            for i in range(1, 150):
                if i % 10 == 0:
                    status = session.GetStatus()
                    if status["major"] == StatusMajor.CONNECTION and status["minor"] == StatusMinor.CONN_CONNECTED:
                        return True, None
                    if status["major"] == StatusMajor.CONNECTION and status["minor"] == StatusMinor.CONN_FAILED:
                        error_msg = "Failed to start the connection"
                        if status["message"]:
                            error_msg += "\n" + status["message"]
                        break
                    if status["major"] == StatusMajor.CONNECTION and status["minor"] == StatusMinor.CONN_AUTH_FAILED:
                        error_msg = "Authentication failed"
                        break
                    print("[%i] Status: %s" % (i, str(session.GetStatus())))
                time.sleep(0.1)
                while Gtk.events_pending():
                    Gtk.main_iteration()
            else:
                status = session.GetStatus()
                error_msg = "Connection timed out.\n" + str(status["major"]) + "\n" + str(status["minor"])
                if status["message"]:
                    error_msg += "\nMessage: " + status["message"]

        # If we are here, we failed to establish a VPN session.
        # Wait for a couple of seconds before terminating the session
        # to allow log writer to capture the logs
        for i in range (0, 10):
            time.sleep(0.2)
            while Gtk.events_pending():
                Gtk.main_iteration()

        # Perform cleanup
        # Session manager is still trying to establish the session in the background
        # So we need to explicitly terminate it
        # Unfortunately, sometimes OpenVPN3 v21 segfaults here :(
        try:
            session.Disconnect()
        except Exception as e:
            self.display_error("Fatal error",
                              "Unexpected error occurred. This is typically caused by backend error,\n"
                              "such as openvpn3 daemon segfault. Please check system log for details.\n"
                              "Session data may be inconsistent, the application will exit now.")
            sys.exit(1)

        return False, error_msg

    def disconnect_vpn(self, config):
        s_path = config["session_path"]
        if s_path is None:
            return
        session = self.smgr.Retrieve(s_path)
        session.Disconnect()


    ##
    #  Simple Log signal callback function.  Called each time a Log event
    #  happens on this session.
    #
    def _LogHandler(self, group, catg, msg):
        loglines = [l for l in msg.split('\n') if len(l) > 0]
        if len(loglines) < 1:
            return

        print('%s %s' % (datetime.datetime.now(), loglines[0]))
        for line in loglines[1:]:
            print('%s%s' % (' ' * 33, line))


    def on_import_profile_clicked(self, widget:Gtk.Button):
        self.idle_counter = 0
        dialog = Gtk.FileChooserDialog(
            title="Import VPN Profile", parent=self, action=Gtk.FileChooserAction.OPEN
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL,
            Gtk.ResponseType.CANCEL,
            Gtk.STOCK_OPEN,
            Gtk.ResponseType.OK,
        )

        self.add_filters(dialog)

        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            if self.is_valid_profile(filename):
                self.connect_dbus()
                self.import_profile(filename)
            else:
                self.display_error("Failed to import profile", "This profile is not valid.")
            self.redraw_win()

    def on_import_profile_action(self, action:Gio.SimpleAction, param):
        self.on_import_profile_clicked(None)

    def add_filters(self, dialog):
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

    def is_valid_profile(self, filename):
        return True

    def import_profile(self, filename):
        fname = os.path.splitext(os.path.basename(filename))[0]
        with open(filename, 'r', encoding="utf-8") as f:
            self.cmgr.Import(fname, f.read(), False, True)

    def on_delete_profile_clicked(self, button, config):
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
            self.disconnect_vpn(config)
            self.cmgr.Retrieve(config["config_path"]).Remove()
            self.redraw_win()

    def auto_exit(self, user_data) -> bool:
        """ Automatically quit the application after 15 minutes of inactivity. """
        self.idle_counter += 1
        if self.idle_counter > 15:
            self.application.quit()
        return True

    def load_user_settings(self):
        if os.path.exists(self.application.settings_filename):
            self.usernames = json.load(open(self.application.settings_filename, encoding="utf-8"))

    def save_user_settings(self):
        json.dump(self.usernames, fp=open(self.application.settings_filename, 'w', encoding="utf-8"), indent=4)

    def on_dark_mode_toggle(self, action: Gio.SimpleAction, value):
        self.idle_counter = 0
        action.set_state(value)
        set_gtk_application_prefer_dark_theme(value.get_boolean())


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

    def do_startup(self):
        Gtk.Application.do_startup(self)

        action = Gio.SimpleAction.new("about", None)
        action.connect("activate", self.on_about)
        self.add_action(action)

        action = Gio.SimpleAction.new("view-log", None)
        action.connect("activate", self.on_view_log)
        self.add_action(action)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)

        self.rotate_log()

    def rotate_log(self):
        if os.path.exists(self.log_filename):
            file_stat = os.stat(self.log_filename)
            if file_stat.st_size > MAX_LOG_SIZE:
                os.rename(self.log_filename, self.log_filename + '.old')

    def on_view_log(self, action, param):
        with open(self.log_filename, 'r', encoding="utf-8") as f:
            win = TextFileWindow(self.log_filename, f.read())
            win.show_all()

    def do_activate(self):
        # We only allow a single window and raise any existing ones
        if not self.window:
            # Windows are associated with the application
            # when the last one is closed the application shuts down
            self.window = AppWindow(application=self, title="OpenVPN3")
            self.window.show_all()
        self.window.present()

    def on_about(self, action, param):
        about_dialog = Gtk.AboutDialog(transient_for=self.window, modal=True)
        about_dialog.set_name           ("OpenVPN3 Linux Frontend GTK3 Application")
        about_dialog.set_version        ("v1.0")
        about_dialog.set_copyright      ("(c) 2023 trengri")
        about_dialog.set_comments       ("Inspired by OpenVPN Connect client")
        about_dialog.set_license        ("GPLv3")
        about_dialog.set_website        ('https://github.com/trengri/ovpn3gui')
        about_dialog.set_website_label  ("GitHub")
        about_dialog.set_authors        (["trengri"])
        about_dialog.set_documenters    (["Nobody"])
        about_dialog.set_artists        (["Nobody"])
        about_dialog.set_logo_icon_name ('network-transmit-receive')
        about_dialog.set_program_name   ("OpenVPN3 Linux Frontend")
        about_dialog.present()

    def on_quit(self, action, param):
        self.quit()


if __name__ == "__main__":
    # Set up the main GLib loop and connect to the system bus
    mainloop = GLib.MainLoop()
    dbusloop = DBusGMainLoop(set_as_default=True)
    sysbus = dbus.SystemBus(mainloop=dbusloop)

    set_gtk_theme_name(get_gtk_theme_name())
    #gs = Gio.Settings.new('org.gnome.desktop.interface')
    #if (gs.get_string('color-scheme') == 'prefer-dark'):
    #  set_gtk_application_prefer_dark_theme(True)

    app = Application()
    app.run(sys.argv)
