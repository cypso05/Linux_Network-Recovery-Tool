PREFIX ?= /usr/local
BINDIR = $(PREFIX)/bin
DESKTOPDIR = $(PREFIX)/share/applications

.PHONY: all install uninstall test

all: install

install:
    @echo "Installing network-recover..."
    @mkdir -p $(BINDIR) $(DESKTOPDIR)
    @install -m 755 src/network-recover $(BINDIR)/
    @install -m 755 src/network-recover-gui $(BINDIR)/
    @install -m 644 desktop/network-recover.desktop $(DESKTOPDIR)/
    @echo "✅ Installation complete!"

uninstall:
    @echo "Uninstalling network-recover..."
    @rm -f $(BINDIR)/network-recover
    @rm -f $(BINDIR)/network-recover-gui
    @rm -f $(DESKTOPDIR)/network-recover.desktop
    @echo "✅ Uninstallation complete!"

test:
    @echo "Running tests..."
    @bash tests/test-manual.sh

help:
    @echo "make install - Install the tool"
    @echo "make uninstall - Remove the tool"
    @echo "make test - Run tests"
