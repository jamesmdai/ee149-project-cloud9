import sys
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

import RPi.GPIO as GPIO
import threading


MOTOR_ENCODER_PIN = 4
SENSOR_PIN = D19
BAUD_RATE = 2000000
TX_POWER = 13
RADIO_FREQUENCY = 915.0

MOTOR_FWD_PIN = 20
MOTOR_BWD_PIN = 21
ROTATION_ENCODINGS = 121

SERVO_PIN = 13
LEFT_ANGLE = 0
CENTER_ANGLE = 90
RIGHT_ANGLE = 15

class GearState(Enum):
    IDLE = "IDLE"
    FWD = "FWD"
    BWD = "BWD"

class TurnState(Enum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    CENTER = "CENTER"

class Robot:
    def __init__(self, robot=True):
        self.gear = GearState.IDLE
        self.turn = TurnState.CENTER
        self.num_packets = 0
        self.ping_cnt = 0
        self.ping_rec_cnt = 0
        self.checked_rec_cnt = 0
        self.temperature = 0.0
        self.humidity = 0.0

        # Enable sensor if robot == TRUE
        self.robot = robot
        self.sensor = adafruit_dht.DHT22(SENSOR_PIN) if robot else None

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

        # Motor control
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(MOTOR_FWD_PIN, GPIO.OUT)
        GPIO.setup(MOTOR_BWD_PIN, GPIO.OUT)
        self.m_f_pwm = GPIO.PWM(MOTOR_FWD_PIN, 20)
        self.m_b_pwm = GPIO.PWM(MOTOR_BWD_PIN, 20)
        self.m_f_pwm.start(0)
        self.m_b_pwm.start(0)

        GPIO.setup(MOTOR_ENCODER_PIN, GPIO.IN)
        self.encoder_state = GPIO.input(MOTOR_ENCODER_PIN)
        self.rotation_count = 0
        self.stateCount = 0
        self.stateDeadline = None

        # Create the I2C interface.
        i2c = busio.I2C(board.SCL, board.SDA)

        # 128x32 OLED Display
        reset_pin = DigitalInOut(board.D4)
        self.display = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c, reset=reset_pin)

        self.display.fill(0)
        self.display.show()
        self.refresh_display()


        # Radio
        CS = DigitalInOut(board.CE1)
        RESET = DigitalInOut(board.D25)
        spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
        self.radio = adafruit_rfm69.RFM69(spi, CS, RESET, RADIO_FREQUENCY, baudrate=BAUD_RATE)
        self.radio.tx_power = TX_POWER
        self.radio.encryption_key = b'\x01\x02\x03\x04\x05\x06\x07\x08\x01\x02\x03\x04\x05\x06\x07\x08'

        # Servo
        GPIO.setup(SERVO_PIN, GPIO.OUT)
        self.servo = GPIO.PWM(SERVO_PIN, 50)
        self.servo.start(0)
        self.set_servo(CENTER_ANGLE)

    def refresh_display(self):
        self.display.fill(0)
        if self.robot:
            self.display.text(
                    f"G: {self.gear.value} T: {self.turn.value}" +
                    f"\nPKTS_RCVD: {self.num_packets}" +
                    f"\nTEM: {self.temperature} HUM: {self.humidity}" +
                    f"\nENC: {self.stateCount}",
                    0, 0, 1
            )
        else:
            self.display.text(
                    f"G: {self.gear.value} T: {self.turn.value}" +
                    f"\nPKTS_RCVD: {self.num_packets}" +
                    f"\nTEM: {self.temperature} HUM: {self.humidity}",
                    0, 0, 1
            )

        self.display.show()

    def read_sensor(self):
        if not self.sensor:
            return
        try:
            self.temperature, self.humidity = self.sensor.temperature, self.sensor.humidity
        except RuntimeError as e:
            pass # fuck a temp sensor print(e)

    def read_motor_encoder(self):
        new_encoder_state = GPIO.input(MOTOR_ENCODER_PIN)
        if new_encoder_state != self.encoder_state:
            self.encoder_state = new_encoder_state
            self.stateCount += 1

    def ping(self):
        if self.robot:
            return
        if not self.ping_cnt % 10:
            data = bytes("PING", "utf-8")
            self.send_radio(data)
        self.ping_cnt += 1

    def check_recieved_ping(self):
        if self.ping_rec_cnt <= self.checked_rec_cnt:
            return False
        else:
            self.checked_rec_cnt = self.ping_rec_cnt
            return True

    def read_radio(self):
        # Recieve the latest Packet, If there is one.
        packet = self.radio.receive()
        if packet is None:
            return None

        # Is the packet garbled?
        try:
            self.ping_rec_cnt += 1
            packet_text = str(packet, "utf-8")
        except UnicodeDecodeError as e:
            print(e)
            return
        self.num_packets += 1

        # Interpret the Command
        # State change packets for robot
        if self.robot:
            if packet_text == "GEAR":
                if self.gear == GearState.IDLE:
                    self.gear = GearState.FWD
                    self.motor_fwd()
                elif self.gear == GearState.FWD:
                    self.gear = GearState.BWD
                    self.motor_bwd()
                elif self.gear == GearState.BWD:
                    self.gear = GearState.IDLE
                    self.motor_idle()
            elif packet_text == "TURN":
                if self.turn == TurnState.RIGHT:
                    self.turn = TurnState.CENTER
                    self.set_servo(CENTER_ANGLE)
                elif self.turn == TurnState.CENTER:
                    self.turn = TurnState.RIGHT
                    self.set_servo(RIGHT_ANGLE)
            elif packet_text == "DISCOVER":
                t = threading.Thread(target=self.discover)
                t.start()
            # robot ACKs packet
            s = f"{self.gear.value} {self.turn.value} {self.temperature} {self.humidity}"
            data = bytes(s, "utf-8")
            self.send_radio(data)
            self.refresh_display()

        # ACK packets for controller
        else:
            states = packet_text.split(" ")
            if states[0] == "IDLE":
                self.gear = GearState.IDLE
            if states[0] == "FWD":
                self.gear = GearState.FWD
            if states[0] == "BWD":
                self.gear = GearState.BWD
            if states[1] == "LEFT":
                self.turn = TurnState.LEFT
            if states[1] == "CENTER":
                self.turn = TurnState.CENTER
            if states[1] == "RIGHT":
                self.turn = TurnState.RIGHT
            self.temperature, self.humidity = states[2], states[3]
            self.refresh_display()
        return packet

    def send_radio(self, data):
        self.radio.send(data)

    # Movement
    def motor_idle(self):
        self.m_f_pwm.stop()
        self.m_b_pwm.stop()

    def motor_fwd(self, duty=75):
        self.gear = GearState.FWD
        self.m_f_pwm.start(duty)
        self.m_b_pwm.stop()

    def motor_encoder_move(self, rotations=1.5, duty=75):
        self.stateDeadline = self.stateCount + rotations * ROTATION_ENCODINGS
        while self.stateDeadline and self.stateCount <= self.stateDeadline:
            print("moving")
            self.motor_fwd(duty)
        self.gear = GearState.IDLE
        self.motor_idle()
        self.stateDeadline = None

    def motor_bwd(self, duty=75):
        self.gear = GearState.BWD
        self.m_f_pwm.stop()
        self.m_b_pwm.start(duty)

    def set_servo(self, angle):
        GPIO.output(SERVO_PIN, False)
        self.servo.ChangeDutyCycle(0)
        time.sleep(.1)
        duty = angle / 18 + 2
        GPIO.output(SERVO_PIN, True)
        self.servo.ChangeDutyCycle(duty)
        #time.sleep(1)
        #GPIO.output(SERVO_PIN, False)
        #self.servo.ChangeDutyCycle(0)

    def discover(self):
        self.turn = TurnState.RIGHT
        self.set_servo(RIGHT_ANGLE)
        
        max_seen = -1000
        max_step = 0
        rssi_vals = []
        for step in range(8):
            print("doing incr")
            while not self.check_recieved_ping():
                print(self.checked_rec_cnt, self.ping_rec_cnt)
                time.sleep(.1)
            rssi_vals.append(self.radio.last_rssi)
            if (self.radio.last_rssi > max_seen):
                max_step = step
            print(f"got rssi {self.radio.last_rssi}")
            time.sleep(.6)
            self.motor_encoder_move(rotations=.75, duty=40)
        time.sleep(1)
        self.motor_encoder_move(rotations=.75*max_step, duty=40)

    # Buttons
    def buttonA(self):
        data = bytes("GEAR", "utf-8")
        self.send_radio(data)
    def buttonB(self):
        data = bytes("TURN", "utf-8")
        self.send_radio(data)
    def buttonC(self):
        data = bytes("DISCOVER", "utf-8")
        self.send_radio(data)

r = Robot(robot=(len(sys.argv) < 2))
def taskA():
    while True:
        if not r.btnA.value:
            r.buttonA()
        if not r.btnB.value:
            r.buttonB()
        if not r.btnC.value:
            r.buttonC()
        r.read_sensor()
        r.ping()
        r.read_radio()
        time.sleep(0.1)

def taskB():
    while True:
        r.read_motor_encoder()

def main():
    tasks = [taskA, taskB]
    for task in tasks:
        t = threading.Thread(target=task)
        t.start()
main()
