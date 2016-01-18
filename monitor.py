import libvirt
import libvirt_qemu
import sys
import json
import threading
import time
import pprint

###################################################
# Global Structures
##################################################
domains = {}

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



########################################################
# Qemu Monitor Commands
#########################################################
def setPollInterval(domain):
    setPollIntervalCommand = {
            'execute':'qom-set',
            'arguments':{
                'path':'/machine/peripheral/balloon0',
                'property':'guest-stats-polling-interval',
                'value':2
                }
            }
    libvirt_qemu.qemuMonitorCommand(domain, json.dumps(setPollIntervalCommand), 0)

def getMemStats(domain):
    global domains
    memStatsCommand = {
            'execute': 'qom-get',
            'arguments': {
                'path':'/machine/peripheral/balloon0',
                'property':'guest-stats',
                }
            }
    out = libvirt_qemu.qemuMonitorCommand(domain, json.dumps(memStatsCommand), 0)
    stats = json.loads(out)['return']['stats']
    domains[domain.UUIDString()]['stats'] = stats

def addNewDomain(domain):
    global domains
    uuid = domain.UUIDString()
    domains[uuid] = {'dom': domain, 'stats': {}}
    setPollInterval(domain)


def removeDomain(domain):
    global domains
    del domains[domain.UUIDString()]

def main():
    global domains
    conn = libvirt.open('qemu:///system')

    #start the event loop
    virEventLoopNativeStart()
    if conn == None:
        print 'Failed to open connection to the hypervisor'
        sys.exit(1);
    try:
        doms = conn.listAllDomains()
    except:
        print 'Failed to find the domains'
        sys.exit(1)
    #register callbacks for domain startup events
    conn.domainEventRegisterAny(None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, domainLifecycleCallback, None)
    for domain in doms:
        if domain.isActive():
            addNewDomain(domain)

    while True:
        for uuid in domains.keys():
            try:
                domain = domains[uuid]['dom']
                getMemStats(domain)
            except:
                print 'failed to get stats of: '+uuid
        print domains
        time.sleep(2)




if __name__ == "__main__":
        main()
#print libvirt_qemu.qemuMonitorCommand(dom0,'{"execute":"qom-get","arguments": { "path": "/machine/peripheral/balloon0","property":"guest-stats"}}',0)

#print dom0.OSType()
#print dom0.info()
