import libvirt
import libvirt_qemu
import sys
import json
import threading
import time
import pprint
from host import *
from guest import *

###################################################
# Global Structures
##################################################
domains = {}
guests = {}

#####################################################
# Libvirt native event loop
####################################################
def virEventLoopNativeRun():
    while True:
        libvirt.virEventRunDefaultImpl()


def virEventLoopNativeStart():
    global eventLoopThread
    libvirt.virEventRegisterDefaultImpl()
    eventLoopThread = threading.Thread(target=virEventLoopNativeRun, name="libvirtEventLoop")
    eventLoopThread.setDaemon(True)
    eventLoopThread.start()

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

def main():
    global domains
    conn = libvirt.open('qemu:///system')
    if conn == None:
        print 'Failed to open connection to the hypervisor'
        sys.exit(1);
    try:
        doms = conn.listAllDomains()
    except:
        print 'Failed to find the domains'
        sys.exit(1)

    #start the event loop
    virEventLoopNativeStart()
    #register callbacks for domain startup events
    conn.domainEventRegisterAny(None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, domainLifecycleCallback, None)
    host = Host(conn)
    for domain in doms:
        if domain.isActive():
            addNewDomain(domain)

    # Main montioring loop
    while True:
        host.monitor()
        for uuid in guests.keys():
            try:
                guests[uuid].monitor()
            except:
                print 'failed to get stats of: '+uuid
        #print domains
        time.sleep(2)


if __name__ == "__main__":
        main()
