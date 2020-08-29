#!/usr/bin/env python3

# Daikin A/C WebThing

from asyncio import sleep, CancelledError, get_event_loop
from webthing import (Action, Event, Property, MultipleThings, Thing, Value,
                      WebThingServer)
from daikinapi import Daikin
import requests
import re
import logging
import os
import time

DEBUG = True if 'DEBUG' in os.environ else False
UPDATE_THING_SECONDS = 15

# Also see:
# https://iot.mozilla.org/wot/
# https://iot.mozilla.org/schemas/
# https://iot.mozilla.org/framework/
# https://github.com/mozilla-iot/webthing-python
# https://github.com/arska/python-daikinapi
# https://github.com/ael-code/daikin-control


class DaikinAC(Thing):
    """A Daikin A/C which updates its measurements every few seconds."""

    def __init__(self, ip_addr):
        self.ip_addr = ip_addr
        daikinac = Daikin(self.ip_addr)
        self.actype = daikinac.type
        self.acname = daikinac.name
        Thing.__init__(self,
                       f"urn:daikin:{self.ip_addr}",
                       f"Daikin {self.actype} {self.acname}",
                       ["Thermostat","OnOffSwitch"],
                       f"Daikin {self.actype} {self.acname}")

        self.room_temperature = Value(0.0)
        self.add_property(
            Property(self,
                     "room_temperature",
                     self.room_temperature,
                     metadata={
                         "@type": "TemperatureProperty",
                         "title": f"Room Temperature",
                         "type": "number",
                         "description": f"The current room temperature for Daikin {self.actype} {self.acname} in °C",
                         "unit": "degree celsius",
                         "readOnly": True,
                     }))

        self.target_temperature = Value(0.0, self.set_tgt_temp)
        self.add_property(
            Property(self,
                     "target_temperature",
                     self.target_temperature,
                     metadata={
                         "@type": "TargetTemperatureProperty",
                         "title": f"Target Temperature",
                         "type": "number",
                         "description": f"The current target temperature for Daikin {self.actype} {self.acname} in °C",
                         "unit": "degree celsius",
                         "readOnly": False,
                     }))

        self.thermo_mode = Value("off", self.set_tmode)
        self.add_property(
            Property(self,
                     "mode",
                     self.thermo_mode,
                     metadata={
                         "@type": "ThermostatModeProperty",
                         "title": f"A/C Mode",
                         "type": "string",
                         "enum": ["off", "auto", "cool", "heat", "dehumid", "fan"],
                         "description": f"The current mode of Daikin {self.actype} {self.acname}",
                         "readOnly": False,
                     }))

        self.power = Value(False, self.set_power)
        self.add_property(
            Property(self,
                     "power",
                     self.power,
                     metadata={
                         "@type": "OnOffProperty",
                         "title": f"Power",
                         "type": "boolean",
                         "description": f"The power (on/off) setting for Daikin {self.actype} {self.acname}",
                         "readOnly": False,
                     }))

        if DEBUG:
            logging.debug("starting the %s %s update looping task", self.actype, self.acname)
        self.sensor_update_task = \
            get_event_loop().create_task(self.update_level())

    async def update_level(self):
        try:
            while True:
                await sleep(UPDATE_THING_SECONDS)
                daikinac = Daikin(self.ip_addr)
                in_temp = daikinac.inside_temperature
                logging.debug("setting new %s %s inside temperature: %s", self.actype, self.acname, in_temp)
                try:
                    tgt_temp = daikinac.target_temperature
                except:
                    tgt_temp = None
                logging.debug("setting new %s %s target temperature: %s", self.actype, self.acname, tgt_temp)
                mode = daikinac.mode
                power = daikinac.power
                logging.debug("setting new %s %s power %s, mode %s", self.actype, self.acname, daikinac.power, daikinac.mode)
                if power == 0:
                    tmode = "off"
                elif mode == 2:
                    tmode = "dehumid"
                elif mode == 3:
                    tmode = "cool"
                elif mode == 4:
                    tmode = "heat"
                elif mode == 6:
                    tmode = "fan"
                else:
                    tmode = "auto"
                if DEBUG:
                    logging.debug("setting new %s %s inside temperature: %s", self.actype, self.acname, in_temp)
                    logging.debug("setting new %s %s target temperature: %s", self.actype, self.acname, tgt_temp)
                    logging.debug("setting new %s %s mode: %s (power %s, mode %s)", self.actype, self.acname, tmode, daikinac.power, daikinac.mode)
                if isinstance(in_temp, (int, float)) or (isinstance(in_temp, str) and in_temp.isnumeric()):
                    self.room_temperature.notify_of_external_update(in_temp)
                if isinstance(tgt_temp, (int, float)) or (isinstance(tgt_temp, str) and tgt_temp.isnumeric()):
                    self.target_temperature.notify_of_external_update(tgt_temp)
                self.thermo_mode.notify_of_external_update(tmode)
                self.power.notify_of_external_update(power)
        except CancelledError:
            # We have no cleanup to do on cancellation so we can just halt the
            # propagation of the cancellation exception and let the method end.
            pass

    def set_tgt_temp(self, new_temp):
        daikinac = Daikin(self.ip_addr)
        daikinac.target_temperature = new_temp

    def set_power(self, power_state):
        daikinac = Daikin(self.ip_addr)
        daikinac.power = 1 if power_state else 0

    def set_tmode(self, new_tmode):
        daikinac = Daikin(self.ip_addr)
        if new_tmode == "off":
            daikinac.power = 0
        elif new_tmode == "dehumid":
            daikinac.mode = 2
        elif new_tmode == "cool":
            daikinac.mode = 3
        elif new_tmode == "heat":
            daikinac.mode = 4
        elif new_tmode == "fan":
            daikinac.mode = 6
        else:
            daikinac.mode = 1

    def cancel_update_level_task(self):
        self.sensor_update_task.cancel()
        get_event_loop().run_until_complete(self.sensor_update_task)


class DaikinCondenser(Thing):
    """A Daikin Condenser unit, accessed via in indoor A/C unit."""

    def __init__(self, ip_addr):
        self.ip_addr = ip_addr
        daikinac = Daikin(self.ip_addr)
        self.actype = daikinac.type
        self.acname = daikinac.name
        Thing.__init__(self,
                       f"urn:daikin:{self.ip_addr}:condenser",
                       f"Daikin {self.actype} Condenser",
                       ["TemperatureSensor"],
                       f"Daikin {self.actype} Condenser, accessed via {self.acname}")

        self.outside_temperature = Value(0.0)
        self.add_property(
            Property(self,
                     "outside_temperature",
                     self.outside_temperature,
                     metadata={
                         "@type": "TemperatureProperty",
                         "title": f"Outside Temperature",
                         "type": "number",
                         "description": f"The current outside temperature according to Daikin {self.actype} {self.acname} in °C",
                         "unit": "degree celsius",
                         "readOnly": True,
                     }))

        if DEBUG:
            logging.debug("starting the %s %s update looping task", self.actype, self.acname)
        self.sensor_update_task = \
            get_event_loop().create_task(self.update_level())

    async def update_level(self):
        try:
            while True:
                await sleep(UPDATE_THING_SECONDS)
                daikinac = Daikin(self.ip_addr)
                out_temp = daikinac.outside_temperature
                if DEBUG:
                    logging.debug("setting new %s %s outside temperature: %s", self.actype, self.acname, out_temp)
                self.outside_temperature.notify_of_external_update(out_temp)
        except CancelledError:
            # We have no cleanup to do on cancellation so we can just halt the
            # propagation of the cancellation exception and let the method end.
            pass

    def cancel_update_level_task(self):
        self.sensor_update_task.cancel()
        get_event_loop().run_until_complete(self.sensor_update_task)



def run_server():
    # Create a thing that represents a humidity sensor
    office_daikin = DaikinAC("192.168.13.30")
    kitchen_daikin = DaikinAC("192.168.13.31")
    bedroom_daikin = DaikinAC("192.168.13.32")
    daikin_condenser = DaikinCondenser("192.168.13.30")

    # If adding more than one thing, use MultipleThings() with a name.
    # In the single thing case, the thing's name will be broadcast.
    server = WebThingServer(
        MultipleThings(
            [office_daikin, kitchen_daikin, bedroom_daikin, daikin_condenser],
            "DaikinAC"),
        port=8889)
    try:
        logging.info("starting the server")
        server.start()
    except KeyboardInterrupt:
        logging.debug("canceling the sensor update looping task")
        office_daikin.cancel_update_level_task()
        kitchen_daikin.cancel_update_level_task()
        bedroom_daikin.cancel_update_level_task()
        daikin_condenser.cancel_update_level_task()
        logging.info("stopping the server")
        server.stop()
        logging.info("done")


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.DEBUG if DEBUG else logging.INFO,
        format="%(asctime)s %(filename)s:%(lineno)s %(levelname)s %(message)s"
    )
    run_server()
