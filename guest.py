import os
import libvirt
import libvirt_qemu
import json

PAGESIZE = os.sysconf("SC_PAGE_SIZE") / 1024 #KiB

class Guest:

    stats = {}

    timestamp = -1

    uuid = -1

    pid = -1

    domname = ""

    maxmem = -1

    currentmem = -1

    #actualmem = -1

    allocatedmem = -1

    usedmem = -1

    loadmem = -1

    avgUsed = -1

    alpha = 0.1

    thresh = 0.95

    def __init__(self, libvirtDomain):
        self.domain = libvirtDomain
        self.uuid = libvirtDomain.UUIDString()
        self.domName = libvirtDomain.getName()
        self.pid = self.getPid()


        self.setPollInterval()
        self.maxmem = self.domain.maxMemory()/1024
        print 'maxmem: ' + str(self.maxmem)
        self.getMemoryStats()
        self.currentmem = self.stats['stat-total-memory']
        print 'currentmem: ' + str(self.currentmem)
        #usedmem should be caclulated before allocatedmem
        self.usedmem = self.stats['stats-total-memory'] - self.stats['stats-free-memory']
        self.avgUsed = self.getLoadMem()
        self.allocatedmem = self.getAllocatedMem()
        print 'allocatedmem: '+self.allocatedmem

    def monitor(self):
        # calculate used memory
        self.getMemoryStats()
        self.usedmem = self.stats['stats-total-memory'] - self.stats['stats-free-memory']
        self.loadmem = self.getLoadMem()
        self.avgUsed = self.alpha*self.loadmem + (1-self.alpha)*self.avgUsed
        # calculate the allocated memory
        self.allocatedmem = self.getAllocatedMem()
        return self.avgUsed

    def getLoadMem(self):
        return self.stats['stat-total-memory'] - self.stats['stat-free-memory'] - 0.9*self.stats['stats-buffer-cache']

    # Convert the stats to MB
    def toMb(self, stats):
        newStats = {}
        for key in stats.keys():
            newStats[key] = round(stats[key]/1024)
        return newStats


    def setPollInterval(self):
        setPollIntervalCommand = {
                'execute':'qom-set',
                'arguments':{
                    'path':'/machine/peripheral/balloon0',
                    'property':'guest-stats-polling-interval',
                    'value':2
                    }
                }
        libvirt_qemu.qemuMonitorCommand(self.domain, json.dumps(setPollIntervalCommand), 0)

    def getMemoryStats(self):
        memStatsCommand = {
                'execute': 'qom-get',
                'arguments': {
                    'path':'/machine/peripheral/balloon0',
                    'property':'guest-stats',
                    }
                }
        try:
            out = libvirt_qemu.qemuMonitorCommand(self.domain, json.dumps(memStatsCommand), 0)
            if self.timestamp < out['return']['last-update']:
                self.stats = self.toMb(out['return']['stats'])
        except:
            print "Unable to get stats of Domain: " + self.uuid

    def getPid(self):
        pid = open('/var/run/libvirt/qemu/'+self.domName+'.pid').read()
        return int(pid)

    # return the overhead of the qmeu process.
    def getQemuOverhead(self):
        # Using a piece-wise continous function right now
        if self.maxmem <= 4*1024:
            return 200
        elif self.maxmem <= 10*1024:
            return 300
        elif self.maxmem <= 18*1024:
            return 400
        else:
            return 500
        pass

    def getAllocatedMem(self):
        try:
            Rss = (int(proc.open('/proc/'+self.pid+'/statm').readline().split()[1])
                       * PAGESIZE)
            return max((Rss - self.getQemuOverhead())/1024, self.usedmem) # Mb
        except:
            "Unable to get Actual memory of domain: " + self.domName

    def balloon(self, target):
        print "Ballooning " + self.domName + " from "+self.currentmem+" to "+ target
        self.domain.setMemory(target*1024)
        print "Finished ballooning " + self.domName


