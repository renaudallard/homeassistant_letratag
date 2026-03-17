# Copyright (c) 2026, Renaud Allard <renaud@allard.it>
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
#    this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Frontend (Lovelace) card registration for the DYMO LetraTag integration.

Securely registers the card JS as a static path via StaticPathConfig and
auto-registers it as a Lovelace resource so users do not need to manually
add the resource URL. Cleans up on last entry unload.

Based on the pattern from github.com/renaudallard/bmw-cardata-ha.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_FRONTEND_SETUP_KEY = "_frontend_setup"
_RESOURCE_ID_KEY = "_frontend_resource_id"

_STATIC_URL = f"/{DOMAIN}/letratag-card.js"
_STATIC_PATH = Path(__file__).parent / "www" / "letratag-card.js"


async def _async_register_lovelace_resource(hass: HomeAssistant) -> str | None:
    """Register the card JS as a Lovelace resource. Returns the resource id."""
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            _LOGGER.debug("Lovelace data not available")
            return None

        resources = getattr(lovelace_data, "resources", None)
        if resources is None:
            _LOGGER.debug("Lovelace resources not available")
            return None

        # Ensure the resource collection is loaded from disk before
        # checking or creating items. Without this, async_create_item
        # on an unloaded collection would overwrite the storage file.
        if hasattr(resources, "loaded") and not resources.loaded:
            await resources.async_load()
            resources.loaded = True

        # Check if already registered
        for item in resources.async_items():
            if item.get("url") == _STATIC_URL:
                return item["id"]

        # Register as a JS module
        item = await resources.async_create_item(
            {"res_type": "module", "url": _STATIC_URL}
        )
        return item["id"]
    except Exception as err:
        _LOGGER.warning("Unable to register Lovelace resource: %s", err)
        return None


async def _async_unregister_lovelace_resource(
    hass: HomeAssistant, resource_id: str
) -> None:
    """Remove the Lovelace resource entry."""
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data is None:
            return
        resources = getattr(lovelace_data, "resources", None)
        if resources is None:
            return
        await resources.async_delete_item(resource_id)
    except Exception as err:
        _LOGGER.debug("Unable to remove Lovelace resource %s: %s", resource_id, err)


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Register the card JS static path and Lovelace resource.

    Safe to call multiple times across config entries.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get(_FRONTEND_SETUP_KEY):
        return

    # Register static path for the card JS
    if not _STATIC_PATH.exists():
        _LOGGER.warning(
            "Frontend card JS missing at %s; Lovelace card unavailable",
            _STATIC_PATH,
        )
    else:
        try:
            from homeassistant.components.http import StaticPathConfig

            await hass.http.async_register_static_paths(
                [StaticPathConfig(_STATIC_URL, str(_STATIC_PATH), True)]
            )
        except Exception as err:
            _LOGGER.debug("Unable to register static path: %s", err)

    # Defer Lovelace resource registration until HA is fully started.
    # During startup the ResourceStorageCollection may not be loaded yet.
    async def _register_resource(_event: Any = None) -> None:
        resource_id = await _async_register_lovelace_resource(hass)
        if resource_id:
            domain_data[_RESOURCE_ID_KEY] = resource_id

    if hass.state is CoreState.running:
        await _register_resource()
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _register_resource)

    domain_data[_FRONTEND_SETUP_KEY] = True


async def async_unload_frontend_if_last_entry(hass: HomeAssistant) -> None:
    """Remove the Lovelace resource if no config entries remain."""
    domain_data: dict[str, Any] | None = hass.data.get(DOMAIN)
    if not domain_data:
        return

    # Check if any non-internal keys remain (config entry IDs)
    remaining = [k for k in domain_data if not k.startswith("_")]
    if remaining:
        return

    resource_id = domain_data.get(_RESOURCE_ID_KEY)
    if isinstance(resource_id, str) and resource_id:
        await _async_unregister_lovelace_resource(hass, resource_id)

    # Clear setup flags so re-adding the integration re-registers the frontend
    domain_data.pop(_FRONTEND_SETUP_KEY, None)
    domain_data.pop(_RESOURCE_ID_KEY, None)
