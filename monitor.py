import os
import libvirt
import libvirt_qemu
import sys
import json
import threading
import time
import pprint
from host import *
from guest import *

#config = {}
#
#config["host"] = {
#        "alpha": 0.1,
#        "migration_threshold": 0.8,
#        "slack_factor": 0,
#        "design_parameter": 7,
#        "window_size": 200000,
#        "cache_factor": 0.1,
#        "hypervisor_reserved": 500
#        }
#
#config["guest"] = {
#        "alpha": 0.1,
#        "threshold": 0.95,
#        "cache_factor": 0.1
#        }

# Memory in MB reserved for hypervisor. This memory should not be given to guests
hypervisor_reserved = 500
guest_reserved = 500

guests = {}
host = None


# Run the libvirt event loop
def virEventLoopNativeRun():
    while True:
        libvirt.virEventRunDefaultImpl()


def virEventLoopNativeStart():
    global eventLoopThread
    libvirt.virEventRegisterDefaultImpl()
    eventLoopThread = threading.Thread(target=virEventLoopNativeRun, name="libvirtEventLoop")
    eventLoopThread.setDaemon(True)
    eventLoopThread.start()


# Event callbacks
def eventToString(event):
    eventStrings = ( "Defined",
                     "Undefined",
                     "Started",
                     "Suspended",
                     "Resumed",
                     "Stopped",
                     "Shutdown" )
    return eventStrings[event]

def domainLifecycleCallback(conn, domain, event, detail, opaque):
    eventType = eventToString(event)
    if(eventType == "Started" or eventType == "Resumed"):
        addNewDomain(domain)
        print "started a new domain: "+domain.UUIDString()
    elif(eventType == "Shutdown" or eventType == "Suspended" or eventType == "Stopped"):
        removeDomain(domain)
        print "stopped a domain: "+domain.UUIDString()


def addNewDomain(domain):
    global guests
    guests[domain.UUIDString] = Guest(domain)


def removeDomain(domain):
    global guests
    del guests[domain.UUIDString()]

def calculateSoftIdle(guest):
    lower = max(guest.usedmem, guest_reserved)
    return max(guest.allocatedmem - lower, 0)

def calculateHardIdle(guest):
    lower = max(guest.loadmem, guest_reserved)
    return max(guest.usedmem - lower, 0)

def calculatePot(host, idleMemory):
    return host.totlamem - host.loadmem - idleMemory

def monitor():
    global guests
    global host
    # guests with idle memory to give away
    softIdle = {}
    hardIdle = {}
    # guests which need more memory
    needy = {}
    # extra memory that is needed by the guests which are under load
    extraMemory = 0
    # IdleMemory is the one which has been allocated to the the qemu process, but is free inside the guest VM.

    # Soft Ballooning:
    # This is the process of ballooning out the free memory from
    # the guest VM.
    # ex- If a VM has allocated 4GB of memory from host and is using
    # 3GB memory, the 1GB free memory can be recovered by just setting
    # currentmem = currentmem-1GB.

    # Hard Ballooning:
    # This is the process of ballooning out used memory from the guest
    # ex - if a VM has 4GB of memory and is using 3GB.
    # Suppose the currentmem is 5GB. Soft ballooning will set
    # currentmem to 4GB and reclaim 1GB of free memory.
    # After that setting decreasing the currentmem will not reclaim
    # any free memory till currentmem=3GB. After this stage, ballooning
    # will again start reclaiming memory. This is called hard ballooning

    # soft idle memory can bee recovered by soft ballooning.
    softIdleMemory = 0

    # hard idle memory can be recovered by hard ballooning
    hardIdleMemory = 0

    # Sum of the maxmem of all guest. Used to decide overcommitment factor and shares of each guest
    totalGuestMemory = 0.0


    # Monitor all the guests
    for uuid in guests.keys():
        guest = guests[uuid]
        try:
            guest.monitor()
            totalGuestMemory += guest.maxmem

            # Calculate Idle memory and ensure that currentmem does not fall below guest_reserved
            softIdle[uuid] = calculateSoftIdle(guest)
            hardIdle[uuid] = calculateHardIdle(guest)
            # add 10% more memory when guest is overloaded
            if guest.avgUsed > 0.95*guest.currentmem and guest.currentmem < self.maxmem:
                needy[uuid] = 0.1*guest.maxmem
                extraMemory += needy[uuid]
                # need guest do not have idle
                softIdle[uuid] = 0
                hardIdle[uuid] = 0
            softIdleMemory += softIdle[uuid]
            hardIdleMemory += hardIdle[uuid]
        except:
            print "Unable to monitor guest: " + uuid
    print 'Total Soft Idle Memory: ' + str(softIdleMemory)
    print 'Total Hard Idle Memory: ' + str(hardIdleMemory)

    # Monitor the host
    try:
    # Idle Memory  should be subtracted from guest used memory.
    # i.e. It should not count towards host load.
    # The result of this is that a host is only migrated when its
    # requirements cannot be satisfied after hard ballooning of all the other guests.
       host.monitor(softIdleMemory + hardIdleMemory)
        # This will try to migrate away guests of there is a overload
    except:
        print "Unable to monitor host"

    # If demands can be satisfied by soft reclamation
    if host.loadmem + hardIdleMemory + extraMemory <= host.totalmem:
        pot = calculatePot(host, softIdleMemory + hardIdleMemory)
        for uuid in needy.keys():
            needyGuest = guests[uuid]
            need = needy[uuid]
            # TODO: Fix the while loop. This might go into an infinite loop
            # Possibly stop when all guests ballooned
            while pot < need:
                idleUuid = softIdle.keys()[0]
                softIdleGuest = guests[idleUuid]
                softIdleGuestMem = softIdle[idleUuid]
                softIdleGuest.balloon(idleGuest.currentmem - softIdleGuestMem)
                pot += softIdleGuestMem
                del softIdle[idleUuid]
            needyGuest.balloon(needyGuest.currentmem + need )
            pot -= need

    # If hard reclamation required
    elif host.loadmem + extraMemory < host.totalmem:
        # pot represents the memory free to give away without ballooning
        # more memory can be added to pot buy ballooning down any guest
        # ballooning up a guest takes away memory from the pot
        pot = host.totalMem - host.allocatedmem
        needAfterSoft = extraMemory - softIdleMemory
        # take away proportional amount of memory from each idle guest
        for uuid in needy.keys():
            needyGuest = guests[uuid]
            need = needy[uuid]
            while pot < need:
                idleUuid = softIdle.keys()[0]
                idleGuest = guests[idleUuid]
                softIdleGuestMem = softIdle[idleUuid]
                hardIdleGuestMem = hardIdle[idleUuid]
                hardReclaim = (hardIdleGuestMem*needAfterSoft)/hardIdleMemory
                if hardReclaim > 0:
                    idleGuest.balloon(idleGuest.usedmem - hardReclaim)
                elif softIdleGuestMem > 0:
                    idleGuest.balloon(idleGuest.currentmem - softIdleGuestMem)
                pot += softIdleGuestMem + hardReclaim
                del softIdle[idleUuid]
                del hardIdle[idleUuid]
            needyGuest.balloon(neeedyGuest.currentmem + need)
            pot -= need
    # If not enough memory is left to give away
    else:
        # calcualte the entitlement of each guest
        idleMemory = 0
        idle = {}
        excessMemory = 0
        excessUsed = {}
        excessUsedMemory = 0
        for uuid in guests.keys():
            guest = guests[uuid]
            entitlement = (guest.maxmem*host.totalmem)/totalGuestMemory
            id entitlement < guest_reserved:
                print "WARNING: too less entitlement."+str(entitlement) + " MB for VM: "+ uuid
                #TODO: next line is wrong. Fix it.
                #The intent is that if entitlement is less than reserved,
                # the extra amount should be given from other VM's entitlement.
                # Below implementation may work, but is wrong
                totalGuestMemory -= (guest_reserved - entitlement)
                entitlement = guest_reserved
            if (uuid in needy.keys()) and guest.currentmem < entitlement:
                needy[uuid] = entitlement - guest.currentmem
                extraMemory += entitlement - guest.currentmem
            elif uuid in needy.keys():
                del needy[uuid]
                idle[uuid] = calculateSoftIdle(guest) + calculateHardIdle(guest)
                idleMemory += idle[uuid]
                excessUsed[uuid] = max(guest.currentmem - idle[uuid] - entitlement, 0)
            else:
                idle[uuid] = softIdle[uuid] + hardIdle[uuid]
                idleMemory += idle[uuid]
                excessUsed[uuid] = max(guest.currentmem - idle[uuid] - entitlement, 0)
        pot = calculatePot(host, idleMemory)
        needAfterIdle = extraMemory - idleMemory
        for needyUuid in needy.keys():
            needyGuest = guests[needyUuid]
            need = needy[needyUuid]
            while pot < need:
                excessUuid = idle.keys()[0]
                excessGuest = guests[excessUuid]
                usedReclaim = excessUsed[excessUuid]
                idleReclaim = idle[excessUuid]
                usedReclaim = (excessUsed[excessUuid]*needAfterIdle)/excessUsedMemory
                excessGuest.balloon(excessGuest.loadmem - usedReclaim)
                pot += idleReclaim + usedReclaim
                del idle[excessUuid]
                del excessUsed[excessUuid]
            needyGuest.balloon(neeedyGuest.currentmem + need)
            pot -= need
 

def main():
    # check if root
    if os.geteuid() != 0:
        sys.stderr.write("Sorry, root permission required.\n")
        sys.stderr.close()
        sys.exit(1)

    # connect to the hypervisor
    conn = libvirt.open('qemu:///system')
    if conn == None:
        print 'Failed to open connection to the hypervisor'
        sys.exit(1);

    # get the list of all domains managed by the hypervisor
    try:
        doms = conn.listAllDomains()
    except:
        print 'Failed to find the domains'
        sys.exit(1)

    # start the event loop
    virEventLoopNativeStart()
    # register callbacks for domain startup events
    conn.domainEventRegisterAny(None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, domainLifecycleCallback, None)

    host = Host(conn)

    for domain in doms:
        if domain.isActive():
            addNewDomain(domain)

    # Main montioring loop
    while True:
        monitor()
        time.sleep(2)


if __name__ == "__main__":
        main()
