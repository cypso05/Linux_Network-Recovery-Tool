# Network Recovery Tool Makefile
# Version: 1.1.0

VERSION = 1.1.0
PREFIX ?= /usr/local
BINDIR = $(PREFIX)/bin
LIBDIR = $(PREFIX)/lib/network-recover
DESKTOPDIR = $(PREFIX)/share/applications
POLKITDIR = $(PREFIX)/share/polkit-1/actions
LOGDIR = /var/log/network-events
SNAPSHOTDIR = /var/lib/network-recover/snapshots

# Colors for output
GREEN = \033[0;32m
RED = \033[0;31m
YELLOW = \033[1;33m
NC = \033[0m

.PHONY: all install uninstall test help

all: install

install:
	@echo "Installing network-recover v$(VERSION)..."
	@echo "  PREFIX: $(PREFIX)"
	@echo ""
	
	# Create directories
	@mkdir -p $(BINDIR) $(LIBDIR) $(DESKTOPDIR) $(POLKITDIR) $(LOGDIR) $(SNAPSHOTDIR)
	@echo "  ✅ Directories created"
	
	# Install core engine
	@if [ -f src/network-recover ]; then \
		install -m 755 src/network-recover $(BINDIR)/ && \
		echo "  ✅ Core engine: $(BINDIR)/network-recover"; \
	else \
		echo "  ❌ src/network-recover not found"; \
		exit 1; \
	fi
	
	# Install GUI wrapper
	@if [ -f src/network-recover-gui ]; then \
		install -m 755 src/network-recover-gui $(BINDIR)/ && \
		echo "  ✅ GUI wrapper: $(BINDIR)/network-recover-gui"; \
	else \
		echo "  ⚠️  src/network-recover-gui not found (optional)"; \
	fi
	
	# Install desktop file
	@if [ -f desktop/network-recover.desktop ]; then \
		install -m 644 desktop/network-recover.desktop $(DESKTOPDIR)/ && \
		echo "  ✅ Desktop entry: $(DESKTOPDIR)/network-recover.desktop"; \
	else \
		echo "  ⚠️  desktop/network-recover.desktop not found"; \
	fi
	
	# Install modular components
	@if [ -d diagnostics ]; then \
		cp -r diagnostics $(LIBDIR)/ && \
		chmod -R 755 $(LIBDIR)/diagnostics && \
		echo "  ✅ diagnostics/ installed ($(shell ls -1 diagnostics 2>/dev/null | wc -l) modules)"; \
	fi
	
	@if [ -d repairs ]; then \
		cp -r repairs $(LIBDIR)/ && \
		chmod -R 755 $(LIBDIR)/repairs && \
		echo "  ✅ repairs/ installed ($(shell ls -1 repairs 2>/dev/null | wc -l) modules)"; \
	fi
	
	@if [ -d collectors ]; then \
		cp -r collectors $(LIBDIR)/ && \
		chmod -R 755 $(LIBDIR)/collectors && \
		echo "  ✅ collectors/ installed ($(shell ls -1 collectors 2>/dev/null | wc -l) modules)"; \
	fi
	
	# Install polkit policy
	@if [ -f polkit/com.network-recover.policy ]; then \
		install -m 644 polkit/com.network-recover.policy $(POLKITDIR)/ && \
		echo "  ✅ Polkit policy: $(POLKITDIR)/com.network-recover.policy"; \
	else \
		echo "  ⚠️  polkit/com.network-recover.policy not found"; \
	fi
	
	# Update desktop database
	@update-desktop-database $(DESKTOPDIR) 2>/dev/null || true
	
	@echo ""
	@echo "=============================================="
	@echo "  ✅ INSTALLATION COMPLETE!"
	@echo "=============================================="
	@echo ""
	@echo "  Quick commands:"
	@echo "    sudo network-recover diagnose"
	@echo "    sudo network-recover repair"
	@echo "    sudo network-recover status"
	@echo "    sudo network-recover snapshot"
	@echo "    sudo network-recover watch"
	@echo ""
	@echo "  Panel integration:"
	@echo "    sudo ./integration/xfce-integration.sh"
	@echo ""

uninstall:
	@echo "Uninstalling network-recover v$(VERSION)..."
	@echo ""
	
	# Remove binaries
	@rm -f $(BINDIR)/network-recover && echo "  ✅ Removed: $(BINDIR)/network-recover" || echo "  ⚠️  Not found: $(BINDIR)/network-recover"
	@rm -f $(BINDIR)/network-recover-gui && echo "  ✅ Removed: $(BINDIR)/network-recover-gui" || echo "  ⚠️  Not found: $(BINDIR)/network-recover-gui"
	
	# Remove desktop file
	@rm -f $(DESKTOPDIR)/network-recover.desktop && echo "  ✅ Removed: $(DESKTOPDIR)/network-recover.desktop" || echo "  ⚠️  Not found: $(DESKTOPDIR)/network-recover.desktop"
	
	# Remove polkit policy
	@rm -f $(POLKITDIR)/com.network-recover.policy && echo "  ✅ Removed: $(POLKITDIR)/com.network-recover.policy" || echo "  ⚠️  Not found: $(POLKITDIR)/com.network-recover.policy"
	
	# Remove modules
	@rm -rf $(LIBDIR) && echo "  ✅ Removed: $(LIBDIR)" || echo "  ⚠️  Not found: $(LIBDIR)"
	
	# Remove logs and snapshots (ask confirmation)
	@echo "  ⚠️  Removing logs and snapshots:"
	@rm -rf $(LOGDIR) && echo "  ✅ Removed: $(LOGDIR)" || echo "  ⚠️  Not found: $(LOGDIR)"
	@rm -rf $(SNAPSHOTDIR) && echo "  ✅ Removed: $(SNAPSHOTDIR)" || echo "  ⚠️  Not found: $(SNAPSHOTDIR)"
	
	# Update desktop database
	@update-desktop-database $(DESKTOPDIR) 2>/dev/null || true
	
	@echo ""
	@echo "=============================================="
	@echo "  ✅ UNINSTALLATION COMPLETE!"
	@echo "=============================================="

test:
	@echo "Running tests..."
	@bash tests/test-manual.sh

help:
	@echo "Network Recovery Tool Makefile"
	@echo ""
	@echo "  make install   - Install the tool"
	@echo "  make uninstall - Remove the tool"
	@echo "  make test      - Run tests"
	@echo "  make help      - Show this help"
	@echo ""
	@echo "Variables:"
	@echo "  PREFIX=$(PREFIX)  - Installation prefix"
	@echo "  VERSION=$(VERSION) - Tool version"