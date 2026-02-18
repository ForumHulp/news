from __future__ import annotations

import asyncio
import calendar
import logging
import email.utils

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from datetime import datetime
import locale
locale.setlocale(locale.LC_ALL, '')
from homeassistant.util import dt as dt_util
from homeassistant.util.dt import as_local
from .const import DOMAIN, ICON

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    """Set up the News media player entity."""
    coordinator = entry.runtime_data

    async_add_entities(
        [
            NewsPlayer(coordinator, entry),
        ],
        update_before_add=True,
    )


class NewsPlayer(CoordinatorEntity, MediaPlayerEntity):
    _attr_icon = ICON
    _attr_name = "News"

    def __init__(self, coordinator, entry):
        self._playing = False
        self._play_task: asyncio.Task | None = None
        self.entry = entry

        options = {**entry.data, **entry.options}
        self._pause_seconds = options.get("pause_seconds", 5)

        super().__init__(coordinator)

    @property
    def unique_id(self):
        return f"{DOMAIN}_{self.entry.entry_id}"

    @property
    def state(self):
        """Return the current state of the media player."""
        if not self.coordinator.data:
            return MediaPlayerState.IDLE
        return MediaPlayerState.PLAYING if getattr(self, "_playing", False) else MediaPlayerState.PAUSED

    @property
    def supported_features(self):
        return (
            MediaPlayerEntityFeature.NEXT_TRACK
            | MediaPlayerEntityFeature.PREVIOUS_TRACK
            | MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
        )

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def media_title(self):
        if not self.coordinator.data:
            return "No articles"
        return self.coordinator.data[self.coordinator.index].get("title")

    @property
    def media_content_id(self):
        if not self.coordinator.data:
            return None
        return self.coordinator.data[self.coordinator.index].get("link")

    @property
    def extra_state_attributes(self):
        if not self.coordinator.data:
            return {}

        article = self.coordinator.data[self.coordinator.index]

        published_time = None
        published_date = None
        if article.get("published"):
            pub_str = article["published"]
            parts = pub_str.split(",")[-1].strip().split(" ")  # ['16', 'Feb', '2026', '14:12:00', 'GMT']

            published_time = " ".join(parts[:3])
            published_date = parts[3] if len(parts) > 3 else ""

        attrs = {
            "article_number": f"{self.coordinator.index + 1}/{len(self.coordinator.data)}",
            "last_refresh": self.coordinator.last_update.strftime("%Y-%m-%d %H:%M:%S")
        }

        if published_time:
            attrs["published_time"] = published_time
        if published_date:
            attrs["published_date"] = published_date

        inclusions = self.entry.options.get("inclusions") or self.entry.data.get("inclusions", [])
        for extra in ["feed_name", "entity_picture"]:
            if extra not in inclusions:
                inclusions.append(extra)
        for key in inclusions:
            if key in article:
                attrs[key] = article[key]

        return attrs

    # ---------------------------
    # Play / Pause / Stop / Next / Previous
    # ---------------------------

    async def async_media_play(self):
        """Start playing and rotate articles automatically."""
        if not self.coordinator.data or self._playing:
            return

        self._playing = True
        self.async_write_ha_state()

        # Prevent duplicate loops
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()

        self._play_task = self.hass.async_create_task(
            self._play_next_article_loop()
        )

    async def async_media_pause(self):
        """Pause the current article."""
        self._playing = False
        if self._play_task:
            self._play_task.cancel()
            self._play_task = None
        self.async_write_ha_state()

    async def async_media_stop(self):
        """Stop the current article."""
        self._playing = False
        if self._play_task:
            self._play_task.cancel()
            self._play_task = None
        self.async_write_ha_state()

    async def async_media_next_track(self):
        """Go to the next article immediately."""
        if not self.coordinator.data:
            return
        self.coordinator.index = (self.coordinator.index + 1) % len(self.coordinator.data)
        self._playing = True
        self.async_write_ha_state()

    async def async_media_previous_track(self):
        """Go to the previous article immediately."""
        if not self.coordinator.data:
            return
        self.coordinator.index = (self.coordinator.index - 1) % len(self.coordinator.data)
        self._playing = True
        self.async_write_ha_state()

    # ---------------------------
    # Internal helper: auto-rotate articles
    # ---------------------------
    async def _play_next_article_loop(self):
        try:
            while self._playing and self.coordinator.data:
                await asyncio.sleep(self._pause_seconds)
                if not self._playing:
                    break
                self.coordinator.index = (
                    self.coordinator.index + 1
                ) % len(self.coordinator.data)
                self.async_write_ha_state()
        except asyncio.CancelledError:
            pass
