.PHONY: test lint docs book book-check know-how relay relay-install relay-update relay-uninstall relay-status relay-logs

# The gates. CI runs all three on every PR (.github/workflows/tests.yml).
# Browser tests need `uv run playwright install chromium`; the encode tests
# skip without ffmpeg on PATH, so a green local run without it proves less.
test:
	uv run pytest -q

lint:
	uv run ruff check auditorium/

# rift lints the agent docs (.rift.yaml). The PyPI package named rift is an
# unrelated project, so the default installs it from GitHub at a pinned tag;
# set RIFT=rift to use a local install.
RIFT ?= uvx -q --from git+https://github.com/apiad/rift@v0.9.0 rift
docs:
	$(RIFT) check

# The book (docs/), built with every block executed: the site, the PDF and the
# gallery of exported examples, all into docs/site/, which CI publishes to
# GitHub Pages. It starts from an empty run cache so every block runs against
# the code as it is; the second render (the PDF) reuses the first one's runs.
SCRIPTORIUM = uv run scriptorium
book:
	rm -rf docs/site docs/build docs/.scriptorium
	$(SCRIPTORIUM) render docs/scriptorium.yaml --only site
	$(SCRIPTORIUM) render docs/scriptorium.yaml --only print
	cp -r docs/build/gallery docs/site/gallery
	cp docs/auditorium.pdf docs/CNAME docs/site/

# scriptorium prints a failing block's output on the page and still exits 0,
# so the grep is what fails the build. tangle --test runs per chapter, because
# given the YAML it finds no blocks and passes. A file under docs/examples/
# that no chapter exports is an orphan tangle cannot see. Every tangled
# project must pass auditorium check, and rift finds every command in the book.
book-check: book
	! grep -l 'class="output error"' docs/site/*.html
	for c in docs/chapters/*.md; do $(SCRIPTORIUM) tangle --test $$c -d docs || exit 1; done
	for e in $$(find docs/examples -type f ! -name __init__.py ! -path '*/dist/*'); do grep -q "export=$${e#docs/}" docs/chapters/*.md || { echo "$$e is not tangled from the book"; exit 1; }; done
	for p in docs/examples/*/; do uv run auditorium check $$p > /dev/null || { echo "$$p fails auditorium check"; exit 1; }; done
	$(RIFT) check

know-how:
	@grep -m1 -H '^when:' know-how/*.md

RELAY_SERVICE = auditorium-relay
SERVICE_FILE = /etc/systemd/system/$(RELAY_SERVICE).service
RELAY_PORT ?= 4243
AUDITORIUM_BIN ?= $(shell command -v auditorium 2>/dev/null || echo "auditorium")

relay:
	auditorium relay --port $(RELAY_PORT)

relay-install:
	@command -v auditorium >/dev/null 2>&1 || { echo "Error: auditorium not found in PATH. Install with: pip install auditorium"; exit 1; }
	@echo "Installing $(RELAY_SERVICE) systemd service..."
	@echo '[Unit]' | sudo tee $(SERVICE_FILE) > /dev/null
	@echo 'Description=Auditorium Relay Server' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo 'After=network.target' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo '' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo '[Service]' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo 'Type=simple' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo 'ExecStart=$(AUDITORIUM_BIN) relay --port $(RELAY_PORT)' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo 'Restart=always' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo 'RestartSec=5' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo '' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo '[Install]' | sudo tee -a $(SERVICE_FILE) > /dev/null
	@echo 'WantedBy=multi-user.target' | sudo tee -a $(SERVICE_FILE) > /dev/null
	sudo systemctl daemon-reload
	sudo systemctl enable $(RELAY_SERVICE)
	sudo systemctl restart $(RELAY_SERVICE)
	@echo ""
	@echo "$(RELAY_SERVICE) installed and running on port $(RELAY_PORT)"
	@echo "Binary: $(AUDITORIUM_BIN)"
	@sudo systemctl status $(RELAY_SERVICE) --no-pager

relay-update:
	git pull
	uv sync
	sudo systemctl restart $(RELAY_SERVICE)
	@sudo systemctl status $(RELAY_SERVICE) --no-pager

relay-uninstall:
	sudo systemctl stop $(RELAY_SERVICE) || true
	sudo systemctl disable $(RELAY_SERVICE) || true
	sudo rm -f $(SERVICE_FILE)
	sudo systemctl daemon-reload
	@echo "$(RELAY_SERVICE) removed"

relay-status:
	sudo systemctl status $(RELAY_SERVICE) --no-pager

relay-logs:
	sudo journalctl -u $(RELAY_SERVICE) -f
