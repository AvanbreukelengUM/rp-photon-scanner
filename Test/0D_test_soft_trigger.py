
from client.photon_client_scanner import PhotonScanner
import time
import numpy as np

pc = PhotonScanner()
pc.disable()
pc.reset()
pc.enable()

pc.set_threshold(100)
pc.set_deadtime(0)
gate_cycles = int(10/4095 * 125_000_000)
pc.set_gate_period(gate_cycles)
pc.trig_soft(False)

# time.sleep(5)
pc.set_pixels(int(4095))
while True:
    print("start")
    t0 = time.time()
    time.sleep(2)
    pc.trig_soft(True)
    while True:
        status =pc.get_trig_status()
        # print(status)
        if status.trig_active:
            print("Trigger Active")
            break
    while True:
        status =pc.get_trig_status()
        if status.trig_done:
            print("Trigger Done")
            break
    print(time.time() - t0)
    print(pc.get_trig_rates_debug())
    print(np.size(pc.get_trig_rates_debug()))
    pc.trig_soft(False)


