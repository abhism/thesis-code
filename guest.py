import os
import libvirt
import libvirt_qemu
import json
import logging
import subprocess

PAGESIZE = os.sysconf("SC_PAGE_SIZE") / 1024 #KiB

class Guest:

    stats = {}

    timestamp = -1

    uuid = -1

    pid = -1

    domname = ""

    maxmem = -1

    currentActualmem = -1

    currentmem = -1

    allocatedmem = -1

    usedmem = -1

    loadmem = -1

    # available memory taken from the 3rd line of /proc/meminfo
    #availablemem = -1

    avgUsed = -1

    alpha = 0.1

    thresh = 0.95

    def __init__(self, libvirtDomain):
        self.domain = libvirtDomain
        self.uuid = libvirtDomain.UUIDString()
        self.domName = libvirtDomain.name()
        self.pid = self.getPid()

        self.setPollInterval()
        self.maxmem = self.domain.maxMemory()/1024
        self.getMemoryStats()
        self.currentmem = self.stats['stat-total-memory']
        # There is a slight gap between the currentmem which is set and which is reported by the VM.
        # currentActualmem is the memory that is set by the user while currentmem is reported by the VM.
        self.currentActualmem = self.domain.info()[2]/1024
        # usedmem should be caclulated before allocatedmem
        self.usedmem = self.stats['stat-total-memory'] - self.stats['stat-free-memory']
        self.avgUsed = self.getLoadMem()
        self.allocatedmem = self.getAllocatedMem()
        self.logStats()

    def monitor(self):
        # calculate used memory
        self.getMemoryStats()
        self.maxmem = self.domain.maxMemory()/1024
        self.currentmem = self.stats['stat-total-memory']
        self.currentActualmem = self.domain.info()[2]/1024
        self.usedmem = self.stats['stat-total-memory'] - self.stats['stat-free-memory']
        self.loadmem = self.getLoadMem()
        self.avgUsed = self.alpha*self.loadmem + (1-self.alpha)*self.avgUsed
        # calculate the allocated memory
        self.allocatedmem = self.getAllocatedMem()
        self.logStats()
        return self.avgUsed

    def getLoadMem(self):
        return self.stats['stat-total-memory'] - self.stats['stat-available-memory']

    # Convert the stats to MB
    def toMb(self, stats):
        newStats = {}
        for key in stats.keys():
            newStats[key] = round(stats[key]/(1024*1024))
        ## TODO: remove the line below when using modified qemu
        if 'stat-available-memory' not in newStats.keys():
            logging.error('guest memory stats do not have available memory. Use the modified qemu')
            newStats['stat-available-memory'] = newStats['stat-free-memory']
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
        try:
            libvirt_qemu.qemuMonitorCommand(self.domain, json.dumps(setPollIntervalCommand), 0)
        except Exception as e:
            logging.exception("name: %s, uuid: %s, Unable to set poll interval",self.domName, self.uuid)


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
            out = json.loads(out)
            if self.timestamp < out['return']['last-update']:
                self.stats = self.toMb(out['return']['stats'])
            self.log('stats: %s', self.stats)
        except Exception as e:
            logging.exception("name: %s, uuid: %s, Unable to get stats",self.domName, self.uuid)

    def getPid(self):
        pid = open('/var/run/libvirt/qemu/'+self.domName+'.pid').read()
        return pid

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
            Rss = self.usedmem
            mmaps = subprocess.check_output(['pmap','-X',self.pid]).splitlines()[2:]
            for mmap in mmaps:
                splits = mmap.split()
                if int(splits[5]) == self.domain.maxMemory():
                    Rss = int(splits[6])
                    break
            return max(Rss/1024 - self.getQemuOverhead(), self.usedmem) # Mb
        except Exception as e:
            logging.exception("name: %s, uuid: %s, Unable to get allocated memory",self.domName, self.uuid)
            # Fallback in case cannot get allocated memory
            return self.currentmem

    def balloon(self, target):
        self.log("Started ballooning form %dMB to"+str(target)+"MB", self.currentmem)
        self.domain.setMemory(int(target*1024))
        self.log("Finished ballooning %s", "")

    def log(self, msg, extra):
        logging.debug("name: %s, uuid: %s, "+msg,self.domName, self.uuid, extra)

    def logStats(self):
        self.log('maxmem: %dMB', self.maxmem)
        self.log('currentmem: %dMB', self.currentmem)
        self.log('allocatedmem: %dMB', self.allocatedmem)
        self.log('usedmem: %dMB', self.usedmem)
        self.log('loadmem: %dMB', self.loadmem)
        self.log('avgUsed: %dMB', self.avgUsed)


