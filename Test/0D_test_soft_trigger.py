from urllib3.util import wait

from client.photon_client_scanner import PhotonScanner

pc = PhotonScanner()
pc.disable()
pc.reset()
pc.stop_stream()
pc.enable()
# pc.set_trig_arm(True)
# pc.set_trig_enable(True)


# pc.start_stream_trig()
pc.set_threshold(100)
pc.set_deadtime(1)
gate_cycles = int(1/127 * 125_000_000)
pc.set_gate_period(gate_cycles)
# print(pc.get_config())
# print(pc.get_status())
# print(pc.get_trig_config())
# print(pc.get_trig_status())
pc.trig_soft(False)
import time
import numpy as np
# time.sleep(5)
pc.set_pixels(int(256))
while True:
    t0 = time.time()
    time.sleep(3)
    pc.trig_soft(True)
    while True:
        status =pc.get_trig_status()
        # print(status)
        # if status.trig_active:
        #     print("active")
        if status.trig_done:
            break
    print(time.time() - t0)
    print(pc.get_trig_rates())
    print(np.size(pc.get_trig_rates()))
    pc.trig_soft(False)


