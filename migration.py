from globals import *
import threading
import time

def handle():
    hosts = nova_demo.hypervisors.list()
    vmUuid = select_vm()
    # TODO: explore if VmSize can be usedmem instead of currentmem
    destination = select_dest(hosts, hostname, guests[vmUuid].currentmem)
    if destination != -1:
        try:
            debuglogger.debug('Started migrating VM %s to host %s', vmUuid, hosts[destination].host_name)
            nova_admin.servers.live_migrate(vmUuid, hosts[destination].host_name, False, False);
            migrationStatusThread = threading.Thread(target=migrationStatus, args=(vmUuid,), name="migrationStatus")
            migrationStatusThread.start()
        except Exception as e:
            errorlogger.exception('Error in migrating vm')


def migrationStatus(vmUuid):
    x = nova_demo.servers.get(vmUuid).status
    start = time.time()
    while(x=='MIGRATING'):
        time.sleep(1)
        x = nova_demo.servers.get(vmUuid).status
        if(time.time()- start > 300):
            errorlogger.error('Migrating VM %s is taking too much time - %f.', time.time() - start)
    end = time.time()
    debuglogger.debug('Finished migrating VM %s in %f time',vmUuid, end-start)

def select_dest(hosts,hostname, vmSize):
    index = -1
    mn = 1000000.0
    for i in hosts:
        if (i.host_name==hostname):
            continue
        key2 = i + '/loadmem'
        key4 = i + '/totalmem'
        mem_used = float(etcdClient.read(key2).value)
        mem_total = float(etcdClient.read(key4).value)
        if ((mem_used+vmSize)>mem_total):
                continue
        mem = vmSize + mem_used
        cost = pow(len(hosts),(mem/mem_total))
        if (cost<mn):
            mn = cost
            index = i
    return index

# TODO: explore other options for selecting candidate vm
def select_vm():
    smallestUuid = None
    smallestmem = 1000000
    for uuid in guests.keys():
        if guests[uuid].currentmem < smallestmem:
            smallestUuid = uuid
            smallestmem = guests[uuid].currentmem
    return smallestUuid
