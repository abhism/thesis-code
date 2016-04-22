import subprocess
import random
import time
import thread
import socket
import requests

run_1 = 0
run_2 = 0

def run(name):
    try:
        print "starting thread "+name
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
            #log elasped time here using http request
            payload = payload + "time,guest=%s,command=%s value=%s" %(hostname,str(cmd),str(elasped))
            print "command run: "+str(cmd)
            print "Time taken:" + str(elasped)
        requests.post('http://172.27.20.40:8086/write?db=test', data=payload)
        print "ending thread "+name
        if name == "1":
            run_1 = 0
        elif name == "2":
            run_2 = 0
    except:
        pass

hostname = socket.gethostname()
while True:
    try:
        run_1 = 1
        thread.start_new_thread(run,("1",))
        run_2 = 1
        thread.start_new_thread(run,("2",))
        while run_1 == 1 or run_2 == 1:
            time.sleep(2)
    except:
        continue
