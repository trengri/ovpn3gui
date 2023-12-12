# OpenVPN3 Linux Frontend

## Features
* Supports multiple OpenVPN profiles
* Supports OTP static challenge authentication
* Lightweight GTK3 interface, looks similar to macOS/Windows OpenVPN Connect client
* Uses OpenVPN3 frontend API instead of calling `openvpn3 session-start`, `openvpn3 config-import` programs

## Screenshots
![изображение](https://github.com/trengri/ovpn3gui/assets/53753844/c9dc85e2-c57e-45fc-bb53-b7a23b77cd82)
![изображение](https://github.com/trengri/ovpn3gui/assets/53753844/116bcfa7-fa21-4e48-b22a-0071ce771719)

## Installation
1. Install [OpenVPN3Linux](https://community.openvpn.net/openvpn/wiki/OpenVPN3Linux).
2. Copy `ovpn3gui.py` and `ovpn3gui.png` files to `/opt/ovpn3gui` or any other directory.
3. Put `ovpn3gui.desktop` file to `/usr/share/applications`. Make to edit it to match the directory from step 2.
