from re import A
import time

import busio
from digitalio import DigitalInOut, Direction, Pull
import board
from board import *

import adafruit_ssd1306
import adafruit_rfm69
import adafruit_dht
from enum import Enum

SENSOR_PIN = D19
BAUD_RATE = 2000000
TX_POWER = 13
RADIO_FREQUENCY = 915.0


class State(Enum):
    IDLE = 1


class Robot:
    def __init__(self, sensor=True):
        self.state = State.IDLE

        # Enable sensor if sensor == TRUE
        self.sensor = adafruit_dht.DHT22(SENSOR_PIN) if sensor else None

        # Button A
        self.btnA = DigitalInOut(board.D5)
        self.btnA.direction = Direction.INPUT
        self.btnA.pull = Pull.UP

        # Button B
        self.btnB = DigitalInOut(board.D6)
        self.btnB.direction = Direction.INPUT
        self.btnB.pull = Pull.UP
        
        # Button C
        self.btnC = DigitalInOut(board.D12)
        self.btnC.direction = Direction.INPUT
        self.btnC.pull = Pull.UP

        # Create the I2C interface.
        i2c = busio.I2C(board.SCL, board.SDA)

        # 128x32 OLED Display
        reset_pin = DigitalInOut(board.D4)
        self.display = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, reset=reset_pin)

        self.display.fill(0)
        self.display.show()

        # Radio
        CS = DigitalInOut(board.CE1)
        RESET = DigitalInOut(board.D25)
        spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
        self.radio = adafruit_rfm69.RFM69(spi, CS, RESET, RADIO_FREQUENCY, baudrate=BAUD_RATE)
        self.radio.tx_power = TX_POWER
        self.prev_packet = None
        self.radio.encryption_key = b'\x01\x02\x03\x04\x05\x06\x07\x08\x01\x02\x03\x04\x05\x06\x07\x08'

    def read_sensor(self):
        if not self.sensor:
            return 0, 0, "Sensor not available"

        err = ""
        try:
            temperature, humidity = self.sensor.temperature, self.sensor.humidity
        except RuntimeError as e:
            temperature, humidity = 0, 0
            print(e)
            err = "Failed to get temperature"
        return temperature, humidity, err

    def read_radio(self):
        packet = self.radio.receive()
        return packet

    def set_display(self, text, x, y, col=1):
        self.display.fill(0)
        self.display.text(text, x, y, col=1)

    def buttonA(self):
        pass

    def buttonB(self):
        pass

    def buttonC(self):
        pass


r = Robot(sensor=True)
while True:
    if not r.btnA.value:
        r.buttonA()
    if not r.btnB.value:
        r.buttonB()
    if not r.btnC.value:
        r.buttonC()
    r.read_radio()
    time.sleep(0.1)

