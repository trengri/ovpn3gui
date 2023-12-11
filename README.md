# OpenVPN3 Linux Frontend

## Features
* Supports multiple OpenVPN profiles
* Supports OTP static challenge authentication
* Lightweight GTK3 interface
* Uses OpenVPN3 Python API instead of calling `openvpn3 session-start`, `openvpn3 config-import` programs

## Screenshots
![изображение](https://github.com/trengri/ovpn3gui/assets/53753844/c88788ff-14dc-4223-ab3e-5f8c9caaef22)
![изображение](https://github.com/trengri/ovpn3gui/assets/53753844/8f57fb91-e8cb-46bd-b133-6b99d8f5506c)
![изображение](https://github.com/trengri/ovpn3gui/assets/53753844/98d0c017-3177-4e8b-91ae-b8701916b641)


## Installation
Copy ovpn3gui.py and ovpn3gui.png files to /opt/ovpn3gui or any other directory (make sure to edit ovpn3gui.desktop file if you use another directory).
Put ovpn3gui.desktop file to /usr/share/applications.
