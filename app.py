from datetime import datetime
import threading
import time

# DEBUG MODE
from unittest.mock import MagicMock
MOCK_HW = False # When true, makes dummy calls to I2CBridge class - for testing without the board connected

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, ProgressBar, RichLog, Select

from i2c_bridge import I2CBridge

# Returns timestamp - used for logs.
def timestamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

class ConnectScreen(Screen):
    # Initial screen to connect to the FT4222 over USB.
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="setup-container"):
            with Center():
                yield Label("To begin, connect the test board via USB then press \"Connect\". Ensure the test board is connected to a 3V3 supply.", id="connection-label")
            with Center():
                yield Button("Connect", id="connect-button", variant="primary")

        yield Label("Connection Log:", classes="section-label")
        yield RichLog(highlight=True, markup=True, id="connection-log")
        yield Footer()

    @on(Button.Pressed, "#connect-button")
    def connect_handler(self) -> None:
        
        log = self.query_one("#connection-log", RichLog)
        log.write(f"Attempting to connect to FT4222...")

        # DEBUG MODE
        if MOCK_HW:
            self.app.controller = MagicMock()
            log.write(f"[{timestamp()}] [bold yellow]Connected to MOCK controller (debug mode).[/bold yellow]")
            self.app.push_screen(ControlScreen())
        
        try:
            # Initialise FT4222 - if successful go to control screen.
            self.app.controller = I2CBridge()
            self.app.controller.connect()
            log.write(f"[{timestamp()}] [bold green]Connected successfully![/bold green]")
            self.app.push_screen(ControlScreen())
        except Exception as e:
            log.write(f"[{timestamp()}] [bold red]Connection failed: [/bold red] {e}")

class ControlScreen(Screen):
    # Main control screen for configuring and running I2C tests

    # Add keyboard shortcut to clear the log
    BINDINGS = [("f5", "clear_log", "Clear Log")]

    def action_clear_log(self) -> None:
        self.query_one("#main-log", RichLog).clear()

    def __init__(self) -> None:
        super().__init__()
        self.is_test_running = False
        self.disconnecting = False
        self.stop_event = threading.Event()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        # Bus speed and test mode selection dialog.
        with Horizontal(id="selection-dialog"):
            with Vertical(classes="selection-box"):
                yield Label("Bus Speed:")
                yield Select(
                    [
                        ("100 kHz (Standard Mode)", 100),
                        ("400 kHz (Fast Mode)", 400),
                        ("1 MHz (Fast Mode Plus)", 1000),
                        ("3.4 MHz (High-Speed)", 3400),
                    ],
                    value=400,
                    allow_blank=False,
                    id="speed"
                )
            with Vertical(classes="selection-box"):
                yield Label("Test Mode:")
                yield Select(
                    [
                        ("Idle Bus", "idle"),
                        ("Single Read / Write", "single"),
                        ("Continous Stream", "stream"),
                        ("Bit Error Rate Test", "ber")
                    ],
                    value="stream",
                    allow_blank=False,
                    id="mode"
                )
        
        # Start / stop buttons
        with Horizontal(id="stop-start-buttons"):
            yield Button("Start", id="start-button", variant="success")
            yield Button("Stop", id="stop-button", variant="error", disabled=True)

        # Progress bar
        with Vertical(id="progress-container"):
            yield Label("Status: Ready", id="status-label")
            yield ProgressBar(total=100, show_eta=False, id="progress-bar")

        # Status / error log
        yield Label("System / Test Log:")
        yield RichLog(highlight=True, markup=True, id="main-log")
        yield Footer()

    # When control screen initialised, setup progress bar and start connection watchdog.
    def on_mount(self) -> None:
        progress_bar = self.query_one("#progress-bar")
        progress_bar.update(total=100, progress=0)
        self.log_message("[bold green]FT4222 connected and ready.[/bold green]")

        # Poll connection to test board every 5 seconds when no tests are running.
        self.watchdog_timer = self.set_interval(5.0, self.check_idle_connection)

    # Check if test board is still connected
    def check_idle_connection(self) -> None:
        if self.is_test_running or self.disconnecting or self.app.controller is None:
            return
        try:
            if not MOCK_HW:
                self.app.controller.check_connection();
        except Exception as e:
            self.disconnect_handler(f"USB connection lost while idle: {e}")

    # When test board is disconnected, delete controller instance and go back to connection screen.
    def disconnect_handler(self, reason: str) -> None:
        if self.disconnecting:
            return
        
        self.disconnecting = True
        self.stop_event.set()
        self.watchdog_timer.stop();

        if (self.app.controller is not None) and (not MOCK_HW):
            try:
                self.app.controller.disconnect()
            except Exception:
                pass
            self.app.controller = None

        self.app.pop_screen()
        connection_log = self.app.screen.query_one("#connection-log", RichLog)
        connection_log.write(f"[timestamp()][bold red]Test board disconnected:[/bold red] {reason}. Check connections and click \"Connect\" to retry.")

    # Writes text to log with timestamp.
    def log_message(self, message: str) -> None:
        log = self.query_one("#main-log", RichLog)
        log.write(f"[{timestamp()}] {message}")

    # Toggles buttons and selection dialog when a test starts or stops.
    def set_running_ui_state(self, is_running: bool, status_text: str = "Status: Ready") -> None:
        self.is_test_running = is_running
        self.query_one("#start-button", Button).disabled = is_running
        self.query_one("#stop-button", Button).disabled = not is_running
        self.query_one("#speed", Select).disabled = is_running
        self.query_one("#mode", Select).disabled = is_running
        
        self.query_one("#status-label", Label).update(status_text)

    # When start button is pressed, start test correspondiong to current settings.
    @on(Button.Pressed, "#start-button")
    def start_handler(self) -> None:
        bus_speed = int(self.query_one("#speed", Select).value)
        test_mode = str(self.query_one("#mode", Select).value)

        self.stop_event.clear()
        progress_bar = self.query_one("#progress-bar", ProgressBar)

        if test_mode in("idle", "stream", "single"):
            # Show pulse animation when not running BER test (there is no progress to show!)
            progress_bar.update(total=None)
        else:
            progress_bar.update(total=100, progress=0)

        self.set_running_ui_state(True, f"Status: Running {test_mode.upper()} test mode at {bus_speed} kHz...")
        self.log_message(f"Starting [bold]{test_mode.upper()}[/bold] test mode at [bold]{bus_speed}[/bold] kHz...")
        self.run_hardware_test(bus_speed, test_mode)

    # Kills test routine threads when stop button is pressed.
    @on(Button.Pressed, "#stop-button")
    def stop_handler(self) -> None:
        self.log_message("[yellow]Stop requested - waiting for current operation to finish.[/yellow]")
        self.stop_event.set()

    # Execute test routine corresponding to user selected test mode.
    @work(thread=True)
    def run_hardware_test(self, bus_speed: int, test_mode: str) -> None:
        # Get I2CBridge instance as simply "controller"
        controller = self.app.controller
        progress_bar = self.query_one("#progress-bar", ProgressBar)

        try:
            # Set the bus speed, corresponding to user selection.
            if not MOCK_HW:
                controller.init_bus(bus_speed)

            # Holds I2C bus idle - used for baseline aggressor noise measurements
            if test_mode == "idle":
                self.app.call_from_thread(self.log_message, f"Bus initialised at {bus_speed} kHz and held IDLE. Press stop to end.")
                
                while not self.stop_event.is_set():
                    if not MOCK_HW:
                        controller.check_connection() # Verify board is still connected without affecting I2C pins.
                    time.sleep(0.05)

            # Writes a random 16 byte payload to a random EEPROM address, then reads it back to verify.
            elif test_mode == "single":
                test_result = {}
                if not MOCK_HW:
                    test_result = controller.single_rw_test()

                    # Check if match...
                    if test_result["pass"]:
                        self.app.call_from_thread(self.log_message, f"[green]PASS[/green]: {test_result["read"].hex().upper()} read back from EEPROM address 0x{test_result["address"]:04X}")
                    else:
                        self.app.call_from_thread(self.log_message, f"[red]FAIL[/red]: {test_result["read"].hex().upper()} read back from EEPROM address 0x{test_result["address"]:04X}) - expected {test_result["written"].hex().upper()}")
                else:
                    self.app.call_from_thread(self.log_message, f"[green]PASS[/green]: 1234 read back from EEPROM address 0x1234")

            # Repeatedly sets the EEPROM's volatile address pointer to 0b010101...
            #   -> Continuous 010101... pattern helps with rise times measurements.
            #   -> No data is actually written to the EEPROM, so safe to leave running for long periods of time.
            elif test_mode == "stream":
                self.app.call_from_thread(self.log_message, f"Streaming 0x5555 continuosly at {bus_speed} kHz. Press stop to end.")

                while not self.stop_event.is_set():
                    # DEBUG MODE
                    if MOCK_HW:
                        time.sleep(0.05)
                    else:
                        controller.continous_stream()

            # Extension of single read / write test - loops for number of times according to "total_packets".
            #   -> Returns results showing bit error rate and associated info.
            elif test_mode == "ber":
                # Sets number of test iterations.
                total_packets = 1000

                # Set progress to 0.
                self.app.call_from_thread(progress_bar.update, total=total_packets, progress=0)

                self.app.call_from_thread(self.log_message, f"Running BER test ({total_packets} iterations) at {bus_speed} kHz. Press stop to abort early.")

                # How to explain this???
                for stats in controller.bit_error_rate_test(total_packets):
                    if self.stop_event.is_set():
                        self.app.call_from_thread(self.log_message, "[yellow]BER test aborted early.[/yellow]")
                        break
                    # Update progress bar
                    self.app.call_from_thread(progress_bar.update, progress=stats["current_packet"])

                else:
                    # Completion message if for loop completes - does not show if test aborted early!
                    self.app.call_from_thread(self.log_message, "[green]BER test complete.[/green]")

                # Write message to log showing results from BER test.
                if "stats" in locals():
                    self.app.call_from_thread(self.log_message,
                        f"[bold]RESULTS:[/bold]\n"
                        f"Number of Tests:                      {stats['total_packets_sent']}\n"
                        f"      -> of which [green]passed[/green]:             {stats['passed_packets']}\n"
                        f"      -> of which [red]failed[/red]              {stats['failed_packets']}\n"
                        f"Packet Error Rate:                    {stats['packet_error_rate']:.2%}\n"
                        f"Bit Error Rate:                       {stats['bit_error_rate']:.2%}\n"
                        f"      -> total number of bits:        {stats['total_bits']}\n"
                        f"      -> total number of bit errors:  {stats['total_bit_errors']}\n"
                        f"I2C Status Summary:                   {stats['status_counts']}"
                    )

        except Exception as e:
            # Hardware / USB call failed, return to connection screen.
            self.app.call_from_thread(self.disconnect_handler, f"hardware error during {test_mode.upper()}: {e}")

        finally:
            # Reset UI when test stopped.
            self.app.call_from_thread(progress_bar.update, total=100, progress=0)
            self.app.call_from_thread(self.set_running_ui_state, False, "Status: Stopped / Ready")
            self.app.call_from_thread(self.log_message, f"Stopped {test_mode.upper()} test")

class I2CTestApp(App):
    # Textual application class

    # UI styling
    CSS = """
        Screen {
            padding: 1 2;
        }

        #setup-container {
            height: 45%;
            align: center middle;
            border: round $primary;
            margin-bottom: 1;
        }

        #connection-label {
            text-style: bold;
            margin: 2 0;
            padding: 0 2;
            width: 100%;
            text-align: center;
        }

        #selection-dialog {
            height: auto;
            margin: 1 0;
        }

        #selection-dialog Label {
            margin-bottom: 1;
        }

        .selection-box {
            height: auto;
            width: 1fr;
            padding: 0 1;
        }

        #stop-start-buttons {
            height: auto;
            align: center middle;
            margin: 1 0;
        }

        #stop-start-buttons Button {
            margin: 0 2;
            min-width: 20;
        }

        #progress-container {
            height: auto;
            width: 100%;
            align: center middle;
            margin: 1 0;
            padding: 1;
            border: solid $surface;
        }

        #progress-bar {
            width: 100%;
            margin-top: 1;
        }

        #progress-bar > #bar {
            width: 1fr;
        }

        RichLog {
            height: 1fr;
            border: solid $accent;
            background: $surface;
        }
    """
    # Text shown at the top of the program.
    TITLE = "I2C Signal Integrity Test Board Control Program"

    # Keyboard shortcut to end the program - common to connect and control screens.
    BINDINGS = [("q", "quit", "Quit Program")]

    def __init__(self) -> None:
        super().__init__()
        self.controller = None

    def on_mount(self) -> None:
        # On program start, show connect screen.
        self.push_screen(ConnectScreen())

    def on_unmount(self) -> None:
        # On program close, disconnect from the test board.
        if self.controller is not None:
            try:
                if not MOCK_HW:
                    self.controller.disconnect()
            except Exception:
                pass

if __name__ == "__main__":
    app = I2CTestApp()
    app.run()