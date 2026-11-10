# i2c-bridge.py
# Class to segregate UI from I2C bridge setup and test routines.

import ft4222
from ft4222.I2CMaster import Flag

import time
import random

EEPROM_ADDRESS = 0x50 # 1010000 - all address pins (A0, A1, A2) tied to ground on PCB
WRITE_CYCLE_DELAY = 0.1 # Wait fixed interval between read / writes

class I2CBridge:
    def __init__(self):
        self.bridge = None

    # Connects to test board (assumes USB device description is "FT4222", which is the default value hardcoded into the bridge IC)
    def connect(self):
        self.bridge = ft4222.openByDescription("FT4222")
        return self.bridge

    # Close connection to test board.
    def disconnect(self):
        if self.bridge:
            self.bridge.close()
            self.bridge = None

    # Checks if the test board is still connected - getClock() method does not disturb any ongoing I2C communication.
    def check_connection(self):
        self.bridge.getClock()

    # Set bus speed.
    def init_bus(self, bus_speed):
        self.bridge.i2cMaster_Init(bus_speed)

    # Writes a random 16 byte payload to a random EEPROM address, then reads it back to verify.
    def single_rw_test(self):
        # Generate random payload.
        PAYLOAD_LENGTH = 16 # Bytes
        random_payload = random.randbytes(PAYLOAD_LENGTH)
        
        # Randomly generate EEPROM address to write to / read from.
        # EEPROM address space is organised in 64 byte pages:
        #   -> 32KB total, so 512 pages of 64 bytes.
        PAGE_SIZE = 64 # Bytes
        TOTAL_MEMORY = 32 # KB
        MAX_PAGE_INDEX = ((TOTAL_MEMORY * 1024) // PAGE_SIZE) - 1 # 512 pages, indexed from 0.
    
        page = random.randint(0, MAX_PAGE_INDEX) # Generate random page.
        offset = random.randint(0, PAGE_SIZE - PAYLOAD_LENGTH) # Account for length of payload.

        # Calculate random address which will not exceed the address space of the selected page.
        random_address = page * PAGE_SIZE + offset 

        # Write random payload to random address on the EEPROM.
        self.bridge.i2cMaster_WriteEx(EEPROM_ADDRESS, Flag.START_AND_STOP, bytes([(random_address >> 8) & 0xFF, random_address & 0xFF]) + random_payload)

        time.sleep(WRITE_CYCLE_DELAY)

        # Set EEPROM address pointer to the random address (expects high byte, low byte).
        self.bridge.i2cMaster_WriteEx(EEPROM_ADDRESS, Flag.START, bytes([(random_address >> 8) & 0xFF, random_address & 0xFF]))

        # Read back data stored at random address - repeated start continues the transaction start by the previous command.
        readback = self.bridge.i2cMaster_ReadEx(EEPROM_ADDRESS, Flag.REPEATED_START | Flag.STOP, PAYLOAD_LENGTH)

        # Return test data.
        return {
            "pass": readback == random_payload,
            "address": random_address,
            "written": random_payload,
            "read": readback,
            "status": self.bridge.i2cMaster_GetStatus()
        }

    # Writes 0b01010101... continuously
    #   -> No payload, so only the EEPROM's volatile address pointer is set
    #   -> Safe to leave running while measuring rise times.
    def continous_stream(self):
        self.bridge.i2cMaster_WriteEx(EEPROM_ADDRESS, Flag.START_AND_STOP, bytes([0x55, 0x55]))
        time.sleep(WRITE_CYCLE_DELAY)

    # Extends single read / write test to determine failure rate over several executions.
    #   -> Generator ("yield" instead of "return") allows the main I2CTestApp class to handle threading and associated UI updates.
    def bit_error_rate_test(self, TOTAL_PACKETS):
        total_packets_sent = 0
        passed_packets = 0
        failed_packets = 0

        total_bits = 0
        total_bit_errors = 0

        # Stores I2C status on end of each packet transaction
        status_counts = {}
        # Status flags from "ft4222" library are ints - lookup table to convert these into strings for report to user.
        status_lookup = {
            ft4222.I2CMaster.ControllerStatus.BUSY: "BUSY",
            ft4222.I2CMaster.ControllerStatus.ERROR: "ERROR",
            ft4222.I2CMaster.ControllerStatus.ADDRESS_NACK: "ADDRESS_NACK",
            ft4222.I2CMaster.ControllerStatus.DATA_NACK: "DATA_NACK",
            ft4222.I2CMaster.ControllerStatus.ARB_LOST: "ARB_LOST",
            ft4222.I2CMaster.ControllerStatus.IDLE: "IDLE",
            ft4222.I2CMaster.ControllerStatus.BUS_BUSY: "BUS_BUSY",
        }

        # Run single read / write test number of times according to "TOTAL_PACKETS"
        for packet in range(TOTAL_PACKETS):
            # Execute single read / write test
            result = self.single_rw_test()

            # Increase total packets and bits sent accordingly
            total_packets_sent += 1
            total_bits += len(result["written"]) * 8 # Written data is given in bytes.

            # Record bus status.
            status_as_string = status_lookup[result["status"]]

            status_counts[status_as_string] = status_counts.get(status_as_string, 0) + 1

            if result["pass"]:
                # If the data read back matched the data which was written, increased the number of packets which passed.
                passed_packets += 1
            else:
                # If there is a mismatch between the data read back and the data written, increased the number of packets which failed.
                failed_packets += 1

                # Get number of individual bits which did not match (XOR payload which was written and the data which was read back)
                bit_errors = 0
                for written, read in zip(result["written"], result["read"]):
                    bit_errors += (written ^ read).bit_count()

                # Increase the total of failed bits accordingly.
                total_bit_errors += bit_errors

            # Calculate running packet error rate and bit error rate
            packet_error_rate = failed_packets / total_packets_sent
            bit_error_rate = total_bit_errors / total_bits

            # Return latest test statistics.
            yield {
                "current_packet": packet + 1,
                "result": result,
                "total_packets_sent": total_packets_sent,
                "passed_packets": passed_packets,
                "failed_packets": failed_packets,
                "packet_error_rate": packet_error_rate,
                "bit_error_rate": bit_error_rate,
                "total_bits": total_bits,
                "total_bit_errors": total_bit_errors,
                "status_counts": status_counts.copy()
            }