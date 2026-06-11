from photon_client_1D import PhotonCounter
import time
pc = PhotonCounter("169.254.121.34")
pc.set_threshold(200)
pc.set_deadtime(0)
# pc.set_gate_period(125000000) #1s = 125000000

pc.enable()
while True:
    rate = pc.get_rate()
    print(f"Count rate: {rate.cps:.0f} cps")
    print(pc.get_adc_raw())
    print(time.time())

histogram = pc.get_histogram()
pc.close()



#
# from photon_client import PhotonCounter
# import time
#
# pc = PhotonCounter("169.254.121.34")
# pc.set_threshold(2)
# pc.set_deadtime(16)
# pc.set_gate_period(12_500_000)  # 100 ms
# pc.enable()
#
# pc.start_stream(100)
#
# for _ in range(10):
#     print(pc.read_stream())
#
# pc.stop_stream()
# pc.close()