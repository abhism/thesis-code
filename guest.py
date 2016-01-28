import os
import libvirt
import libvirt_qemu
import json

PAGESIZE = os.sysconf("SC_PAGE_SIZE") / 1024 #KiB

class Guest:

    stats = {}

    timestamp = -1

    uuid = -1

    maxmem = -1

    currentmem = -1

    actualmem = -1

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
        self.avgUsed = self.getUsedMem()
        self.actualmem = self.getActualMem()
        print 'actualmem: '+self.actualmem

    def monitor(self):
        # calculate used memory
        self.getMemoryStats()
        self.avgUsed = self.alpha*self.getUsedMem + (1-self.alpha)*self.avgUsed
        # calculate the actula memory
        self.actualmem = self.getActualMem()
        return self.avgUsed
        #if(self.avgUsed > 0.95*self.currentmem and self.currentmem < self.maxmem):
         #   print "balloon up"

    def getUsedMem(self):
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



    def getActualMem(self):
        try:
            Rss = (int(proc.open('/proc/'+self.pid+'/statm').readline().split()[1])
                       * PAGESIZE)
            return Rss/1024 # Mb
        except:
            "Unable to get Actual memory of domain: " + self.domName


