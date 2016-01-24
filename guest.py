import libvirt
import libvirt_qemu
import json


class Guest:

    stats = {}

    timestamp = -1

    uuid = -1

    maxmem = -1

    currentmem = -1

    avgUsed = -1

    alpha = 0.1

    thresh = 0.95

    def __init__(self, libvirtDomain):
        self.domain = libvirtDomain
        self.uuid = libvirtDomain.UUIDString()
        self.setPollInterval()
        self.maxmem = self.domain.maxMemory()/1024
        print 'maxmem: ' + str(self.maxmem)
        self.getMemoryStats()
        self.currentmem = self.stats['stat-total-memory']
        print 'currentmem: ' + str(self.currentmem)
        self.avgUsed = self.getUsedMem()

    def monitor(self):
        self.getMemoryStats()
        self.avgUsed = self.alpha*self.getUsedMem + (1-self.alpha)*self.avgUsed
        if(self.avgUsed > 0.95*self.currentmem and self.currentmem < self.maxmem):
            print "balloon up"

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


