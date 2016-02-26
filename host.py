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
    data = deque([])
    n = 0
    s1 = 0
    s2 = 0

    def __init__(self, used):
        for i in range(20000):
            self.data.append(numpy.random.randint(used-250, used+250))
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
    mu = 0

    # threshold for migration
    thresh = 1
    totalmem = -1

    usedmem = -1

    loadmem = -1

    # accumulated deviation
    d = 0

    #slack factor
    K = 0

    #the design parameter
    h = 7

    def __init__(self, conn):
        self.conn = conn
        self.thresh = config.getfloat('migration', 'migration_thresh')
        stats = self.getMemoryStats()
        self.totalmem = stats['total']
        self.usedmem = stats['total'] - stats['free']
        self.loadmem = self.getLoadMem(stats, 0)
        self.mu = self.loadmem
        self.std = RunningStats(self.loadmem)
        self.updateEtcd()

    def updateEtcd(self):
        if config.getboolean('etcd', 'enabled'):
            etcdClient.write('/'+hostname+'/totalmem', self.totalmem)
            etcdClient.write('/'+hostname+'/loadmem', self.mu)


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
    def getLoadMem(self, stats, idleMemory):
        hypervisor_reserved = config.getint('monitor', 'hypervisor_reserved')
        vmLoad = self.getVMLoad()
        hypervisorLoad = stats['total'] - stats['free'] - (stats['buffers'] + stats['cached'])- vmLoad
        # hypervisor_extra ensures that atleast hypervisor_reserved memory is added towards host's load
        hypervisor_extra = max(hypervisorLoad-hypervisor_reserved, 0)
        debuglogger.debug("Hypervisor Load is %dMB", hypervisorLoad)
        #load = vmLoad + hypervisorLoad + 0.1*(stats['buffers']+stats['cached']) - idleMemory#TODO: modify 0.9
        load = (stats['total'] - self.getAvailableMemory()) + hypervisor_extra - idleMemory
        return load

    def monitor(self, idleMemory):
        self.checkMemory(idleMemory)
        self.checkCpu()

    def checkMemory(self, idleMemory):
        stats = self.getMemoryStats()
        self.totalmem = stats['total']
        # k is the slack factor which is equal to ∆/2 where ∆ is minimum shift to be detected
        # Here, we have taken ∆ as 0.1 i.e minimum 1% shift is to be detected
        self.K = 0.005*self.totalmem
        self.usedmem = stats['total'] - stats['free']
        # calculate moving average
        self.loadmem = self.getLoadMem(stats, idleMemory)
        self.mu = self.alpha*self.loadmem + (1-self.alpha)*self.mu
        # calcualte the deviation
        self.d = max(0, self.d+self.loadmem-(self.mu+self.K))
        self.std.add(self.loadmem)
        H = self.h*self.std.standardDeviation()
        self.logStats(H)
        if(self.d > H):
            print 'Profile Changed'
            self.updateEtcd()
            # TODO: verify if making d 0 after profile change makes sense
            self.d = 0
            if(self.mu > self.thresh*self.totalmem):
                print 'Threshold exceeded. Migrate!'
                if config.getboolean('migration', 'enabled') and config.getboolean('etcd', 'enabled') and config.getboolean('nova', 'enabled'):
                    # migrate here
                    migration.handle()
                    pass

    def checkCpu(self):
        pass

    def logStats(self, H):
        debuglogger.debug('Host totalmem: %dMB', self.totalmem)
        debuglogger.debug('Host usedmem: %dMB', self.usedmem)
        debuglogger.debug('Host loadmem: %dMB', self.loadmem)
        debuglogger.debug('Host mu: %f', self.mu)
        debuglogger.debug('Host d: %f', self.d)
        debuglogger.debug('Host H: %f', H)

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
