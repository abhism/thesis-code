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


def monitor():
    global guests
    global host
    # guests with idle memory to give away
    idle = {}
    # guests which need mopre memory
    needy = {}
    # extra memory that is needed by the guests which are under load
    extraMemory = 0
    # IdleMemory is the one which has been allocated to the the qemu process, but is free inside the guest VM.
    # This memory can be retrieved by ballooning, hence should not be counted in used memory of the host
    idleMemory = 0
    # Sum of the maxmem of all guest. Used to decide overcommitment factor and shares of each guest
    totalGuestMemory = 0.0


    # Monitor all the guests
    for uuid in guests.keys():
        guest = guests[uuid]
        try:
            guest.monitor()
            totalGuestMemory += guest.maxmem
            # TODO: Doubt whether usedMem or avgUsed should be used here
            if guest.actualmem - guest.usedMem > 0:
                idle[uuid] = guest.actualmem - guest.usedMem
                idleMemory += idle[uuid]
            # add 10% more memory when guest is overloaded
            if guest.avgUsed > 0.95*guest.currentmem and guest.currentmem < self.maxmem:
                needy[uuid] = 0.1*guest.maxmem
                extraMemory += needy[uuid]
        except:
            print "Unable to monitor guest: " + uuid
    print 'Total Idle Memory: ' + str(idleMemory)


    # Monitor the host
    try:
       host.monitor(idleMemory)
        # This will try to migrate away guests of there is a overload
    except:
        print "Unable to monitor host"


    # If enough memory is left to give away
    if host.usedMem + extraMemory < host.totalMem:
        # pot represents the memory free to give away without ballooning
        # more memory can be added to pot buy ballooning down any guest
        # ballooning up a guest takes away memory from the pot
        pot = host.totalMem - host.usedMem
        for uuid in needy.keys():
            needyGuest = guests[uuid]
            need = needy[uuid]
            while pot < need:
                idleUuid = idle.keys()[0]
                idleGuest = guests[idleUuid]
                guestIdlemem = idle[idleUuid]
                idleGuest.balloon(idleGuest.currentmem - guestIdlemem)
                pot += guestIdlemem
            needyGuest.balloon(neeedyGuest.currentmem + need)
    # If not enough memory is left to give away
    else:
        # calculate entitlement of each guest
        entitlement = {}
        pot = host.totalMem - (host.usedMem + idleMemory)
        overcommitmentFactor = host.totalMem/totalGuestMemory
        excess = {}
        canGive = 0
        for uuid in guests.keys():
            guest = guests[uuid]
            entitlement[uuid] = overcommitmentFactor*guest.maxmem
            lowerBound = min(entitlement[uuid], guest.usedMem)
            if guest.actualmem - lowerBound > 0:
                excess[uuid] = guest.actualmem - lowerBound
                canGive += excess[uuid]
                if uuid in needy:
                    del needy[uuid]
                    extraMemory -= 0.1*guest.maxmem




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
