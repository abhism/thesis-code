from globals import *
import threading
import time

def handle(reason, totalmem):
    global migrationFlag
    global etcdClient
    global guests
    if migrationFlag:
        debuglogger.debug('A guest is already under Migration')
        return
    hosts = nova_admin.hypervisors.list()
    #vmUuid = select_vm(reason)
    # TODO: fix the list of hosts and the index
    # This part of code does not work
    (vmUuid, destination) = select_pair(hosts, reason, totalmem)
    if destination != -1 and vmUuid != -1:
        # reclaim memory from destination
        try:
            etcdClient.write('/'+destination.hypervisor_hostname+'/reclaim', guests[vmUuid].maxmem)
            # wait for  max 10 seconds to reclaim
            t = 0
            migrate = False
            while time < 10:
                time.sleep(2)
                t+=2
                if float(etcdClient.read('/' + destination.hypervisor_hostname + '/reclaim').value) <= 0:
                    migrate = True
                    break
            if not migrate:
                debuglogger.debug('Cannot migrate VM %s to host %s because of memory reclamation problems',
                        vmUuid, destination.hypervisor_hostname)
                return
            # migrate if memory reclaimed
            debuglogger.debug('Started migrating VM %s to host %s', vmUuid, destination.hypervisor_hostname)
            migrationFlag = True
            nova_admin.servers.live_migrate(vmUuid, destination.hypervisor_hostname, False, False);
            migrationStatusThread = threading.Thread(target=migrationStatus, args=(vmUuid,), name="migrationStatus")
            migrationStatusThread.start()
        except Exception as e:
            errorlogger.exception('Error in migrating vm')
            migrationFlag = False


def migrationStatus(vmUuid):
    global hostLog
    global migrationFlag
    global host
    x = nova_demo.servers.get(vmUuid).status
    start = time.time()
    while(x=='MIGRATING'):
        time.sleep(1)
        x = nova_demo.servers.get(vmUuid).status
        if(time.time()- start > 300):
            errorlogger.error('Migrating VM %s is taking too much time - %f.', str(vmUuid), time.time() - start)
            break
    end = time.time()
    migrationFlag = False
    debuglogger.debug('Finished migrating VM %s in %f time',vmUuid, end-start)
    hostLog['successMigration'] = host.muCpu


def select_pair(hosts, reason, totalmem):
    global guests
    global cpuCores
    global hostname
    pair = (-1,-1)
    mx = -10000000
    for i in hosts:
        if (i.hypervisor_hostname==hostname):
            continue
        key1 = i.hypervisor_hostname + '/loadmem'
        key2 = i.hypervisor_hostname + '/totalmem'
        key3 = i.hypervisor_hostname + '/cpucores'
        key4 = i.hypervisor_hostname + '/usedcpu'
        mem_used = float(etcdClient.read(key1).value)
        mem_total = float(etcdClient.read(key2).value)
        cpu_cores = int(etcdClient.read(key3).value)
        cpu_used = float(etcdClient.read(key4).value)
        destCpuUsage = cpu_used*cpu_cores
        destCpuCapacity = 100*cpu_cores
        for uuid in guests.keys():
            guest = guests[uuid]
            # TODO: VVIP xxx should it be vmSize or memused?
            # What about overcommitment here?
            if ((mem_used+guest.maxmem)>mem_total):
                    continue
            guestCpuUsage = guest.avgBusy*cpuCores
            guestCpuDemand = guest.avgCpuDemand*cpuCores
            guestUnsatisfiedDemand = guestCpuDemand - guestCpuUsage
            # if not even half of the unsatisfied, do not migrate.
            # TODO: is 0.5 the best parameter
            if (destCpuCapacity - destCpuUsage) < (guestCpuUsage+0.5*guestUnsatisfiedDemand):
                continue
            mem = guest.usedmem + mem_used
            cpu = min(guestCpuDemand + destCpuUsage, destCpuCapacity)
            cost = pow(len(hosts),mem/float(mem_total)) + pow(len(hosts),cpu/float(destCpuCapacity))
            cost = (cost*100)/float(2*len(hosts))
            benefit = 0
            if reason == "memory":
                benefit = (guest.allocatedmem*100)/float(totalmem)
                benefit = benefit/float(len(guests))
            if reason == "cpu":
                benefit = guest.avgBusy/float(len(guests))
            # select the guest with maximum (benefit-cost)
            if (benefit-cost>mx):
                mx = benefit-cost
                pair = (uuid, i)
    return pair

# TODO: explore other options for selecting candidate vm
# def select_vm(reason):
#     global guests
#     smallestUuid = None
#     smallestmem = 1000000
#     resourceUsed = 0
#     for uuid in guests.keys():
#         if reason == "memory":
#             resourceUsed = (guests[uuid].usedmem*100)/float(guests[uuid].maxmem)
#         elif:
#             resourceUsed = guests[uuid].busyTime
#         if guests[uuid].currentmem <= smallestmem and resourceUsed > 10:
#             smallestUuid = uuid
#             smallestmem = guests[uuid].currentmem
#     return smallestUuid
