from client.photon_client_scanner import PhotonScanner

pc = PhotonScanner()
pc.set_trig_arm(True)
pc.set_trig_enable(True)
pc.start_stream_trig()
while True:
    print(pc.read_stream_trig())
    # pc.set_trig_arm(False)
    # pc.set_trig_enable(False)
