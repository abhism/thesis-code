# coding=UTF-8

import libvirt
import math
from collections import deque
import numpy
import time
import os
import migration
from globals import *


PAGESIZE = os.sysconf("SC_PAGE_SIZE") / 1024 #KiB

class RunningStats:
    windowSize = 200000
    n = 0
    s1 = 0
    s2 = 0

    def __init__(self, used):
        self.data = deque([])
        for i in range(20000):
            if used > 100:
                self.data.append(numpy.random.randint(used-250, used+250))
            else:
                self.data.append(numpy.random.randint(0,100))
            self.n+=1
        pass

    def add(self, x):
        if(self.n < self.windowSize):
            self.n = self.n+1
            popped = 0
        else:
            popped = self.data.popleft()
        #self.s1 = self.s1+x - popped
        #self.s2 = self.s2+ x*x - popped*popped
        self.data.append(x)

    def variance(self):
        if self.n > 1:
            return (self.s2-self.n*self.s1*self.s1)/(self.n-1)
        else:
            return 0.0

    def standardDeviation(self):
        #var = self.variance()
        #return math.sqrt(var)
        #start = time.time()
        dev = numpy.std(self.data)
        #end = time.time()
        return dev;


class Host:

    #the weight of moving average
    alpha = 0.1

    # the moving average
    muMem = 0
    muCpu = 0

    # threshold for migration
    thresh = 1
    totalmem = -1

    usedmem = -1

    loadmem = -1

    # accumulated deviation
    dMem = 0
    dCpu = 0
    #slack factor
    KMem = 0
    KCpu = 0

    #the design parameter
    h = 7

    prevTotalTime = 0

    prevBusyTime = 0

    cpuUsage = 0

    cpuCores = 0

    # candidates for migration due to cpu load
    maybeMigrate = {}

    def __init__(self, conn):
        self.conn = conn
        self.cpuCores = self.conn.getCPUMap(0)[0]
        self.thresh = config.getfloat('migration', 'migration_thresh')
        stats = self.getMemoryStats()
        self.totalmem = stats['total']
        self.usedmem = stats['total'] - stats['free']
        self.loadmem = self.getLoadMem(stats, 0)
        self.muMem = self.loadmem

        self.getCpuUsage()
        self.muCpu = self.cpuUsage

        self.stdMem = RunningStats(self.loadmem)
        self.stdCpu = RunningStats(self.cpuUsage)
        self.updateEtcd()


    def updateEtcd(self):
        if config.getboolean('etcd', 'enabled'):
            etcdClient.write('/'+hostname+'/totalmem', self.totalmem)
            etcdClient.write('/'+hostname+'/loadmem', self.muMem)
            etcdClient.write('/'+hostname+'/cpucores',self.cpuCores)
            etcdClient.write('/'+hostname+'/usedcpu',self.muCpu)


    def getMemoryStats(self):
        stats = self.conn.getMemoryStats(libvirt.VIR_NODE_MEMORY_STATS_ALL_CELLS, 0)
        return self.toMb(stats)

    # Convert the stats to MB
    def toMb(self, stats):
        newStats = {}
        for key in stats.keys():
            newStats[key] = round(stats[key]/1024)
        debuglogger.debug("Stats: %s", str(newStats))
        return newStats

    # get used memory form statistics
    # TODO: find a way to use swap memory in loadmem too
    # TODO: does taking away all of the available memory make sense?
    # Or should there be a cap on the maximum amount of memory that can be taken
    # away in a step, and also increased in a step?
    def getLoadMem(self, stats, idleMemory):
        hypervisor_reserved = config.getint('monitor', 'hypervisor_reserved')
        vmLoad = self.getVMLoad()
        hypervisorLoad = stats['total'] - stats['free'] - (stats['buffers'] + stats['cached'])- vmLoad
        # hypervisor_extra ensures that atleast hypervisor_reserved memory is added towards host's load
        hypervisor_extra = max(hypervisor_reserved-hypervisorLoad, 0)
        debuglogger.debug("Hypervisor Load is %dMB", hypervisorLoad)
        #load = vmLoad + hypervisorLoad + 0.1*(stats['buffers']+stats['cached']) - idleMemory#TODO: modify 0.9
        load = (stats['total'] - self.getAvailableMemory()) + hypervisor_extra - idleMemory
        return load

    def monitor(self, idleMemory, stealTime):
        self.checkMemory(idleMemory)
        self.checkCpu(stealTime)
        self.logStats()

    def checkMemory(self, idleMemory):
        stats = self.getMemoryStats()
        self.totalmem = stats['total']
        # k is the slack factor which is equal to ∆/2 where ∆ is minimum shift to be detected
        # Here, we have taken ∆ as 0.1 i.e minimum 1% shift is to be detected
        self.KMem = 0.005*self.totalmem
        self.usedmem = stats['total'] - stats['free']
        # calculate moving average
        self.loadmem = self.getLoadMem(stats, idleMemory)
        self.muMem = self.alpha*self.loadmem + (1-self.alpha)*self.muMem
        # calcualte the deviation
        self.dMem = self.dMem+self.loadmem-(self.muMem+self.KMem)
        self.stdMem.add(self.loadmem)
        H = self.h*self.stdMem.standardDeviation()
        if(abs(self.dMem) > H):
            print 'Profile Changed'
            self.updateEtcd()
            # TODO: verify if making d 0 after profile change makes sense
            self.dMem = 0
            if(self.muMem > self.thresh*self.totalmem):
                print 'Threshold exceeded. Migrate!'
                if config.getboolean('migration', 'enabled') and config.getboolean('etcd', 'enabled') and config.getboolean('nova', 'enabled'):
                    # migrate here
                    migration.handle()

    def checkCpu(self, stealTime):
        self.getCpuUsage()

        # detect 1% shift
        self.KCpu = 0.005*100
        self.muCpu = self.alpha*self.cpuUsage + (1-self.alpha)*self.muCpu
        #print "muCpu: %f"%self.muCpu
        self.dCpu = self.dCpu+self.cpuUsage-(self.muCpu+self.KCpu)
        #print "dCpu: %f"%self.dCpu
        self.stdCpu.add(self.cpuUsage)
        # write smaller changes too because cpu usage fluctuates a lot
        H = (self.h-3)*self.stdCpu.standardDeviation()
        #print "H: %f"%H
        if(abs(self.dCpu) > H):
            print 'Cpu Profile Changed'
            self.updateEtcd()
            # TODO: verify if making d 0 after profile change makes sense
            self.dCpu = 0

        #check if migration required by looking at steal times
        for uuid in stealTime.keys():
            if stealTime[uuid] > 10:
                if uuid not in self.maybeMigrate.keys():
                    self.maybeMigrate[uuid] = 1
                else:
                    self.maybeMigrate[uuid] = self.maybeMigrate[uuid] + 1
                    if self.maybeMigrate[uuid] > 5:
                        print "Migrating due to CPU imbalance"
                        if config.getboolean('migration', 'enabled') and config.getboolean('etcd', 'enabled') and config.getboolean('nova', 'enabled'):
                            migration.handle()
                            break
            else:
                self.maybeMigrate[uuid] = 0


    def getCpuUsage(self):
        # get cpu usage
        stats = self.conn.getCPUStats(libvirt.VIR_NODE_CPU_STATS_ALL_CPUS, 0)
        totalTime = stats['kernel'] + stats['user'] + stats['idle'] + stats['iowait']
        busyTime = stats['kernel'] + stats['user']
        if self.prevBusyTime !=0 and (totalTime - self.prevTotalTime) !=0:
            self.cpuUsage = (busyTime - self.prevBusyTime)*100/float(totalTime - self.prevTotalTime)
        self.prevTotalTime = totalTime
        self.prevBusyTime = busyTime
        #print "cpuUsage: %f"%self.cpuUsage


    def logStats(self):
        debuglogger.debug('Host cpuUsage: %f', self.cpuUsage)
        debuglogger.debug('Host totalmem: %dMB', self.totalmem)
        debuglogger.debug('Host usedmem: %dMB', self.usedmem)
        debuglogger.debug('Host loadmem: %dMB', self.loadmem)
        #debuglogger.debug('Host mu: %f', self.muMem)
        #debuglogger.debug('Host d: %f', self.dMem)
        #debuglogger.debug('Host H: %f', H)

    def getVMLoad(self):
        pids = []
        memUsed = 0
        for fil in os.listdir('/var/run/libvirt/qemu/'):
            if fil.endswith('.pid'):
                pids.append(open('/var/run/libvirt/qemu/'+fil).read())
        for pid in pids:
            Rss = (int(open('/proc/'+pid+'/statm').readline().split()[1])
                       * PAGESIZE)
            memUsed += Rss/1024 # Mb
        debuglogger.debug("VM Load is: %dMB", memUsed)
        return memUsed

    def getAvailableMemory(self):
        line = open('/proc/meminfo').readlines()[2]
        return int(line.split()[1])/1024
