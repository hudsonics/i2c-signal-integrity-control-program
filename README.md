
# I2C Signal Integrity Control Program

Control program for interfacing with FT4222H USB-to-I2C bridge IC. It implements a user interface using [Textual](https://github.com/Textualize/textual) to run the following test routines:

*  `Idle` - keeps the bus idle; used for measuring noise induced from aggressor.

*  `Stream` - repeatedly sends `0x5555` (`0b010101010...`) on the bus; used for measuring rise times. Note that this only sets the EEPROM's volatile address pointer, so is safe to run for extended periods.

*  `Single Read / Write` - writes a random payload to a random address, and reads it back; used to manually verify operation of the bus.

*  `Bit Error Rate` - iterates over the single read / write test; used to qualitatively assess the performance of the bus under different test conditions.

## To do

* Verify operation at 3.4MHz (high-speed mode) - appears to work, but not clear if it is failing and defaulting to a lower speed.
* Add hardware implementation information to this page.