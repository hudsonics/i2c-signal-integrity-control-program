from datetime import datetime
import threading
import time

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Label, ProgressBar, RichLog, Select

import ft4222
from ft4222 import I2CMaster
from ft4222.I2CMaster import Flag

from unittest.mock import MagicMock
MOCK_HW = True # When true, makes dummy calls to controller - for testing without the board connected

# 24SC256 hardware address - may need adjusted for 3.4 Mbps mode...
EEPROM_ADDRESS = 0b1010000 # 0x50 - all address pin (A0, A1, A2) tied to ground on PCB.

def timestamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")

class SetupScreen(Screen):
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

        if MOCK_HW:
            self.app.controller = MagicMock()
            log.write(f"[{timestamp()}] [bold yellow]Connected to MOCK controller (debug mode).[/bold yellow]")
            self.app.push_screen(ControlScreen())
        
        try:
            controller = ft4222.openByDescription("FT4222")
            self.app.controller = controller
            log.write(f"[{timestamp()}] [bold green]Connected successfully![/bold green]")
            self.app.push_screen(ControlScreen())
        except Exception as e:
            log.write(f"[{timestamp()}] [bold red]Connection failed: [/bold red] {e}")

class ControlScreen(Screen):
    # Main control screen for configuring and running I2C tests
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

    def on_mount(self) -> None:
        progress_bar = self.query_one("#progress-bar")
        progress_bar.update(total=100, progress=0)
        self.log_message("[bold green]FT4222 connected and ready.[/bold green]")

        # Poll connection to test board every 5 seconds when no tests are running.
        self.watchdog_timer = self.set_interval(5.0, self.check_idle_connection)

    def check_idle_connection(self) -> None:
        if self.is_test_running or self.disconnecting or self.app.controller is None:
            return
        try:
            self.app.controller.getClock();
        except Exception as e:
            self.disconnect_handler(f"USB connection lost while idle: {e}")

    def disconnect_handler(self, reason: str) -> None:
        if self.disconnecting:
            return
        
        self.disconnecting = True
        self.stop_event.set()
        self.watchdog_timer.stop();

        if self.app.controller is not None:
            try:
                self.app.controller.close()
            except Exception:
                pass
            self.app.controller = None

        self.app.pop_screen()
        connection_log = self.app.screen.query_one("#connection-log", RichLog)
        connection_log.write(
            f"[timestamp()] [bold red]Test board disconnected:[/bold red] {reason}"
            "Check connections and click \"Connect\" to retry." 
        )

    def log_message(self, message: str) -> None:
        log = self.query_one("#main-log", RichLog)
        log.write(f"[{timestamp()}] {message}")

    def set_running_ui_state(self, is_running: bool, status_text: str = "Status: Ready") -> None:
        # Toggles buttons and selection dialog when a test starts / stops.
        self.is_test_running = is_running
        self.query_one("#start-button", Button).disabled = is_running
        self.query_one("#stop-button", Button).disabled = not is_running
        self.query_one("#speed", Select).disabled = is_running
        self.query_one("#mode", Select).disabled = is_running
        
        self.query_one("#status-label", Label).update(status_text)

    @on(Button.Pressed, "#start-button")
    def start_handler(self) -> None:
        bus_speed = int(self.query_one("#speed", Select).value)
        test_mode = str(self.query_one("#mode", Select).value)

        self.stop_event.clear()
        progress_bar = self.query_one("#progress-bar", ProgressBar)

        if test_mode in("idle", "stream"):
            # Shows pulse animaiton
            progress_bar.update(total=None)
        else:
            progress_bar.update(total=100, progress=0)

        self.set_running_ui_state(True, f"Status: Running {test_mode.upper()} test mode at {bus_speed} kHz...")
        self.log_message(f"Starting [bold]{test_mode.upper()}[/bold] test mode at [bold]{bus_speed}[/bold] kHz...")
        self.run_hardware_test(bus_speed, test_mode)

    @on(Button.Pressed, "#stop-button")
    def stop_handler(self) -> None:
        self.log_message("[yellow]Stop requested - waiting for current operation to finish.[/yellow]")
        self.stop_event.set()

    @work(thread=True)
    def run_hardware_test(self, bus_speed: int, test_mode: str) -> None:
        controller = self.app.controller
        progress_bar = self.query_one("#progress-bar")

        try:
            if not MOCK_HW:
                controller.i2cMaster_Init(bus_speed)

            if test_mode == "idle":
                self.app.call_from_thread(self.log_message, f"Bus initialised at {bus_speed} kHz and held IDLE. Press stop to end.")
                while not self.stop_event.is_set():
                    controller.getClock() # Verify board is still connected without affecting I2C pins.
                    time.sleep(0.05)

            elif test_mode == "stream":
                self.app.call_from_thread(self.log_message, f"Streaming 0x5555 continuosly at {bus_speed} kHz. Press stop to end.")

                while not self.stop_event.is_set():
                    if MOCK_HW:
                        time.sleep(0.05)
                    else:
                        controller.i2cMaster_WriteEx(EEPROM_ADDRESS, Flag.START_AND_STOP, bytes([0x55, 0x55]))
                        time.sleep(0.001)


            elif test_mode == "ber":
                # PLACEHOLDER bit error rate test routine.
                total_packets = 200
                self.app.call_from_thread(progress_bar.update, total=total_packets, progress=0)
                self.app.call_from_thread(self.log_message, f"Running BER test ({total_packets} iterations) at {bus_speed} kHz. Press stop to abort early.")

                for i in range(1, total_packets + 1):
                    if self.stop_event.is_set():
                        self.app.call_from_thread(self.log_message, "[yellow]BER test aborted early.[/yellow]")
                        break

                    # Replace sleep with actual EEPROM read / write verifications.
                    time.sleep(0.05)
                    self.app.call_from_thread(progress_bar.update, progress = i)

                else:
                    self.app.call_from_thread(self.log_message, "[green]BER test complete (placeholder: 0 errors).[/green]")

        except Exception as e:
            # Heardware / USB call failed, return to connection screen.
            self.app.call_from_thread(self.disconnect_handler, f"hardware error during {test_mode.upper()}: {e}")

        finally:
            self.app.call_from_thread(progress_bar.update, total=100, progress=0)
            self.app.call_from_thread(self.set_running_ui_state, False, "Status: Stopped / Ready")
            self.app.call_from_thread(self.log_message, f"Stopped {test_mode.upper()} test")

class I2CTestApp(App):
    # Textual application class

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
    TITLE = "I2C Signal Integrity Test Board Control Program"

    BINDINGS = [("q", "quit", "Quit Program")]

    def __init__(self) -> None:
        super().__init__()
        self.controller = None

    def on_mount(self) -> None:
        self.push_screen(SetupScreen())

    def on_unmount(self) -> None:
        if self.controller is not None:
            try:
                if not MOCK_HW:
                    self.controller.close()
            except Exception:
                pass

if __name__ == "__main__":
    app = I2CTestApp()
    app.run()