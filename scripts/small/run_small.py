import subprocess
import random
import time
import socket
import requests

def getCmd(cmd):
    if cmd[0] == './usemem':
        return 'usemem'
    else:
        return cmd[1]

hostname = socket.gethostname()
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
        payload = ""
        if r:
            payload = payload + "time,guest=%s,command=%s value=%s" %(hostname,getCmd(cmd),'0')
            print "Program exited with error code"
        else:
            payload = payload + "time,guest=%s,command=%s value=%s" %(hostname,getCmd(cmd),str(elasped))
            #log elasped time here using http request
            print "command run: "+str(cmd)
            print "Time taken:" + str(elasped)
        resp = requests.post('http://172.27.20.40:8086/write?db=test', data=payload)
        if resp.status_code != 204:
            print 'Unable to send request'
            print resp.content
