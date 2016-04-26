import os
import libvirt
import libvirt_qemu
import json
from globals import *

PAGESIZE = os.sysconf("SC_PAGE_SIZE") / 1024 #KiB

class Guest:

    stats = {}

    timestamp = -1

    uuid = -1

    pid = -1

    # vCpuPid should be an instance varibale
    # declaring it here will create a class varibale, hence declaring it inside init
    # refer to http://stackoverflow.com/questions/8701500/python-class-instance-variables-and-class-variables
    #vCpuPid = []

    domName = ""

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

    # this should be 0, not -1 like others
    stealTime = 0

    busyTime = 0

    avgSteal = -1

    avgBusy = -1

    avgCpuDemand = -1

    prevWaitTime = 0

    prevBusyTime = 0

    prevTotalTime = 0

    def __init__(self, libvirtDomain):
        self.vCpuPid = []

        self.domain = libvirtDomain
        self.uuid = libvirtDomain.UUIDString()
        self.domName = libvirtDomain.name()
        self.pid = self.getPid()
        self.getvCpuPid()

        self.avgSteal, self.avgBusy = self.getCpuStats()
        self.avgCpuDemand = self.avgBusy*(1+self.avgSteal/100)

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
        # calculate average steal time
        steal, busy = self.getCpuStats()
        self.avgSteal = self.alpha*steal + (1-self.alpha)*self.avgSteal
        self.avgBusy = self.alpha*busy + (1-self.alpha)*self.avgBusy
        # cpu demad is scaled value of actual cpu usage
        self.avgCpuDemand = self.avgBusy*(1+self.avgSteal/100)

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
        # reserving around 500MB of memory
        if self.stats['stat-available-memory'] > 500:
            return self.stats['stat-total-memory'] - (self.stats['stat-available-memory'] - 500)
        else:
            return self.stats['stat-total-memory']

    # Convert the stats to MB
    def toMb(self, stats):
        newStats = {}
        for key in stats.keys():
            newStats[key] = round(stats[key]/(1024*1024))
        ## TODO: remove the line below when using modified qemu
        if 'stat-available-memory' not in newStats.keys():
            errorlogger.error('guest memory stats do not have available memory. Use the modified qemu')
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
            libvirt_qemu.qemuMonitorCommand(self.domain,
                json.dumps(setPollIntervalCommand), 0)
        except Exception as e:
            errorlogger.exception("name: %s, uuid: %s, Unable to set poll interval",
                self.domName, self.uuid)


    def getMemoryStats(self):
        memStatsCommand = {
                'execute': 'qom-get',
                'arguments': {
                    'path':'/machine/peripheral/balloon0',
                    'property':'guest-stats',
                    }
                }
        try:
            out = libvirt_qemu.qemuMonitorCommand(self.domain,
                json.dumps(memStatsCommand), 0)
            out = json.loads(out)
            if self.timestamp < out['return']['last-update']:
                self.stats = self.toMb(out['return']['stats'])
            #self.log('stats: %s', self.stats)
        except Exception as e:
            errorlogger.exception("name: %s, uuid: %s, Unable to get stats",
                self.domName, self.uuid)

    def getvCpuPid(self):
        command = {
            'execute': 'query-cpus',
        }
        try:
            out = libvirt_qemu.qemuMonitorCommand(self.domain, json.dumps(command), 0)
            out = json.loads(out)
            for cpu in out['return']:
                self.vCpuPid.append(str(cpu['thread_id']))
        except Exception as e:
            errorlogger.exception("name: %s, uuid: %s, Unable to get vCpuPid",
                self.domName, self.uuid)

    def getCpuStats(self):
        global cpuCores
        # waitTime and busytime are in nano seconds
        waitTime = 0
        busyTime = 0
        totalTime = 0
        try:
            for vCpu in self.vCpuPid:
                f = open('/proc/%s/task/%s/schedstat' % (self.pid, vCpu))
                v = f.read().split()
                waitTime += int(v[1])
                busyTime += int(v[0])
                f.close()
            waitTime = waitTime/len(self.vCpuPid)
            busyTime = busyTime/len(self.vCpuPid)
        except Exception as e:
            errorlogger.exception("name: %s, uuid: %s, Unable to get wait time",
                self.domName, self.uuid)
        try:
            with open('/proc/stat') as stat:
                values = stat.read().split('\n')[0].split()
                # totaltime is in seconds
                # assumes that 1 jiffy is 1/100 of a second
                # TODO: better way would be to take that value from sysconf
                totalTime = ((int(values[1]) + int(values[3]) + int(values[4]) +
                    int(values[5]) + int(values[6]) + int(values[7]))/float(100))
                # Since there multiple cores and total time is sum of time on all cores
                totalTime = totalTime / cpuCores
        except Exception as e:
            errorlogger.exception("name: %s, uuid: %s, Unable to get total time",
                self.domName, self.uuid)
        if self.prevWaitTime !=0 and (totalTime-self.prevTotalTime) > 0:
            self.stealTime = (waitTime-self.prevWaitTime)/float(totalTime-self.prevTotalTime)
            self.busyTime = (busyTime-self.prevBusyTime)/float(totalTime-self.prevTotalTime)
            # make steal and time into percentage
            self.stealTime = self.stealTime/10000000
            self.busyTime = self.busyTime/10000000
        self.prevWaitTime = waitTime
        self.prevBusyTime = busyTime
        self.prevTotalTime = totalTime
        return (self.stealTime, self.busyTime)

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
            f = open('/proc/'+self.pid+'/smaps')
            lines = f.readlines()
            for index, l in enumerate(lines):
                splits = l.split()
                if len(splits) > 2 and splits[0] == 'Size:' and int(splits[1]) == self.domain.maxMemory():
                    Rss = int(lines[index+1].split()[1])
                    break
            return max(Rss/1024 - self.getQemuOverhead(), self.usedmem) # Mb
        except Exception as e:
            errorlogger.exception("name: %s, uuid: %s, Unable to get allocated memory",self.domName, self.uuid)
            # Fallback in case cannot get allocated memory
            return self.currentmem

    def balloon(self, target):
        if config.getboolean('monitor', 'balloon'):
            self.log("Started ballooning form %dMB to"+str(target)+"MB", self.currentmem)
            self.domain.setMemory(int(target*1024))
            self.log("Finished ballooning %s", "")
        else:
            self.log("Ballooning disabled in config. Unable to balloon %s", self.domName)

    def log(self, msg, extra):
        debuglogger.debug("name: %s, uuid: %s, "+msg,self.domName, self.uuid, extra)

    def logStats(self):
        global guestLog
        guestLog[self.domName] = {}
        guestLog[self.domName]['guestmaxmem'] = self.maxmem
        guestLog[self.domName]['guestcurrentmem'] = self.currentmem
        guestLog[self.domName]['guestallocatedmem'] = self.allocatedmem
        guestLog[self.domName]['guestusedmem'] = self.usedmem
        guestLog[self.domName]['guestloadmem'] = self.loadmem
        guestLog[self.domName]['guestavgusedmem'] = self.avgUsed
        guestLog[self.domName]['gueststealTime'] = self.stealTime
        guestLog[self.domName]['guestbusytime'] = self.busyTime
        guestLog[self.domName]['guestavgBusytime'] = self.avgBusy
        guestLog[self.domName]['guestavgCpuDemand'] = self.avgCpuDemand

        self.log('busytime: %f', self.busyTime)
        self.log('avgBusytime: %f', self.avgBusy)
        self.log('stealtime: %f', self.stealTime)
        self.log('avgCpuDemand: %f', self.avgCpuDemand)
        self.log('maxmem: %dMB', self.maxmem)
        self.log('currentmem: %dMB', self.currentmem)
        self.log('allocatedmem: %dMB', self.allocatedmem)
        self.log('usedmem: %dMB', self.usedmem)
        self.log('loadmem: %dMB', self.loadmem)
        self.log('avgUsed: %dMB', self.avgUsed)
