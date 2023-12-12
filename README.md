# OpenVPN3 Linux Frontend

## Features
* Supports multiple OpenVPN profiles
* Supports OTP static challenge authentication
* Lightweight GTK3 interface, looks similar to macOS/Windows OpenVPN Connect client
* Uses OpenVPN3 frontend API instead of calling `openvpn3 session-start`, `openvpn3 config-import` programs

## Screenshots
![изображение](https://github.com/trengri/ovpn3gui/assets/53753844/98d0c017-3177-4e8b-91ae-b8701916b641)
![изображение](https://github.com/trengri/ovpn3gui/assets/53753844/8f57fb91-e8cb-46bd-b133-6b99d8f5506c)



## Installation
1. Install [OpenVPN3Linux](https://community.openvpn.net/openvpn/wiki/OpenVPN3Linux).
2. Copy `ovpn3gui.py` and `ovpn3gui.png` files to `/opt/ovpn3gui` or any other directory.
3. Put `ovpn3gui.desktop` file to `/usr/share/applications`. Make to edit it to match the directory from step 2.
