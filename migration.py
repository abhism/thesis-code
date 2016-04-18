from globals import *
import threading
import time

def handle():
    if migrationFlag:
        debuglogger.debug('A guest is already under Migration')
        return
    hosts = nova_demo.hypervisors.list()
    vmUuid = select_vm()
    # TODO: explore if VmSize can be usedmem instead of currentmem
    destination = select_dest(hosts, hostname, guests[vmUuid])
    if destination != -1:
        try:
            debuglogger.debug('Started migrating VM %s to host %s', vmUuid, hosts[destination].host_name)
            migrationFlag = True
            nova_admin.servers.live_migrate(vmUuid, hosts[destination].host_name, False, False);
            migrationStatusThread = threading.Thread(target=migrationStatus, args=(vmUuid,), name="migrationStatus")
            migrationStatusThread.start()
        except Exception as e:
            errorlogger.exception('Error in migrating vm')
            migrationFlag = False


def migrationStatus(vmUuid):
    x = nova_demo.servers.get(vmUuid).status
    start = time.time()
    while(x=='MIGRATING'):
        time.sleep(1)
        x = nova_demo.servers.get(vmUuid).status
        if(time.time()- start > 300):
            errorlogger.error('Migrating VM %s is taking too much time - %f.', time.time() - start)
    end = time.time()
    migrationFlag = False
    debuglogger.debug('Finished migrating VM %s in %f time',vmUuid, end-start)

def select_dest(hosts,hostname, guest):
    index = -1
    mn = 1000000.0
    for i in hosts:
        if (i.host_name==hostname):
            continue
        key1 = i + '/loadmem'
        key2 = i + '/totalmem'
        key3 = i + '/cpucores'
        key4 = i + '/usedcpu'
        mem_used = float(etcdClient.read(key1).value)
        mem_total = float(etcdClient.read(key2).value)
        cpu_cores = int(etcdClient.read(key3).value)
        cpu_used = float(etcdClient.read(key4).value)
        # TODO: VVIP xxx should it be vmSize or memused?
        # What about overcommitment here?
        if ((mem_used+guest.currentActualmem)>mem_total):
                continue

        guestCpuUsage = guest.avgBusy*host.cpuCores
        guestCpuDemand = guest.avgCpuDemand*host.cpuCores
        guestUnsatisfiedDemand = guestCpuDemand - guestCpuUsage
        destCpuUsage = cpu_used*cpu_cores
        destCpuCapacity = 100*cpu_cores
        # if not even half of the unsatisfied, do not migrate.
        # TODO: is 0.5 the best parameter
        if (destCpuCapacity - destCpuUsage) < (guestCpuUsage+0.5*guestUnsatisfiedDemand):
            continue
        mem = guest.currentActualmem + mem_used
        cpu = guestCpuDemand + destCpuUsage
        cost = pow(len(hosts),mem/mem_total) + pow(len(hosts),cpu/destCpuCapacity)
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
