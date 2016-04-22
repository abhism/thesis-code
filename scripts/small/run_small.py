import subprocess
import random
import time
import socket
import requests

hostname = socket.gethostname()
while True:
    try:
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
        payload = ""
        if r:
            payload = payload + "time,guest=%s,command=%s value=%s" %(hostname,str(cmd),'0')
            print "Program exited with error code"
        else:
            payload = payload + "time,guest=%s,command=%s value=%s" %(hostname,str(cmd),str(elasped))
            #log elasped time here using http request
            print "command run: "+str(cmd)
            print "Time taken:" + str(elasped)
        requests.post('http://172.27.20.40:8086/write?db=test', data=payload)
    except:
        continue
