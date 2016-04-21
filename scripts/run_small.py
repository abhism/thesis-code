import subprocess
import random
import time
while True:
    chance = random.randrange(0,3)
    cmd = []
    r = 1
    if chance == 0:
        cmd = ["./run_spec.sh", "mcf"]
    elif chance == 1:
        cmd = ["./run_spec.sh","libquantum"]
    else :
        cmd = ["./usemem"]
    start = time.time()
    r = subprocess.call(cmd)
    elasped = time.time() - start
    if r:
        print "Program exited with error code"
    else:
        #log elasped time here using http request
        print "command run: "+str(cmd)
        print "Time taken:" + str(elasped)
