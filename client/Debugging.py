from photon_client_1D import PhotonCounter
import time

pc = PhotonCounter("169.254.121.34")

while True:
    adc = pc.get_adc_raw()
    peak = pc.get_peak()
    rate = pc.get_rate()

    print(
        f"ADC={adc:6d}   "
        f"PEAK={peak:6d}   "
        f"RATE={rate.cps:8.1f} cps",time.time()
    )

    # time.sleep(0.1)