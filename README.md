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
1. Install [OpenVPN3Linux](https://community.openvpn.net/openvpn/wiki/OpenVPN3Linux)
2. Enter the following commands:
   ```
   git clone https://github.com/trengri/ovpn3gui.git
   cd ovpn3gui
   make install
   ```
## Usage
Launch OpenVPN3 icon from GNOME

## Uninstall
   ```
   cd ovpn3gui
   make uninstall
   ```
