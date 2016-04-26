import os
import libvirt
import libvirt_qemu
import sys
import json
import threading
import time
import pprint
import logging
import ConfigParser
import requests
from host import *
from guest import *
from globals import *

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
    elif(eventType == "Shutdown" or eventType == "Suspended" or eventType == "Stopped"):
        removeDomain(domain)


def addNewDomain(domain):
    global guests
    guests[domain.UUIDString()] = Guest(domain)
    debuglogger.info("Added a new domain name: %s, uuid: %s ",domain.name(), domain.UUIDString())


def removeDomain(domain):
    global guests
    del guests[domain.UUIDString()]
    debuglogger.info("Removed a domain name: %s, uuid: %s ",domain.name(), domain.UUIDString())

def calculateSoftIdle(guest):
    guest_reserved = config.getint('monitor', 'guest_reserved')
    lower = max(guest.usedmem, guest_reserved)
    return max(guest.allocatedmem - lower, 0)

def calculateHardIdle(guest):
    guest_reserved = config.getint('monitor', 'guest_reserved')
    lower = max(guest.loadmem, guest_reserved)
    return max(guest.usedmem - lower, 0)

def calculatePot(host, idleMemory):
    return host.totalmem - host.loadmem - idleMemory

def monitor():
    global guests
    global host

    # steal time of all guests
    stealTime = {}

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

        assert uuid == guest.uuid

        debuglogger.debug('Monitoring guest name: %s, uuid: %s', guest.domName, uuid)
        try:
            guest.monitor()

            stealTime[uuid] = guest.avgSteal

            totalGuestMemory += guest.maxmem

            # Calculate Idle memory and ensure that currentmem does not fall below guest_reserved
            softIdle[uuid] = calculateSoftIdle(guest)
            hardIdle[uuid] = calculateHardIdle(guest)
            # add 10% more memory when guest is overloaded
            expansion_thresh = config.getfloat('monitor', 'expansion_thresh')
            if guest.avgUsed > expansion_thresh*guest.currentmem and guest.currentActualmem < guest.maxmem:
                needy[uuid] = min(0.1*guest.maxmem,guest.maxmem-guest.currentActualmem)
                guest.log("Is needy, need: %dMB", needy[uuid])
                extraMemory += needy[uuid]
                # need guest do not have idle
                softIdle[uuid] = 0
                hardIdle[uuid] = 0
            guest.log('Soft Idle is %dMB', softIdle[uuid])
            guest.log('Hard Idle is %dMB', hardIdle[uuid])
            softIdleMemory += softIdle[uuid]
            hardIdleMemory += hardIdle[uuid]
        except:
            errorlogger.exception('Unable to monitor guest name: %s, uuid: %s ',guest.domName, uuid)

    debuglogger.debug("Total soft idle memory: %dMB", softIdleMemory)
    debuglogger.debug("Total hard idle memory: %dMB", hardIdleMemory)
    debuglogger.debug("Extra Memory Required: %dMB", extraMemory)
    # Monitor the host
    try:
    # Idle Memory  should be subtracted from guest used memory.
    # i.e. It should not count towards host load.
    # The result of this is that a host is only migrated when its
    # requirements cannot be satisfied after hard ballooning of all the other guests.
       host.monitor(softIdleMemory + hardIdleMemory, stealTime)
        # This will try to migrate away guests of there is a overload
    except Exception as e:
        errorlogger.exception('Unable to monitor host')

    # If demands can be satisfied by soft reclamation
    if host.loadmem + hardIdleMemory + extraMemory <= host.totalmem:
        debuglogger.debug("Demands can be satisfied by soft reclamation")
        pot = calculatePot(host, softIdleMemory + hardIdleMemory)
        for uuid in needy.keys():
            needyGuest = guests[uuid]
            need = needy[uuid]
            while pot < need and len(softIdle.keys()) > 0:
                idleUuid = softIdle.keys()[0]
                softIdleGuest = guests[idleUuid]
                softIdleGuestMem = softIdle[idleUuid]
                softIdleGuest.balloon(softIdleGuest.currentActualmem - softIdleGuestMem)
                pot += softIdleGuestMem
                del softIdle[idleUuid]
            if(pot-need < -100):
                errorlogger.warn("More than 100MB deficit in pot. check the algo.")
            else:
                needyGuest.balloon(needyGuest.currentActualmem + need )
                pot -= need

    # If hard reclamation required
    elif host.loadmem + extraMemory < host.totalmem:
        debuglogger.debug("Demands need hard reclamation")
        # pot represents the memory free to give away without ballooning
        # more memory can be added to pot buy ballooning down any guest
        # ballooning up a guest takes away memory from the pot
        pot = host.totalMem - host.allocatedmem
        needAfterSoft = extraMemory - softIdleMemory
        # take away proportional amount of memory from each idle guest
        for uuid in needy.keys():
            needyGuest = guests[uuid]
            need = needy[uuid]
            while pot < need and len(softIdle.keys()) > 0:
                idleUuid = softIdle.keys()[0]
                idleGuest = guests[idleUuid]
                softIdleGuestMem = softIdle[idleUuid]
                hardIdleGuestMem = hardIdle[idleUuid]
                hardReclaim = (hardIdleGuestMem*needAfterSoft)/hardIdleMemory
                if hardReclaim > 0:
                    idleGuest.balloon(idleGuest.usedmem - hardReclaim)
                elif softIdleGuestMem > 0:
                    idleGuest.balloon(idleGuest.currentActualmem - softIdleGuestMem)
                pot += softIdleGuestMem + hardReclaim
                del softIdle[idleUuid]
                del hardIdle[idleUuid]
            if(pot-need < -100):
                errorlogger.warn("More than 100MB deficit in pot. check the algo.")
            else:
                needyGuest.balloon(neeedyGuest.currentActualmem + need)
                pot -= need
    # If not enough memory is left to give away
    else:
        debuglogger.debug("Overload, calculate entitlement")
        # calcualte the entitlement of each guest
        idleMemory = 0
        idle = {}
        excessMemory = 0
        excessUsed = {}
        excessUsedMemory = 0
        for uuid in guests.keys():
            guest = guests[uuid]
            entitlement = (guest.maxmem*host.totalmem)/totalGuestMemory
            if entitlement < guest_reserved:
                guest.log("Entitlement less than reserved: %dMB", entitlement)
                #TODO: next line is wrong. Fix it.
                #The intent is that if entitlement is less than reserved,
                # the extra amount should be given from other VM's entitlement.
                # Below implementation may work, but is wrong
                totalGuestMemory -= (guest_reserved - entitlement)
                entitlement = guest_reserved
            guest.log("Entitlement: %dMB", entitlement)
            if (uuid in needy.keys()) and guest.currentActualmem < entitlement:
                needy[uuid] = entitlement - guest.currentActualmem
                extraMemory += entitlement - guest.currentActualmem
            elif uuid in needy.keys():
                del needy[uuid]
                idle[uuid] = calculateSoftIdle(guest) + calculateHardIdle(guest)
                idleMemory += idle[uuid]
                excessUsed[uuid] = max(guest.currentActualmem - idle[uuid] - entitlement, 0)
            else:
                idle[uuid] = softIdle[uuid] + hardIdle[uuid]
                idleMemory += idle[uuid]
                excessUsed[uuid] = max(guest.currentActualmem - idle[uuid] - entitlement, 0)
        pot = calculatePot(host, idleMemory)
        needAfterIdle = extraMemory - idleMemory
        for needyUuid in needy.keys():
            needyGuest = guests[needyUuid]
            need = needy[needyUuid]
            while pot < need and len(idle.keys()) > 0:
                excessUuid = idle.keys()[0]
                excessGuest = guests[excessUuid]
                usedReclaim = excessUsed[excessUuid]
                idleReclaim = idle[excessUuid]
                usedReclaim = (excessUsed[excessUuid]*needAfterIdle)/excessUsedMemory
                excessGuest.balloon(excessGuest.loadmem - usedReclaim)
                pot += idleReclaim + usedReclaim
                del idle[excessUuid]
                del excessUsed[excessUuid]
            if(pot-need < -100):
                errorlogger.warn("More than 100MB deficit in pot. check the algo.")
            else:
                needyGuest.balloon(neeedyGuest.currentActualmem + need)
                pot -= need

def sendLog():
    global hostLog
    global guestLog
    if config.getboolean('influx','enabled'):
        db = config.get('influx','db')
        host = config.get('influx','host')
        payload = ""
        for key in hostLog.keys():
            payload = payload + (key+',host='+hostname+' value='+str(hostLog[key])+'\n')
        for guest in guestLog.keys():
            stat = guestLog[guest]
            for key in stat.keys():
                payload = payload + (key+',guest='+guest+',host='+hostname+' value='+str(stat[key])+'\n')
            # this metric is used to track migration
            n = hostname[-1:]
            try:
                n = int(n)
            except:
                n = ord(n)
            payload = payload + ('host,guest='+guest+' value='+str(n)+'\n')
        resp = requests.post('http://'+host+'/write?db='+db, data=payload)
        if resp.status_code != 204:
            debuglogger.warn('Unable to send request to influx db %s', resp.content)
    hostLog.clear()
    guestLog.clear()

def main():
    global config
    global host
    global guests
    global cpuCores

    # Set up logger
    #logging.basicConfig(filename='monitor.log',format='%(asctime)s: %(levelname)8s: %(message)s', level=logging.DEBUG)
    debuglogger.info('Monitoring started!')

    # check if root
    if os.geteuid() != 0:
        errorlogger.error('Root permission required to run the script! Exiting.')
        sys.exit(1)

    # connect to the hypervisor
    try:
        conn = libvirt.open('qemu:///system')
    except Exception as e:
        errorlogger.exception('Failed to open connection to the hypervisor, Exiting')
        sys.exit(1)

    if conn == None:
        errorlogger.error('Failed to open connection to the hypervisor, Exiting')
        sys.exit(1)

    # get the list of all domains managed by the hypervisor
    try:
        doms = conn.listAllDomains()
    except Exception as e:
        errorlogger.exception('Failed to find the domains, Exiting')
        sys.exit(1)

    # start the event loop
    try:
        virEventLoopNativeStart()
        debuglogger.info("libvirt event loop started")
    except Exception as e:
        errorlogger.exception('Failed to start libvirt event loop, Exiting')
        sys.exit(1)
    # register callbacks for domain startup events
    try:
        conn.domainEventRegisterAny(None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, domainLifecycleCallback, None)
        debuglogger.info("libvirt domain lifecycle callbacks registered")
    except Exception as e:
        errorlogger.exception('Failed to register domain lifecycle events, Exiting')

    cpuCores = conn.getCPUMap(0)[0]
    host = Host(conn)

    for domain in doms:
        if domain.isActive():
            addNewDomain(domain)

    # Main montioring loop
    while True:
        try:
            debuglogger.info("****Starting new round of monitoring***")
            monitor()
        except Exception as e:
            errorlogger.exception('An exception occured in monitoring')
        sendLog()
        time.sleep(config.getint('monitor', 'time'))


if __name__ == "__main__":
        main()
