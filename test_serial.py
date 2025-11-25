#!/usr/bin/env python3
"""
Simple serial port diagnostic tool for TASCAM CD-400U
Tests basic communication and shows raw data
"""

import serial
import time
import sys

PORT = '/dev/serial/by-id/usb-FTDI_USB_Serial_Converter_FTEM3Y6M-if00-port0'
BAUDRATE = 9600

def test_serial():
    print(f"=== TASCAM CD-400U Serial Port Diagnostic ===")
    print(f"Port: {PORT}")
    print(f"Baudrate: {BAUDRATE}")
    print()

    try:
        # Open serial port
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1.0,
            rtscts=False,  # No hardware flow control
            xonxoff=False
        )

        print(f"✓ Serial port opened successfully")
        print(f"  - DTR: {ser.dtr}")
        print(f"  - RTS: {ser.rts}")
        print(f"  - CTS: {ser.cts}")
        print(f"  - DSR: {ser.dsr}")
        print()

        # Flush buffers
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        # Test 1: Send MECHA STATUS SENSE command
        print("Test 1: Sending MECHA STATUS SENSE command (0x50)...")
        command = b'\x0A0500\x0D'  # LF + 0 + 50 + 00 + CR
        print(f"  TX: {command.hex(' ')} ({len(command)} bytes)")
        ser.write(command)

        # Wait for response
        time.sleep(0.2)

        if ser.in_waiting > 0:
            response = ser.read(ser.in_waiting)
            print(f"  RX: {response.hex(' ')} ({len(response)} bytes)")
            print(f"  ASCII: {response}")
            print("  ✓ Got response!")
        else:
            print("  ✗ No response received")
        print()

        # Test 2: Send TRACK NUMBER SENSE
        print("Test 2: Sending TRACK NUMBER SENSE command (0x55)...")
        command = b'\x0A055\x0D'  # LF + 0 + 55 + CR
        print(f"  TX: {command.hex(' ')} ({len(command)} bytes)")
        ser.write(command)

        time.sleep(0.2)

        if ser.in_waiting > 0:
            response = ser.read(ser.in_waiting)
            print(f"  RX: {response.hex(' ')} ({len(response)} bytes)")
            print(f"  ASCII: {response}")
            print("  ✓ Got response!")
        else:
            print("  ✗ No response received")
        print()

        # Test 3: Listen for any unsolicited data (5 seconds)
        print("Test 3: Listening for any incoming data (5 seconds)...")
        print("  (Try pressing buttons on the CD-400U...)")

        start_time = time.time()
        data_received = False

        while time.time() - start_time < 5.0:
            if ser.in_waiting > 0:
                response = ser.read(ser.in_waiting)
                print(f"  RX: {response.hex(' ')} ({len(response)} bytes)")
                print(f"  ASCII: {response}")
                data_received = True
            time.sleep(0.1)

        if not data_received:
            print("  ✗ No data received")
        print()

        ser.close()

        print("=== Diagnostic Complete ===")
        print()
        print("If you see '✗ No response received' for all tests:")
        print("  1. Check TX/RX wiring (might be swapped)")
        print("  2. Verify cable is RS-232 'straight-through' (not null modem)")
        print("  3. Check ground connection (pin 5)")
        print("  4. Confirm CD-400U RS-232 is enabled in its settings")
        print()
        print("If you see responses, the connection is working!")

    except serial.SerialException as e:
        print(f"✗ Serial port error: {e}")
        return 1
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(test_serial())
