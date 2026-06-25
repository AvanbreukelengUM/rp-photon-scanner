from client.photon_client_scanner import PhotonScanner

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
gate_cycles = int(0.01 * 125_000_000)
pc.set_gate_period(gate_cycles)
pc.set_pixels(int(100))
# print(pc.get_config())
print(pc.get_status())
# print(pc.get_trig_config())
# print(pc.get_trig_status())
import time
# time.sleep(5)
# print(pc.get_trig_config())
# print(pc.get_trig_status())
# time.sleep(5)

while True:
    status =pc.get_trig_status()
    # print(status)
    if status.trig_active:
        print("active")
    if status.trig_done:
        break
print(pc.get_trig_rates())
# Read all gate counts (0x500 to 0x500 + 4*num_gates)


# while True:
#     ps = pc.get_trig_counts()
#     # print(ps[0])
#     for p in ps:
#         if p > 0:
#             print(p)
#         print(pc.get_trig_config())
#         print(pc.get_trig_status())

    # pc.set_trig_arm(False)
    # pc.set_trig_enable(False)
# print("errorss")
