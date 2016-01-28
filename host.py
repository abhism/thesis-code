# coding=UTF-8

import libvirt
import math
from collections import deque
import numpy
import time
import etcd

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
        #print "Variance: " + str(var)
        #return math.sqrt(var)
        #start = time.time()
        dev = numpy.std(self.data)
        #end = time.time()
        print "std: " + str(dev)
        #print "time taken: " + str(end - start)
        return dev;


class Host:

    #the weight of moving average
    alpha = 0.1

    # the moving average
    mu = 0

    # threshold for migration
    thresh = 0.8
    totalMem = -1
    usedMem = -1

    # accumulated deviation
    d = 0

    #slack factor
    K = 0

    #the design parameter
    h = 7

    # TODO: This is to be replaced with the name nova uses to identify the compute nodes
    hostName = "someRandomValue"

    def __init__(self, conn):
        self.conn = conn
        stats = self.getMemoryStats()
        self.totalMem = stats['total']
        self.usedMem = self.getUsedMem(stats)
        self.mu = usedMem
        self.std = RunningStats(usedMem)

        #etcd
        self.etcdClient = etcd.Client(port=2379)
        self.updateEtcd()


    def updateEtcd(self):
        self.client.write('/'+self.hostName+'/totalMem', self.totalMem)
        self.client.write('/'+self.hostName+'/usedMem', self.mu)


    def getMemoryStats(self):
        stats = self.conn.getMemoryStats(libvirt.VIR_NODE_MEMORY_STATS_ALL_CELLS, 0)
        return self.toMb(stats)

    # Convert the stats to MB
    def toMb(self, stats):
        newStats = {}
        for key in stats.keys():
            newStats[key] = round(stats[key]/1024)
        return newStats

    # get used memory form statistics
    def getUsedMem(self, stats, correctionFactor):
        used = stats['total'] - stats['free'] - 0.9*(stats['buffers']+stats['cached']) - correctionFactor #TODO: modify 0.9
        return used

    def monitor(self, correctionFactor):
        self.checkMemory(correctionFactor)
        self.checkCpu()

    def checkMemory(self, correctionFactor):
        stats = self.getMemoryStats()
        self.totalMem = stats['total']
        # k is the slack factor which is equal to ∆/2 where ∆ is minimum shift to be detected
        # Here, we have taken ∆ as 0.1 i.e minimum 1% shift is to be detected
        self.K = 0.005*self.totalMem
        # calculate moving average
        self.usedMem = self.getUsedMem(stats, correctionFactor)
        print 'Used: '+ str(self.usedMem)
        self.mu = self.alpha*self.usedMem + (1-self.alpha)*self.mu
        # calcualte the deviation
        self.d = max(0, self.d+self.usedMem-(self.mu+self.K))
        print "mu: " + str(self.mu)
        print "d: " + str(self.d)
        self.std.add(used)
        H = self.h*self.std.standardDeviation()
        if(self.d > H):
            print 'Profile Changed'
            self.updateEtcd()
            if(self.mu > self.thresh*self.totalMem):
                print 'Threshold exceeded. Migrate!'

    def checkCpu(self):
        pass

