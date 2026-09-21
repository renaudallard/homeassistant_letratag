/**
 * DYMO LetraTag Lovelace Card
 *
 * Custom card for printing labels from the Home Assistant UI.
 * Provides text input, font/size selection, banner mode toggle,
 * and a live label preview.
 */

// Integration domain, used for the service call and to pick out this
// integration's entities in the registry.
const DOMAIN = "letratag";

// Built-in font display names, shared by the dropdown and config validation.
// Must stay in sync with FONT_MAP in const.py and the _cssFontFamily map.
const FONTS = [
  "DejaVu Sans Bold",
  "DejaVu Mono Bold",
  "DejaVu Serif Bold",
  "Liberation Sans Bold",
  "FreeSans Bold",
  "Roboto Bold",
  "Noto Serif Bold",
  "Courgette Bold",
  "Sancreek Bold",
  "Noto Sans Bold",
  "Open Sans Bold",
  "Source Sans 3 Bold",
  "Inter Bold",
  "Fira Sans Bold",
  "Oswald Bold",
  "Archivo Narrow Bold",
  "Bebas Neue",
  "Merriweather Bold",
  "Roboto Slab Bold",
  "JetBrains Mono Bold",
  "IBM Plex Mono Bold",
];

class LetraTagCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._sensorSignature = null;
    this._printerSignature = null;
    this._printerList = [];
    this._state = {
      text: "",
      fontName: "DejaVu Sans Bold",
      fontSize: 0, // 0 = auto
      rotate: false,
      address: null, // which printer, when more than one is configured
      copies: 1,
      printing: false,
      message: "",
      messageType: "",
    };
  }

  setConfig(config) {
    this._config = config;
    this._applyConfigDefaults(config);
    this._render();
  }

  _applyConfigDefaults(config) {
    // Optional card defaults. default_font must be a known font, otherwise
    // the built-in default is kept. default_size is an explicit 8-32 px size;
    // anything else (omitted, 0, out of range) means auto.
    if (FONTS.includes(config.default_font)) {
      this._state.fontName = config.default_font;
    }
    const size = parseInt(config.default_size, 10);
    this._state.fontSize =
      Number.isInteger(size) && size > 0 ? Math.min(Math.max(size, 8), 32) : 0;
  }

  set hass(hass) {
    this._hass = hass;
    this._updatePrinters();
    this._updateSensors();
  }

  getCardSize() {
    return 5;
  }

  static getStubConfig() {
    return {};
  }

  static getConfigForm() {
    // Native ha-form editor shown in the dashboard card editor. HA renders
    // these selectors itself; every field is optional and maps to the YAML
    // keys. Leaving the size empty keeps the automatic size.
    return {
      schema: [
        { name: "title", selector: { text: {} } },
        {
          name: "default_font",
          selector: { select: { mode: "dropdown", options: FONTS } },
        },
        {
          name: "default_size",
          selector: {
            number: {
              min: 8,
              max: 32,
              step: 1,
              mode: "box",
              unit_of_measurement: "px",
            },
          },
        },
      ],
      computeLabel: (schema) => {
        switch (schema.name) {
          case "title":
            return "Title";
          case "default_font":
            return "Default font";
          case "default_size":
            return "Default size";
          default:
            return undefined;
        }
      },
      computeHelper: (schema) =>
        schema.name === "default_size" ? "Leave empty for automatic size" : undefined,
    };
  }

  _updateState(key, value) {
    this._state[key] = value;
    this._updatePreview();
  }

  _printers() {
    // Every printer is a device of this integration, and its address is the
    // device identifier, so the card never has to be told a MAC.
    const devices = this._hass.devices || {};
    return Object.values(devices)
      .map((d) => {
        const identifier = (d.identifiers || []).find(([domain]) => domain === DOMAIN);
        return identifier
          ? {
              deviceId: d.id,
              address: identifier[1],
              name: d.name_by_user || d.name || identifier[1],
            }
          : null;
      })
      .filter(Boolean)
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  _selectedDeviceId() {
    const printer = this._printerList.find((p) => p.address === this._state.address);
    return printer ? printer.deviceId : null;
  }

  _updatePrinters() {
    if (!this._hass || !this.shadowRoot) return;
    const field = this.shadowRoot.getElementById("printer-field");
    const select = this.shadowRoot.getElementById("printer-select");
    if (!field || !select) return;

    const printers = this._printers();
    this._printerList = printers;

    const signature = printers.map((p) => `${p.address}\u0000${p.name}`).join("\u0001");
    const selectable =
      !printers.length || printers.some((p) => p.address === this._state.address);
    if (signature === this._printerSignature && selectable) return;
    this._printerSignature = signature;

    if (!selectable) {
      this._state.address = printers[0].address;
      this._sensorSignature = null;
    }

    select.textContent = "";
    for (const printer of printers) {
      const option = document.createElement("option");
      option.value = printer.address;
      option.textContent = printer.name;
      select.appendChild(option);
    }
    select.value = this._state.address || "";

    // With a single printer there is nothing to choose, so stay out of the way
    field.classList.toggle("hidden", printers.length < 2);
  }

  _sensorEntityIds() {
    // Ask the entity registry which entities this integration owns. Matching
    // on the entity id instead meant a renamed device hid the sensors and an
    // unrelated entity with "dymo" in its id showed up as one of ours.
    const registry = this._hass.entities || {};
    const deviceId = this._selectedDeviceId();
    return Object.keys(registry)
      .filter(
        (eid) =>
          eid.startsWith("sensor.") &&
          registry[eid].platform === DOMAIN &&
          (!deviceId || registry[eid].device_id === deviceId)
      )
      .sort();
  }

  _updateSensors() {
    if (!this._hass || !this.shadowRoot) return;
    const statusEl = this.shadowRoot.getElementById("sensor-status");
    if (!statusEl) return;

    const shown = this._sensorEntityIds()
      .map((eid) => this._hass.states[eid])
      .filter((s) => s && s.state !== "unavailable" && s.state !== "unknown");

    // Home Assistant hands the card a new hass on every state change in the
    // whole instance, so only touch the DOM when a chip would actually differ.
    const signature = shown
      .map((s) => `${s.entity_id}\u0000${s.state}\u0000${s.attributes.friendly_name}\u0000${s.attributes.icon}`)
      .join("\u0001");
    if (signature === this._sensorSignature) return;
    this._sensorSignature = signature;

    statusEl.textContent = "";
    for (const s of shown) {
      const name = s.attributes.friendly_name || s.entity_id.split(".")[1];
      const icon = s.attributes.icon || "mdi:printer";
      const chip = document.createElement("span");
      chip.className = "sensor-chip";
      chip.title = s.entity_id;
      const haIcon = document.createElement("ha-icon");
      haIcon.setAttribute("icon", icon);
      chip.appendChild(haIcon);
      const label = document.createElement("span");
      label.textContent = ` ${name}: `;
      chip.appendChild(label);
      const val = document.createElement("b");
      val.textContent = s.state;
      chip.appendChild(val);
      statusEl.appendChild(chip);
    }
  }

  _updatePreview() {
    const preview = this.shadowRoot?.getElementById("label-preview");
    const previewText = this.shadowRoot?.getElementById("preview-text");
    if (!preview || !previewText) return;

    const text = this._state.text || "Label Preview";
    const rotate = this._state.rotate;

    previewText.textContent = text;
    previewText.style.fontFamily = this._cssFontFamily();

    const sizeVal = this._state.fontSize;
    if (sizeVal > 0) {
      // Scale preview font: printer is 32px tall, preview box is ~48px
      const scale = 48 / 32;
      previewText.style.fontSize = `${Math.round(sizeVal * scale)}px`;
    } else {
      previewText.style.fontSize = "";
    }

    if (rotate) {
      preview.classList.add("banner");
      preview.classList.remove("normal");
    } else {
      preview.classList.add("normal");
      preview.classList.remove("banner");
    }
  }

  _cssFontFamily() {
    const map = {
      "DejaVu Sans Bold": "'DejaVu Sans', Arial, Helvetica, sans-serif",
      "DejaVu Mono Bold": "'DejaVu Sans Mono', 'Courier New', monospace",
      "DejaVu Serif Bold": "'DejaVu Serif', Georgia, 'Times New Roman', serif",
      "Liberation Sans Bold": "'Liberation Sans', Arial, Helvetica, sans-serif",
      "FreeSans Bold": "'FreeSans', Arial, Helvetica, sans-serif",
      "Roboto Bold": "'Roboto', Arial, Helvetica, sans-serif",
      "Noto Serif Bold": "'Noto Serif', Georgia, 'Times New Roman', serif",
      "Courgette Bold": "'Courgette', cursive",
      "Sancreek Bold": "'Sancreek', fantasy",
      "Noto Sans Bold": "'Noto Sans', Arial, Helvetica, sans-serif",
      "Open Sans Bold": "'Open Sans', Arial, Helvetica, sans-serif",
      "Source Sans 3 Bold": "'Source Sans 3', 'Source Sans Pro', Arial, sans-serif",
      "Inter Bold": "'Inter', Arial, Helvetica, sans-serif",
      "Fira Sans Bold": "'Fira Sans', Arial, Helvetica, sans-serif",
      "Oswald Bold": "'Oswald', 'Arial Narrow', sans-serif",
      "Archivo Narrow Bold": "'Archivo Narrow', 'Arial Narrow', sans-serif",
      "Bebas Neue": "'Bebas Neue', 'Arial Narrow', sans-serif",
      "Merriweather Bold": "'Merriweather', Georgia, 'Times New Roman', serif",
      "Roboto Slab Bold": "'Roboto Slab', Georgia, serif",
      "JetBrains Mono Bold": "'JetBrains Mono', 'Courier New', monospace",
      "IBM Plex Mono Bold": "'IBM Plex Mono', 'Courier New', monospace",
    };
    return map[this._state.fontName] || "sans-serif";
  }

  async _print() {
    if (!this._hass || !this._state.text.trim()) return;

    this._state.printing = true;
    this._state.message = "";
    this._setButtonState();

    const data = {
      text: this._state.text,
      copies: this._state.copies,
      font_name: this._state.fontName,
      rotate: this._state.rotate,
    };
    if (this._state.fontSize > 0) {
      data.font_size = this._state.fontSize;
    }
    if (this._state.address) {
      data.address = this._state.address;
    }

    try {
      await this._hass.callService(DOMAIN, "print_label", data);
      this._state.message = "Print sent successfully";
      this._state.messageType = "success";
    } catch (err) {
      this._state.message = err.message || "Print failed";
      this._state.messageType = "error";
    }

    this._state.printing = false;
    this._setButtonState();
    this._showMessage();
  }

  _setButtonState() {
    const btn = this.shadowRoot?.getElementById("print-btn");
    if (!btn) return;
    btn.disabled = this._state.printing;
    btn.textContent = this._state.printing ? "Printing..." : "Print";
  }

  _showMessage() {
    const el = this.shadowRoot?.getElementById("message");
    if (!el) return;
    el.textContent = this._state.message;
    el.className = `message ${this._state.messageType}`;
    if (this._msgTimer) clearTimeout(this._msgTimer);
    if (this._state.message) {
      this._msgTimer = setTimeout(() => {
        el.textContent = "";
        el.className = "message";
        this._msgTimer = null;
      }, 5000);
    }
  }

  _render() {
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          --card-bg: var(--ha-card-background, var(--card-background-color, #fff));
          --primary: var(--primary-color, #03a9f4);
          --primary-text: var(--primary-text-color, #212121);
          --secondary-text: var(--secondary-text-color, #727272);
          --divider: var(--divider-color, #e0e0e0);
          --radius: var(--ha-card-border-radius, 12px);
          --error-color: var(--error-color, #db4437);
          --success-color: var(--success-color, #43a047);
        }

        ha-card {
          overflow: hidden;
        }

        .card-header {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 16px 16px 8px;
          font-size: 1.1em;
          font-weight: 500;
          color: var(--primary-text);
        }

        .card-header ha-icon {
          color: var(--primary);
          --mdc-icon-size: 28px;
        }

        .card-content {
          padding: 8px 16px 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        /* Label preview */
        .preview-container {
          background: var(--divider);
          border-radius: 8px;
          padding: 12px;
          display: flex;
          justify-content: center;
          align-items: center;
          min-height: 60px;
        }

        .label-tape {
          background: #fff;
          border: 1.5px solid #ccc;
          display: flex;
          align-items: center;
          justify-content: center;
          overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,0.12);
          transition: all 0.3s ease;
        }

        .label-tape.normal {
          height: 48px;
          min-width: 120px;
          max-width: 100%;
          padding: 0 16px;
          border-radius: 4px 24px 24px 4px;
        }

        .label-tape.banner {
          width: 48px;
          min-height: 90px;
          max-height: 200px;
          padding: 12px 0;
          border-radius: 24px 24px 4px 4px;
          flex-direction: column;
        }

        .preview-text {
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          font-weight: 700;
          font-size: 18px;
          color: #1a1a1a;
          line-height: 1.1;
          user-select: none;
          transition: all 0.3s ease;
        }

        .banner .preview-text {
          writing-mode: vertical-rl;
          text-orientation: mixed;
          white-space: nowrap;
          font-size: 22px;
          letter-spacing: 2px;
        }

        /* Sensor chips */
        .sensors {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .sensor-chip {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 0.78em;
          color: var(--secondary-text);
          background: var(--divider);
          border-radius: 12px;
          padding: 2px 10px;
        }

        .sensor-chip ha-icon {
          --mdc-icon-size: 14px;
        }

        /* Text input */
        textarea {
          width: 100%;
          min-height: 56px;
          padding: 10px 12px;
          border: 1.5px solid var(--divider);
          border-radius: 8px;
          font-family: inherit;
          font-size: 0.95em;
          color: var(--primary-text);
          background: var(--card-bg);
          resize: vertical;
          box-sizing: border-box;
          transition: border-color 0.2s;
          outline: none;
        }

        textarea:focus {
          border-color: var(--primary);
        }

        textarea::placeholder {
          color: var(--secondary-text);
          opacity: 0.7;
        }

        /* Controls grid */
        .controls {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 10px;
        }

        @media (max-width: 400px) {
          .controls {
            grid-template-columns: 1fr;
          }
        }

        .field {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }

        .field label {
          font-size: 0.78em;
          font-weight: 500;
          color: var(--secondary-text);
          text-transform: uppercase;
          letter-spacing: 0.5px;
        }

        select, input[type="number"] {
          width: 100%;
          padding: 8px 10px;
          border: 1.5px solid var(--divider);
          border-radius: 8px;
          font-family: inherit;
          font-size: 0.9em;
          color: var(--primary-text);
          background: var(--card-bg);
          box-sizing: border-box;
          outline: none;
          transition: border-color 0.2s;
          -webkit-appearance: none;
          appearance: none;
        }

        select {
          background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath d='M6 8L1 3h10z' fill='%23727272'/%3E%3C/svg%3E");
          background-repeat: no-repeat;
          background-position: right 10px center;
          padding-right: 28px;
        }

        select:focus, input:focus {
          border-color: var(--primary);
        }

        /* Size slider row */
        .size-row {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .size-row input[type="range"] {
          flex: 1;
          height: 4px;
          -webkit-appearance: none;
          appearance: none;
          background: var(--divider);
          border-radius: 2px;
          outline: none;
        }

        .size-row input[type="range"]::-webkit-slider-thumb {
          -webkit-appearance: none;
          width: 18px;
          height: 18px;
          background: var(--primary);
          border-radius: 50%;
          cursor: pointer;
        }

        .size-row input[type="range"]::-moz-range-thumb {
          width: 18px;
          height: 18px;
          background: var(--primary);
          border: none;
          border-radius: 50%;
          cursor: pointer;
        }

        .size-value {
          min-width: 32px;
          text-align: center;
          font-size: 0.85em;
          font-weight: 600;
          color: var(--primary-text);
        }

        /* Mode toggle */
        .mode-toggle {
          display: flex;
          border: 1.5px solid var(--divider);
          border-radius: 8px;
          overflow: hidden;
        }

        .mode-btn {
          flex: 1;
          padding: 8px 4px;
          border: none;
          background: transparent;
          font-family: inherit;
          font-size: 0.82em;
          font-weight: 500;
          color: var(--secondary-text);
          cursor: pointer;
          transition: all 0.2s;
          text-align: center;
        }

        .mode-btn.active {
          background: var(--primary);
          color: #fff;
        }

        .mode-btn:not(.active):hover {
          background: var(--divider);
        }

        /* Bottom row */
        .bottom-row {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .option {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 0.85em;
          color: var(--primary-text);
          white-space: nowrap;
        }

        .option input[type="checkbox"] {
          width: 16px;
          height: 16px;
          accent-color: var(--primary);
        }

        .option input[type="number"] {
          width: 52px;
          padding: 4px 6px;
          text-align: center;
        }

        /* Print button */
        .print-btn {
          width: 100%;
          padding: 12px;
          border: none;
          border-radius: 10px;
          background: var(--primary);
          color: #fff;
          font-family: inherit;
          font-size: 1em;
          font-weight: 600;
          cursor: pointer;
          transition: opacity 0.2s, transform 0.1s;
          letter-spacing: 0.5px;
        }

        .print-btn:hover:not(:disabled) {
          opacity: 0.9;
        }

        .print-btn:active:not(:disabled) {
          transform: scale(0.98);
        }

        .print-btn:disabled {
          opacity: 0.5;
          cursor: not-allowed;
        }

        /* Message */
        .message {
          font-size: 0.85em;
          text-align: center;
          min-height: 1.2em;
          transition: color 0.2s;
        }

        .hidden { display: none; }

        .message.success { color: var(--success-color); }
        .message.error { color: var(--error-color); }
      </style>

      <ha-card>
        <div class="card-header">
          <ha-icon icon="mdi:label-variant"></ha-icon>
          <span id="card-title"></span>
        </div>

        <div class="card-content">
          <div id="sensor-status" class="sensors"></div>

          <div class="preview-container">
            <div id="label-preview" class="label-tape normal">
              <span id="preview-text" class="preview-text">Label Preview</span>
            </div>
          </div>

          <textarea
            id="text-input"
            placeholder="Enter label text..."
            rows="2"
          ></textarea>

          <div class="controls">
            <div class="field hidden" id="printer-field" style="grid-column: 1 / -1">
              <label for="printer-select">Printer</label>
              <select id="printer-select"></select>
            </div>

            <div class="field">
              <label>Font</label>
              <select id="font-select">
                ${FONTS.map((f) => `<option value="${f}">${f}</option>`).join("")}
              </select>
            </div>

            <div class="field">
              <label>Mode</label>
              <div class="mode-toggle">
                <button class="mode-btn active" data-mode="normal">Normal</button>
                <button class="mode-btn" data-mode="banner">Banner 90&deg;</button>
              </div>
            </div>

            <div class="field" style="grid-column: 1 / -1">
              <label>Size <span id="size-label">(auto)</span></label>
              <div class="size-row">
                <input type="range" id="size-slider" min="8" max="33" value="33" step="1">
                <span id="size-value" class="size-value">Auto</span>
              </div>
            </div>
          </div>

          <div class="bottom-row">
            <div class="option">
              <label for="copies-input">Copies</label>
              <input type="number" id="copies-input" value="1" min="1" max="255">
            </div>
            <div style="flex:1"></div>
          </div>

          <button id="print-btn" class="print-btn">Print</button>
          <div id="message" class="message"></div>
        </div>
      </ha-card>
    `;

    this._attachListeners();
    this._syncControls();
    this._updatePreview();

    // Set title via textContent to prevent XSS
    const titleEl = this.shadowRoot.getElementById("card-title");
    if (titleEl) titleEl.textContent = this._config.title || "DYMO LetraTag";

    // Both rows went out with the old DOM, so rebuild them from scratch
    this._printerSignature = null;
    this._sensorSignature = null;
    this._updatePrinters();
    this._updateSensors();
  }

  _syncControls() {
    // Reflect the runtime state into the freshly rendered controls so
    // configured defaults show up. The HTML template only carries the
    // built-in defaults; everything else is applied here.
    const $ = (id) => this.shadowRoot.getElementById(id);

    const fontSel = $("font-select");
    if (fontSel) fontSel.value = this._state.fontName;

    const slider = $("size-slider");
    const sizeValue = $("size-value");
    const sizeLabel = $("size-label");
    if (!slider || !sizeValue) return;

    if (this._state.fontSize > 0) {
      slider.value = this._state.fontSize;
      sizeValue.textContent = `${this._state.fontSize}px`;
      if (sizeLabel) sizeLabel.textContent = "";
    } else {
      slider.value = slider.max;
      sizeValue.textContent = "Auto";
      if (sizeLabel) sizeLabel.textContent = "(auto)";
    }
  }

  _attachListeners() {
    const $ = (id) => this.shadowRoot.getElementById(id);

    // Text input
    $("text-input").addEventListener("input", (e) => {
      this._updateState("text", e.target.value);
    });

    // Printer select, only on screen when there is more than one
    $("printer-select").addEventListener("change", (e) => {
      this._state.address = e.target.value;
      this._sensorSignature = null;
      this._updateSensors();
    });

    // Font select
    $("font-select").addEventListener("change", (e) => {
      this._updateState("fontName", e.target.value);
    });

    // Size slider: 8..32 explicit, rightmost position = auto (biggest)
    $("size-slider").addEventListener("input", (e) => {
      const raw = parseInt(e.target.value, 10);
      const max = parseInt(e.target.max, 10);
      const isAuto = raw >= max;
      this._state.fontSize = isAuto ? 0 : raw;
      $("size-value").textContent = isAuto ? "Auto" : `${raw}px`;
      const sizeLabel = $("size-label");
      if (sizeLabel) sizeLabel.textContent = isAuto ? "(auto)" : "";
      this._updatePreview();
    });

    // Mode toggle
    for (const btn of this.shadowRoot.querySelectorAll(".mode-btn")) {
      btn.addEventListener("click", () => {
        const isRotate = btn.dataset.mode === "banner";
        this._state.rotate = isRotate;

        for (const b of this.shadowRoot.querySelectorAll(".mode-btn")) {
          b.classList.toggle("active", b === btn);
        }

        // Adjust size slider max for banner mode (last position = auto)
        const slider = $("size-slider");
        slider.max = isRotate ? "65" : "33";
        slider.value = slider.max;
        this._state.fontSize = 0;
        $("size-value").textContent = "Auto";
        const sizeLabel = $("size-label");
        if (sizeLabel) sizeLabel.textContent = "(auto)";

        this._updatePreview();
      });
    }

    // Copies
    $("copies-input").addEventListener("change", (e) => {
      this._state.copies = Math.max(1, Math.min(255, parseInt(e.target.value, 10) || 1));
      e.target.value = this._state.copies;
    });

    // Print button
    $("print-btn").addEventListener("click", () => this._print());

    // Ctrl+Enter to print
    $("text-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        this._print();
      }
    });
  }
}

customElements.define("letratag-card", LetraTagCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "letratag-card",
  name: "DYMO LetraTag",
  description: "Print labels on your DYMO LetraTag 200B",
  preview: true,
});
