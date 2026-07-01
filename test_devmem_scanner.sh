#!/bin/bash
# Quick test script — run on Red Pitaya via SSH after loading the bitstream.
# Tests register read/write at the photon counter base address 0x40700000.
#
# Usage: ssh root@169.254.32.2 'bash -s' < test_devmem.sh

BASE=0x40700000

echo "=== Photon Counter Register Test ==="

# Read CTRL (should be 0)
echo -n "CTRL:       "
devmem $((BASE + 0x00))

# Write threshold = 200
echo "Setting threshold to 200..."
devmem $((BASE + 0x04)) 32 200

# Read back threshold
echo -n "THRESHOLD:  "
devmem $((BASE + 0x04))

# Write deadtime = 16
echo "Setting deadtime to 16..."
devmem $((BASE + 0x08)) 32 16

# Read back deadtime
echo -n "DEADTIME:   "
devmem $((BASE + 0x08))

# Enable counting
echo "Enabling counter..."
devmem $((BASE + 0x00)) 32 1

# Wait a moment
sleep 1

# Read count
echo -n "COUNTS:      "
devmem $((BASE + 0x500))

# Read status
echo -n "TRIG_STATUS:     "
devmem $((BASE + 0x38))

# Disable
echo "Disabling counter."
devmem $((BASE + 0x00)) 32 0

echo "=== Done ==="
