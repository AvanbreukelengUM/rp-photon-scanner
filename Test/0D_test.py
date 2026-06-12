from urllib3.util import wait

from client.photon_client_scanner import PhotonScanner

pc = PhotonScanner()
pc.disable()
pc.reset()
pc.stop_stream()
pc.enable()
pc.set_trig_arm(False)
pc.set_trig_enable(False)


# pc.start_stream_trig()
pc.set_threshold(100)
pc.set_deadtime(1)
gate_cycles = int(1 * 125_000_000)
pc.set_gate_period(gate_cycles)
print(pc.get_config())
print(pc.get_status())
print(pc.get_trig_config())
print(pc.get_trig_status())
import time
time.sleep(5)
while True:
    ps = pc.get_rate()

    print(ps)

