INSTALL_DIR=/opt/ovpn3gui

all:

install: ovpn3gui.py ovpn3gui.png ovpn3gui.desktop
	install -m 755 -d $(INSTALL_DIR)
	install -m 644 ovpn3gui.py ovpn3gui.png $(INSTALL_DIR)
	install -m 644 ovpn3gui.desktop /usr/share/applications

uninstall:
	rm $(INSTALL_DIR)/ovpn3gui.py $(INSTALL_DIR)/ovpn3gui.png
	rmdir $(INSTALL_DIR)
	rm /usr/share/applications/ovpn3gui.desktop

.PHONY: install
