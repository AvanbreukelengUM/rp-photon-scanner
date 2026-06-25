
from client.photon_client_scanner import PhotonScanner

pc = PhotonScanner()
pc.disable()
pc.reset()
pc.enable()

pc.set_threshold(100)
pc.set_deadtime(1)
gate_cycles = int(0.01 * 125_000_000)
pc.set_gate_period(gate_cycles)
pc.set_pixels(int(100))
print(pc.get_config())

"""START AGW"""
print("START Generation to activate trigger")

while True:
    status = pc.get_trig_status()
    # print(status)
    if status.trig_active:
        print("Trigger Active")
        break
while True:
    status = pc.get_trig_status()
    if status.trig_done:
        print("Trigger Done")
        break
print(pc.get_trig_rates())
# Read all gate counts (0x500 to 0x500 + 4*num_gates)
