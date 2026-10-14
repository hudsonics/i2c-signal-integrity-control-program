import argparse
import ft4222
from ft4222.I2CMaster import Flag

# 24SC256 hardware address - may need adjusted for 3.4 Mbps mode...
EEPROM_ADDRESS = 0b1010000


def open_i2c_controller(bus_speed):
    try:
        controller = ft4222.openByDescription("FT4222")
        controller.i2cMaster_Init(bus_speed)
        return controller
    except Exception as e:
        print(f"Failed to open FT4222: {e}")
        exit()


def get_transfer_flag(bus_speed):
    if bus_speed > 1000:
        return Flag.HIGH_SPEED
    return Flag.NONE


def stream_test(controller, bus_speed):
    # Continuously sends 0x5555 (16-bit 0b01010101...) to the EEPROM until stopped.
    # No write takes place - EEPROM volatile address pointer just gets reset.
    flag = get_transfer_flag(bus_speed)

    print(f"Stream test at {bus_speed} kbps. Press Ctrl+C to stop...")

    try:
        while True:
            controller.i2cMaster_WriteEx(EEPROM_ADDRESS, flag, bytes([0x55, 0x55]))
    except KeyboardInterrupt:
        print("\nStream stopped")


def idle_test(controller, bus_speed):
    # Placeholder for idle test mode.
    print(f"Idle test mode not yet implemented (bus speed: {bus_speed} kbps)")


def ber_test(controller, bus_speed):
    # Placeholder for BER test mode.
    print(f"BER test mode not yet implemented (bus speed: {bus_speed} kbps)")


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Control program for I2C signal integrity test board using FTDI FT4222H"
    )

    parser.add_argument(
        "--bus-speed",
        type=int,
        choices=[100, 400, 1000, 3400],
        default=400,
        help="I2C bus speed in kbps (100, 400, 1000, or 3400)"
    )

    parser.add_argument(
        "--test-mode",
        choices=["idle", "stream", "ber"],
        default="stream",
        help="Test mode to run"
    )

    return parser.parse_args()


def main():
    args = parse_arguments()

    controller = open_i2c_controller(args.bus_speed)

    try:
        test_modes = {
            "idle": idle_test,
            "stream": stream_test,
            "ber": ber_test,
        }

        test_modes[args.test_mode](controller, args.bus_speed)
        
    finally:
        controller.close()

main()