/**
 * DYMO LetraTag Lovelace Card
 *
 * Custom card for printing labels from the Home Assistant UI.
 * Provides text input, font/size selection, banner mode toggle,
 * and a live label preview.
 */

class LetraTagCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._state = {
      text: "",
      fontName: "DejaVu Sans Bold",
      fontSize: 0, // 0 = auto
      rotate: false,
      copies: 1,
      cut: true,
      printing: false,
      message: "",
      messageType: "",
    };
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Update sensor displays if entities configured
    this._updateSensors();
  }

  getCardSize() {
    return 5;
  }

  static getStubConfig() {
    return {};
  }

  _updateState(key, value) {
    this._state[key] = value;
    this._updatePreview();
  }

  _updateSensors() {
    if (!this._hass || !this.shadowRoot) return;
    const statusEl = this.shadowRoot.getElementById("sensor-status");
    if (!statusEl) return;

    // Find letratag sensors
    const entities = Object.keys(this._hass.states).filter((e) =>
      e.startsWith("sensor.") && (
        e.includes("letratag") || e.includes("dymo")
      )
    );

    statusEl.textContent = "";
    for (const eid of entities) {
      const s = this._hass.states[eid];
      if (!s) continue;
      const name = s.attributes.friendly_name || eid.split(".")[1];
      const icon = s.attributes.icon || "mdi:printer";
      const chip = document.createElement("span");
      chip.className = "sensor-chip";
      chip.title = eid;
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
      // Scale preview font: printer is 26px tall, preview box is ~48px
      const scale = 48 / 26;
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
      cut: this._state.cut,
      font_name: this._state.fontName,
      rotate: this._state.rotate,
    };
    if (this._state.fontSize > 0) {
      data.font_size = this._state.fontSize;
    }

    try {
      await this._hass.callService("letratag", "print_label", data);
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
    const fonts = [
      "DejaVu Sans Bold",
      "DejaVu Mono Bold",
      "DejaVu Serif Bold",
      "Liberation Sans Bold",
      "FreeSans Bold",
    ];

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
            <div class="field">
              <label>Font</label>
              <select id="font-select">
                ${fonts.map((f) => `<option value="${f}">${f}</option>`).join("")}
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
                <input type="range" id="size-slider" min="8" max="27" value="27" step="1">
                <span id="size-value" class="size-value">Auto</span>
              </div>
            </div>
          </div>

          <div class="bottom-row">
            <div class="option">
              <label for="copies-input">Copies</label>
              <input type="number" id="copies-input" value="1" min="1" max="255">
            </div>
            <div class="option">
              <input type="checkbox" id="cut-check" checked>
              <label for="cut-check">Cut tape</label>
            </div>
            <div style="flex:1"></div>
          </div>

          <button id="print-btn" class="print-btn">Print</button>
          <div id="message" class="message"></div>
        </div>
      </ha-card>
    `;

    this._attachListeners();
    this._updatePreview();

    // Set title via textContent to prevent XSS
    const titleEl = this.shadowRoot.getElementById("card-title");
    if (titleEl) titleEl.textContent = this._config.title || "DYMO LetraTag";
  }

  _attachListeners() {
    const $ = (id) => this.shadowRoot.getElementById(id);

    // Text input
    $("text-input").addEventListener("input", (e) => {
      this._updateState("text", e.target.value);
    });

    // Font select
    $("font-select").addEventListener("change", (e) => {
      this._updateState("fontName", e.target.value);
    });

    // Size slider: 8..26 explicit, rightmost position = auto (biggest)
    $("size-slider").addEventListener("input", (e) => {
      const raw = parseInt(e.target.value, 10);
      const max = parseInt(e.target.max, 10);
      const isAuto = raw >= max;
      this._state.fontSize = isAuto ? 0 : raw;
      $("size-value").textContent = isAuto ? "Auto" : `${raw}px`;
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
        slider.max = isRotate ? "53" : "27";
        slider.value = slider.max;
        this._state.fontSize = 0;
        $("size-value").textContent = "Auto";

        this._updatePreview();
      });
    }

    // Copies
    $("copies-input").addEventListener("change", (e) => {
      this._state.copies = Math.max(1, Math.min(255, parseInt(e.target.value, 10) || 1));
      e.target.value = this._state.copies;
    });

    // Cut checkbox
    $("cut-check").addEventListener("change", (e) => {
      this._state.cut = e.target.checked;
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
