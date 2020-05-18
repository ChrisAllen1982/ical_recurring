"""Support for ICS Calendar."""
import copy
import logging
from datetime import timedelta
from urllib.error import ContentTooShortError, HTTPError, URLError
from urllib.request import urlopen

import arrow
from icalendar import Calendar
import voluptuous as vol
from homeassistant.components.calendar import (ENTITY_ID_FORMAT,
                                               PLATFORM_SCHEMA,
                                               CalendarEventDevice,
                                               calculate_offset,
                                               is_offset_reached)
from homeassistant.const import CONF_NAME, CONF_URL
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.util import Throttle

import icalevents.icalevents as ical

VERSION = "1.0.0"

_LOGGER = logging.getLogger(__name__)

CONF_DEVICE_ID = 'device_id'
CONF_CALENDARS = 'calendars'
CONF_CALENDAR = 'calendar'

OFFSET = "!!"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    # pylint: disable=no-value-for-parameter
    vol.Optional(CONF_CALENDARS, default=[]):
        vol.All(cv.ensure_list, vol.Schema([
            vol.Schema({
                vol.Required(CONF_URL): vol.Url(),
                vol.Required(CONF_NAME): cv.string
            })
        ]))
})

MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=15)


def setup_platform(hass, config, add_entities, _=None):
    """Set up the ICS Calendar platform """
    _LOGGER.info("Setting up ics calendars")
    calendar_devices = []
    for calendar in config.get(CONF_CALENDARS):
        device_data = {
            CONF_NAME: calendar.get(CONF_NAME),
            CONF_URL: calendar.get(CONF_URL)
        }
        device_id = "{}".format(device_data[CONF_NAME])
        entity_id = generate_entity_id(ENTITY_ID_FORMAT, device_id, hass=hass)
        calendar_devices.append(
            ICSCalendarEventDevice(entity_id, device_data))

    add_entities(calendar_devices)


class ICSCalendarEventDevice(CalendarEventDevice):
    """A device for getting the next Task from an ICS Calendar"""

    def __init__(self, entity_id, device_data):
        _LOGGER.debug("Initializing calendar: %s", device_data[CONF_NAME])
        self.data = ICSCalendarData(device_data)
        self.entity_id = entity_id
        self.url = device_data[CONF_URL]
        self._event = None
        self._name = device_data[CONF_NAME]
        self._offset_reached = False

    @property
    def device_state_attributes(self):
        """Return the calendar entity's state attributes."""
        return {'offset_reached': self._offset_reached}

    @property
    def event(self):
        """Returns the current event for the calendar entity or None"""
        return self._event

    @property
    def name(self):
        """Returns the name of the calendar entity"""
        return self._name

    async def async_get_events(self, _, start_date, end_date):
        """Get all events in a specific time frame."""
        return await self.data.async_get_events(start_date, end_date)

    def update(self):
        """Update event data."""
        self.data.update()
        event = copy.deepcopy(self.data.event)
        if event is None:
            self._event = event
            return
        event = calculate_offset(event, OFFSET)
        self._offset_reached = is_offset_reached(event)
        self._event = event


class ICSCalendarData:
    """Calss to use the calendar ICS client object to get next event."""

    def __init__(self, device_data):
        """Set up how we are going to connect to the ICS Calendar"""
        self.name = device_data[CONF_NAME]
        self.url = device_data[CONF_URL]
        self.event = None

    async def async_get_events(self, start_date, end_date):
        """Get all events in a specific time frame."""
        event_list = []

        try:
	        events_items = ical.latest_events(self.name)
	        _LOGGER.debug("Got Events for %s", self.name )
	       
       	except:
       		None
       		
        #events_items = ical.events(self.url, None, None, start_date, end_date )

        for event in events_items:
            uid = None
            if hasattr(event, 'uid'):
                uid = event.uid
            data = {
                'uid': uid,
                'title': event.summary,
                'start': self.get_date_formatted(event.start, event.all_day),
                'end': self.get_date_formatted(event.end, event.all_day),
                'location': event.location,
                'description': event.description
            }
            # Note that we return a formatted date for start and end here,
            # but a different format for self.event!
            event_list.append(data)

        return event_list


    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        # """Get the latest data."""
        
        _LOGGER.debug("Updating %s", self.name )

        ical.events_async(self.name, self.url)

        event_items = []
        try:
        	events_items = ical.latest_events(self.name)
        	_LOGGER.debug("Got Events %s", self.name )
        except:
        	None

        temp_event = None

        right_now = arrow.utcnow()

        for event in events_items:

            ar_start = arrow.get(event.start)
            ar_end = arrow.get(event.end)

            if(ar_end < right_now) or (ar_start > right_now):
                continue

            if temp_event is None:
                temp_event = event
            elif arrow.get(temp_event.end) > ar_end:
                temp_event = event


        if temp_event is None:
            self.event = None
            return True

        self.event = {
            'summary': temp_event.summary,
            'start': self.get_hass_date(temp_event.start, temp_event.all_day),
            'end': self.get_hass_date(temp_event.end, temp_event.all_day),
            'location': temp_event.location,
            'description': temp_event.description
        }
        
        return True

    @staticmethod
    def get_date_formatted(arw, is_all_day):
        """Return the formatted date"""
        # Note that all day events should have a time of 0, and the timezone
        # must be local.  The server probably has the timezone erroneously set
        # to UTC!
        if is_all_day:
            arw = arrow.get(arw)
            arw = arw.replace(hour=0, minute=0, second=0,
                              microsecond=0, tzinfo='local')
            return arw.format('YYYY-MM-DD')

        return arw.isoformat()

    @staticmethod
    def get_hass_date(arw, is_all_day):
        """Return the wrapped and formatted date"""
        if is_all_day:
            return {'date': ICSCalendarData.get_date_formatted(arw, is_all_day)}
        return {'dateTime': ICSCalendarData.get_date_formatted(arw, is_all_day)}
